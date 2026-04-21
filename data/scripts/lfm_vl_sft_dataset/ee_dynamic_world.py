"""Fetch Dynamic World ``label`` from Google Earth Engine (aligned via reproject)."""

from __future__ import annotations

import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np


def _parse_scene_center(date_start: str, date_end: str) -> datetime:
    """UTC noon on the scene calendar day (``date_start``) or midpoint if range spans multiple days."""
    d0 = datetime.strptime(date_start.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    d1 = datetime.strptime(date_end.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if d1 <= d0:
        return d0 + timedelta(hours=12)
    mid = d0 + (d1 - d0) / 2.0
    return mid


def _symmetric_date_window(center: datetime, half_days: int) -> tuple[str, str]:
    """EE ``filterDate`` bounds: inclusive start date, **exclusive** end date string."""
    first = (center - timedelta(days=half_days)).date()
    last = (center + timedelta(days=half_days)).date()
    lo = first.isoformat()
    hi = (last + timedelta(days=1)).isoformat()
    return lo, hi


def iter_dynamic_world_date_windows(
    date_start: str,
    date_end: str,
    datetime_query_fallback: str,
) -> list[tuple[str, str, str]]:
    """
    EE ``filterDate`` windows to try (start, end exclusive, tag).

    Order: strict scene window, symmetric expansions around the scene center, then optional
    STAC ``datetime`` query span from ``poi.json`` when labels are sparse (e.g. high latitude).
    """
    out: list[tuple[str, str, str]] = [(date_start, date_end, "scene_window")]
    center = _parse_scene_center(date_start, date_end)
    for half in (7, 14, 30, 60, 120):
        lo, hi = _symmetric_date_window(center, half)
        out.append((lo, hi, f"symmetric_{half}d"))
    if datetime_query_fallback.strip():
        from lfm_vl_sft_dataset.stac_meta import ee_filter_dates_from_query

        qs, qe = ee_filter_dates_from_query(datetime_query_fallback)
        out.append((qs, qe, "stac_datetime_query_fallback"))
    return out


def _download_url_to_path(url: str, dest: Path, timeout: int = 600) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    tmp.replace(dest)


def _load_first_geotiff_from_zip(zpath: Path) -> Path:
    with zipfile.ZipFile(zpath, "r") as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".tif", ".tiff"))]
        if not names:
            raise RuntimeError(f"No GeoTIFF inside EE zip: {zpath}")
        member = names[0]
        out = zpath.with_suffix(".extracted.tif")
        out.write_bytes(zf.read(member))
        return out


def fetch_dynamic_world_label(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    date_start: str,
    date_end: str,
    dst_crs: str,
    dst_transform: tuple[float, float, float, float, float, float],
    width: int,
    height: int,
    datetime_query_fallback: str = "",
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Download Dynamic World ``label`` for the WGS84 rectangle and **reproject** to the
    reference grid (nearest). Requires ``earthengine-api`` and prior ``ee.Initialize()``.

    ``date_start`` / ``date_end`` are inclusive-exclusive ISO strings (EE ``filterDate``).
    If the strict scene-day window is empty, tries wider symmetric windows, then
    ``datetime_query_fallback`` (same ``datetime_query`` string stored on ``poi.json`` from STAC).
    """
    import ee
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject

    region = ee.Geometry.Rectangle([west, south, east, north], proj="EPSG:4326", geodesic=False)
    epsg = int(dst_crs.split(":")[-1])
    meta: dict[str, Any] = {"dw_collection": "GOOGLE/DYNAMICWORLD/V1"}
    ic = None
    n = 0
    for lo, hi, tag in iter_dynamic_world_date_windows(date_start, date_end, datetime_query_fallback):
        cand = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(region).filterDate(lo, hi)
        cand_n = cand.size().getInfo()
        meta[f"ee_try_{tag}"] = cand_n
        if cand_n > 0:
            ic = cand
            n = cand_n
            meta["dw_filter_window"] = tag
            meta["dw_filter_start"] = lo
            meta["dw_filter_end"] = hi
            meta["ee_image_count"] = n
            break
    if ic is None or n == 0:
        raise RuntimeError(
            f"No Dynamic World images for region {west:.4f},{south:.4f},{east:.4f},{north:.4f} "
            f"after trying scene window and wider date filters (original EE window {date_start} .. {date_end})."
        )
    label = ic.sort("system:time_start", False).first().select("label").byte()
    url = label.getDownloadURL(
        {
            "name": "dw_label",
            "crs": f"EPSG:{epsg}",
            "scale": 10,
            "region": region,
            "format": "GEO_TIFF",
        }
    )
    meta["download_url_host"] = url.split("/")[2] if "://" in url else ""

    with tempfile.TemporaryDirectory(prefix="nutonic_dw_") as td:
        raw = Path(td) / "dw_raw.zip"
        try:
            _download_url_to_path(url, raw)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Earth Engine getDownloadURL failed: {e}") from e

        sig = raw.read_bytes()[:4]
        if zipfile.is_zipfile(raw) or sig.startswith(b"PK"):
            tif = _load_first_geotiff_from_zip(raw)
        elif sig[:2] in (b"II", b"MM"):
            tif = raw.rename(raw.with_suffix(".tif"))
        else:
            tif = raw.rename(raw.with_suffix(".tif"))

        dst = np.empty((height, width), dtype=np.uint8)
        aff = Affine(*dst_transform)
        with rasterio.open(tif) as src:
            meta["src_shape"] = (src.height, src.width)
            meta["src_crs"] = str(src.crs)
            reproject(
                source=rasterio.band(src, 1),
                destination=dst,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=aff,
                dst_crs=dst_crs,
                resampling=Resampling.nearest,
                dst_nodata=255,
            )
    return dst, meta


def synthetic_label(width: int, height: int, *, seed: int = 0) -> np.ndarray:
    """Deterministic pseudo-label map for offline tests."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 9, size=(height, width), dtype=np.uint8)
