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
- **Multi-mode scoring** (``--score-mode``): legacy **lexical** checks, **grounding** vs Sentinel-2 SCL
  reference boxes (COG-aligned still refresh), **structured** checklist for production-style outputs,
  and **composite** (default) combining them with guardrails

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
from patagonia_eval_scoring import ScoreWeights, score_patagonia_multimodal  # noqa: E402
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
    return {"lexical": "lexical", "grounding": "grounding", "structured": "structured"}.get(sm, "composite")


def _needs_stac_gold_refresh(args: argparse.Namespace) -> bool:
    if getattr(args, "no_stac_gold", False):
        return False
    if args.still_source != "stac":
        return False
    sm = args.score_mode.strip().lower()
    return sm in ("grounding", "composite", "all")


def _build_score_weights(args: argparse.Namespace) -> ScoreWeights:
    w = getattr(args, "score_weight", None)
    if isinstance(w, (list, tuple)) and len(w) == 3:
        return ScoreWeights(lexical=float(w[0]), grounding=float(w[1]), structured=float(w[2]))
    return ScoreWeights()


def _apply_full_scoring(
    caption: str,
    target: EvalTarget,
    args: argparse.Namespace,
    gold_boxes: list[dict[str, Any]] | None,
    pass_metric_resolved: str,
) -> dict[str, Any]:
    mode = args.score_mode.strip().lower()
    if mode == "all":
        mode = "composite"
    scored = score_patagonia_multimodal(
        caption,
        target,
        threshold=args.score_threshold,
        gold_boxes=gold_boxes,
        weights=_build_score_weights(args),
        score_mode=mode,
        pass_metric=pass_metric_resolved,
    )
    # Store the scalar that drove pass/fail so we can sweep thresholds without re-running inference.
    pass_value: float | None = None
    if pass_metric_resolved == "lexical":
        pass_value = float(scored["lexical"]["score"])
    elif pass_metric_resolved == "grounding":
        pass_value = None if scored["grounding"]["score"] is None else float(scored["grounding"]["score"])
    elif pass_metric_resolved == "structured":
        pass_value = float(scored["structured"]["score"])
    else:
        pass_value = float(scored["composite"])
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
        "structured_score": scored["structured"]["score"],
        "composite_score": scored["composite"],
        "scoring": scored,
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
    from patagonia_eval_gold import gold_boxes_from_scl
    from stac_reference_still import fetch_sentinel_cog_rgb_scl_matched

    gold_dir = out_dir / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    gold_by_id: dict[str, Any] = {}
    st_raw = (args.stac_still_url or "").strip() or None
    coll = (args.stac_still_collection or "").strip() or None
    dt_raw = (args.stac_still_datetime or "").strip() or None

    for t in targets:
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
        sidecar = {"target_id": t.target_id, "stac_pair_meta": meta}
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
        else:
            gold_by_id[t.target_id] = None
            sidecar["gold_boxes"] = None
            sidecar["reason"] = meta.get("reason", "cog_pair_failed")
        _write_json(gold_dir / f"{t.target_id}.json", sidecar)
    return gold_by_id


def _target_profile(target: EvalTarget) -> str:
    cat = target.category.lower()
    if "glacier" in cat:
        return "brief_only"
    if "marine" in cat or "water" in cat:
        return "oceanscout_ship_detection"
    if "forest" in cat or "coastal" in cat or "urban" in cat:
        return "land_use_change"
    return "brief_only"


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
        "batch": [
            {
                "map_id": t.target_id,
                "location_id": t.target_id,
                "analysis_profile": _target_profile(t),
                "rgb_mode": "s2_rgb",
                "s2_mode": "stac",
                "lat": t.lat,
                "lon": t.lon,
                "datetime": args.s2_datetime,
            }
            for t in targets
        ],
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
                "structured_sum": 0.0,
                "composite_sum": 0.0,
                "lexical_n": 0,
                "grounding_n": 0,
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
        if cur.get("structured_n", 0) > 0:
            cur["mean_structured_score"] = round(cur["structured_sum"] / cur["structured_n"], 4)
        if cur.get("composite_n", 0) > 0:
            cur["mean_composite_score"] = round(cur["composite_sum"] / cur["composite_n"], 4)
        for k in (
            "lexical_sum",
            "lexical_n",
            "grounding_sum",
            "grounding_n",
            "structured_sum",
            "structured_n",
            "composite_sum",
            "composite_n",
        ):
            cur.pop(k, None)
    return out


def _summary_metric_cell(summary_row: dict[str, Any], key: str) -> str:
    v = summary_row.get(key)
    return f"{float(v):.3f}" if v is not None else "—"


def _write_markdown(out_dir: Path, payload: dict[str, Any]) -> None:
    meta = payload["meta"]
    lines = [
        "# Patagonia TiM E2E VLM Evaluation",
        "",
        f"Generated: `{meta['generated_at_utc']}`",
        f"Scoring: `{meta.get('score_mode', '')}` · pass metric: `{meta.get('pass_metric_resolved', '')}` · "
        f"threshold `{meta.get('score_threshold', '')}`",
        "",
        "## Summary",
        "",
        "| Model | Targets | Errors | Pass Rate | Mean (primary) | Mean Lex | Mean Grd | Mean Str | Mean Comp |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, s in payload["summary_by_model"].items():
        lines.append(
            f"| {name} | {s['n']} | {s['errors']} | {s['pass_rate']:.3f} | {s['mean_score']:.3f} | "
            f"{_summary_metric_cell(s, 'mean_lexical_score')} | {_summary_metric_cell(s, 'mean_grounding_score')} | "
            f"{_summary_metric_cell(s, 'mean_structured_score')} | {_summary_metric_cell(s, 'mean_composite_score')} |"
        )
    lines.extend(["", "## Artifacts", ""])
    lines.append("- `report.json`: full machine-readable report")
    lines.append("- `predictions.jsonl`: one row per model/target prediction")
    lines.append("- `prompts.jsonl`: exact user prompt records with injected TiM JSON")
    lines.append("- `tim/tim_export.jsonl`: local TiM outputs")
    lines.append("- `images/`: cached reference stills (STAC or Mapbox)")
    lines.append("- `gold/`: Sentinel-2 SCL-derived reference boxes (when STAC COG pair succeeded)")

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
    lines.extend(["", "## Per-Target Results", ""])
    for r in payload["results"]:
        lines.append(f"### {r['target_id']} · {r['model_name']}")
        if r.get("error"):
            lines.append(f"- Error: `{r['error']}`")
        else:
            lines.append(
                f"- Primary score: `{r['score']}` · passed: `{r['passed']}` · "
                f"lex `{r.get('lexical_score', '')}` · grd `{r.get('grounding_score', '')}` · "
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
        choices=("lexical", "grounding", "structured", "composite", "all"),
        default="composite",
        help="primary reported score: composite (default) mixes lexical+SCL IoU+structured; 'all' same as composite with full breakdown.",
    )
    p.add_argument(
        "--pass-metric",
        default="auto",
        help="What drives pass/fail: auto (follows score-mode), lexical, grounding, structured, or composite.",
    )
    p.add_argument(
        "--score-weight",
        nargs=3,
        type=float,
        metavar=("LEX", "GRD", "STR"),
        default=None,
        help="Composite weights when SCL gold exists (default 0.22 0.48 0.30).",
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
        help="Do not replace stills with COG RGB+SCL pair or write gold/ (lexical+structured only for composite).",
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
        "--local-vlm-model",
        action="append",
        default=[],
        help=(
            "HF model id for TiM-in-prompt eval (repeatable). If omitted, runs finetune vs base "
            "from patagonia_comparison_hf_model_ids() (NuTonic/lspace vs LiquidAI/LFM2.5-VL-450M)."
        ),
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
                stac_datetime=args.stac_still_datetime,
            )
            still_prov[t.target_id] = prov
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

    prompts_path = out_dir / "prompts.jsonl"
    prompts_no_tim_path = out_dir / "prompts_no_tim.jsonl"
    predictions_path = out_dir / "predictions.jsonl"
    for pth in (prompts_path, prompts_no_tim_path, predictions_path):
        if pth.exists():
            pth.unlink()

    prompt_by_id: dict[str, str] = {}
    prompt_no_tim_by_id: dict[str, str] = {}
    for t in targets:
        tim_row = tim_by_id.get(t.target_id) or {}
        profile = str(tim_row.get("analysis_profile") or _target_profile(t)).strip()
        prompt = build_production_tim_user_prompt(
            analysis_profile=profile,
            tim_compact_json=compact_tim_for_production_prompt(tim_row),
        )
        prompt_by_id[t.target_id] = prompt
        _append_jsonl(
            prompts_path,
            {
                "target_id": t.target_id,
                "image_path": target_records[t.target_id]["image_path"],
                "prompt": prompt,
                "tim": compact_tim_for_production_prompt(tim_row),
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
                    rec.update(_apply_full_scoring(infer.caption, t, args, gb, pass_metric_resolved))
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
            for t in targets:
                image_path = Path(target_records[t.target_id]["image_path"])
                gb = gold_by_id.get(t.target_id)

                if args.local_vlm_variants in ("tim", "both"):
                    rec_tim = {
                        "target_id": t.target_id,
                        "model_name": model_name,
                        "model_id": hf_id,
                        "model_kind": "local_transformers_tim_prompt",
                        "image_path": str(image_path),
                        "tim_injected": True,
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
                        rec_tim.update(_apply_full_scoring(caption, t, args, gb, pass_metric_resolved))
                    except Exception as exc:  # noqa: BLE001
                        rec_tim["error"] = f"{type(exc).__name__}: {exc}"
                    results.append(rec_tim)
                    _append_jsonl(predictions_path, rec_tim)

                if args.local_vlm_variants in ("no_tim", "both"):
                    rec_nt = {
                        "target_id": t.target_id,
                        "model_name": f"{model_name}_no_tim",
                        "model_id": hf_id,
                        "model_kind": "local_transformers_no_tim_prompt",
                        "image_path": str(image_path),
                        "tim_injected": False,
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
                        rec_nt.update(_apply_full_scoring(caption, t, args, gb, pass_metric_resolved))
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
            "score_weights": (
                {"lexical": float(args.score_weight[0]), "grounding": float(args.score_weight[1]), "structured": float(args.score_weight[2])}
                if getattr(args, "score_weight", None) is not None
                else {"lexical": 0.22, "grounding": 0.48, "structured": 0.30}
            ),
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
                    "structured checklist + composite). Override ids with NUTONIC_PATAGONIA_EVAL_*_MODEL_ID. "
                    "Optional HTTP /v1/infer: --endpoint or NUTONIC_PATAGONIA_EVAL_ENABLE_HTTP=1."
                ),
            },
            "vlm_prompt_style": "sft_production_analysis",
        },
        "targets": target_records,
        "summary_by_model": _summarize(results),
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
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_markdown(out_dir, payload)
    print(f"Patagonia TiM E2E evaluation complete: {out_dir}")
    for name, s in payload["summary_by_model"].items():
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
