#!/usr/bin/env python3
"""Build high-quality procedural VLM SFT rows from sat-bbox metadata sidecars (no Mapbox fetch)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lfm_vl_sft_dataset.sat_bbox_metadata_sft import (  # noqa: E402
    PRODUCTION_ANALYSIS_PROFILES,
    SatBBoxMetadataSftConfig,
    run_metadata_sft_build,
    run_metadata_sft_build_streaming,
    write_split_jsonl_and_sidecars,
)


def _parse_task_mix(s: str) -> frozenset[str]:
    parts = {p.strip().lower() for p in s.split(",") if p.strip()}
    return frozenset(parts) if parts else frozenset({"all"})


def _parse_profiles(s: str) -> tuple[str, ...]:
    parts = tuple(p.strip() for p in s.split(",") if p.strip())
    return parts if parts else PRODUCTION_ANALYSIS_PROFILES


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dataset-root",
        type=Path,
        required=True,
        help="Dataset root containing data/*.jsonl, metadata/s*/, images/, optional mapbox_stills/.",
    )
    ap.add_argument(
        "--split",
        choices=("all", "train", "validation", "test"),
        default="all",
        help="Emit only rows assigned to this split (metadata ``split`` or deterministic hash).",
    )
    ap.add_argument("--out-dir", type=Path, required=True, help="Output dataset root (data/*.jsonl + sidecars).")
    ap.add_argument("--max-rows", type=int, default=0, help="Cap total emitted rows (0 = no cap).")
    ap.add_argument(
        "--task-mix",
        default="all",
        help="Comma list: production_analysis,caption,grounding,per_class,absence,cross_view,all "
        "(per_class expands to per-label grounding + class-focus).",
    )
    ap.add_argument(
        "--analysis-profiles",
        default=",".join(PRODUCTION_ANALYSIS_PROFILES),
        help="Comma list of production analysis profiles for production_analysis rows.",
    )
    ap.add_argument(
        "--include-mapbox-context",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Emit cross-view rows when mapbox_stills paths exist (default: on).",
    )
    ap.add_argument(
        "--require-local-images",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Drop rows when referenced image paths are missing under dataset-root (default: on).",
    )
    ap.add_argument("--max-prompt-chars", type=int, default=16_000)
    ap.add_argument(
        "--stream-to-disk",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Write rows incrementally (O(1) RAM vs row count). Strongly recommended for full-corpus runs.",
    )
    ap.add_argument(
        "--prefer-hardlink",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="When copying images from dataset-root, use hardlinks if same filesystem (instant, saves space).",
    )
    ap.add_argument(
        "--render-workers",
        type=int,
        default=1,
        help="Process pool size for procedural analysis PNGs (only with --stream-to-disk; default 1 = sequential).",
    )
    ap.add_argument(
        "--copy-workers",
        type=int,
        default=1,
        help="Thread pool size for copying/linking source images per batch (only with --stream-to-disk; default 1).",
    )
    ap.add_argument(
        "--flush-batch-size",
        type=int,
        default=32,
        help="Rows per batch when using parallel render/copy (ignored when both worker counts are 1).",
    )
    args = ap.parse_args()

    cfg = SatBBoxMetadataSftConfig(
        dataset_root=args.dataset_root,
        split_filter=args.split,
        max_rows=max(0, int(args.max_rows)),
        task_mix=_parse_task_mix(args.task_mix),
        analysis_profiles=_parse_profiles(args.analysis_profiles),
        include_mapbox_context=bool(args.include_mapbox_context),
        require_local_images=bool(args.require_local_images),
        max_prompt_chars=int(args.max_prompt_chars),
    )
    src = args.dataset_root.resolve()
    if args.stream_to_disk:
        stats = run_metadata_sft_build_streaming(
            cfg,
            args.out_dir,
            source_root=src,
            copy_source_images=True,
            prefer_hardlink=bool(args.prefer_hardlink),
            render_workers=int(args.render_workers),
            copy_workers=int(args.copy_workers),
            flush_batch_size=int(args.flush_batch_size),
        )
    else:
        rows, stats = run_metadata_sft_build(cfg)
        write_split_jsonl_and_sidecars(
            rows,
            args.out_dir,
            source_root=src,
            prefer_hardlink=bool(args.prefer_hardlink),
        )
    summary = stats.summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
