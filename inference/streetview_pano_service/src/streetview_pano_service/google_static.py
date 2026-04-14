"""
Google Street View **Static** + **Metadata** APIs.

Docs: https://developers.google.com/maps/documentation/streetview
"""

from __future__ import annotations

import json
import math
from typing import Any
from urllib.parse import urlencode

import httpx

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
STATIC_URL = "https://maps.googleapis.com/maps/api/streetview"


def offset_lat_lon(lat: float, lon: float, *, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    """Approximate WGS84 offset for small ``distance_m`` (meters), ``bearing_deg`` clockwise from north."""
    R = 6378137.0
    br = math.radians(bearing_deg)
    dlat = distance_m * math.cos(br) / R * (180.0 / math.pi)
    dlon = (
        distance_m * math.sin(br) / (R * math.cos(math.radians(lat)) * (180.0 / math.pi))
        if abs(math.cos(math.radians(lat))) > 1e-6
        else 0.0
    )
    return lat + dlat, lon + dlon


def fetch_metadata(lat: float, lon: float, *, api_key: str, timeout: float = 30.0) -> dict[str, Any]:
    q = urlencode({"location": f"{lat:.7f},{lon:.7f}", "key": api_key})
    url = f"{METADATA_URL}?{q}"
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url)
        r.raise_for_status()
    return json.loads(r.text)


def fetch_static_jpeg(
    lat: float,
    lon: float,
    *,
    api_key: str,
    heading: float = 0.0,
    pitch: float = 0.0,
    fov: int = 75,
    width: int = 640,
    height: int = 640,
    timeout: float = 60.0,
) -> bytes:
    params = {
        "location": f"{lat:.7f},{lon:.7f}",
        "size": f"{width}x{height}",
        "heading": str(int(round(heading))),
        "pitch": str(int(round(pitch))),
        "fov": str(int(fov)),
        "key": api_key,
    }
    q = urlencode(params)
    url = f"{STATIC_URL}?{q}"
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.content
    if len(data) < 1000 or not data.startswith(b"\xff\xd8"):
        raise RuntimeError(
            "Street View Static returned a non-JPEG body (missing coverage or billing error). "
            "Check API key billing and Street View availability at this location."
        )
    return data
