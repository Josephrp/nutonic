#!/usr/bin/env python3
"""
Standalone Patagonia evaluation with local TerraMind TiM artifacts.

Outputs a publishable run directory containing:
- fetched Mapbox stills
- local TiM export JSONL generated on-device via torch/TerraTorch
- per-target prompt records with the TiM JSON injected in the user turn
- VLM predictions for endpoint and/or local-transformers models
- aggregate JSON + Markdown summary

The local TiM path reuses `inference/terramind_tim_local` directly; no TiM
remote service is required.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
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

from evaluate_vlm_patagonia import (  # noqa: E402
    EvalTarget,
    _check_endpoint_health,
    _infer_caption,
    _mapbox_static_png,
    _parse_endpoints,
    _score_caption,
    _sha256_bytes,
    _sanitize_filename,
    default_patagonia_targets,
)


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


def _target_profile(target: EvalTarget) -> str:
    cat = target.category.lower()
    if "glacier" in cat:
        return "brief_only"
    if "marine" in cat or "water" in cat:
        return "oceanscout_ship_detection"
    if "forest" in cat or "coastal" in cat or "urban" in cat:
        return "land_use_change"
    return "brief_only"


def _tim_batch_config(args: argparse.Namespace, targets: list[EvalTarget]) -> dict[str, Any]:
    return {
        "content_version": "nutonic.patagonia_tim_e2e.v1",
        "paths": {"repo_root": str(REPO_ROOT)},
        "model_id": args.tim_model_id,
        "pretrained": True,
        "merge_method": args.tim_merge_method,
        "modalities": ["RGB", "S2L2A"],
        "tim_modalities": args.tim_modalities,
        "device": args.tim_device,
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


def _run_local_tim(args: argparse.Namespace, targets: list[EvalTarget], out_dir: Path) -> dict[str, dict[str, Any]]:
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

    cfg = _tim_batch_config(args, targets)
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


def _compact_tim_for_prompt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tim_modality_outputs": row.get("tim_modality_outputs") or {},
        "profile_analytics": row.get("profile_analytics") or {},
    }


def _prompt_text(tim_row: dict[str, Any]) -> str:
    compact = _compact_tim_for_prompt(tim_row)
    return (
        "Review the provided satellite imagery and the provided analytics JSON. "
        "Use the JSON as auxiliary context, and put any comparisons or change interpretation in your response.\n\n"
        f"Provided analytics JSON:\n{_json_dumps(compact)}\n\n"
        "Describe the visible land-cover pattern and summarize any relevant change or risk indicated by the provided analytics."
    )


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
) -> str:
    import torch

    image = Image.open(image_path).convert("RGB")
    conversation = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
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


def _score_result(caption: str, target: EvalTarget, threshold: float) -> dict[str, Any]:
    score, gh, gt, e_hits, f_hits, c_hits, flags, wc, passed = _score_caption(caption, target, threshold)
    return {
        "score": round(score, 4),
        "passed": passed,
        "expected_groups_hit": gh,
        "expected_groups_total": gt,
        "expected_hits": e_hits,
        "forbidden_hits": f_hits,
        "claim_risk_hits": c_hits,
        "quality_flags": flags,
        "word_count": wc,
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in results:
        name = str(r["model_name"])
        cur = out.setdefault(name, {"n": 0, "errors": 0, "passed": 0, "score_sum": 0.0})
        cur["n"] += 1
        if r.get("error"):
            cur["errors"] += 1
            continue
        cur["passed"] += int(bool(r.get("passed")))
        cur["score_sum"] += float(r.get("score") or 0.0)
    for cur in out.values():
        scored = max(1, int(cur["n"]) - int(cur["errors"]))
        cur["mean_score"] = round(float(cur["score_sum"]) / scored, 4)
        cur["pass_rate"] = round(float(cur["passed"]) / scored, 4)
        cur.pop("score_sum", None)
    return out


def _write_markdown(out_dir: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Patagonia TiM E2E VLM Evaluation",
        "",
        f"Generated: `{payload['meta']['generated_at_utc']}`",
        "",
        "## Summary",
        "",
        "| Model | Targets | Errors | Pass Rate | Mean Score |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, s in payload["summary_by_model"].items():
        lines.append(f"| {name} | {s['n']} | {s['errors']} | {s['pass_rate']:.3f} | {s['mean_score']:.3f} |")
    lines.extend(["", "## Artifacts", ""])
    lines.append("- `report.json`: full machine-readable report")
    lines.append("- `predictions.jsonl`: one row per model/target prediction")
    lines.append("- `prompts.jsonl`: exact user prompt records with injected TiM JSON")
    lines.append("- `tim/tim_export.jsonl`: local TiM outputs")
    lines.append("- `images/`: cached Mapbox stills")
    lines.extend(["", "## Per-Target Results", ""])
    for r in payload["results"]:
        lines.append(f"### {r['target_id']} · {r['model_name']}")
        if r.get("error"):
            lines.append(f"- Error: `{r['error']}`")
        else:
            lines.append(f"- Score: `{r['score']}` · passed: `{r['passed']}`")
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
    p.add_argument("--mapbox-token", default=os.environ.get("MAPBOX_ACCESS_TOKEN", ""))
    p.add_argument("--mapbox-size", type=int, default=640)
    p.add_argument("--refresh-images", action="store_true")
    p.add_argument("--category", action="append", default=[])
    p.add_argument("--target-id", action="append", default=[])
    p.add_argument("--max-targets", type=int, default=0)
    p.add_argument("--score-threshold", type=float, default=0.55)
    p.add_argument("--endpoint", action="append", default=[], help="Optional legacy /v1/infer endpoint name=url.")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--skip-health-check", action="store_true")
    p.add_argument("--local-vlm-model", action="append", default=[], help="Local HF model id for true TiM-in-prompt eval.")
    p.add_argument("--local-vlm-device", default="auto")
    p.add_argument("--local-vlm-dtype", default="bfloat16")
    p.add_argument("--max-new-tokens", type=int, default=220)
    p.add_argument("--tim-model-id", default="terramind_v1_tiny_tim")
    p.add_argument("--tim-device", default="cpu")
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
    if not args.mapbox_token:
        raise SystemExit("MAPBOX_ACCESS_TOKEN is required (or pass --mapbox-token).")

    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    target_records: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=httpx.Timeout(args.timeout), follow_redirects=True) as client:
        for t in targets:
            img_name = _sanitize_filename(f"{t.target_id}_z{t.zoom}_s{args.mapbox_size}_{t.lat:.4f}_{t.lon:.4f}.png")
            img_path = image_dir / img_name
            if not img_path.exists() or args.refresh_images:
                img_path.write_bytes(
                    _mapbox_static_png(
                        client,
                        token=args.mapbox_token,
                        lat=t.lat,
                        lon=t.lon,
                        zoom=t.zoom,
                        size=args.mapbox_size,
                    )
                )
            target_records[t.target_id] = {
                "target": asdict(t),
                "image_path": str(img_path),
                "image_sha256": _sha256_bytes(img_path.read_bytes()),
            }

    tim_by_id = _run_local_tim(args, targets, out_dir)

    prompts_path = out_dir / "prompts.jsonl"
    predictions_path = out_dir / "predictions.jsonl"
    for pth in (prompts_path, predictions_path):
        if pth.exists():
            pth.unlink()

    prompt_by_id: dict[str, str] = {}
    for t in targets:
        tim_row = tim_by_id.get(t.target_id) or {}
        prompt = _prompt_text(tim_row)
        prompt_by_id[t.target_id] = prompt
        _append_jsonl(
            prompts_path,
            {
                "target_id": t.target_id,
                "image_path": target_records[t.target_id]["image_path"],
                "prompt": prompt,
                "tim": _compact_tim_for_prompt(tim_row),
            },
        )

    results: list[dict[str, Any]] = []
    endpoint_health: dict[str, Any] = {}
    endpoints = _parse_endpoints(args.endpoint, "")
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
                    rec.update(_score_result(infer.caption, t, args.score_threshold))
                except Exception as exc:  # noqa: BLE001
                    rec["error"] = f"{type(exc).__name__}: {exc}"
                results.append(rec)
                _append_jsonl(predictions_path, rec)

    for model_id in args.local_vlm_model:
        model, processor = _load_local_vlm(model_id, device=args.local_vlm_device, dtype=args.local_vlm_dtype)
        safe_name = _sanitize_filename(model_id)
        for t in targets:
            rec = {
                "target_id": t.target_id,
                "model_name": safe_name,
                "model_id": model_id,
                "model_kind": "local_transformers_tim_prompt",
                "image_path": target_records[t.target_id]["image_path"],
                "tim_injected": True,
            }
            try:
                caption = _local_vlm_caption(
                    model,
                    processor,
                    image_path=Path(target_records[t.target_id]["image_path"]),
                    prompt=prompt_by_id[t.target_id],
                    max_new_tokens=args.max_new_tokens,
                )
                rec["caption"] = caption
                rec.update(_score_result(caption, t, args.score_threshold))
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"{type(exc).__name__}: {exc}"
            results.append(rec)
            _append_jsonl(predictions_path, rec)

    payload = {
        "meta": {
            "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
            "out_dir": str(out_dir),
            "score_threshold": args.score_threshold,
            "mapbox_size": args.mapbox_size,
            "target_count": len(targets),
            "tim_model_id": args.tim_model_id,
            "tim_device": args.tim_device,
            "tim_outputs": args.tim_outputs,
            "endpoint_health": endpoint_health,
        },
        "targets": target_records,
        "summary_by_model": _summarize(results),
        "results": results,
    }
    _write_json(out_dir / "report.json", payload)
    _write_markdown(out_dir, payload)
    print(f"Patagonia TiM E2E evaluation complete: {out_dir}")
    for name, s in payload["summary_by_model"].items():
        print(f"- {name}: pass_rate={s['pass_rate']:.3f} mean_score={s['mean_score']:.3f} errors={s['errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
