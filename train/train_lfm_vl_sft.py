#!/usr/bin/env python3
"""
Configurable launcher for fine-tuning LFM-VL on NU:TONIC satellite SFT datasets.

This script generates a LEAP `vlm_sft` YAML config and can optionally execute the
reference trainer in `refs/leap-finetune-main`. It is intentionally thin: model
loading, Ray/DeepSpeed setup, VLM collation, image loading, and LoRA application
remain owned by the LEAP reference code.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEAP_ROOT = REPO_ROOT / "refs" / "leap-finetune-main"
DEFAULT_DATASET = "NuTonic/sat-vl-sft-training-ready-v1"
# LEAP's loader prepends "LiquidAI/" for non-local names, so keep this short.
DEFAULT_MODEL = "LFM2.5-VL-450M"


def _resolve_uv_executable(uv_arg: str) -> str | None:
    """Return a usable uv path, or None if uv is not installed."""
    candidate = Path(uv_arg).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    w = shutil.which(uv_arg)
    return str(Path(w).resolve()) if w else None


def _leap_launch_without_uv(leap_root: Path, config_path: Path) -> tuple[list[str], dict[str, str]]:
    """
    Run leap-finetune entrypoint with the current interpreter when uv is missing.

    Requires LEAP dependencies (torch, ray, etc.) in the active environment, e.g.:
    ``pip install -e refs/leap-finetune-main``
    """
    leap_src = (leap_root.resolve() / "src").resolve()
    if not leap_src.is_dir():
        raise SystemExit(f"LEAP src layout missing: {leap_src}")

    env = os.environ.copy()
    sep = os.pathsep
    prev = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = str(leap_src) if not prev else f"{leap_src}{sep}{prev}"

    cfg = str(config_path.resolve())
    code = (
        "import sys;"
        f"sys.argv = ['leap-finetune', {cfg!r}];"
        "from leap_finetune import main;"
        "main()"
    )
    return [sys.executable, "-c", code], env


def _quote_yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _emit_yaml(obj: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(obj, dict):
        lines: list[str] = []
        for key, value in obj.items():
            if isinstance(value, dict):
                lines.append(f"{pad}{key}:")
                lines.extend(_emit_yaml(value, indent + 2))
            elif isinstance(value, list):
                lines.append(f"{pad}{key}:")
                lines.extend(_emit_yaml(value, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_quote_yaml_scalar(value)}")
        return lines
    if isinstance(obj, list):
        lines = []
        for value in obj:
            if isinstance(value, dict):
                lines.append(f"{pad}-")
                lines.extend(_emit_yaml(value, indent + 2))
            else:
                lines.append(f"{pad}- {_quote_yaml_scalar(value)}")
        return lines
    return [f"{pad}{_quote_yaml_scalar(obj)}"]


def _write_yaml(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(_emit_yaml(obj)) + "\n", encoding="utf-8")


def _build_config(args: argparse.Namespace) -> dict[str, Any]:
    training_config: dict[str, Any] = {
        "extends": "DEFAULT_VLM_SFT",
        "num_train_epochs": args.epochs,
        "per_device_train_batch_size": args.per_device_train_batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "learning_rate": args.learning_rate,
        "warmup_ratio": args.warmup_ratio,
        "weight_decay": args.weight_decay,
        "lr_scheduler_type": args.lr_scheduler_type,
        "logging_steps": args.logging_steps,
        "save_strategy": args.save_strategy,
        "eval_strategy": args.eval_strategy,
        "eval_on_start": args.eval_on_start,
        "gradient_checkpointing": args.gradient_checkpointing,
        "dataloader_drop_last": args.dataloader_drop_last,
        "max_image_tokens": args.max_image_tokens,
        "do_image_splitting": args.do_image_splitting,
        "vision_encoder_lr_multiplier": args.vision_encoder_lr_multiplier,
        "tracker": args.tracker,
    }
    if args.resume_from_checkpoint:
        training_config["resume_from_checkpoint"] = args.resume_from_checkpoint
    if args.trackio_space_id:
        training_config["trackio_space_id"] = args.trackio_space_id
    if args.output_dir:
        training_config["output_dir"] = args.output_dir
    if args.use_liger_kernel:
        training_config["use_liger_kernel"] = True

    config: dict[str, Any] = {
        "project_name": args.project_name,
        "model_name": args.model_name,
        "training_type": "vlm_sft",
        "dataset": {
            "path": args.dataset,
            "type": "vlm_sft",
            "limit": args.limit,
            "test_size": args.test_size,
            "split": args.split,
            "image_root": args.image_root,
            "cache_dataset": args.cache_dataset,
        },
        "training_config": training_config,
        "peft_config": {
            "extends": args.peft_preset,
            "use_peft": args.use_peft,
            "r": args.lora_r,
            "lora_alpha": args.lora_alpha,
            "lora_dropout": args.lora_dropout,
            "bias": "none",
        },
    }

    if args.benchmark_jsonl:
        config["benchmarks"] = {
            "max_new_tokens": args.benchmark_max_new_tokens,
            "image_root": args.benchmark_image_root or args.image_root,
            "benchmarks": [
                {
                    "name": args.benchmark_name,
                    "path": args.benchmark_jsonl,
                    "metric": args.benchmark_metric,
                    "limit": args.benchmark_limit,
                }
            ],
        }
    return config


def _validate_args(args: argparse.Namespace) -> None:
    leap_root = Path(args.leap_root).resolve()
    if not leap_root.is_dir():
        raise SystemExit(f"LEAP root not found: {leap_root}")
    if not (leap_root / "pyproject.toml").is_file():
        raise SystemExit(f"LEAP root does not look valid (missing pyproject.toml): {leap_root}")
    if args.image_root and not Path(args.image_root).exists() and not args.image_root.startswith(("s3://", "gs://", "/")):
        print(f"Warning: image_root does not exist locally: {args.image_root}", file=sys.stderr)
    if args.learning_rate <= 0:
        raise SystemExit("--learning-rate must be positive")
    if not (0 < args.test_size < 1):
        raise SystemExit("--test-size must be between 0 and 1")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--dataset", default=DEFAULT_DATASET, help="HF dataset id or local JSONL/parquet path.")
    p.add_argument("--model-name", default=DEFAULT_MODEL, help="LFM-VL base model id/name.")
    p.add_argument("--project-name", default="nutonic_sat_vl_sft")
    p.add_argument("--split", default="train")
    p.add_argument("--limit", type=int, default=None, help="Optional row cap for smoke tests.")
    p.add_argument("--test-size", type=float, default=0.02, help="Held-out split created by LEAP loader.")
    p.add_argument(
        "--image-root",
        default=None,
        help=(
            "Prepended to relative image paths in messages (local Parquet/JSONL). "
            "Use the HF dataset checkout root—the directory that contains images/, "
            "mapbox_stills/, etc."
        ),
    )
    p.add_argument("--cache-dataset", action="store_true")

    p.add_argument("--epochs", type=float, default=1.0)
    p.add_argument("--per-device-train-batch-size", type=int, default=1)
    p.add_argument("--gradient-accumulation-steps", type=int, default=16)
    p.add_argument("--learning-rate", type=float, default=1e-5)
    p.add_argument("--warmup-ratio", type=float, default=0.05)
    p.add_argument("--weight-decay", type=float, default=0.0)
    p.add_argument("--lr-scheduler-type", default="cosine")
    p.add_argument("--logging-steps", type=int, default=10)
    p.add_argument("--save-strategy", default="epoch")
    p.add_argument("--eval-strategy", default="epoch")
    p.add_argument("--no-eval-on-start", dest="eval_on_start", action="store_false")
    p.set_defaults(eval_on_start=True)
    p.add_argument("--no-gradient-checkpointing", dest="gradient_checkpointing", action="store_false")
    p.set_defaults(gradient_checkpointing=True)
    p.add_argument("--no-dataloader-drop-last", dest="dataloader_drop_last", action="store_false")
    p.set_defaults(dataloader_drop_last=True)
    p.add_argument("--max-image-tokens", type=int, default=None)
    p.add_argument("--no-image-splitting", dest="do_image_splitting", action="store_false")
    p.set_defaults(do_image_splitting=True)
    p.add_argument("--vision-encoder-lr-multiplier", type=float, default=0.05)
    p.add_argument("--use-liger-kernel", action="store_true")
    p.add_argument("--resume-from-checkpoint", default=None, help="'latest' or explicit checkpoint path.")
    p.add_argument("--output-dir", default=None, help="Override LEAP output_dir.")

    p.add_argument("--use-peft", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--peft-preset", default="DEFAULT_VLM_LORA", choices=("DEFAULT_VLM_LORA", "MINIMAL_VLM_LORA"))
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--lora-dropout", type=float, default=0.05)

    p.add_argument("--tracker", default="none", choices=("none", "wandb", "trackio"))
    p.add_argument("--trackio-space-id", default=None)

    p.add_argument("--benchmark-jsonl", default=None, help="Optional LEAP-format VLM eval JSONL.")
    p.add_argument("--benchmark-name", default="patagonia_tim_eval")
    p.add_argument("--benchmark-metric", default="short_answer")
    p.add_argument("--benchmark-limit", type=int, default=None)
    p.add_argument("--benchmark-max-new-tokens", type=int, default=220)
    p.add_argument("--benchmark-image-root", default=None)

    p.add_argument("--leap-root", default=str(DEFAULT_LEAP_ROOT))
    p.add_argument("--config-out", default=str(REPO_ROOT / "train" / "configs" / "lfm_vl_satellite_sft.yaml"))
    p.add_argument("--dry-run", action="store_true", help="Only write the config.")
    p.add_argument(
        "--launch",
        action="store_true",
        help=(
            "Run leap-finetune after writing config (prefers ``uv run``; falls back to "
            "current Python + PYTHONPATH if uv is not installed)."
        ),
    )
    p.add_argument("--uv", default=os.environ.get("UV", "uv"), help="uv executable (full path allowed).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _validate_args(args)

    config = _build_config(args)
    config_path = Path(args.config_out).resolve()
    _write_yaml(config_path, config)
    print(f"Wrote training config: {config_path}")

    if args.dry_run or not args.launch:
        print("Dry run complete. Add --launch to start training.")
        return 0

    leap_root = Path(args.leap_root).resolve()
    uv_bin = _resolve_uv_executable(args.uv)
    if uv_bin:
        cmd = [uv_bin, "run", "--directory", str(leap_root), "leap-finetune", str(config_path)]
        print("+ " + " ".join(cmd), flush=True)
        return subprocess.run(cmd, check=False).returncode

    print(
        "uv not found on PATH; launching leap-finetune with this Python and PYTHONPATH "
        f"(install uv from https://docs.astral.sh/uv/ or use: pip install -e {leap_root}).",
        file=sys.stderr,
    )
    cmd, env = _leap_launch_without_uv(leap_root, config_path)
    print(f"+ {sys.executable} -c '... leap-finetune {config_path}'", flush=True)
    return subprocess.run(cmd, check=False, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
