"""Opt-in TerraTorch TiM smoke tests (heavy deps + HF weights)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_TERRATORCH_TIM") != "1",
    reason="Set RUN_TERRATORCH_TIM=1 to download weights and run TerraTorch TiM smoke tests",
)


def test_run_tim_forward_export_minimal_yaml(tmp_path: Path) -> None:
    from nutonic_terramind_tim_local.run import load_run_config, run_tim_forward_export, write_json

    cfg_path = Path(__file__).resolve().parents[1] / "config.example.yaml"
    cfg = load_run_config(cfg_path)
    cfg["device"] = "cpu"
    cfg.setdefault("export", {})["map_id"] = "t_map"
    cfg.setdefault("export", {})["location_id"] = "t_loc"
    row = run_tim_forward_export(cfg)
    assert row["map_id"] == "t_map"
    assert row["engine"]["patch_diagnostics"]["diagnostics_version"] == "nutonic.terramind_patches.v1"
    assert "tim_modality_outputs" in row
    assert "Coordinates" in row["tim_modality_outputs"]
    assert "ai_lat" in row and "ai_lon" in row
    write_json(tmp_path / "x.json", row)
    assert tmp_path.joinpath("x.json").is_file()


def test_batch_two_rows(tmp_path: Path) -> None:
    from nutonic_terramind_tim_local.run import load_run_config, run_tim_batch_export

    cfg_path = Path(__file__).resolve().parents[1] / "config.example.yaml"
    cfg = load_run_config(cfg_path)
    cfg["device"] = "cpu"
    cfg["batch"] = [
        {"map_id": "a", "location_id": "a", "rgb_mode": "random"},
        {"map_id": "b", "location_id": "b", "rgb_mode": "random"},
    ]
    rows = run_tim_batch_export(cfg)
    assert len(rows) == 2
    assert rows[0]["map_id"] == "a"
    p = tmp_path / "batch.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
