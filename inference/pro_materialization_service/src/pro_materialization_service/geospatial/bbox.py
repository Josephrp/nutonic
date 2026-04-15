"""Square WGS84 bbox around a pin (`plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md` §5.4)."""

from __future__ import annotations

import math


def square_bbox_wgs84(latitude: float, longitude: float, half_km: float) -> tuple[float, float, float, float]:
    """
    Return ``(west, south, east, north)`` in degrees.

    Uses geographic meter offsets (adequate for STAC query windows at PRO scales).
    """
    if half_km <= 0:
        raise ValueError("half_km must be positive")
    meters_per_deg_lat = 111_320.0
    cos_lat = math.cos(math.radians(latitude))
    cos_lat = max(cos_lat, 1e-6)
    meters_per_deg_lon = meters_per_deg_lat * cos_lat
    dlat = (half_km * 1000.0) / meters_per_deg_lat
    dlon = (half_km * 1000.0) / meters_per_deg_lon
    west = longitude - dlon
    east = longitude + dlon
    south = latitude - dlat
    north = latitude + dlat
    west = max(west, -180.0)
    east = min(east, 180.0)
    south = max(south, -90.0)
    north = min(north, 90.0)
    return west, south, east, north
