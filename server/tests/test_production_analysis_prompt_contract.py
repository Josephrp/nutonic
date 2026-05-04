"""Ensure server prompt helpers stay aligned with ``lfm_vl_sft_dataset``."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_production_analysis_system_matches_data_scripts() -> None:
    sys.path.insert(0, str(_ROOT / "data" / "scripts"))
    from lfm_vl_sft_dataset.pro_prompts import PRODUCTION_ANALYSIS_SYSTEM as ref

    from nutonic_server.production_analysis_prompt import PRODUCTION_ANALYSIS_SYSTEM

    assert PRODUCTION_ANALYSIS_SYSTEM == ref


def test_build_production_tim_user_prompt_matches_data_scripts() -> None:
    sys.path.insert(0, str(_ROOT / "data" / "scripts"))
    from lfm_vl_sft_dataset.production_analysis_prompt import (
        build_production_tim_user_prompt as ref_build,
    )

    from nutonic_server.production_analysis_prompt import build_production_tim_user_prompt

    compact = {"tim_modality_outputs": {"x": 1}, "profile_analytics": {}}
    a = ref_build(analysis_profile="brief_only", tim_compact_json=compact)
    b = build_production_tim_user_prompt(analysis_profile="brief_only", tim_compact_json=compact)
    assert a == b
