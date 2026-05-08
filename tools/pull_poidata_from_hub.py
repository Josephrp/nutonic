#!/usr/bin/env python3
"""
Sync POI folder trees from the Hugging Face Dataset ``NuTonic/poidata`` into ``data/downloads/``.

The Hub mirror may not match a local ``Image``-feature Parquet layout; this tool uses
``snapshot_download`` (file-based tree) so ``geoguessr_poi_12`` / ``geoguessr_poi_120`` paths
work with ``catalog_import_poi.py`` unchanged.

Requires: ``pip install huggingface_hub`` and read auth for private datasets
(``HF_API_READ`` or ``HUGGING_FACE_HUB_TOKEN`` / ``HF_TOKEN``; optional for public reads).

Usage::

    python tools/pull_poidata_from_hub.py --local-dir data/downloads
    python tools/pull_poidata_from_hub.py --local-dir data/downloads --allow-patterns 'geoguessr_poi_12/*' 'geoguessr_poi_120/*'
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
    apply_hf_read_token()
    p = argparse.ArgumentParser(
        description="Download NuTonic/poidata (or another dataset) snapshot for geoguessr_poi_* trees.",
    )
    p.add_argument(
        "--repo-id",
        default="NuTonic/poidata",
        help="Hugging Face dataset repo id (default: NuTonic/poidata).",
    )
    p.add_argument(
        "--local-dir",
        type=Path,
        required=True,
        help="Destination directory (e.g. data/downloads). POI roots appear under <local-dir>/geoguessr_poi_12 etc.",
    )
    p.add_argument(
        "--revision",
        default=None,
        help="Optional git revision (branch / tag / commit).",
    )
    p.add_argument(
        "--allow-patterns",
        nargs="*",
        default=("geoguessr_poi_12/**", "geoguessr_poi_120/**"),
        help="Glob patterns passed to snapshot_download (default: both GeoGuessr POI trees).",
    )
    p.add_argument(
        "--ignore-patterns",
        nargs="*",
        default=None,
        help="Optional ignore glob patterns for snapshot_download.",
    )
    p.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Parallel download workers for snapshot_download.",
    )
    args = p.parse_args(argv)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Install huggingface_hub: pip install huggingface_hub", file=sys.stderr)
        return 2

    dest = args.local_dir.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    try:
        path = snapshot_download(
            repo_id=args.repo_id,
            repo_type="dataset",
            local_dir=str(dest),
            revision=args.revision,
            allow_patterns=list(args.allow_patterns) if args.allow_patterns else None,
            ignore_patterns=list(args.ignore_patterns) if args.ignore_patterns else None,
            max_workers=args.max_workers,
        )
    except OSError as e:
        print(f"snapshot_download I/O error: {e}", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 — hub errors vary by version
        print(f"snapshot_download failed: {e}", file=sys.stderr)
        return 4

    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
