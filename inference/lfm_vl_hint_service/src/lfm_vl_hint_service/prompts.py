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
        "Do not output latitude, longitude, GPS coordinates, or comma-separated decimal degree pairs. "
        "Do not name countries, cities, famous landmarks, or street signs that reveal a specific place. "
        "Focus on road geometry, vegetation, architecture materials, weather, and generic urban vs rural cues."
        if req.ranked_clue_safe
        else "Avoid outputting raw latitude/longitude numbers."
    )
    return (
        f"{h}Describe this street-level photograph in at most two short sentences for viewpoint {viewpoint_label!r}. "
        f"{safe} "
        "Do not transcribe readable text from signs."
    )


def narrative_system_prompt() -> str:
    return (
        "You fuse short street scene captions into one cohesive paragraph for a geography game's assist panel. "
        "Do not add new place names or coordinates. Keep under 800 characters."
    )


def narrative_user_payload(captions: list[tuple[str, str]]) -> str:
    lines = "\n".join(f"- {vid}: {txt}" for vid, txt in captions)
    return f"Captions:\n{lines}\n\nWrite one fused neutral paragraph."
