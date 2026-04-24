"""Route inference to stub, in-process Hugging Face (official LFM-VL weights), or OpenAI-compatible servers."""

from __future__ import annotations

import math
from typing import Any

from lfm_vl_hint_service.config import get_settings
from lfm_vl_hint_service.models import SuggestionsFromFramesRequest, SuggestionsFromFramesResponse


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
    profile_name = profile.strip() or "brief_only"
    warnings = [] if mismatch is None else ["AOI mismatch override was used; interpret cross-profile synthesis cautiously."]
    limitations = _profile_limitations(profile_name)
    key_findings = _key_findings(profile_name, tim_summary, artifact_refs, jobs)
    summary = (
        f"{_profile_label(profile_name)} brief assembled from {len(jobs) or 1} PRO signal source(s). "
        "Findings are confidence-aware indicators and require corroboration before operational claims."
    )
    return {
        "executive_summary": summary[:1200],
        "key_findings": key_findings,
        "confidence": "limited" if limitations else "moderate",
        "recommended_actions": [
            "Review source artifacts and observation coverage before sharing.",
            "Corroborate high-impact findings with an independent data source.",
        ],
        "sections": [
            {"title": "Executive Summary", "body": summary[:2000], "confidence": "limited"},
            {"title": "Evidence And Limitations", "body": "; ".join(limitations)[:2000], "confidence": "limited"},
        ],
        "warnings": warnings,
        "limitations": limitations,
    }


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
    return findings


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
