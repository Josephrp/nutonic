"""Pin-centered Mapbox Static Images API (`data/scripts/download_simsat_sources.py` parity)."""

from __future__ import annotations

import os

import httpx

MAPBOX_STYLE = "mapbox/satellite-v9"
MAPBOX_STATIC_BASE = "https://api.mapbox.com/styles/v1"


def mapbox_access_token() -> str:
    return (os.environ.get("MAPBOX_ACCESS_TOKEN") or "").strip()


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
) -> str:
    wh = f"{width}x{height}"
    if retina:
        wh += "@2x"
    return (
        f"{MAPBOX_STATIC_BASE}/{MAPBOX_STYLE}/static/"
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
    timeout_s: float = 120.0,
) -> tuple[bytes, str]:
    """
    Download Mapbox satellite PNG bytes.

    Returns ``(png_bytes, attribution_snippet)`` — attribution is fixed product string
    (store verbatim in ``run_manifest`` per plan §5.4).
    """
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
    r = client.get(url, timeout=timeout_s)
    r.raise_for_status()
    attribution = "© Mapbox © OpenStreetMap © Maxar"
    return r.content, attribution
