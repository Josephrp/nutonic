#!/usr/bin/env python3
"""
Stage a self-contained Docker Space folder and upload to Hugging Face Hub.

Usage (from repository root):
  export HF_TOKEN=...
  python tools/hf_deploy/upload_space.py --service lfm_vl_hint --repo-id Tonic/nutonic-lfm-vl-streetview

Requires: huggingface_hub (install from tools/hf_deploy/requirements.txt).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SERVICE_SPECS: dict[str, dict[str, Path | str]] = {
    "lfm_vl_hint": {
        "source_dir": REPO_ROOT / "inference" / "lfm_vl_hint_service",
        "readme_template": REPO_ROOT / "tools" / "hf_deploy" / "templates" / "readme_lfm_vl_hint.md",
        "dockerignore": None,
    },
    "terramind_tim": {
        "source_dir": REPO_ROOT / "inference" / "terramind_tim_local",
        "readme_template": REPO_ROOT / "tools" / "hf_deploy" / "templates" / "readme_terramind_tim.md",
        "dockerignore": None,
    },
    "game_server": {
        "source_dir": REPO_ROOT / "server",
        "readme_template": REPO_ROOT / "tools" / "hf_deploy" / "templates" / "readme_game_server.md",
        "dockerignore": None,
    },
    "pro_materialization": {
        "source_dir": REPO_ROOT / "inference" / "pro_materialization_service",
        "readme_template": REPO_ROOT / "tools" / "hf_deploy" / "templates" / "readme_pro_materialization.md",
        "dockerignore": None,
    },
}


def _stage_service(service: str) -> Path:
    spec = SERVICE_SPECS[service]
    src = Path(spec["source_dir"])
    tmpl = Path(spec["readme_template"])
    if not src.is_dir():
        raise FileNotFoundError(f"Missing service directory: {src}")
    if not tmpl.is_file():
        raise FileNotFoundError(f"Missing README template: {tmpl}")

    stage = Path(tempfile.mkdtemp(prefix=f"hf_space_{service}_"))

    dockerfile = src / "Dockerfile"
    if not dockerfile.is_file():
        raise FileNotFoundError(f"Missing Dockerfile in {src}")

    shutil.copy2(dockerfile, stage / "Dockerfile")
    shutil.copy2(src / "pyproject.toml", stage / "pyproject.toml")
    pkg_readme = src / "README.md"
    if pkg_readme.is_file():
        shutil.copy2(pkg_readme, stage / "README.package.md")

    shutil.copytree(src / "src", stage / "src", dirs_exist_ok=True)
    shutil.copy2(tmpl, stage / "README.md")
    return stage


def _upload(repo_id: str, folder: Path, token: str, commit_message: str) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="space", exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        folder_path=str(folder),
        repo_type="space",
        commit_message=commit_message,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Upload a NU:TONIC Python service to a Hugging Face Docker Space.")
    p.add_argument(
        "--service",
        choices=list(SERVICE_SPECS.keys()),
        required=True,
        help="Which monorepo service to stage.",
    )
    p.add_argument(
        "--repo-id",
        required=True,
        help="Target Space repo id, e.g. Tonic/nutonic-lfm-vl-streetview or NuTonic/nutonic-game-server",
    )
    p.add_argument(
        "--token-env",
        default="HF_TOKEN",
        help="Environment variable name holding a write token (default: HF_TOKEN).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only stage to a temp directory; print path and skip upload.",
    )
    args = p.parse_args()

    token = os.environ.get(args.token_env, "").strip()
    if not token and not args.dry_run:
        print(f"Missing {args.token_env} in environment.", file=sys.stderr)
        return 2

    stage = _stage_service(args.service)
    sha = os.environ.get("GITHUB_SHA", "local")[:12]
    msg = f"ci: deploy {args.service} ({sha})"

    try:
        if args.dry_run:
            print(f"Staged {args.service} -> {stage}")
            return 0
        _upload(args.repo_id, stage, token, msg)
        print(f"Uploaded {args.service} -> https://huggingface.co/spaces/{args.repo_id}")
        return 0
    finally:
        if not args.dry_run:
            shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
