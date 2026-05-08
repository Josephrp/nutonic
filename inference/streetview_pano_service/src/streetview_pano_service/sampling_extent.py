"""Sentinel-2–scaled default disk radius and uniform disk sampling helpers."""

from __future__ import annotations

import math
import os
import random

from streetview_pano_service.google_static import offset_lat_lon

# Server-side cap for ``area_radius_m`` (meters).
MAX_AREA_RADIUS_M = 15_000.0

# Attempt loop: at most this factor × ``count`` metadata tries (stochastic mode).
def _attempts_factor() -> int:
    raw = os.environ.get("STREETVIEW_MAX_METADATA_ATTEMPTS_FACTOR", "24").strip()
    try:
        n = int(raw)
    except ValueError:
        return 24
    return max(4, min(n, 128))


MAX_METADATA_ATTEMPTS_FACTOR = _attempts_factor()

S2_AREA_POLICY_VERSION = "2026-04-18.v1"


def _env_float(name: str, default: str) -> float:
    raw = os.environ.get(name, default).strip()
    return float(raw)


def s2_gsd_m() -> float:
    return _env_float("STREETVIEW_S2_GSD_M", "10")


def s2_chip_edge_px() -> float:
    return _env_float("STREETVIEW_S2_CHIP_EDGE_PX", "512")


def default_area_radius_m() -> float:
    """
    ``R_default = (W_px × g_m) / 2`` with S2 10 m GSD and reference chip edge (see plan §0.1).
    """
    g_m = _env_float("STREETVIEW_S2_GSD_M", "10")
    w_px = _env_float("STREETVIEW_S2_CHIP_EDGE_PX", "512")
    if g_m <= 0 or w_px <= 0:
        raise ValueError("STREETVIEW_S2_GSD_M and STREETVIEW_S2_CHIP_EDGE_PX must be positive")
    r = (w_px * g_m) / 2.0
    return float(min(r, MAX_AREA_RADIUS_M))


def clamp_area_radius_m(requested: float | None) -> float:
    if requested is None:
        return default_area_radius_m()
    if requested <= 0:
        raise ValueError("area_radius_m must be positive")
    return float(min(requested, MAX_AREA_RADIUS_M))


def uniform_disk_offset(
    rng: random.Random,
    center_lat: float,
    center_lon: float,
    radius_m: float,
) -> tuple[float, float]:
    """Uniform draw over a planar disk (``r = R * sqrt(U)``, ``U ~ Uniform(0,1)``)."""
    if radius_m <= 0:
        return center_lat, center_lon
    u = rng.random()
    dist = radius_m * math.sqrt(u)
    bearing = rng.uniform(0.0, 360.0)
    return offset_lat_lon(center_lat, center_lon, distance_m=dist, bearing_deg=bearing)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters (WGS84 sphere)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c
