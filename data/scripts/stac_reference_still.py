"""
Sentinel-2 L2A reference still via Earth Search STAC (no Mapbox).

Used when ``render_mapbox_still.py --stac-reference-stills`` runs on the HF hydration Job.
"""

from __future__ import annotations

import io
import math
import os
from datetime import date, timedelta
from typing import Any

import numpy as np
import requests
from PIL import Image, ImageOps

try:
    import rasterio
    from rasterio.transform import rowcol
    from rasterio.windows import Window
    from rasterio.warp import transform as warp_xy
except ImportError:
    rasterio = None  # type: ignore[assignment]


def resolve_href(href: str) -> str:
    """Earth Search may list ``s3://`` assets; map to HTTPS where possible."""
    if not href.startswith("s3://"):
        return href
    _, rest = href.split("s3://", 1)
    bucket, _, key = rest.partition("/")
    if bucket == "sentinel-s2-l2a":
        return f"https://sentinel-s2-l2a.s3.eu-central-1.amazonaws.com/{key}"
    if bucket == "sentinel-s2-l1c":
        return f"https://sentinel-s2-l1c.s3.eu-central-1.amazonaws.com/{key}"
    return f"https://{bucket}.s3.amazonaws.com/{key}"


def bbox_around_point(lon: float, lat: float, bbox_half_km: float) -> tuple[float, float, float, float]:
    earth_radius_km = 6371.0
    d_lat = math.degrees(bbox_half_km / earth_radius_km)
    cos_lat = math.cos(math.radians(lat))
    d_lon = math.degrees(bbox_half_km / (earth_radius_km * cos_lat)) if abs(cos_lat) > 1e-9 else d_lat
    return (lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat)


def _default_datetime_window() -> str:
    end = date.today()
    start = end - timedelta(days=400)
    return f"{start.isoformat()}/{end.isoformat()}"


def _session() -> requests.Session:
    s = requests.Session()
    return s


def _pil_from_url(sess: requests.Session, url: str, timeout: int = 180) -> Image.Image | None:
    try:
        r = sess.get(url, timeout=timeout, stream=True)
        if r.status_code != 200:
            return None
        data = r.content
        if not data:
            return None
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


def _rio_open_url(url: str) -> str:
    u = resolve_href(url)
    if u.startswith("https://"):
        return "/vsicurl/" + u
    return u


def _point_chip_window(
    src: Any,
    lon: float,
    lat: float,
) -> Any | None:
    """Geospatial window around (lon, lat) for Sentinel-2–style rasters (shared grid)."""
    if rasterio is None:
        return None
    try:
        xs, ys = warp_xy("EPSG:4326", src.crs, [lon], [lat])
        r0, c0 = rowcol(src.transform, xs[0], ys[0])
        span = max(256, min(src.width, src.height) // 8)
        row_off = max(0, int(r0) - span // 2)
        col_off = max(0, int(c0) - span // 2)
        h = min(span, src.height - row_off)
        w = min(span, src.width - col_off)
        if h < 8 or w < 8:
            return None
        return Window(col_off, row_off, w, h)
    except Exception:
        return None


def _chip_from_geotiff_url(
    sess: requests.Session,
    url: str,
    lon: float,
    lat: float,
    out_w: int,
    out_h: int,
) -> Image.Image | None:
    del sess  # rasterio reads COG via GDAL VSI; session unused
    if rasterio is None:
        return None
    url = _rio_open_url(url)
    try:
        with rasterio.Env(OGR_HTTP_UNSAFE_SSL="YES", GDAL_HTTP_TIMEOUT=180):
            with rasterio.open(url) as src:
                if src.count < 1:
                    return None
                win = _point_chip_window(src, lon, lat)
                if win is None:
                    return None
                if src.count >= 3:
                    arr = src.read([1, 2, 3], window=win)
                else:
                    b = src.read(1, window=win)
                    arr = np.stack([b, b, b])

                x = np.transpose(arr, (1, 2, 0)).astype(np.float32)
                lo, hi = float(np.percentile(x, 2)), float(np.percentile(x, 98))
                x = np.clip((x - lo) / (hi - lo + 1e-6), 0.0, 1.0)
                x = (x * 255.0).clip(0, 255).astype(np.uint8)
                im = Image.fromarray(x, mode="RGB")
                return ImageOps.contain(im, (out_w, out_h))
    except Exception:
        return None


def read_visual_and_scl_chips_from_urls(
    *,
    visual_href: str,
    scl_href: str,
    lon: float,
    lat: float,
    out_w: int,
    out_h: int,
) -> tuple[Image.Image | None, np.ndarray | None]:
    """
    Read RGB + Scene Classification (SCL) chips using the **same** geographic window (Sentinel-2 grid).

    Both assets must share dimensions/transform (standard L2A). Returns PIL RGB and uint8 SCL with
    classes 0–11+, resized with ``ImageOps.contain`` to ``out_w`` × ``out_h`` (same display framing).
    """
    if rasterio is None:
        return None, None
    vis_u = _rio_open_url(visual_href)
    scl_u = _rio_open_url(scl_href)
    rgb: Image.Image | None = None
    win = None
    grid_wh: tuple[int, int] | None = None
    try:
        with rasterio.Env(OGR_HTTP_UNSAFE_SSL="YES", GDAL_HTTP_TIMEOUT=180):
            with rasterio.open(vis_u) as src_v:
                win = _point_chip_window(src_v, lon, lat)
                if win is None:
                    return None, None
                grid_wh = (src_v.width, src_v.height)
                if src_v.count >= 3:
                    arr = src_v.read([1, 2, 3], window=win)
                else:
                    b = src_v.read(1, window=win)
                    arr = np.stack([b, b, b])
                x = np.transpose(arr, (1, 2, 0)).astype(np.float32)
                lo, hi = float(np.percentile(x, 2)), float(np.percentile(x, 98))
                x = np.clip((x - lo) / (hi - lo + 1e-6), 0.0, 1.0)
                x = (x * 255.0).clip(0, 255).astype(np.uint8)
                rgb = Image.fromarray(x, mode="RGB")
                rgb = ImageOps.contain(rgb, (out_w, out_h))

            with rasterio.open(scl_u) as src_s:
                if grid_wh is None or win is None:
                    return rgb, None
                gw, gh = grid_wh
                if src_s.width != gw or src_s.height != gh:
                    return rgb, None
                scl_raw = src_s.read(1, window=win).astype(np.uint8)
                scl_img = Image.fromarray(scl_raw, mode="L")
                scl_rs = ImageOps.contain(scl_img, (out_w, out_h))
                scl_arr = np.asarray(scl_rs, dtype=np.uint8)
                return rgb, scl_arr
    except Exception:
        return None, None


def find_visual_cog_href(item: Any) -> str | None:
    """Prefer true-color COG / JP2 over thumbnails when pairing with SCL."""
    for key in ("visual", "overview"):
        if key not in item.assets:
            continue
        asset = item.assets[key]
        href = resolve_href(asset.href)
        mt = (asset.media_type or "").lower()
        hl = href.lower()
        if rasterio is not None and (
            "geotiff" in mt
            or "tiff" in mt
            or "jp2" in mt
            or "jpeg2000" in mt
            or hl.endswith((".tif", ".tiff", ".jp2"))
        ):
            return href
    return None


def find_scl_cog_href(item: Any) -> str | None:
    for key in ("scl", "SCL", "scene-classification"):
        if key not in item.assets:
            continue
        asset = item.assets[key]
        href = resolve_href(asset.href)
        mt = (asset.media_type or "").lower()
        hl = href.lower()
        if rasterio is not None and (
            "geotiff" in mt
            or "tiff" in mt
            or "jp2" in mt
            or "jpeg2000" in mt
            or hl.endswith((".tif", ".tiff", ".jp2"))
        ):
            return href
    return None


def fetch_sentinel_cog_rgb_scl_matched(
    lat: float,
    lon: float,
    *,
    width_px: int,
    height_px: int,
    stac_url: str | None = None,
    collection: str | None = None,
    bbox_half_km: float | None = None,
    max_cloud: float | None = None,
    max_items: int | None = None,
    datetime_range: str | None = None,
) -> tuple[Image.Image | None, np.ndarray | None, dict[str, Any]]:
    """
    Sentinel-2 chips from **COG** visual + **COG** SCL with matched footprint for grounding gold.

    Falls back to ``rgb=None`` when STAC items lack paired COGs (caller keeps JPEG/cache path).
    """
    from pystac_client import Client

    stac_url_resolved = (stac_url or "").strip() or (os.environ.get("NUTONIC_STAC_STILL_URL") or "").strip()
    stac_url_resolved = stac_url_resolved or "https://earth-search.aws.element84.com/v1"
    collection_resolved = (collection or "").strip() or (os.environ.get("NUTONIC_STAC_STILL_COLLECTION") or "").strip()
    collection_resolved = collection_resolved or "sentinel-2-l2a"
    half_km = bbox_half_km
    if half_km is None:
        half_km = float((os.environ.get("NUTONIC_STAC_STILL_BBOX_HALF_KM") or "12.0").strip())
    max_cloud_resolved = max_cloud
    if max_cloud_resolved is None:
        max_cloud_resolved = float((os.environ.get("NUTONIC_STAC_STILL_MAX_CLOUD") or "85.0").strip())
    max_items_resolved = max_items
    if max_items_resolved is None:
        max_items_resolved = int((os.environ.get("NUTONIC_STAC_STILL_MAX_ITEMS") or "30").strip())
    dt_raw = (datetime_range or "").strip()
    if not dt_raw:
        dt_raw = (os.environ.get("NUTONIC_STAC_STILL_DATETIME") or "").strip()
    datetime_range_resolved = dt_raw if dt_raw else _default_datetime_window()

    bbox = bbox_around_point(lon, lat, half_km)
    client = Client.open(stac_url_resolved)
    search = client.search(
        collections=[collection_resolved],
        bbox=list(bbox),
        datetime=datetime_range_resolved,
        max_items=max_items_resolved,
        query={"eo:cloud_cover": {"lt": max_cloud_resolved}},
    )
    items = [it for it in search.items() if it.datetime is not None]
    meta: dict[str, Any] = {
        "stac_url": stac_url_resolved,
        "collection": collection_resolved,
        "strategy": "cog_visual_scl_pair",
        "ok": False,
    }
    if not items:
        meta["reason"] = "no_items"
        return None, None, meta

    items.sort(key=lambda it: float(it.properties.get("eo:cloud_cover", 999.0)))

    for it in items:
        v_href = find_visual_cog_href(it)
        s_href = find_scl_cog_href(it)
        if not v_href or not s_href:
            continue
        rgb, scl = read_visual_and_scl_chips_from_urls(
            visual_href=v_href,
            scl_href=s_href,
            lon=lon,
            lat=lat,
            out_w=width_px,
            out_h=height_px,
        )
        meta.update(
            {
                "item_id": it.id,
                "datetime": str(it.datetime),
                "eo:cloud_cover": it.properties.get("eo:cloud_cover"),
                "visual_href_suffix": v_href[-80:],
                "scl_href_suffix": s_href[-80:],
            }
        )
        if rgb is not None and scl is not None:
            meta["ok"] = True
            return rgb, scl, meta

    meta["reason"] = "no_cog_visual_scl_pair"
    return None, None, meta


def image_from_stac_item(
    sess: requests.Session,
    item: Any,
    *,
    lon: float,
    lat: float,
    target_w: int,
    target_h: int,
) -> Image.Image | None:
    """Prefer small JPEG assets; fall back to COG visual chip."""
    keys_priority = ("thumbnail", "preview", "visual")
    for key in keys_priority:
        if key not in item.assets:
            continue
        asset = item.assets[key]
        href = resolve_href(asset.href)
        mt = (asset.media_type or "").lower()
        if any(x in mt for x in ("jpeg", "jpg", "png")) or href.lower().endswith((".jpg", ".jpeg", ".png")):
            im = _pil_from_url(sess, href)
            if im is not None:
                return ImageOps.contain(im, (target_w, target_h))
        if (
            rasterio is not None
            and ("geotiff" in mt or "tiff" in mt or href.lower().endswith(".tif"))
        ):
            chip = _chip_from_geotiff_url(sess, href, lon, lat, target_w, target_h)
            if chip is not None:
                return chip
    return None


def fetch_sentinel_reference_still(
    lat: float,
    lon: float,
    *,
    width_px: int,
    height_px: int,
    stac_url: str | None = None,
    collection: str | None = None,
    bbox_half_km: float | None = None,
    max_cloud: float | None = None,
    max_items: int | None = None,
    datetime_range: str | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    """
    Return an RGB PIL image and metadata for one catalog point.

    Optional ``stac_url``, ``collection``, ``bbox_half_km``, ``max_cloud``, ``max_items``, and
    ``datetime_range`` override ``NUTONIC_STAC_STILL_*`` environment variables (see module docstring).

    Raises ``RuntimeError`` if no usable STAC scene was found or decoded.
    """
    from pystac_client import Client

    stac_url_resolved = (stac_url or "").strip() or (os.environ.get("NUTONIC_STAC_STILL_URL") or "").strip()
    stac_url_resolved = stac_url_resolved or "https://earth-search.aws.element84.com/v1"
    collection_resolved = (collection or "").strip() or (os.environ.get("NUTONIC_STAC_STILL_COLLECTION") or "").strip()
    collection_resolved = collection_resolved or "sentinel-2-l2a"
    half_km = bbox_half_km
    if half_km is None:
        half_km = float((os.environ.get("NUTONIC_STAC_STILL_BBOX_HALF_KM") or "12.0").strip())
    max_cloud_resolved = max_cloud
    if max_cloud_resolved is None:
        max_cloud_resolved = float((os.environ.get("NUTONIC_STAC_STILL_MAX_CLOUD") or "85.0").strip())
    max_items_resolved = max_items
    if max_items_resolved is None:
        max_items_resolved = int((os.environ.get("NUTONIC_STAC_STILL_MAX_ITEMS") or "30").strip())
    dt_raw = (datetime_range or "").strip()
    if not dt_raw:
        dt_raw = (os.environ.get("NUTONIC_STAC_STILL_DATETIME") or "").strip()
    datetime_range_resolved = dt_raw if dt_raw else _default_datetime_window()

    bbox = bbox_around_point(lon, lat, half_km)
    client = Client.open(stac_url_resolved)
    search = client.search(
        collections=[collection_resolved],
        bbox=list(bbox),
        datetime=datetime_range_resolved,
        max_items=max_items_resolved,
        query={"eo:cloud_cover": {"lt": max_cloud_resolved}},
    )
    items = [it for it in search.items() if it.datetime is not None]
    if not items:
        raise RuntimeError(
            f"No STAC items for lon={lon:.5f} lat={lat:.5f} in {datetime_range_resolved} "
            f"(collection={collection_resolved}, max_cloud<{max_cloud_resolved}).",
        )

    items.sort(key=lambda it: float(it.properties.get("eo:cloud_cover", 999.0)))

    sess = _session()
    base_meta: dict[str, Any] = {"stac_url": stac_url_resolved, "collection": collection_resolved}
    for it in items:
        row_meta = {
            **base_meta,
            "item_id": it.id,
            "datetime": str(it.datetime),
            "eo:cloud_cover": it.properties.get("eo:cloud_cover"),
        }
        im = image_from_stac_item(sess, it, lon=lon, lat=lat, target_w=width_px, target_h=height_px)
        if im is not None:
            row_meta["asset_strategy"] = "thumbnail_or_visual"
            return im, row_meta

    raise RuntimeError(f"No decodable thumbnail/visual for STAC items near lon={lon:.5f} lat={lat:.5f}")
