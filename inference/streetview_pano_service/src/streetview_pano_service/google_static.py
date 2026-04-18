"""
Google Street View **Static** + **Metadata** APIs.

Docs: https://developers.google.com/maps/documentation/streetview
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MetadataResult:
    """Typed Street View metadata response (HTTP 200 JSON body)."""

    raw: dict[str, Any]
    status: str
    pano_id: str | None
    lat: float | None
    lon: float | None


def _parse_metadata_payload(payload: dict[str, Any]) -> MetadataResult:
    st = str(payload.get("status") or "")
    pid = payload.get("pano_id")
    pano_s = str(pid) if pid not in (None, "") else None
    loc = payload.get("location")
    lat = lon = None
    if isinstance(loc, dict):
        try:
            lat = float(loc["lat"])
            lon = float(loc["lng"])
        except (KeyError, TypeError, ValueError):
            lat = lon = None
    return MetadataResult(raw=payload, status=st, pano_id=pano_s, lat=lat, lon=lon)


def _sleep_backoff(attempt: int) -> None:
    base = min(8.0, 0.5 * (2**attempt))
    time.sleep(base)


def _get_with_retry(client: httpx.Client, url: str, *, max_attempts: int = 5) -> httpx.Response:
    last: httpx.Response | None = None
    for attempt in range(max_attempts):
        r = client.get(url)
        last = r
        if r.status_code in (429, 500, 502, 503, 504):
            if attempt + 1 < max_attempts:
                _sleep_backoff(attempt)
            continue
        r.raise_for_status()
        return r
    assert last is not None
    last.raise_for_status()
    return last


def fetch_metadata(lat: float, lon: float, *, api_key: str, timeout: float = 30.0) -> MetadataResult:
    q = urlencode({"location": f"{lat:.7f},{lon:.7f}", "key": api_key})
    url = f"{METADATA_URL}?{q}"
    with httpx.Client(timeout=timeout) as client:
        r = _get_with_retry(client, url)
    payload = json.loads(r.text)
    if not isinstance(payload, dict):
        raise RuntimeError("Street View metadata returned non-object JSON")
    return _parse_metadata_payload(payload)


def fetch_static_jpeg(
    *,
    api_key: str,
    lat: float | None = None,
    lon: float | None = None,
    pano_id: str | None = None,
    heading: float = 0.0,
    pitch: float = 0.0,
    fov: int = 75,
    width: int = 640,
    height: int = 640,
    timeout: float = 60.0,
) -> bytes:
    """Fetch a JPEG; supply **either** ``pano_id`` **or** ``(lat, lon)``, not both."""
    has_pano = pano_id is not None and str(pano_id).strip() != ""
    has_loc = lat is not None and lon is not None
    if has_pano == has_loc:
        raise ValueError("fetch_static_jpeg requires exactly one of pano_id or (lat, lon)")
    params: dict[str, str] = {
        "size": f"{width}x{height}",
        "heading": str(int(round(heading))),
        "pitch": str(int(round(pitch))),
        "fov": str(int(fov)),
        "key": api_key,
    }
    if has_pano:
        params["pano"] = str(pano_id)
    else:
        params["location"] = f"{float(lat):.7f},{float(lon):.7f}"
    q = urlencode(params)
    url = f"{STATIC_URL}?{q}"
    with httpx.Client(timeout=timeout) as client:
        r = _get_with_retry(client, url)
    data = r.content
    if len(data) < 1000 or not data.startswith(b"\xff\xd8"):
        raise RuntimeError(
            "Street View Static returned a non-JPEG body (missing coverage or billing error). "
            "Check API key billing and Street View availability at this location."
        )
    return data
