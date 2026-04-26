"""Reference raster grid (UTM, 10 m) aligned to a WGS84 AOI."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds


def utm_epsg(lat: float, lon: float) -> int:
    """Return EPSG code for UTM zone (6°) containing (lon, lat)."""
    zone = int((lon + 180.0) // 6.0) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0.0 else 32700) + zone


@dataclass(frozen=True)
class ReferenceGrid:
    """Pixel grid for S2 + Dynamic World at fixed resolution (meters)."""

    crs: str
    width: int
    height: int
    transform: tuple[float, float, float, float, float, float]
    bounds_4326: tuple[float, float, float, float]

    @property
    def transform_affine(self):
        from rasterio.transform import Affine

        return Affine(*self.transform)


def build_reference_grid(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    resolution_m: float = 10.0,
    lat_anchor: float | None = None,
    lon_anchor: float | None = None,
) -> ReferenceGrid:
    """
    Build a north-up UTM grid covering the WGS84 bbox at ``resolution_m``.

    ``lat_anchor`` / ``lon_anchor`` (defaults: bbox center) pick the UTM zone.
    """
    lat_c = lat_anchor if lat_anchor is not None else (south + north) / 2.0
    lon_c = lon_anchor if lon_anchor is not None else (west + east) / 2.0
    epsg = utm_epsg(lat_c, lon_c)
    crs = f"EPSG:{epsg}"
    left, bottom, right, top = transform_bounds(
        "EPSG:4326",
        crs,
        west,
        south,
        east,
        north,
        densify_pts=21,
    )
    width = max(1, int(np.ceil((right - left) / resolution_m)))
    height = max(1, int(np.ceil((top - bottom) / resolution_m)))
    aff = from_bounds(left, bottom, right, top, width, height)
    return ReferenceGrid(
        crs=crs,
        width=width,
        height=height,
        transform=tuple(aff)[:6],
        bounds_4326=(west, south, east, north),
    )
