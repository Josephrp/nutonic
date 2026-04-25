#!/usr/bin/env python3
"""Build FloodPulse SFT dataset (inundation change captioning + grounding)."""

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

from lfm_vl_sft_dataset.caption_rules import FloodStats, floodpulse_caption
from lfm_vl_sft_dataset.change_instances import find_change_regions
from lfm_vl_sft_dataset.event_catalog import load_events_file
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
from lfm_vl_sft_dataset.pro_hub_readme import floodpulse_readme
from lfm_vl_sft_dataset.pro_prompts import (
    FLOODPULSE_CHANGE_CAPTION,
    FLOODPULSE_GROUNDING,
    SYSTEM_GEOSPATIAL_ANALYST,
    SYSTEM_OPTICAL_LIMITS,
)
from lfm_vl_sft_dataset.s2_rgb import stack_s2_bands_on_grid, stack_s2_rgb_on_grid
from lfm_vl_sft_dataset.spectral_indices import compute_mndwi
from lfm_vl_sft_dataset.temporal_stac import bbox_around_point

DEFAULT_HF_REPO = "NuTonic/floodpulse-sft-v1"


def main() -> int:
    p = argparse.ArgumentParser(description="Build FloodPulse SFT dataset.")
    p.add_argument("--events", type=Path, required=True, help="CSV/JSON with event_id,lat,lon,event_date")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "floodpulse_sft",
    )
    p.add_argument(
        "--work-dir",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "floodpulse_sft_work",
    )
    p.add_argument("--max-events", type=int, default=0)
    p.add_argument("--bbox-half-km", type=float, default=5.0)
    p.add_argument("--pre-window-days", type=int, default=120)
    p.add_argument("--post-window-days", type=int, default=60)
    p.add_argument("--max-cloud-pct", type=float, default=35.0)
    p.add_argument("--stac-url", default="https://earth-search.aws.element84.com/v1")
    p.add_argument("--collection", default="sentinel-2-l2a")
    p.add_argument(
        "--sentinel-mode",
        choices=("minimal", "full"),
        default="minimal",
        help="``minimal`` downloads only bands required by this script (recommended). ``full`` downloads all STAC assets (slow).",
    )
    p.add_argument("--native-tile", type=int, default=512)
    p.add_argument("--stride", type=int, default=128)
    p.add_argument("--output-size", type=int, default=224)
    p.add_argument("--min-area-px", type=int, default=40)
    p.add_argument("--mndwi-water-threshold", type=float, default=0.15)
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

    events = load_events_file(args.events, profile="flood", source="events_file")
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
        required_assets=["red", "green", "blue", "swir16", "visual", "thumbnail"],
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "nutonic-floodpulse-sft/1.0"})

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
            b_pre, _ = stack_s2_bands_on_grid(
                pair.pre_item_dir,
                band_names=["green", "swir16"],
                dst_crs=grid.crs,
                dst_transform=grid.transform,
                width=grid.width,
                height=grid.height,
            )
            b_post, _ = stack_s2_bands_on_grid(
                pair.post_item_dir,
                band_names=["green", "swir16"],
                dst_crs=grid.crs,
                dst_transform=grid.transform,
                width=grid.width,
                height=grid.height,
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{ev.event_id}: {e}")
            continue

        mndwi_pre = compute_mndwi(b_pre["green"], b_pre["swir16"])
        mndwi_post = compute_mndwi(b_post["green"], b_post["swir16"])
        water_pre = (mndwi_pre > args.mndwi_water_threshold) & np.isfinite(mndwi_pre)
        water_post = (mndwi_post > args.mndwi_water_threshold) & np.isfinite(mndwi_post)
        inundation = (water_post & (~water_pre)).astype(np.uint8)

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
                inundation,
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
                label_name="inundation",
            )
            inundated_px = int((mask_small > 0).sum())
            total_px = int(mask_small.size)
            stats = FloodStats(
                inundated_px=inundated_px,
                total_px=total_px,
                water_expansion_ratio=(float(inundated_px) / float(total_px)) if total_px > 0 else None,
            )
            caption = floodpulse_caption(regions, stats)
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
                "profile": "floodpulse",
                "lat": ev.lat,
                "lon": ev.lon,
                "event_date": ev.event_date,
                "pre_scene": pair.pre_scene.item_id,
                "post_scene": pair.post_scene.item_id,
                "tile_index": ti,
                "tile_origin_native": [spec.row_off, spec.col_off],
                "bbox_wgs84": [west, south, east, north],
                "mndwi_threshold": args.mndwi_water_threshold,
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
                caption_prompt=FLOODPULSE_CHANGE_CAPTION.format(
                    date_t0=pair.pre_scene.datetime_iso[:10],
                    date_t1=pair.post_scene.datetime_iso[:10],
                ),
                caption_text=caption,
                grounding_prompt=FLOODPULSE_GROUNDING,
                regions=regions,
                image_size=args.output_size,
                metadata={"event_id": ev.event_id, "profile": "floodpulse", "tile_stem": stem},
            )
            for s, row in rows:
                by_split[s].append(row)
            built += 1

    for name in ("train", "validation", "test"):
        write_jsonl(out_dir / "data" / f"{name}.jsonl", by_split.get(name, []))
    (out_dir / "README.md").write_text(
        floodpulse_readme(
            hub_repo_id=args.upload_repo,
            n_train=len(by_split["train"]),
            n_val=len(by_split["validation"]),
            n_test=len(by_split["test"]),
            n_tiles=built,
        ),
        encoding="utf-8",
    )
    print(
        f"Built FloodPulse tiles={built} rows(train={len(by_split['train'])}, "
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

