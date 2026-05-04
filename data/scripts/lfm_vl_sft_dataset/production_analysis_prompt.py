"""Production-analysis VLM user prompts (TiM JSON + task footer).

Aligned with ``sat_bbox_metadata_sft`` ``production_analysis`` rows and Patagonia TiM E2E eval.
"""

from __future__ import annotations

import json
from typing import Any

from lfm_vl_sft_dataset.pro_prompts import PRODUCTION_ANALYSIS_SYSTEM

__all__ = ["PRODUCTION_ANALYSIS_SYSTEM", "build_production_tim_user_prompt", "compact_tim_for_production_prompt"]


def compact_tim_for_production_prompt(tim_row: dict[str, Any] | None) -> dict[str, Any]:
    """Same TiM cap shape as Patagonia eval and server ``compact_tim_from_summary``."""
    row = tim_row if isinstance(tim_row, dict) else {}
    tmo = row.get("tim_modality_outputs")
    pa = row.get("profile_analytics")
    return {
        "tim_modality_outputs": tmo if isinstance(tmo, dict) else {},
        "profile_analytics": pa if isinstance(pa, dict) else {},
    }


def build_production_tim_user_prompt(*, analysis_profile: str, tim_compact_json: dict[str, Any]) -> str:
    """
    User task text for one optical still + TiM JSON (Patagonia eval and single-chip PRO).

    Multi-image SFT rows use the same header/footer; image-sequence lines differ by dataset.
    """
    js = json.dumps(tim_compact_json, ensure_ascii=False, indent=2)
    return "\n".join(
        [
            "Production-like analysis input:",
            f"- analysis_profile: {analysis_profile}",
            "- Image sequence:",
            "  1. Sentinel-2 RGB still for visual interpretation (single-chip Patagonia eval; no separate metadata dump).",
            "- TiM-style analytics JSON (model-shaped; STAC / raw sidecar fields omitted):",
            js,
            "",
            "Task: write the application-specific analytical summary. Ground dominant land-cover claims in the "
            "Sentinel-2 imagery, then relate them to the TiM-shaped JSON above; call out increases, decreases, "
            "confidence, and limitations.",
        ]
    )
