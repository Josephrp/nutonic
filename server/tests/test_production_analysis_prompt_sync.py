"""Ensure server vendored prompt helpers stay aligned with ``lfm_vl_sft_dataset``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nutonic_server.production_analysis_prompt import (
    PRODUCTION_ANALYSIS_SYSTEM as SERVER_PA_SYSTEM,
    build_production_tim_user_prompt as server_build_user,
    compact_tim_from_summary as server_compact,
)


def test_compact_tim_matches_lfm_package() -> None:
    root = Path(__file__).resolve().parents[2]
    scripts = root / "data" / "scripts"
    if not scripts.is_dir():
        pytest.skip("monorepo data/scripts not present")
    sys.path.insert(0, str(scripts))
    from lfm_vl_sft_dataset.production_analysis_prompt import (  # noqa: PLC0415
        compact_tim_for_production_prompt as lfm_compact,
    )

    sample = {"tim_modality_outputs": {"a": 1}, "profile_analytics": {"b": 2}}
    assert server_compact(sample) == lfm_compact(sample)


def test_build_user_prompt_matches_lfm_package() -> None:
    root = Path(__file__).resolve().parents[2]
    scripts = root / "data" / "scripts"
    if not scripts.is_dir():
        pytest.skip("monorepo data/scripts not present")
    sys.path.insert(0, str(scripts))
    from lfm_vl_sft_dataset.production_analysis_prompt import (  # noqa: PLC0415
        build_production_tim_user_prompt as lfm_build,
    )

    compact = {"tim_modality_outputs": {}, "profile_analytics": {}}
    assert server_build_user(analysis_profile="land_use_change", tim_compact_json=compact) == lfm_build(
        analysis_profile="land_use_change", tim_compact_json=compact
    )


def test_production_analysis_system_matches_pro_prompts() -> None:
    root = Path(__file__).resolve().parents[2]
    scripts = root / "data" / "scripts"
    if not scripts.is_dir():
        pytest.skip("monorepo data/scripts not present")
    sys.path.insert(0, str(scripts))
    from lfm_vl_sft_dataset.pro_prompts import PRODUCTION_ANALYSIS_SYSTEM as LFM_PA_SYSTEM  # noqa: PLC0415

    assert SERVER_PA_SYSTEM == LFM_PA_SYSTEM
