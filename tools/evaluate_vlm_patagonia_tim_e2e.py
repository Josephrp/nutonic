#!/usr/bin/env python3
"""
Standalone Patagonia evaluation with local TerraMind TiM artifacts.

Outputs a publishable run directory containing:
- fetched reference stills (STAC Sentinel-2 by default, or Mapbox via ``--still-source mapbox``)
- local TiM export JSONL generated on-device via torch/TerraTorch
- per-target prompt records with the TiM JSON injected in the user turn (SFT **production_analysis** layout + system message; see ``patagonia_eval_sft_prompts``)
- **local** TerraMind TiM via ``nutonic_terramind_tim_local.run.run_tim_batch_export`` (in-process PyTorch;
  Sentinel-2 STAC inputs; no remote TiM API). Device defaults to **auto** (CUDA → MPS → CPU).
- **local** Transformers VLMs (default: **NuTonic/lspace** vs **LiquidAI/LFM2.5-VL-450M**; override with
  ``--local-vlm-model`` or env ``NUTONIC_PATAGONIA_EVAL_*_MODEL_ID``)
- optional HTTP ``/v1/infer`` (no TiM in request) if you pass ``--endpoint`` or set
  ``NUTONIC_PATAGONIA_EVAL_ENABLE_HTTP=1`` to use URL env resolution
- aggregate JSON + Markdown summary
- **Multi-mode scoring** (``--score-mode``): **lexical** checks, **grounding** vs Sentinel-2 SCL
  reference boxes (COG-aligned still refresh), **output_contract** (hard JSON/box schema gate),
  **faithfulness** (caption ↔ injected analytics, source-agnostic), and **composite** (default).
- **Analytics sources** (``--analytics-source``): inject deterministic **procedural** analytics
  (SFT-aligned), **dynamic_world** / **procedural_or_dw** (EE label-chip fractions when
  ``--fetch-dynamic-world`` fills ``gold/*.json``), **synthetic_oracle** YAML, **tim_generated**
  (local TiM), **procedural_or_tim** (prefer healthy TiM else procedural), or **none** (image-only prompt).
- **Gold modes**: ``--gold-mode state`` (single-date SCL components, default) or ``delta`` (bi-temporal SCL XOR
  change regions when STAC yields two sufficiently separated acquisitions; falls back to state on failure).
- **Contrastive / counterfactual probes** (optional): ``--contrastive-tim-flip`` (legacy alias) or
  ``--counterfactuals`` for additional passes (wrong analytics, redacted analytics, image swap).

The local TiM path reuses `inference/terramind_tim_local` directly; no TiM
remote service is required. Use ``--skip-local-vlm`` for HTTP-only evals on deployed Spaces.

After success, ``NUTONIC_PATAGONIA_EVAL_HF_DATASET`` or ``--hf-dataset-repo`` uploads the run
(including ``models/finetune`` and ``models/base``) and ``by_model/...`` on the Hub.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import gc
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install httpx first: pip install httpx") from exc

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
TIM_SRC = REPO_ROOT / "inference" / "terramind_tim_local" / "src"
if str(TIM_SRC) not in sys.path:
    sys.path.insert(0, str(TIM_SRC))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from nutonic_terramind_tim_local.tim_defaults import DEFAULT_TIM_MODEL_ID  # noqa: E402

from evaluate_vlm_patagonia import (  # noqa: E402
    EvalTarget,
    _check_endpoint_health,
    _infer_caption,
    _sha256_bytes,
    _sanitize_filename,
    default_patagonia_targets,
    patagonia_comparison_hf_model_ids,
    resolve_local_vlm_comparison_runs,
    resolve_patagonia_eval_endpoints,
    write_patagonia_eval_still,
    write_patagonia_per_model_artifacts,
)
from patagonia_eval_scoring import SCORE_WEIGHT_PRESETS, ScoreWeights, score_patagonia_multimodal  # noqa: E402
from patagonia_eval_tim_contrast import contrast_caption_responsiveness  # noqa: E402
from patagonia_eval_analytics_sources import load_synthetic_oracle, select_analytics, trim_for_prompt  # noqa: E402
from patagonia_eval_counterfactuals import (  # noqa: E402
    ALL_KINDS,
    caption_disagreement,
    perturb_half_redact,
    perturb_tim_payload_flip,
    perturb_wrong_analytics,
)
from patagonia_eval_provider_health import aggregate as aggregate_tim_health, assess_tim_row  # noqa: E402
from patagonia_eval_visual_gold import gold_meta_for_target, has_no_local_features, load_visual_gold  # noqa: E402
from patagonia_eval_sft_prompts import (  # noqa: E402
    PRODUCTION_ANALYSIS_SYSTEM,
    build_production_no_tim_user_prompt,
    build_production_tim_user_prompt,
    compact_tim_for_production_prompt,
)

try:
    from upload_patagonia_eval_to_hf import upload_patagonia_eval_bundle
except ImportError:
    upload_patagonia_eval_bundle = None  # type: ignore[misc,assignment]


DEFAULT_OUT_DIR = REPO_ROOT / "data" / "downloads" / "evals" / "patagonia_tim_e2e"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if os.environ.get("NUTONIC_NO_DOTENV") == "1":
        return
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()


def _json_dumps(obj: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dumps(obj, pretty=True) + "\n", encoding="utf-8")


def _score_weight_presets_for_meta() -> dict[str, dict[str, float]]:
    return {
        name: {
            "lexical": float(w.lexical),
            "grounding": float(w.grounding),
            "contract": float(w.contract),
            "faithfulness": float(w.faithfulness),
            "structured": float(w.structured),
            "tim_alignment": float(w.tim_alignment),
        }
        for name, w in SCORE_WEIGHT_PRESETS.items()
    }


def _judge_pack_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": r.get("target_id"),
        "model_name": r.get("model_name"),
        "tim_injected": r.get("tim_injected"),
        "analysis_profile": r.get("analysis_profile"),
        "composite_weight_preset_resolved": r.get("composite_weight_preset_resolved"),
        "tim_compact": r.get("tim_compact"),
        "caption": r.get("caption"),
        "contrastive_pair_group": r.get("contrastive_pair_group"),
        "contrastive_arm": r.get("contrastive_arm"),
        "contrastive_responsiveness_vs_flip": r.get("contrastive_responsiveness_vs_flip"),
        "contrastive_error": r.get("contrastive_error"),
        "scores": {
            "primary": r.get("score"),
            "lexical": r.get("lexical_score"),
            "grounding": r.get("grounding_score"),
            "output_contract": r.get("structured_score"),
            "structured": r.get("structured_score"),
            "faithfulness": r.get("tim_alignment_score"),
            "tim_alignment": r.get("tim_alignment_score"),
            "composite": r.get("composite_score"),
            "ship_plausibility": r.get("ship_plausibility_score"),
        },
        "error": r.get("error"),
    }


def _append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(_json_dumps(obj) + "\n")


def _resolve_tim_device(flag: str) -> str:
    """
    Map ``auto`` (default) to an available accelerator for local in-process TiM; otherwise pass through
    a valid ``torch.device`` string (``cuda``, ``cpu``, ``cuda:0``, ``mps``, …).
    """
    v = (flag or "").strip().lower()
    if v in ("", "auto"):
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            mps = getattr(getattr(torch, "backends", None), "mps", None)
            if mps is not None and mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"
    return flag.strip()


def _resolve_pass_metric(score_mode: str, pass_metric_cli: str) -> str:
    pm = (pass_metric_cli or "auto").strip().lower()
    if pm not in ("", "auto"):
        return pm
    sm = score_mode.strip().lower()
    return {
        "lexical": "lexical",
        "grounding": "grounding",
        "structured": "output_contract",
        "output_contract": "output_contract",
        "tim_alignment": "faithfulness",
        "faithfulness": "faithfulness",
    }.get(sm, "composite")


def _needs_stac_gold_refresh(args: argparse.Namespace) -> bool:
    if getattr(args, "no_stac_gold", False):
        return False
    if args.still_source != "stac":
        return False
    sm = args.score_mode.strip().lower()
    if sm == "structured":
        sm = "output_contract"
    if sm == "tim_alignment":
        sm = "faithfulness"
    need_scores = sm in ("grounding", "composite", "all", "faithfulness", "output_contract")
    src = (getattr(args, "analytics_source", "") or "").strip().lower()
    need_dw_path = bool(getattr(args, "fetch_dynamic_world", False)) or src in ("dynamic_world", "procedural_or_dw")
    return need_scores or need_dw_path


def _gold_contract_tags(args: argparse.Namespace) -> list[str]:
    if getattr(args, "no_stac_gold", False) or args.still_source != "stac":
        return []
    if not _needs_stac_gold_refresh(args):
        return []
    gm = (getattr(args, "gold_mode", "state") or "state").strip().lower()
    if gm == "delta":
        return ["sentinel2_scl_bitemporal_delta", "sentinel2_late_rgb_chip"]
    return ["sentinel2_scl_connected_components_chip"]


def _composite_preset_label(
    args: argparse.Namespace,
    *,
    tim_injected: bool,
    resolved_analytics_source: str | None = None,
) -> str:
    w_cli = getattr(args, "score_weight", None)
    if isinstance(w_cli, (list, tuple)) and len(w_cli) == 3:
        return "explicit_cli"
    pr = (getattr(args, "composite_weight_preset", None) or "auto").strip().lower()
    if pr != "auto":
        return pr if pr in SCORE_WEIGHT_PRESETS else "default"
    src = (resolved_analytics_source or getattr(args, "analytics_source", "procedural_or_tim") or "").strip().lower()
    if not tim_injected or src == "none":
        return "image_only"
    if src == "synthetic_oracle":
        return "synthetic_oracle"
    if src.startswith("tim_generated"):
        return "tim_generated"
    return "procedural_analytics"


def _build_score_weights(
    args: argparse.Namespace,
    *,
    tim_injected: bool,
    resolved_analytics_source: str | None = None,
) -> ScoreWeights:
    """Resolve composite weights; explicit ``--score-weight`` fixes lexical/grounding/contract (faithfulness forced 0)."""
    import warnings

    w_cli = getattr(args, "score_weight", None)
    preset_arg = (getattr(args, "composite_weight_preset", None) or "auto").strip().lower()

    if isinstance(w_cli, (list, tuple)) and len(w_cli) == 3:
        warnings.warn(
            "--score-weight LEX GRD STR is deprecated; use --composite-weight-preset or the new 4-axis presets.",
            DeprecationWarning,
            stacklevel=2,
        )
        return ScoreWeights(lexical=float(w_cli[0]), grounding=float(w_cli[1]), contract=float(w_cli[2]), faithfulness=0.0)

    preset_name = preset_arg
    if preset_name == "auto":
        preset_name = _composite_preset_label(
            args, tim_injected=tim_injected, resolved_analytics_source=resolved_analytics_source
        )
    return SCORE_WEIGHT_PRESETS.get(preset_name) or SCORE_WEIGHT_PRESETS["default"]


def _build_grounding_policy(args: argparse.Namespace):
    from patagonia_eval_scoring import GroundingPolicy

    return GroundingPolicy(
        box_budget_max=int(getattr(args, "max_pred_boxes", 3)),
        box_budget_penalty_per_extra=float(getattr(args, "box_budget_penalty_per_extra", 0.08)),
        oversize_penalty_strength=float(getattr(args, "oversize_penalty_strength", 0.75)),
    )


def _apply_full_scoring(
    caption: str,
    target: EvalTarget,
    args: argparse.Namespace,
    gold_boxes: list[dict[str, Any]] | None,
    pass_metric_resolved: str,
    *,
    tim_injected: bool,
    analytics_in_prompt: dict[str, Any] | None,
    analysis_profile: str,
    resolved_analytics_source: str | None,
    tim_health: str | None,
    no_local_features: bool,
) -> dict[str, Any]:
    mode = args.score_mode.strip().lower()
    if mode == "all":
        mode = "composite"
    pm_eff = pass_metric_resolved.strip().lower()
    if pm_eff == "structured":
        pm_eff = "output_contract"
    if pm_eff == "tim_alignment":
        pm_eff = "faithfulness"

    gold_boxes_eff = None if no_local_features else gold_boxes
    scored = score_patagonia_multimodal(
        caption,
        target,
        threshold=args.score_threshold,
        gold_boxes=gold_boxes_eff,
        weights=_build_score_weights(
            args,
            tim_injected=tim_injected,
            resolved_analytics_source=resolved_analytics_source,
        ),
        score_mode=mode,
        pass_metric=pm_eff,
        grounding_label_mode=str(getattr(args, "grounding_label_mode", "canonical") or "canonical"),
        grounding_policy=_build_grounding_policy(args),
        analytics_in_prompt=analytics_in_prompt if tim_injected else None,
        analytics_source=resolved_analytics_source,
        analysis_profile=analysis_profile,
        no_local_features=no_local_features,
        tim_health=tim_health,
    )
    # Store the scalar that drove pass/fail so we can sweep thresholds without re-running inference.
    pass_value: float | None = None
    if pm_eff == "lexical":
        pass_value = float(scored["lexical"]["score"])
    elif pm_eff == "grounding":
        pass_value = None if scored["grounding"]["score"] is None else float(scored["grounding"]["score"])
    elif pm_eff in ("output_contract", "structured"):
        pass_value = float(scored["output_contract"]["score"])
    elif pm_eff in ("faithfulness", "tim_alignment"):
        fb = scored.get("faithfulness") or {}
        pv = fb.get("score")
        pass_value = None if pv is None else float(pv)
    else:
        pass_value = float(scored["composite"])
    fb_block = scored.get("faithfulness") or scored.get("tim_alignment") or {}
    return {
        "score": scored["score"],
        "passed": scored["passed"],
        "pass_value": pass_value,
        "expected_groups_hit": scored["lexical"]["expected_groups_hit"],
        "expected_groups_total": scored["lexical"]["expected_groups_total"],
        "expected_hits": scored["lexical"]["expected_hits"],
        "forbidden_hits": scored["lexical"]["forbidden_hits"],
        "claim_risk_hits": scored["lexical"]["claim_risk_hits"],
        "quality_flags": scored["lexical"]["quality_flags"],
        "word_count": scored["lexical"]["word_count"],
        "lexical_score": scored["lexical"]["score"],
        "grounding_score": scored["grounding"]["score"],
        "ship_plausibility_score": scored.get("ship_plausibility", {}).get("score"),
        "structured_score": scored["output_contract"]["score"],
        "tim_alignment_score": fb_block.get("score"),
        "composite_score": scored["composite"],
        "composite_weight_preset_resolved": _composite_preset_label(
            args,
            tim_injected=tim_injected,
            resolved_analytics_source=resolved_analytics_source,
        ),
        "resolved_analytics_source": resolved_analytics_source,
        "tim_health": tim_health,
        "no_local_features": no_local_features,
        "scoring": scored,
        "caption_quality": scored.get("caption_quality") or {},
    }


def _parse_threshold_sweep(arg: str) -> list[float]:
    raw = (arg or "").strip()
    if not raw:
        return []
    out: list[float] = []
    for part in re.split(r"[,\s]+", raw):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(float(p))
        except ValueError:
            continue
    # Stable unique thresholds
    out2: list[float] = []
    for x in sorted(set(out)):
        if 0.0 <= x <= 1.0:
            out2.append(float(x))
    return out2


def _summarize_for_threshold(results: list[dict[str, Any]], *, threshold: float) -> dict[str, dict[str, Any]]:
    """Same as _summarize, but pass/fail is recomputed from per-row pass_value >= threshold."""
    out: dict[str, dict[str, Any]] = {}
    for r in results:
        name = str(r["model_name"])
        cur = out.setdefault(name, {"n": 0, "errors": 0, "passed": 0})
        cur["n"] += 1
        if r.get("error"):
            cur["errors"] += 1
            continue
        pv = r.get("pass_value")
        if pv is None:
            # If this metric was unavailable for this row, treat as not passed.
            continue
        cur["passed"] += int(float(pv) >= float(threshold))
    for cur in out.values():
        scored = max(1, int(cur["n"]) - int(cur["errors"]))
        cur["pass_rate"] = round(float(cur["passed"]) / scored, 4)
    return out


def _refresh_stills_with_stac_cog_gold(
    args: argparse.Namespace,
    targets: list[EvalTarget],
    target_records: dict[str, dict[str, Any]],
    out_dir: Path,
) -> dict[str, Any]:
    """Replace cached stills with COG RGB aligned to SCL when possible; write ``gold/*.json`` sidecars."""
    data_scripts = REPO_ROOT / "data" / "scripts"
    if str(data_scripts) not in sys.path:
        sys.path.insert(0, str(data_scripts))
    from patagonia_eval_analytics_sources import sentinel_fractions_for_patagonia_chip
    from patagonia_eval_gold import gold_boxes_from_scl, gold_boxes_from_scl_delta
    from stac_reference_still import (
        fetch_sentinel_bitemporal_cog_rgb_scl_delta,
        fetch_sentinel_cog_rgb_scl_matched,
    )

    gold_dir = out_dir / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    gold_by_id: dict[str, Any] = {}
    st_raw = (args.stac_still_url or "").strip() or None
    coll = (args.stac_still_collection or "").strip() or None
    dt_default = (args.stac_still_datetime or "").strip()
    gold_mode = (getattr(args, "gold_mode", "state") or "state").strip().lower()
    min_sep = float(getattr(args, "gold_min_temporal_separation_days", 21.0))

    for t in targets:
        sidecar: dict[str, Any] = {"target_id": t.target_id, "gold_mode_requested": gold_mode}
        dt_eff = _temporal_datetime_for_target_args(args, t, default=dt_default)
        dt_raw = dt_eff or None
        scenes_for_target = list(_temporal_scenes(t))
        if scenes_for_target:
            sidecar["temporal_scenes"] = scenes_for_target
            sidecar["temporal_scenes_mode"] = (getattr(args, "temporal_scenes_mode", "latest") or "latest")
            sidecar["temporal_datetime_effective"] = dt_eff

        def _single_date_fallback(reason_key: str):
            rgb2, scl2, meta2 = fetch_sentinel_cog_rgb_scl_matched(
                t.lat,
                t.lon,
                width_px=int(args.mapbox_size),
                height_px=int(args.mapbox_size),
                stac_url=st_raw,
                collection=coll,
                bbox_half_km=float(args.stac_still_bbox_half_km),
                max_cloud=float(args.stac_still_max_cloud),
                max_items=int(args.stac_still_max_items),
                datetime_range=dt_raw,
            )
            sidecar[f"{reason_key}_fallback"] = "single_date_state_gold"
            sidecar["gold_mode_effective"] = "state"
            return rgb2, scl2, meta2

        if gold_mode == "delta":
            rgb, scl_early, scl_late, meta = fetch_sentinel_bitemporal_cog_rgb_scl_delta(
                t.lat,
                t.lon,
                width_px=int(args.mapbox_size),
                height_px=int(args.mapbox_size),
                stac_url=st_raw,
                collection=coll,
                bbox_half_km=float(args.stac_still_bbox_half_km),
                max_cloud=float(args.stac_still_max_cloud),
                max_items=int(args.stac_still_max_items),
                datetime_range=dt_raw,
                min_temporal_separation_days=min_sep,
            )
            sidecar["stac_pair_meta"] = meta
            if rgb is not None and scl_early is not None and scl_late is not None and meta.get("ok_delta"):
                boxes = gold_boxes_from_scl_delta(scl_early, scl_late, category=t.category)
                sidecar["gold_mode_effective"] = "delta"
                if not boxes:
                    boxes = gold_boxes_from_scl(scl_late, category=t.category)
                    sidecar["delta_fallback"] = "empty_delta_mask_used_state_on_late_scl"
                fr, fr_tag = sentinel_fractions_for_patagonia_chip(np.asarray(scl_late, dtype=np.uint8), category=t.category)
                sidecar["sentinel_scl_fractions"] = {str(k): float(v) for k, v in fr.items()}
                if fr_tag != "strict":
                    sidecar["sentinel_scl_fractions_tag"] = fr_tag
                _attach_dynamic_world_to_sidecar(sidecar, args, t, meta)
                p = Path(target_records[t.target_id]["image_path"])
                rgb.save(p)
                target_records[t.target_id]["image_sha256"] = _sha256_bytes(p.read_bytes())
                prov = target_records[t.target_id].setdefault("still_provenance", {})
                if isinstance(prov, dict):
                    prov["cog_scl_gold_refresh"] = True
                    prov["stac_gold_item_id"] = meta.get("late_item_id") or meta.get("item_id")
                    prov["stac_gold_bitemporal"] = True
                gold_by_id[t.target_id] = boxes
                sidecar["gold_boxes"] = boxes
                _write_json(gold_dir / f"{t.target_id}.json", sidecar)
                continue

            sidecar["delta_failure_reason"] = meta.get("reason", "delta_fetch_failed")
            rgb, scl, meta = _single_date_fallback("delta")
            sidecar["stac_pair_meta"] = meta
            if rgb is not None and scl is not None:
                p = Path(target_records[t.target_id]["image_path"])
                rgb.save(p)
                target_records[t.target_id]["image_sha256"] = _sha256_bytes(p.read_bytes())
                prov = target_records[t.target_id].setdefault("still_provenance", {})
                if isinstance(prov, dict):
                    prov["cog_scl_gold_refresh"] = True
                    prov["stac_gold_item_id"] = meta.get("item_id")
                boxes = gold_boxes_from_scl(scl, category=t.category)
                gold_by_id[t.target_id] = boxes
                sidecar["gold_boxes"] = boxes
                fr, fr_tag = sentinel_fractions_for_patagonia_chip(np.asarray(scl, dtype=np.uint8), category=t.category)
                sidecar["sentinel_scl_fractions"] = {str(k): float(v) for k, v in fr.items()}
                if fr_tag != "strict":
                    sidecar["sentinel_scl_fractions_tag"] = fr_tag
                _attach_dynamic_world_to_sidecar(sidecar, args, t, meta)
            else:
                gold_by_id[t.target_id] = None
                sidecar["gold_boxes"] = None
                sidecar["reason"] = meta.get("reason", "cog_pair_failed")
            _write_json(gold_dir / f"{t.target_id}.json", sidecar)
            continue

        rgb, scl, meta = fetch_sentinel_cog_rgb_scl_matched(
            t.lat,
            t.lon,
            width_px=int(args.mapbox_size),
            height_px=int(args.mapbox_size),
            stac_url=st_raw,
            collection=coll,
            bbox_half_km=float(args.stac_still_bbox_half_km),
            max_cloud=float(args.stac_still_max_cloud),
            max_items=int(args.stac_still_max_items),
            datetime_range=dt_raw,
        )
        sidecar["stac_pair_meta"] = meta
        sidecar["gold_mode_effective"] = "state"
        if rgb is not None and scl is not None:
            p = Path(target_records[t.target_id]["image_path"])
            rgb.save(p)
            target_records[t.target_id]["image_sha256"] = _sha256_bytes(p.read_bytes())
            prov = target_records[t.target_id].setdefault("still_provenance", {})
            if isinstance(prov, dict):
                prov["cog_scl_gold_refresh"] = True
                prov["stac_gold_item_id"] = meta.get("item_id")
            boxes = gold_boxes_from_scl(scl, category=t.category)
            gold_by_id[t.target_id] = boxes
            sidecar["gold_boxes"] = boxes
            fr, fr_tag = sentinel_fractions_for_patagonia_chip(np.asarray(scl, dtype=np.uint8), category=t.category)
            sidecar["sentinel_scl_fractions"] = {str(k): float(v) for k, v in fr.items()}
            if fr_tag != "strict":
                sidecar["sentinel_scl_fractions_tag"] = fr_tag
            _attach_dynamic_world_to_sidecar(sidecar, args, t, meta)
        else:
            gold_by_id[t.target_id] = None
            sidecar["gold_boxes"] = None
            sidecar["reason"] = meta.get("reason", "cog_pair_failed")
        _write_json(gold_dir / f"{t.target_id}.json", sidecar)
    return gold_by_id


def _load_gold_sidecars(out_dir: Path, targets: list[EvalTarget]) -> dict[str, dict[str, Any]]:
    gold_dir = out_dir / "gold"
    by_id: dict[str, dict[str, Any]] = {}
    for t in targets:
        p = gold_dir / f"{t.target_id}.json"
        if not p.exists():
            by_id[t.target_id] = {}
            continue
        try:
            by_id[t.target_id] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            by_id[t.target_id] = {}
    return by_id


def _scl_fractions_from_sidecar(sidecar: dict[str, Any]) -> dict[int, float] | None:
    raw = sidecar.get("sentinel_scl_fractions")
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[int, float] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out or None


def _dw_fractions_from_sidecar(sidecar: dict[str, Any]) -> dict[int, float] | None:
    raw = sidecar.get("dynamic_world_fractions")
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[int, float] = {}
    for k, v in raw.items():
        try:
            out[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out or None


def _attach_dynamic_world_to_sidecar(
    sidecar: dict[str, Any],
    args: argparse.Namespace,
    t: EvalTarget,
    meta: dict[str, Any] | None,
) -> None:
    """Populate ``dynamic_world_fractions`` / ``dynamic_world_fetch`` when ``--fetch-dynamic-world``."""
    if not getattr(args, "fetch_dynamic_world", False):
        return
    from patagonia_eval_analytics_sources import fractions_from_dynamic_world_label
    from patagonia_eval_dynamic_world import fetch_dynamic_world_chip

    dt_fallback = _temporal_datetime_for_target_args(args, t, default=(args.stac_still_datetime or "").strip())
    chip, dmeta = fetch_dynamic_world_chip(
        t.lat,
        t.lon,
        width_px=int(args.mapbox_size),
        height_px=int(args.mapbox_size),
        bbox_half_km=float(args.stac_still_bbox_half_km),
        stac_meta=meta if isinstance(meta, dict) else None,
        datetime_query_fallback=dt_fallback,
    )
    sidecar["dynamic_world_fetch"] = dmeta
    if chip is None:
        return
    fr = fractions_from_dynamic_world_label(np.asarray(chip, dtype=np.uint8))
    sidecar["dynamic_world_fractions"] = {str(k): float(v) for k, v in fr.items()}


def _lulc_class_pcts_percent(analytics: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(analytics, dict):
        return {}
    tmo = analytics.get("tim_modality_outputs")
    if not isinstance(tmo, dict):
        return {}
    lulc = tmo.get("LULC")
    if not isinstance(lulc, dict):
        return {}
    cf = lulc.get("class_fractions")
    if not isinstance(cf, dict):
        return {}
    out: dict[str, float] = {}
    for name, frac in cf.items():
        if not isinstance(name, str):
            continue
        if not isinstance(frac, (int, float)):
            continue
        out[name] = float(frac) * 100.0
    return out


def _target_profile(target: EvalTarget) -> str:
    hint = (getattr(target, "analysis_profile_hint", "") or "").strip().lower()
    if hint:
        return hint
    cat = target.category.lower()
    if "glacier" in cat:
        return "brief_only"
    if "marine" in cat or "water" in cat:
        return "oceanscout_ship_detection"
    if "forest" in cat or "coastal" in cat or "urban" in cat:
        return "land_use_change"
    return "brief_only"


def _temporal_scenes(target: EvalTarget) -> tuple[str, ...]:
    """Normalized ``EvalTarget.temporal_scenes`` (whitespace-trimmed; empty entries dropped)."""
    raw = getattr(target, "temporal_scenes", ()) or ()
    if isinstance(raw, str):
        raw = (raw,)
    out: list[str] = []
    for entry in raw:
        s = str(entry or "").strip()
        if s:
            out.append(s)
    return tuple(out)


def _temporal_datetime_for_target(target: EvalTarget, fallback: str, mode: str = "latest") -> str:
    """Resolve a single STAC ``datetime`` interval for ``target`` from ``temporal_scenes``.

    - ``latest``: use the last scene; bi-temporal scoring uses earlier scenes implicitly via STAC search.
    - ``union``: combine first-start / last-end into a single wide ``YYYY-MM-DD/YYYY-MM-DD`` interval
      so STAC has the full window to pick a recent valid item.

    Returns ``fallback`` when ``temporal_scenes`` is empty or unusable.
    """
    scenes = _temporal_scenes(target)
    if not scenes:
        return fallback
    m = (mode or "latest").strip().lower()
    if m == "latest" or len(scenes) == 1:
        return scenes[-1]
    if m == "union":

        def _split(rng: str) -> tuple[str, str]:
            a, _sep, b = rng.partition("/")
            return a.strip(), b.strip() or a.strip()

        starts = [_split(s)[0] for s in scenes if "/" in s or s]
        ends = [_split(s)[1] for s in scenes if "/" in s or s]
        if not starts or not ends:
            return scenes[-1]
        return f"{min(starts)}/{max(ends)}"
    return scenes[-1]


def _temporal_datetime_for_target_args(args: argparse.Namespace, target: EvalTarget, *, default: str) -> str:
    mode = (getattr(args, "temporal_scenes_mode", "latest") or "latest").strip().lower()
    return _temporal_datetime_for_target(target, default, mode=mode)


def _tim_batch_row_for_target(args: argparse.Namespace, t: EvalTarget) -> dict[str, Any]:
    row: dict[str, Any] = {
        "map_id": t.target_id,
        "location_id": t.target_id,
        "analysis_profile": _target_profile(t),
        "rgb_mode": "s2_rgb",
        "s2_mode": "stac",
        "lat": t.lat,
        "lon": t.lon,
        "datetime": _temporal_datetime_for_target_args(args, t, default=args.s2_datetime),
    }
    scenes = _temporal_scenes(t)
    if scenes:
        row["temporal_scenes"] = list(scenes)
    return row


def _tim_batch_config(
    args: argparse.Namespace,
    targets: list[EvalTarget],
    *,
    tim_device_effective: str,
) -> dict[str, Any]:
    return {
        "content_version": "nutonic.patagonia_tim_e2e.v1",
        "paths": {"repo_root": str(REPO_ROOT)},
        "model_id": args.tim_model_id,
        "pretrained": True,
        "merge_method": args.tim_merge_method,
        "modalities": ["RGB", "S2L2A"],
        "tim_modalities": args.tim_modalities,
        "device": tim_device_effective,
        "inputs": {
            "batch_size": 1,
            "s2_mode": "stac",
            "datetime": args.s2_datetime,
            "s2": {
                "stac_url": args.stac_url,
                "collection": args.stac_collection,
                "half_km": args.s2_half_km,
                "patch_hw": 224,
                "max_cloud": args.s2_max_cloud,
                "max_items": args.s2_max_items,
            },
        },
        "serialization": {
            "tensor_sample_limit": args.tim_tensor_sample_limit,
            "encoder_tensor_sample_limit": 0,
            "include_encoder_trace": False,
            "encoder_trace_mode": "last",
            "tim_outputs": args.tim_outputs,
            "include_tim_raw_keys": False,
        },
        "export": {"include_ai_guess_row": True},
        "batch": [_tim_batch_row_for_target(args, t) for t in targets],
    }


def _run_local_tim(
    args: argparse.Namespace,
    targets: list[EvalTarget],
    out_dir: Path,
    *,
    tim_device_effective: str,
) -> dict[str, dict[str, Any]]:
    try:
        from nutonic_terramind_tim_local.run import run_tim_batch_export
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "Local TiM dependencies are not importable. Install with:\n"
            "  uv sync --project inference/terramind_tim_local --extra s2\n"
            "Then run this script with that environment, e.g.:\n"
            "  uv run --directory inference/terramind_tim_local python ../../tools/evaluate_vlm_patagonia_tim_e2e.py ...\n"
            f"Import error: {type(exc).__name__}: {exc}"
        ) from exc

    cfg = _tim_batch_config(args, targets, tim_device_effective=tim_device_effective)
    _write_json(out_dir / "tim" / "tim_config.json", cfg)
    rows = run_tim_batch_export(cfg)
    export_path = out_dir / "tim" / "tim_export.jsonl"
    if export_path.exists():
        export_path.unlink()
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        _append_jsonl(export_path, row)
        by_id[str(row.get("location_id") or row.get("map_id"))] = row
    return by_id


def _load_local_vlm(model_id: str, *, device: str, dtype: str) -> tuple[Any, Any]:
    try:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Install transformers/torch for --local-vlm-model.") from exc

    torch_dtype = getattr(torch, dtype) if dtype != "auto" else "auto"
    kwargs: dict[str, Any] = {"trust_remote_code": True}
    if torch_dtype != "auto":
        kwargs["dtype"] = torch_dtype
    if device == "auto":
        kwargs["device_map"] = "auto"
    model = AutoModelForImageTextToText.from_pretrained(model_id, **kwargs)
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    if device not in ("auto", "cpu"):
        model = model.to(device)
    model.eval()
    return model, processor


def _local_vlm_caption(
    model: Any,
    processor: Any,
    *,
    image_path: Path,
    prompt: str,
    max_new_tokens: int,
    system_text: str | None = None,
) -> str:
    import torch

    image = Image.open(image_path).convert("RGB")
    conversation: list[dict[str, Any]] = []
    if system_text:
        conversation.append({"role": "system", "content": system_text})
    conversation.append(
        {"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}
    )
    inputs = processor.apply_chat_template(
        conversation,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
        tokenize=True,
    )
    device = getattr(model, "device", None)
    if device is not None and hasattr(inputs, "to"):
        inputs = inputs.to(device)
    elif device is not None:
        inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}
    in_len = int(inputs["input_ids"].shape[1])
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    return processor.batch_decode(out[:, in_len:], skip_special_tokens=True)[0].strip()


def _summarize(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in results:
        name = str(r["model_name"])
        cur = out.setdefault(
            name,
            {
                "n": 0,
                "errors": 0,
                "passed": 0,
                "score_sum": 0.0,
                "lexical_sum": 0.0,
                "grounding_sum": 0.0,
                "ship_sum": 0.0,
                "tim_align_sum": 0.0,
                "structured_sum": 0.0,
                "composite_sum": 0.0,
                "lexical_n": 0,
                "grounding_n": 0,
                "ship_n": 0,
                "tim_align_n": 0,
                "structured_n": 0,
                "composite_n": 0,
            },
        )
        cur["n"] += 1
        if r.get("error"):
            cur["errors"] += 1
            continue
        cur["passed"] += int(bool(r.get("passed")))
        cur["score_sum"] += float(r.get("score") or 0.0)
        if r.get("lexical_score") is not None:
            cur["lexical_sum"] += float(r["lexical_score"])
            cur["lexical_n"] += 1
        if r.get("grounding_score") is not None:
            cur["grounding_sum"] += float(r["grounding_score"])
            cur["grounding_n"] += 1
        if r.get("ship_plausibility_score") is not None:
            cur["ship_sum"] += float(r["ship_plausibility_score"])
            cur["ship_n"] += 1
        if r.get("tim_alignment_score") is not None:
            cur["tim_align_sum"] += float(r["tim_alignment_score"])
            cur["tim_align_n"] += 1
        if r.get("structured_score") is not None:
            cur["structured_sum"] += float(r["structured_score"])
            cur["structured_n"] += 1
        if r.get("composite_score") is not None:
            cur["composite_sum"] += float(r["composite_score"])
            cur["composite_n"] += 1
    for cur in out.values():
        scored = max(1, int(cur["n"]) - int(cur["errors"]))
        cur["mean_score"] = round(float(cur["score_sum"]) / scored, 4)
        cur["pass_rate"] = round(float(cur["passed"]) / scored, 4)
        cur.pop("score_sum", None)
        if cur.get("lexical_n", 0) > 0:
            cur["mean_lexical_score"] = round(cur["lexical_sum"] / cur["lexical_n"], 4)
        if cur.get("grounding_n", 0) > 0:
            cur["mean_grounding_score"] = round(cur["grounding_sum"] / cur["grounding_n"], 4)
        if cur.get("ship_n", 0) > 0:
            cur["mean_ship_plausibility_score"] = round(cur["ship_sum"] / cur["ship_n"], 4)
        if cur.get("structured_n", 0) > 0:
            cur["mean_structured_score"] = round(cur["structured_sum"] / cur["structured_n"], 4)
        if cur.get("composite_n", 0) > 0:
            cur["mean_composite_score"] = round(cur["composite_sum"] / cur["composite_n"], 4)
        if cur.get("tim_align_n", 0) > 0:
            cur["mean_tim_alignment_score"] = round(cur["tim_align_sum"] / cur["tim_align_n"], 4)
        for k in (
            "lexical_sum",
            "lexical_n",
            "grounding_sum",
            "grounding_n",
            "ship_sum",
            "ship_n",
            "tim_align_sum",
            "tim_align_n",
            "structured_sum",
            "structured_n",
            "composite_sum",
            "composite_n",
        ):
            cur.pop(k, None)
    return out


def _summarize_variant_pairs(summary_by_model: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """When ``local_vlm_variants`` is ``both``, compare ``model`` vs ``model_no_tim``."""
    out: dict[str, dict[str, Any]] = {}
    for name, s_nt in summary_by_model.items():
        if not str(name).endswith("_no_tim"):
            continue
        base = str(name)[: -len("_no_tim")]
        s_tim = summary_by_model.get(base)
        if not isinstance(s_tim, dict) or not isinstance(s_nt, dict):
            continue
        key = f"{base}_tim_vs_no_tim"
        out[key] = {
            "tim_variant": base,
            "no_tim_variant": str(name),
            "delta_mean_primary": round(float(s_tim.get("mean_score", 0.0)) - float(s_nt.get("mean_score", 0.0)), 4),
            "delta_mean_composite": round(
                float(s_tim.get("mean_composite_score") or 0.0) - float(s_nt.get("mean_composite_score") or 0.0),
                4,
            ),
            "delta_mean_grounding": _delta_optional_mean(s_tim, s_nt, "mean_grounding_score"),
            "delta_mean_tim_alignment": _delta_optional_mean(s_tim, s_nt, "mean_tim_alignment_score"),
            "tim_summary": {"mean_score": s_tim.get("mean_score"), "pass_rate": s_tim.get("pass_rate")},
            "no_tim_summary": {"mean_score": s_nt.get("mean_score"), "pass_rate": s_nt.get("pass_rate")},
        }
    return out


def _summarize_by_category(
    results: list[dict[str, Any]], *, target_records: dict[str, dict[str, Any]]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Model -> category -> same summary fields as `_summarize`."""
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in results:
        m = str(r.get("model_name") or "")
        tid = str(r.get("target_id") or "")
        cat = (
            str(((target_records.get(tid) or {}).get("target") or {}).get("category") or "unknown")
            .strip()
            .lower()
        )
        buckets.setdefault(m, {}).setdefault(cat, []).append(r)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for m, cats in buckets.items():
        out[m] = {}
        for cat, rows in cats.items():
            out[m][cat] = _summarize(rows).get(m, {"n": len(rows), "errors": 0, "passed": 0, "pass_rate": 0.0, "mean_score": 0.0})
    return out


def _summarize_by_profile(results: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Model -> effective ``analysis_profile`` -> same summary fields as ``_summarize``."""
    buckets: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for r in results:
        m = str(r.get("model_name") or "")
        prof = str(r.get("analysis_profile") or "unknown").strip().lower() or "unknown"
        buckets.setdefault(m, {}).setdefault(prof, []).append(r)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for m, profs in buckets.items():
        out[m] = {}
        for prof, rows in profs.items():
            out[m][prof] = _summarize(rows).get(
                m, {"n": len(rows), "errors": 0, "passed": 0, "pass_rate": 0.0, "mean_score": 0.0}
            )
    return out


def _summary_metric_cell(summary_row: dict[str, Any], key: str) -> str:
    v = summary_row.get(key)
    return f"{float(v):.3f}" if v is not None else "—"


def _delta_optional_mean(a: dict[str, Any], b: dict[str, Any], field: str) -> float | None:
    av = a.get(field)
    bv = b.get(field)
    if av is None or bv is None:
        return None
    try:
        return round(float(av) - float(bv), 4)
    except (TypeError, ValueError):
        return None


def _write_markdown(out_dir: Path, payload: dict[str, Any]) -> None:
    meta = payload["meta"]
    lines = [
        "# Patagonia TiM E2E VLM Evaluation",
        "",
        f"Generated: `{meta['generated_at_utc']}`",
        f"Scoring: `{meta.get('score_mode', '')}` · pass metric: `{meta.get('pass_metric_resolved', '')}` · "
        f"threshold `{meta.get('score_threshold', '')}`",
        "",
        "## What this run measures",
        "",
        "- **Optical / SCL alignment**: grounding IoU vs Sentinel-2 scene-class reference boxes (single-acquisition **state**, not TiM-predicted change).",
        "- **Lexical probes**: curated keyword groups per AOI (`EvalTarget.expected_any`), not STAC item metadata text.",
        "- **TiM alignment** (when TiM is injected): heuristic checks that the caption engages TiM themes and separates model-shaped signals from pure optics — orthogonal to SCL IoU.",
        "- **Gold mode**: `state` = single-date SCL; `delta` = bi-temporal SCL XOR regions when STAC provides two spaced acquisitions (see `gold/*.json` sidecars).",
        "- **Contrastive TiM**: rows named `*_tim_contrast_flip` negate modality numeric samples to expose caption sensitivity to TiM JSON.",
        "- **Composite**: weighted blend (preset-controlled); `--composite-weight-preset auto` uses **tim_integration** weights for TiM prompts and **optical_focus** for image-only rows.",
        "",
        "## Summary",
        "",
        "| Model | Targets | Errors | Pass Rate | Mean (primary) | Mean Lex | Mean Grd | Mean Ship | Mean TiM | Mean Str | Mean Comp |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, s in payload["summary_by_model"].items():
        lines.append(
            f"| {name} | {s['n']} | {s['errors']} | {s['pass_rate']:.3f} | {s['mean_score']:.3f} | "
            f"{_summary_metric_cell(s, 'mean_lexical_score')} | {_summary_metric_cell(s, 'mean_grounding_score')} | "
            f"{_summary_metric_cell(s, 'mean_ship_plausibility_score')} | {_summary_metric_cell(s, 'mean_tim_alignment_score')} | "
            f"{_summary_metric_cell(s, 'mean_structured_score')} | "
            f"{_summary_metric_cell(s, 'mean_composite_score')} |"
        )
    lines.extend(["", "## Artifacts", ""])
    lines.append("- `report.json`: full machine-readable report")
    lines.append("- `predictions.jsonl`: one row per model/target prediction")
    lines.append("- `prompts.jsonl`: exact user prompt records with injected TiM JSON")
    lines.append("- `tim/tim_export.jsonl`: local TiM outputs")
    lines.append("- `images/`: cached reference stills (STAC or Mapbox)")
    lines.append("- `gold/`: Sentinel-2 SCL-derived reference boxes (when STAC COG pair succeeded)")
    lines.append("- `judge_pack.jsonl`: optional rubric export when using `--write-judge-pack`")
    if payload.get("summary_tim_vs_no_tim"):
        lines.extend(["", "## TiM vs image-only (paired models)", ""])
        lines.append("| Pair | Δ primary | Δ composite | Δ grounding | Δ TiM align |")
        lines.append("|---|---:|---:|---:|---:|")
        for pk, row in payload["summary_tim_vs_no_tim"].items():
            if not isinstance(row, dict):
                continue
            dg = row.get("delta_mean_grounding")
            dt = row.get("delta_mean_tim_alignment")
            lines.append(
                f"| `{pk}` | {row.get('delta_mean_primary', '')} | {row.get('delta_mean_composite', '')} | "
                f"{dg if dg is not None else '—'} | {dt if dt is not None else '—'} |"
            )

    sweep = payload.get("threshold_sweep")
    if isinstance(sweep, dict) and sweep:
        lines.extend(["", "## Threshold sweep (pass_rate)", ""])
        models = list(payload["summary_by_model"].keys())
        if models:
            lines.append("| Threshold | " + " | ".join(models) + " |")
            lines.append("|---:|" + "|".join(["---:"] * len(models)) + "|")
            for thr in sorted((float(k), k) for k in sweep.keys()):
                k = thr[1]
                row = sweep.get(k) or {}
                cells: list[str] = []
                for m in models:
                    pr = None
                    if isinstance(row, dict):
                        mr = row.get(m)
                        if isinstance(mr, dict):
                            pr = mr.get("pass_rate")
                    cells.append(f"{float(pr):.3f}" if pr is not None else "—")
                lines.append(f"| {float(k):.2f} | " + " | ".join(cells) + " |")

    by_cat = payload.get("summary_by_model_by_category")
    if isinstance(by_cat, dict) and by_cat:
        lines.extend(["", "## Breakdown by category (mean primary / pass_rate)", ""])
        cats: list[str] = sorted({c for m in by_cat.values() if isinstance(m, dict) for c in m.keys()})
        if cats:
            lines.append("| Model | " + " | ".join(cats) + " |")
            lines.append("|---|" + "|".join(["---:"] * len(cats)) + "|")
            for model, mrow in by_cat.items():
                if not isinstance(mrow, dict):
                    continue
                cells: list[str] = []
                for c in cats:
                    s = mrow.get(c) if isinstance(mrow.get(c), dict) else None
                    if isinstance(s, dict):
                        cells.append(f"{float(s.get('mean_score', 0.0)):.3f}/{float(s.get('pass_rate', 0.0)):.2f}")
                    else:
                        cells.append("—")
                lines.append("| " + str(model) + " | " + " | ".join(cells) + " |")
    lines.extend(["", "## Per-Target Results", ""])
    for r in payload["results"]:
        lines.append(f"### {r['target_id']} · {r['model_name']}")
        if r.get("error"):
            lines.append(f"- Error: `{r['error']}`")
        else:
            lines.append(
                f"- Primary score: `{r['score']}` · passed: `{r['passed']}` · "
                f"lex `{r.get('lexical_score', '')}` · grd `{r.get('grounding_score', '')}` · "
                f"tim `{r.get('tim_alignment_score', '')}` · "
                f"str `{r.get('structured_score', '')}` · comp `{r.get('composite_score', '')}`"
            )
            lines.append(f"- Hits: `{', '.join(r.get('expected_hits') or [])}`")
            flags = ", ".join(r.get("quality_flags") or [])
            if flags:
                lines.append(f"- Flags: `{flags}`")
            cap = str(r.get("caption") or "").replace("\n", " ")
            lines.append(f"- Caption: {cap[:500]}")
        lines.append("")
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument(
        "--still-source",
        choices=("mapbox", "stac"),
        default="stac",
        help="Reference imagery: STAC Sentinel-2 (default) or Mapbox Satellite static API.",
    )
    p.add_argument("--mapbox-token", default=os.environ.get("MAPBOX_ACCESS_TOKEN", ""))
    p.add_argument(
        "--mapbox-size",
        type=int,
        default=640,
        help="Square edge in pixels for stills (Mapbox or STAC thumbnail size).",
    )
    p.add_argument(
        "--stac-still-url",
        default="",
        help="STAC API root for stills (default: Earth Search or NUTONIC_STAC_STILL_URL).",
    )
    p.add_argument("--stac-still-collection", default="", help="STAC collection for stills (default: sentinel-2-l2a).")
    p.add_argument("--stac-still-bbox-half-km", type=float, default=14.0)
    p.add_argument("--stac-still-max-cloud", type=float, default=80.0)
    p.add_argument("--stac-still-max-items", type=int, default=30)
    p.add_argument("--stac-still-datetime", default="")
    p.add_argument("--refresh-images", action="store_true")
    p.add_argument("--category", action="append", default=[])
    p.add_argument("--target-id", action="append", default=[])
    p.add_argument("--max-targets", type=int, default=0)
    p.add_argument(
        "--score-threshold",
        type=float,
        default=0.5,
        help="Pass threshold for the active pass metric (default 0.5; use 0.55 for stricter legacy-style runs).",
    )
    p.add_argument(
        "--score-mode",
        choices=(
            "lexical",
            "grounding",
            "structured",
            "output_contract",
            "tim_alignment",
            "faithfulness",
            "composite",
            "all",
        ),
        default="composite",
        help="Primary reported score. ``structured`` aliases ``output_contract``; ``tim_alignment`` aliases ``faithfulness``.",
    )
    p.add_argument(
        "--grounding-label-mode",
        choices=("canonical", "any"),
        default="canonical",
        help="Grounding IoU matching: canonical (label must map to water/vegetation/snow_ice/bare) or any (label-agnostic).",
    )
    p.add_argument("--max-pred-boxes", type=int, default=3, help="Predicted box budget before grounding penalty.")
    p.add_argument(
        "--box-budget-penalty-per-extra",
        type=float,
        default=0.08,
        help="Grounding multiplicative penalty per predicted box beyond --max-pred-boxes.",
    )
    p.add_argument(
        "--oversize-penalty-strength",
        type=float,
        default=0.75,
        help="Penalize predicted boxes much larger than the gold region (0 disables; higher penalizes more).",
    )
    p.add_argument(
        "--pass-metric",
        default="auto",
        help="Pass/fail driver: auto (follows score-mode), lexical, grounding, output_contract (alias structured), "
        "faithfulness (alias tim_alignment), or composite.",
    )
    p.add_argument(
        "--composite-weight-preset",
        choices=(
            "auto",
            "default",
            "image_only",
            "procedural_analytics",
            "synthetic_oracle",
            "tim_generated",
            "optical_focus",
            "tim_integration",
        ),
        default="auto",
        help="4-axis composite presets (lexical/grounding/output_contract/faithfulness). "
        "``auto`` picks by ``--analytics-source`` + whether analytics JSON is injected.",
    )
    p.add_argument(
        "--score-weight",
        nargs=3,
        type=float,
        metavar=("LEX", "GRD", "CONTRACT"),
        default=None,
        help="Deprecated: override LEX/GRD/CONTRACT with faithfulness forced to 0. Prefer --composite-weight-preset.",
    )
    p.add_argument(
        "--threshold-sweep",
        default="0.3,0.4,0.5,0.55,0.6",
        help=(
            "Comma/space-separated thresholds to compute pass-rate curves from the *same* run "
            "(no extra inference). Uses pass_metric_resolved."
        ),
    )
    p.add_argument(
        "--no-stac-gold",
        action="store_true",
        help="Do not replace stills with COG RGB+SCL pair or write gold/ (lexical+contract-only composite path).",
    )
    p.add_argument(
        "--gold-mode",
        choices=("state", "delta"),
        default="state",
        help="Reference boxes: single-date SCL components (state) or bi-temporal SCL XOR change regions (delta). "
        "Delta requires two acquisitions ≥ --gold-min-temporal-separation-days apart (falls back to state).",
    )
    p.add_argument(
        "--gold-min-temporal-separation-days",
        type=float,
        default=21.0,
        help="Minimum days between early and late STAC items when --gold-mode delta.",
    )
    p.add_argument(
        "--temporal-scenes-mode",
        choices=("latest", "union"),
        default="latest",
        help=(
            "How to resolve EvalTarget.temporal_scenes into a STAC datetime. "
            "``latest`` uses the last entry as the per-target datetime; ``union`` combines first start "
            "with last end into a wide search interval. Falls back to --stac-still-datetime / --s2-datetime "
            "when temporal_scenes is empty."
        ),
    )
    p.add_argument(
        "--write-judge-pack",
        action="store_true",
        help="Write judge_pack.jsonl (prompt-side TiM JSON + caption + scores) for human/LLM rubric evaluation.",
    )
    p.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help=(
            "Optional HTTP /v1/infer (image only; no TiM in body). Repeatable. By default HTTP is off; "
            "set NUTONIC_PATAGONIA_EVAL_ENABLE_HTTP=1 to use FINETUNE_URL+BASE_URL or SATELLITE_URL from env."
        ),
    )
    p.add_argument(
        "--skip-local-vlm",
        action="store_true",
        help="Do not run local Transformers models (use with --endpoint or ENABLE_HTTP for HTTP-only).",
    )
    p.add_argument(
        "--hf-dataset-repo",
        default=os.environ.get("NUTONIC_PATAGONIA_EVAL_HF_DATASET", ""),
        help="Upload this run to this HF dataset repo id after success (also env NUTONIC_PATAGONIA_EVAL_HF_DATASET).",
    )
    p.add_argument(
        "--hf-upload-path-in-repo",
        default="",
        help="Dataset repo subpath (default: patagonia_eval_runs/<UTC>).",
    )
    p.add_argument(
        "--hf-upload-token",
        default=os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN") or "",
        help="Hub token for upload (default: HF_TOKEN).",
    )
    p.add_argument("--hf-upload-private", action="store_true", help="Create dataset repo as private if missing.")
    p.add_argument("--skip-hf-upload", action="store_true", help="Disable Hub upload even if env/repo is set.")
    p.add_argument(
        "--hf-upload-no-by-model",
        action="store_true",
        help="Upload only the full run folder; skip extra by_model/<finetune|base>/ copies.",
    )
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--skip-health-check", action="store_true")
    p.add_argument(
        "--analytics-source",
        choices=(
            "none",
            "procedural",
            "dynamic_world",
            "synthetic_oracle",
            "tim_generated",
            "procedural_or_tim",
            "procedural_or_dw",
        ),
        default="procedural_or_tim",
        help=(
            "Which analytics JSON is injected into the TiM-style production prompt. "
            "``procedural`` uses SFT-aligned deterministic analytics from SCL fractions; "
            "``dynamic_world`` / ``procedural_or_dw`` prefer EE Dynamic World label-chip fractions "
            "when ``gold/*.json`` contains ``dynamic_world_fractions`` (see ``--fetch-dynamic-world``); "
            "``procedural_or_tim`` prefers healthy local TiM JSON when available."
        ),
    )
    p.add_argument(
        "--fetch-dynamic-world",
        action="store_true",
        help=(
            "During STAC gold refresh, fetch Google Dynamic World (Earth Engine) label chip aligned to the "
            "same footprint/datetime and store ``dynamic_world_fractions`` (+ ``dynamic_world_fetch``) in "
            "``gold/<target_id>.json``. Prefer service-account auth (``GOOGLE_APPLICATION_CREDENTIALS`` + project); "
            "see ``patagonia_eval_dynamic_world`` / ``lfm_vl_sft_dataset.ee_auth``."
        ),
    )
    p.add_argument(
        "--no-fetch-dynamic-world",
        action="store_true",
        help=(
            "Skip Earth Engine Dynamic World fetch (sets ``NUTONIC_SKIP_EE_DYNAMIC_WORLD=1``). "
            "Use on CI without EE credentials to avoid auth noise in ``gold/*.json``. Mutually exclusive with "
            "``--fetch-dynamic-world``."
        ),
    )
    p.add_argument(
        "--synthetic-oracle-yaml",
        default="",
        help="Optional override path for tools/data/patagonia_synthetic_oracle.yaml (synthetic_oracle source).",
    )
    p.add_argument(
        "--visual-gold-yaml",
        default="",
        help="Optional override path for tools/data/patagonia_visual_gold.yaml (no_local_features grounding hints).",
    )
    p.add_argument(
        "--counterfactuals",
        action="append",
        default=[],
        help=(
            "Optional extra local-VLM passes per probe (repeatable). Choices: "
            + ", ".join(ALL_KINDS)
            + ". ``tim_payload_flip`` mirrors --contrastive-tim-flip."
        ),
    )
    p.add_argument(
        "--local-vlm-model",
        action="append",
        default=[],
        help=(
            "HF model id for TiM-in-prompt eval (repeatable). If omitted, runs finetune vs base "
            "from patagonia_comparison_hf_model_ids() (NuTonic/lspace vs LiquidAI/LFM2.5-VL-450M)."
        ),
    )
    p.add_argument(
        "--contrastive-tim-flip",
        action="store_true",
        help="After each TiM local-VLM run, run a second pass with negated tim_modality numeric samples "
        "and record responsiveness vs baseline caption (behavioral TiM sensitivity probe).",
    )
    p.add_argument(
        "--local-vlm-variants",
        choices=("tim", "no_tim", "both"),
        default="both",
        help=(
            "Which local VLM runs to execute per model: "
            "tim (TiM JSON injected), no_tim (image-only), or both (default)."
        ),
    )
    p.add_argument("--local-vlm-device", default="auto")
    p.add_argument("--local-vlm-dtype", default="bfloat16")
    p.add_argument("--max-new-tokens", type=int, default=220)
    p.add_argument(
        "--tim-model-id",
        default=DEFAULT_TIM_MODEL_ID,
        help=f"TerraTorch TiM backbone (default: {DEFAULT_TIM_MODEL_ID}, largest).",
    )
    p.add_argument(
        "--tim-device",
        default="auto",
        help="TiM torch device: auto (CUDA if available, else MPS, else CPU), or cuda/cpu/mps/…. "
        "TiM always runs in-process (run_tim_batch_export); there is no remote TiM service.",
    )
    p.add_argument("--tim-merge-method", default="mean")
    p.add_argument("--tim-modalities", nargs="+", default=["LULC", "NDVI", "location"])
    p.add_argument("--tim-outputs", default="product", choices=("product", "full"))
    p.add_argument("--tim-tensor-sample-limit", type=int, default=0)
    p.add_argument("--s2-datetime", default="2025-11-01/2026-04-30")
    p.add_argument("--s2-half-km", type=float, default=14.0)
    p.add_argument("--s2-max-cloud", type=float, default=80.0)
    p.add_argument("--s2-max-items", type=int, default=30)
    p.add_argument("--stac-url", default="https://earth-search.aws.element84.com/v1")
    p.add_argument("--stac-collection", default="sentinel-2-l2a")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = parse_args(argv)

    if getattr(args, "fetch_dynamic_world", False) and getattr(args, "no_fetch_dynamic_world", False):
        raise SystemExit("Choose at most one of --fetch-dynamic-world and --no-fetch-dynamic-world.")
    if getattr(args, "no_fetch_dynamic_world", False):
        os.environ["NUTONIC_SKIP_EE_DYNAMIC_WORLD"] = "1"

    cf_raw: list[str] = []
    for chunk in getattr(args, "counterfactuals", []) or []:
        for part in str(chunk).split(","):
            p = part.strip()
            if p:
                cf_raw.append(p)
    if getattr(args, "contrastive_tim_flip", False) and "tim_payload_flip" not in cf_raw:
        cf_raw.append("tim_payload_flip")
    bad = sorted({c for c in cf_raw if c not in ALL_KINDS})
    if bad:
        raise SystemExit(f"Unknown --counterfactuals entries: {bad}; allowed: {list(ALL_KINDS)}")
    args.counterfactuals_effective = cf_raw

    oracle_yaml = Path(args.synthetic_oracle_yaml).resolve() if str(getattr(args, "synthetic_oracle_yaml", "")).strip() else None
    vg_yaml = Path(args.visual_gold_yaml).resolve() if str(getattr(args, "visual_gold_yaml", "")).strip() else None
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = default_patagonia_targets()
    if args.category:
        wanted = {c.lower() for c in args.category}
        targets = [t for t in targets if t.category.lower() in wanted]
    if args.target_id:
        wanted_id = set(args.target_id)
        targets = [t for t in targets if t.target_id in wanted_id]
    if args.max_targets > 0:
        targets = targets[: args.max_targets]
    if not targets:
        raise SystemExit("No targets selected.")
    if args.still_source == "mapbox" and not args.mapbox_token.strip():
        raise SystemExit("MAPBOX_ACCESS_TOKEN is required for --still-source mapbox (or pass --mapbox-token).")

    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    target_records: dict[str, dict[str, Any]] = {}
    still_prov: dict[str, Any] = {}
    with httpx.Client(timeout=httpx.Timeout(args.timeout), follow_redirects=True) as client:
        for t in targets:
            dt_for_target = _temporal_datetime_for_target_args(args, t, default=args.stac_still_datetime)
            img_path, _, prov = write_patagonia_eval_still(
                client=client,
                cache_dir=image_dir,
                target=t,
                pixel_size=args.mapbox_size,
                refresh=bool(args.refresh_images),
                still_source=args.still_source,
                mapbox_token=args.mapbox_token.strip(),
                stac_url=args.stac_still_url,
                stac_collection=args.stac_still_collection,
                stac_bbox_half_km=args.stac_still_bbox_half_km,
                stac_max_cloud=args.stac_still_max_cloud,
                stac_max_items=args.stac_still_max_items,
                stac_datetime=dt_for_target,
            )
            still_prov[t.target_id] = prov
            scenes_for_target = list(_temporal_scenes(t))
            if scenes_for_target:
                if isinstance(prov, dict):
                    prov["temporal_scenes"] = scenes_for_target
                    prov["temporal_datetime_effective"] = dt_for_target
                    prov["temporal_scenes_mode"] = (getattr(args, "temporal_scenes_mode", "latest") or "latest")
            target_records[t.target_id] = {
                "target": asdict(t),
                "image_path": str(img_path),
                "image_sha256": _sha256_bytes(img_path.read_bytes()),
                "still_provenance": prov,
            }

    pass_metric_resolved = _resolve_pass_metric(args.score_mode, args.pass_metric)
    if _needs_stac_gold_refresh(args):
        gold_by_id = _refresh_stills_with_stac_cog_gold(args, targets, target_records, out_dir)
    else:
        gold_by_id = {t.target_id: None for t in targets}

    tim_device_effective = _resolve_tim_device(args.tim_device)
    tim_by_id = _run_local_tim(args, targets, out_dir, tim_device_effective=tim_device_effective)

    gold_sidecars_by_id = _load_gold_sidecars(out_dir, targets)
    oracle_map = load_synthetic_oracle(oracle_yaml) if oracle_yaml is not None else load_synthetic_oracle()
    visual_gold = load_visual_gold(vg_yaml) if vg_yaml is not None else load_visual_gold()

    tim_health_by_id: dict[str, str] = {}
    health_rows: list[Any] = []
    analytics_full_by_id: dict[str, dict[str, Any] | None] = {}
    analytics_prompt_by_id: dict[str, dict[str, Any] | None] = {}
    resolved_analytics_source_by_id: dict[str, str] = {}
    profile_effective_by_id: dict[str, str] = {}

    for t in targets:
        tim_row = tim_by_id.get(t.target_id) or {}
        profile_hint = _target_profile(t)
        profile_tim = str(tim_row.get("analysis_profile") or profile_hint).strip()
        tim_compact_raw = compact_tim_for_production_prompt(tim_row)
        h = assess_tim_row(
            target_id=t.target_id,
            tim_compact=tim_compact_raw,
            requested_lat=float(t.lat),
            requested_lon=float(t.lon),
            profile=profile_tim,
        )
        tim_health_by_id[t.target_id] = str(h.status)
        health_rows.append(h)

        sidecar = gold_sidecars_by_id.get(t.target_id) or {}
        scl_fr = _scl_fractions_from_sidecar(sidecar)
        dw_fr = _dw_fractions_from_sidecar(sidecar)

        analytics_full, rsrc = select_analytics(
            str(getattr(args, "analytics_source", "procedural_or_tim")),
            target_id=t.target_id,
            profile=profile_tim,
            target_lat=float(t.lat),
            target_lon=float(t.lon),
            sentinel_fractions=scl_fr,
            dynamic_world_fractions=dw_fr,
            scene_meta=sidecar.get("stac_pair_meta") if isinstance(sidecar.get("stac_pair_meta"), dict) else None,
            tim_compact=tim_compact_raw,
            tim_health=str(h.status),
            oracle=oracle_map,
        )
        analytics_full_by_id[t.target_id] = analytics_full
        resolved_analytics_source_by_id[t.target_id] = rsrc
        analytics_prompt_by_id[t.target_id] = trim_for_prompt(analytics_full) if isinstance(analytics_full, dict) else None
        profile_effective_by_id[t.target_id] = str(
            ((analytics_full.get("profile_analytics") or {}) if isinstance(analytics_full, dict) else {}).get("profile")
            or profile_tim
        )

    provider_health = {"tim": aggregate_tim_health(health_rows)}

    prompts_path = out_dir / "prompts.jsonl"
    prompts_no_tim_path = out_dir / "prompts_no_tim.jsonl"
    predictions_path = out_dir / "predictions.jsonl"
    for pth in (prompts_path, prompts_no_tim_path, predictions_path):
        if pth.exists():
            pth.unlink()

    prompt_by_id: dict[str, str] = {}
    prompt_no_tim_by_id: dict[str, str] = {}
    for t in targets:
        profile_eff = profile_effective_by_id.get(t.target_id) or _target_profile(t)
        ap = analytics_prompt_by_id.get(t.target_id)
        if ap:
            prompt = build_production_tim_user_prompt(
                analysis_profile=profile_eff,
                tim_compact_json=_json_dumps(ap, pretty=False),
            )
        else:
            prompt = build_production_no_tim_user_prompt(analysis_profile=profile_eff)
        prompt_by_id[t.target_id] = prompt
        _append_jsonl(
            prompts_path,
            {
                "target_id": t.target_id,
                "image_path": target_records[t.target_id]["image_path"],
                "prompt": prompt,
                "tim": ap,
                "analytics_source_requested": getattr(args, "analytics_source", ""),
                "analytics_source_resolved": resolved_analytics_source_by_id.get(t.target_id),
                "tim_health": tim_health_by_id.get(t.target_id),
            },
        )
        prompt_no_tim = build_production_no_tim_user_prompt(analysis_profile=_target_profile(t))
        prompt_no_tim_by_id[t.target_id] = prompt_no_tim
        _append_jsonl(
            prompts_no_tim_path,
            {
                "target_id": t.target_id,
                "image_path": target_records[t.target_id]["image_path"],
                "prompt": prompt_no_tim,
                "tim": None,
            },
        )

    results: list[dict[str, Any]] = []
    endpoint_health: dict[str, Any] = {}
    http_from_env = (os.environ.get("NUTONIC_PATAGONIA_EVAL_ENABLE_HTTP") or "").strip() == "1"
    if args.endpoint:
        endpoints = resolve_patagonia_eval_endpoints(args.endpoint)
    elif http_from_env:
        endpoints = resolve_patagonia_eval_endpoints([])
    else:
        endpoints = []

    with httpx.Client(timeout=httpx.Timeout(args.timeout), follow_redirects=True) as client:
        if endpoints and not args.skip_health_check:
            endpoint_health = {name: _check_endpoint_health(client, url) for name, url in endpoints}
        for name, url in endpoints:
            for t in targets:
                rec: dict[str, Any] = {
                    "target_id": t.target_id,
                    "model_name": name,
                    "model_kind": "endpoint_legacy_no_tim_prompt",
                    "image_path": target_records[t.target_id]["image_path"],
                    "tim_injected": False,
                }
                try:
                    infer = _infer_caption(
                        client,
                        endpoint_url=url,
                        image_bytes=Path(target_records[t.target_id]["image_path"]).read_bytes(),
                        ranked_clue_safe=True,
                    )
                    rec["caption"] = infer.caption
                    rec["model_id"] = infer.model_id
                    gb = gold_by_id.get(t.target_id)
                    prof_nt = _target_profile(t)
                    vg_meta = gold_meta_for_target(t.target_id, gold=visual_gold)
                    no_loc = has_no_local_features(t.target_id, gold=visual_gold) or bool(vg_meta.get("no_local_features"))
                    rec["analysis_profile"] = prof_nt
                    rec["tim_compact"] = None
                    rec["analytics_in_prompt"] = None
                    rec["analytics_source_resolved"] = resolved_analytics_source_by_id.get(t.target_id)
                    rec["tim_health"] = tim_health_by_id.get(t.target_id)
                    rec["no_local_features"] = no_loc
                    rec.update(
                        _apply_full_scoring(
                            infer.caption,
                            t,
                            args,
                            gb,
                            pass_metric_resolved,
                            tim_injected=False,
                            analytics_in_prompt=None,
                            analysis_profile=prof_nt,
                            resolved_analytics_source=resolved_analytics_source_by_id.get(t.target_id),
                            tim_health=tim_health_by_id.get(t.target_id),
                            no_local_features=no_loc,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    rec["error"] = f"{type(exc).__name__}: {exc}"
                results.append(rec)
                _append_jsonl(predictions_path, rec)

    local_runs: list[tuple[str, str]] = []
    if not args.skip_local_vlm:
        local_runs = resolve_local_vlm_comparison_runs(args.local_vlm_model)

    if not endpoints and not local_runs:
        raise SystemExit(
            "No VLM eval to run: local runs were skipped (--skip-local-vlm) but no HTTP endpoints "
            "were configured (pass --endpoint or set NUTONIC_PATAGONIA_EVAL_ENABLE_HTTP=1)."
        )

    for model_name, hf_id in local_runs:
        model, processor = _load_local_vlm(hf_id, device=args.local_vlm_device, dtype=args.local_vlm_dtype)
        try:
            for idx, t in enumerate(targets):
                tim_row = tim_by_id.get(t.target_id) or {}
                tim_compact_raw = compact_tim_for_production_prompt(tim_row)
                profile_eff = profile_effective_by_id.get(t.target_id) or str(
                    tim_row.get("analysis_profile") or _target_profile(t)
                ).strip()
                analytics_full_base = analytics_full_by_id.get(t.target_id)
                analytics_prompt_base = analytics_prompt_by_id.get(t.target_id)
                rsrc = resolved_analytics_source_by_id.get(t.target_id) or ""
                th = tim_health_by_id.get(t.target_id)
                image_path = Path(target_records[t.target_id]["image_path"])
                gb = gold_by_id.get(t.target_id)
                vg_meta = gold_meta_for_target(t.target_id, gold=visual_gold)
                no_loc = has_no_local_features(t.target_id, gold=visual_gold) or bool(vg_meta.get("no_local_features"))

                if args.local_vlm_variants in ("tim", "both"):
                    rec_tim: dict[str, Any] = {
                        "target_id": t.target_id,
                        "model_name": model_name,
                        "model_id": hf_id,
                        "model_kind": "local_transformers_tim_prompt",
                        "image_path": str(image_path),
                        "tim_injected": bool(analytics_prompt_base),
                        "analysis_profile": profile_eff,
                        "tim_compact": tim_compact_raw,
                        "analytics_full": analytics_full_base,
                        "analytics_in_prompt": analytics_prompt_base,
                        "analytics_source_requested": getattr(args, "analytics_source", ""),
                        "analytics_source_resolved": rsrc,
                        "tim_health": th,
                        "no_local_features": no_loc,
                    }
                    try:
                        caption = _local_vlm_caption(
                            model,
                            processor,
                            image_path=image_path,
                            prompt=prompt_by_id[t.target_id],
                            max_new_tokens=args.max_new_tokens,
                            system_text=PRODUCTION_ANALYSIS_SYSTEM,
                        )
                        rec_tim["caption"] = caption
                        rec_tim.update(
                            _apply_full_scoring(
                                caption,
                                t,
                                args,
                                gb,
                                pass_metric_resolved,
                                tim_injected=bool(analytics_prompt_base),
                                analytics_in_prompt=analytics_prompt_base,
                                analysis_profile=profile_eff,
                                resolved_analytics_source=rsrc,
                                tim_health=th,
                                no_local_features=no_loc,
                            )
                        )

                        def _emit_cf(
                            kind: str,
                            *,
                            caption_cf: str,
                            prompt_cf: str,
                            analytics_for_score: dict[str, Any] | None,
                            extra: dict[str, Any],
                        ) -> None:
                            rec_cf: dict[str, Any] = {
                                "target_id": t.target_id,
                                "model_name": f"{model_name}_cf_{kind}",
                                "model_id": hf_id,
                                "model_kind": f"local_transformers_counterfactual::{kind}",
                                "image_path": str(image_path),
                                "tim_injected": bool(analytics_for_score),
                                "analysis_profile": profile_eff,
                                "counterfactual": kind,
                                "tim_compact": tim_compact_raw,
                                "analytics_full": analytics_full_base,
                                "analytics_in_prompt": analytics_for_score,
                                "analytics_source_resolved": rsrc,
                                "tim_health": th,
                                "no_local_features": no_loc,
                                **extra,
                            }
                            rec_cf["caption"] = caption_cf
                            rec_cf["counterfactual_prompt"] = prompt_cf
                            rec_cf.update(
                                _apply_full_scoring(
                                    caption_cf,
                                    t,
                                    args,
                                    gb,
                                    pass_metric_resolved,
                                    tim_injected=bool(analytics_for_score),
                                    analytics_in_prompt=analytics_for_score,
                                    analysis_profile=profile_eff,
                                    resolved_analytics_source=rsrc,
                                    tim_health=th,
                                    no_local_features=no_loc,
                                )
                            )
                            results.append(rec_cf)
                            _append_jsonl(predictions_path, rec_cf)

                        cf_list = list(getattr(args, "counterfactuals_effective", []) or [])
                        legacy_flip = bool(getattr(args, "contrastive_tim_flip", False)) and "tim_payload_flip" not in cf_list
                        if legacy_flip:
                            cf_list.append("tim_payload_flip")

                        if "tim_payload_flip" in cf_list and isinstance(analytics_full_base, dict):
                            pair_group = f"{t.target_id}::{model_name}"
                            rec_tim["contrastive_pair_group"] = pair_group
                            rec_tim["contrastive_arm"] = "baseline_analytics_prompt"
                            compact_flip, contrast_perturb_diag = perturb_tim_payload_flip(analytics_full_base)
                            prompt_flip = build_production_tim_user_prompt(
                                analysis_profile=profile_eff,
                                tim_compact_json=_json_dumps(trim_for_prompt(compact_flip), pretty=False),
                            )
                            caption_flip = _local_vlm_caption(
                                model,
                                processor,
                                image_path=image_path,
                                prompt=prompt_flip,
                                max_new_tokens=args.max_new_tokens,
                                system_text=PRODUCTION_ANALYSIS_SYSTEM,
                            )
                            resp, diag = contrast_caption_responsiveness(caption, caption_flip)
                            rec_tim["contrastive_responsiveness_vs_flip"] = resp
                            rec_tim["contrastive_responsiveness_diag"] = diag
                            _emit_cf(
                                "tim_payload_flip",
                                caption_cf=caption_flip,
                                prompt_cf=prompt_flip,
                                analytics_for_score=trim_for_prompt(compact_flip),
                                extra={
                                    "contrastive_pair_group": pair_group,
                                    "contrastive_perturbation_diag": contrast_perturb_diag,
                                    "contrastive_responsiveness_vs_flip": resp,
                                    "contrastive_responsiveness_diag": diag,
                                },
                            )

                        if "wrong_analytics" in cf_list and isinstance(analytics_full_base, dict):
                            wrong_full, wdiag = perturb_wrong_analytics(analytics_full_base, profile=profile_eff)
                            wrong_prompt = trim_for_prompt(wrong_full) if isinstance(wrong_full, dict) else None
                            if isinstance(wrong_prompt, dict):
                                p_wrong = build_production_tim_user_prompt(
                                    analysis_profile=profile_eff,
                                    tim_compact_json=_json_dumps(wrong_prompt, pretty=False),
                                )
                                cap_wrong = _local_vlm_caption(
                                    model,
                                    processor,
                                    image_path=image_path,
                                    prompt=p_wrong,
                                    max_new_tokens=args.max_new_tokens,
                                    system_text=PRODUCTION_ANALYSIS_SYSTEM,
                                )
                                true_pct = _lulc_class_pcts_percent(analytics_full_base)
                                wrong_pct = _lulc_class_pcts_percent(wrong_full if isinstance(wrong_full, dict) else {})
                                disagree, ddiag = caption_disagreement(cap_wrong, true_class_pcts=true_pct, wrong_class_pcts=wrong_pct)
                                _emit_cf(
                                    "wrong_analytics",
                                    caption_cf=cap_wrong,
                                    prompt_cf=p_wrong,
                                    analytics_for_score=wrong_prompt,
                                    extra={
                                        "counterfactual_wrong_analytics_diag": wdiag,
                                        "counterfactual_disagreement_score": disagree,
                                        "counterfactual_disagreement_diag": ddiag,
                                    },
                                )

                        if "half_redact" in cf_list and isinstance(analytics_full_base, dict):
                            red_full, rdiag = perturb_half_redact(analytics_full_base)
                            red_prompt_obj = trim_for_prompt(red_full) if isinstance(red_full, dict) else None
                            if isinstance(red_prompt_obj, dict):
                                p_red = build_production_tim_user_prompt(
                                    analysis_profile=profile_eff,
                                    tim_compact_json=_json_dumps(red_prompt_obj, pretty=False),
                                )
                                cap_red = _local_vlm_caption(
                                    model,
                                    processor,
                                    image_path=image_path,
                                    prompt=p_red,
                                    max_new_tokens=args.max_new_tokens,
                                    system_text=PRODUCTION_ANALYSIS_SYSTEM,
                                )
                                _emit_cf(
                                    "half_redact",
                                    caption_cf=cap_red,
                                    prompt_cf=p_red,
                                    analytics_for_score=red_prompt_obj,
                                    extra={"counterfactual_redact_diag": rdiag},
                                )

                        if "image_swap" in cf_list:
                            partner = targets[(idx + 1) % len(targets)]
                            p_img = Path(target_records[partner.target_id]["image_path"])
                            if p_img.exists():
                                cap_sw = _local_vlm_caption(
                                    model,
                                    processor,
                                    image_path=p_img,
                                    prompt=prompt_by_id[t.target_id],
                                    max_new_tokens=args.max_new_tokens,
                                    system_text=PRODUCTION_ANALYSIS_SYSTEM,
                                )
                                _emit_cf(
                                    "image_swap",
                                    caption_cf=cap_sw,
                                    prompt_cf=prompt_by_id[t.target_id],
                                    analytics_for_score=analytics_prompt_base,
                                    extra={
                                        "counterfactual_image_swap_from_target_id": partner.target_id,
                                        "counterfactual_image_path": str(p_img),
                                    },
                                )
                    except Exception as exc:  # noqa: BLE001
                        rec_tim["error"] = f"{type(exc).__name__}: {exc}"
                    results.append(rec_tim)
                    _append_jsonl(predictions_path, rec_tim)

                if args.local_vlm_variants in ("no_tim", "both"):
                    prof_nt = _target_profile(t)
                    rec_nt = {
                        "target_id": t.target_id,
                        "model_name": f"{model_name}_no_tim",
                        "model_id": hf_id,
                        "model_kind": "local_transformers_no_tim_prompt",
                        "image_path": str(image_path),
                        "tim_injected": False,
                        "analysis_profile": prof_nt,
                        "tim_compact": None,
                        "analytics_in_prompt": None,
                        "analytics_source_resolved": "none",
                        "tim_health": th,
                        "no_local_features": no_loc,
                    }
                    try:
                        caption = _local_vlm_caption(
                            model,
                            processor,
                            image_path=image_path,
                            prompt=prompt_no_tim_by_id[t.target_id],
                            max_new_tokens=args.max_new_tokens,
                            system_text=PRODUCTION_ANALYSIS_SYSTEM,
                        )
                        rec_nt["caption"] = caption
                        rec_nt.update(
                            _apply_full_scoring(
                                caption,
                                t,
                                args,
                                gb,
                                pass_metric_resolved,
                                tim_injected=False,
                                analytics_in_prompt=None,
                                analysis_profile=prof_nt,
                                resolved_analytics_source="none",
                                tim_health=th,
                                no_local_features=no_loc,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        rec_nt["error"] = f"{type(exc).__name__}: {exc}"
                    results.append(rec_nt)
                    _append_jsonl(predictions_path, rec_nt)
        finally:
            del model
            del processor
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    judge_pack_path: str | None = None
    if args.write_judge_pack:
        jp = out_dir / "judge_pack.jsonl"
        if jp.exists():
            jp.unlink()
        for r in results:
            _append_jsonl(jp, _judge_pack_row(r))
        judge_pack_path = str(jp.resolve())

    gold_contract = _gold_contract_tags(args)

    summary_build_errors: list[str] = []
    try:
        summary_by_model = _summarize(results)
    except Exception as exc:  # noqa: BLE001
        summary_build_errors.append(f"summary_by_model:{type(exc).__name__}:{exc}")
        summary_by_model = {}
    try:
        summary_tim_vs_no_tim = _summarize_variant_pairs(summary_by_model)
    except Exception as exc:  # noqa: BLE001
        summary_build_errors.append(f"summary_tim_vs_no_tim:{type(exc).__name__}:{exc}")
        summary_tim_vs_no_tim = {}
    try:
        summary_by_model_by_category = _summarize_by_category(results, target_records=target_records)
    except Exception as exc:  # noqa: BLE001
        summary_build_errors.append(f"summary_by_model_by_category:{type(exc).__name__}:{exc}")
        summary_by_model_by_category = {}
    try:
        summary_by_model_by_profile = _summarize_by_profile(results)
    except Exception as exc:  # noqa: BLE001
        summary_build_errors.append(f"summary_by_model_by_profile:{type(exc).__name__}:{exc}")
        summary_by_model_by_profile = {}
    payload = {
        "meta": {
            "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
            "out_dir": str(out_dir),
            "score_threshold": args.score_threshold,
            "score_mode": args.score_mode,
            "pass_metric": args.pass_metric,
            "pass_metric_resolved": pass_metric_resolved,
            "threshold_sweep": _parse_threshold_sweep(args.threshold_sweep),
            "stac_gold_refresh": bool(_needs_stac_gold_refresh(args)),
            "fetch_dynamic_world": bool(getattr(args, "fetch_dynamic_world", False)),
            "temporal_scenes_mode": getattr(args, "temporal_scenes_mode", "latest"),
            "temporal_scenes_by_target": {
                t.target_id: list(_temporal_scenes(t)) for t in targets if _temporal_scenes(t)
            },
            "composite_weight_preset": getattr(args, "composite_weight_preset", "auto"),
            "score_weight_presets": _score_weight_presets_for_meta(),
            "evaluation_hypotheses": {
                "optical_scl_state": "Grounding IoU vs single-acquisition SCL-derived boxes (scene state, not TiM change truth).",
                "optical_scl_delta": "When --gold-mode delta, grounding targets bi-temporal SCL disagreement regions (falls back to state).",
                "output_contract": "Hard gate on the SFT production_analysis JSON tail (fenced JSON + boxes schema + anti-leak).",
                "faithfulness": "Deterministic caption ↔ injected analytics agreement (works for procedural / oracle / TiM JSON).",
                "tim_provider_health": "TerraMind TiM health is reported separately; eval does not treat TiM correctness as the target metric.",
                "counterfactual_probes": "Optional passes perturb analytics or swap imagery to measure model sensitivity (not provider quality).",
                "lexical_vocabulary": "Keyword groups probe visible vocabulary per AOI (EvalTarget.expected_any).",
                "dynamic_world_optional": "With --fetch-dynamic-world, EE Dynamic World label chips align to the STAC still footprint; "
                "gold/*.json stores dynamic_world_fractions for --analytics-source dynamic_world / procedural_or_dw.",
            },
            "gold_mode": getattr(args, "gold_mode", "state"),
            "gold_min_temporal_separation_days": float(getattr(args, "gold_min_temporal_separation_days", 21.0)),
            "contrastive_tim_flip": bool(getattr(args, "contrastive_tim_flip", False)),
            "counterfactuals_effective": list(getattr(args, "counterfactuals_effective", []) or []),
            "analytics_source": getattr(args, "analytics_source", ""),
            "gold_contract": gold_contract,
            "judge_pack_path": judge_pack_path,
            "summary_build_errors": summary_build_errors,
            "score_weights": (
                {
                    "lexical": float(args.score_weight[0]),
                    "grounding": float(args.score_weight[1]),
                    "contract": float(args.score_weight[2]),
                    "faithfulness": 0.0,
                    "structured": float(args.score_weight[2]),
                    "tim_alignment": 0.0,
                }
                if getattr(args, "score_weight", None) is not None
                else {
                    "lexical": float(SCORE_WEIGHT_PRESETS["default"].lexical),
                    "grounding": float(SCORE_WEIGHT_PRESETS["default"].grounding),
                    "contract": float(SCORE_WEIGHT_PRESETS["default"].contract),
                    "faithfulness": float(SCORE_WEIGHT_PRESETS["default"].faithfulness),
                    "structured": float(SCORE_WEIGHT_PRESETS["default"].contract),
                    "tim_alignment": float(SCORE_WEIGHT_PRESETS["default"].faithfulness),
                }
            ),
            "grounding_label_mode": args.grounding_label_mode,
            "grounding_policy": {
                "max_pred_boxes": args.max_pred_boxes,
                "box_budget_penalty_per_extra": args.box_budget_penalty_per_extra,
                "oversize_penalty_strength": args.oversize_penalty_strength,
            },
            "still_source": args.still_source,
            "mapbox_size": args.mapbox_size,
            "still_provenance_by_target": still_prov,
            "target_count": len(targets),
            "tim_model_id": args.tim_model_id,
            "tim_device_requested": args.tim_device,
            "tim_device_effective": tim_device_effective,
            "tim_execution": "local_in_process",
            "tim_run_entry": "nutonic_terramind_tim_local.run.run_tim_batch_export",
            "tim_outputs": args.tim_outputs,
            "endpoint_health": endpoint_health,
            "http_endpoints": dict(endpoints),
            "http_enabled_via": ("cli" if args.endpoint else ("env" if http_from_env else None)),
            "local_vlm_runs": [{"model_name": n, "hf_model_id": mid} for n, mid in local_runs],
            "local_vlm_variants": args.local_vlm_variants,
            "comparison_expectations": {
                "expected_hf_models": patagonia_comparison_hf_model_ids(),
                "notes": (
                    "TiM runs in-process (run_tim_batch_export); VLM runs locally by default (Transformers) "
                    "with TiM JSON in the prompt. Local VLM uses SFT-aligned production_analysis system + user "
                    "layout (see patagonia_eval_sft_prompts). Scoring: multimodal (lexical + SCL IoU grounding + "
                    "output_contract + faithfulness + composite). Analytics JSON may be procedural (SFT-aligned) or "
                    "TiM-generated; TiM provider health is reported separately. Presets: --composite-weight-preset auto. "
                    "Optional counterfactual probes: --counterfactuals. Optional HTTP /v1/infer: --endpoint or "
                    "NUTONIC_PATAGONIA_EVAL_ENABLE_HTTP=1."
                ),
            },
            "vlm_prompt_style": "sft_production_analysis",
        },
        "provider_health": provider_health,
        "targets": target_records,
        "summary_by_model": summary_by_model,
        "summary_tim_vs_no_tim": summary_tim_vs_no_tim,
        "summary_by_model_by_category": summary_by_model_by_category,
        "summary_by_model_by_profile": summary_by_model_by_profile,
        "threshold_sweep": {},
        "results": results,
    }
    sweeps = payload["meta"].get("threshold_sweep") or []
    if isinstance(sweeps, list) and sweeps:
        payload["threshold_sweep"] = {str(t): _summarize_for_threshold(results, threshold=float(t)) for t in sweeps}
    _write_json(out_dir / "report.json", payload)
    write_patagonia_per_model_artifacts(
        out_dir,
        results=payload["results"],
        summary_by_model=payload["summary_by_model"],
        name_field="model_name",
    )
    (out_dir / "eval_manifest.json").write_text(
        json.dumps(
            {
                "generated_at_utc": payload["meta"]["generated_at_utc"],
                "expected_hf_models": patagonia_comparison_hf_model_ids(),
                "tim_device_effective": tim_device_effective,
                "tim_execution": "local_in_process",
                "local_vlm_runs": payload["meta"]["local_vlm_runs"],
                "http_endpoints": dict(endpoints),
                "out_dir": str(out_dir),
                "vlm_prompt_style": payload["meta"]["vlm_prompt_style"],
                "score_mode": payload["meta"].get("score_mode"),
                "pass_metric_resolved": payload["meta"].get("pass_metric_resolved"),
                "score_threshold": payload["meta"].get("score_threshold"),
                "composite_weight_preset": payload["meta"].get("composite_weight_preset"),
                "evaluation_hypotheses": payload["meta"].get("evaluation_hypotheses"),
                "gold_contract": payload["meta"].get("gold_contract"),
                "gold_mode": payload["meta"].get("gold_mode"),
                "contrastive_tim_flip": payload["meta"].get("contrastive_tim_flip"),
                "judge_pack_path": payload["meta"].get("judge_pack_path"),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_markdown(out_dir, payload)
    print(f"Patagonia TiM E2E evaluation complete: {out_dir}")
    for name, s in (payload.get("summary_by_model") or {}).items():
        extra = ""
        if "mean_composite_score" in s:
            extra = f" mean_composite={s['mean_composite_score']:.3f}"
        print(
            f"- {name}: pass_rate={s['pass_rate']:.3f} mean_primary={s['mean_score']:.3f}{extra} errors={s['errors']}"
        )

    hf_repo = (args.hf_dataset_repo or "").strip() or (os.environ.get("NUTONIC_PATAGONIA_EVAL_HF_DATASET") or "").strip()
    if hf_repo and not args.skip_hf_upload:
        if upload_patagonia_eval_bundle is None:
            print("Install huggingface_hub to upload: pip install huggingface_hub", file=sys.stderr)
            return 1
        tok = (args.hf_upload_token or "").strip() or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        path_sel = (args.hf_upload_path_in_repo or "").strip() or None
        try:
            urls = upload_patagonia_eval_bundle(
                folder=out_dir,
                repo_id=hf_repo,
                path_in_repo=path_sel,
                token=tok,
                private=bool(args.hf_upload_private),
                upload_per_model_subfolders=not bool(args.hf_upload_no_by_model),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"HF dataset upload failed: {exc}", file=sys.stderr)
            return 1
        for u in urls:
            print(f"uploaded: {u}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
