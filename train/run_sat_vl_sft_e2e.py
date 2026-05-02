#!/usr/bin/env python3
"""
End-to-end NU:TONIC satellite VLM SFT **single-run** training + Hugging Face Hub upload.

Stages:

1. **Materialize** (optional): one Parquet directory mixing ~800k **main** hub rows,
   repeated **task** hubs (~5k combined by default), and repeated **Firewatch** (~200 rows)
   so rare slices still matter after LEAP shuffles (see ``materialize_vlm_sft_mix.py``).
2. **Train once** on that mix via LEAP ``vlm_sft``.
3. Upload merged weights + optional artifacts (checkpoints, configs, manifest).

When ``--hf-artifacts-repo`` is set, checkpoints and a merged snapshot are uploaded
after training (single pass — no intermediate phase overwrites).

Environment:

* ``OUTPUT_DIR`` is set to ``--leap-output-parent`` for LEAP runs.
* ``HF_TOKEN`` or ``HUGGING_FACE_HUB_TOKEN`` for upload (unless ``--no-push``).

Typical remote GPU usage::

  python train/run_sat_vl_sft_e2e.py \\
    --leap-output-parent /data/nutonic/sat_vl_run1 \\
    --mix-out-dir /data/nutonic/parquet_mix_v1 \\
    --hf-model-repo NuTonic/my-lfm-vl-sat-sft-v1 \\
    --hf-artifacts-repo NuTonic/my-lfm-vl-sat-sft-v1-artifacts \\
    --launch

Use the same repo for ``--hf-model-repo`` and ``--hf-artifacts-repo`` if you want release
weights at the repo root and artifacts under ``runs/<run>/...``.

Prerequisite: ``uv`` + LEAP submodule at ``refs/leap-finetune-main`` (same as
``train/train_lfm_vl_sft.py``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MAIN = "NuTonic/sat-vl-sft-training-ready-v1"
DEFAULT_SMALL = "NuTonic/firewatch-sft-v1"


def _find_run_dir(leap_output_parent: Path) -> Path:
    dirs = [
        d
        for d in leap_output_parent.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ]
    if not dirs:
        raise FileNotFoundError(f"No run subdirectory under {leap_output_parent}")

    def score(path: Path) -> float:
        base = path.stat().st_mtime
        if (path / "latest").exists():
            return base + 1e12
        return base

    return max(dirs, key=score)


def _find_latest_merged_model(run_dir: Path) -> Path:
    merged = [p for p in run_dir.iterdir() if p.is_dir() and "-lora_m-" in p.name]
    if not merged:
        raise FileNotFoundError(
            f"No merged model directory (-lora_m-) under {run_dir}. "
            "Ensure LEAP finished and PEFT merge ran."
        )
    return max(merged, key=lambda p: p.stat().st_mtime)


def _checkpoint_dirs(run_dir: Path) -> list[Path]:
    """LEAP may leave ``checkpoint-*`` dirs or renamed ``...-e{N}s{step}-...`` folders."""
    out: list[Path] = []
    renamed = re.compile(r"-e\d+s\d+-")
    for p in run_dir.iterdir():
        if not p.is_dir() or p.name.startswith("."):
            continue
        if p.name.startswith("checkpoint-"):
            out.append(p)
        elif renamed.search(p.name):
            out.append(p)
    return sorted(out, key=lambda x: x.stat().st_mtime)


def _merged_dirs(run_dir: Path) -> list[Path]:
    return sorted(
        (p for p in run_dir.iterdir() if p.is_dir() and "-lora_m-" in p.name),
        key=lambda p: p.stat().st_mtime,
    )


def _hub_token() -> str | None:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def _ensure_model_repo(*, api: Any, repo_id: str, private: bool) -> None:
    from huggingface_hub import create_repo

    create_repo(repo_id, repo_type="model", private=private, exist_ok=True)


def _upload_folder(
    *,
    folder: Path,
    repo_id: str,
    private: bool,
    path_in_repo: str | None = None,
) -> None:
    from huggingface_hub import HfApi

    token = _hub_token()
    api = HfApi(token=token)
    _ensure_model_repo(api=api, repo_id=repo_id, private=private)
    kwargs: dict[str, Any] = {
        "folder_path": str(folder),
        "repo_id": repo_id,
        "repo_type": "model",
        "token": token,
    }
    if path_in_repo:
        kwargs["path_in_repo"] = path_in_repo.strip("/")
    api.upload_folder(**kwargs)


def _upload_file(
    *,
    local_path: Path,
    repo_id: str,
    private: bool,
    path_in_repo: str,
) -> None:
    from huggingface_hub import HfApi

    token = _hub_token()
    api = HfApi(token=token)
    _ensure_model_repo(api=api, repo_id=repo_id, private=private)
    api.upload_file(
        path_or_fileobj=str(local_path),
        path_in_repo=path_in_repo.strip("/"),
        repo_id=repo_id,
        repo_type="model",
        token=token,
    )


def _write_model_card(path: Path, *, base_model: str, hub_repo: str) -> None:
    body = f"""---
library_name: transformers
tags:
  - vision-language
  - satellite
  - geospatial
  - liquid-ai
  - lfm
base_model: LiquidAI/{base_model}
---

# {hub_repo}

Fine-tuned from `LiquidAI/{base_model}` using the NU:TONIC satellite VLM SFT mix
(`train/run_sat_vl_sft_e2e.py`): single LEAP run on main + task + Firewatch Parquet mix.

Training stack: LEAP `vlm_sft` in this repo's `refs/leap-finetune-main`.
"""
    path.write_text(body, encoding="utf-8")


def _artifacts_base_path(run_dir: Path, override: str | None) -> str:
    if override:
        return override.strip("/")
    safe = re.sub(r"[^\w.\-]+", "_", run_dir.name).strip("_")
    return f"runs/{safe or 'unnamed_run'}"


def _write_artifacts_readme(path: Path, *, base_path: str, run_dir: Path) -> None:
    body = f"""# Training artifacts

Local run directory: `{run_dir}`

Hub layout under `{base_path}/`:

- `checkpoints/<checkpoint_dir_name>/` — Hugging Face Trainer / LEAP checkpoints (LoRA + optimizer state).
- `merged_after_training/` — full-precision merged model snapshot after the single training run.
- `configs/` — generated LEAP YAML for this run.
- `manifest.jsonl` — one JSON line with epoch/LR/dataset summary.
- `ray_logs/` — optional Ray Train experiment export if enabled with ``--upload-ray-logs``.

The **canonical release** weights may also be uploaded separately to your primary model repo (repo root).
"""
    path.write_text(body, encoding="utf-8")


class _ArtifactUploader:
    """Tracks checkpoint folders already uploaded to avoid duplicate transfers."""

    def __init__(
        self,
        *,
        repo_id: str,
        private: bool,
        base_path: str,
        dry_run: bool,
    ) -> None:
        self.repo_id = repo_id
        self.private = private
        self.base_path = base_path.rstrip("/")
        self.dry_run = dry_run
        self._seen_ckpt: set[str] = set()

    def upload_new_checkpoints(self, run_dir: Path) -> None:
        for ck in _checkpoint_dirs(run_dir):
            if ck.name in self._seen_ckpt:
                continue
            dest = f"{self.base_path}/checkpoints/{ck.name}"
            print(f"  [artifacts] checkpoint -> {self.repo_id} ({dest})", flush=True)
            if not self.dry_run:
                _upload_folder(
                    folder=ck,
                    repo_id=self.repo_id,
                    private=self.private,
                    path_in_repo=dest,
                )
            self._seen_ckpt.add(ck.name)

    def upload_merged_snapshot(self, run_dir: Path, *, hub_subdir: str) -> None:
        merged_list = _merged_dirs(run_dir)
        if not merged_list:
            print("  [artifacts] no merged (-lora_m-) folder yet", flush=True)
            return
        latest = merged_list[-1]
        dest = f"{self.base_path}/{hub_subdir.strip('/')}/{latest.name}"
        print(f"  [artifacts] merged snapshot -> {self.repo_id} ({dest})", flush=True)
        if not self.dry_run:
            _upload_folder(
                folder=latest,
                repo_id=self.repo_id,
                private=self.private,
                path_in_repo=dest,
            )

    def upload_configs(self, config_paths: list[Path]) -> None:
        for p in config_paths:
            if not p.is_file():
                continue
            dest = f"{self.base_path}/configs/{p.name}"
            print(f"  [artifacts] config {p.name} -> {self.repo_id}", flush=True)
            if not self.dry_run:
                _upload_file(
                    local_path=p,
                    repo_id=self.repo_id,
                    private=self.private,
                    path_in_repo=dest,
                )

    def upload_ray_logs(self, run_dir: Path) -> None:
        ray_dir = run_dir / "ray_logs"
        if not ray_dir.is_dir():
            print("  [artifacts] no ray_logs/ directory (skip)", flush=True)
            return
        dest = f"{self.base_path}/ray_logs"
        print(f"  [artifacts] ray_logs -> {self.repo_id} ({dest})", flush=True)
        if not self.dry_run:
            _upload_folder(
                folder=ray_dir,
                repo_id=self.repo_id,
                private=self.private,
                path_in_repo=dest,
            )

    def append_manifest(self, run_dir: Path, entry: dict[str, Any]) -> None:
        """Append one JSON line to a local manifest; upload the file to Hub."""
        manifest_path = run_dir / "hub_artifacts_manifest.jsonl"
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        print(f"  [artifacts] manifest entry ({entry.get('training', 'run')})", flush=True)
        if self.dry_run:
            return
        with manifest_path.open("a", encoding="utf-8") as f:
            f.write(line)
        _upload_file(
            local_path=manifest_path,
            repo_id=self.repo_id,
            private=self.private,
            path_in_repo=f"{self.base_path}/manifest.jsonl",
        )

    def upload_readme(self, run_dir: Path) -> None:
        path = run_dir / "ARTIFACTS_README.md"
        if self.dry_run:
            print(f"  [artifacts] README -> {self.repo_id} ({self.base_path}/README.md)", flush=True)
            return
        _write_artifacts_readme(path, base_path=self.base_path, run_dir=run_dir)
        _upload_file(
            local_path=path,
            repo_id=self.repo_id,
            private=self.private,
            path_in_repo=f"{self.base_path}/README.md",
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument(
        "--leap-output-parent",
        type=Path,
        required=True,
        help="Directory passed to LEAP as OUTPUT_DIR (contains one timestamped run folder per job).",
    )
    p.add_argument(
        "--mix-out-dir",
        type=Path,
        default=REPO_ROOT / "train" / "cache" / "vlm_sft_task_mix_parquet",
        help="Parquet directory for training (materialized if --materialize).",
    )
    p.add_argument("--model-name", default="LFM2.5-VL-450M")
    p.add_argument("--project-name", default="nutonic_sat_vl_sft_single")
    p.add_argument("--leap-root", default=str(REPO_ROOT / "refs" / "leap-finetune-main"))

    p.add_argument("--epochs", type=int, default=1, help="Training epochs on the mixed Parquet corpus.")
    p.add_argument("--learning-rate", type=float, default=1e-5)

    p.add_argument("--materialize", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument(
        "--mix-overwrite",
        action="store_true",
        help="Pass --overwrite to materialize_vlm_sft_mix.py.",
    )
    p.add_argument("--mix-chunk-rows", type=int, default=4096)
    p.add_argument(
        "--mix-task-repeat",
        type=int,
        default=8,
        help="Forwarded to materialize_vlm_sft_mix.py --task-repeat.",
    )
    p.add_argument(
        "--mix-small-repeat",
        type=int,
        default=80,
        help="Forwarded to materialize_vlm_sft_mix.py --small-repeat.",
    )
    p.add_argument("--mix-main-max-rows", type=int, default=None)
    p.add_argument("--mix-subset", default=None)

    p.add_argument("--hf-model-repo", default=None, help="HF model repo id to upload (e.g. NuTonic/my-model).")
    p.add_argument(
        "--hf-artifacts-repo",
        default=None,
        help=(
            "HF model repo for checkpoints, merged snapshot, configs "
            "(tree under --artifacts-base-path). May match --hf-model-repo."
        ),
    )
    p.add_argument(
        "--artifacts-base-path",
        default=None,
        help="Hub path prefix for artifacts (default: runs/<sanitized_local_run_dir_name>).",
    )
    p.add_argument(
        "--upload-artifacts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Upload checkpoints + merged snapshot + config when --hf-artifacts-repo is set.",
    )
    p.add_argument(
        "--upload-ray-logs",
        action="store_true",
        help="Also upload run_dir/ray_logs to the artifacts repo (can be large).",
    )
    p.add_argument(
        "--no-push",
        action="store_true",
        help="Skip all Hub uploads (final model, checkpoints, artifacts, configs).",
    )
    p.add_argument("--private-repo", action="store_true", help="Create HF model repo as private.")

    p.add_argument(
        "--image-root",
        default=None,
        help=(
            "Required for local Parquet training when rows use repo-relative paths (images/, "
            "mapbox_stills/, …). Must be the dataset root directory that contains those folders "
            "(see train/download_lfm_vl_training_dataset.py). Union extra hub files here if needed."
        ),
    )
    p.add_argument(
        "--verify-mix-assets",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Before LEAP, run train/verify_vlm_mix_assets.py on a sample of rows (needs files on disk).",
    )
    p.add_argument("--per-device-train-batch-size", type=int, default=1)
    p.add_argument("--gradient-accumulation-steps", type=int, default=16)
    p.add_argument("--test-size", type=float, default=0.02)
    p.add_argument("--tracker", default="none", choices=("none", "wandb", "trackio"))
    p.add_argument("--trackio-space-id", default=None, help="HF Space id for Trackio sync, e.g. NuTonic/lspace-trackio.")
    p.add_argument("--dry-run", action="store_true", help="Print steps without executing training/upload.")

    p.add_argument(
        "--launch",
        action="store_true",
        help="Pass --launch to train_lfm_vl_sft.py (required for real training).",
    )
    return p.parse_args(argv)


def _train_command(*, dataset: str, args: argparse.Namespace) -> list[str]:
    cfg = REPO_ROOT / "train" / "configs" / "sat_vl_sft_single.yaml"
    cmd = [
        sys.executable,
        str(REPO_ROOT / "train" / "train_lfm_vl_sft.py"),
        "--dataset",
        dataset,
        "--epochs",
        str(args.epochs),
        "--learning-rate",
        str(args.learning_rate),
        "--project-name",
        args.project_name,
        "--model-name",
        args.model_name,
        "--leap-root",
        args.leap_root,
        "--config-out",
        str(cfg),
        "--per-device-train-batch-size",
        str(args.per_device_train_batch_size),
        "--gradient-accumulation-steps",
        str(args.gradient_accumulation_steps),
        "--test-size",
        str(args.test_size),
    ]
    if args.image_root:
        cmd.extend(["--image-root", args.image_root])
    if args.tracker:
        cmd.extend(["--tracker", args.tracker])
    if args.trackio_space_id:
        cmd.extend(["--trackio-space-id", args.trackio_space_id])
    if args.launch:
        cmd.append("--launch")
    return cmd


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.dry_run and not args.launch:
        print(
            "Training steps require --launch (invokes LEAP through train_lfm_vl_sft.py). "
            "Use --dry-run to print commands only.",
            file=sys.stderr,
        )
        return 2

    leap_parent = args.leap_output_parent.expanduser().resolve()
    leap_parent.mkdir(parents=True, exist_ok=True)

    mix_dir = args.mix_out_dir.expanduser().resolve()

    if args.materialize:
        mat_cmd = [
            sys.executable,
            str(REPO_ROOT / "train" / "materialize_vlm_sft_mix.py"),
            "--out-dir",
            str(mix_dir),
            "--chunk-rows",
            str(args.mix_chunk_rows),
            "--task-repeat",
            str(args.mix_task_repeat),
            "--small-repeat",
            str(args.mix_small_repeat),
        ]
        if args.mix_overwrite:
            mat_cmd.append("--overwrite")
        if args.mix_main_max_rows is not None:
            mat_cmd.extend(["--main-max-rows", str(args.mix_main_max_rows)])
        if args.mix_subset:
            mat_cmd.extend(["--subset", args.mix_subset])
        mat_cmd.extend(
            [
                "--main-repo-id",
                DEFAULT_MAIN,
                "--small-repo-id",
                DEFAULT_SMALL,
            ]
        )
        print("+ " + " ".join(mat_cmd), flush=True)
        if not args.dry_run:
            rc = subprocess.run(mat_cmd, cwd=str(REPO_ROOT)).returncode
            if rc != 0:
                return rc

    env = os.environ.copy()
    env["OUTPUT_DIR"] = str(leap_parent)

    dataset_path = str(mix_dir)
    config_path = REPO_ROOT / "train" / "configs" / "sat_vl_sft_single.yaml"

    mix_dir_resolved = mix_dir.expanduser().resolve()
    if (
        not args.dry_run
        and mix_dir_resolved.is_dir()
        and any(mix_dir_resolved.glob("*.parquet"))
        and not args.image_root
    ):
        print(
            "Warning: local Parquet mix without --image-root. LEAP will resolve paths like "
            "images/... against image_root; without it, validation fails (image not loadable). "
            "Download hub assets and pass --image-root /path/to/dataset/root.",
            file=sys.stderr,
        )

    if (
        not args.dry_run
        and args.verify_mix_assets
        and args.image_root
        and mix_dir_resolved.is_dir()
        and any(mix_dir_resolved.glob("*.parquet"))
    ):
        verify_cmd = [
            sys.executable,
            str(REPO_ROOT / "train" / "verify_vlm_mix_assets.py"),
            "--mix-dir",
            str(mix_dir_resolved),
            "--image-root",
            str(Path(args.image_root).expanduser().resolve()),
            "--max-rows",
            "500",
        ]
        print("+ " + " ".join(verify_cmd), flush=True)
        rv = subprocess.run(verify_cmd, cwd=str(REPO_ROOT)).returncode
        if rv != 0:
            return rv

    cmd = _train_command(dataset=dataset_path, args=args)
    print("+ " + " ".join(cmd), flush=True)
    if args.dry_run:
        base_preview = _artifacts_base_path(
            Path("dry-run-placeholder"), args.artifacts_base_path
        )
        if args.hf_artifacts_repo and args.upload_artifacts and not args.no_push:
            print(
                f"  [dry-run] After training: checkpoints, merged_after_training/, "
                f"manifest -> {args.hf_artifacts_repo} ({base_preview}/)",
                flush=True,
            )
        print("Dry run complete.", flush=True)
        return 0

    rc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env).returncode
    if rc != 0:
        return rc

    run_dir = _find_run_dir(leap_parent)

    want_artifacts = (
        bool(args.hf_artifacts_repo)
        and args.upload_artifacts
        and not args.no_push
    )
    artifact_uploader: _ArtifactUploader | None = None
    if want_artifacts:
        base = _artifacts_base_path(run_dir, args.artifacts_base_path)
        artifact_uploader = _ArtifactUploader(
            repo_id=args.hf_artifacts_repo,
            private=args.private_repo,
            base_path=base,
            dry_run=False,
        )
        print(f"Artifacts hub prefix: {args.hf_artifacts_repo} ({base})", flush=True)
        artifact_uploader.upload_readme(run_dir)
        print("Uploading artifacts after training...", flush=True)
        artifact_uploader.upload_new_checkpoints(run_dir)
        artifact_uploader.upload_merged_snapshot(run_dir, hub_subdir="merged_after_training")
        artifact_uploader.append_manifest(
            run_dir,
            {
                "training": "single_mix",
                "dataset": dataset_path,
                "epochs": args.epochs,
                "learning_rate": args.learning_rate,
                "model_name": args.model_name,
                "project_name": args.project_name,
                "main_hub": DEFAULT_MAIN,
                "mix_task_repeat": args.mix_task_repeat,
                "mix_small_repeat": args.mix_small_repeat,
            },
        )
        artifact_uploader.upload_configs([config_path])
        if args.upload_ray_logs:
            artifact_uploader.upload_ray_logs(run_dir)

    merged = _find_latest_merged_model(run_dir)
    print(f"Merged model directory: {merged}", flush=True)

    if args.no_push:
        print("Skipping Hub upload (--no-push).", flush=True)
        return 0

    if not args.hf_model_repo:
        print(
            "Skipping primary model upload: provide --hf-model-repo.",
            file=sys.stderr,
        )
        return 0

    readme = merged / "README.md"
    if not readme.is_file():
        _write_model_card(readme, base_model=args.model_name, hub_repo=args.hf_model_repo)

    print(f"Uploading release merged weights {merged} -> {args.hf_model_repo} (repo root) ...", flush=True)
    _upload_folder(folder=merged, repo_id=args.hf_model_repo, private=args.private_repo)
    print("Upload complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
