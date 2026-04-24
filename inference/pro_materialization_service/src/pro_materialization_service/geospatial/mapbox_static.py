"""Pin-centered Mapbox Static Images API (`data/scripts/download_simsat_sources.py` parity)."""

from __future__ import annotations

import os

import httpx

MAPBOX_STYLE = "mapbox/satellite-v9"
MAPBOX_STATIC_BASE = "https://api.mapbox.com/styles/v1"
MAPBOX_ATTRIBUTION = "© Mapbox © OpenStreetMap © Maxar"


def mapbox_access_token() -> str:
    return (os.environ.get("MAPBOX_ACCESS_TOKEN") or "").strip()


def mapbox_style() -> str:
    return (
        os.environ.get("NUTONIC_MAPBOX_STATIC_STYLE") or os.environ.get("MAPBOX_STATIC_STYLE") or MAPBOX_STYLE
    ).strip()


def mapbox_static_base() -> str:
    return (
        os.environ.get("NUTONIC_MAPBOX_STATIC_BASE")
        or os.environ.get("MAPBOX_STATIC_BASE")
        or MAPBOX_STATIC_BASE
    ).strip().rstrip("/")


def mapbox_attribution() -> str:
    return (
        os.environ.get("NUTONIC_MAPBOX_ATTRIBUTION")
        or os.environ.get("MAPBOX_ATTRIBUTION")
        or MAPBOX_ATTRIBUTION
    ).strip()


def mapbox_timeout_seconds() -> float:
    return _env_float(
        "NUTONIC_MAPBOX_TIMEOUT_SECONDS",
        "MAPBOX_TIMEOUT_SECONDS",
        default=120.0,
        minimum=1.0,
    )


def mapbox_retry_count() -> int:
    return _env_int("NUTONIC_MAPBOX_RETRY_COUNT", "MAPBOX_RETRY_COUNT", default=1, minimum=0)


def build_mapbox_static_url(
    *,
    lon: float,
    lat: float,
    zoom: float,
    bearing: float,
    pitch: float,
    width: int,
    height: int,
    retina: bool,
    token: str,
    style: str | None = None,
    static_base: str | None = None,
) -> str:
    wh = f"{width}x{height}"
    if retina:
        wh += "@2x"
    style_id = (style or mapbox_style()).strip()
    base = (static_base or mapbox_static_base()).strip().rstrip("/")
    return (
        f"{base}/{style_id}/static/"
        f"{lon},{lat},{zoom},{bearing},{pitch}/{wh}"
        f"?access_token={token}"
    )


def fetch_mapbox_static_png(
    client: httpx.Client,
    *,
    lon: float,
    lat: float,
    zoom: float,
    bearing: float,
    pitch: float,
    width: int,
    height: int,
    retina: bool,
    token: str,
    timeout_s: float | None = None,
    retry_count: int | None = None,
) -> tuple[bytes, str]:
    """
    Download Mapbox satellite PNG bytes.

    Returns ``(png_bytes, attribution_snippet)`` — attribution is fixed product string
    (store verbatim in ``run_manifest`` per plan §5.4).
    """
    timeout = float(timeout_s if timeout_s is not None else mapbox_timeout_seconds())
    retries = int(retry_count if retry_count is not None else mapbox_retry_count())
    url = build_mapbox_static_url(
        lon=lon,
        lat=lat,
        zoom=zoom,
        bearing=bearing,
        pitch=pitch,
        width=width,
        height=height,
        retina=retina,
        token=token,
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = client.get(url, timeout=timeout)
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                r.raise_for_status()
            r.raise_for_status()
            return r.content, mapbox_attribution()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_error = exc
            non_retryable_status = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500
            if attempt >= retries or non_retryable_status:
                raise
    assert last_error is not None
    raise last_error


def mapbox_source_metadata() -> dict[str, str]:
    return {
        "provider": "mapbox",
        "style": mapbox_style(),
        "static_base": mapbox_static_base(),
        "attribution": mapbox_attribution(),
    }


def _env_float(*names: str, default: float, minimum: float) -> float:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            continue
        try:
            return max(minimum, float(raw.strip()))
        except ValueError:
            return default
    return default


def _env_int(*names: str, default: int, minimum: int) -> int:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            continue
        try:
            return max(minimum, int(raw.strip()))
        except ValueError:
            return default
    return default
