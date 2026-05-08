"""Route inference to stub, in-process Hugging Face (official LFM-VL weights), or OpenAI-compatible servers."""

from __future__ import annotations

import math
from typing import Any

from lfm_vl_hint_service.config import get_settings
from lfm_vl_hint_service.infer_openai import pro_brief_fuse_openai
from lfm_vl_hint_service.infer_transformers import pro_brief_fuse_transformers
from lfm_vl_hint_service.models import SuggestionsFromFramesRequest, SuggestionsFromFramesResponse
from lfm_vl_hint_service.prompts import PRO_BRIEF_PROMPT_VERSION

_PROFILES = {
    "wildfire",
    "oceanscout_ship_detection",
    "land_use_change",
    "flood_pulse",
    "brief_only",
}

_CLAIM_GUARD_REPLACEMENTS = {
    "illegal activity detected": "activity signal requiring review",
    "illegal vessel": "vessel candidate",
    "confirmed vessel": "vessel candidate",
    "confirmed fire": "wildfire-related signal",
    "confirmed flood": "flood-related signal",
    "proves": "suggests",
    "proof": "supporting signal",
    "certainly": "possibly",
}


def effective_lfm_backend() -> str:
    """
    Resolve ``LFM_VL_BACKEND=auto`` to ``transformers`` when ``torch`` + ``transformers`` are importable, else ``stub``.
    """
    raw = get_settings().backend
    if raw != "auto":
        return raw
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForImageTextToText  # noqa: F401

        return "transformers"
    except ImportError:
        return "stub"


def infer_suggestions(req: SuggestionsFromFramesRequest) -> SuggestionsFromFramesResponse:
    backend = effective_lfm_backend()
    if backend == "transformers":
        from lfm_vl_hint_service.infer_transformers import infer_from_frames_transformers

        return infer_from_frames_transformers(req)
    if backend in ("openai", "openai_compatible", "vllm", "sglang"):
        from lfm_vl_hint_service.infer_openai import infer_from_frames_openai

        return infer_from_frames_openai(req)
    from lfm_vl_hint_service.stub_infer import infer_from_frames_stub

    return infer_from_frames_stub(req)


def narrative_fuse_text(captions: list[tuple[str, str]]) -> str:
    backend = effective_lfm_backend()
    if backend == "transformers":
        from lfm_vl_hint_service.infer_transformers import narrative_fuse_transformers

        return narrative_fuse_transformers(captions)
    if backend in ("openai", "openai_compatible", "vllm", "sglang"):
        from lfm_vl_hint_service.infer_openai import narrative_fuse_openai

        return narrative_fuse_openai(captions)
    parts = [f"{vid}: {txt}" for vid, txt in captions]
    fused = " · ".join(parts)[:890]
    return fused


def pro_brief_fuse_text(
    *,
    profile: str,
    tim_summary: dict[str, Any] | None,
    artifact_refs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    force_compose: bool,
    max_compose_distance_km: float,
) -> dict[str, Any]:
    mismatch = _aoi_mismatch(jobs, max_compose_distance_km)
    if mismatch is not None and not force_compose:
        return {
            "error": "aoi_mismatch",
            "detail": mismatch,
            "job_ids": [str(j.get("job_id")) for j in jobs if j.get("job_id")],
        }
    profile_name = _normalize_profile(profile)
    warnings = [] if mismatch is None else ["AOI mismatch override was used; interpret cross-profile synthesis cautiously."]
    limitations = _profile_limitations(profile_name)
    generated_text, generation_warning = _generated_profile_brief(
        profile=profile_name,
        tim_summary=tim_summary,
        artifact_refs=artifact_refs,
        jobs=jobs,
        limitations=limitations,
    )
    if generation_warning:
        warnings.append(generation_warning)
    key_findings = _key_findings(profile_name, tim_summary, artifact_refs, jobs)
    evidence_sentence = _profile_evidence_sentence(profile_name, artifact_refs)
    summary = generated_text or (
        f"{_profile_label(profile_name)} brief assembled from {len(jobs) or 1} PRO signal source(s). "
        f"{evidence_sentence} "
        "Findings are confidence-aware indicators and require corroboration before operational claims."
    )
    sections = [
        {"title": "Executive Summary", "body": summary[:2000], "confidence": "limited"},
        {
            "title": "Profile Evidence",
            "body": _evidence_section(profile_name, tim_summary, artifact_refs, jobs)[:2000],
            "confidence": "limited",
        },
        {"title": "Evidence And Limitations", "body": "; ".join(limitations)[:2000], "confidence": "limited"},
    ]
    payload = {
        "executive_summary": summary[:1200],
        "key_findings": key_findings,
        "confidence": _confidence(profile_name, tim_summary, artifact_refs),
        "recommended_actions": _recommended_actions(profile_name),
        "sections": sections,
        "warnings": warnings,
        "limitations": limitations,
    }
    guarded, guard_warnings = _guard_brief_payload(payload, profile_name)
    guarded["warnings"].extend(guard_warnings)
    return guarded


def _normalize_profile(profile: str) -> str:
    raw = (profile or "").strip() or "brief_only"
    if raw == "vessel_monitoring":
        return "oceanscout_ship_detection"
    return raw if raw in _PROFILES else "brief_only"


def _generated_profile_brief(
    *,
    profile: str,
    tim_summary: dict[str, Any] | None,
    artifact_refs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    limitations: list[str],
) -> tuple[str | None, str | None]:
    backend = effective_lfm_backend()
    if backend == "stub":
        return None, None
    try:
        if backend == "transformers":
            text = pro_brief_fuse_transformers(
                profile=profile,
                profile_label=_profile_label(profile),
                tim_summary=tim_summary,
                artifact_refs=artifact_refs,
                jobs=jobs,
                limitations=limitations,
            )
        elif backend in ("openai", "openai_compatible", "vllm", "sglang"):
            text = pro_brief_fuse_openai(
                profile=profile,
                profile_label=_profile_label(profile),
                tim_summary=tim_summary,
                artifact_refs=artifact_refs,
                jobs=jobs,
                limitations=limitations,
            )
        else:
            return None, None
    except Exception as exc:  # noqa: BLE001
        return None, f"LFM brief generation fell back to deterministic synthesis: {str(exc)[:180]}"
    sanitized, _changed = _sanitize_claim_text(text)
    warning = "Certainty language was softened by the PRO brief guard." if _changed else None
    return sanitized[:2400] if sanitized else None, warning


def _profile_label(profile: str) -> str:
    labels = {
        "wildfire": "FireWatch",
        "oceanscout_ship_detection": "OceanScout",
        "land_use_change": "LandShift",
        "flood_pulse": "FloodPulse",
        "brief_only": "Brief Composer",
    }
    return labels.get(profile, profile)


def _profile_limitations(profile: str) -> list[str]:
    if profile == "oceanscout_ship_detection":
        return [
            "Optical and pseudo-SAR-like evidence cannot establish legal certainty.",
            "Cloud, sun glint, shoreline ambiguity, and observation cadence may hide vessels.",
        ]
    if profile in {"wildfire", "flood_pulse", "land_use_change"}:
        return [
            "Change metrics depend on comparable temporal scenes and cloud conditions.",
            "Thresholds should be calibrated before external reporting.",
        ]
    return ["Brief output is a synthesis aid, not a field-verified assessment."]


def _recommended_actions(profile: str) -> list[str]:
    actions = {
        "wildfire": [
            "Review temporal scene comparability, cloud masks, and hotspot overlays before escalation.",
            "Corroborate burn/change signals with incident, weather, or in-situ reports.",
        ],
        "oceanscout_ship_detection": [
            "Display observation coverage before vessel-candidate summaries.",
            "Corroborate candidates with AIS, SAR, patrol reports, or other independent maritime sources.",
        ],
        "land_use_change": [
            "Review before/after scene provenance and top transition classes.",
            "Corroborate large transitions with cadastral, field, or recent high-resolution imagery.",
        ],
        "flood_pulse": [
            "Review pre/post scene quality and water-mask confidence before impact estimates.",
            "Corroborate affected-area signals with hydrology, gauge, or emergency management data.",
        ],
    }
    return actions.get(
        profile,
        [
            "Review source artifacts and observation coverage before sharing.",
            "Corroborate high-impact findings with an independent data source.",
        ],
    )


def _confidence(profile: str, tim_summary: dict[str, Any] | None, artifact_refs: list[dict[str, Any]]) -> str:
    artifact_ids = {str(a.get("artifact_id") or "") for a in artifact_refs}
    if profile == "oceanscout_ship_detection" and "observation_coverage" not in artifact_ids:
        return "limited"
    if isinstance(tim_summary, dict) and tim_summary.get("has_npz") and artifact_refs:
        return "moderate"
    return "limited"


def _profile_evidence_sentence(profile: str, artifact_refs: list[dict[str, Any]]) -> str:
    artifact_ids = {str(a.get("artifact_id") or "") for a in artifact_refs}
    if profile == "oceanscout_ship_detection":
        if "observation_coverage" in artifact_ids:
            return "Observation coverage is available and must frame any candidate-vessel discussion."
        return "Observation coverage is not available, so maritime claims must remain especially limited."
    if profile in {"wildfire", "land_use_change", "flood_pulse"}:
        return "Temporal scene provenance and overlay artifacts should be reviewed together."
    return "Source artifacts should be reviewed before treating this as an assessment."


def _evidence_section(
    profile: str,
    tim_summary: dict[str, Any] | None,
    artifact_refs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> str:
    artifact_ids = [str(a.get("artifact_id") or a.get("kind") or "artifact") for a in artifact_refs[:10]]
    tim_keys = sorted(tim_summary.keys())[:10] if isinstance(tim_summary, dict) else []
    return (
        f"Profile: {_profile_label(profile)}. "
        f"Artifacts: {', '.join(artifact_ids) if artifact_ids else 'none provided'}. "
        f"TiM summary keys: {', '.join(tim_keys) if tim_keys else 'none provided'}. "
        f"Job count: {len(jobs) or 1}. "
        f"Prompt template: {PRO_BRIEF_PROMPT_VERSION}."
    )


def _key_findings(
    profile: str,
    tim_summary: dict[str, Any] | None,
    artifact_refs: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> list[str]:
    keys = sorted(tim_summary.keys()) if isinstance(tim_summary, dict) else []
    findings = [
        f"Profile: {_profile_label(profile)}.",
        f"Artifacts available: {len(artifact_refs)}.",
    ]
    if keys:
        findings.append("TiM summary keys present: " + ", ".join(keys[:8]) + ".")
    if jobs:
        findings.append(f"Composed from {len(jobs)} job(s).")
    if profile == "oceanscout_ship_detection":
        artifact_ids = {str(a.get("artifact_id") or "") for a in artifact_refs}
        if "observation_coverage" in artifact_ids:
            findings.append("Observation coverage artifact is available and should be shown before candidate claims.")
        else:
            findings.append("Observation coverage artifact is missing; maritime conclusions remain screening-only.")
    return findings


def _guard_brief_payload(payload: dict[str, Any], profile: str) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    out = dict(payload)
    for key in ("executive_summary",):
        text, changed = _sanitize_claim_text(str(out.get(key) or ""))
        out[key] = text
        if changed:
            warnings.append("Certainty language was softened by the PRO brief guard.")
    guarded_findings = []
    for finding in out.get("key_findings") or []:
        text, changed = _sanitize_claim_text(str(finding))
        guarded_findings.append(text)
        if changed:
            warnings.append("A key finding contained unsupported certainty language and was softened.")
    out["key_findings"] = guarded_findings[:8]
    guarded_sections = []
    for section in out.get("sections") or []:
        if not isinstance(section, dict):
            continue
        body, changed = _sanitize_claim_text(str(section.get("body") or ""))
        if changed:
            warnings.append(f"Section {section.get('title') or 'untitled'} was softened by the PRO brief guard.")
        guarded_sections.append(
            {
                "title": str(section.get("title") or "Section")[:128],
                "body": body[:2000],
                "confidence": _section_confidence(section.get("confidence")),
            }
        )
    out["sections"] = guarded_sections[:6]
    out["confidence"] = _section_confidence(out.get("confidence"))
    out["recommended_actions"] = [str(action)[:300] for action in (out.get("recommended_actions") or [])[:6]]
    out["limitations"] = _profile_limitations(profile)
    out["warnings"] = [str(warning)[:300] for warning in (out.get("warnings") or [])[:8]]
    return out, sorted(set(warnings))


def _sanitize_claim_text(text: str) -> tuple[str, bool]:
    out = text.strip()
    changed = False
    for bad, replacement in _CLAIM_GUARD_REPLACEMENTS.items():
        lower = out.lower()
        if bad not in lower:
            continue
        out = _replace_case_insensitive(out, bad, replacement)
        changed = True
    return out, changed


def _replace_case_insensitive(text: str, needle: str, replacement: str) -> str:
    lower = text.lower()
    start = lower.find(needle)
    while start >= 0:
        end = start + len(needle)
        text = text[:start] + replacement + text[end:]
        lower = text.lower()
        start = lower.find(needle)
    return text


def _section_confidence(raw: object) -> str:
    value = str(raw or "limited").strip().lower()
    return value if value in {"limited", "moderate", "high"} else "limited"


def _aoi_mismatch(jobs: list[dict[str, Any]], max_distance_km: float) -> str | None:
    points: list[tuple[str, float, float]] = []
    for job in jobs:
        lat = job.get("center_lat")
        lon = job.get("center_lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            points.append((str(job.get("job_id") or job.get("profile") or "job"), float(lat), float(lon)))
    for i, a in enumerate(points):
        for b in points[i + 1 :]:
            dist = _haversine_km(a[1], a[2], b[1], b[2])
            if dist > max_distance_km:
                return f"{a[0]} is {dist:,.0f} km from {b[0]}; max allowed is {max_distance_km:,.0f} km."
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))
