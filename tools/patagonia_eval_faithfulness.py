"""Deterministic caption-vs-analytics faithfulness scorer (source-agnostic).

Replaces the keyword-bingo ``score_tim_alignment`` heuristic, which over-rewarded
empty TiM payloads (22/40 rows hit 1.0 in run ``20260507T194602Z`` despite empty
``land_transition`` bodies).

Inputs:
    caption                 — VLM output text.
    analytics_in_prompt     — the *same* compact JSON the model received in the prompt
                              (``tim_modality_outputs`` + ``profile_analytics``-shaped),
                              regardless of whether it came from TerraMind TiM, the SFT
                              procedural builder, or a synthetic oracle.
    analysis_profile        — production analysis profile (``brief_only``, ``land_use_change``,
                              ``wildfire``, ``flood_pulse``, ``oceanscout_ship_detection``).

Output: ``(score in [0, 1] | None, breakdown_diag)`` where ``None`` means the analytics
JSON was completely missing (so faithfulness is undefined for the row).

Key invariants:
- Hedge propriety is contextual: required when analytics body is empty / sparse;
  neutral otherwise.
- Numeric / class claims must be supported by the JSON; fabricated claims are penalized.
- Anti-narration caps the score at 0.4 when the caption echoes prompt scaffolding.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


# Synonyms → Dynamic World canonical class names (matches ``DYNAMIC_WORLD_CLASSES`` from
# ``data/scripts/lfm_vl_sft_dataset/instances.py`` so faithfulness aligns with the
# procedural analytics builder used for SFT data).
_CLASS_SYNONYMS: dict[str, tuple[str, ...]] = {
    "water": ("water", "lake", "river", "ocean", "sea", "marine", "fjord", "lago", "open water", "channel"),
    "trees": ("trees", "forest", "woodland", "canopy"),
    "grass": ("grass", "grassland", "pasture", "meadow"),
    "flooded_vegetation": ("flooded vegetation", "wetland", "marsh", "inundated vegetation"),
    "crops": ("crop", "crops", "cropland", "farm", "farmland", "agriculture", "agricultural"),
    "shrub_and_scrub": ("shrub", "scrub", "shrubland", "shrub-and-scrub"),
    "built": ("built", "urban", "buildings", "infrastructure", "city", "town", "port", "harbor", "road", "roads"),
    "bare_ground": ("bare", "barren", "rock", "rocks", "scree", "sand", "soil", "bare ground"),
    "snow_and_ice": ("snow", "ice", "glacier", "cryosphere", "frozen", "snow-covered"),
}

_HEDGE_TERMS: tuple[str, ...] = (
    "limitation",
    "limitations",
    "confidence",
    "uncertain",
    "cannot verify",
    "not definitive",
    "approximate",
    "optical-only",
    "optical only",
    "pseudo-sar",
    "pseudo sar",
    "corroborat",
)

_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("captions_marker", re.compile(r"\[captions?\s*:", re.IGNORECASE)),
    ("boxes_marker", re.compile(r"\[boxes\]", re.IGNORECASE)),
    ("xy_eq_zero", re.compile(r"\bx1\s*=\s*0\.0", re.IGNORECASE)),
    ("tim_label_echo", re.compile(r"tim[-\s]style\s+analytics\s+json\s*:?", re.IGNORECASE)),
)

_NUMERIC_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|km2|km²|km|ha|m2|m²|°c|deg)",
    re.IGNORECASE,
)
_NUMERIC_TOLERANCE_PP = 15.0  # percentage-point tolerance against analytics fractions


def _lower(text: str) -> str:
    return (text or "").strip().lower()


def _hedge_present(caption: str) -> bool:
    t = _lower(caption)
    return any(term in t for term in _HEDGE_TERMS)


def _anti_narration_hits(caption: str) -> list[str]:
    return [name for name, pat in _LEAK_PATTERNS if pat.search(caption or "")]


def _class_claims(caption: str) -> Counter[str]:
    """Canonical Dynamic World class names mentioned in caption (count of distinct synonym hits)."""
    t = _lower(caption)
    out: Counter[str] = Counter()
    for canon, synonyms in _CLASS_SYNONYMS.items():
        for syn in synonyms:
            if syn in t:
                out[canon] += 1
                break
    return out


def _percent_claims(caption: str) -> list[dict[str, Any]]:
    """Numeric claims with units; we focus on percent claims for class-fraction matching."""
    out: list[dict[str, Any]] = []
    for m in _NUMERIC_RE.finditer(caption or ""):
        unit = m.group("unit").lower()
        try:
            value = float(m.group("value"))
        except ValueError:
            continue
        out.append({"value": value, "unit": unit, "raw": m.group(0)})
    return out


def _supported_classes(analytics: dict[str, Any]) -> tuple[Counter[str], dict[str, float]]:
    """Return (claim-count Counter, class→fraction map) for any class evidence in the JSON."""
    pct_by_class: dict[str, float] = {}
    counts: Counter[str] = Counter()

    tmo = analytics.get("tim_modality_outputs")
    pa = analytics.get("profile_analytics")

    if isinstance(tmo, dict):
        lulc = tmo.get("LULC")
        if isinstance(lulc, dict):
            cf = lulc.get("class_fractions")
            if isinstance(cf, dict):
                for name, frac in cf.items():
                    if isinstance(frac, (int, float)) and frac > 0:
                        pct_by_class[str(name)] = float(frac) * 100.0

    if isinstance(pa, dict):
        for key in ("land_transition", "summary", "burn_change", "water_change"):
            block = pa.get(key)
            if isinstance(block, dict):
                cd = block.get("class_distribution") or block.get("dominant_tim_classes") or block.get("dominant_sentinel_classes")
                if isinstance(cd, list):
                    for row in cd:
                        if not isinstance(row, dict):
                            continue
                        lab = row.get("label")
                        frac = row.get("fraction")
                        if isinstance(lab, str) and isinstance(frac, (int, float)) and frac > 0:
                            pct_by_class.setdefault(lab, float(frac) * 100.0)
        vc = pa.get("vessel_candidates")
        if isinstance(vc, list) and vc:
            counts["vessel_candidate"] = len(vc)

    for name in pct_by_class:
        counts[name] += 1
    return counts, pct_by_class


def _profile_body_signal(analytics: dict[str, Any], profile: str) -> tuple[bool, dict[str, Any]]:
    """Return ``(rich, detail)``: whether ``profile_analytics`` carries non-trivial body content for ``profile``."""
    pa = analytics.get("profile_analytics") if isinstance(analytics, dict) else None
    if not isinstance(pa, dict):
        return False, {"reason": "no_profile_analytics"}

    if profile == "land_use_change":
        lt = pa.get("land_transition")
        if isinstance(lt, dict):
            top = lt.get("top_transitions") or []
            nz_top = sum(
                1
                for r in top
                if isinstance(r, dict)
                and isinstance(r.get("count"), (int, float))
                and float(r["count"]) > 0
                and str(r.get("from")) != str(r.get("to"))
            )
            cd = lt.get("class_distribution") or []
            return bool(nz_top or len(cd) >= 2), {"nz_top_transitions": nz_top, "class_distribution_n": len(cd)}
    if profile == "wildfire":
        bc = pa.get("burn_change")
        if isinstance(bc, dict):
            sc = bc.get("sample_count") or 0
            hot = bc.get("hotspot_count") or 0
            return bool(sc and (hot or bc.get("changed_area_pct"))), {"sample_count": sc, "hotspot_count": hot}
    if profile == "flood_pulse":
        wc = pa.get("water_change")
        if isinstance(wc, dict):
            sc = wc.get("sample_count") or 0
            poly = wc.get("inundation_polygon_count") or 0
            return bool(sc and (poly or wc.get("expanded_area_pct"))), {
                "sample_count": sc,
                "inundation_polygon_count": poly,
            }
    if profile == "oceanscout_ship_detection":
        vc = pa.get("vessel_candidates") or []
        dss = pa.get("detection_score_summary") or {}
        sc = dss.get("sample_count") if isinstance(dss, dict) else 0
        return bool(vc) or bool(isinstance(sc, (int, float)) and sc > 0), {
            "vessel_candidates_n": len(vc) if isinstance(vc, list) else 0,
            "detection_sample_count": sc,
        }
    if profile == "brief_only":
        summ = pa.get("summary")
        if isinstance(summ, dict):
            return bool(summ.get("dominant_tim_classes") or summ.get("largest_deltas")), {
                "summary_keys": sorted(summ.keys()),
            }
    return False, {"reason": "unknown_profile_or_empty"}


def faithfulness_score(
    caption: str,
    analytics_in_prompt: dict[str, Any] | None,
    *,
    profile: str,
) -> tuple[float | None, dict[str, Any]]:
    """Return ``(score, diag)``; ``score`` is ``None`` when no analytics JSON is available."""
    if not isinstance(analytics_in_prompt, dict) or not analytics_in_prompt:
        return None, {"reason": "no_analytics_in_prompt"}

    diag: dict[str, Any] = {
        "profile": profile,
        "anti_narration_hits": _anti_narration_hits(caption),
        "hedge_present": _hedge_present(caption),
    }

    rich, body_detail = _profile_body_signal(analytics_in_prompt, profile)
    diag["body_rich"] = rich
    diag["body_detail"] = body_detail

    supported_class_counts, pct_by_class = _supported_classes(analytics_in_prompt)
    diag["analytics_class_pcts"] = {k: round(v, 2) for k, v in pct_by_class.items()}

    caption_classes = _class_claims(caption)
    diag["caption_class_claims"] = dict(caption_classes)

    if not caption.strip():
        return 0.0, {**diag, "verdict": "empty_caption"}

    score = 0.5  # neutral baseline; adjusted up/down by evidence

    if rich:
        # Reward supported class claims (more for ≥2 distinct classes).
        supported = [c for c in caption_classes if c in pct_by_class]
        if len(supported) >= 2:
            score += 0.28
            diag["supported_class_claims"] = supported
        elif supported:
            score += 0.18
            diag["supported_class_claims"] = supported
        else:
            score -= 0.15
            diag.setdefault("penalties", []).append("no_supported_class_claim_when_body_rich")
        # Penalize fabricated dominant claims (caption asserts a class with ≥0 mention but it's not in
        # the analytics class map at all).
        fabricated = [c for c in caption_classes if c not in pct_by_class and c != "vessel_candidate"]
        if fabricated:
            score -= 0.20 * min(2, len(fabricated)) / 2.0
            diag["fabricated_class_claims"] = fabricated
    else:
        # Body sparse / empty: hedging is required.
        if _hedge_present(caption):
            score += 0.15
            diag.setdefault("bonuses", []).append("hedge_when_body_sparse")
        else:
            score -= 0.30
            diag.setdefault("penalties", []).append("no_hedge_when_body_sparse")

    # Numeric-cue check (only when analytics actually carries class fractions).
    pct_claims = _percent_claims(caption)
    diag["numeric_pct_claims"] = pct_claims[:8]
    if pct_by_class and pct_claims:
        # For each percent claim in the caption, check if any analytics class matches within tolerance.
        wide_misses = 0
        for claim in pct_claims:
            if claim["unit"] not in ("%", "percent"):
                continue
            v = float(claim["value"])
            nearest = min((abs(v - pct) for pct in pct_by_class.values()), default=None)
            if nearest is not None and nearest > _NUMERIC_TOLERANCE_PP:
                wide_misses += 1
        if wide_misses:
            score -= min(0.20, 0.10 * wide_misses)
            diag["numeric_wide_misses"] = wide_misses

    # Profile-specific propriety: e.g., oceanscout caption asserting "no ships" while vessel_candidates non-empty.
    pa = analytics_in_prompt.get("profile_analytics") or {}
    if profile == "oceanscout_ship_detection":
        vc = pa.get("vessel_candidates") if isinstance(pa, dict) else None
        cap_l = _lower(caption)
        if isinstance(vc, list) and len(vc) > 0:
            if ("no ship" in cap_l or "no vessels" in cap_l or "no maritime" in cap_l) and (
                "tim" not in cap_l and "model" not in cap_l and "candidate" not in cap_l
            ):
                score -= 0.20
                diag.setdefault("penalties", []).append("denies_vessel_candidates_present")

    leaks = diag["anti_narration_hits"]
    if leaks:
        score = min(score, 0.40)
        diag.setdefault("caps", []).append("anti_narration_cap_0.40")

    score = max(0.0, min(1.0, score))
    diag["score"] = round(score, 4)
    return round(score, 4), diag
