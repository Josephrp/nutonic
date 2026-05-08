"""Production-analysis VLM user prompts (TiM JSON + task footer).

Aligned with ``sat_bbox_metadata_sft`` ``production_analysis`` rows and Patagonia TiM E2E eval.
"""

from __future__ import annotations

import json
from typing import Any

from lfm_vl_sft_dataset.pro_prompts import PRODUCTION_ANALYSIS_SYSTEM, PRO_ON_DEVICE_VLM_USER_INSTRUCTION_LINES

__all__ = [
    "PRODUCTION_ANALYSIS_SYSTEM",
    "build_production_tim_user_prompt",
    "build_production_no_tim_user_prompt",
    "compact_tim_for_production_prompt",
]


BOX_OUTPUT_FOOTER = (
    "\n\n"
    "Output format requirement:\n"
    "- First: a concise caption (1–3 sentences).\n"
    "- Then: strict JSON with key `boxes` (array). Each item must be `{label,bbox,confidence}` where "
    "`bbox` is [x1,y1,x2,y2] normalized to 0..1 and `confidence` is 0..1.\n"
    "- If no meaningful boxes can be supported by visible evidence, return `{\"boxes\": []}`."
)


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
    return (
        "\n".join(
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
        + BOX_OUTPUT_FOOTER
        + "\n\n"
        + PRO_ON_DEVICE_VLM_USER_INSTRUCTION_LINES
    )


def build_production_no_tim_user_prompt(*, analysis_profile: str) -> str:
    """
    Production-like analysis prompt for image-only evaluation (no TiM JSON present).

    Uses the same header/footer contract as TiM prompts, but explicitly notes that no TiM JSON is provided.
    """
    return (
        "\n".join(
            [
                "Production-like analysis input:",
                f"- analysis_profile: {analysis_profile}",
                "- Image sequence:",
                "  1. Sentinel-2 RGB still for visual interpretation (single-chip Patagonia eval; no separate metadata dump).",
                "- TiM-style analytics JSON: not provided for this run (image-only baseline).",
                "",
                "Task: write the application-specific analytical summary grounded in the Sentinel-2 imagery. "
                "Call out uncertainty, confidence, and limitations.",
            ]
        )
        + BOX_OUTPUT_FOOTER
        + "\n\n"
        + PRO_ON_DEVICE_VLM_USER_INSTRUCTION_LINES
    )
