"""Versioned system prompts for Street View captioning (coordinate-free tiers enforced downstream)."""

from __future__ import annotations

from typing import Any, Mapping

from lfm_vl_hint_service.models import SuggestionsFromFramesRequest

PRO_BRIEF_PROMPT_VERSION = "pro-brief-v2"

# Keep aligned with ``data/scripts/lfm_vl_sft_dataset/pro_prompts.py`` :: SYSTEM_ASSESSMENT.
_SYSTEM_ASSESSMENT_BRIEF = (
    "You are a geospatial analyst specializing in satellite imagery interpretation. "
    "Analyze the provided Sentinel-2 satellite images and report findings grounded in visible evidence. "
    "Use [x1, y1, x2, y2] bounding boxes normalized to 0-1 relative to image dimensions. "
    "This is optical-only observation. Avoid certainty claims beyond visible evidence, "
    "and state confidence and limitations where appropriate. "
    "TerraMind or TiM modality summaries are **auxiliary model evidence**, not field truth unless "
    "independently validated. Never treat pseudo-SAR-like or optical-only signals as legal or operational "
    "confirmation of activity."
)

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
        "Frames from the same batch may be nearby samples around the same map context; treat them as complementary views, "
        "not a requirement for any single camera geometry. "
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


def pro_brief_system_prompt(profile: str) -> str:
    return (
        f"{_SYSTEM_ASSESSMENT_BRIEF} "
        "You synthesize conservative NU:TONIC PRO mini-app briefs from machine-readable artifacts only. "
        f"Profile: {profile}. Use only the provided TiM summary, artifact refs, and job metadata. "
        "Do not invent observations, scene IDs, coordinates, incident causes, vessel identity, illegal activity, damage totals, or legal certainty. "
        "Use confidence-aware language such as 'candidate', 'signal', 'screening indicator', and 'requires corroboration'. "
        "If evidence is insufficient, say so plainly and recommend review of the source artifacts."
    )


def pro_brief_user_payload(
    *,
    profile: str,
    profile_label: str,
    tim_summary: Mapping[str, Any] | None,
    artifact_refs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    limitations: list[str],
) -> str:
    artifact_lines = "\n".join(
        f"- {artifact.get('artifact_id', 'artifact')}: kind={artifact.get('kind')}, profile={artifact.get('profile')}"
        for artifact in artifact_refs[:12]
    )
    job_lines = "\n".join(
        f"- {job.get('job_id', 'job')}: profile={job.get('profile')}, center=({job.get('center_lat')}, {job.get('center_lon')})"
        for job in jobs[:8]
    )
    tim_keys = ", ".join(sorted(tim_summary.keys())[:12]) if isinstance(tim_summary, Mapping) else "none"
    limitation_lines = "\n".join(f"- {item}" for item in limitations)
    return (
        f"Write a short {profile_label} brief for profile token {profile!r}.\n\n"
        f"TiM summary keys: {tim_keys}\n\n"
        f"Artifact refs:\n{artifact_lines or '- none'}\n\n"
        f"Jobs:\n{job_lines or '- no job metadata'}\n\n"
        f"Required limitations:\n{limitation_lines or '- none'}\n\n"
        "Return 2-4 concise paragraphs. Include a first paragraph that states the evidence level and the main signal. "
        "Include a final sentence naming at least one next review action. Avoid unsupported certainty."
    )
