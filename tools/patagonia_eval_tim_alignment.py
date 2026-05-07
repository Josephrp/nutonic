"""Heuristic TiM–caption alignment for Patagonia eval (orthogonal to SCL IoU).

Scores whether the model acknowledges TiM-shaped analytics and profile-specific themes.
Does not assert TiM is ground truth — only integration quality vs injected JSON.
"""

from __future__ import annotations

from typing import Any


def _lower(s: str) -> str:
    return (s or "").strip().lower()


def _mentions_tim_bridge(text: str) -> bool:
    t = _lower(text)
    markers = (
        "tim",
        "terra",
        "modality",
        "analytics json",
        "model-shaped",
        "model inferred",
        "model-inferred",
        "auxiliary",
        "tim_modality",
        "profile_analytics",
        "json block",
        "encoded in the json",
    )
    return any(m in t for m in markers)


def _risk_language(text: str) -> bool:
    t = _lower(text)
    return any(
        x in t
        for x in (
            "limitation",
            "limitations",
            "confidence",
            "uncertain",
            "cannot verify",
            "approximate",
            "corroborat",
            "not definitive",
            "optical",
            "pseudo-sar",
            "pseudo sar",
        )
    )


def _vessel_candidate_strength(profile_analytics: dict[str, Any]) -> float:
    vc = profile_analytics.get("vessel_candidates")
    if not isinstance(vc, list) or not vc:
        return 0.0
    best = 0.0
    for item in vc:
        if not isinstance(item, dict):
            continue
        sc = item.get("score")
        if isinstance(sc, (int, float)):
            best = max(best, float(sc))
    return float(best)


def _expected_theme_terms(profile_analytics: dict[str, Any]) -> list[str]:
    """Broad caption keywords suggested by profile_analytics shape."""
    themes: list[str] = []
    prof = str(profile_analytics.get("profile") or "").strip().lower()

    if profile_analytics.get("land_transition"):
        themes.extend(["transition", "change", "land cover", "landcover", "lulc", "vegetation", "land use"])
    if profile_analytics.get("water_change"):
        themes.extend(["water", "flood", "inundation", "wet"])
    if profile_analytics.get("burn_change"):
        themes.extend(["burn", "wildfire", "fire", "heat"])
    if profile_analytics.get("vessel_candidates") or prof == "oceanscout_ship_detection":
        themes.extend(["vessel", "ship", "maritime", "candidate", "detection", "ocean", "sea"])

    # brief_only still benefits from separating optical vs model path
    if prof == "brief_only" or not themes:
        themes.extend(["dominant", "summary", "imagery", "scene"])

    return list(dict.fromkeys(themes))


def _caption_hits_theme(text: str, terms: list[str]) -> bool:
    t = _lower(text)
    return any(term in t for term in terms)


def score_tim_alignment(
    caption: str,
    tim_compact: dict[str, Any] | None,
    *,
    analysis_profile: str,
) -> tuple[float | None, dict[str, Any]]:
    """
    Return alignment score in [0, 1] or None when no TiM payload should be scored.

    ``tim_compact`` matches ``compact_tim_for_production_prompt`` (modality outputs + profile_analytics).
    """
    if not tim_compact or not isinstance(tim_compact, dict):
        return None, {"reason": "no_tim_compact"}

    pa = tim_compact.get("profile_analytics")
    if not isinstance(pa, dict):
        pa = {}

    prof = str(pa.get("profile") or analysis_profile or "").strip().lower()
    diag: dict[str, Any] = {"profile_resolved": prof or analysis_profile}

    tmo = tim_compact.get("tim_modality_outputs")
    has_modalities = isinstance(tmo, dict) and len(tmo) > 0
    has_pa_body = any(
        k in pa
        for k in ("land_transition", "water_change", "burn_change", "vessel_candidates", "detection_score_summary")
    )

    if not has_modalities and not has_pa_body and prof == "brief_only":
        # TiM present but analytically empty — reward generic coherent analysis + optional TiM bridge.
        score = 0.55
        if _mentions_tim_bridge(caption):
            score += 0.25
        if _risk_language(caption):
            score += 0.15
        score = max(0.0, min(1.0, score))
        diag.update({"path": "brief_only_sparse", "mentions_tim_bridge": _mentions_tim_bridge(caption)})
        return round(score, 4), diag

    if not has_modalities and not has_pa_body:
        return None, {"reason": "tim_compact_empty_signals"}

    themes = _expected_theme_terms(pa)
    diag["theme_terms_sample"] = themes[:12]

    score = 0.35
    if _mentions_tim_bridge(caption):
        score += 0.28
    if _risk_language(caption):
        score += 0.12
    if _caption_hits_theme(caption, themes):
        score += 0.25

    # Marine: penalize confident "no ships" when TiM lists strong candidates (soft — heuristic only).
    if prof == "oceanscout_ship_detection" or pa.get("vessel_candidates"):
        strength = _vessel_candidate_strength(pa)
        diag["vessel_candidate_strength_max"] = round(strength, 4)
        cl = _lower(caption)
        denial = ("no ship" in cl or "no ships" in cl or "absence of vessels" in cl) and (
            "tim" not in cl and "candidate" not in cl and "model" not in cl
        )
        if strength >= 0.67 and denial:
            score -= 0.22

    score = max(0.0, min(1.0, score))
    diag["mentions_tim_bridge"] = _mentions_tim_bridge(caption)
    diag["hits_theme"] = _caption_hits_theme(caption, themes)
    return round(score, 4), diag
