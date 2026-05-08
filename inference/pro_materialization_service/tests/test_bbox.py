from __future__ import annotations

import math

import pytest

from pro_materialization_service.geospatial.bbox import square_bbox_wgs84


def test_square_bbox_contains_pin() -> None:
    west, south, east, north = square_bbox_wgs84(48.8566, 2.3522, half_km=5.0)
    assert west < 2.3522 < east
    assert south < 48.8566 < north
    assert abs((north - south) * math.pi / 180 * 6371000 / 2 - 5000) < 800


def test_square_bbox_invalid() -> None:
    with pytest.raises(ValueError):
        square_bbox_wgs84(0.0, 0.0, half_km=0.0)
