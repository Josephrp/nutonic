#!/usr/bin/env python3
"""
Sample GeoGuessr-style Hugging Face rows that include WGS84 coordinates, then for
each point download Sentinel-2 L2A (Earth Search STAC) and Mapbox satellite static
imagery using the same HTTP/STAC logic as download_simsat_sources.py.

Candidates are subsampled for geographic spread: by default we require a minimum
great-circle distance between any two chosen POIs so nearby street-view locations
(e.g. same Sentinel-2 granule) are not selected together.

Context — refs/terramind-geogen-main:
  - TerraMesh samples carry geographic truth via zarr fields center_lon / center_lat
    when return_metadata=True (see src/terramesh.py, zarr_metadata_decoding).
  - Haversine scoring uses (lon, lat) order in src/geo_utils.py.
  - Error heatmaps bin Latitude / Longitude from CSV (scripts/plot_error_heatmap.py).

The popular HF dataset marcelomoreno26/geoguessr only exposes image + country label
(no coordinates). The default dataset here is stochastic/random_streetview_images_pano_v0.0.2
(GeoGuessr-inspired, MIT), which includes latitude and longitude per row.

Does not modify download_simsat_sources.py; loads it as a sibling module.

Usage:
  pip install -r data/scripts/requirements.txt
  python data/scripts/download_geoguessr_poi_imagery.py --out-dir data/downloads/geoguessr_poi
  # Many POIs (e.g. 120): use --auto-min-separation so spacing is maximized while still filling the count.
  python data/scripts/download_geoguessr_poi_imagery.py --num-points 120 --auto-min-separation --out-dir data/downloads/geoguessr_poi_120
  # Small smoke: --num-points 8 --max-scan 50_000
  # Use every geolocated row in the scan window: --num-points 0 --max-scan 0   (entire HF split; can take a long time)

End-to-end LFM-VL raw SFT (HF POIs → geo-jitter re-downloads → tiles + JSONL) is three stages:
  1) this script  2) ``data/scripts/run_lfm_vl_sft_geo_jitter_pipeline.py``  3) ``build_lfm_vl_sft_dataset.py`` (invoked by step 2).
  Geo-jitter runs only in step 2 (default ``--geo-variants 2``); step 3 never re-jitters coordinates.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests
from datasets import load_dataset
from pystac_client import Client

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from geo_nutonic import haversine_km

REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()
except ImportError:
    pass


def pairwise_min_distance_km(points: list[dict[str, Any]]) -> float | None:
    if len(points) < 2:
        return None
    best = float("inf")
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = haversine_km(
                points[i]["longitude"],
                points[i]["latitude"],
                points[j]["longitude"],
                points[j]["latitude"],
            )
            best = min(best, d)
    return best


def _haversine_km_matrix(
    lon1: np.ndarray,
    lat1: np.ndarray,
    lon2: np.ndarray,
    lat2: np.ndarray,
) -> np.ndarray:
    """Shapes (R,), (R,), (S,), (S,) -> (R, S) distances in km."""
    lon1r = np.radians(lon1)[:, np.newaxis]
    lat1r = np.radians(lat1)[:, np.newaxis]
    lon2r = np.radians(lon2)[np.newaxis, :]
    lat2r = np.radians(lat2)[np.newaxis, :]
    dlon = lon2r - lon1r
    dlat = lat2r - lat1r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.minimum(1.0, np.sqrt(a)))
    return 6371.0 * c


def select_spread_points_farthest_min(
    candidates: list[dict[str, Any]],
    k: int,
    min_separation_km: float,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """
    Pick up to k points so each new point is at least min_separation_km from all
    already chosen. Among feasible candidates, add the one whose minimum distance
    to the current set is largest (farthest-first), which tends to spread globally.
    Vectorized over the candidate pool for large N (e.g. binary-search auto separation).
    """
    if k <= 0 or not candidates:
        return []
    n = len(candidates)
    lons = np.array([float(c["longitude"]) for c in candidates], dtype=np.float64)
    lats = np.array([float(c["latitude"]) for c in candidates], dtype=np.float64)
    order = list(range(n))
    rng.shuffle(order)
    first = order[0]
    selected_idx: list[int] = [first]
    available = set(order[1:])
    while len(selected_idx) < k and available:
        rem = np.array(list(available), dtype=np.int64)
        sel = np.array(selected_idx, dtype=np.int64)
        d = _haversine_km_matrix(lons[rem], lats[rem], lons[sel], lats[sel])
        d_min = d.min(axis=1)
        ok = d_min >= min_separation_km
        if not np.any(ok):
            break
        rem_ok = rem[ok]
        d_ok = d_min[ok]
        pick = int(rem_ok[int(np.argmax(d_ok))])
        selected_idx.append(pick)
        available.discard(pick)
    return [candidates[i] for i in selected_idx]


def _load_simsat_module():
    here = Path(__file__).resolve().parent
    path = here / "download_simsat_sources.py"
    spec = importlib.util.spec_from_file_location("download_simsat_sources", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bbox_around_point(lon: float, lat: float, size_km: float) -> tuple[float, float, float, float]:
    """Match refs/SimSat-main SentinelProvider.get_bbox_around_lon_lat (km half-extent)."""
    r_km = 6371.0
    half = size_km / 2.0
    d_lat = math.degrees(half / r_km)
    cos_lat = math.cos(math.radians(lat))
    d_lon = math.degrees(half / (r_km * cos_lat)) if abs(cos_lat) > 1e-9 else d_lat
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


def parse_float_coord(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (float, int)):
        x = float(v)
    else:
        try:
            x = float(str(v).strip())
        except (TypeError, ValueError):
            return None
    if not math.isfinite(x):
        return None
    return x


def extract_lat_lon(row: dict[str, Any], lat_keys: list[str], lon_keys: list[str]) -> tuple[float, float] | None:
    lat = next((parse_float_coord(row[k]) for k in lat_keys if k in row), None)
    lon = next((parse_float_coord(row[k]) for k in lon_keys if k in row), None)
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def iter_geolocated_rows(
    dataset_id: str,
    dataset_config: str | None,
    split: str,
    lat_keys: list[str],
    lon_keys: list[str],
    streaming: bool,
    max_scan: int,
):
    if dataset_config is not None:
        ds = load_dataset(dataset_id, dataset_config, split=split, streaming=streaming)
    else:
        ds = load_dataset(dataset_id, split=split, streaming=streaming)
    scanned = 0
    for row in ds:
        scanned += 1
        if max_scan > 0 and scanned > max_scan:
            break
        coords = extract_lat_lon(row, lat_keys, lon_keys)
        if coords is None:
            continue
        lat, lon = coords
        yield {
            "latitude": lat,
            "longitude": lon,
            "raw": {k: row[k] for k in row if k != "image"},
        }


def collect_geolocated_candidates(
    dataset_id: str,
    dataset_config: str | None,
    split: str,
    lat_keys: list[str],
    lon_keys: list[str],
    streaming: bool,
    max_scan: int,
) -> list[dict[str, Any]]:
    return list(
        iter_geolocated_rows(
            dataset_id,
            dataset_config,
            split,
            lat_keys,
            lon_keys,
            streaming,
            max_scan,
        )
    )


def select_pois(
    candidates: list[dict[str, Any]],
    k: int,
    min_separation_km: float,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    if k <= 0:
        return []
    if min_separation_km <= 0:
        pool = list(candidates)
        rng.shuffle(pool)
        return pool[: min(k, len(pool))]
    return select_spread_points_farthest_min(candidates, k, min_separation_km, rng)


def _count_selected(
    candidates: list[dict[str, Any]],
    k: int,
    min_separation_km: float,
    seed: int,
) -> int:
    return len(select_pois(candidates, k, min_separation_km, seed))


def maximize_min_separation_for_count(
    candidates: list[dict[str, Any]],
    k: int,
    seed: int,
    hi_km: float,
    iterations: int = 36,
) -> tuple[float, list[dict[str, Any]]]:
    """
    Find the largest min-separation in [0, hi_km] such that farthest-min selection
    still returns k POIs (monotone: higher separation is harder). Requires len(candidates) >= k.
    """
    if len(candidates) < k:
        return 0.0, []
    if k <= 0:
        return 0.0, []
    if _count_selected(candidates, k, hi_km, seed) >= k:
        chosen = hi_km
    else:
        lo, hi_b = 0.0, hi_km
        for _ in range(iterations):
            mid = (lo + hi_b) / 2.0
            if _count_selected(candidates, k, mid, seed) >= k:
                lo = mid
            else:
                hi_b = mid
        chosen = lo
    points = select_pois(candidates, k, chosen, seed)
    if len(points) < k:
        points = select_pois(candidates, k, 0.0, seed)
        chosen = 0.0
    return chosen, points


def download_sentinel_for_bbox(
    simsat,
    session: requests.Session,
    *,
    stac_url: str,
    collection: str,
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    max_cloud: float,
    skip_existing: bool,
    optional_keys: frozenset[str],
    asset_allowlist: frozenset[str] | None,
    out_item_dir: Path,
) -> tuple[list[str], list[str], str | None]:
    """Returns (errors, warnings, stac_item_id or None)."""
    west, south, east, north = bbox
    client = Client.open(stac_url)
    search = client.search(
        collections=[collection],
        bbox=[west, south, east, north],
        datetime=datetime_range,
        max_items=1,
        query={"eo:cloud_cover": {"lt": max_cloud}},
    )
    items = list(search.items())
    if not items:
        return (["no STAC item for bbox"], [], None)
    item = max(items, key=lambda i: i.datetime)
    item_dir = out_item_dir / simsat._safe_filename(item.id)
    if asset_allowlist is not None:

        def pick_assets(it):
            return {k: v for k, v in it.assets.items() if k in asset_allowlist}

        class _Wrap:
            def __init__(self, wrapped, assets):
                self._w = wrapped
                self.assets = assets
                self.id = wrapped.id
                self.datetime = wrapped.datetime

        wrapped = _Wrap(item, pick_assets(item))
        errs, warns = simsat.download_sentinel_item_assets(
            session,
            wrapped,
            item_dir,
            skip_existing=skip_existing,
            optional_asset_keys=optional_keys,
        )
        return errs, warns, item.id

    errs, warns = simsat.download_sentinel_item_assets(
        session, item, item_dir, skip_existing=skip_existing, optional_asset_keys=optional_keys
    )
    return errs, warns, item.id


def download_poi_imagery_at_location(
    simsat: Any,
    session: requests.Session,
    poi_dir: Path,
    *,
    poi_id: str,
    lat: float,
    lon: float,
    bbox_km: float,
    datetime_range: str,
    stac_url: str,
    collection: str,
    max_cloud_cover: float,
    skip_existing: bool,
    optional_keys: frozenset[str],
    asset_allowlist: frozenset[str] | None,
    no_mapbox: bool,
    mapbox_zoom: float,
    mapbox_size: int,
    hf_dataset: str,
    hf_split: str,
    hf_row_meta: dict[str, Any],
    sentinel_mode: str,
    selection_block: dict[str, Any],
    extra_poi_fields: dict[str, Any] | None = None,
) -> tuple[list[str], list[str], str | None, dict[str, Any]]:
    """
    Download Sentinel-2 L2A (+ optional Mapbox) for one WGS84 point and write ``poi.json``.

    Used by ``download_geoguessr_poi_imagery`` main and by
    ``run_lfm_vl_sft_geo_jitter_pipeline`` for coordinate-jittered re-downloads.
    """
    poi_dir.mkdir(parents=True, exist_ok=True)
    bbox = bbox_around_point(lon, lat, bbox_km)

    s_errs, s_warns, stac_id = download_sentinel_for_bbox(
        simsat,
        session,
        stac_url=stac_url,
        collection=collection,
        bbox=bbox,
        datetime_range=datetime_range,
        max_cloud=max_cloud_cover,
        skip_existing=skip_existing,
        optional_keys=optional_keys,
        asset_allowlist=asset_allowlist,
        out_item_dir=poi_dir / "sentinel-2-l2a",
    )

    mapbox_path = poi_dir / "mapbox" / f"satellite-v9_{lon:.5f}_{lat:.5f}_z{mapbox_zoom}.png"
    mapbox_info: dict[str, Any]
    token = os.environ.get("MAPBOX_ACCESS_TOKEN")
    if no_mapbox:
        mapbox_info = {"skipped": True, "reason": "--no-mapbox"}
    elif not token:
        mapbox_info = {"skipped": True, "reason": "MAPBOX_ACCESS_TOKEN not set"}
    else:
        try:
            if skip_existing and mapbox_path.exists() and mapbox_path.stat().st_size > 0:
                mapbox_info = {"path": str(mapbox_path), "skipped": True}
            else:
                mapbox_path.parent.mkdir(parents=True, exist_ok=True)
                simsat.fetch_mapbox_static(
                    session,
                    token,
                    lon,
                    lat,
                    mapbox_zoom,
                    0.0,
                    0.0,
                    mapbox_size,
                    mapbox_size,
                    True,
                    mapbox_path,
                )
                mapbox_info = {"path": str(mapbox_path), "skipped": False}
        except Exception as e:  # noqa: BLE001
            mapbox_info = {"error": str(e)}
            s_errs.append(f"{poi_id} mapbox: {e}")

    doc: dict[str, Any] = {
        "poi_id": poi_id,
        "latitude": lat,
        "longitude": lon,
        "bbox_wgs84": list(bbox),
        "bbox_km_half": bbox_km,
        "hf_dataset": hf_dataset,
        "hf_split": hf_split,
        "hf_row_meta": hf_row_meta,
        "stac_item_id": stac_id,
        "datetime_query": datetime_range,
        "sentinel_mode": sentinel_mode,
        "mapbox": mapbox_info,
        "selection": selection_block,
    }
    if extra_poi_fields:
        doc.update(extra_poi_fields)
    (poi_dir / "poi.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return s_errs, s_warns, stac_id, mapbox_info


def default_datetime_window(days: int) -> str:
    end = time.time()
    start = end - days * 24 * 3600
    return f"{time.strftime('%Y-%m-%d', time.gmtime(start))}/{time.strftime('%Y-%m-%d', time.gmtime(end))}"


def main() -> int:
    p = argparse.ArgumentParser(
        description="Cache Sentinel + Mapbox imagery for a few GeoGuessr-style HF points."
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/downloads/geoguessr_poi"),
        help="Output root (per-point subfolders)",
    )
    p.add_argument(
        "--num-points",
        type=int,
        default=12,
        help="How many POIs to capture after geographic selection. Use 0 for all geolocated rows "
        "in the scan window (len(candidate pool), capped by --max-scan unless --max-scan 0).",
    )
    p.add_argument(
        "--min-separation-km",
        type=float,
        default=2200.0,
        help="Minimum great-circle distance between any two selected POIs. "
        "Use 0 to disable and take the first --num-points shuffled candidates.",
    )
    p.add_argument(
        "--auto-min-separation",
        action="store_true",
        help="Binary-search the largest min-separation in [0, --auto-separation-hi-km] that still "
        "yields --num-points POIs (needed for large counts, e.g. 120 on ~11k candidates).",
    )
    p.add_argument(
        "--auto-separation-hi-km",
        type=float,
        default=2200.0,
        help="Upper bound for --auto-min-separation search (default: same as prior fixed default).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for shuffling candidates before farthest-min selection.",
    )
    p.add_argument(
        "--dataset",
        default="stochastic/random_streetview_images_pano_v0.0.2",
        help="Hugging Face dataset id (must expose latitude/longitude or use --lat-field/--lon-field).",
    )
    p.add_argument(
        "--dataset-config",
        default=None,
        help="Config/subset name, e.g. default for marcelomoreno26/geoguessr (still needs coords).",
    )
    p.add_argument("--split", default="train")
    p.add_argument(
        "--no-streaming",
        action="store_true",
        help="Load the full split into memory (can download all media for image-heavy datasets). "
        "Default is streaming=True to avoid pulling street-view binaries.",
    )
    p.add_argument(
        "--max-scan",
        type=int,
        default=100_000,
        help="Max HF rows to scan when building the candidate pool. Use 0 to scan the entire split "
        "(can be very slow/large; streaming=True by default avoids pulling image binaries). "
        "Increase if selection finds too few POIs.",
    )
    p.add_argument(
        "--lat-field",
        action="append",
        default=[],
        help="Column for latitude (repeatable). Default: latitude lat y",
    )
    p.add_argument(
        "--lon-field",
        action="append",
        default=[],
        help="Column for longitude (repeatable). Default: longitude lon x",
    )
    p.add_argument("--bbox-km", type=float, default=5.0, help="Square bbox half-size in km (SimSat-style).")
    p.add_argument("--stac-url", default="https://earth-search.aws.element84.com/v1")
    p.add_argument("--collection", default="sentinel-2-l2a")
    p.add_argument("--datetime", default=None, help="STAC datetime interval (default: last 90 days).")
    p.add_argument("--datetime-days", type=int, default=90)
    p.add_argument("--max-cloud-cover", type=float, default=100.0)
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument(
        "--sentinel-mode",
        choices=("minimal", "full"),
        default="full",
        help="minimal: thumbnail, visual COG, small metadata; full: every STAC asset (all bands; very large).",
    )
    p.add_argument("--no-mapbox", action="store_true")
    p.add_argument("--mapbox-zoom", type=float, default=12.0)
    p.add_argument("--mapbox-size", type=int, default=1280)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    lat_keys = args.lat_field or ["latitude", "lat", "y"]
    lon_keys = args.lon_field or ["longitude", "lon", "x"]

    simsat = _load_simsat_module()
    dt = args.datetime or default_datetime_window(args.datetime_days)
    optional_keys = frozenset(["product_metadata"])

    minimal_assets = frozenset(
        ["thumbnail", "visual", "tileinfo_metadata", "granule_metadata"]
    )
    asset_allowlist: frozenset[str] | None = None
    if args.sentinel_mode == "minimal":
        asset_allowlist = minimal_assets

    out_root = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"Building candidate pool from Hugging Face (may take several minutes)…", flush=True)

    candidates = collect_geolocated_candidates(
        args.dataset,
        args.dataset_config,
        args.split,
        lat_keys,
        lon_keys,
        streaming=not args.no_streaming,
        max_scan=args.max_scan,
    )
    if not candidates:
        print(
            "No geolocated rows in scan window. Check --dataset / --lat-field / --lon-field / --max-scan.",
            file=sys.stderr,
        )
        return 2

    if args.num_points == 0:
        n_req = len(candidates)
        print(f"--num-points 0: using full candidate pool ({n_req} geolocated row(s))", flush=True)
    else:
        n_req = args.num_points
        if len(candidates) < n_req:
            print(
                f"Need at least {n_req} geolocated candidates but only have {len(candidates)}. "
                "Increase --max-scan or use a larger dataset.",
                file=sys.stderr,
            )
            return 2

    if args.auto_min_separation:
        chosen_sep, points = maximize_min_separation_for_count(
            candidates,
            n_req,
            args.seed,
            args.auto_separation_hi_km,
        )
        selection_strategy = "auto_max_min_distance"
        requested_sep = args.auto_separation_hi_km
    else:
        chosen_sep = args.min_separation_km
        points = select_pois(
            candidates,
            n_req,
            args.min_separation_km,
            args.seed,
        )
        selection_strategy = "farthest_min" if args.min_separation_km > 0 else "shuffle_head"
        requested_sep = args.min_separation_km

    p_min = pairwise_min_distance_km(points)

    if len(points) < n_req:
        print(
            f"Selection produced only {len(points)} POI(s) (requested {n_req}). "
            f"Candidates={len(candidates)}, effective_min_separation_km={chosen_sep}. "
            "Try --auto-min-separation, increase --max-scan, or lower --min-separation-km.",
            file=sys.stderr,
        )
        if not points:
            return 2

    if args.dry_run:
        print(
            f"candidates={len(candidates)} selected={len(points)} "
            f"selection={selection_strategy} effective_min_separation_km={chosen_sep} "
            f"(requested_cap_km={requested_sep}) seed={args.seed} "
            f"pairwise_min_km={p_min if p_min is not None else 'n/a'}",
            file=sys.stderr,
        )
        for i, pnt in enumerate(points):
            meta = json.dumps(pnt["raw"], ensure_ascii=True)
            print(f"poi_{i:04d}  lat={pnt['latitude']:.6f} lon={pnt['longitude']:.6f}  meta={meta}")
        return 0

    session = requests.Session()
    session.headers.update({"User-Agent": "nutonic-download-geoguessr-poi/1.0"})

    manifest_points: list[dict[str, Any]] = []
    all_errors: list[str] = []
    all_warnings: list[str] = []

    selection_block = {
        "strategy": selection_strategy,
        "effective_min_separation_km": chosen_sep,
        "requested_min_separation_km": requested_sep,
        "auto_min_separation": args.auto_min_separation,
        "seed": args.seed,
        "candidate_pool_size": len(candidates),
        "requested_num_points": n_req,
        "num_points_cli": args.num_points,
        "pairwise_min_km_all_pois": p_min,
    }

    for i, pnt in enumerate(points):
        lat, lon = pnt["latitude"], pnt["longitude"]
        poi_id = f"poi_{i:04d}"
        poi_dir = out_root / poi_id
        s_errs, s_warns, stac_id, mapbox_info = download_poi_imagery_at_location(
            simsat,
            session,
            poi_dir,
            poi_id=poi_id,
            lat=lat,
            lon=lon,
            bbox_km=args.bbox_km,
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
            hf_dataset=args.dataset,
            hf_split=args.split,
            hf_row_meta=pnt["raw"],
            sentinel_mode=args.sentinel_mode,
            selection_block=selection_block,
            extra_poi_fields=None,
        )
        all_errors.extend(s_errs)
        all_warnings.extend(s_warns)

        manifest_points.append(
            {
                "poi_id": poi_id,
                "latitude": lat,
                "longitude": lon,
                "stac_item_id": stac_id,
                "mapbox": mapbox_info,
                "sentinel_errors": s_errs,
                "sentinel_warnings": s_warns,
            }
        )

    meta_path = out_root / "geoguessr_poi_manifest.json"
    meta_path.write_text(
        json.dumps(
            {
                "dataset": args.dataset,
                "split": args.split,
                "num_points": len(points),
                "num_points_requested_cli": args.num_points,
                "num_points_effective_selection": n_req,
                "selection": {
                    "strategy": selection_strategy,
                    "effective_min_separation_km": chosen_sep,
                    "requested_min_separation_km": requested_sep,
                    "auto_min_separation": args.auto_min_separation,
                    "seed": args.seed,
                    "candidate_pool_size": len(candidates),
                    "pairwise_min_km": p_min,
                },
                "output": str(out_root),
                "datetime": dt,
                "points": manifest_points,
                "errors": all_errors,
                "warnings": all_warnings,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if all_warnings:
        print("Warnings:", file=sys.stderr)
        for w in all_warnings:
            print(f"  {w}", file=sys.stderr)
    if all_errors:
        print("Completed with errors:", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print(f"Wrote {len(points)} POI folder(s) under {out_root}")
    print(f"Manifest: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
