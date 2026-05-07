"""Google Earth Engine Dynamic World label fetch for Patagonia eval (aligned chip).

Uses ``lfm_vl_sft_dataset.ee_dynamic_world.fetch_dynamic_world_label`` after ``ee.Initialize()``.
The output grid matches the STAC still footprint: WGS84 bbox from ``bbox_around_point`` (same
half-km as STAC stills), reprojected to **Web Mercator (EPSG:3857)** with an affine that exactly
covers that bbox at ``width``×``height`` pixels — same dimensions as the RGB/SCL eval chip.

Environment (typical):
- **Recommended (CI / headless)**: point ``GOOGLE_APPLICATION_CREDENTIALS`` at your **service account**
  JSON (copying the file to the server is not enough—the env var must reference it, e.g.
  ``export GOOGLE_APPLICATION_CREDENTIALS=/root/.config/gcloud/radioshaq-ee.json``).
  Project id is taken from ``GOOGLE_CLOUD_PROJECT`` / ``EE_PROJECT_*`` if set; otherwise from the
  JSON's ``project_id`` field. Register the service account email with Earth Engine (EE registration).
  See ``lfm_vl_sft_dataset.ee_auth`` for credential resolution order.
- **Interactive**: ``earthengine authenticate`` then ``ee.Initialize(project=...)``.
- **Skip Dynamic World** without touching EE: ``NUTONIC_SKIP_EE_DYNAMIC_WORLD=1`` — writes
  ``dynamic_world_fetch.reason=skipped_env`` once per process (no repeated auth errors).

Failed EE initialization is **cached** for the remainder of the process so each target does not
re-log the same ``EEException``.

This module is optional: callers should catch failures and fall back to SCL-derived fractions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_SCRIPTS = REPO_ROOT / "data" / "scripts"

# (success: bool, diagnostics dict) — set on first EE init attempt; avoids N× identical auth errors.
_EE_INIT_CACHE: tuple[bool, dict[str, Any]] | None = None


def reset_earth_engine_init_cache() -> None:
    """Clear cached EE init state (for tests or after changing credentials in-process)."""
    global _EE_INIT_CACHE
    _EE_INIT_CACHE = None


def _ensure_data_scripts_path() -> None:
    import sys

    if str(_DATA_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_DATA_SCRIPTS))


def _project_id_from_service_account_json_path(path: Path) -> str | None:
    """Read ``project_id`` from a GCP service account JSON (same field Google ships in downloaded keys)."""
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if payload.get("type") != "service_account":
        return None
    pid = (payload.get("project_id") or "").strip()
    return pid or None


def _project_id_from_credentials_env_paths() -> str | None:
    """If ``GOOGLE_APPLICATION_CREDENTIALS`` / ``EE_SERVICE_ACCOUNT_KEY_PATH`` point at a SA JSON, use its ``project_id``."""
    for envk in ("GOOGLE_APPLICATION_CREDENTIALS", "EE_SERVICE_ACCOUNT_KEY_PATH"):
        raw = (os.environ.get(envk) or "").strip()
        if not raw:
            continue
        p = Path(raw).expanduser()
        if not p.is_file():
            continue
        pid = _project_id_from_service_account_json_path(p)
        if pid:
            return pid
    return None


def ee_project_id() -> str | None:
    """Resolve GCP project id for ``ee.Initialize``: env vars first, then ``project_id`` inside the SA JSON."""
    for key in ("EE_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "GEE_PROJECT", "EARTHENGINE_PROJECT", "EE_PROJECT", "GCP_PROJECT"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return _project_id_from_credentials_env_paths()


def _skip_dynamic_world_env() -> bool:
    v = (os.environ.get("NUTONIC_SKIP_EE_DYNAMIC_WORLD") or "").strip().lower()
    return v in ("1", "true", "yes")


def earth_engine_init_cached() -> tuple[bool, dict[str, Any]]:
    """Initialize EE once per process; returns ``(ok, diagnostics)``.

    Uses ``lfm_vl_sft_dataset.ee_auth.initialize_earth_engine`` when available (service account,
    ADC, then legacy OAuth). Caches failure so repeated ``fetch_dynamic_world_chip`` calls do not
    spam identical authentication errors.
    """
    global _EE_INIT_CACHE
    if _EE_INIT_CACHE is not None:
        ok, d = _EE_INIT_CACHE
        return ok, dict(d)

    if _skip_dynamic_world_env():
        diag = {
            "reason": "skipped_env",
            "hint": "Dynamic World disabled via NUTONIC_SKIP_EE_DYNAMIC_WORLD=1",
            "auth_docs": "For EE access set GOOGLE_APPLICATION_CREDENTIALS + project id, or run earthengine authenticate",
        }
        _EE_INIT_CACHE = (False, diag)
        return False, diag

    _ensure_data_scripts_path()
    proj = ee_project_id()
    try:
        from lfm_vl_sft_dataset.ee_auth import initialize_earth_engine as ee_auth_initialize

        diag = ee_auth_initialize(project=proj)
        _EE_INIT_CACHE = (True, diag)
        return True, diag
    except Exception as exc:  # noqa: BLE001
        diag = {
            "reason": "ee_init_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "hint": "Use a service account JSON (GOOGLE_APPLICATION_CREDENTIALS), or run: earthengine authenticate",
            "project_hint": proj,
        }
        _EE_INIT_CACHE = (False, diag)
        return False, diag


def initialize_earth_engine() -> dict[str, Any]:
    """Initialize EE; raises ``RuntimeError`` if unavailable (backward-compatible for callers)."""
    ok, diag = earth_engine_init_cached()
    if not ok:
        raise RuntimeError(diag.get("error", str(diag)))
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

    ok, init_diag = earth_engine_init_cached()
    meta_out["ee_init"] = init_diag
    if not ok:
        meta_out["reason"] = str(init_diag.get("reason") or "ee_init_failed")
        if init_diag.get("error"):
            meta_out["error"] = init_diag["error"]
        if init_diag.get("hint"):
            meta_out["hint"] = init_diag["hint"]
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
