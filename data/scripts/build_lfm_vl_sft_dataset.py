#!/usr/bin/env python3
"""
Build LFM-VL satellite SFT dataset: Sentinel-2 RGB + Dynamic World labels →
downsampled PNG tiles + leap-finetune JSONL, optional Hugging Face Hub upload.

Prerequisites (full pipeline):
  pip install -r data/scripts/requirements.txt -r data/scripts/requirements-lfm-vl-dataset.txt
  Earth Engine: service account JSON (see ``lfm_vl_sft_dataset.ee_auth``) or ADC / ``earthengine authenticate``
  POI tree from download_geoguessr_poi_imagery.py (sentinel-2-l2a COGs per POI)

Smoke without EE:
  python data/scripts/build_lfm_vl_sft_dataset.py --poi-root <poi> --out-dir /tmp/out \\
    --synthetic-labels --max-pois 1 --no-upload

Optional on-chip views (flip + 90/180/270, same mask alignment):
  ... --image-aug
  ... --image-aug --image-aug-no-rotate

Optional QA overlays (one PNG per JSONL row, boxes match that row):
  ... --write-bbox-overlays
  ... --write-bbox-overlays --no-bbox-overlay-jsonl-key

Ephemeral / low-disk runs (large STAC COG trees):
  ... --stream-jsonl --prune-sentinel-after-poi
  # Optional: --prune-poi-mapbox-after-poi  # removes poi_*/mapbox/ when under --poi-root

Default Hub dataset: NuTonic/raw-sft-init (override with --upload-repo).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lfm_vl_sft_dataset.ee_auth import initialize_earth_engine
from lfm_vl_sft_dataset.hf_upload import upload_dataset_folder
from lfm_vl_sft_dataset.jsonl_format import append_jsonl_row, truncate_split_jsonl_files, write_jsonl
from lfm_vl_sft_dataset.prune_inputs import prune_poi_mapbox_cache, prune_sentinel_l2a
from lfm_vl_sft_dataset.pipeline import (
    PipelineConfig,
    discover_poi_dirs,
    filter_poi_dirs_max_base_pois,
    process_poi,
)

DEFAULT_HF_REPO = "NuTonic/raw-sft-init"


def _preflight_dataset_deps() -> bool:
    """Require rasterio, scipy, Pillow before touching POIs."""
    missing: list[str] = []
    for mod, label in (("rasterio", "rasterio"), ("scipy", "scipy"), ("PIL", "pillow")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(label)
    if missing:
        print(
            "Missing Python packages: "
            + ", ".join(missing)
            + ".\nInstall with:\n"
            "  pip install -r data/scripts/requirements.txt -r data/scripts/requirements-lfm-vl-dataset.txt\n"
            "(conda: conda install -c conda-forge rasterio scipy pillow)",
            file=sys.stderr,
        )
        return False
    return True

DATASET_README = """---
license: apache-2.0
task_categories:
  - image-text-to-text
language:
  - en
tags:
  - satellite
  - land-cover
  - lfm-vl
  - geospatial
pretty_name: NU-TONIC raw SFT init (satellite imagery + land-cover labels)
---

# NU-TONIC raw SFT init

**Satellite imagery** and aligned **land-cover** outputs packaged as **image–text** rows for fine-tuning LFM-VL (leap-finetune `vlm_sft` format). JSONL user prompts name the modality (satellite imagery vs. overhead context) where it matters.

## Provenance

- **Locations:** GeoGuessr-style POIs (default HF source: `stochastic/random_streetview_images_pano_v0.0.2`) via `download_geoguessr_poi_imagery.py`.
- **Optical:** multispectral optical COGs from a public STAC catalog, **blue/green/red** or **visual** preview, percentile-stretched to uint8.
- **Labels:** per-pixel land-cover raster from Earth Engine, **reprojected** to the same 10 m grid as the RGB stack, then tiled and **nearest-neighbor** downsampled with the mask.
- **Context:** optional geographic overhead still per POI (token-based static map API) under `mapbox_stills/`.
- **Rows:** global caption + grounding per tile of satellite imagery, plus **per–land-cover-class** caption (and optional grounding) when a class exceeds `--min-class-fraction`.
- **Downstream format:** `messages[]` with `image` + text, aligned with `refs/satellite-vlm` / VRSBench converter conventions.

## Layout

- `images/*.png` — RGB chips (downsampled, e.g. 224×224).
- `overlays/*.png` — optional bbox visualization per JSONL row (``--write-bbox-overlays``).
- `mapbox_stills/*.png` — overhead context still per POI (when API token set).
- `data/train.jsonl`, `data/validation.jsonl`, `data/test.jsonl` — splits hashed by `poi_id`.
- `metadata/*.json` — per-tile sidecars (coordinates, scene id, `land_cover_label_meta` counts/shapes only).

## Build

See `docs/scripts/SPEC-lfm-vl-sft-dataset.md` and `python data/scripts/build_lfm_vl_sft_dataset.py --help`.

## Licenses

Respect the **STAC** data provider terms, **Earth Engine** terms for label rasters, the **static map** provider ToS for optional stills, and the **MIT** HF pano dataset license for source coordinates.
"""


def main() -> int:
    p = argparse.ArgumentParser(description="Build S2 + Dynamic World LFM-VL SFT dataset and optional HF upload.")
    p.add_argument("--poi-root", type=Path, required=True, help="Root with poi_*/poi.json + sentinel-2-l2a/")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "lfm_vl_raw_sft_init",
        help="Output directory (images/, data/, metadata/, README.md)",
    )
    p.add_argument("--native-tile", type=int, default=512, help="Tile size in native 10 m pixels.")
    p.add_argument(
        "--stride",
        type=int,
        default=128,
        help="Sliding-window stride in native pixels (smaller ⇒ more tiles / more rows per POI).",
    )
    p.add_argument("--output-size", type=int, default=224, help="Square output image side after downsample.")
    p.add_argument("--min-area-px", type=int, default=50, help="Min connected-component area at native scale.")
    p.add_argument("--min-valid-fraction", type=float, default=0.35, help="Skip tiles with mostly invalid DW labels.")
    p.add_argument(
        "--max-pois",
        type=int,
        default=0,
        help="Cap **total** POI directories after sorting (0 = all). With geo-jitter names "
        "(`poi_NNNN_g###`), the first N sorted dirs are often all one base POI — use --max-base-pois instead.",
    )
    p.add_argument(
        "--max-base-pois",
        type=int,
        default=0,
        help="Cap **distinct base** POIs (`poi_0000`, `poi_0000_g001`, … share base `poi_0000`; 0 = no cap). "
        "Applied before --max-pois.",
    )
    p.add_argument("--synthetic-labels", action="store_true", help="Skip Earth Engine; random DW classes for tests.")
    p.add_argument("--no-grounding", action="store_true", help="Emit captioning JSONL rows only.")
    p.add_argument(
        "--no-mapbox-still",
        action="store_true",
        help="Do not fetch Mapbox Satellite still (otherwise needs MAPBOX_ACCESS_TOKEN).",
    )
    p.add_argument("--mapbox-zoom", type=float, default=12.0)
    p.add_argument("--mapbox-size", type=int, default=1280)
    p.add_argument("--no-mapbox-retina", action="store_true", help="Use 1x static image size instead of @2x.")
    p.add_argument(
        "--no-per-class-rows",
        action="store_true",
        help="Disable extra caption+grounding rows per Dynamic World class per tile.",
    )
    p.add_argument(
        "--no-per-class-grounding",
        action="store_true",
        help="Keep per-class captions but skip per-class grounding JSON rows.",
    )
    p.add_argument("--min-class-fraction", type=float, default=0.05, help="Min pixel fraction to emit a class row.")
    p.add_argument("--max-classes-per-tile", type=int, default=9, help="Cap classes considered per tile (by area).")
    p.add_argument(
        "--image-aug",
        action="store_true",
        help="Emit extra tile views: horizontal flip and 90°/180°/270° rotations (RGB+mask; fresh regions/bboxes).",
    )
    p.add_argument(
        "--image-aug-no-flip",
        action="store_true",
        help="With --image-aug, skip the horizontal-flip view.",
    )
    p.add_argument(
        "--image-aug-no-rotate",
        action="store_true",
        help="With --image-aug, skip r90/r180/r270 views (flip only if flip enabled).",
    )
    p.add_argument(
        "--write-bbox-overlays",
        action="store_true",
        help="For each JSONL row, also write overlays/*.png with the same boxes as that row (caption=all regions; per-class rows=that class).",
    )
    p.add_argument(
        "--no-bbox-overlay-jsonl-key",
        action="store_true",
        help="With --write-bbox-overlays, write PNGs only (do not add bbox_overlay_image to row dicts).",
    )
    p.add_argument("--bbox-overlay-line-width", type=int, default=2, help="Overlay rectangle stroke width in pixels.")
    p.add_argument("--no-upload", action="store_true", help="Skip Hugging Face upload.")
    p.add_argument("--upload-repo", default=DEFAULT_HF_REPO, help="HF dataset repo id (org/name).")
    p.add_argument(
        "--hf-token",
        default=None,
        help="Token for Hub upload (overrides HF_TOKEN / HUGGING_FACE_HUB_TOKEN for this run).",
    )
    p.add_argument("--private-repo", action="store_true", help="Create private dataset repo if missing.")
    p.add_argument("--stac-url", default="https://earth-search.aws.element84.com/v1")
    p.add_argument("--collection", default="sentinel-2-l2a")
    p.add_argument(
        "--ee-project",
        default=None,
        help="Earth Engine / GCP project id (e.g. radioshaq). Else EE_PROJECT / EARTHENGINE_PROJECT.",
    )
    p.add_argument(
        "--ee-service-account-key",
        type=Path,
        default=None,
        help="Path to service account JSON. Else EE_SERVICE_ACCOUNT_KEY_PATH or GOOGLE_APPLICATION_CREDENTIALS.",
    )
    p.add_argument(
        "--ee-service-account-email",
        default=None,
        help="Override client_email from JSON. Else EE_SERVICE_ACCOUNT_EMAIL.",
    )
    p.add_argument(
        "--prune-sentinel-after-poi",
        action="store_true",
        help="After each successful POI, delete that folder's sentinel-2-l2a/ COGs (frees most download disk). "
        "Skipped when the tree resolves outside --poi-root (e.g. symlinked base POI); use --prune-allow-external to override.",
    )
    p.add_argument(
        "--prune-poi-mapbox-after-poi",
        action="store_true",
        help="After each successful POI, delete poi_*/mapbox/ cache if it resolves under --poi-root.",
    )
    p.add_argument(
        "--prune-allow-external",
        action="store_true",
        help="Allow pruning paths that resolve outside --poi-root (dangerous with symlinked POIs).",
    )
    p.add_argument(
        "--stream-jsonl",
        action="store_true",
        help="Append JSONL rows after each POI instead of buffering all splits in RAM. "
        "Truncates data/{train,validation,test}.jsonl at job start; use a fresh --out-dir or expect overwrite of images/metadata by stem.",
    )
    p.add_argument(
        "--stream-jsonl-skip-init-truncate",
        action="store_true",
        help="With --stream-jsonl, do not truncate split JSONLs at startup (multi-batch orchestrator truncates once).",
    )
    args = p.parse_args()

    if not _preflight_dataset_deps():
        return 2

    if args.stream_jsonl_skip_init_truncate and not args.stream_jsonl:
        print("--stream-jsonl-skip-init-truncate requires --stream-jsonl", file=sys.stderr)
        return 2

    poi_root = args.poi_root.resolve()
    out_dir = args.out_dir.resolve()
    images_dir = out_dir / "images"
    meta_dir = out_dir / "metadata"
    data_dir = out_dir / "data"
    images_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    if args.write_bbox_overlays:
        (out_dir / "overlays").mkdir(parents=True, exist_ok=True)

    cfg = PipelineConfig(
        stac_url=args.stac_url,
        collection=args.collection,
        native_tile=args.native_tile,
        stride=args.stride,
        output_size=args.output_size,
        min_area_px=args.min_area_px,
        min_valid_fraction=args.min_valid_fraction,
        include_grounding=not args.no_grounding,
        synthetic_labels=args.synthetic_labels,
        fetch_mapbox_still=not args.no_mapbox_still,
        mapbox_zoom=args.mapbox_zoom,
        mapbox_size=args.mapbox_size,
        mapbox_retina=not args.no_mapbox_retina,
        per_class_caption_rows=not args.no_per_class_rows,
        per_class_grounding_rows=not args.no_per_class_grounding,
        min_class_fraction=args.min_class_fraction,
        max_classes_per_tile=args.max_classes_per_tile,
        image_aug=args.image_aug,
        image_aug_hflip=args.image_aug and not args.image_aug_no_flip,
        image_aug_rot90=args.image_aug and not args.image_aug_no_rotate,
        write_bbox_overlays=args.write_bbox_overlays,
        bbox_overlay_in_jsonl=args.write_bbox_overlays and not args.no_bbox_overlay_jsonl_key,
        bbox_overlay_line_width=max(1, int(args.bbox_overlay_line_width)),
    )

    all_poi_dirs = discover_poi_dirs(poi_root)
    if args.max_base_pois > 0:
        poi_dirs = filter_poi_dirs_max_base_pois(all_poi_dirs, args.max_base_pois)
    else:
        poi_dirs = list(all_poi_dirs)
    if args.max_pois > 0:
        if args.max_base_pois == 0 and any(re.fullmatch(r"poi_\d+_g\d{3}", d.name) for d in all_poi_dirs):
            print(
                "build_lfm_vl_sft_dataset: with `poi_NNNN_g###` geo-jitter folders, "
                "`--max-pois` limits **sorted directory count** (not three separate map locations). "
                "Prefer `--max-base-pois 3` to keep all `g###` variants for the first three bases.",
                file=sys.stderr,
            )
        poi_dirs = poi_dirs[: args.max_pois]

    print(f"Processing {len(poi_dirs)} POI folder(s) under {poi_root}", flush=True)
    if args.stream_jsonl and not args.stream_jsonl_skip_init_truncate:
        truncate_split_jsonl_files(data_dir)
        print("Streaming JSONL: truncated data/train.jsonl, data/validation.jsonl, data/test.jsonl", flush=True)

    if not args.synthetic_labels:
        try:
            info = initialize_earth_engine(
                project=args.ee_project,
                service_account_key=args.ee_service_account_key,
                service_account_email=args.ee_service_account_email,
            )
            print(f"Earth Engine: {info}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(
                "Earth Engine init failed. Options:\n"
                "  • Service account: set EE_SERVICE_ACCOUNT_KEY_PATH or --ee-service-account-key to JSON, "
                "and EE_PROJECT or --ee-project (see https://developers.google.com/earth-engine/guides/service_account )\n"
                "  • ADC: gcloud auth application-default login or GOOGLE_APPLICATION_CREDENTIALS\n"
                "  • Or use --synthetic-labels for offline smoke.\n"
                f"  Error: {e}",
                file=sys.stderr,
            )
            return 2

    by_split: dict[str, list[dict]] = defaultdict(list)
    split_counts: dict[str, int] = defaultdict(int)
    errors: list[str] = []
    prune_notes: list[str] = []

    for d in poi_dirs:
        try:
            rows = process_poi(d, out_dir, cfg)
            if args.stream_jsonl:
                for split, row in rows:
                    append_jsonl_row(data_dir / f"{split}.jsonl", row)
                    split_counts[split] += 1
            else:
                for split, row in rows:
                    by_split[split].append(row)
            if args.prune_sentinel_after_poi or args.prune_poi_mapbox_after_poi:
                if args.prune_sentinel_after_poi:
                    ok, reason = prune_sentinel_l2a(
                        d,
                        poi_root,
                        allow_external=args.prune_allow_external,
                    )
                    if not ok and reason != "no_sentinel_dir":
                        prune_notes.append(f"{d.name} sentinel: {reason}")
                if args.prune_poi_mapbox_after_poi:
                    ok_m, reason_m = prune_poi_mapbox_cache(
                        d,
                        poi_root,
                        allow_external=args.prune_allow_external,
                    )
                    if not ok_m and reason_m != "no_mapbox_dir":
                        prune_notes.append(f"{d.name} mapbox: {reason_m}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{d.name}: {e}")

    (out_dir / "README.md").write_text(DATASET_README, encoding="utf-8")

    if args.stream_jsonl:
        print(f"Wrote images under {images_dir}")
        if args.write_bbox_overlays:
            print(f"Wrote bbox overlays under {out_dir / 'overlays'}")
        print(
            f"Wrote JSONL under {data_dir} (train={split_counts['train']}, "
            f"val={split_counts['validation']}, test={split_counts['test']}) [streamed]",
            flush=True,
        )
    else:
        for name, key in (("train", "train"), ("validation", "validation"), ("test", "test")):
            write_jsonl(data_dir / f"{name}.jsonl", by_split.get(key, []))

        print(f"Wrote images under {images_dir}")
        if args.write_bbox_overlays:
            print(f"Wrote bbox overlays under {out_dir / 'overlays'}")
        print(
            f"Wrote JSONL under {data_dir} (train={len(by_split['train'])}, "
            f"val={len(by_split['validation'])}, test={len(by_split['test'])})",
            flush=True,
        )

    if prune_notes:
        print("Prune notes:", file=sys.stderr)
        for n in prune_notes:
            print(f"  {n}", file=sys.stderr)
    if errors:
        print("Errors:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)

    if args.no_upload:
        if args.upload_repo != DEFAULT_HF_REPO:
            print(
                "Note: --no-upload is set; Hugging Face upload was skipped (--upload-repo ignored).",
                file=sys.stderr,
            )
    else:
        tok = (args.hf_token or "").strip() or os.environ.get("HF_TOKEN") or os.environ.get(
            "HUGGING_FACE_HUB_TOKEN"
        )
        if not (tok or "").strip():
            print(
                "Upload failed: no token. Set HF_TOKEN or HUGGING_FACE_HUB_TOKEN, or pass --hf-token, "
                "or use --no-upload to skip.",
                file=sys.stderr,
            )
            return 1
        try:
            upload_dataset_folder(
                out_dir,
                args.upload_repo,
                private=args.private_repo,
                token=args.hf_token,
            )
            print(f"Uploaded to https://huggingface.co/datasets/{args.upload_repo}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"Upload failed: {e}", file=sys.stderr)
            return 1

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
