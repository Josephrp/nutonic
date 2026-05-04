"""Patagonia TiM E2E — re-exports production-analysis prompts from SFT package."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SFT_SCRIPTS = _REPO_ROOT / "data" / "scripts"
if str(_SFT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SFT_SCRIPTS))

from lfm_vl_sft_dataset.production_analysis_prompt import (  # noqa: E402
    PRODUCTION_ANALYSIS_SYSTEM,
    build_production_tim_user_prompt,
    compact_tim_for_production_prompt,
)

__all__ = ["PRODUCTION_ANALYSIS_SYSTEM", "build_production_tim_user_prompt", "compact_tim_for_production_prompt"]
