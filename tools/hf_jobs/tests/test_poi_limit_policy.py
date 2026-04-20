"""Tests for POI limit vs. required Hub trees and catalog import root."""

from __future__ import annotations

import sys
from pathlib import Path

_HFJ = Path(__file__).resolve().parents[1]
if str(_HFJ) not in sys.path:
    sys.path.insert(0, str(_HFJ))

import entrypoint_hf_hydration as ep


def test_required_poi_trees_unlimited(monkeypatch) -> None:
    monkeypatch.delenv("NUTONIC_POI_LIMIT", raising=False)
    assert ep._required_poi_trees() == ("geoguessr_poi_12", "geoguessr_poi_120")


def test_required_poi_trees_small_limit(monkeypatch) -> None:
    monkeypatch.setenv("NUTONIC_POI_LIMIT", "8")
    assert ep._required_poi_trees() == ("geoguessr_poi_12",)


def test_required_poi_trees_large_limit(monkeypatch) -> None:
    monkeypatch.setenv("NUTONIC_POI_LIMIT", "40")
    assert ep._required_poi_trees() == ("geoguessr_poi_12", "geoguessr_poi_120")


def _touch_layout_b(root: Path, poi_name: str) -> None:
    p = root / poi_name / "poi.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")


def test_limited_catalog_root_prefers_120(monkeypatch, tmp_path: Path) -> None:
    dd = tmp_path / "data" / "downloads"
    _touch_layout_b(dd / "geoguessr_poi_12", "poi_0000")
    _touch_layout_b(dd / "geoguessr_poi_120", "poi_0000")
    monkeypatch.setattr(ep, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("NUTONIC_POI_LIMIT", "70")
    assert ep._limited_catalog_poi_root().resolve() == (dd / "geoguessr_poi_120").resolve()


def test_limited_catalog_root_small_limit(monkeypatch, tmp_path: Path) -> None:
    dd = tmp_path / "data" / "downloads"
    _touch_layout_b(dd / "geoguessr_poi_12", "poi_0000")
    _touch_layout_b(dd / "geoguessr_poi_120", "poi_0000")
    monkeypatch.setattr(ep, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("NUTONIC_POI_LIMIT", "5")
    assert ep._limited_catalog_poi_root().resolve() == (dd / "geoguessr_poi_12").resolve()
