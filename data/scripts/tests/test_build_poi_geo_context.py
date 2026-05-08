"""Tests for build_poi_geo_context — fixture geo (no full Natural Earth download)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import pandas as pd

from build_poi_geo_context import _series_idxmin_safe, main, pick_projected_crs, resolve_vector_path, run_build
from catalog_import_poi import run_import

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_GEO = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "geo"
FIXTURE_POI_MINI = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "poi_mini"


def test_series_idxmin_safe_all_nan():
    s = pd.Series([float("nan"), float("nan")], index=[10, 20])
    assert _series_idxmin_safe(s) is None


def test_series_idxmin_safe_finds_min():
    s = pd.Series([3.0, 1.0, 2.0], index=["a", "b", "c"])
    assert _series_idxmin_safe(s) == "b"


def test_pick_projected_crs_utm_vs_mercator():
    assert pick_projected_crs(20.25, 10.5).startswith("EPSG:32")
    assert pick_projected_crs(0.0, 85.0) == "EPSG:3857"


def test_resolve_vector_path_finds_geojson():
    p = resolve_vector_path(FIXTURE_GEO, "ne_50m_admin_0_countries")
    assert p is not None and p.suffix == ".geojson"


def test_run_build_missing_layers_exit_6(tmp_path: Path):
    empty_geo = tmp_path / "geo"
    empty_geo.mkdir()
    (empty_geo / "MANIFEST.json").write_text('{"natural_earth_version": "x"}', encoding="utf-8")
    catalog = tmp_path / "catalog"
    (catalog / "locations").mkdir(parents=True)
    (catalog / "locations" / "a.yaml").write_text(
        "location_id: a\ntruth_lat: 0\ntruth_lon: 0\n", encoding="utf-8"
    )
    assert run_build(catalog, empty_geo, tmp_path / "out", r_max_km=50.0, r_scale_k=3.0) == 6


def test_run_build_happy_path_fixture_geo(tmp_path: Path):
    catalog = tmp_path / "catalog"
    assert run_import(FIXTURE_POI_MINI, REPO_ROOT, catalog, dry_run=False, force=True, maps_file=None, content_version="t") == 0
    out_dir = tmp_path / "geo_context"
    rc = run_build(catalog, FIXTURE_GEO, out_dir, r_max_km=200.0, r_scale_k=3.0)
    assert rc == 0
    p0 = out_dir / "poi_test_0.json"
    assert p0.is_file()
    ctx = json.loads(p0.read_text(encoding="utf-8"))
    assert ctx["schema_version"] == "nutonic.geo_context.v1"
    assert ctx["location_id"] == "poi_test_0"
    assert ctx["admin0_name"] == "Fixtureland"
    assert ctx["admin1_name"] == "North Fixture"
    assert ctx["continent"] == "Africa"
    assert ctx["nearest_river"]["name"] == "Fixture River"
    assert ctx["nearest_river"]["distance_km"] is not None
    assert ctx["nearest_lake"]["name"] == "Fixture Pond"
    assert ctx["nearest_lake"]["distance_km"] is not None
    assert ctx["coast_distance_km"] is not None
    assert ctx["coast_distance_km"] > 50.0
    assert ctx["sources"]["natural_earth_version"] == "test-fixture-1"
    facts = ctx.get("hint_compile_facts") or {}
    assert facts.get("schema_version") == "nutonic.hint_compile_facts.v1"
    assert facts.get("continent") == "Africa"
    assert facts.get("river_proximity") in ("immediate", "near", "regional", "distant", "none")


def test_main_cli_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = tmp_path / "catalog"
    assert run_import(FIXTURE_POI_MINI, REPO_ROOT, catalog, dry_run=False, force=True, maps_file=None, content_version="cli") == 0
    out = tmp_path / "gc"
    monkeypatch.chdir(REPO_ROOT)
    code = main(
        [
            "--catalog-root",
            str(catalog),
            "--geo-root",
            str(FIXTURE_GEO),
            "--output-dir",
            str(out),
        ]
    )
    assert code == 0
    assert (out / "poi_test_1.json").is_file()
