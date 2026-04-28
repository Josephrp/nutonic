from __future__ import annotations

import httpx

from pro_materialization_service.geospatial.mapbox_static import (
    fetch_mapbox_static_png,
    mapbox_source_metadata,
)


def test_mapbox_source_metadata_reads_env(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("NUTONIC_MAPBOX_STATIC_STYLE", "mapbox/custom-style")
    monkeypatch.setenv("NUTONIC_MAPBOX_STATIC_BASE", "https://tiles.example.test/styles/v1/")
    monkeypatch.setenv("NUTONIC_MAPBOX_ATTRIBUTION", "Example tiles")

    assert mapbox_source_metadata() == {
        "provider": "mapbox",
        "style": "mapbox/custom-style",
        "static_base": "https://tiles.example.test/styles/v1",
        "attribution": "Example tiles",
    }


def test_fetch_mapbox_static_retries_transient_status(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("NUTONIC_MAPBOX_ATTRIBUTION", "Retry attribution")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, content=b"png", request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        png, attribution = fetch_mapbox_static_png(
            client,
            lon=1.0,
            lat=2.0,
            zoom=12.0,
            bearing=0.0,
            pitch=0.0,
            width=256,
            height=256,
            retina=False,
            token="token",
            timeout_s=1.0,
            retry_count=1,
        )

    assert png == b"png"
    assert attribution == "Retry attribution"
    assert calls == 2
