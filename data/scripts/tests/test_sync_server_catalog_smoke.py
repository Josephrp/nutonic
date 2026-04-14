from __future__ import annotations

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
