from __future__ import annotations

import random

from streetview_pano_service.sampling_extent import haversine_m, uniform_disk_offset


def test_haversine_m_zero() -> None:
    assert haversine_m(1.0, 2.0, 1.0, 2.0) == 0.0


def test_haversine_m_separation_filter() -> None:
    a = (0.0, 0.0)
    b = (0.0, 0.0001)
    d = haversine_m(a[0], a[1], b[0], b[1])
    assert 10.0 < d < 15.0


def test_uniform_disk_offset_in_radius() -> None:
    rng = random.Random(42)
    lat, lon = 48.8566, 2.3522
    for _ in range(20):
        alat, alon = uniform_disk_offset(rng, lat, lon, 100.0)
        assert haversine_m(lat, lon, alat, alon) <= 100.5
