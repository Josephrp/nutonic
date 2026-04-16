#!/usr/bin/env python3
"""
Download a hydration output snapshot from a Hugging Face **dataset** into ``data/cache/``.

Jobs (or local runs) should ``upload_folder`` / commit artifacts under e.g. ``runs/<content_version>/``.
This script uses ``snapshot_download`` so you can **delete** large local ``data/downloads/geoguessr_*``
trees after the first successful run and re-sync from Hub only when needed.

Requires: ``pip install huggingface_hub`` and read token (``HF_API_READ`` or ``HUGGING_FACE_HUB_TOKEN``).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from hf_hub_tokens import apply_hf_read_token


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if os.environ.get("NUTONIC_NO_DOTENV") == "1":
        return
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv()


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()

    p = argparse.ArgumentParser(description="Download hydration artifacts from a HF dataset.")
    p.add_argument(
        "--repo-id",
        default=os.environ.get("NUTONIC_HYDRATION_OUTPUT_DATASET", "NuTonic/nutonic-hydration-cache"),
        help="Dataset repo containing uploaded run folders (default env NUTONIC_HYDRATION_OUTPUT_DATASET or NuTonic/nutonic-hydration-cache).",
    )
    p.add_argument(
        "--local-dir",
        type=Path,
        default=None,
        help="Destination directory (default: data/cache/hf_downloads/<repo sanitized>).",
    )
    p.add_argument(
        "--allow-patterns",
        nargs="*",
        default=None,
        help="Optional glob patterns (default: entire repo snapshot).",
    )
    p.add_argument("--revision", default=None)
    args = p.parse_args(argv)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("pip install huggingface_hub", file=sys.stderr)
        return 2

    apply_hf_read_token()
    if not (os.environ.get("HUGGING_FACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")):
        print(
            "No Hub read token: set HF_API_READ or HUGGING_FACE_HUB_TOKEN or HF_TOKEN",
            file=sys.stderr,
        )
        return 3

    dest = args.local_dir
    if dest is None:
        safe = args.repo_id.replace("/", "__")
        dest = REPO_ROOT / "data" / "cache" / "hf_downloads" / safe
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    try:
        path = snapshot_download(
            repo_id=args.repo_id,
            repo_type="dataset",
            local_dir=str(dest),
            revision=args.revision,
            allow_patterns=list(args.allow_patterns) if args.allow_patterns else None,
        )
    except Exception as e:  # noqa: BLE001
        print(f"snapshot_download failed: {e}", file=sys.stderr)
        return 4

    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
