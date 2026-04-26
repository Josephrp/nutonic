"""Tests for catalog_lint."""

from __future__ import annotations

from pathlib import Path

import yaml

from catalog_lint import lint_catalog

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_min_catalog(root: Path, *, bad_map_duplicate: bool = False, missing_location: bool = False) -> None:
    (root / "locations").mkdir(parents=True)
    loc_a = {
        "location_id": "m_a",
        "map_id": "m_a",
        "truth_lat": 0.0,
        "truth_lon": 0.0,
        "assist_level": "standard",
        "still_source": {
            "render_policy": {
                "center_lat": 0.0,
                "center_lon": 0.0,
                "zoom": 12.0,
                "width_px": 128,
                "height_px": 128,
                "style": "satellite-v9",
            }
        },
    }
    (root / "locations" / "m_a.yaml").write_text(yaml.safe_dump(loc_a), encoding="utf-8")
    maps = [
        {"map_id": "m_a", "title": "A", "local_only": True, "ranked_pool": False},
    ]
    if bad_map_duplicate:
        maps.append({"map_id": "m_a", "title": "dup", "local_only": True, "ranked_pool": False})
    if missing_location:
        maps.append({"map_id": "ghost", "title": "G", "local_only": True, "ranked_pool": False})
    (root / "maps.yaml").write_text(
        yaml.safe_dump({"content_version": "1", "maps": maps}),
        encoding="utf-8",
    )


def test_lint_passes_minimal(tmp_path):
    _write_min_catalog(tmp_path)
    assert not lint_catalog(tmp_path, REPO_ROOT, verbose=False, json_errors=False)


def test_lint_duplicate_map_id(tmp_path):
    _write_min_catalog(tmp_path, bad_map_duplicate=True)
    v = lint_catalog(tmp_path, REPO_ROOT, verbose=False, json_errors=False)
    assert any(x.code == "duplicate_map_id" for x in v)


def test_lint_missing_location_for_map(tmp_path):
    _write_min_catalog(tmp_path, missing_location=True)
    v = lint_catalog(tmp_path, REPO_ROOT, verbose=False, json_errors=False)
    assert any(x.code == "map_missing_location" for x in v)


def test_lint_bundled_file_missing(tmp_path):
    (tmp_path / "locations").mkdir(parents=True)
    loc = {
        "location_id": "x",
        "map_id": "x",
        "truth_lat": 1.0,
        "truth_lon": 1.0,
        "still_source": {"bundled_relative": "data/scripts/tests/fixtures/no_such_still.png"},
    }
    (tmp_path / "locations" / "x.yaml").write_text(yaml.safe_dump(loc), encoding="utf-8")
    (tmp_path / "maps.yaml").write_text(
        yaml.safe_dump({"maps": [{"map_id": "x", "title": "X", "local_only": True, "ranked_pool": False}]}),
        encoding="utf-8",
    )
    v = lint_catalog(tmp_path, REPO_ROOT, verbose=False, json_errors=False)
    assert any(x.code == "bundled_missing" for x in v)


def test_lint_main_exit_code(tmp_path, capsys):
    _write_min_catalog(tmp_path)
    from catalog_lint import main

    assert main(["--catalog-root", str(tmp_path), "--repo-root", str(REPO_ROOT)]) == 0
