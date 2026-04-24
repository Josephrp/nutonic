#!/usr/bin/env python3
"""Build LandShift SFT dataset (temporal land-change captioning + grounding)."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lfm_vl_sft_dataset.caption_rules import landshift_caption
from lfm_vl_sft_dataset.change_instances import find_change_regions
from lfm_vl_sft_dataset.event_catalog import load_events_file, sample_land_change_locations
from lfm_vl_sft_dataset.grid import build_reference_grid
from lfm_vl_sft_dataset.hf_upload import upload_dataset_folder
from lfm_vl_sft_dataset.jsonl_format import write_jsonl
from lfm_vl_sft_dataset.pro_dataset_common import (
    TemporalPairFetchConfig,
    build_tile_specs,
    crop_or_pad_tile,
    downsample_rgb_and_mask,
    fetch_temporal_pair_for_event,
    make_pair_rows,
    save_pair_images,
    split_for_event,
    write_metadata,
)
from lfm_vl_sft_dataset.pro_prompts import (
    LANDSHIFT_CHANGE_CAPTION,
    LANDSHIFT_GROUNDING,
    SYSTEM_GEOSPATIAL_ANALYST,
    SYSTEM_OPTICAL_LIMITS,
)
from lfm_vl_sft_dataset.s2_rgb import stack_s2_bands_on_grid, stack_s2_rgb_on_grid
from lfm_vl_sft_dataset.temporal_stac import bbox_around_point

DEFAULT_HF_REPO = "NuTonic/landshift-sft-v1"


def _load_red_nir(item_dir: Path, *, grid) -> dict[str, np.ndarray]:
    try:
        bands, _ = stack_s2_bands_on_grid(
            item_dir,
            band_names=["red", "nir"],
            dst_crs=grid.crs,
            dst_transform=grid.transform,
            width=grid.width,
            height=grid.height,
        )
        return bands
    except Exception:
        bands, _ = stack_s2_bands_on_grid(
            item_dir,
            band_names=["red", "nir08"],
            dst_crs=grid.crs,
            dst_transform=grid.transform,
            width=grid.width,
            height=grid.height,
        )
        return bands


def _compute_ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    red_f = red.astype(np.float32, copy=False)
    nir_f = nir.astype(np.float32, copy=False)
    den = nir_f + red_f
    out = np.full_like(den, np.nan, dtype=np.float32)
    valid = np.isfinite(den) & np.isfinite(red_f) & np.isfinite(nir_f) & (np.abs(den) > 1e-6)
    out[valid] = (nir_f[valid] - red_f[valid]) / den[valid]
    return out


def _resolve_nir(bands: dict[str, np.ndarray]) -> np.ndarray:
    if "nir" in bands:
        return bands["nir"]
    if "nir08" in bands:
        return bands["nir08"]
    raise RuntimeError("No NIR band found (expected 'nir' or 'nir08').")


def main() -> int:
    p = argparse.ArgumentParser(description="Build LandShift SFT dataset.")
    p.add_argument(
        "--events",
        type=Path,
        default=None,
        help="Optional CSV/JSON events with event_id,lat,lon,event_date. If omitted, seeded locations are used.",
    )
    p.add_argument("--seeded-events", type=int, default=24, help="Used when --events is not provided.")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "landshift_sft",
    )
    p.add_argument(
        "--work-dir",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "landshift_sft_work",
    )
    p.add_argument("--max-events", type=int, default=0)
    p.add_argument("--bbox-half-km", type=float, default=5.0)
    p.add_argument("--pre-window-days", type=int, default=365)
    p.add_argument("--post-window-days", type=int, default=120)
    p.add_argument("--max-cloud-pct", type=float, default=30.0)
    p.add_argument("--stac-url", default="https://earth-search.aws.element84.com/v1")
    p.add_argument("--collection", default="sentinel-2-l2a")
    p.add_argument("--sentinel-mode", choices=("minimal", "full"), default="full")
    p.add_argument("--native-tile", type=int, default=512)
    p.add_argument("--stride", type=int, default=128)
    p.add_argument("--output-size", type=int, default=224)
    p.add_argument("--min-area-px", type=int, default=40)
    p.add_argument("--ndvi-delta-threshold", type=float, default=0.22)
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--upload-repo", default=DEFAULT_HF_REPO)
    p.add_argument("--hf-token", default=None)
    p.add_argument("--private-repo", action="store_true")
    args = p.parse_args()

    out_dir = args.out_dir.resolve()
    work_dir = args.work_dir.resolve()
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "metadata").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.events is not None:
        events = load_events_file(args.events, profile="land_use_change", source="events_file")
    else:
        events = sample_land_change_locations(args.seeded_events, seed=42)
    if args.max_events > 0:
        events = events[: args.max_events]
    if not events:
        print("No valid events were loaded.", file=sys.stderr)
        return 2

    fetch_cfg = TemporalPairFetchConfig(
        stac_url=args.stac_url,
        collection=args.collection,
        bbox_half_km=args.bbox_half_km,
        pre_window_days=args.pre_window_days,
        post_window_days=args.post_window_days,
        max_cloud_pct=args.max_cloud_pct,
        sentinel_mode=args.sentinel_mode,
        skip_existing=args.skip_existing,
        required_assets=["red", "green", "blue", "nir", "nir08", "visual", "thumbnail"],
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "nutonic-landshift-sft/1.0"})

    by_split: dict[str, list[dict]] = defaultdict(list)
    errors: list[str] = []
    built = 0
    for ev in events:
        pair = fetch_temporal_pair_for_event(
            event_id=ev.event_id,
            lat=ev.lat,
            lon=ev.lon,
            event_date=ev.event_date,
            work_root=work_dir,
            cfg=fetch_cfg,
            session=session,
        )
        if pair is None:
            errors.append(f"{ev.event_id}: no usable temporal pair")
            continue

        west, south, east, north = bbox_around_point(ev.lon, ev.lat, args.bbox_half_km)
        grid = build_reference_grid(
            west,
            south,
            east,
            north,
            resolution_m=10.0,
            lat_anchor=ev.lat,
            lon_anchor=ev.lon,
        )
        try:
            rgb_pre, _ = stack_s2_rgb_on_grid(
                pair.pre_item_dir,
                dst_crs=grid.crs,
                dst_transform=grid.transform,
                width=grid.width,
                height=grid.height,
            )
            rgb_post, _ = stack_s2_rgb_on_grid(
                pair.post_item_dir,
                dst_crs=grid.crs,
                dst_transform=grid.transform,
                width=grid.width,
                height=grid.height,
            )
            b_pre = _load_red_nir(pair.pre_item_dir, grid=grid)
            b_post = _load_red_nir(pair.post_item_dir, grid=grid)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{ev.event_id}: {e}")
            continue

        ndvi_pre = _compute_ndvi(b_pre["red"], _resolve_nir(b_pre))
        ndvi_post = _compute_ndvi(b_post["red"], _resolve_nir(b_post))
        ndvi_delta = np.abs(ndvi_post - ndvi_pre)
        change_mask = ((ndvi_delta > args.ndvi_delta_threshold) & np.isfinite(ndvi_delta)).astype(np.uint8)

        tile_specs = build_tile_specs(grid.height, grid.width, args.native_tile, args.stride)
        min_ds = max(1, int(args.min_area_px * args.output_size / args.native_tile))
        for ti, spec in enumerate(tile_specs):
            rgb_pre_tile = crop_or_pad_tile(
                rgb_pre,
                row_off=spec.row_off,
                col_off=spec.col_off,
                height=spec.height,
                width=spec.width,
                native_tile=args.native_tile,
                fill_value=0.0,
            )
            rgb_post_tile = crop_or_pad_tile(
                rgb_post,
                row_off=spec.row_off,
                col_off=spec.col_off,
                height=spec.height,
                width=spec.width,
                native_tile=args.native_tile,
                fill_value=0.0,
            )
            mask_tile = crop_or_pad_tile(
                change_mask,
                row_off=spec.row_off,
                col_off=spec.col_off,
                height=spec.height,
                width=spec.width,
                native_tile=args.native_tile,
                fill_value=0,
            )
            rgb_pre_small, mask_small = downsample_rgb_and_mask(
                rgb_pre_tile,
                mask_tile,
                output_size=args.output_size,
            )
            rgb_post_small, _ = downsample_rgb_and_mask(
                rgb_post_tile,
                mask_tile,
                output_size=args.output_size,
            )
            regions = find_change_regions(
                mask_small,
                min_area_px=min_ds,
                max_regions=20,
                label_name="land_transition",
            )
            transition_matrix = {"vegetation_shift": int((mask_small > 0).sum())} if regions else {}
            caption = landshift_caption(transition_matrix, regions)
            split = split_for_event(ev.event_id)
            stem = f"{ev.event_id}_t{ti:04d}"
            rel_pre, rel_post = save_pair_images(
                out_dir=out_dir,
                stem=stem,
                rgb_pre_hw3=rgb_pre_small,
                rgb_post_hw3=rgb_post_small,
            )
            metadata = {
                "event_id": ev.event_id,
                "profile": "landshift",
                "lat": ev.lat,
                "lon": ev.lon,
                "event_date": ev.event_date,
                "pre_scene": pair.pre_scene.item_id,
                "post_scene": pair.post_scene.item_id,
                "tile_index": ti,
                "tile_origin_native": [spec.row_off, spec.col_off],
                "bbox_wgs84": [west, south, east, north],
                "ndvi_delta_threshold": args.ndvi_delta_threshold,
                "regions": [
                    {"label": r.label, "bbox": list(r.bbox_xyxy), "area_px": r.area_px}
                    for r in regions
                ],
            }
            write_metadata(out_dir, stem, metadata)
            rows = make_pair_rows(
                split_id=split,
                image_paths=[rel_pre, rel_post],
                system_text=f"{SYSTEM_GEOSPATIAL_ANALYST} {SYSTEM_OPTICAL_LIMITS}",
                caption_prompt=LANDSHIFT_CHANGE_CAPTION.format(
                    date_t0=pair.pre_scene.datetime_iso[:10],
                    date_t1=pair.post_scene.datetime_iso[:10],
                ),
                caption_text=caption,
                grounding_prompt=LANDSHIFT_GROUNDING,
                regions=regions,
                image_size=args.output_size,
                metadata={"event_id": ev.event_id, "profile": "landshift", "tile_stem": stem},
            )
            for s, row in rows:
                by_split[s].append(row)
            built += 1

    for name in ("train", "validation", "test"):
        write_jsonl(out_dir / "data" / f"{name}.jsonl", by_split.get(name, []))
    (out_dir / "README.md").write_text(
        "# LandShift SFT Dataset\n\nTemporal Sentinel-2 image pairs with land-transition change rows.\n",
        encoding="utf-8",
    )
    print(
        f"Built LandShift tiles={built} rows(train={len(by_split['train'])}, "
        f"val={len(by_split['validation'])}, test={len(by_split['test'])})"
    )
    if errors:
        print("Errors:", file=sys.stderr)
        for e in errors[:50]:
            print(f"  {e}", file=sys.stderr)
    if not args.no_upload:
        upload_dataset_folder(
            out_dir,
            args.upload_repo,
            private=args.private_repo,
            token=args.hf_token,
        )
        print(f"Uploaded to https://huggingface.co/datasets/{args.upload_repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

