"""Random WGS84 offsets in meters (local tangent plane) for geo-jittered re-downloads."""

from __future__ import annotations

import math
import random


def sample_lat_lon_offset_m(
    lat: float,
    lon: float,
    rng: random.Random,
    max_offset_m: float,
) -> tuple[float, float, float, float]:
    """
    Uniform random offset in a disk of radius ``max_offset_m``.

    Returns ``(lat2, lon2, delta_east_m, delta_north_m)`` with lon/lat clamped to valid ranges.
    """
    if max_offset_m <= 0:
        return lat, lon, 0.0, 0.0
    theta = rng.random() * 2.0 * math.pi
    r = math.sqrt(rng.random()) * max_offset_m
    de = r * math.cos(theta)
    dn = r * math.sin(theta)
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    dlat = dn / 111_320.0
    dlon = de / (111_320.0 * cos_lat)
    lat2 = max(-89.0, min(89.0, lat + dlat))
    lon2 = max(-180.0, min(180.0, lon + dlon))
    return lat2, lon2, de, dn
