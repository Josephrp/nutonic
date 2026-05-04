"""Production-analysis TiM + VLM prompts — keep in sync with ``lfm_vl_sft_dataset/production_analysis_prompt.py``."""

from __future__ import annotations

import json
from typing import Any

# Mirror ``lfm_vl_sft_dataset.pro_prompts.PRODUCTION_ANALYSIS_SYSTEM`` (single string for deployment bundles).
PRODUCTION_ANALYSIS_SYSTEM = (
    "You are a geospatial analyst specializing in satellite imagery interpretation. "
    "Analyze the provided Sentinel-2 satellite images and report findings grounded in visible evidence. "
    "Use [x1, y1, x2, y2] bounding boxes normalized to 0-1 relative to image dimensions. "
    "This is optical-only observation. Avoid certainty claims beyond visible evidence, "
    "and state confidence and limitations where appropriate. "
    "You receive Sentinel-2 imagery plus a compact TiM-style analytics JSON block (model-shaped signals). "
    "Write an analytical summary grounded in the images and that JSON; distinguish what you infer from "
    "the optical chip from TiM-predicted signals encoded in the JSON."
)


def compact_tim_from_summary(tim_summary: dict[str, Any] | None) -> dict[str, Any]:
    """Same cap as Patagonia eval / ``compact_tim_for_production_prompt``."""
    row = tim_summary if isinstance(tim_summary, dict) else {}
    tmo = row.get("tim_modality_outputs")
    pa = row.get("profile_analytics")
    return {
        "tim_modality_outputs": tmo if isinstance(tmo, dict) else {},
        "profile_analytics": pa if isinstance(pa, dict) else {},
    }


def build_production_tim_user_prompt(*, analysis_profile: str, tim_compact_json: dict[str, Any]) -> str:
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
