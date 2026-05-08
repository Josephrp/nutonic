"""Patagonia VLM eval scoring (model-centric).

Scoring axes (each in ``[0, 1]`` or ``None`` when undefined):

- ``lexical``         — legacy keyword-coverage / forbidden-term checks.
- ``grounding``       — IoU vs labelled visual gold (SCL-derived or per-AOI YAML).
- ``output_contract`` — *hard* SFT contract gate (preamble + fenced JSON + box schema +
                        no prompt-marker leaks). Replaces the lenient ``structured_task_score``.
- ``faithfulness``    — caption ↔ analytics agreement (source-agnostic). Replaces
                        ``tim_alignment``; works for ``procedural`` / ``synthetic_oracle`` /
                        ``tim_generated`` analytics.
- ``composite``       — weighted blend with guardrails.

Returned keys preserve the legacy aliases ``structured`` and ``tim_alignment`` for
backward compatibility with any external dashboards / report readers.
"""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass
from typing import Any

from evaluate_vlm_patagonia import EvalTarget, _score_caption
from patagonia_eval_faithfulness import faithfulness_score
from patagonia_eval_output_contract import output_contract_score


@dataclass(frozen=True)
class ScoreWeights:
    """Composite weights. ``structured`` and ``tim_alignment`` are legacy aliases."""

    lexical: float = 0.18
    grounding: float = 0.42
    contract: float = 0.22
    faithfulness: float = 0.18

    @property
    def structured(self) -> float:  # legacy alias
        return self.contract

    @property
    def tim_alignment(self) -> float:  # legacy alias
        return self.faithfulness


# Presets are keyed by analytics-source so the harness can pick automatically.
SCORE_WEIGHT_PRESETS: dict[str, ScoreWeights] = {
    "default": ScoreWeights(0.18, 0.42, 0.22, 0.18),
    "image_only": ScoreWeights(0.22, 0.50, 0.28, 0.0),
    "procedural_analytics": ScoreWeights(0.16, 0.40, 0.22, 0.22),
    "synthetic_oracle": ScoreWeights(0.14, 0.36, 0.22, 0.28),
    "tim_generated": ScoreWeights(0.16, 0.40, 0.22, 0.22),
    # Legacy preset names (aliases) for backward compatibility.
    "optical_focus": ScoreWeights(0.20, 0.50, 0.30, 0.0),
    "tim_integration": ScoreWeights(0.16, 0.40, 0.22, 0.22),
}


@dataclass(frozen=True)
class GroundingPolicy:
    """IoU-gaming guards.

    - ``box_budget_max``: max boxes before per-extra penalty.
    - ``box_budget_penalty_per_extra``: multiplicative penalty per extra box.
    - ``oversize_penalty_strength``: penalize predicted boxes much larger than the gold region.
    """

    box_budget_max: int = 3
    box_budget_penalty_per_extra: float = 0.08
    oversize_penalty_strength: float = 0.75


def iou_xyxy(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


_CANONICAL_ALIASES: dict[str, frozenset[str]] = {
    "water": frozenset({"water", "ocean", "sea", "marine", "fjord", "lake", "lago", "inundation", "channel"}),
    "vegetation": frozenset(
        {
            "vegetation",
            "veg",
            "forest",
            "trees",
            "woodland",
            "grass",
            "grassland",
            "crops",
            "crop",
            "cropland",
            "agriculture",
            "agricultural",
            "shrub",
            "shrubland",
            "scrub",
            "plant",
            "plants",
            "canopy",
        }
    ),
    "bare": frozenset({"bare", "soil", "bare_ground", "barren", "sand", "rock", "rocks", "scree"}),
    "snow_ice": frozenset({"snow", "ice", "glacier", "cryosphere", "snow_ice", "frozen"}),
    "built": frozenset({"built", "urban", "buildings", "infrastructure", "city", "town", "port", "harbor"}),
}


def normalize_pred_label(label: str) -> str | None:
    s = (label or "").strip().lower()
    if not s:
        return None
    if s in _CANONICAL_ALIASES:
        return s
    for canon, aliases in _CANONICAL_ALIASES.items():
        if s in aliases:
            return canon
        for a in aliases:
            if len(a) >= 3 and a in s:
                return canon
    return None


def _all_pred_boxes(caption: str) -> list[tuple[tuple[float, float, float, float], str | None]]:
    out: list[tuple[tuple[float, float, float, float], str | None]] = []
    for p in parse_predicted_boxes(caption):
        bb = p.get("bbox")
        if not isinstance(bb, list) or len(bb) != 4:
            continue
        try:
            box = tuple(float(x) for x in bb)
        except (TypeError, ValueError):
            continue
        lab = normalize_pred_label(str(p.get("label") or ""))
        out.append((box, lab))
    return out


def parse_predicted_boxes(text: str) -> list[dict[str, Any]]:
    """Extract ``label`` + ``bbox`` [x1,y1,x2,y2] lists from model output (JSON fragments)."""
    out: list[dict[str, Any]] = []
    if not text.strip():
        return out

    for m in re.finditer(r"\{[^{}]*\"label\"[^{}]*\"bbox\"[^{}]*\}", text, re.DOTALL):
        frag = m.group(0)
        try:
            obj = json.loads(frag)
        except json.JSONDecodeError:
            continue
        lab = obj.get("label")
        bb = obj.get("bbox")
        if isinstance(lab, str) and isinstance(bb, list) and len(bb) == 4:
            try:
                box = tuple(float(x) for x in bb)
            except (TypeError, ValueError):
                continue
            out.append({"label": lab, "bbox": list(box)})

    for m in re.finditer(r"\[[\s\S]{10,8000}?\]", text):
        block = m.group(0)
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        for obj in data:
            if not isinstance(obj, dict):
                continue
            lab = obj.get("label")
            bb = obj.get("bbox")
            if isinstance(lab, str) and isinstance(bb, list) and len(bb) == 4:
                try:
                    box = tuple(float(x) for x in bb)
                except (TypeError, ValueError):
                    continue
                out.append({"label": lab, "bbox": list(box)})

    if not out:
        for m in re.finditer(r'"boxes"\s*:\s*\[[\s\S]{0,8000}?\]', text):
            try:
                inner = "{" + m.group(0) + "}"
                obj = json.loads(inner)
                arr = obj.get("boxes")
                if isinstance(arr, list):
                    for item in arr:
                        if not isinstance(item, dict):
                            continue
                        lab = item.get("label")
                        bb = item.get("bbox")
                        if isinstance(lab, str) and isinstance(bb, list) and len(bb) == 4:
                            try:
                                box = tuple(float(x) for x in bb)
                            except (TypeError, ValueError):
                                continue
                            out.append({"label": lab, "bbox": list(box)})
            except json.JSONDecodeError:
                continue

    return out


def _box_area(bb: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = bb
    return max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1))


def _is_marine_target(target: EvalTarget) -> bool:
    c = (target.category or "").strip().lower()
    return "marine" in c or "oceanscout" in c or "chokepoint" in c


def _is_ship_label(label: str) -> bool:
    s = (label or "").strip().lower()
    return any(k in s for k in ("ship", "vessel", "boat", "trawler"))


def ship_plausibility_score(caption: str, *, box_soft_area: float = 0.02, box_hard_area: float = 0.08) -> tuple[float, dict[str, Any]]:
    """Heuristic for marine outputs without ship truth labels."""
    preds = parse_predicted_boxes(caption)
    ship_boxes: list[tuple[float, float, float, float]] = []
    for p in preds:
        lab = str(p.get("label") or "")
        if not _is_ship_label(lab):
            continue
        bb = p.get("bbox")
        if not isinstance(bb, list) or len(bb) != 4:
            continue
        try:
            ship_boxes.append(tuple(float(x) for x in bb))
        except (TypeError, ValueError):
            continue
    if not ship_boxes:
        return 1.0, {"ship_box_count": 0, "reason": "no_ship_boxes"}
    per: list[float] = []
    for bb in ship_boxes:
        a = _box_area(bb)
        if a <= box_soft_area:
            per.append(1.0)
        elif a >= box_hard_area:
            per.append(0.0)
        else:
            per.append(float(1.0 - (a - box_soft_area) / max(1e-6, (box_hard_area - box_soft_area))))
    score = float(sum(per) / max(1, len(per)))
    if len(ship_boxes) > 3:
        score *= max(0.0, 1.0 - 0.12 * float(len(ship_boxes) - 3))
    return max(0.0, min(1.0, score)), {
        "ship_box_count": len(ship_boxes),
        "ship_box_areas": [round(_box_area(bb), 5) for bb in ship_boxes[:10]],
        "score_raw_mean": round(float(sum(per) / max(1, len(per))), 4),
    }


def grounding_score_vs_gold(
    caption: str,
    gold_boxes: list[dict[str, Any]],
    *,
    label_mode: str = "canonical",
    policy: GroundingPolicy | None = None,
    no_local_features: bool = False,
) -> tuple[float, dict[str, Any]]:
    """Mean best IoU per gold box; ``no_local_features=True`` rewards proper abstention.

    When ``no_local_features=True``: empty predictions → 1.0, any prediction → 0.5
    (the model is hallucinating boxes for an open-water / featureless tile).
    """
    pol = policy or GroundingPolicy()
    preds_raw = parse_predicted_boxes(caption)
    preds = _all_pred_boxes(caption)

    if no_local_features:
        return (1.0 if not preds_raw else 0.5), {
            "reason": "no_local_features_abstention" if not preds_raw else "no_local_features_pred_present",
            "pred_box_count": len(preds_raw),
        }

    if not gold_boxes:
        return 1.0, {"reason": "no_gold", "pred_boxes": []}

    diag: dict[str, Any] = {
        "pred_boxes": preds_raw,
        "gold_count": len(gold_boxes),
        "label_mode": label_mode,
        "policy": {
            "box_budget_max": pol.box_budget_max,
            "box_budget_penalty_per_extra": pol.box_budget_penalty_per_extra,
            "oversize_penalty_strength": pol.oversize_penalty_strength,
        },
    }
    ious: list[float] = []
    n_boxes = len(preds_raw)
    extra = max(0, n_boxes - int(pol.box_budget_max))
    budget_factor = max(0.0, 1.0 - float(pol.box_budget_penalty_per_extra) * float(extra))
    diag["pred_box_count"] = n_boxes
    diag["box_budget_factor"] = round(budget_factor, 4)

    for g in gold_boxes:
        glabel = str(g.get("label") or "")
        canon_g = normalize_pred_label(glabel) or glabel
        gbb = g.get("bbox")
        if not isinstance(gbb, list) or len(gbb) != 4:
            continue
        try:
            gt = tuple(float(x) for x in gbb)
        except (TypeError, ValueError):
            continue
        gold_area = float(g.get("area_fraction") or g.get("area_fraction_total") or 0.0)
        best = 0.0
        best_diag: dict[str, Any] = {"best_pred_area": None, "best_iou_raw": 0.0, "oversize_factor": 1.0}
        for pt, plab in preds:
            if label_mode != "any" and plab != canon_g:
                continue
            raw = iou_xyxy(gt, pt)
            if raw <= 0:
                continue
            pred_area = _box_area(pt)
            oversize = 1.0
            if gold_area > 0 and pred_area > gold_area:
                ratio = gold_area / max(1e-6, pred_area)
                oversize = float(max(0.0, min(1.0, ratio ** float(pol.oversize_penalty_strength))))
            eff = raw * oversize
            if eff > best:
                best = eff
                best_diag = {
                    "best_pred_area": round(pred_area, 5),
                    "best_iou_raw": round(raw, 5),
                    "oversize_factor": round(float(oversize), 5),
                }
        ious.append(best * budget_factor)
        best_diag["best_iou_effective"] = round(best * budget_factor, 5)
        diag.setdefault("per_gold_best", []).append({**best_diag, "gold_label": canon_g, "gold_area": gold_area})

    mean_iou = float(sum(ious) / max(1, len(ious))) if ious else 0.0
    diag["per_gold_best_iou"] = ious
    diag["mean_iou"] = round(mean_iou, 4)
    return mean_iou, diag


# ---------------------------------------------------------------------------
# Legacy ``structured_task_score`` shim
# ---------------------------------------------------------------------------


def structured_task_score(caption: str, target: EvalTarget) -> tuple[float, dict[str, Any]]:
    """Deprecated: use :func:`patagonia_eval_output_contract.output_contract_score`."""
    warnings.warn(
        "structured_task_score is deprecated; use output_contract_score from patagonia_eval_output_contract.",
        DeprecationWarning,
        stacklevel=2,
    )
    score, br = output_contract_score(caption, min_caption_words=max(12, target.min_words // 4))
    return score, {"checks": {}, "caption_quality": br, "_via": "output_contract"}


# ---------------------------------------------------------------------------
# Top-level multimodal scorer
# ---------------------------------------------------------------------------


def score_patagonia_multimodal(
    caption: str,
    target: EvalTarget,
    *,
    threshold: float,
    gold_boxes: list[dict[str, Any]] | None,
    weights: ScoreWeights | None = None,
    score_mode: str = "composite",
    pass_metric: str = "composite",
    grounding_label_mode: str = "canonical",
    grounding_policy: GroundingPolicy | None = None,
    analytics_in_prompt: dict[str, Any] | None = None,
    analytics_source: str | None = None,
    analysis_profile: str = "",
    no_local_features: bool = False,
    tim_health: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Score a caption across all axes.

    ``analytics_in_prompt`` is the *exact* JSON the model received in its prompt
    (regardless of source). Faithfulness scoring uses this; if ``None``, the
    faithfulness axis is dropped from the composite (weight set to 0).
    """
    if kwargs.get("tim_compact") is not None and analytics_in_prompt is None:
        warnings.warn(
            "score_patagonia_multimodal(tim_compact=...) is deprecated; pass analytics_in_prompt=... instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        analytics_in_prompt = kwargs.get("tim_compact")

    w = weights or ScoreWeights()
    mode = score_mode.strip().lower()
    if mode == "structured":
        mode = "output_contract"
    pm = pass_metric.strip().lower()
    if pm == "structured":
        pm = "output_contract"
    if pm == "tim_alignment":
        pm = "faithfulness"

    lex, gh, gt, e_hits, f_hits, c_hits, q_flags, wc, lex_passed = _score_caption(caption, target, threshold)
    lex_out = {
        "score": round(lex, 4),
        "passed_lexical": lex_passed,
        "expected_groups_hit": gh,
        "expected_groups_total": gt,
        "expected_hits": e_hits,
        "forbidden_hits": f_hits,
        "claim_risk_hits": c_hits,
        "quality_flags": q_flags,
        "word_count": wc,
    }

    grounding_usable = no_local_features or (bool(gold_boxes) and len(gold_boxes) > 0)
    gr_score: float | None
    gr_score_v, gr_diag = grounding_score_vs_gold(
        caption,
        list(gold_boxes or []),
        label_mode=grounding_label_mode.strip().lower() or "canonical",
        policy=grounding_policy,
        no_local_features=no_local_features,
    )
    if not grounding_usable:
        gr_score = None
    else:
        gr_score = float(gr_score_v)

    contract_score, contract_diag = output_contract_score(
        caption, min_caption_words=max(12, target.min_words // 4)
    )

    faith_score: float | None
    faith_score_v, faith_diag = faithfulness_score(
        caption,
        analytics_in_prompt,
        profile=(analysis_profile or target.category or "").strip().lower() or "brief_only",
    )
    faith_score = None if faith_score_v is None else float(faith_score_v)
    faith_weight_eff = float(w.faithfulness) if faith_score is not None else 0.0

    ship_score = None
    ship_diag: dict[str, Any] | None = None
    if _is_marine_target(target):
        ship_score, ship_diag = ship_plausibility_score(caption)

    forbidden_penalty = 0.25 * len(f_hits)
    claim_penalty = 0.08 * len(c_hits)
    guardrail = max(0.0, 1.0 - forbidden_penalty - claim_penalty)

    if grounding_usable and gr_score is not None:
        g_eff = float(gr_score)
        if ship_score is not None:
            g_eff *= float(ship_score)
        sum_w = float(w.lexical + w.grounding + w.contract + faith_weight_eff)
        sum_w = sum_w if sum_w > 1e-9 else 1.0
        comp_raw = (
            float(w.lexical) * lex
            + float(w.grounding) * g_eff
            + float(w.contract) * contract_score
            + (faith_weight_eff * float(faith_score) if faith_score is not None else 0.0)
        ) / sum_w
    else:
        z = float(w.lexical + w.contract + faith_weight_eff)
        z = z if z > 1e-6 else 1.0
        comp_raw = (float(w.lexical) / z) * lex + (float(w.contract) / z) * contract_score
        if faith_score is not None:
            comp_raw += (faith_weight_eff / z) * float(faith_score)

    composite = max(0.0, min(1.0, comp_raw * guardrail))

    n_pred_boxes = len(_all_pred_boxes(caption))
    caption_quality: dict[str, Any] = {
        **dict(contract_diag),
        "pred_boxes_parsed": n_pred_boxes,
        "gold_boxes_available": grounding_usable and not no_local_features,
        "no_local_features": no_local_features,
        "tim_health": tim_health,
        "analytics_source": analytics_source,
        "analytics_in_prompt": analytics_in_prompt is not None,
    }

    if grounding_usable and not no_local_features and n_pred_boxes == 0:
        composite = min(composite, 0.42)
        caption_quality["composite_cap"] = "gold_no_pred_boxes"
    if not grounding_usable and _is_marine_target(target) and ship_score is not None:
        composite = float(composite) * float(ship_score)
        caption_quality["marine_no_gold_ship_gate"] = True
    if contract_diag.get("verdict") == "leak" or contract_diag.get("leaks"):
        composite = min(composite, 0.35)
        caption_quality["composite_cap"] = "contract_leak"
    composite = max(0.0, min(1.0, composite))

    if mode == "lexical":
        primary = lex
    elif mode == "grounding":
        primary = float(gr_score) if gr_score is not None else 0.0
    elif mode in ("output_contract", "structured"):
        primary = contract_score
    elif mode in ("faithfulness", "tim_alignment"):
        primary = float(faith_score) if faith_score is not None else 0.0
    elif mode in ("composite", "all"):
        primary = composite
    else:
        primary = composite

    if pm == "lexical":
        passed = lex >= threshold
    elif pm == "grounding":
        passed = (float(gr_score) if gr_score is not None else 0.0) >= threshold
    elif pm == "output_contract":
        passed = contract_score >= threshold
    elif pm == "faithfulness":
        passed = (float(faith_score) if faith_score is not None else 0.0) >= threshold
    else:
        passed = composite >= threshold

    contract_block = {"score": round(contract_score, 4), "diagnostics": contract_diag}
    faith_block = {
        "score": None if faith_score is None else round(float(faith_score), 4),
        "diagnostics": faith_diag,
        "weight_effective": round(faith_weight_eff, 4),
    }

    return {
        "score": round(primary, 4),
        "passed": passed,
        "score_mode": mode,
        "pass_metric": pm,
        "lexical": lex_out,
        "grounding": {
            "score": None if gr_score is None else round(float(gr_score), 4),
            "gold_available": grounding_usable and not no_local_features,
            "no_local_features": no_local_features,
            "diagnostics": gr_diag,
        },
        "ship_plausibility": {
            "score": None if ship_score is None else round(float(ship_score), 4),
            "diagnostics": ship_diag,
        },
        "output_contract": contract_block,
        "structured": contract_block,  # legacy alias
        "caption_quality": caption_quality,
        "faithfulness": faith_block,
        "tim_alignment": faith_block,  # legacy alias
        "composite": round(composite, 4),
        "guardrail_factor": round(guardrail, 4),
        "weights_applied": {
            "lexical": w.lexical,
            "grounding": w.grounding,
            "contract": w.contract,
            "faithfulness": faith_weight_eff,
            "structured": w.contract,  # legacy alias
            "tim_alignment": faith_weight_eff,  # legacy alias
        },
        "analytics_source": analytics_source,
        "tim_health": tim_health,
    }
