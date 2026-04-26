"""Pytest fixtures: ensure `data/scripts` is importable as a flat module root."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "data" / "scripts"
_scripts = str(SCRIPTS_DIR)
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)
