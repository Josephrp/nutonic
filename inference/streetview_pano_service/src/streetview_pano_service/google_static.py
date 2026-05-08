"""
Google Street View **Static** + **Metadata** APIs.

Docs: https://developers.google.com/maps/documentation/streetview
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
STATIC_URL = "https://maps.googleapis.com/maps/api/streetview"

# Metadata JSON ``status`` values that often clear after backoff (rate limits / transient faults).
_METADATA_JSON_RETRYABLE = frozenset({"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"})


def _read_positive_int(name: str, default: int) -> int:
    raw = (os.environ.get(name, "") or "").strip()
    if not raw:
        raw = str(default)
    try:
        v = int(raw)
    except ValueError:
        return default
    return max(1, v)


def _http_max_attempts() -> int:
    return _read_positive_int(
        "STREETVIEW_GOOGLE_HTTP_MAX_ATTEMPTS",
        _read_positive_int("NUTONIC_GOOGLE_STREETVIEW_HTTP_MAX_ATTEMPTS", 5),
    )


def _metadata_json_max_attempts() -> int:
    return _read_positive_int("STREETVIEW_GOOGLE_METADATA_JSON_MAX_ATTEMPTS", 5)


def _static_validation_max_attempts() -> int:
    return _read_positive_int("STREETVIEW_GOOGLE_STATIC_VALIDATION_RETRIES", 3)


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


def _retryable_http_status(code: int) -> bool:
    return code in (408, 429, 500, 502, 503, 504)


def _get_with_retry(client: httpx.Client, url: str, *, max_attempts: int) -> httpx.Response:
    last: httpx.Response | None = None
    for attempt in range(max_attempts):
        try:
            r = client.get(url)
        except httpx.RequestError:
            if attempt + 1 >= max_attempts:
                raise
            _sleep_backoff(attempt)
            continue
        last = r
        if _retryable_http_status(r.status_code):
            if attempt + 1 < max_attempts:
                _sleep_backoff(attempt)
                continue
            r.raise_for_status()
            return r
        r.raise_for_status()
        return r
    assert last is not None
    last.raise_for_status()
    return last


def fetch_metadata(lat: float, lon: float, *, api_key: str, timeout: float = 30.0) -> MetadataResult:
    q = urlencode({"location": f"{lat:.7f},{lon:.7f}", "key": api_key})
    url = f"{METADATA_URL}?{q}"
    http_attempts = _http_max_attempts()
    meta_rounds = _metadata_json_max_attempts()
    last_result: MetadataResult | None = None
    for ja in range(meta_rounds):
        with httpx.Client(timeout=timeout) as client:
            r = _get_with_retry(client, url, max_attempts=http_attempts)
        payload = json.loads(r.text)
        if not isinstance(payload, dict):
            raise RuntimeError("Street View metadata returned non-object JSON")
        last_result = _parse_metadata_payload(payload)
        if last_result.status not in _METADATA_JSON_RETRYABLE or ja + 1 >= meta_rounds:
            return last_result
        _sleep_backoff(ja)
    assert last_result is not None
    return last_result


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
    http_attempts = _http_max_attempts()
    val_rounds = _static_validation_max_attempts()
    last_err: str | None = None
    for va in range(val_rounds):
        with httpx.Client(timeout=timeout) as client:
            r = _get_with_retry(client, url, max_attempts=http_attempts)
        data = r.content
        if len(data) >= 1000 and data.startswith(b"\xff\xd8"):
            return data
        last_err = (
            "Street View Static returned a non-JPEG body (missing coverage or billing error). "
            "Check API key billing and Street View availability at this location."
        )
        if va + 1 >= val_rounds:
            raise RuntimeError(last_err)
        _sleep_backoff(va)
    raise RuntimeError(last_err or "Street View Static fetch failed")
