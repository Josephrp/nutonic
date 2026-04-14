"""Optional catalog replacement from assembled manifest.full.json."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import nutonic_server.catalog as game_catalog


def _minimal_manifest() -> dict[str, object]:
    return {
        "content_version": "nutonic.catalog.from_file.v1",
        "engine_version": "9.9.9",
        "maps": [
            {
                "map_id": "m_x",
                "title": "Loaded from file",
                "engine_version": None,
                "content_version": None,
            }
        ],
        "locations": [
            {
                "map_id": "m_x",
                "location_id": "loc_x",
                "truth_lat": 10.0,
                "truth_lon": 20.0,
                "still_bundled_resource": "files/3.jpg",
                "still_bundle_id": "nutonic.bundle.v1.demo_still",
                "useful_hints": None,
                "play_budget_ms": 60_000,
                "ai_marker_phase_enabled": True,
                "satellite_caption_sidecar": {"pipeline": "test", "note": "ignored by server model"},
            }
        ],
        "ai_guesses": [{"map_id": "m_x", "location_id": "loc_x", "ai_lat": 11.0, "ai_lon": 21.0}],
    }


def test_manifest_full_path_replaces_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snap_pub = [m.model_copy(deep=True) for m in game_catalog.PUBLISHED_MAPS]
    snap_loc = [m.model_copy(deep=True) for m in game_catalog.MANIFEST_LOCATIONS]
    snap_ai = [m.model_copy(deep=True) for m in game_catalog.MANIFEST_AI_GUESSES]
    snap_cv = game_catalog.CATALOG_MANIFEST_CONTENT_VERSION
    snap_ev = game_catalog.CATALOG_MANIFEST_ENGINE_VERSION
    mf = tmp_path / "manifest.full.json"
    mf.write_text(json.dumps(_minimal_manifest()), encoding="utf-8")
    monkeypatch.setenv("NUTONIC_MANIFEST_FULL_PATH", str(mf))
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    import nutonic_server.main as main

    try:
        importlib.reload(main)
        c = TestClient(main.app)
        maps = c.get("/api/v1/maps").json()
        assert len(maps) == 1
        assert maps[0]["map_id"] == "m_x"
        man = c.get("/api/v1/cache/manifest").json()
        assert man["content_version"] == "nutonic.catalog.from_file.v1"
        assert man["engine_version"] == "9.9.9"
    finally:
        monkeypatch.delenv("NUTONIC_MANIFEST_FULL_PATH", raising=False)
        game_catalog.PUBLISHED_MAPS[:] = snap_pub
        game_catalog.MANIFEST_LOCATIONS[:] = snap_loc
        game_catalog.MANIFEST_AI_GUESSES[:] = snap_ai
        game_catalog.CATALOG_MANIFEST_CONTENT_VERSION = snap_cv
        game_catalog.CATALOG_MANIFEST_ENGINE_VERSION = snap_ev
