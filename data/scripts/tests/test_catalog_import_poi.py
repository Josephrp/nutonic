"""Tests for catalog_import_poi — Layout A/B ingest and path normalization."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from catalog_import_poi import (
    CatalogImportError,
    collect_import_jobs,
    normalize_mapbox_path,
    plan_import,
    run_import,
)
from catalog_lint import lint_catalog

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_POI_MINI = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "poi_mini"
FIXTURE_LAYOUT_B = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "poi_mini_layout_b"

# Minimal valid 1×1 PNG (grayscale)
MINI_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x00\x00\x00\x00:~\x9bU"
    b"\x00\x00\x00\nIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x18\xdd\x8d\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_normalize_mapbox_path_relative_posix():
    rel = normalize_mapbox_path("data/scripts/tests/fixtures/poi_mini/poi_test_0/poi.json", REPO_ROOT)
    assert rel is not None
    assert rel == "data/scripts/tests/fixtures/poi_mini/poi_test_0/poi.json"


def test_normalize_rejects_path_outside_repo():
    outside = Path.home().resolve() / "nutonic_catalog_import_nonexistent.png"
    with pytest.raises(CatalogImportError, match="escapes"):
        normalize_mapbox_path(str(outside), REPO_ROOT)


def test_collect_layout_a_prefers_manifest():
    jobs = collect_import_jobs(FIXTURE_POI_MINI)
    assert len(jobs) == 2
    assert {j["poi_id"] for j in jobs} == {"poi_test_0", "poi_test_1"}


def test_collect_layout_b_without_manifest():
    jobs = collect_import_jobs(FIXTURE_LAYOUT_B)
    assert len(jobs) == 2
    assert {j["poi_id"] for j in jobs} == {"poi_b0", "poi_b1"}


def test_import_layout_a_dry_run(tmp_path):
    catalog = tmp_path / "catalog"
    rc = run_import(
        FIXTURE_POI_MINI,
        REPO_ROOT,
        catalog,
        dry_run=True,
        force=True,
        maps_file=None,
        content_version="test-1",
    )
    assert rc == 0
    assert not catalog.exists() or not (catalog / "locations").exists()


def test_import_writes_yaml_and_merge_maps(tmp_path):
    catalog = tmp_path / "catalog"
    assert run_import(FIXTURE_POI_MINI, REPO_ROOT, catalog, dry_run=False, force=True, maps_file=None, content_version="t") == 0
    loc0 = catalog / "locations" / "poi_test_0.yaml"
    assert loc0.is_file()
    data = yaml.safe_load(loc0.read_text(encoding="utf-8"))
    assert data["truth_lat"] == 10.5
    assert data["still_source"]["render_policy"]["center_lat"] == 10.5
    maps = yaml.safe_load((catalog / "maps.yaml").read_text(encoding="utf-8"))
    assert len(maps["maps"]) == 2
    assert maps["content_version"] == "t"
    assert not lint_catalog(catalog, REPO_ROOT, verbose=False, json_errors=False)


def test_import_refuses_overwrite_without_force(tmp_path):
    catalog = tmp_path / "catalog"
    assert run_import(FIXTURE_POI_MINI, REPO_ROOT, catalog, dry_run=False, force=True, maps_file=None, content_version="t") == 0
    rc = run_import(FIXTURE_POI_MINI, REPO_ROOT, catalog, dry_run=False, force=False, maps_file=None, content_version="t")
    assert rc == 2


def test_import_bundled_still_when_png_present(tmp_path):
    """Raster must live under REPO_ROOT so bundled_relative normalization succeeds."""
    scratch = REPO_ROOT / "data" / "scripts" / "tests" / "_scratch_raster"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        still_dir = scratch / "poi_raster" / "mapbox"
        still_dir.mkdir(parents=True, exist_ok=True)
        still_path = still_dir / "x.png"
        still_path.write_bytes(MINI_PNG)
        manifest = {
            "points": [
                {
                    "poi_id": "poi_raster",
                    "latitude": 0.0,
                    "longitude": 0.0,
                    "mapbox": {"path": str(still_path.resolve()), "skipped": False},
                }
            ]
        }
        poi_root = tmp_path / "poi"
        (poi_root / "poi_raster").mkdir(parents=True)
        (poi_root / "geoguessr_poi_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        catalog = tmp_path / "catalog"
        assert run_import(poi_root, REPO_ROOT, catalog, dry_run=False, force=True, maps_file=None, content_version="r") == 0
        loc = yaml.safe_load((catalog / "locations" / "poi_raster.yaml").read_text(encoding="utf-8"))
        assert "bundled_relative" in loc["still_source"]
        rel = loc["still_source"]["bundled_relative"]
        assert (REPO_ROOT / rel).is_file()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_ranked_split_half_assigns_pools(tmp_path):
    catalog = tmp_path / "catalog"
    assert (
        run_import(
            FIXTURE_POI_MINI,
            REPO_ROOT,
            catalog,
            dry_run=False,
            force=True,
            maps_file=None,
            content_version="split",
            ranked_split="half",
        )
        == 0
    )
    maps = yaml.safe_load((catalog / "maps.yaml").read_text(encoding="utf-8"))
    by_id = {m["map_id"]: m for m in maps["maps"]}
    # Sorted: poi_test_0, poi_test_1 — first half (n//2=1) ranked_pool False, second True
    assert by_id["poi_test_0"]["ranked_pool"] is False
    assert by_id["poi_test_1"]["ranked_pool"] is True


def test_maps_file_overrides(tmp_path):
    overrides = tmp_path / "ov.yaml"
    overrides.write_text(
        yaml.safe_dump({"overrides": {"poi_test_0": {"title": "Custom Title", "ranked_pool": True}}}),
        encoding="utf-8",
    )
    catalog = tmp_path / "catalog"
    assert (
        run_import(
            FIXTURE_POI_MINI,
            REPO_ROOT,
            catalog,
            dry_run=False,
            force=True,
            maps_file=overrides,
            content_version="o",
        )
        == 0
    )
    maps = yaml.safe_load((catalog / "maps.yaml").read_text(encoding="utf-8"))
    row0 = next(m for m in maps["maps"] if m["map_id"] == "poi_test_0")
    assert row0["title"] == "Custom Title"
    assert row0["ranked_pool"] is True


def test_plan_import_duplicate_source_ids(tmp_path):
    dup_root = tmp_path / "bad"
    dup_root.mkdir()
    bad_manifest = {"points": [{"poi_id": "x", "latitude": 0, "longitude": 0, "mapbox": {"path": "", "skipped": True}}] * 2}
    (dup_root / "geoguessr_poi_manifest.json").write_text(json.dumps(bad_manifest), encoding="utf-8")
    with pytest.raises(CatalogImportError, match="Duplicate"):
        plan_import(dup_root, REPO_ROOT, tmp_path / "cat", force=True, map_overrides={}, ranked_split=None)
