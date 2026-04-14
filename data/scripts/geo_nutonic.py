"""
Shared geodesy for NU:TONIC data scripts — stdlib only (no torch, no geopandas).

Point order for haversine helpers is (longitude, latitude), matching
refs/terramind-geogen-main/src/geo_utils.py tensor convention.
"""

from __future__ import annotations

import math


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in km; (lon, lat) order matches src/geo_utils.haversine."""
    r_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlamb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlamb / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return r_km * c


def clamp_distance_km(d: float, max_km: float | None) -> float:
    """Clamp a distance in km to max_km when max_km is set; otherwise return d unchanged."""
    if max_km is None:
        return d
    return min(d, max_km)


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial forward azimuth from point 1 toward point 2, degrees clockwise from north [0, 360)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def destination_point_km(lon1: float, lat1: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """
    Spherical direct geodesic: move ``distance_km`` from (lon1, lat1) along ``bearing_deg``
    (clockwise from north, same convention as ``bearing_deg`` point-to-point).

    Returns ``(lon2, lat2)`` in WGS84 degrees. Uses Earth radius **6371 km** to match ``haversine_km``.
    """
    if distance_km < 0:
        raise ValueError("distance_km must be non-negative")
    r_km = 6371.0
    angular = distance_km / r_km
    br = math.radians(bearing_deg)
    phi1 = math.radians(lat1)
    lam1 = math.radians(lon1)
    sin_phi1, cos_phi1 = math.sin(phi1), math.cos(phi1)
    sin_d, cos_d = math.sin(angular), math.cos(angular)
    phi2 = math.asin(min(1.0, max(-1.0, sin_phi1 * cos_d + cos_phi1 * sin_d * math.cos(br))))
    lam2 = lam1 + math.atan2(
        math.sin(br) * sin_d * cos_phi1,
        cos_d - sin_phi1 * math.sin(phi2),
    )
    lon2 = math.degrees(lam2)
    lon2 = ((lon2 + 540.0) % 360.0) - 180.0
    lat2 = math.degrees(phi2)
    lat2 = max(-90.0, min(90.0, lat2))
    return lon2, lat2
