from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_validate_shipped_compose_resources_ok() -> None:
    repo = Path(__file__).resolve().parents[3]
    script = repo / "data" / "scripts" / "validate_shipped_compose_resources.py"
    r = subprocess.run([sys.executable, str(script)], cwd=repo, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr + r.stdout
