#!/usr/bin/env python3
"""
Merge base GeoGuessr POI folders with **geo-jittered** re-downloads, then run
``build_lfm_vl_sft_dataset.py`` on the merged tree.

For each ``poi_NNNN`` under ``--source-poi-root``, this script:

1. Links or copies the base folder into ``--merged-poi-root`` (same ``poi_id``).
2. Creates ``poi_NNNN_g001``, ``poi_NNNN_g002``, … with **new** lat/lon (meters-scale
   jitter), re-runs STAC Sentinel-2 + optional Mapbox download like the initial
   ``download_geoguessr_poi_imagery.py`` step, then writes ``poi.json``.
3. Invokes ``build_lfm_vl_sft_dataset.py``, forwarding **all unknown CLI flags**
   (place build options after the wrapper flags), e.g. ``--out-dir … --no-upload``, ``--image-aug``, or
   ``--stream-jsonl --prune-sentinel-after-poi`` for low ephemeral disk.

By default ``--geo-variants`` is **2** (two jittered folders per base ``poi_NNNN``). Pass ``--geo-variants 0`` to only merge/copy bases and run the builder (no extra STAC downloads).

Example::

  python data/scripts/run_lfm_vl_sft_geo_jitter_pipeline.py \\
    --source-poi-root data/downloads/geoguessr_poi_3 \\
    --merged-poi-root data/downloads/geoguessr_poi_3_geo_merged \\
    --geo-max-offset-m 350 --seed 7 \\
    --out-dir data/downloads/lfm_vl_geo_jitter_out \\
    --max-base-pois 3 --no-upload \\
    --ee-project radioshaq --ee-service-account-key radioshaq-0c20df7b3f9b.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import requests

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from download_geoguessr_poi_imagery import (  # noqa: E402
    _load_simsat_module,
    default_datetime_window,
    download_poi_imagery_at_location,
)
from lfm_vl_sft_dataset.geo_jitter import sample_lat_lon_offset_m  # noqa: E402
from lfm_vl_sft_dataset.pipeline import iter_base_poi_dirs  # noqa: E402

_BUILD_SCRIPT = _SCRIPTS / "build_lfm_vl_sft_dataset.py"


def _link_or_copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            shutil.rmtree(dst)
    if os.name == "posix":
        try:
            dst.symlink_to(src.resolve(), target_is_directory=True)
            return
        except OSError:
            pass
    shutil.copytree(src, dst)


def _asset_policy(sentinel_mode: str) -> tuple[frozenset[str], frozenset[str] | None]:
    optional_keys = frozenset(["product_metadata"])
    if sentinel_mode == "minimal":
        allow = frozenset(["thumbnail", "visual", "tileinfo_metadata", "granule_metadata"])
        return optional_keys, allow
    return optional_keys, None


def main() -> int:
    p = argparse.ArgumentParser(
        description="Geo-jitter POI coordinates, re-download Sentinel/Mapbox, merge POI tree, run LFM-VL dataset build.",
    )
    p.add_argument("--source-poi-root", type=Path, required=True, help="Existing poi_NNNN trees from download_geoguessr_poi_imagery.")
    p.add_argument(
        "--merged-poi-root",
        type=Path,
        required=True,
        help="Output folder containing base + jittered POI dirs for the build step.",
    )
    p.add_argument(
        "--geo-variants",
        type=int,
        default=2,
        help="Extra jittered POI folders per base poi_NNNN (g001, g002, …). Re-downloads Sentinel/Mapbox at offset coords. "
        "Use 0 for merge+build only (no geo-jitter downloads).",
    )
    p.add_argument(
        "--geo-max-offset-m",
        type=float,
        default=300.0,
        help="Max horizontal offset radius (meters) for jittered lat/lon (uniform disk).",
    )
    p.add_argument("--seed", type=int, default=42, help="RNG seed for jitter draws.")
    p.add_argument("--stac-url", default="https://earth-search.aws.element84.com/v1")
    p.add_argument("--collection", default="sentinel-2-l2a")
    p.add_argument("--max-cloud-cover", type=float, default=100.0)
    p.add_argument("--skip-existing", action="store_true", help="Skip Sentinel/Mapbox assets when already present.")
    p.add_argument(
        "--sentinel-mode",
        choices=("minimal", "full"),
        default=None,
        help="Override Sentinel asset set for jittered downloads only (default: inherit from base poi.json).",
    )
    p.add_argument("--no-mapbox", action="store_true", help="Skip Mapbox fetch for jittered POIs.")
    p.add_argument("--mapbox-zoom", type=float, default=12.0)
    p.add_argument("--mapbox-size", type=int, default=1280)
    p.add_argument(
        "--max-base-pois",
        type=int,
        default=0,
        help="Cap base POI folders processed (0 = all poi_NNNN under source).",
    )
    args, build_argv = p.parse_known_args()

    source = args.source_poi_root.resolve()
    merged = args.merged_poi_root.resolve()
    merged.mkdir(parents=True, exist_ok=True)

    base_dirs = iter_base_poi_dirs(source)
    if args.max_base_pois > 0:
        base_dirs = base_dirs[: args.max_base_pois]
    if not base_dirs:
        print(f"No base poi_NNNN folders under {source}", file=sys.stderr)
        return 2

    simsat = _load_simsat_module()
    session = requests.Session()
    session.headers.update({"User-Agent": "nutonic-run-lfm-vl-sft-geo-jitter/1.0"})

    geo_n = max(0, args.geo_variants)
    if geo_n == 0:
        print(
            "run_lfm_vl_sft_geo_jitter_pipeline: --geo-variants 0 → no jittered re-downloads; "
            "only linking/copying base POIs then running the dataset build.",
            flush=True,
        )
    dl_errors: list[str] = []
    dl_warnings: list[str] = []

    for src_dir in base_dirs:
        base_id = src_dir.name
        dst_base = merged / base_id
        _link_or_copy_tree(src_dir, dst_base)

        data = json.loads((src_dir / "poi.json").read_text(encoding="utf-8"))
        lat0 = float(data["latitude"])
        lon0 = float(data["longitude"])
        bbox_km = float(data.get("bbox_km_half", 5.0))
        dt = str(data.get("datetime_query") or "").strip()
        if not dt:
            dt = default_datetime_window(90)

        hf_ds = str(data.get("hf_dataset", ""))
        hf_split = str(data.get("hf_split", "train"))
        hf_meta = data.get("hf_row_meta") or {}
        sentinel_mode = args.sentinel_mode or str(data.get("sentinel_mode", "full"))
        optional_keys, asset_allowlist = _asset_policy(sentinel_mode)

        selection_block = {
            "strategy": "geo_jitter_pipeline",
            "source_poi_id": base_id,
            "seed": args.seed,
            "geo_variants": geo_n,
            "geo_max_offset_m": args.geo_max_offset_m,
        }

        for j in range(1, geo_n + 1):
            new_id = f"{base_id}_g{j:03d}"
            new_dir = merged / new_id
            if new_dir.exists():
                shutil.rmtree(new_dir)
            rng = random.Random(args.seed + hash(base_id) % 100_000 + j * 10_007)
            lat_j, lon_j, de, dn = sample_lat_lon_offset_m(lat0, lon0, rng, args.geo_max_offset_m)
            extra = {
                "source_poi_id": base_id,
                "geo_jitter": {
                    "variant_index": j,
                    "max_offset_m": args.geo_max_offset_m,
                    "delta_east_m": round(de, 2),
                    "delta_north_m": round(dn, 2),
                    "latitude_base": lat0,
                    "longitude_base": lon0,
                },
            }
            s_errs, s_warns, _stac_id, _mb = download_poi_imagery_at_location(
                simsat,
                session,
                new_dir,
                poi_id=new_id,
                lat=lat_j,
                lon=lon_j,
                bbox_km=bbox_km,
                datetime_range=dt,
                stac_url=args.stac_url,
                collection=args.collection,
                max_cloud_cover=args.max_cloud_cover,
                skip_existing=args.skip_existing,
                optional_keys=optional_keys,
                asset_allowlist=asset_allowlist,
                no_mapbox=args.no_mapbox,
                mapbox_zoom=args.mapbox_zoom,
                mapbox_size=args.mapbox_size,
                hf_dataset=hf_ds,
                hf_split=hf_split,
                hf_row_meta=dict(hf_meta) if isinstance(hf_meta, dict) else {},
                sentinel_mode=sentinel_mode,
                selection_block=selection_block,
                extra_poi_fields=extra,
            )
            dl_errors.extend(f"{new_id}: {e}" for e in s_errs)
            dl_warnings.extend(f"{new_id}: {w}" for w in s_warns)

    cmd = [sys.executable, str(_BUILD_SCRIPT), "--poi-root", str(merged), *build_argv]
    print("Running:", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd)
    if dl_warnings:
        print("Geo-jitter download warnings:", file=sys.stderr)
        for w in dl_warnings:
            print(f"  {w}", file=sys.stderr)
    if dl_errors:
        print("Geo-jitter download errors:", file=sys.stderr)
        for e in dl_errors:
            print(f"  {e}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
