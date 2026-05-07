"""Counterfactual probes that test the *VLM* (not the analytics provider).

Each probe perturbs *exactly one* input axis and re-runs the model. A faithful model
should:

- ``wrong_analytics``    — disagree with planted false analytics (caption should NOT
                           parrot the wrong fractions; faithfulness vs *true* analytics
                           should not collapse).
- ``half_redact``        — gracefully hedge when the JSON body is empty.
- ``image_swap``         — change its caption (an image-only-baseline failure if not).
- ``tim_payload_flip``   — legacy ``--contrastive-tim-flip`` semantics, kept for
                           backward compatibility under a clearer name.

The output of each probe is a small dict that the harness records alongside the
primary row. Aggregate metrics are computed from these per-probe dicts.
"""

from __future__ import annotations

import copy
import json
import math
import re
from difflib import SequenceMatcher
from typing import Any, Literal


CounterfactualKind = Literal[
    "wrong_analytics",
    "half_redact",
    "image_swap",
    "tim_payload_flip",
]
ALL_KINDS: tuple[CounterfactualKind, ...] = (
    "wrong_analytics",
    "half_redact",
    "image_swap",
    "tim_payload_flip",
)


def _canonical(obj: dict[str, Any] | None) -> str:
    return json.dumps(obj or {}, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Perturbations
# ---------------------------------------------------------------------------


def perturb_wrong_analytics(
    analytics: dict[str, Any] | None,
    *,
    profile: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Plant deliberately wrong but well-formed fractions / counts. Body shape preserved."""
    if not isinstance(analytics, dict):
        return None, {"reason": "no_analytics"}
    out = copy.deepcopy(analytics)
    diag: dict[str, Any] = {"profile": profile, "mode": "wrong_analytics"}

    tmo = out.get("tim_modality_outputs")
    if isinstance(tmo, dict):
        lulc = tmo.get("LULC")
        if isinstance(lulc, dict):
            cf = lulc.get("class_fractions")
            if isinstance(cf, dict) and cf:
                # Reverse class ordering by fraction → assigns "dominant" to actual minorities.
                items = sorted(cf.items(), key=lambda kv: float(kv[1] or 0.0))
                vals = [float(v or 0.0) for _, v in items]
                vals.reverse()
                cf2 = {k: vals[i] for i, (k, _) in enumerate(items)}
                lulc["class_fractions"] = cf2
                diag["lulc_reversed"] = True
        for name, block in tmo.items():
            if name == "Coordinates" or not isinstance(block, dict):
                continue
            samples = block.get("sample")
            if isinstance(samples, list):
                block["sample"] = [_negate_finite(x) for x in samples]

    pa = out.get("profile_analytics")
    if isinstance(pa, dict):
        pa["source_perturbed"] = "wrong_analytics"
        if profile == "land_use_change":
            lt = pa.get("land_transition")
            if isinstance(lt, dict):
                top = lt.get("top_transitions") or []
                # Swap from↔to for each transition (changes "what changed into what").
                lt["top_transitions"] = [
                    {**t, "from": t.get("to"), "to": t.get("from")} if isinstance(t, dict) else t for t in top
                ]
                diag["land_transition_swapped"] = True
        if profile == "oceanscout_ship_detection":
            vc = pa.get("vessel_candidates")
            if isinstance(vc, list) and vc:
                pa["vessel_candidates"] = []
                diag["vessel_candidates_cleared"] = True
            else:
                pa["vessel_candidates"] = [
                    {"candidate_id": "cf_planted_0", "score": 0.85, "centroid_xy": [0.5, 0.5]}
                ]
                diag["vessel_candidates_planted"] = 1

    diag["json_changed"] = _canonical(out) != _canonical(analytics)
    return out, diag


def perturb_half_redact(
    analytics: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Drop ``profile_analytics`` body content; keep only the profile id + an empty marker."""
    if not isinstance(analytics, dict):
        return None, {"reason": "no_analytics"}
    out = copy.deepcopy(analytics)
    pa = out.get("profile_analytics")
    if isinstance(pa, dict):
        keep_profile = pa.get("profile") or pa.get("source")
        out["profile_analytics"] = {
            "profile": keep_profile,
            "redacted": True,
            "source_perturbed": "half_redact",
        }
    diag = {"mode": "half_redact", "json_changed": _canonical(out) != _canonical(analytics)}
    return out, diag


def perturb_tim_payload_flip(
    analytics: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Backward-compatible numeric flip (with token jitter when payload is degenerate)."""
    if not isinstance(analytics, dict):
        return None, {"reason": "no_analytics"}
    out = copy.deepcopy(analytics)
    diag: dict[str, Any] = {"mode": "tim_payload_flip"}
    tmo = out.get("tim_modality_outputs")
    if isinstance(tmo, dict):
        for name, block in tmo.items():
            if name == "Coordinates" or not isinstance(block, dict):
                continue
            samples = block.get("sample")
            if isinstance(samples, list):
                block["sample"] = [_negate_finite(x) for x in samples]
            stats = block.get("statistics")
            if isinstance(stats, dict):
                for sk, sv in list(stats.items()):
                    if isinstance(sv, (int, float)) and math.isfinite(float(sv)):
                        stats[sk] = float(-float(sv))
    if _canonical(out) == _canonical(analytics):
        pa = out.setdefault("profile_analytics", {})
        if isinstance(pa, dict):
            pa["_eval_contrast_flip_token"] = float(pa.get("_eval_contrast_flip_token", 0.0) or 0.0) + 1e-6
            diag["mode"] = "profile_analytics_token_jitter"
    diag["json_changed"] = _canonical(out) != _canonical(analytics)
    return out, diag


def _negate_finite(x: Any) -> Any:
    if isinstance(x, (int, float)) and math.isfinite(float(x)):
        return float(-float(x))
    return x


# ---------------------------------------------------------------------------
# Probe metrics
# ---------------------------------------------------------------------------


def caption_responsiveness(caption_a: str, caption_b: str) -> tuple[float, dict[str, Any]]:
    """Cheap proxy: ``1 − SequenceMatcher.ratio`` (higher = more responsive to perturbation)."""
    a = (caption_a or "").strip().lower()
    b = (caption_b or "").strip().lower()
    if not a and not b:
        return 0.0, {"reason": "both_empty"}
    ratio = SequenceMatcher(None, a, b).ratio()
    return round(max(0.0, min(1.0, 1.0 - ratio)), 4), {"sequence_matcher_ratio": round(ratio, 4)}


_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|percent)", re.IGNORECASE)


def caption_disagreement(
    caption_under_wrong: str,
    *,
    true_class_pcts: dict[str, float],
    wrong_class_pcts: dict[str, float],
) -> tuple[float, dict[str, Any]]:
    """Score = fraction of % claims in the caption that are *closer* to true than wrong fractions.

    Higher = the model resists the planted analytics. Score is ``None``-equivalent (0.5)
    when no percent claims are present.
    """
    cap = caption_under_wrong or ""
    matches = _PCT_RE.findall(cap)
    if not matches:
        return 0.5, {"reason": "no_percent_claims_in_caption"}
    nearest_true: list[float] = []
    nearest_wrong: list[float] = []
    closer_to_true = 0
    total = 0
    for raw, _unit in matches:
        try:
            v = float(raw)
        except ValueError:
            continue
        total += 1
        nt = min((abs(v - p) for p in true_class_pcts.values()), default=999.0)
        nw = min((abs(v - p) for p in wrong_class_pcts.values()), default=999.0)
        nearest_true.append(nt)
        nearest_wrong.append(nw)
        if nt < nw:
            closer_to_true += 1
    if total == 0:
        return 0.5, {"reason": "no_parseable_percents"}
    score = round(closer_to_true / total, 4)
    return score, {
        "n_percent_claims": total,
        "closer_to_true": closer_to_true,
        "nearest_true_pp": nearest_true,
        "nearest_wrong_pp": nearest_wrong,
    }
