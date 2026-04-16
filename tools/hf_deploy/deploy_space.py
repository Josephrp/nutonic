#!/usr/bin/env python3
"""
Stage a Docker Space folder, deploy with the **hf** CLI (auth, repos create, upload),
then sync Space **variables** / **secrets** / **hardware** via Hugging Face Hub APIs.

The Hub exposes no `hf spaces secret set` today; secret/variable *updates* use
``HfApi.add_space_secret`` / ``add_space_variable`` (same package as the ``hf`` binary).

Usage (repo root):
  export HF_TOKEN=...
  python tools/hf_deploy/deploy_space.py --service lfm_vl_hint --repo-id Tonic/nutonic-lfm-vl-streetview

Requires: ``pip install -r tools/hf_deploy/requirements.txt`` (installs ``hf`` entry point).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = REPO_ROOT / "tools" / "hf_deploy" / "profiles"

SERVICE_SPECS: dict[str, dict[str, Path]] = {
    "lfm_vl_hint": {
        "source_dir": REPO_ROOT / "inference" / "lfm_vl_hint_service",
        "readme_template": REPO_ROOT / "tools" / "hf_deploy" / "templates" / "readme_lfm_vl_hint.md",
    },
    "terramind_tim": {
        "source_dir": REPO_ROOT / "inference" / "terramind_tim_local",
        "readme_template": REPO_ROOT / "tools" / "hf_deploy" / "templates" / "readme_terramind_tim.md",
    },
    "game_server": {
        "source_dir": REPO_ROOT / "server",
        "readme_template": REPO_ROOT / "tools" / "hf_deploy" / "templates" / "readme_game_server.md",
    },
    "pro_materialization": {
        "source_dir": REPO_ROOT / "inference" / "pro_materialization_service",
        "readme_template": REPO_ROOT / "tools" / "hf_deploy" / "templates" / "readme_pro_materialization.md",
    },
}

SERVICE_PROFILE = {
    "lfm_vl_hint": PROFILES_DIR / "lfm_vl_hint.yaml",
    "terramind_tim": PROFILES_DIR / "terramind_tim.yaml",
    "game_server": PROFILES_DIR / "game_server.yaml",
    "pro_materialization": PROFILES_DIR / "pro_materialization.yaml",
}


def _stage_service(service: str) -> Path:
    spec = SERVICE_SPECS[service]
    src = spec["source_dir"]
    tmpl = spec["readme_template"]
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


def _hf_bin() -> str:
    hf = shutil.which("hf")
    if not hf:
        print(
            "The `hf` CLI was not found on PATH. Install a recent huggingface_hub:\n"
            "  pip install -r tools/hf_deploy/requirements.txt",
            file=sys.stderr,
        )
        sys.exit(2)
    return hf


def _run_hf(args: list[str], *, token: str, dry_run: bool) -> None:
    env = {**os.environ, "HF_TOKEN": token}
    cmd = [_hf_bin(), *args]
    if dry_run:
        print("[dry-run] ", " ".join(cmd), file=sys.stderr)
        return
    subprocess.run(cmd, check=True, env=env)


def _load_profile(service: str) -> dict[str, Any]:
    path = SERVICE_PROFILE[service]
    if not path.is_file():
        return {}
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _sync_space_runtime(repo_id: str, token: str, service: str, *, dry_run: bool, skip_runtime: bool) -> None:
    if dry_run or skip_runtime:
        return

    from huggingface_hub import HfApi

    profile = _load_profile(service)
    api = HfApi(token=token)

    for key, value in (profile.get("variables") or {}).items():
        if not isinstance(key, str) or value is None:
            continue
        api.add_space_variable(repo_id, key, str(value), token=token)

    secrets_map = profile.get("secrets") or {}
    if isinstance(secrets_map, dict):
        for hf_key, env_name in secrets_map.items():
            if not isinstance(hf_key, str) or not isinstance(env_name, str):
                continue
            val = os.environ.get(env_name, "").strip()
            if not val:
                continue
            api.add_space_secret(repo_id, hf_key, val, token=token)

    hw = profile.get("space_hardware")
    if isinstance(hw, str) and hw.strip():
        sleep_raw = profile.get("sleep_time_seconds")
        sleep_time: int | None
        if sleep_raw is None or sleep_raw == "":
            sleep_time = None
        else:
            try:
                sleep_time = int(sleep_raw)
            except (TypeError, ValueError):
                sleep_time = None
        try:
            api.request_space_hardware(repo_id, hardware=hw.strip(), token=token, sleep_time=sleep_time)
        except Exception as exc:
            print(
                f"Warning: request_space_hardware({hw!r}) failed ({exc}). "
                "Set hardware in the Space UI or ensure billing/grants allow this flavor.",
                file=sys.stderr,
            )


def _deploy_with_hf(repo_id: str, stage: Path, token: str, commit_message: str, *, dry_run: bool) -> None:
    _run_hf(["auth", "login", "--token", token], token=token, dry_run=dry_run)

    _run_hf(
        [
            "repos",
            "create",
            repo_id,
            "--repo-type",
            "space",
            "--space-sdk",
            "docker",
            "--exist-ok",
        ],
        token=token,
        dry_run=dry_run,
    )

    _run_hf(
        [
            "upload",
            repo_id,
            str(stage),
            ".",
            "--repo-type",
            "space",
            "--delete",
            "*",
            "--commit-message",
            commit_message,
        ],
        token=token,
        dry_run=dry_run,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Deploy a NU:TONIC service to a Hugging Face Docker Space via `hf`.")
    p.add_argument("--service", choices=list(SERVICE_SPECS.keys()), required=True)
    p.add_argument("--repo-id", required=True, help="e.g. Tonic/nutonic-lfm-vl-streetview")
    p.add_argument("--token-env", default="HF_TOKEN", help="Env var holding the Hub write token.")
    p.add_argument("--dry-run", action="store_true", help="Print `hf` commands; stage only; skip Hub writes.")
    p.add_argument(
        "--skip-runtime-sync",
        action="store_true",
        help="Skip variables/secrets/hardware API sync (upload only).",
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
            print(f"Staged {args.service} -> {stage}", file=sys.stderr)
        tok = token or "dry-run-no-token"
        _deploy_with_hf(args.repo_id, stage, tok, msg, dry_run=args.dry_run)
        _sync_space_runtime(
            args.repo_id,
            tok,
            args.service,
            dry_run=args.dry_run,
            skip_runtime=args.skip_runtime_sync,
        )
        if not args.dry_run:
            print(f"Deployed {args.service} -> https://huggingface.co/spaces/{args.repo_id}")
        return 0
    finally:
        if not args.dry_run:
            shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
