#!/usr/bin/env python3
"""
Submit Hugging Face **Jobs** for cache hydration (Street View + LFM-VL) or TerraTorch TiM batches.

Local scripts (``tools/batch_streetview_hints.py``, ``inference/terramind_tim_local``) stay the source
of truth; this module only wraps ``huggingface_hub.run_job`` with sensible defaults (dataset volume,
flavors, dry-run).

Docs: ``tools/hf_jobs/README.md``

Requires: ``pip install -r tools/hf_jobs/requirements.txt`` and a **write**-capable Hub token
(``HF_API_WRITE`` preferred, or ``HF_TOKEN`` / ``huggingface-cli login``).

**Important:** ``run_job`` expects a **Docker Hub** image (or HF Space URL) that already contains the
repo, Python deps, and an entrypoint script. Build and push your image first; see README.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from hf_hub_tokens import apply_hf_tokens_for_hub


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if os.environ.get("NUTONIC_NO_DOTENV") == "1":
        return
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()


def _import_run_job():
    try:
        from huggingface_hub import SpaceHardware
        from huggingface_hub import Volume
        from huggingface_hub import run_job
    except ImportError as e:
        print(
            "Missing huggingface_hub (with Jobs API). Install: pip install -r tools/hf_jobs/requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(2) from e
    return run_job, SpaceHardware, Volume


def _resolve_flavor(SpaceHardware: type, name: str):
    slug = name.strip().lower().replace("_", "-")
    try:
        return SpaceHardware(slug)
    except ValueError:
        pass
    for member in SpaceHardware:
        if member.name.lower() == name.strip().lower().replace("-", "_"):
            return member
    raise SystemExit(
        f"Unknown --flavor {name!r}. Examples: cpu-basic, zero-a10g, a10g-small, t4-medium.",
    )


def _hub_job_token_for_secrets() -> str | None:
    """Token forwarded into the container (uploads / Hub reads)."""
    return (os.environ.get("HF_API_WRITE") or os.environ.get("HF_TOKEN") or "").strip() or None


def submit_hydration_job(
    *,
    docker_image: str,
    command: list[str],
    flavor_name: str,
    timeout: str,
    dataset_volume: str | None,
    dataset_mount_path: str,
    dataset_revision: str | None,
    env: dict[str, object],
    secrets: dict[str, str] | None,
    labels: dict[str, str] | None,
    dry_run: bool,
) -> object | None:
    """
    Call ``huggingface_hub.run_job``. Returns ``JobInfo`` when not dry-run, else ``None``.

    Caller must ensure Hub write auth (e.g. ``HF_API_WRITE``) before calling when ``dry_run`` is false.
    """
    run_job, SpaceHardware, Volume = _import_run_job()
    flavor = _resolve_flavor(SpaceHardware, flavor_name)

    volumes: list | None = None
    if dataset_volume:
        volumes = [
            Volume(
                type="dataset",
                source=dataset_volume,
                mount_path=dataset_mount_path,
                revision=dataset_revision,
                read_only=True,
            )
        ]

    if dry_run:
        print(
            json.dumps(
                {
                    "image": docker_image,
                    "command": command,
                    "flavor": str(flavor),
                    "env": env,
                    "secrets_keys": list(secrets.keys()) if secrets else [],
                    "volumes": [v.to_dict() for v in volumes] if volumes else [],
                    "timeout": timeout,
                    "labels": labels,
                },
                indent=2,
            )
        )
        return None

    return run_job(
        image=docker_image,
        command=command,
        env=env or None,
        secrets=secrets,
        flavor=flavor,
        volumes=volumes,
        timeout=timeout,
        labels=labels,
    )


def cmd_streetview_lfm(args: argparse.Namespace) -> int:
    env: dict[str, object] = {}
    if args.env_json:
        env = json.loads(Path(args.env_json).read_text(encoding="utf-8"))
    for kv in args.env or []:
        if "=" not in kv:
            print(f"Invalid --env {kv!r} (expected KEY=VAL)", file=sys.stderr)
            return 2
        k, _, v = kv.partition("=")
        env[k] = v

    secrets: dict[str, str] | None = None
    if args.secret_hf_token:
        tok = _hub_job_token_for_secrets()
        if not tok:
            print(
                "HF_API_WRITE or HF_TOKEN required in environment when using --secret-hf-token",
                file=sys.stderr,
            )
            return 2
        secrets = {"HF_TOKEN": tok}
    if args.secrets_json:
        raw = json.loads(Path(args.secrets_json).read_text(encoding="utf-8"))
        merge = {str(k): str(v) for k, v in raw.items()}
        secrets = {**secrets, **merge} if secrets else merge

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print(
            "Provide container argv after `--`, e.g. streetview-lfm ... -- /app/entrypoint.sh sv-lfm",
            file=sys.stderr,
        )
        return 2

    labels = json.loads(args.labels_json) if args.labels_json else None

    if not args.dry_run:
        apply_hf_tokens_for_hub(write=True)

    job = submit_hydration_job(
        docker_image=args.docker_image,
        command=command,
        flavor_name=args.flavor,
        timeout=args.timeout,
        dataset_volume=args.dataset_volume,
        dataset_mount_path=args.dataset_mount_path,
        dataset_revision=args.dataset_revision,
        env=env,
        secrets=secrets,
        labels=labels,
        dry_run=bool(args.dry_run),
    )
    if args.dry_run:
        return 0
    assert job is not None
    print(job.url)
    if getattr(args, "json_output", False):
        print(
            json.dumps(
                {
                    "id": job.id,
                    "url": job.url,
                    "namespace": job.owner.name,
                }
            )
        )
    return 0


def cmd_tim_s2(args: argparse.Namespace) -> int:
    """Same as streetview-lfm but documented defaults for TiM; reuses run_job."""
    return cmd_streetview_lfm(args)


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(description="Submit NU:TONIC hydration jobs to Hugging Face Jobs.")
    sub = p.add_subparsers(dest="which", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--docker-image", required=True, help="Docker Hub image (myuser/nutonic-hydration:tag).")
    common.add_argument(
        "--flavor",
        default="a10g_small",
        help="Hardware flavor enum name (A10G_SMALL) or raw slug (a10g-small). Default: a10g_small.",
    )
    common.add_argument("--timeout", default="6h", help="Job timeout (e.g. 6h, 360m).")
    common.add_argument("--dry-run", action="store_true", help="Print job spec JSON and exit.")
    common.add_argument("--dataset-volume", default="NuTonic/poidata", help="HF dataset id to mount read-only.")
    common.add_argument("--dataset-mount-path", default="/mnt/poidata", dest="dataset_mount_path")
    common.add_argument("--dataset-revision", default=None, dest="dataset_revision")
    common.add_argument("--no-dataset-volume", action="store_true", help="Do not mount NuTonic/poidata.")
    common.add_argument("--env", action="append", default=[], metavar="KEY=VAL", help="Repeatable env pairs.")
    common.add_argument("--env-json", type=Path, default=None, help="JSON object merged into environment.")
    common.add_argument(
        "--secret-hf-token",
        action="store_true",
        help="Pass HF_API_WRITE (else HF_TOKEN) from the environment into job secrets as HF_TOKEN.",
    )
    common.add_argument("--secrets-json", type=Path, default=None, help="JSON map of secret name -> value.")
    common.add_argument("--labels-json", type=str, default=None, help="Optional JSON object of job labels.")
    common.add_argument(
        "--json-output",
        action="store_true",
        help="After submit, print a second line of JSON with id, url, namespace (for orchestrators).",
    )

    p_sv = sub.add_parser("streetview-lfm", parents=[common], help="VLM Street View hint batch (GPU).")
    p_sv.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Container entrypoint + args (prefix with --). Example: -- /app/entrypoint.sh sv-lfm",
    )
    p_sv.set_defaults(func=cmd_streetview_lfm)

    p_tim = sub.add_parser("tim-s2", parents=[common], help="TerraTorch TiM S2 batch (GPU; mount poidata optional).")
    p_tim.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Container entrypoint + args (prefix with --). Example: -- /app/entrypoint.sh tim-s2",
    )
    p_tim.set_defaults(func=cmd_tim_s2)

    args = p.parse_args(argv)
    if getattr(args, "no_dataset_volume", False):
        args.dataset_volume = None

    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
