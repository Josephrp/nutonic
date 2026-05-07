"""Multi-mode Patagonia eval scoring: lexical (legacy), SCL grounding IoU, structured checklist, composite."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from evaluate_vlm_patagonia import EvalTarget, _match_terms, _score_caption


@dataclass(frozen=True)
class ScoreWeights:
    lexical: float = 0.22
    grounding: float = 0.48
    structured: float = 0.30


@dataclass(frozen=True)
class GroundingPolicy:
    """
    Heuristics to reduce gaming of SCL-region IoU.

    - box_budget_max: max boxes before penalty
    - box_budget_penalty_per_extra: multiplicative penalty per extra box
    - oversize_penalty_strength: penalize predicted boxes that are much larger than the gold region
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
    "water": frozenset({"water", "ocean", "sea", "marine", "fjord", "lake", "lago", "inundation"}),
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
}


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


def parse_predicted_boxes(text: str) -> list[dict[str, Any]]:
    """Extract ``label`` + ``bbox`` [x1,y1,x2,y2] lists from model output (JSON fragments)."""
    out: list[dict[str, Any]] = []
    if not text.strip():
        return out

    # Objects like {"label":"water","bbox":[0,0,1,1]}
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

    # JSON arrays of objects
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

    # boxes key in nested JSON (single object)
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
    """
    Heuristic for Oceanscout-like outputs when we lack ship truth labels.

    - If no ship/vessel boxes: score 1.0 (abstention is plausible in most tiles)
    - If ship boxes exist: reward *small* boxes; penalize large area boxes and many boxes.
    """
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
            # Linear falloff between soft and hard
            per.append(float(1.0 - (a - box_soft_area) / max(1e-6, (box_hard_area - box_soft_area))))
    score = float(sum(per) / max(1, len(per)))
    # Mild penalty for spamming ship boxes
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
) -> tuple[float, dict[str, Any]]:
    """
    Mean best IoU per gold box (label must match canonical class); 1.0 if no gold boxes.

    Returns mean IoU in [0,1] and diagnostics.
    """
    if not gold_boxes:
        return 1.0, {"reason": "no_gold", "pred_boxes": []}

    preds_raw = parse_predicted_boxes(caption)
    preds = _all_pred_boxes(caption)
    pol = policy or GroundingPolicy()
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

    # Budget penalty: discourage emitting many boxes to maximize chance overlap.
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
        if label_mode == "any":
            for pt, _lab in preds:
                raw = iou_xyxy(gt, pt)
                if raw <= 0:
                    continue
                pred_area = _box_area(pt)
                # Penalize predicted boxes much larger than gold region fraction.
                # If gold_area is ~1.0 (open ocean), this factor is ~1 and does not penalize.
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
        else:
            for pt, plab in preds:
                if plab != canon_g:
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


def structured_task_score(caption: str, target: EvalTarget) -> tuple[float, dict[str, bool]]:
    """Light checklist aligned with production-analysis / TiM SFT style outputs."""
    t = caption.lower()
    wc = len([w for w in re.split(r"\s+", caption.strip()) if w])
    checks = {
        "non_empty": len(caption.strip()) > 0,
        "min_tokens": wc >= max(12, min(18, target.min_words // 2)),
        "structured_or_sections": bool(
            re.search(r"```(?:json|toml)|analytical|dominant|summary|land_cover|tim_modality", t)
        ),
        "risk_aware_language": any(
            x in t for x in ("limitation", "confidence", "optical", "uncertain", "cannot verify", "approximate")
        ),
    }
    score = sum(1 for v in checks.values() if v) / max(1, len(checks))
    return float(score), checks


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
) -> dict[str, Any]:
    """
    Compute lexical, grounding, structured, composite; guardrails from ``EvalTarget``.

    ``score_mode``: lexical | grounding | structured | composite | all
    ``pass_metric``: which scalar drives ``passed`` (default composite; falls back if unavailable).
    """
    w = weights or ScoreWeights()

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

    grounding_usable = bool(gold_boxes) and len(gold_boxes) > 0
    gr_score, gr_diag = grounding_score_vs_gold(
        caption,
        list(gold_boxes or []),
        label_mode=grounding_label_mode.strip().lower() or "canonical",
        policy=grounding_policy,
    )
    if not grounding_usable:
        gr_score = None  # type: ignore[assignment]

    st_score, st_checks = structured_task_score(caption, target)

    ship_score = None
    ship_diag: dict[str, Any] | None = None
    if _is_marine_target(target):
        ship_score, ship_diag = ship_plausibility_score(caption)

    forbidden_penalty = 0.25 * len(f_hits)
    claim_penalty = 0.08 * len(c_hits)
    guardrail = max(0.0, 1.0 - forbidden_penalty - claim_penalty)

    if grounding_usable and gr_score is not None:
        # For marine tiles, down-weight region-IoU gaming by gating grounding with ship plausibility.
        g_eff = float(gr_score)
        if ship_score is not None:
            g_eff *= float(ship_score)
        comp_raw = w.lexical * lex + w.grounding * g_eff + w.structured * st_score
    else:
        # Renormalize lexical + structured when grounding missing
        z = w.lexical + w.structured
        z = z if z > 1e-6 else 1.0
        comp_raw = (w.lexical / z) * lex + (w.structured / z) * st_score

    composite = max(0.0, min(1.0, comp_raw * guardrail))

    mode = score_mode.strip().lower()
    if mode == "lexical":
        primary = lex
    elif mode == "grounding":
        primary = float(gr_score) if gr_score is not None else 0.0
    elif mode == "structured":
        primary = st_score
    elif mode in ("composite", "all"):
        primary = composite
    else:
        primary = composite

    pm = pass_metric.strip().lower()
    if pm == "lexical":
        passed = lex >= threshold
    elif pm == "grounding":
        passed = (float(gr_score) if gr_score is not None else 0.0) >= threshold
    elif pm == "structured":
        passed = st_score >= threshold
    else:
        passed = composite >= threshold

    return {
        "score": round(primary, 4),
        "passed": passed,
        "score_mode": mode,
        "pass_metric": pm,
        "lexical": lex_out,
        "grounding": {
            "score": None if gr_score is None else round(float(gr_score), 4),
            "gold_available": grounding_usable,
            "diagnostics": gr_diag,
        },
        "ship_plausibility": {
            "score": None if ship_score is None else round(float(ship_score), 4),
            "diagnostics": ship_diag,
        },
        "structured": {"score": round(st_score, 4), "checks": st_checks},
        "composite": round(composite, 4),
        "guardrail_factor": round(guardrail, 4),
        "weights_applied": {"lexical": w.lexical, "grounding": w.grounding, "structured": w.structured},
    }
