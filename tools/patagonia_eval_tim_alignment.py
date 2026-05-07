"""Heuristic TiM–caption alignment for Patagonia eval (orthogonal to SCL IoU).

Scores whether the model acknowledges TiM-shaped analytics and profile-specific themes.
Does not assert TiM is ground truth — only integration quality vs injected JSON.
"""

from __future__ import annotations

import math
import re
from typing import Any


def _lower(s: str) -> str:
    return (s or "").strip().lower()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def _coords_drift_km(tim_compact: dict[str, Any], elat: float, elon: float) -> float | None:
    tmo = tim_compact.get("tim_modality_outputs")
    if not isinstance(tmo, dict):
        return None
    c = tmo.get("Coordinates")
    if not isinstance(c, dict):
        return None
    try:
        la = float(c["latitude"])  # type: ignore[arg-type]
        lo = float(c["longitude"])  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(la) and math.isfinite(lo)):
        return None
    return _haversine_km(la, lo, elat, elon)


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


def _numeric_or_quant_cue(text: str) -> bool:
    """Lightweight signal that the caption cites numbers / units (not only theme echo)."""
    t = text or ""
    if re.search(r"\b\d{1,3}(?:\.\d+)?\s*(?:%|km|ha|m2|m²|acres|deg|°c|celsius)\b", t, re.IGNORECASE):
        return True
    if re.search(r"\b(?:pct|percent|fraction|ratio)\b[^.]{0,40}\d", t, re.IGNORECASE):
        return True
    if re.search(r"\b(?:class|lulc|ndvi|scl)\b[^.]{0,24}\d", t, re.IGNORECASE):
        return True
    return False


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


def _profile_analytics_signal_strength(profile_analytics: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """How much non-trivial structure sits in ``profile_analytics`` (0..1)."""
    detail: dict[str, Any] = {}
    strength = 0.0
    lt = profile_analytics.get("land_transition")
    if isinstance(lt, dict):
        tm = lt.get("transition_matrix") or []
        top = lt.get("top_transitions") or []
        nz_tm = 0
        if isinstance(tm, list):
            for r in tm:
                if not isinstance(r, dict):
                    continue
                try:
                    c = int(r.get("count", 0))
                except (TypeError, ValueError):
                    c = 0
                if c > 0:
                    nz_tm += 1
        nz_top = 0
        if isinstance(top, list):
            for r in top:
                if not isinstance(r, dict):
                    continue
                try:
                    c = int(r.get("count", 0))
                except (TypeError, ValueError):
                    c = 0
                if c > 0 and str(r.get("from")) != str(r.get("to")):
                    nz_top += 1
        detail["land_transition_nonempty"] = nz_tm > 0 or nz_top > 0
        if nz_tm or nz_top:
            strength = max(strength, 0.72)

    wc = profile_analytics.get("water_change")
    if isinstance(wc, dict) and wc:
        strength = max(strength, 0.55)
        detail["water_change_present"] = True

    bc = profile_analytics.get("burn_change")
    if isinstance(bc, dict) and bc:
        strength = max(strength, 0.55)
        detail["burn_change_present"] = True

    vc = profile_analytics.get("vessel_candidates")
    if isinstance(vc, list) and len(vc) > 0:
        strength = max(strength, 0.65)
        detail["vessel_candidates_n"] = len(vc)

    dss = profile_analytics.get("detection_score_summary")
    if isinstance(dss, dict):
        try:
            sc = int(dss.get("sample_count") or 0)
        except (TypeError, ValueError):
            sc = 0
        if sc > 0:
            strength = max(strength, 0.35)
            detail["detection_samples"] = sc

    return float(min(1.0, strength)), detail


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
    expected_latitude: float | None = None,
    expected_longitude: float | None = None,
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

    drift_km: float | None = None
    if expected_latitude is not None and expected_longitude is not None:
        drift_km = _coords_drift_km(tim_compact, float(expected_latitude), float(expected_longitude))
        if drift_km is not None:
            diag["coordinates_drift_km_vs_target"] = round(drift_km, 2)

    pa_signal, pa_sig_detail = _profile_analytics_signal_strength(pa)
    diag["profile_analytics_signal"] = round(pa_signal, 4)
    diag.update({"profile_analytics_signal_detail": pa_sig_detail})

    if not has_modalities and not has_pa_body and prof == "brief_only":
        score = 0.48
        if _mentions_tim_bridge(caption):
            score += 0.22
        if _risk_language(caption):
            score += 0.12
        score = max(0.0, min(0.82, score))
        diag.update({"path": "brief_only_sparse", "mentions_tim_bridge": _mentions_tim_bridge(caption)})
        if drift_km is not None and drift_km > 300.0:
            score *= 0.55
            diag["coordinates_drift_penalty"] = True
        return round(max(0.0, min(1.0, score)), 4), diag

    if not has_modalities and not has_pa_body:
        return None, {"reason": "tim_compact_empty_signals"}

    themes = _expected_theme_terms(pa)
    diag["theme_terms_sample"] = themes[:12]

    degenerate_profile = has_pa_body and pa_signal < 0.08 and prof != "brief_only"
    diag["degenerate_profile_analytics"] = degenerate_profile

    score = 0.28
    if _mentions_tim_bridge(caption):
        score += 0.22
    if _risk_language(caption):
        score += 0.10
    if _caption_hits_theme(caption, themes):
        score += 0.18

    if pa_signal >= 0.35 and not _numeric_or_quant_cue(caption):
        score -= 0.12
        diag["numeric_cue_missing_penalty"] = True

    if degenerate_profile:
        score = min(score, 0.58)
        if not (_mentions_tim_bridge(caption) and _risk_language(caption)):
            score -= 0.08

    if prof == "oceanscout_ship_detection" or pa.get("vessel_candidates"):
        strength = _vessel_candidate_strength(pa)
        diag["vessel_candidate_strength_max"] = round(strength, 4)
        cl = _lower(caption)
        denial = ("no ship" in cl or "no ships" in cl or "absence of vessels" in cl) and (
            "tim" not in cl and "candidate" not in cl and "model" not in cl
        )
        if strength >= 0.67 and denial:
            score -= 0.22

    if drift_km is not None and drift_km > 300.0:
        score *= 0.52
        diag["coordinates_drift_penalty"] = True

    score = max(0.0, min(1.0, score))
    diag["mentions_tim_bridge"] = _mentions_tim_bridge(caption)
    diag["hits_theme"] = _caption_hits_theme(caption, themes)
    diag["numeric_or_quant_cue"] = _numeric_or_quant_cue(caption)
    return round(score, 4), diag
