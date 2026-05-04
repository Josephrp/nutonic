#!/usr/bin/env python3
"""
Stage source Hub dataset media into the namespaced layout referenced by the VLM mix.

The training-ready rows reference paths like::

  images/NuTonic__sat-bbox-metadata-sft-v1/s00000/...

But downloading ``NuTonic/sat-bbox-metadata-sft-v1`` directly into the shared data
root usually creates::

  images/s00000/...

This script downloads each source repo into an isolated cache directory, then stages
``images/``, ``mapbox_stills/``, ``analysis_images/``, and ``overlays/`` under the
repo namespace expected by the Parquet rows.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


DEFAULT_REPOS = [
    "NuTonic/sat-bbox-metadata-sft-v1",
    "NuTonic/sat-image-boundingbox-sft-full",
    "NuTonic/brief-composer-sft-v1",
    "NuTonic/oceanscout-sft-v1",
    "NuTonic/floodpulse-sft-v1",
    "NuTonic/landshift-sft-v1",
    "NuTonic/firewatch-sft-v1",
]

MEDIA_DIRS = ("images", "mapbox_stills", "analysis_images", "overlays")
ALLOW_PATTERNS = [f"{d}/**" for d in MEDIA_DIRS] + ["README.md", "dataset_infos.json"]


def _safe_repo(repo_id: str) -> str:
    return repo_id.replace("/", "__")


def _stage_file(src: Path, dst: Path, *, mode: str) -> bool:
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copy2(src, dst)
    elif mode == "symlink":
        os.symlink(src, dst)
    elif mode == "hardlink":
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    else:
        raise ValueError(f"Unsupported mode: {mode}")
    return True


def _stage_tree(src_root: Path, dst_root: Path, *, mode: str) -> tuple[int, int]:
    staged = 0
    skipped = 0
    if not src_root.is_dir():
        return staged, skipped
    for src in src_root.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(src_root)
        if _stage_file(src, dst_root / rel, mode=mode):
            staged += 1
        else:
            skipped += 1
    return staged, skipped


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--data-root", type=Path, required=True, help="Shared root used as --image-root for training.")
    p.add_argument(
        "--download-root",
        type=Path,
        default=Path("/data/nutonic/source_hf_assets"),
        help="Isolated per-repo download cache. Keep this if using --link-mode symlink.",
    )
    p.add_argument("--repo-id", action="append", default=[], help="Repo to stage. Repeatable. Defaults to all known repos.")
    p.add_argument("--revision", default="main")
    p.add_argument("--max-workers", type=int, default=32)
    p.add_argument("--hf-token", default=None, help="Override HF_TOKEN / HUGGING_FACE_HUB_TOKEN.")
    p.add_argument(
        "--link-mode",
        choices=("hardlink", "copy", "symlink"),
        default="hardlink",
        help="How to stage files into the namespaced tree. hardlink falls back to copy across filesystems.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise SystemExit("Install huggingface_hub first: pip install -U huggingface_hub hf_transfer") from e

    data_root = args.data_root.expanduser().resolve()
    download_root = args.download_root.expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    download_root.mkdir(parents=True, exist_ok=True)
    token = args.hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

    repos = args.repo_id or DEFAULT_REPOS
    total_staged = 0
    total_skipped = 0

    for repo_id in repos:
        safe = _safe_repo(repo_id)
        local_repo = download_root / safe
        print(f"\n=== {repo_id} -> namespace {safe} ===", flush=True)
        snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            revision=args.revision,
            local_dir=str(local_repo),
            allow_patterns=ALLOW_PATTERNS,
            token=token,
            max_workers=max(1, int(args.max_workers)),
        )
        for media_dir in MEDIA_DIRS:
            src = local_repo / media_dir
            dst = data_root / media_dir / safe
            staged, skipped = _stage_tree(src, dst, mode=args.link_mode)
            total_staged += staged
            total_skipped += skipped
            if src.is_dir():
                print(f"  {media_dir}: staged={staged:,}, already_present={skipped:,} -> {dst}", flush=True)
            else:
                print(f"  {media_dir}: not present in repo", flush=True)

    print(f"\nDone. staged={total_staged:,}, already_present={total_skipped:,}", flush=True)
    print(f"Data root: {data_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
