"""Tests for export_terramind_assessment_seed_aois (poi-root layout)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_export_poi_root_writes_jsonl(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    fx = repo / "data" / "scripts" / "tests" / "fixtures" / "poi_mini"
    out = tmp_path / "seeds.jsonl"
    cmd = [
        sys.executable,
        str(repo / "data" / "scripts" / "export_terramind_assessment_seed_aois.py"),
        "poi-root",
        "--poi-root",
        str(fx),
        "--out",
        str(out),
        "--default-profile",
        "brief_only",
    ]
    r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr + r.stdout
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    row0 = json.loads(lines[0])
    assert "lat" in row0 and "lon" in row0
    assert row0["map_id"] == "poi_test_0"


def test_export_sat_bbox_sft_from_metadata(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    fx = repo / "data" / "scripts" / "tests" / "fixtures" / "sat_bbox_sft_mini"
    out = tmp_path / "seeds_sat.jsonl"
    cmd = [
        sys.executable,
        str(repo / "data" / "scripts" / "export_terramind_assessment_seed_aois.py"),
        "sat-bbox-sft",
        "--dataset-root",
        str(fx),
        "--split",
        "train",
        "--out",
        str(out),
        "--default-profile",
        "brief_only",
    ]
    r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr + r.stdout
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    row0 = json.loads(lines[0])
    assert row0["map_id"] == "poi_000099"
    assert abs(row0["lat"] - 51.405) < 1e-6
    assert abs(row0["lon"] - (-0.095)) < 1e-6


def test_export_sat_bbox_sft_from_poi_latlon_sidecar(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    jl = data_dir / "train.jsonl"
    jl.write_text(
        '{"messages":[{"role":"user","content":[{"type":"image","image":"images/s00001/poi_000001_t0000.png"}]}]}\n',
        encoding="utf-8",
    )
    side = tmp_path / "poi_ll.jsonl"
    side.write_text(
        '{"poi_id":"poi_000001","latitude":10.5,"longitude":20.25}\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.jsonl"
    cmd = [
        sys.executable,
        str(repo / "data" / "scripts" / "export_terramind_assessment_seed_aois.py"),
        "sat-bbox-sft",
        "--dataset-root",
        str(tmp_path),
        "--poi-latlon-jsonl",
        str(side),
        "--out",
        str(out),
    ]
    r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr + r.stdout
    row0 = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row0["map_id"] == "poi_000001"
    assert row0["lat"] == 10.5 and row0["lon"] == 20.25
