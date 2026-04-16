#!/usr/bin/env python3
"""
Build and push NU:TONIC Hugging Face Job Docker images (sv-lfm, llm, TiM).

Run from the **repository root** with Docker logged in to your registry (``docker login``).

**Git Bash on Windows:** use Unix-style paths, e.g. ``cd /c/Users/MeMyself/nutonic`` (``cd c:\\Users\\...`` is not valid in bash).

Environment (optional):
  ``NUTONIC_DOCKER_NAMESPACE`` — default for ``--namespace`` (Docker Hub user or org).

Example::

    python tools/hf_jobs/build_and_push_images.py --namespace myuser --tag 2026-04-16
    python tools/hf_jobs/build_and_push_images.py --namespace myuser --tag $(git rev-parse --short HEAD) --dry-run
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], *, dry_run: bool) -> None:
    line = " ".join(cmd)
    print("+", line, flush=True)
    if dry_run:
        return
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build and push hydration Job images to Docker Hub (or compatible registry).")
    p.add_argument(
        "--namespace",
        default=os.environ.get("NUTONIC_DOCKER_NAMESPACE", "").strip(),
        help="Image namespace (Docker Hub username or org). Default: env NUTONIC_DOCKER_NAMESPACE.",
    )
    p.add_argument("--tag", required=True, help="Image tag (e.g. date or git short SHA).")
    p.add_argument(
        "--registry",
        default=os.environ.get("NUTONIC_DOCKER_REGISTRY", "docker.io").strip(),
        help="Registry host (default docker.io). Image becomes REGISTRY/NAMESPACE/NAME:TAG when REGISTRY is not docker.io.",
    )
    p.add_argument("--dry-run", action="store_true", help="Print docker commands only.")
    p.add_argument("--no-push", action="store_true", help="Build but do not push.")
    args = p.parse_args(argv)

    if not args.namespace:
        print("Missing --namespace or NUTONIC_DOCKER_NAMESPACE", file=sys.stderr)
        return 2

    reg = args.registry.rstrip("/")
    if reg in ("", "docker.io"):
        prefix = f"{args.namespace}"
    else:
        prefix = f"{reg}/{args.namespace}"

    images: list[tuple[str, Path]] = [
        ("nutonic-hydration-sv-lfm", REPO_ROOT / "tools" / "hf_jobs" / "Dockerfile.hydration"),
        ("nutonic-hydration-llm", REPO_ROOT / "tools" / "hf_jobs" / "Dockerfile.hydration-llm"),
        ("nutonic-hydration-tim", REPO_ROOT / "tools" / "hf_jobs" / "Dockerfile.hydration-tim"),
    ]

    for name, dockerfile in images:
        tag_full = f"{prefix}/{name}:{args.tag}"
        dockerfile_rel = dockerfile.relative_to(REPO_ROOT).as_posix()
        _run(
            [
                "docker",
                "build",
                "-f",
                dockerfile_rel,
                "-t",
                tag_full,
                ".",
            ],
            dry_run=args.dry_run,
        )
        if not args.no_push:
            _run(["docker", "push", tag_full], dry_run=args.dry_run)

    print("\nSet in .env for run_full_hydration.py:", flush=True)
    print(f"  NUTONIC_HYDRATION_SV_LFM_IMAGE={prefix}/nutonic-hydration-sv-lfm:{args.tag}", flush=True)
    print(f"  NUTONIC_HYDRATION_LLM_IMAGE={prefix}/nutonic-hydration-llm:{args.tag}", flush=True)
    print(f"  NUTONIC_HYDRATION_TIM_IMAGE={prefix}/nutonic-hydration-tim:{args.tag}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
