#!/usr/bin/env python3
"""
E2E convenience runner for metadata-first sat-bbox procedural SFT.

Wraps the same pipeline as ``build_sat_bbox_metadata_sft.py`` (JSONL + sidecars),
uses repo-relative defaults for a quick smoke run, prints build stats, then
pretty-prints every emitted row from ``out-dir/data/*.jsonl``.
"""

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
    write_split_jsonl_and_sidecars,
)


def _parse_task_mix(s: str) -> frozenset[str]:
    parts = {p.strip().lower() for p in s.split(",") if p.strip()}
    return frozenset(parts) if parts else frozenset({"all"})


def _parse_profiles(s: str) -> tuple[str, ...]:
    parts = tuple(p.strip() for p in s.split(",") if p.strip())
    return parts if parts else PRODUCTION_ANALYSIS_PROFILES


def _iter_jsonl_rows(data_dir: Path) -> list[tuple[str, int, dict[str, object]]]:
    """Return (split_name, line_index, row_obj) for all non-empty lines in data/*.jsonl."""
    out: list[tuple[str, int, dict[str, object]]] = []
    if not data_dir.is_dir():
        return out
    for path in sorted(data_dir.glob("*.jsonl")):
        split_name = path.stem
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            out.append((split_name, i, json.loads(line)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dataset-root",
        type=Path,
        default=REPO_ROOT / "data" / "scripts" / "tests" / "fixtures" / "sat_bbox_sft_mini",
        help="Dataset root (default: sat_bbox_sft_mini fixture under this repo).",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "tmp_e2e_sat_bbox_metadata_sft",
        help="Output dataset root (default: tmp_e2e_sat_bbox_metadata_sft under repo root).",
    )
    ap.add_argument("--max-rows", type=int, default=5, help="Cap total emitted rows (default: 5).")
    ap.add_argument(
        "--split",
        choices=("all", "train", "validation", "test"),
        default="all",
        help="Only emit rows for this split label.",
    )
    ap.add_argument(
        "--task-mix",
        default="production_analysis",
        help="Comma list: production_analysis,caption,grounding,per_class,absence,cross_view,all.",
    )
    ap.add_argument(
        "--analysis-profiles",
        default=",".join(PRODUCTION_ANALYSIS_PROFILES),
        help="Comma list of production profiles to emit for production_analysis rows.",
    )
    ap.add_argument(
        "--include-mapbox-context",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    ap.add_argument(
        "--require-local-images",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    ap.add_argument("--max-prompt-chars", type=int, default=16_000)
    ap.add_argument(
        "--no-print-rows",
        action="store_true",
        help="Only print JSON stats; do not pretty-print emitted JSONL rows.",
    )
    args = ap.parse_args()

    dataset_root = args.dataset_root.resolve()
    out_dir = args.out_dir.resolve()
    if not dataset_root.is_dir():
        print(f"error: dataset-root is not a directory: {dataset_root}", file=sys.stderr)
        return 2

    cfg = SatBBoxMetadataSftConfig(
        dataset_root=dataset_root,
        split_filter=args.split,
        max_rows=max(0, int(args.max_rows)),
        task_mix=_parse_task_mix(args.task_mix),
        analysis_profiles=_parse_profiles(args.analysis_profiles),
        include_mapbox_context=bool(args.include_mapbox_context),
        require_local_images=bool(args.require_local_images),
        max_prompt_chars=int(args.max_prompt_chars),
    )
    rows, stats = run_metadata_sft_build(cfg)
    write_split_jsonl_and_sidecars(rows, out_dir, source_root=dataset_root)

    print("=== build summary ===", flush=True)
    print(json.dumps(stats.summary(), indent=2, ensure_ascii=False), flush=True)

    if args.no_print_rows:
        print(f"\nWrote: {out_dir / 'data'}", flush=True)
        return 0

    data_dir = out_dir / "data"
    loaded = _iter_jsonl_rows(data_dir)
    print("\n=== emitted rows (pretty) ===", flush=True)
    for split_name, line_no, row in loaded:
        print(f"\n--- {split_name}.jsonl line {line_no} ---", flush=True)
        print(json.dumps(row, indent=2, ensure_ascii=False), flush=True)

    print(f"\nDone. Output root: {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
