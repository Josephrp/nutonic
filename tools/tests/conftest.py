"""Ensure ``tools/`` is importable as flat modules (``nutonic_hmac``, ``batch_streetview_hints``)."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
