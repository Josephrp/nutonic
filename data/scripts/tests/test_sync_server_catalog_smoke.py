from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _manifest_demo_still_only(path: Path) -> None:
    """
    Minimal manifest whose ``still_bundle_id`` is always in committed ``bundles/registry.json``
    and backed by ``nutonic.bundle.v1.demo_still.jpg`` (see ``server/pyproject.toml``).

    Shipped ``composeResources/.../manifest.full.json`` tracks product hydration and may list
    POI still ids without compose JPEGs or bundle rows on CI — do not use it for this smoke test.
    """
    path.write_text(
        json.dumps(
            {
                "content_version": "nutonic.manifest.smoke.sync_catalog.v1",
                "engine_version": "0.1.0",
                "maps": [
                    {
                        "map_id": "demo",
                        "title": "Demo mission",
                        "engine_version": "0.1.0",
                        "content_version": None,
                    },
                ],
                "locations": [
                    {
                        "map_id": "demo",
                        "location_id": "demo-vienna-001",
                        "truth_lat": 48.2082,
                        "truth_lon": 16.3738,
                        "ruleset_version": "nutonic.ruleset.v1",
                        "still_bundle_id": "nutonic.bundle.v1.demo_still",
                        "still_bundled_resource": "files/3.jpg",
                        "still_http_url": None,
                        "useful_hints": {"tier_1": "a", "tier_2": "b", "tier_3": "c"},
                        "play_budget_ms": 180_000,
                        "ai_marker_phase_enabled": True,
                    },
                ],
                "ai_guesses": [],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def test_sync_server_catalog_dry_run_diff_exits_zero(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    script = repo / "data" / "scripts" / "sync_server_catalog.py"
    manifest = tmp_path / "manifest.full.json"
    _manifest_demo_still_only(manifest)
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


def test_sync_server_catalog_sql_mode_prints_ddl(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    script = repo / "data" / "scripts" / "sync_server_catalog.py"
    manifest = tmp_path / "manifest.full.json"
    _manifest_demo_still_only(manifest)
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
