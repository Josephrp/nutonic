"""Great-circle distance for ranked verification (`docs/RANKED-MODE.md`, IMP-090)."""

from __future__ import annotations

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """WGS84 haversine distance in kilometers."""
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def score_from_distance_km(distance_km: float) -> int:
    """Monotonic score: closer → higher (simple clamped inverse for lab rounds)."""
    if distance_km <= 0:
        return 1_000_000
    raw = int(1_000_000 / (1.0 + distance_km))
    return max(0, min(1_000_000, raw))
