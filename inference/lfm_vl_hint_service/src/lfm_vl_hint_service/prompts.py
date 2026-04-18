"""Versioned system prompts for Street View captioning (coordinate-free tiers enforced downstream)."""

from __future__ import annotations

from lfm_vl_hint_service.models import SuggestionsFromFramesRequest

def streetview_user_prompt(
    *,
    viewpoint_label: str,
    heading_deg: float | None,
    req: SuggestionsFromFramesRequest,
) -> str:
    """Single-frame user message (Liquid LFM-VL multi-modal chat)."""
    h = "" if heading_deg is None else f"Camera heading is roughly {heading_deg:.0f} degrees. "
    safe = (
        "Produce a richly detailed geographic description that captures as many visual signals as possible. "
        "Emphasize vegetation types (trees, shrubs, crops), landscape and terrain, climate indicators, and seasonal cues. "
        "Describe road structure, lane markings, signage styles, traffic direction, vehicle types, license plate formats, and street furniture. "
        "Include architecture styles, building materials, density, urban planning patterns, and construction details. "
        "Transcribe and analyze any visible text such as store names, advertisements, road signs, and note the language, script, and formatting. "
        "Highlight subtle regional markers such as utility poles, fencing styles, sidewalks, drainage, and public infrastructure."
        if req.ranked_clue_safe
        else "Produce a richly detailed geographic description focusing on vegetation, terrain, climate, roads, vehicles, signage, language, architecture, and infrastructure. "
        "Capture all observable details that could inform regional identification."
    )
    return (
        f"{h}Describe this street-level photograph for viewpoint {viewpoint_label!r} with a dense, information-rich summary. "
        f"{safe} "
        "Synthesize observations into a cohesive description that surfaces distinctive geographic patterns and clues."
    )


def narrative_system_prompt() -> str:
    return (
        "You combine multiple street-level scene descriptions into a single cohesive geographic narrative for a location-guessing assist panel. "
        "Integrate and reinforce clues about vegetation, terrain, climate, signage, visible language, store names, architecture, road systems, vehicles, and infrastructure. "
        "Highlight consistent patterns across viewpoints and emphasize distinctive regional signals. "
        "Write a fluid, information-dense paragraph that helps a reader infer the broader geographic context while staying grounded in the provided observations. "
    #   "Keep the paragraph under 800 characters."
    )


def narrative_user_payload(captions: list[tuple[str, str]]) -> str:
    lines = "\n".join(f"- {vid}: {txt}" for vid, txt in captions)
    return (
        f"Captions:\n{lines}\n\n"
        "Write one cohesive paragraph that synthesizes these descriptions into a clear, information-rich geographic summary, "
        "highlighting the strongest clues for identifying the likely region."
    )
