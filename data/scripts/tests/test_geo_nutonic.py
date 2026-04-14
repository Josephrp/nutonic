"""Unit tests for geo_nutonic — reference distances via spherical Geod (6371 km)."""

from __future__ import annotations

import math

import pytest
from pyproj import Geod

from geo_nutonic import bearing_deg, clamp_distance_km, destination_point_km, haversine_km

# Match haversine_km's mean Earth radius (km) as meters for pyproj spherical geodesic.
_REF_GEOD = Geod(ellps="sphere", a=6371000.0, b=6371000.0)

# (lon1, lat1, lon2, lat2, label)
_HAVERSINE_TABLE: list[tuple[float, float, float, float, str]] = [
    (0.0, 0.0, 0.0, 0.0, "same point"),
    (-74.006, 40.7128, 2.3522, 48.8566, "NYC–Paris"),
    (151.2093, -33.8688, 174.7633, -36.8485, "Sydney–Auckland"),
    (12.4924, 41.8902, 12.4534, 41.9029, "Rome short hop"),
    (179.0, 0.0, -179.0, 0.0, "near antimeridian equator"),
    (0.0, 89.0, 90.0, 89.0, "high latitude arc"),
]


def _reference_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    _az12, _az21, dist_m = _REF_GEOD.inv(lon1, lat1, lon2, lat2)
    return dist_m / 1000.0


@pytest.mark.parametrize("lon1,lat1,lon2,lat2,label", _HAVERSINE_TABLE)
def test_haversine_vs_spherical_geod(
    lon1: float, lat1: float, lon2: float, lat2: float, label: str
) -> None:
    got = haversine_km(lon1, lat1, lon2, lat2)
    ref = _reference_km(lon1, lat1, lon2, lat2)
    tol_km = 0.01
    assert abs(got - ref) <= tol_km, f"{label}: got={got} ref={ref}"


def test_clamp_distance_none_passthrough() -> None:
    assert clamp_distance_km(500.0, None) == 500.0


def test_clamp_distance_caps() -> None:
    assert clamp_distance_km(100.0, 50.0) == 50.0
    assert clamp_distance_km(30.0, 50.0) == 30.0


def test_bearing_north_and_east() -> None:
    # Due north: same lon, lat increases → bearing ~0
    b = bearing_deg(0.0, 0.0, 0.0, 1.0)
    assert abs(b - 0.0) < 0.01 or abs(b - 360.0) < 0.01
    # Due east on equator: lon increases, same lat → bearing ~90
    b_e = bearing_deg(0.0, 0.0, 1.0, 0.0)
    assert abs(b_e - 90.0) < 0.1


def test_bearing_range() -> None:
    b = bearing_deg(-74.0, 40.7, 2.35, 48.85)
    assert 0.0 <= b < 360.0
    assert math.isfinite(b)


def test_destination_point_km_matches_geodesic_distance() -> None:
    lon0, lat0 = 12.5, 41.9
    dist_km = 33.3
    brg = 200.0
    lon1, lat1 = destination_point_km(lon0, lat0, brg, dist_km)
    got = haversine_km(lon0, lat0, lon1, lat1)
    assert abs(got - dist_km) < 0.05
