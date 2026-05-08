"""Helpers for ``run_lfm_vl_sft_orchestrator.py`` (HF selection, batch materialize, geo-jitter)."""

from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import requests

from download_geoguessr_poi_imagery import (
    collect_geolocated_candidates,
    default_datetime_window,
    download_poi_imagery_at_location,
    maximize_min_separation_for_count,
    select_pois,
)
from lfm_vl_sft_dataset.geo_jitter import sample_lat_lon_offset_m
from lfm_vl_sft_dataset.pipeline import iter_base_poi_dirs
from lfm_vl_sft_dataset.s2_rgb import poi_dir_has_sentinel_l2a


@dataclass
class HfSelectionConfig:
    dataset: str
    dataset_config: str | None
    split: str
    max_scan: int
    streaming: bool
    lat_keys: list[str]
    lon_keys: list[str]
    num_points: int
    min_separation_km: float
    auto_min_separation: bool
    auto_separation_hi_km: float
    seed: int


def select_hf_points(cfg: HfSelectionConfig) -> list[dict[str, Any]]:
    """Mirror ``download_geoguessr_poi_imagery`` candidate + selection logic."""
    candidates = collect_geolocated_candidates(
        cfg.dataset,
        cfg.dataset_config,
        cfg.split,
        cfg.lat_keys,
        cfg.lon_keys,
        cfg.streaming,
        cfg.max_scan,
    )
    if not candidates:
        raise RuntimeError(
            "No geolocated HF rows. Check dataset id, --max-scan, and lat/lon field names."
        )
    if cfg.num_points == 0:
        n_req = len(candidates)
    else:
        n_req = cfg.num_points
        if len(candidates) < n_req:
            raise RuntimeError(
                f"Need at least {n_req} geolocated candidates but only have {len(candidates)}. "
                "Increase --max-scan."
            )
    if cfg.auto_min_separation:
        _chosen_sep, points = maximize_min_separation_for_count(
            candidates,
            n_req,
            cfg.seed,
            cfg.auto_separation_hi_km,
        )
    else:
        points = select_pois(candidates, n_req, cfg.min_separation_km, cfg.seed)
    if not points:
        raise RuntimeError("Selection produced zero POIs.")
    if cfg.num_points != 0 and len(points) < n_req:
        raise RuntimeError(
            f"Selection produced only {len(points)} POI(s) (requested {n_req}). "
            "Try --auto-min-separation, increase --max-scan, or lower --min-separation-km."
        )
    return points


@dataclass
class BatchDownloadConfig:
    stac_url: str
    collection: str
    datetime_days: int
    bbox_km: float
    max_cloud_cover: float
    skip_existing: bool
    sentinel_mode: str
    no_mapbox: bool
    mapbox_zoom: float
    mapbox_size: int
    hf_dataset: str
    hf_split: str


def _asset_policy(sentinel_mode: str) -> tuple[frozenset[str], frozenset[str] | None]:
    optional_keys = frozenset(["product_metadata"])
    if sentinel_mode == "minimal":
        allow = frozenset(["thumbnail", "visual", "tileinfo_metadata", "granule_metadata"])
        return optional_keys, allow
    return optional_keys, None


def materialize_batch(
    simsat: Any,
    session: requests.Session,
    batch_dir: Path,
    slice_points: list[dict[str, Any]],
    global_start_index: int,
    dl: BatchDownloadConfig,
) -> list[str]:
    """Write ``poi_<6d>/`` trees under ``batch_dir`` (Sentinel + Mapbox + poi.json). Returns log notes."""
    notes: list[str] = []
    batch_dir.mkdir(parents=True, exist_ok=True)
    dt = default_datetime_window(dl.datetime_days)
    optional_keys, asset_allowlist = _asset_policy(dl.sentinel_mode)
    for j, pnt in enumerate(slice_points):
        gid = global_start_index + j
        poi_id = f"poi_{gid:06d}"
        poi_dir = batch_dir / poi_id
        lat, lon = float(pnt["latitude"]), float(pnt["longitude"])
        selection_block = {
            "strategy": "orchestrator_batch",
            "batch_dir": str(batch_dir),
            "global_index": gid,
            "index_in_batch": j,
        }
        download_poi_imagery_at_location(
            simsat,
            session,
            poi_dir,
            poi_id=poi_id,
            lat=lat,
            lon=lon,
            bbox_km=dl.bbox_km,
            datetime_range=dt,
            stac_url=dl.stac_url,
            collection=dl.collection,
            max_cloud_cover=dl.max_cloud_cover,
            skip_existing=dl.skip_existing,
            optional_keys=optional_keys,
            asset_allowlist=asset_allowlist,
            no_mapbox=dl.no_mapbox,
            mapbox_zoom=dl.mapbox_zoom,
            mapbox_size=dl.mapbox_size,
            hf_dataset=dl.hf_dataset,
            hf_split=dl.hf_split,
            hf_row_meta=pnt["raw"],
            sentinel_mode=dl.sentinel_mode,
            selection_block=selection_block,
            extra_poi_fields=None,
        )
        if not poi_dir_has_sentinel_l2a(poi_dir):
            rm_tree_quiet(poi_dir)
            notes.append(
                f"{poi_id}: dropped (no usable STAC/Sentinel assets under batch tree; see downloader errors above)."
            )
    return notes


def apply_geo_jitter_under_root(
    simsat: Any,
    session: requests.Session,
    root: Path,
    *,
    geo_variants: int,
    geo_max_offset_m: float,
    jitter_seed: int,
    dl: BatchDownloadConfig,
) -> list[str]:
    """
    For each base ``poi_<digits>`` under ``root``, add ``poi_<digits>_gNNN`` siblings (same contract as
    ``run_lfm_vl_sft_geo_jitter_pipeline``).
    """
    notes: list[str] = []
    if geo_variants <= 0:
        return notes
    optional_keys, asset_allowlist = _asset_policy(dl.sentinel_mode)
    for src_dir in iter_base_poi_dirs(root):
        data = json.loads((src_dir / "poi.json").read_text(encoding="utf-8"))
        lat0 = float(data["latitude"])
        lon0 = float(data["longitude"])
        bbox_km = float(data.get("bbox_km_half", dl.bbox_km))
        dt = str(data.get("datetime_query") or "").strip() or default_datetime_window(dl.datetime_days)
        hf_meta = data.get("hf_row_meta") or {}
        base_id = src_dir.name
        selection_block = {
            "strategy": "orchestrator_geo_jitter",
            "source_poi_id": base_id,
            "seed": jitter_seed,
            "geo_variants": geo_variants,
            "geo_max_offset_m": geo_max_offset_m,
        }
        for j in range(1, geo_variants + 1):
            new_id = f"{base_id}_g{j:03d}"
            new_dir = root / new_id
            if new_dir.exists():
                shutil.rmtree(new_dir)
            rng = random.Random(jitter_seed + hash(base_id) % 100_000 + j * 10_007)
            lat_j, lon_j, de, dn = sample_lat_lon_offset_m(lat0, lon0, rng, geo_max_offset_m)
            extra = {
                "source_poi_id": base_id,
                "geo_jitter": {
                    "variant_index": j,
                    "max_offset_m": geo_max_offset_m,
                    "delta_east_m": round(de, 2),
                    "delta_north_m": round(dn, 2),
                    "latitude_base": lat0,
                    "longitude_base": lon0,
                },
            }
            s_errs, s_warns, _st, _mb = download_poi_imagery_at_location(
                simsat,
                session,
                new_dir,
                poi_id=new_id,
                lat=lat_j,
                lon=lon_j,
                bbox_km=bbox_km,
                datetime_range=dt,
                stac_url=dl.stac_url,
                collection=dl.collection,
                max_cloud_cover=dl.max_cloud_cover,
                skip_existing=dl.skip_existing,
                optional_keys=optional_keys,
                asset_allowlist=asset_allowlist,
                no_mapbox=dl.no_mapbox,
                mapbox_zoom=dl.mapbox_zoom,
                mapbox_size=dl.mapbox_size,
                hf_dataset=dl.hf_dataset,
                hf_split=dl.hf_split,
                hf_row_meta=dict(hf_meta) if isinstance(hf_meta, dict) else {},
                sentinel_mode=dl.sentinel_mode,
                selection_block=selection_block,
                extra_poi_fields=extra,
            )
            notes.extend(f"{new_id}: {e}" for e in s_errs)
            notes.extend(f"{new_id} warn: {w}" for w in s_warns)
            if not poi_dir_has_sentinel_l2a(new_dir):
                rm_tree_quiet(new_dir)
                notes.append(f"{new_id}: removed incomplete directory (no Sentinel STAC assets).")
    return notes


def iter_batch_slices(points: list[dict[str, Any]], batch_size: int) -> Iterator[tuple[int, int, list[dict[str, Any]]]]:
    """Yield ``(batch_index, global_start_index, slice)``."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    off = 0
    bi = 0
    while off < len(points):
        sl = points[off : off + batch_size]
        yield bi, off, sl
        off += len(sl)
        bi += 1


def rm_tree_quiet(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
