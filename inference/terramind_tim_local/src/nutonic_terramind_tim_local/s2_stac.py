"""Sentinel-2 L2A patch loading for TerraMind TiM (STAC + rasterio).

TerraMind v1 expects **12-channel S2L2A** in the same order as
``terratorch...PRETRAINED_BANDS["untok_sen2l2a@224"]`` (B01…B12 excluding
cirrus): surface reflectance scaled to **~0–10000** (training statistics are
defined on that numeric range).

Optional dependencies (``pip install -e ".[s2]"``): ``pystac-client``,
``rasterio``.

Imports of those libraries stay inside ``load_s2l2a_patch_np`` so the base
install does not require GDAL/rasterio (optional ``[s2]`` extra).
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

# TerraMind S2L2A channel order (B01…B12 excl. cirrus) → Earth Search Element84 ``sentinel-2-l2a`` asset ids.
# (Copernicus ``B01``… ids are tried as fallbacks in ``_pick_asset_key``.)
EARTH_SEARCH_S2L2A_ASSET_KEYS: tuple[str, ...] = (
    "coastal",
    "blue",
    "green",
    "red",
    "rededge1",
    "rededge2",
    "rededge3",
    "nir",
    "nir08",
    "wvp",
    "swir16",
    "swir22",
)


def _require_stac_rasterio() -> Any:
    try:
        import rasterio  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise ImportError("S2 STAC inputs need rasterio (pip install nutonic-terramind-tim-local[s2])") from e
    try:
        from pystac_client import Client  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise ImportError("S2 STAC inputs need pystac-client (pip install nutonic-terramind-tim-local[s2])") from e
    import rasterio

    return rasterio


def _resolve_href(href: str) -> str:
    """Match ``data/scripts/download_simsat_sources.resolve_href`` for s3 sentinel buckets."""
    if not href.startswith("s3://"):
        return href
    _, rest = href.split("s3://", 1)
    bucket, _, key = rest.partition("/")
    if bucket == "sentinel-s2-l2a":
        return f"https://sentinel-s2-l2a.s3.eu-central-1.amazonaws.com/{key}"
    if bucket == "sentinel-s2-l1c":
        return f"https://sentinel-s2-l1c.s3.amazonaws.com/{key}"
    return f"https://{bucket}.s3.amazonaws.com/{key}"


def _asset_href(item: Any, key: str) -> str:
    asset = item.assets[key]
    href = getattr(asset, "href", None) or asset.get_absolute_href()
    return _resolve_href(str(href))


def _bbox_around(lon: float, lat: float, half_km: float) -> tuple[float, float, float, float]:
    km_per_deg_lat = 111.0
    cos_lat = max(0.2, abs(math.cos(math.radians(lat))))
    km_per_deg_lon = 111.0 * cos_lat
    dx = half_km / km_per_deg_lon
    dy = half_km / km_per_deg_lat
    return (lon - dx, lat - dy, lon + dx, lat + dy)


def _pick_asset_key(item: Any, preferred: str) -> str | None:
    assets = getattr(item, "assets", None) or {}
    seq: list[str] = []
    for k in (preferred, preferred.lower(), preferred.upper()):
        if k and k not in seq:
            seq.append(k)
    if preferred.upper().startswith("B"):
        for k in (preferred.upper(), preferred.lower()):
            if k not in seq:
                seq.append(k)
    for ak in seq:
        if ak not in assets:
            continue
        if ak.endswith("-jp2"):
            cog = ak[:-4]
            if cog in assets:
                return cog
            return ak
        return ak
    return None


def load_s2l2a_patch_np(
    *,
    lat: float,
    lon: float,
    datetime_range: str,
    stac_url: str,
    collection: str,
    half_km: float,
    patch_hw: int,
    max_cloud: float,
    asset_keys: Sequence[str] | None,
    max_items: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Return ``stack`` float32 ``(12, patch_hw, patch_hw)`` in TerraMind band order
    and a small metadata dict (item id, datetime, asset keys used).
    """
    rasterio = _require_stac_rasterio()
    from pystac_client import Client
    from rasterio.enums import Resampling
    from rasterio.transform import rowcol
    from rasterio.windows import Window, bounds as window_bounds, from_bounds

    west, south, east, north = _bbox_around(lon, lat, half_km)
    client = Client.open(stac_url)
    search = client.search(
        collections=[collection],
        bbox=[west, south, east, north],
        datetime=datetime_range,
        max_items=max(1, int(max_items)),
        query={"eo:cloud_cover": {"lt": float(max_cloud)}},
    )
    items = list(search.items())
    if not items:
        raise RuntimeError(
            f"No STAC items for bbox=({west:.5f},{south:.5f},{east:.5f},{north:.5f}) "
            f"datetime={datetime_range!r} collection={collection!r}"
        )
    item = min(items, key=lambda i: float(i.properties.get("eo:cloud_cover") or 999.0))

    keys = tuple(asset_keys) if asset_keys is not None else EARTH_SEARCH_S2L2A_ASSET_KEYS
    if len(keys) != 12:
        raise ValueError(f"S2L2A expects 12 asset keys, got {len(keys)}")

    ref_key = _pick_asset_key(item, keys[1]) or _pick_asset_key(item, "B02")
    if ref_key is None:
        raise RuntimeError(f"No reference asset among {keys} on item {item.id}")

    ref_href = _asset_href(item, ref_key)
    meta: dict[str, Any] = {
        "stac_item_id": item.id,
        "stac_datetime": item.datetime.isoformat() if item.datetime else None,
        "eo_cloud_cover": item.properties.get("eo:cloud_cover"),
        "reference_asset": ref_key,
        "band_asset_keys": [],
    }

    with rasterio.open(ref_href) as ref:
        xs, ys = rasterio.warp.transform("EPSG:4326", ref.crs, [lon], [lat])
        row_i, col_i = rowcol(ref.transform, xs[0], ys[0])
        row0 = int(row_i) - patch_hw // 2
        col0 = int(col_i) - patch_hw // 2
        row0 = min(max(row0, 0), max(0, ref.height - patch_hw))
        col0 = min(max(col0, 0), max(0, ref.width - patch_hw))
        if ref.height < patch_hw or ref.width < patch_hw:
            raise RuntimeError(f"Reference raster {ref.width}x{ref.height} smaller than patch_hw={patch_hw}")
        win_ref = Window(col0, row0, patch_hw, patch_hw)
        geo_left, geo_bottom, geo_right, geo_top = window_bounds(win_ref, ref.transform)
        ref_crs = ref.crs

    bands: list[np.ndarray] = []
    used_keys: list[str] = []

    for preferred in keys:
        ak = _pick_asset_key(item, preferred)
        if ak is None:
            raise RuntimeError(f"Missing asset for band {preferred!r} on item {item.id}")
        href = _asset_href(item, ak)
        used_keys.append(ak)
        with rasterio.open(href) as src:
            if src.crs != ref_crs:
                gl, gb, gr, gt = rasterio.warp.transform_bounds(
                    ref_crs, src.crs, geo_left, geo_bottom, geo_right, geo_top, densify_pts=21
                )
            else:
                gl, gb, gr, gt = geo_left, geo_bottom, geo_right, geo_top
            win = from_bounds(gl, gb, gr, gt, transform=src.transform)
            win = win.intersection(Window(0, 0, src.width, src.height))
            if win.width < 1 or win.height < 1:
                raise RuntimeError(
                    f"Band {ak} geographic window does not intersect raster ({src.width}x{src.height}); "
                    "try a larger half_km."
                )
            arr = src.read(
                1,
                window=win,
                out_shape=(patch_hw, patch_hw),
                resampling=Resampling.bilinear,
                boundless=False,
            ).astype(np.float32)
            scale = src.scales[0] if src.scales and src.scales[0] is not None else None
            offset = src.offsets[0] if src.offsets and src.offsets[0] is not None else None
            if scale is not None:
                arr = arr * float(scale)
                if offset is not None:
                    arr = arr + float(offset)
            bands.append(arr)

    meta["band_asset_keys"] = used_keys
    stack = np.stack(bands, axis=0)
    return stack, meta


def apply_reflectance_scale(stack: np.ndarray, s2_cfg: Mapping[str, Any]) -> np.ndarray:
    """If values look like 0–1 reflectance, scale to TerraMind's ~0–10000 range."""
    out = stack.astype(np.float32, copy=False)
    max_ref = float(s2_cfg.get("reflectance_saturation_hint", 1.5))
    scale_to_dn = float(s2_cfg.get("scale_to_dn_if_under", 10_000.0))
    if float(np.nanmax(out)) <= max_ref and scale_to_dn > 0:
        out = out * scale_to_dn
    return out


def stac_s2_params_from_cfg(in_cfg: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    s2 = dict(in_cfg.get("s2") or {})
    for k in (
        "lat",
        "lon",
        "datetime",
        "stac_url",
        "collection",
        "half_km",
        "patch_hw",
        "max_cloud",
        "max_items",
        "asset_keys",
    ):
        if row.get(k) is not None:
            s2[k] = row[k]
        elif s2.get(k) is None and in_cfg.get(k) is not None:
            s2[k] = in_cfg[k]
    return s2
