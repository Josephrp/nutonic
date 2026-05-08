#!/usr/bin/env python3
"""
Evaluate VLM grounding on held-out NU:TONIC SFT JSONL data (the *training-aligned* way).

This is designed to demonstrate whether a finetune beats a base model on the same prompt schema it
was trained on (leap-finetune VLM SFT `messages[]` with images + user text, and assistant text that
contains strict JSON bboxes).

Inputs:
- A local dataset folder containing:
  - `data/<split>.jsonl` (split: train|validation|test)
  - image files referenced by the JSONL (e.g. `images/...png`, `mapbox_stills/...png`, `analysis_images/...png`)

Outputs:
- `report.json`, `predictions.jsonl`, `README.md`
- `models/<model_name>/{predictions.jsonl,summary.json}`

Optionally uploads the run folder to a HF dataset repo using `upload_patagonia_eval_bundle`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from patagonia_eval_scoring import GroundingPolicy, ScoreWeights, parse_predicted_boxes  # noqa: E402
from patagonia_eval_scoring import grounding_score_vs_gold as _ground_vs_gold  # noqa: E402

try:
    from upload_patagonia_eval_to_hf import upload_patagonia_eval_bundle  # noqa: E402
except Exception:
    upload_patagonia_eval_bundle = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RowInput:
    row_id: str
    split: str
    task: str
    system_text: str | None
    user_text: str
    image_paths: list[str]
    gold_boxes: list[dict[str, Any]]


def _json_dumps(obj: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(_json_dumps(obj) + "\n")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dumps(obj, pretty=True) + "\n", encoding="utf-8")


def _load_local_vlm(model_id: str, *, device: str, dtype: str) -> tuple[Any, Any]:
    try:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Install transformers/torch for local VLM eval.") from exc

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


def _local_vlm_generate(
    model: Any,
    processor: Any,
    *,
    dataset_root: Path,
    system_text: str | None,
    user_text: str,
    image_paths: list[str],
    max_new_tokens: int,
) -> str:
    import torch

    imgs = []
    for rel in image_paths:
        p = (dataset_root / rel).resolve()
        imgs.append(Image.open(p).convert("RGB"))

    content: list[dict[str, Any]] = [{"type": "image", "image": im} for im in imgs]
    content.append({"type": "text", "text": user_text})
    conversation: list[dict[str, Any]] = []
    if system_text:
        conversation.append({"role": "system", "content": system_text})
    conversation.append({"role": "user", "content": content})
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


def _extract_messages(obj: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Return (system_text, user_message, assistant_message)."""
    msgs = obj.get("messages")
    if not isinstance(msgs, list):
        return None, None, None
    system_text: str | None = None
    user: dict[str, Any] | None = None
    assistant: dict[str, Any] | None = None
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "system":
            c = m.get("content")
            if isinstance(c, list) and c and isinstance(c[0], dict) and c[0].get("type") == "text":
                system_text = str(c[0].get("text") or "")
        elif role == "user":
            user = m
        elif role == "assistant":
            assistant = m
    return system_text, user, assistant


def _extract_user_payload(user_msg: dict[str, Any]) -> tuple[str, list[str]]:
    content = user_msg.get("content")
    if not isinstance(content, list):
        return "", []
    images: list[str] = []
    user_text = ""
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "image":
            rel = part.get("image")
            if isinstance(rel, str) and rel.strip():
                images.append(rel.strip().replace("\\", "/"))
        if part.get("type") == "text":
            t = part.get("text")
            if isinstance(t, str) and t.strip():
                user_text = t.strip()
    return user_text, images


def _assistant_text(assistant_msg: dict[str, Any] | None) -> str:
    if not assistant_msg:
        return ""
    content = assistant_msg.get("content")
    if not isinstance(content, list) or not content:
        return ""
    # Most SFT rows store a single text part.
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            return str(part.get("text") or "")
    return ""


def _gold_boxes_from_assistant_text(text: str) -> list[dict[str, Any]]:
    # Training grounding answers are either a JSON list of {label,bbox} or embedded in code fences.
    boxes = parse_predicted_boxes(text)
    out: list[dict[str, Any]] = []
    for b in boxes:
        lab = str(b.get("label") or "").strip()
        bb = b.get("bbox")
        if not lab or not isinstance(bb, list) or len(bb) != 4:
            continue
        try:
            out.append({"label": lab, "bbox": [float(x) for x in bb], "source": "sft_assistant"})
        except (TypeError, ValueError):
            continue
    return out


def _task_from_row(obj: dict[str, Any]) -> str:
    md = obj.get("metadata")
    if isinstance(md, dict):
        t = md.get("task")
        if isinstance(t, str) and t.strip():
            return t.strip()
    return "unknown"


def load_grounding_rows(dataset_root: Path, *, split: str, max_rows: int) -> list[RowInput]:
    p = dataset_root / "data" / f"{split}.jsonl"
    if not p.is_file():
        raise FileNotFoundError(f"Missing split file: {p}")

    out: list[RowInput] = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        if max_rows > 0 and len(out) >= max_rows:
            break
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            continue
        system_text, user_msg, assistant_msg = _extract_messages(obj)
        if not user_msg:
            continue
        user_text, images = _extract_user_payload(user_msg)
        if not images or not user_text:
            continue
        task = _task_from_row(obj)
        assistant_text = _assistant_text(assistant_msg)
        gold = _gold_boxes_from_assistant_text(assistant_text)
        # Prefer rows that actually carry gold boxes (grounding tasks)
        if not gold:
            continue
        row_id = str((obj.get("metadata") or {}).get("sample_id") or f"{split}:{i}")
        out.append(
            RowInput(
                row_id=row_id,
                split=split,
                task=task,
                system_text=system_text,
                user_text=user_text,
                image_paths=images,
                gold_boxes=gold,
            )
        )
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if not r.get("error")]
    n = len(rows)
    scored = max(1, len(ok))
    mean_iou = sum(float(r.get("grounding_score") or 0.0) for r in ok) / scored
    fmt_ok = sum(int(bool(r.get("format_ok"))) for r in ok) / scored
    return {
        "n": n,
        "errors": n - len(ok),
        "mean_grounding_score": round(float(mean_iou), 4),
        "format_ok_rate": round(float(fmt_ok), 4),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--dataset-root", type=Path, required=True, help="Local dataset folder containing data/<split>.jsonl + media.")
    p.add_argument("--split", default="validation", choices=("train", "validation", "test"))
    p.add_argument("--max-rows", type=int, default=200, help="Cap number of evaluated rows (0=all).")
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data" / "downloads" / "evals" / "sft_grounding_eval")
    p.add_argument("--model", action="append", default=[], help="Repeatable: name=hf_id or hf_id (name inferred).")
    p.add_argument("--base-model", default=os.environ.get("NUTONIC_PATAGONIA_EVAL_BASE_MODEL_ID", "LiquidAI/LFM2.5-VL-450M"))
    p.add_argument("--finetune-model", default=os.environ.get("NUTONIC_PATAGONIA_EVAL_FINETUNE_MODEL_ID", "NuTonic/lspace"))
    p.add_argument("--device", default="auto")
    p.add_argument("--dtype", default="bfloat16")
    p.add_argument("--max-new-tokens", type=int, default=220)
    p.add_argument("--grounding-label-mode", choices=("canonical", "any"), default="any")
    p.add_argument("--max-pred-boxes", type=int, default=3)
    p.add_argument("--box-budget-penalty-per-extra", type=float, default=0.08)
    p.add_argument("--oversize-penalty-strength", type=float, default=0.75)
    p.add_argument("--score-threshold", type=float, default=0.5)
    p.add_argument("--threshold-sweep", default="0.3,0.4,0.5,0.55,0.6,0.65")
    p.add_argument("--hf-dataset-repo", default=os.environ.get("NUTONIC_PATAGONIA_EVAL_HF_DATASET", ""))
    p.add_argument("--hf-upload-path-in-repo", default="")
    p.add_argument("--hf-upload-token", default=os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN") or "")
    p.add_argument("--skip-hf-upload", action="store_true")
    p.add_argument("--hf-upload-no-by-model", action="store_true")
    return p.parse_args(argv)


def _parse_models(args: argparse.Namespace) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if args.model:
        for raw in args.model:
            s = str(raw).strip()
            if not s:
                continue
            if "=" in s:
                n, mid = s.split("=", 1)
                out.append((n.strip() or mid.strip(), mid.strip()))
            else:
                safe = s.strip().split("/")[-1]
                out.append((safe, s.strip()))
        return out
    return [("finetune", str(args.finetune_model)), ("base", str(args.base_model))]


def _parse_thresholds(arg: str) -> list[float]:
    raw = (arg or "").strip()
    if not raw:
        return []
    vals: list[float] = []
    for part in raw.replace(",", " ").split():
        try:
            vals.append(float(part))
        except ValueError:
            pass
    return sorted({v for v in vals if 0.0 <= v <= 1.0})


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset_root = args.dataset_root.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_grounding_rows(dataset_root, split=args.split, max_rows=int(args.max_rows))
    if not rows:
        raise SystemExit("No grounding rows found in this split (assistant JSON boxes missing).")

    thresholds = _parse_thresholds(args.threshold_sweep)
    policy = GroundingPolicy(
        box_budget_max=int(args.max_pred_boxes),
        box_budget_penalty_per_extra=float(args.box_budget_penalty_per_extra),
        oversize_penalty_strength=float(args.oversize_penalty_strength),
    )

    predictions_path = out_dir / "predictions.jsonl"
    if predictions_path.exists():
        predictions_path.unlink()

    results: list[dict[str, Any]] = []
    models = _parse_models(args)
    for model_name, model_id in models:
        model, processor = _load_local_vlm(model_id, device=args.device, dtype=args.dtype)
        try:
            for r in rows:
                rec: dict[str, Any] = {
                    "row_id": r.row_id,
                    "split": r.split,
                    "task": r.task,
                    "model_name": model_name,
                    "model_id": model_id,
                    "image_paths": r.image_paths,
                }
                try:
                    pred = _local_vlm_generate(
                        model,
                        processor,
                        dataset_root=dataset_root,
                        system_text=r.system_text,
                        user_text=r.user_text,
                        image_paths=r.image_paths,
                        max_new_tokens=int(args.max_new_tokens),
                    )
                    rec["prediction"] = pred
                    pred_boxes = parse_predicted_boxes(pred)
                    rec["pred_boxes"] = pred_boxes
                    rec["format_ok"] = bool(pred_boxes)  # strict JSON extraction succeeded
                    score, diag = _ground_vs_gold(
                        pred,
                        r.gold_boxes,
                        label_mode=str(args.grounding_label_mode),
                        policy=policy,
                    )
                    rec["grounding_score"] = round(float(score), 4)
                    rec["grounding_diag"] = diag
                    rec["passed"] = bool(score >= float(args.score_threshold))
                    rec["pass_value"] = float(score)
                except Exception as exc:  # noqa: BLE001
                    rec["error"] = f"{type(exc).__name__}: {exc}"
                results.append(rec)
                _append_jsonl(predictions_path, rec)
        finally:
            del model
            del processor

    # Build per-model summaries
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_model.setdefault(str(r["model_name"]), []).append(r)

    summary_by_model: dict[str, Any] = {m: summarize(rows) for m, rows in by_model.items()}
    threshold_sweep: dict[str, Any] = {}
    for thr in thresholds:
        cur: dict[str, Any] = {}
        for m, rows_m in by_model.items():
            ok = [x for x in rows_m if not x.get("error")]
            scored = max(1, len(ok))
            passed = sum(1 for x in ok if (x.get("pass_value") is not None and float(x["pass_value"]) >= float(thr)))
            cur[m] = {"n": len(rows_m), "errors": len(rows_m) - len(ok), "passed": passed, "pass_rate": round(passed / scored, 4)}
        threshold_sweep[str(thr)] = cur

    # Write per-model artifacts for Hub browsing
    models_dir = out_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for m, rows_m in by_model.items():
        sub = models_dir / m
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "predictions.jsonl").write_text(
            "\n".join(_json_dumps(x, pretty=False) for x in rows_m) + "\n",
            encoding="utf-8",
        )
        (sub / "summary.json").write_text(json.dumps(summary_by_model[m], indent=2) + "\n", encoding="utf-8")

    report = {
        "meta": {
            "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
            "dataset_root": str(dataset_root),
            "split": args.split,
            "row_count": len(rows),
            "models": [{"model_name": n, "model_id": mid} for n, mid in models],
            "grounding_label_mode": args.grounding_label_mode,
            "grounding_policy": {
                "max_pred_boxes": args.max_pred_boxes,
                "box_budget_penalty_per_extra": args.box_budget_penalty_per_extra,
                "oversize_penalty_strength": args.oversize_penalty_strength,
            },
        },
        "summary_by_model": summary_by_model,
        "threshold_sweep": threshold_sweep,
        "results": results[: min(len(results), 2000)],  # cap; full rows are in predictions.jsonl
    }
    _write_json(out_dir / "report.json", report)

    # Markdown
    lines = [
        "# SFT Grounding Evaluation",
        "",
        f"Generated: `{report['meta']['generated_at_utc']}`",
        f"Split: `{args.split}` · rows: `{len(rows)}`",
        "",
        "## Summary",
        "",
        "| Model | N | Errors | Mean IoU | Format OK rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for m, s in summary_by_model.items():
        lines.append(f"| {m} | {s['n']} | {s['errors']} | {s['mean_grounding_score']:.3f} | {s['format_ok_rate']:.3f} |")
    if threshold_sweep:
        lines.extend(["", "## Threshold sweep (pass_rate)", ""])
        ms = list(summary_by_model.keys())
        lines.append("| Threshold | " + " | ".join(ms) + " |")
        lines.append("|---:|" + "|".join(["---:"] * len(ms)) + "|")
        for k in sorted(threshold_sweep.keys(), key=lambda x: float(x)):
            row = threshold_sweep[k]
            cells = []
            for m in ms:
                pr = row.get(m, {}).get("pass_rate")
                cells.append(f"{float(pr):.3f}" if pr is not None else "—")
            lines.append(f"| {float(k):.2f} | " + " | ".join(cells) + " |")
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Optional upload
    hf_repo = (args.hf_dataset_repo or "").strip()
    if hf_repo and not args.skip_hf_upload:
        if upload_patagonia_eval_bundle is None:
            raise SystemExit("huggingface_hub not installed; cannot upload.")
        tok = (args.hf_upload_token or "").strip() or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        path_sel = (args.hf_upload_path_in_repo or "").strip() or None
        urls = upload_patagonia_eval_bundle(
            folder=out_dir,
            repo_id=hf_repo,
            path_in_repo=path_sel,
            token=tok,
            private=False,
            upload_per_model_subfolders=not bool(args.hf_upload_no_by_model),
        )
        for u in urls:
            print(f"uploaded: {u}")

    print(f"SFT grounding eval complete: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

