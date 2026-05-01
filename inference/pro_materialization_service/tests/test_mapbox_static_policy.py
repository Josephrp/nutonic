from __future__ import annotations

from pro_materialization_service.geospatial.mapbox_static import mapbox_source_metadata


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
