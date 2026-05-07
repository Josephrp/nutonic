"""Google Earth Engine Dynamic World label fetch for Patagonia eval (aligned chip).

Uses ``lfm_vl_sft_dataset.ee_dynamic_world.fetch_dynamic_world_label`` after ``ee.Initialize()``.
The output grid matches the STAC still footprint: WGS84 bbox from ``bbox_around_point`` (same
half-km as STAC stills), reprojected to **Web Mercator (EPSG:3857)** with an affine that exactly
covers that bbox at ``width``×``height`` pixels — same dimensions as the RGB/SCL eval chip.

Environment (typical):
- Authenticate Earth Engine (``earthengine authenticate`` or service-account JSON).
- Set one of: ``EE_PROJECT_ID``, ``GOOGLE_CLOUD_PROJECT``, ``GEE_PROJECT`` for ``ee.Initialize(project=...)``.
  If unset, ``ee.Initialize()`` is attempted with application default credentials.

This module is optional: callers should catch failures and fall back to SCL-derived fractions.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_SCRIPTS = REPO_ROOT / "data" / "scripts"


def _ensure_data_scripts_path() -> None:
    import sys

    if str(_DATA_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_DATA_SCRIPTS))


def ee_project_id() -> str | None:
    for key in ("EE_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "GEE_PROJECT", "EARTHENGINE_PROJECT"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return None


def initialize_earth_engine() -> dict[str, Any]:
    """Idempotent ``ee.Initialize``; returns diagnostics."""
    import ee

    diag: dict[str, Any] = {}
    try:
        ee.Number(1).getInfo()
        diag["mode"] = "already_initialized"
        return diag
    except Exception:
        pass
    proj = ee_project_id()
    if proj:
        ee.Initialize(project=proj)
        diag["mode"] = "project"
        diag["project"] = proj
    else:
        ee.Initialize()
        diag["mode"] = "default_credentials"
    return diag


def wgs84_bbox_half_km(lon: float, lat: float, bbox_half_km: float) -> tuple[float, float, float, float]:
    _ensure_data_scripts_path()
    from stac_reference_still import bbox_around_point

    return bbox_around_point(float(lon), float(lat), float(bbox_half_km))


def chip_transform_web_mercator(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    width: int,
    height: int,
) -> tuple[str, tuple[float, float, float, float, float, float]]:
    """Return ``("EPSG:3857", (a,b,c,d,e,f))`` affine covering WGS84 bounds at pixel resolution."""
    from rasterio.transform import from_bounds
    from rasterio.warp import transform_bounds

    xmin, ymin, xmax, ymax = transform_bounds(
        "EPSG:4326",
        "EPSG:3857",
        west,
        south,
        east,
        north,
        densify_pts=21,
    )
    aff = from_bounds(xmin, ymin, xmax, ymax, int(width), int(height))
    return "EPSG:3857", tuple(float(x) for x in aff[:6])


def stac_meta_to_ee_filter_dates(meta: dict[str, Any] | None, *, fallback_query: str = "") -> tuple[str, str, str]:
    """EE ``filterDate`` bounds (start inclusive, end **exclusive**) from STAC item datetime."""
    dt_s = ""
    if isinstance(meta, dict):
        raw = meta.get("datetime")
        if raw is not None:
            dt_s = str(raw).strip()
    if not dt_s and fallback_query.strip():
        _ensure_data_scripts_path()
        from lfm_vl_sft_dataset.stac_meta import ee_filter_dates_from_query

        lo, hi = ee_filter_dates_from_query(fallback_query)
        return lo, hi, "stac_datetime_query_fallback"
    if not dt_s:
        raise ValueError("stac_meta missing datetime and no fallback_query")
    # Parse ISO8601; use UTC calendar day window [day, day+1)
    if dt_s.endswith("Z"):
        dt_s = dt_s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(dt_s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unparseable STAC datetime: {dt_s!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    day = dt.astimezone(timezone.utc).date()
    start = day.isoformat()
    end = (day + timedelta(days=1)).isoformat()
    return start, end, "stac_item_day"


def fetch_dynamic_world_chip(
    lat: float,
    lon: float,
    *,
    width_px: int,
    height_px: int,
    bbox_half_km: float,
    stac_meta: dict[str, Any] | None = None,
    datetime_query_fallback: str = "",
) -> tuple[np.ndarray | None, dict[str, Any]]:
    """
    Return ``(label_uint8_hw_or_none, meta)`` where labels are 0–8 Dynamic World classes and 255=nodata.

    On any failure (import, auth, empty collection, network), returns ``(None, {"ok": False, ...})``.
    """
    meta_out: dict[str, Any] = {"ok": False, "source": "patagonia_eval_dynamic_world"}
    try:
        _ensure_data_scripts_path()
        from lfm_vl_sft_dataset.ee_dynamic_world import fetch_dynamic_world_label
    except ImportError as exc:
        meta_out["reason"] = "import_error"
        meta_out["error"] = f"{type(exc).__name__}: {exc}"
        return None, meta_out

    west, south, east, north = wgs84_bbox_half_km(lon, lat, bbox_half_km)
    meta_out["wgs84_bounds"] = {"west": west, "south": south, "east": east, "north": north}
    try:
        lo, hi, tag = stac_meta_to_ee_filter_dates(stac_meta, fallback_query=datetime_query_fallback)
        meta_out["ee_filter"] = {"start": lo, "end_exclusive": hi, "tag": tag}
    except ValueError as exc:
        meta_out["reason"] = "bad_datetime"
        meta_out["error"] = str(exc)
        return None, meta_out

    try:
        init_diag = initialize_earth_engine()
        meta_out["ee_init"] = init_diag
    except Exception as exc:  # noqa: BLE001
        meta_out["reason"] = "ee_init_failed"
        meta_out["error"] = f"{type(exc).__name__}: {exc}"
        return None, meta_out

    dst_crs, dst_transform = chip_transform_web_mercator(west, south, east, north, width=int(width_px), height=int(height_px))
    meta_out["dst_crs"] = dst_crs
    meta_out["dst_transform"] = dst_transform

    try:
        chip, dw_meta = fetch_dynamic_world_label(
            west,
            south,
            east,
            north,
            date_start=lo,
            date_end=hi,
            dst_crs=dst_crs,
            dst_transform=dst_transform,
            width=int(width_px),
            height=int(height_px),
            datetime_query_fallback=datetime_query_fallback or "",
        )
        meta_out.update(dw_meta)
        meta_out["ok"] = True
        meta_out["chip_shape"] = [int(chip.shape[0]), int(chip.shape[1])]
        return chip, meta_out
    except Exception as exc:  # noqa: BLE001
        meta_out["reason"] = "fetch_failed"
        meta_out["error"] = f"{type(exc).__name__}: {exc}"
        return None, meta_out
