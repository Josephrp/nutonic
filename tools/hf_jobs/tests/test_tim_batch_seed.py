"""Tests for ``tim_batch_seed`` merge (no torch)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_HFJ = Path(__file__).resolve().parents[1]
if str(_HFJ) not in sys.path:
    sys.path.insert(0, str(_HFJ))

from tim_batch_seed import apply_tim_batch_seed_to_config, load_tim_batch_seed, tim_batch_seed_rows_from_catalog


def test_apply_tim_batch_seed_replaces_batch(tmp_path: Path) -> None:
    base = {
        "content_version": "test",
        "model_id": "m",
        "pretrained": True,
        "merge_method": "mean",
        "modalities": ["RGB", "S2L2A"],
        "tim_modalities": ["LULC", "NDVI", "location"],
        "device": "cpu",
        "inputs": {"batch_size": 1, "s2_mode": "stac", "datetime": "2026-01-10/2026-04-10", "s2": {}},
        "batch": [
            {
                "map_id": "poi_0000",
                "location_id": "poi_0000",
                "rgb_mode": "s2_rgb",
                "lat": 1.0,
                "lon": 2.0,
                "datetime": "2026-01-10/2026-04-10",
                "s2_mode": "stac",
            }
        ],
    }
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            {
                "schema_version": "nutonic.tim_batch_seed.v1",
                "content_version": "x",
                "rows": [
                    {"map_id": "a", "location_id": "lid_a", "truth_lat": 10.0, "truth_lon": 20.0},
                    {"map_id": "b", "location_id": "lid_b", "truth_lat": -5.0, "truth_lon": 30.0},
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    seed = load_tim_batch_seed(seed_path)
    merged = apply_tim_batch_seed_to_config(base, seed)
    assert len(merged["batch"]) == 2
    assert merged["batch"][0]["location_id"] == "lid_a"
    assert merged["batch"][0]["lat"] == 10.0
    assert merged["batch"][0]["lon"] == 20.0
    assert merged["batch"][0]["rgb_mode"] == "s2_rgb"
    assert merged["batch"][1]["location_id"] == "lid_b"


def test_tim_batch_seed_rows_from_catalog_order(tmp_path: Path) -> None:
    loc = tmp_path / "locations"
    loc.mkdir(parents=True)
    (loc / "poi_z.yaml").write_text(
        "location_id: poi_z\nmap_id: m_z\ntruth_lat: 1.5\ntruth_lon: -2.5\n",
        encoding="utf-8",
    )
    (loc / "poi_a.yaml").write_text(
        "location_id: poi_a\nmap_id: m_a\ntruth_lat: 0.0\ntruth_lon: 1.0\n",
        encoding="utf-8",
    )
    rows = tim_batch_seed_rows_from_catalog(location_ids=["poi_z", "poi_a"], catalog_locations_dir=loc)
    assert [r["location_id"] for r in rows] == ["poi_z", "poi_a"]
    assert rows[0]["truth_lat"] == 1.5


def test_roundtrip_yaml_snippet(tmp_path: Path) -> None:
    """Ensure merged config is valid YAML for ``nutonic_terramind_tim_local`` CLI."""
    ypath = tmp_path / "base.yaml"
    ypath.write_text(
        yaml.dump(
            {
                "content_version": "cv",
                "model_id": "terramind_v1_large_tim",
                "pretrained": True,
                "merge_method": "mean",
                "modalities": ["RGB", "S2L2A"],
                "tim_modalities": ["LULC", "NDVI", "location"],
                "device": "cpu",
                "inputs": {
                    "batch_size": 1,
                    "s2_mode": "stac",
                    "datetime": "2026-01-10/2026-04-10",
                    "s2": {"half_km": 14.0},
                },
                "batch": [
                    {
                        "map_id": "x",
                        "location_id": "x",
                        "rgb_mode": "s2_rgb",
                        "lat": 0.0,
                        "lon": 0.0,
                        "datetime": "2026-01-10/2026-04-10",
                        "s2_mode": "stac",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cfg = yaml.safe_load(ypath.read_text(encoding="utf-8"))
    seed = {
        "schema_version": "nutonic.tim_batch_seed.v1",
        "rows": [{"map_id": "p1", "location_id": "p1", "truth_lat": -10.0, "truth_lon": 50.0}],
    }
    merged = apply_tim_batch_seed_to_config(cfg, seed)
    out = tmp_path / "merged.yaml"
    out.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
    roundtrip = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(roundtrip["batch"]) == 1
    assert roundtrip["batch"][0]["lat"] == -10.0
