"""Tests for compile_useful_hint_tiers.py — six coordinate-free tiers."""

from __future__ import annotations

import json
from pathlib import Path

from build_poi_geo_context import run_build
from catalog_import_poi import run_import
from compile_useful_hint_tiers import compile_one, run_compile

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_GEO = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "geo"
FIXTURE_POI_MINI = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "poi_mini"
POLICY = REPO_ROOT / "data" / "scripts" / "tier_policy.default.yaml"


def test_compile_one_round_trip(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    assert run_import(FIXTURE_POI_MINI, REPO_ROOT, catalog, dry_run=False, force=True, maps_file=None, content_version="t") == 0
    geo_dir = tmp_path / "geo_context"
    assert run_build(catalog, FIXTURE_GEO, geo_dir, r_max_km=200.0, r_scale_k=3.0) == 0
    geo = json.loads((geo_dir / "poi_test_0.json").read_text(encoding="utf-8"))
    import yaml

    pol = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    out = compile_one(geo, pol)
    assert out["location_id"] == "poi_test_0"
    uh = out["useful_hints"]
    assert set(uh) == {f"tier_{i}" for i in range(1, 7)}
    for i in range(1, 7):
        assert len(uh[f"tier_{i}"]) > 10
    assert "Fixtureland" in uh["tier_5"] or "Fixtureland" in uh["tier_6"]


def test_run_compile_writes_validated_json(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    assert run_import(FIXTURE_POI_MINI, REPO_ROOT, catalog, dry_run=False, force=True, maps_file=None, content_version="t") == 0
    geo_dir = tmp_path / "geo_context"
    assert run_build(catalog, FIXTURE_GEO, geo_dir, r_max_km=200.0, r_scale_k=3.0) == 0
    out_dir = tmp_path / "useful_hints"
    rc = run_compile(geo_dir, POLICY, out_dir, skip_validate=False)
    assert rc == 0
    p0 = out_dir / "poi_test_0.json"
    assert p0.is_file()
    data = json.loads(p0.read_text(encoding="utf-8"))
    assert data["facts_used"]["continent"] == "Africa"
    assert (out_dir / "poi_test_1.json").is_file()
