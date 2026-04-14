from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "data" / "scripts"
STUB_PNG = REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "maps" / "reuse_stub.png"


def _write_minimal_catalog(catalog_root: Path, bundled_rel: str) -> None:
    loc = catalog_root / "locations"
    loc.mkdir(parents=True, exist_ok=True)
    row = {
        "location_id": "loc_ci_still",
        "map_id": "loc_ci_still",
        "truth_lat": 10.5,
        "truth_lon": 20.25,
        "assist_level": "standard",
        "still_source": {"bundled_relative": bundled_rel},
    }
    (loc / "loc_ci_still.yaml").write_text(yaml.safe_dump(row, sort_keys=True), encoding="utf-8")


def test_reuse_only_writes_jpeg_and_index(tmp_path: Path) -> None:
    assert STUB_PNG.is_file(), "reuse_stub.png should exist (generated once in repo)"
    catalog = tmp_path / "catalog"
    out_maps = tmp_path / "maps"
    meta = tmp_path / "meta"
    rel = STUB_PNG.relative_to(REPO_ROOT).as_posix()
    _write_minimal_catalog(catalog, rel)

    cmd = [
        sys.executable,
        str(SCRIPTS / "render_mapbox_still.py"),
        "--catalog-root",
        str(catalog),
        "--compose-resources-maps-dir",
        str(out_maps),
        "--meta-dir",
        str(meta),
        "--reuse-only",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    assert proc.returncode == 0

    jpg = out_maps / "loc_ci_still.jpg"
    assert jpg.is_file()
    Image.open(jpg).verify()

    idx = json.loads((meta / "still_index.json").read_text(encoding="utf-8"))
    assert len(idx["locations"]) == 1
    row = idx["locations"][0]
    assert row["still_bundled_resource"] == "files/maps/loc_ci_still.jpg"
    assert row["still_sha256"] and len(row["still_sha256"]) == 64
    assert row["width_px"] > 0 and row["height_px"] > 0

    meta_one = json.loads((meta / "stills" / "loc_ci_still.meta.json").read_text(encoding="utf-8"))
    assert meta_one["still_sha256"] == row["still_sha256"]


def test_reuse_only_missing_bundled_exits_nonzero(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    _write_minimal_catalog(catalog, "data/scripts/tests/fixtures/maps/does_not_exist.png")
    cmd = [
        sys.executable,
        str(SCRIPTS / "render_mapbox_still.py"),
        "--catalog-root",
        str(catalog),
        "--compose-resources-maps-dir",
        str(tmp_path / "maps"),
        "--meta-dir",
        str(tmp_path / "meta"),
        "--reuse-only",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    assert proc.returncode != 0


def test_network_render_disabled_without_allow_network(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    loc = catalog / "locations"
    loc.mkdir(parents=True, exist_ok=True)
    row = {
        "location_id": "loc_net",
        "map_id": "loc_net",
        "truth_lat": 48.858844,
        "truth_lon": 2.294351,
        "assist_level": "standard",
        "still_source": {
            "render_policy": {
                "center_lat": 48.858844,
                "center_lon": 2.294351,
                "zoom": 11.0,
                "width_px": 256,
                "height_px": 256,
                "style": "satellite-v9",
            }
        },
    }
    (loc / "loc_net.yaml").write_text(yaml.safe_dump(row, sort_keys=True), encoding="utf-8")
    cmd = [
        sys.executable,
        str(SCRIPTS / "render_mapbox_still.py"),
        "--catalog-root",
        str(catalog),
        "--compose-resources-maps-dir",
        str(tmp_path / "maps"),
        "--meta-dir",
        str(tmp_path / "meta"),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    assert proc.returncode == 4


def test_mapbox_render_requires_token_when_allow_network(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    loc = catalog / "locations"
    loc.mkdir(parents=True, exist_ok=True)
    row = {
        "location_id": "loc_net",
        "map_id": "loc_net",
        "truth_lat": 48.858844,
        "truth_lon": 2.294351,
        "assist_level": "standard",
        "still_source": {
            "render_policy": {
                "center_lat": 48.858844,
                "center_lon": 2.294351,
                "zoom": 11.0,
                "width_px": 256,
                "height_px": 256,
                "style": "satellite-v9",
            }
        },
    }
    (loc / "loc_net.yaml").write_text(yaml.safe_dump(row, sort_keys=True), encoding="utf-8")
    cmd = [
        sys.executable,
        str(SCRIPTS / "render_mapbox_still.py"),
        "--catalog-root",
        str(catalog),
        "--compose-resources-maps-dir",
        str(tmp_path / "maps"),
        "--meta-dir",
        str(tmp_path / "meta"),
        "--allow-network",
    ]
    env = os.environ.copy()
    env.pop("MAPBOX_ACCESS_TOKEN", None)
    env.pop("MAPBOX_TOKEN", None)
    env["NUTONIC_NO_DOTENV"] = "1"
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, check=False)
    assert proc.returncode == 4
