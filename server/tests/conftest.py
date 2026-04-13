"""Pytest bootstrap: ensure `src/` is on `sys.path` for `import nutonic_server` (editable installs vary by platform)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Hermetic SQLite (StaticPool) before `nutonic_server.main` imports the global store (IMP-060).
os.environ.setdefault(
    "NUTONIC_LEADERBOARD_DATABASE_URL",
    "sqlite+pysqlite:///:memory:",
)

_server_root = Path(__file__).resolve().parents[1]
_src = _server_root / "src"
if _src.is_dir():
    sys.path.insert(0, str(_src))
