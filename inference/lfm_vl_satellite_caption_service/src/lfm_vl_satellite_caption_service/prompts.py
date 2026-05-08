"""Versioned user prompts for satellite / aerial captioning (coordinate-free when ranked-safe)."""

from __future__ import annotations

_NON_RANKED_SAFE = "You may include any geographic clues that help identify the location."

_RANKED_SAFE_TRANSFORMERS = (
    "Focus on detailed visual clues such as vegetation types, land use, road patterns, water bodies, terrain, and shadows."
)
_RANKED_SAFE_OPENAI = (
    "Focus on detailed visual clues such as vegetation, land cover, built structures, road layouts, and geographic context."
)


def _safe_addon(*, ranked_clue_safe: bool, openai: bool) -> str:
    if ranked_clue_safe:
        return _RANKED_SAFE_OPENAI if openai else _RANKED_SAFE_TRANSFORMERS
    return _NON_RANKED_SAFE


def _profile_context(analysis_profile: str | None, contract_id: str | None) -> str:
    parts: list[str] = []
    if analysis_profile:
        parts.append(f"PRO analysis profile: {analysis_profile}.")
    if contract_id:
        parts.append(f"Output contract: {contract_id}.")
    if not parts:
        return ""
    return " " + " ".join(parts)


def satellite_transformers_user_prompt(
    *,
    ranked_clue_safe: bool,
    analysis_profile: str | None = None,
    contract_id: str | None = None,
) -> str:
    safe = _safe_addon(ranked_clue_safe=ranked_clue_safe, openai=False)
    return (
        "Provide a detailed description of this satellite or aerial image that would help someone infer its location. "
        "Emphasize vegetation, land cover, terrain, infrastructure, road networks, water features, and spatial patterns. "
        f"{safe}{_profile_context(analysis_profile, contract_id)}"
    )


def satellite_openai_user_prompt(
    *,
    ranked_clue_safe: bool,
    analysis_profile: str | None = None,
    contract_id: str | None = None,
) -> str:
    safe = _safe_addon(ranked_clue_safe=ranked_clue_safe, openai=True)
    return (
        "Describe this satellite image with rich geographic detail to help identify where it might be. "
        "Focus on vegetation, land cover, built areas, road systems, water bodies, and overall geographic context. "
        f"{safe}{_profile_context(analysis_profile, contract_id)}"
    )