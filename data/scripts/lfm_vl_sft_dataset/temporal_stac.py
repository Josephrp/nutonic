"""Temporal STAC helpers for paired Sentinel-2 event sampling."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
from pystac_client import Client


@dataclass(frozen=True)
class TemporalScene:
    """Small immutable view of a STAC item used by dataset builders."""

    item_id: str
    datetime_iso: str
    cloud_cover: float | None
    bbox_wgs84: tuple[float, float, float, float]


def bbox_around_point(lon: float, lat: float, bbox_half_km: float) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) around a center point."""
    earth_radius_km = 6371.0
    d_lat = math.degrees(bbox_half_km / earth_radius_km)
    cos_lat = math.cos(math.radians(lat))
    d_lon = math.degrees(bbox_half_km / (earth_radius_km * cos_lat)) if abs(cos_lat) > 1e-9 else d_lat
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


def _to_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_event_date(event_date: str) -> datetime:
    """Accept YYYY-MM-DD or full ISO datetime."""
    raw = event_date.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dt = datetime.combine(date.fromisoformat(raw), datetime.min.time(), tzinfo=timezone.utc)
        return dt
    return _to_utc_datetime(raw)


def _datetime_window(start: datetime, end: datetime) -> str:
    return f"{start.date().isoformat()}/{end.date().isoformat()}"


def _score_pre_item(item: Any, event_dt: datetime) -> tuple[float, float, float]:
    dt = _to_utc_datetime(item.datetime)
    cloud = float(item.properties.get("eo:cloud_cover", 100.0) or 100.0)
    return (abs((event_dt - dt).total_seconds()), cloud, -dt.timestamp())


def _score_post_item(item: Any, event_dt: datetime) -> tuple[float, float, float]:
    dt = _to_utc_datetime(item.datetime)
    cloud = float(item.properties.get("eo:cloud_cover", 100.0) or 100.0)
    return (abs((dt - event_dt).total_seconds()), cloud, dt.timestamp())


def _search_items(
    *,
    stac_url: str,
    collection: str,
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    max_cloud_pct: float,
    max_items: int,
) -> list[Any]:
    client = Client.open(stac_url)
    search = client.search(
        collections=[collection],
        bbox=list(bbox),
        datetime=datetime_range,
        max_items=max_items,
        query={"eo:cloud_cover": {"lt": max_cloud_pct}},
    )
    out: list[Any] = []
    for item in search.items():
        if item.datetime is None:
            continue
        out.append(item)
    return out


def scene_from_item(item: Any) -> TemporalScene:
    dt = _to_utc_datetime(item.datetime).isoformat()
    bbox = tuple(float(v) for v in item.bbox)
    if len(bbox) != 4:
        raise ValueError(f"Unexpected bbox shape for item {item.id}: {item.bbox}")
    cloud_raw = item.properties.get("eo:cloud_cover")
    cloud = float(cloud_raw) if cloud_raw is not None else None
    return TemporalScene(
        item_id=str(item.id),
        datetime_iso=dt,
        cloud_cover=cloud,
        bbox_wgs84=(bbox[0], bbox[1], bbox[2], bbox[3]),
    )


def search_temporal_pair(
    *,
    lat: float,
    lon: float,
    bbox_half_km: float,
    event_date: str,
    pre_window_days: int = 90,
    post_window_days: int = 60,
    max_cloud_pct: float = 30.0,
    stac_url: str = "https://earth-search.aws.element84.com/v1",
    collection: str = "sentinel-2-l2a",
    max_items: int = 50,
) -> tuple[TemporalScene | None, TemporalScene | None]:
    """Return best pre-event and post-event STAC scenes for an event center."""
    event_dt = _parse_event_date(event_date)
    bbox = bbox_around_point(lon, lat, bbox_half_km)

    pre_start = event_dt - timedelta(days=pre_window_days)
    pre_end = event_dt
    post_start = event_dt
    post_end = event_dt + timedelta(days=post_window_days)

    pre_items = _search_items(
        stac_url=stac_url,
        collection=collection,
        bbox=bbox,
        datetime_range=_datetime_window(pre_start, pre_end),
        max_cloud_pct=max_cloud_pct,
        max_items=max_items,
    )
    post_items = _search_items(
        stac_url=stac_url,
        collection=collection,
        bbox=bbox,
        datetime_range=_datetime_window(post_start, post_end),
        max_cloud_pct=max_cloud_pct,
        max_items=max_items,
    )

    pre_item = min(pre_items, key=lambda item: _score_pre_item(item, event_dt)) if pre_items else None
    post_item = min(post_items, key=lambda item: _score_post_item(item, event_dt)) if post_items else None
    return (
        scene_from_item(pre_item) if pre_item is not None else None,
        scene_from_item(post_item) if post_item is not None else None,
    )


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "asset"


def _suffix_for_asset(media_type: str | None, href: str) -> str:
    if media_type:
        mt = media_type.split(";")[0].strip().lower()
        if "geotiff" in mt or mt == "image/tiff":
            return ".tif"
        if "jp2" in mt or mt == "image/jp2":
            return ".jp2"
        if "jpeg" in mt or mt == "image/jpeg":
            return ".jpg"
        if "json" in mt:
            return ".json"
        if "xml" in mt:
            return ".xml"
    href_l = href.lower()
    for ext in (".tif", ".tiff", ".jp2", ".jpg", ".jpeg", ".json", ".xml", ".png"):
        if href_l.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ""


def _resolve_href(href: str) -> str:
    if not href.startswith("s3://"):
        return href
    _, rest = href.split("s3://", 1)
    bucket, _, key = rest.partition("/")
    if bucket == "sentinel-s2-l2a":
        return f"https://sentinel-s2-l2a.s3.eu-central-1.amazonaws.com/{key}"
    if bucket == "sentinel-s2-l1c":
        return f"https://sentinel-s2-l1c.s3.eu-central-1.amazonaws.com/{key}"
    return f"https://{bucket}.s3.amazonaws.com/{key}"


def _download_url(session: requests.Session, url: str, dest: Path, timeout: int = 45) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with session.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    tmp.replace(dest)


def download_item_assets(
    *,
    item: Any,
    item_root: Path,
    session: requests.Session,
    asset_allowlist: set[str] | None = None,
    optional_asset_keys: set[str] | None = None,
    skip_existing: bool = True,
    timeout_s: int = 45,
) -> tuple[Path, list[str], list[str]]:
    """Download STAC item assets into ``item_root/<item_id>/``."""
    optional_asset_keys = optional_asset_keys or {"product_metadata"}
    item_dir = item_root / _safe_filename(str(item.id))
    item_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    warnings: list[str] = []

    for key, asset in item.assets.items():
        if asset_allowlist is not None and key not in asset_allowlist:
            continue
        suffix = _suffix_for_asset(asset.media_type, asset.href)
        dest = item_dir / f"{_safe_filename(key)}{suffix}"
        if skip_existing and dest.exists() and dest.stat().st_size > 0:
            continue
        try:
            _download_url(session, _resolve_href(asset.href), dest, timeout=timeout_s)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            msg = f"{item.id}/{key}: {exc}"
            if key in optional_asset_keys and code == 404:
                warnings.append(msg)
            else:
                errors.append(msg)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{item.id}/{key}: {exc}")
    return item_dir, errors, warnings


def _find_band_file(item_dir: Path, band_key: str) -> Path | None:
    candidates = [
        f"{band_key}.tif",
        f"{band_key}.tiff",
        f"{band_key.upper()}.tif",
        f"{band_key.upper()}.tiff",
    ]
    for name in candidates:
        p = item_dir / name
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def stack_item_bands_on_grid(
    *,
    item_dir: Path,
    band_keys: list[str],
    dst_crs: str,
    dst_transform: tuple[float, float, float, float, float, float],
    width: int,
    height: int,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Warp requested one-band assets to the destination grid."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject

    aff = Affine(*dst_transform)
    out: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {"assets": {}}
    for key in band_keys:
        path = _find_band_file(item_dir, key)
        if path is None:
            continue
        arr = np.empty((height, width), dtype=np.float32)
        with rasterio.open(path) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=arr,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=aff,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                dst_nodata=np.nan,
            )
        out[key] = arr
        meta["assets"][key] = str(path)
    return out, meta
