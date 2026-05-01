#!/usr/bin/env python3
"""
Stage Hugging Face dataset **media + tables** into one local tree before E2E training.

Runs **step-by-step** with verification between stages:

1. **Main** — ``download_lfm_vl_training_dataset.py`` (JSONL + sampled image checks).
2. **Task hubs** — ``snapshot_download`` into the **same** ``--data-root`` with the same
   allow patterns as the main downloader (plus Parquet shards if present).
3. **Spot-check** — for each task repo, verify a random sample of remote paths exist on disk.

Then print the exact **materialize**, **verify_vlm_mix_assets**, and **run_sat_vl_sft_e2e** commands.

Environment: ``HF_TOKEN`` or ``HUGGING_FACE_HUB_TOKEN``. For speed: ``HF_HUB_ENABLE_HF_TRANSFER=1``
and ``pip install hf_transfer``.

Example::

  python train/stage_vlm_sft_media.py --data-root /data/nutonic/sat-vl-sft-training-ready-v1
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import random
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

MAIN_REPO = "NuTonic/sat-vl-sft-training-ready-v1"
TASK_REPOS = [
    "NuTonic/brief-composer-sft-v1",
    "NuTonic/oceanscout-sft-v1",
    "NuTonic/floodpulse-sft-v1",
    "NuTonic/landshift-sft-v1",
]
SMALL_REPO = "NuTonic/firewatch-sft-v1"

# Match ``download_lfm_vl_training_dataset.py`` plus common Parquet layouts on the Hub.
SNAPSHOT_ALLOW_PATTERNS = [
    "data/**",
    "images/**",
    "mapbox_stills/**",
    "analysis_images/**",
    "overlays/**",
    "README.md",
    "dataset_infos.json",
    "*.parquet",
    "**/*.parquet",
]


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def _download_via_snapshot(
    *,
    repo_id: str,
    revision: str,
    local_dir: Path,
    token: str | None,
    max_workers: int,
) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=str(local_dir),
        allow_patterns=SNAPSHOT_ALLOW_PATTERNS,
        token=token,
        max_workers=max(1, int(max_workers)),
    )


def _spot_check_repo_files(
    *,
    local_dir: Path,
    repo_id: str,
    revision: str,
    token: str | None,
    sample_size: int,
) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    remote = [
        p
        for p in api.list_repo_files(repo_id=repo_id, repo_type="dataset", revision=revision)
        if _matches(p, SNAPSHOT_ALLOW_PATTERNS) and not p.endswith("/")
    ]
    if not remote:
        raise RuntimeError(f"No files matched allow patterns for {repo_id}@{revision}")

    n = min(int(sample_size), len(remote))
    sample = random.sample(remote, n)
    missing = [p for p in sample if not (local_dir / p).is_file()]
    if missing:
        raise RuntimeError(
            f"Spot-check failed for {repo_id}: {len(missing)}/{n} sampled paths missing; "
            f"first={missing[:5]}"
        )
    print(f"  spot-check OK: {n} random path(s) from {repo_id} exist under {local_dir}", flush=True)


def _run_main_downloader(*, data_root: Path, revision: str, max_workers: int, hf_token: str | None) -> None:
    dl = REPO_ROOT / "train" / "download_lfm_vl_training_dataset.py"
    cmd = [
        sys.executable,
        str(dl),
        "--repo-id",
        MAIN_REPO,
        "--revision",
        revision,
        "--out-dir",
        str(data_root),
        "--download-strategy",
        "snapshot",
        "--max-workers",
        str(max_workers),
    ]
    if hf_token:
        cmd.extend(["--hf-token", hf_token])
    print("+ " + " ".join(cmd), flush=True)
    rc = subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode
    if rc != 0:
        raise SystemExit(f"Main download failed with exit code {rc}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Single directory that will contain merged trees (images/, data/, …).",
    )
    p.add_argument("--revision", default="main")
    p.add_argument("--max-workers", type=int, default=32)
    p.add_argument(
        "--hf-token",
        default=None,
        help="Optional; else HF_TOKEN / HUGGING_FACE_HUB_TOKEN from the environment.",
    )
    p.add_argument(
        "--skip-main",
        action="store_true",
        help="Skip main corpus download (already staged).",
    )
    p.add_argument(
        "--skip-tasks",
        action="store_true",
        help="Skip task / Firewatch snapshot steps.",
    )
    p.add_argument(
        "--spot-check-samples",
        type=int,
        default=25,
        help="Random paths to verify per task repo after snapshot.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for spot-check sampling (reproducible).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    random.seed(int(args.seed))

    data_root = args.data_root.expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)

    token = args.hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

    if not args.skip_main:
        print("\n========== STEP 1/2: main corpus (verified JSONL + media sample) ==========\n", flush=True)
        _run_main_downloader(
            data_root=data_root,
            revision=args.revision,
            max_workers=args.max_workers,
            hf_token=token,
        )
    else:
        print("\n========== STEP 1/2: skipped (--skip-main) ==========\n", flush=True)

    if not args.skip_tasks:
        print("\n========== STEP 2/2: task + Firewatch hubs (snapshot + spot-check) ==========\n", flush=True)
        for repo_id in [*TASK_REPOS, SMALL_REPO]:
            print(f"--- {repo_id} ---", flush=True)
            _download_via_snapshot(
                repo_id=repo_id,
                revision=args.revision,
                local_dir=data_root,
                token=token,
                max_workers=args.max_workers,
            )
            _spot_check_repo_files(
                local_dir=data_root,
                repo_id=repo_id,
                revision=args.revision,
                token=token,
                sample_size=args.spot_check_samples,
            )
    else:
        print("\n========== STEP 2/2: skipped (--skip-tasks) ==========\n", flush=True)

    mix = "/data/nutonic/vlm_mix_parquet"
    leap = "/data/nutonic/sat_vl_out"
    print("\n========== NEXT: materialize → verify mix → E2E ==========\n", flush=True)
    print(
        f"MIX={mix}\n"
        f"LEAP_PARENT={leap}\n"
        f"DATA_ROOT={data_root}\n\n"
        "1) Build Parquet mix:\n"
        f"   python train/materialize_vlm_sft_mix.py --out-dir {mix} --overwrite \\\n"
        "     --task-repeat 8 --small-repeat 80\n\n"
        "2) Verify rows reference files on disk:\n"
        f"   python train/verify_vlm_mix_assets.py --mix-dir {mix} --image-root {data_root} --max-rows 500\n\n"
        "3) Train + Hub uploads:\n"
        f"   python train/run_sat_vl_sft_e2e.py \\\n"
        f"     --leap-output-parent {leap} --mix-out-dir {mix} --image-root {data_root} \\\n"
        "     --mix-overwrite --epochs 1 --learning-rate 1e-5 \\\n"
        "     --mix-task-repeat 8 --mix-small-repeat 80 \\\n"
        "     --hf-model-repo NuTonic/YOUR_MODEL --hf-artifacts-repo NuTonic/YOUR_ARTIFACTS \\\n"
        "     --launch\n",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
