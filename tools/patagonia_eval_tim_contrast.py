"""Contrastive / perturbation helpers for TiM-conditioned Patagonia eval."""

from __future__ import annotations

import copy
import json
import math
import warnings
from difflib import SequenceMatcher
from typing import Any


def flip_tim_modality_numeric_samples(tim_compact: dict[str, Any]) -> dict[str, Any]:
    warnings.warn(
        "flip_tim_modality_numeric_samples is a low-level helper; prefer patagonia_eval_counterfactuals.perturb_tim_payload_flip.",
        DeprecationWarning,
        stacklevel=2,
    )
    """
    Deep-copy TiM compact JSON and negate finite numeric samples under ``tim_modality_outputs``.

    Intended as an A/B stress test: if captions barely change vs this perturbation, the model may be
    ignoring TiM-conditioned cues (or relying only on optics).
    """
    out = copy.deepcopy(tim_compact) if isinstance(tim_compact, dict) else {}
    tmo = out.get("tim_modality_outputs")
    if not isinstance(tmo, dict):
        return out
    for _mod_key, block in tmo.items():
        if not isinstance(block, dict):
            continue
        samples = block.get("sample")
        if isinstance(samples, list):
            block["sample"] = [_negate_finite(x) for x in samples]
        stats = block.get("statistics")
        if isinstance(stats, dict):
            for sk, sv in list(stats.items()):
                if isinstance(sv, (int, float)) and math.isfinite(float(sv)):
                    stats[sk] = float(-float(sv))
    return out


def _negate_finite(x: Any) -> Any:
    if isinstance(x, (int, float)) and math.isfinite(float(x)):
        return float(-float(x))
    return x


def _tim_compact_canonical_json(tim_compact: dict[str, Any]) -> str:
    return json.dumps(tim_compact, sort_keys=True, default=str)


def perturb_tim_compact_for_contrast(tim_compact: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Apply numeric flip; if the canonical JSON is unchanged (all-zero / empty modalities), jitter a
    benign eval-only token under ``profile_analytics`` so prompts differ and contrastive scoring is meaningful.
    """
    flipped = flip_tim_modality_numeric_samples(tim_compact)
    diag: dict[str, Any] = {"mode": "negate_modality_samples"}
    if _tim_compact_canonical_json(flipped) != _tim_compact_canonical_json(tim_compact):
        diag["json_changed"] = True
        return flipped, diag

    alt = copy.deepcopy(tim_compact) if isinstance(tim_compact, dict) else {}
    pa = alt.get("profile_analytics")
    if not isinstance(pa, dict):
        pa = {}
        alt["profile_analytics"] = pa
    prev = float(pa.get("_eval_contrast_flip_token", 0.0) or 0.0)
    pa["_eval_contrast_flip_token"] = prev + 1e-6
    diag["mode"] = "profile_analytics_token_jitter"
    diag["json_changed"] = _tim_compact_canonical_json(alt) != _tim_compact_canonical_json(tim_compact)
    return alt, diag


def contrast_caption_responsiveness(caption_a: str, caption_b: str) -> tuple[float, dict[str, Any]]:
    """Cheap proxy: 1 − normalized similarity (higher ⇒ captions diverged under perturbation)."""
    a = (caption_a or "").strip().lower()
    b = (caption_b or "").strip().lower()
    if not a and not b:
        return 0.0, {"reason": "both_empty"}
    ratio = SequenceMatcher(None, a, b).ratio()
    score = round(max(0.0, min(1.0, 1.0 - ratio)), 4)
    return score, {"sequence_matcher_ratio": round(ratio, 4)}
