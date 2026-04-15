from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_sync_server_catalog_dry_run_diff_exits_zero() -> None:
    repo = Path(__file__).resolve().parents[3]
    script = repo / "data" / "scripts" / "sync_server_catalog.py"
    manifest = (
        repo
        / "nutonic"
        / "shared"
        / "src"
        / "commonMain"
        / "composeResources"
        / "files"
        / "cache"
        / "manifest.full.json"
    )
    r = subprocess.run(
        [sys.executable, str(script), "--manifest", str(manifest)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr


def test_sync_server_catalog_rejects_unknown_still_bundle_id(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    script = repo / "data" / "scripts" / "sync_server_catalog.py"
    bad_manifest = {
        "content_version": "nutonic.test.bad_bundle",
        "engine_version": "0.0.0",
        "maps": [{"map_id": "m_x", "title": "t", "engine_version": None, "content_version": None}],
        "locations": [
            {
                "map_id": "m_x",
                "location_id": "loc_x",
                "truth_lat": 1.0,
                "truth_lon": 2.0,
                "still_bundle_id": "nutonic.bundle.v99.not_in_registry",
                "still_bundled_resource": None,
            }
        ],
        "ai_guesses": [],
    }
    mf = tmp_path / "manifest.full.json"
    mf.write_text(json.dumps(bad_manifest), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(script), "--manifest", str(mf)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 14, (r.stderr, r.stdout)
    err = (r.stderr or "") + (r.stdout or "")
    assert "not listed" in err or "missing filename" in err or "Bundle registry file problems" in err


def test_sync_server_catalog_sql_mode_prints_ddl() -> None:
    repo = Path(__file__).resolve().parents[3]
    script = repo / "data" / "scripts" / "sync_server_catalog.py"
    manifest = (
        repo
        / "nutonic"
        / "shared"
        / "src"
        / "commonMain"
        / "composeResources"
        / "files"
        / "cache"
        / "manifest.full.json"
    )
    r = subprocess.run(
        [sys.executable, str(script), "--manifest", str(manifest), "--mode", "sql"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "CREATE TABLE IF NOT EXISTS nutonic_catalog_maps" in out
    assert "INSERT INTO nutonic_catalog_locations" in out
    assert "COMMIT;" in out
