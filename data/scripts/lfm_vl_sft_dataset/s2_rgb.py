"""Stack Sentinel-2 L2A blue/green/red COGs onto a reference grid."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def _find_tif(item_dir: Path, stem: str) -> Path | None:
    for pat in (f"{stem}.tif", f"{stem}.tiff", f"{stem.upper()}.tif"):
        p = item_dir / pat
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def _find_visual_preview(item_dir: Path) -> Path | None:
    """Earth Search ``minimal`` POI downloads often ship ``visual`` / ``thumbnail`` only."""
    for pat in (
        "visual.tif",
        "visual.tiff",
        "visual-cog.tif",
        "visual.jpg",
        "visual.jpeg",
        "thumbnail.jpg",
        "thumbnail.jpeg",
    ):
        p = item_dir / pat
        if p.is_file() and p.stat().st_size > 0:
            return p
    for p in sorted(item_dir.glob("*visual*")):
        if p.suffix.lower() in (".tif", ".tiff", ".jpg", ".jpeg") and p.is_file() and p.stat().st_size > 0:
            return p
    return None


def _stack_visual_on_grid(
    visual_path: Path,
    *,
    dst_crs: str,
    dst_transform: tuple[float, float, float, float, float, float],
    width: int,
    height: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Warp preview RGB (or single-band) to the reference grid as float32."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject

    dst_t = Affine(*dst_transform)
    out = np.empty((3, height, width), dtype=np.float32)
    meta: dict[str, Any] = {"assets": [str(visual_path)], "source": "visual_or_thumbnail"}
    with rasterio.open(visual_path) as src:
        n = min(3, max(1, src.count))
        for i in range(3):
            b = min(i + 1, n)
            reproject(
                source=rasterio.band(src, b),
                destination=out[i],
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_t,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                dst_nodata=np.nan,
            )
    return out, meta


def poi_dir_has_sentinel_l2a(poi_dir: Path) -> bool:
    """True if ``poi_dir/sentinel-2-l2a`` exists and contains at least one STAC item folder."""
    root = poi_dir / "sentinel-2-l2a"
    if not root.is_dir():
        return False
    return any(d.is_dir() for d in root.iterdir())


def resolve_sentinel_item_dir(poi_dir: Path, stac_item_id: str | None) -> Path:
    root = poi_dir / "sentinel-2-l2a"
    if not root.is_dir():
        raise FileNotFoundError(f"No sentinel-2-l2a directory under {poi_dir}")
    subs = sorted([d for d in root.iterdir() if d.is_dir()])
    if not subs:
        raise FileNotFoundError(f"No STAC item folders under {root}")
    if stac_item_id:
        for d in subs:
            if d.name == stac_item_id or stac_item_id in d.name:
                return d
    return subs[0]


def stack_s2_rgb_on_grid(
    item_dir: Path,
    *,
    dst_crs: str,
    dst_transform: tuple[float, float, float, float, float, float],
    width: int,
    height: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Return float32 ``(3, height, width)`` in **R, G, B** order (reflectance / DN as stored in COG).

    Missing bands raise ``RuntimeError``.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject

    dst_t = Affine(*dst_transform)
    out = np.empty((3, height, width), dtype=np.float32)
    meta: dict[str, Any] = {"assets": []}

    paths = [_find_tif(item_dir, s) for s in ("red", "green", "blue")]
    if all(paths):
        for i, path in enumerate(paths):
            assert path is not None
            meta["assets"].append(str(path))
            with rasterio.open(path) as src:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=out[i],
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=dst_t,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                    dst_nodata=np.nan,
                )
        meta["source"] = "red_green_blue"
        return out, meta

    vis = _find_visual_preview(item_dir)
    if vis is not None:
        return _stack_visual_on_grid(vis, dst_crs=dst_crs, dst_transform=dst_transform, width=width, height=height)

    raise RuntimeError(
        f"No usable Sentinel RGB under {item_dir} (expected red/green/blue.tif or visual/thumbnail). "
        "Re-run download_geoguessr_poi_imagery.py without --skip-existing or use --sentinel-mode full."
    )


def stack_s2_bands_on_grid(
    item_dir: Path,
    *,
    band_names: list[str],
    dst_crs: str,
    dst_transform: tuple[float, float, float, float, float, float],
    width: int,
    height: int,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """
    Warp requested Sentinel-2 single-band assets to the reference grid.

    Returns:
      - dict band_name -> float32 (height, width)
      - metadata with resolved assets
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject

    dst_t = Affine(*dst_transform)
    out: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {"assets": {}}
    missing: list[str] = []
    for band in band_names:
        p = _find_tif(item_dir, band)
        if p is None:
            missing.append(band)
            continue
        arr = np.empty((height, width), dtype=np.float32)
        with rasterio.open(p) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=arr,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_t,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                dst_nodata=np.nan,
            )
        out[band] = arr
        meta["assets"][band] = str(p)
    if missing:
        raise RuntimeError(f"Missing Sentinel bands under {item_dir}: {', '.join(missing)}")
    return out, meta
