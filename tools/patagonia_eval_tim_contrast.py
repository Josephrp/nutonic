"""Contrastive / perturbation helpers for TiM-conditioned Patagonia eval."""

from __future__ import annotations

import copy
import math
from difflib import SequenceMatcher
from typing import Any


def flip_tim_modality_numeric_samples(tim_compact: dict[str, Any]) -> dict[str, Any]:
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


def contrast_caption_responsiveness(caption_a: str, caption_b: str) -> tuple[float, dict[str, Any]]:
    """Cheap proxy: 1 − normalized similarity (higher ⇒ captions diverged under perturbation)."""
    a = (caption_a or "").strip().lower()
    b = (caption_b or "").strip().lower()
    if not a and not b:
        return 0.0, {"reason": "both_empty"}
    ratio = SequenceMatcher(None, a, b).ratio()
    score = round(max(0.0, min(1.0, 1.0 - ratio)), 4)
    return score, {"sequence_matcher_ratio": round(ratio, 4)}
