#!/usr/bin/env python3
"""
Fail-fast check that image paths referenced in a Parquet mix exist under ``image_root``.

Shards may have **different Parquet schemas** (e.g. main corpus vs Firewatch ``regions`` /
different ``metadata``). This tool reads each file separately so Hugging Face does not try
to cast everything to one union schema.

Use **before** ``run_sat_vl_sft_e2e.py`` / LEAP so missing Hub downloads surface immediately.

Example::

  python train/verify_vlm_mix_assets.py \\
    --mix-dir /data/nutonic/vlm_mix_parquet \\
    --image-root /data/nutonic/sat-vl-sft-training-ready-v1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Same conversational aliases as LEAP ``normalize_vlm_sft`` (validate_loader).
_CONVERSATION_COLUMNS = ("messages", "conversation", "conversations", "chat", "dialogue")


def _top_level_parquet_columns(path: Path, pf: object) -> list[str]:
    """Top-level field names (not flattened leaf names). ``ParquetFile.schema.names`` can list leaves."""
    sa = getattr(pf, "schema_arrow", None)
    if sa is not None:
        return list(sa.names)
    import pyarrow.parquet as pq

    return list(pq.read_schema(path).names)


def _pick_conversation_column(column_names: list[str]) -> str | None:
    name_set = set(column_names)
    for cand in _CONVERSATION_COLUMNS:
        if cand in name_set:
            return cand
    return None


def _metadata_extra_rel_paths(row: dict) -> list[str]:
    """Paths stored on ``metadata`` (training-ready rows) that may not repeat every image in ``messages``."""
    out: list[str] = []
    meta = row.get("metadata")
    if not isinstance(meta, dict):
        return out
    aip = meta.get("analysis_image_path")
    if isinstance(aip, str) and aip and not aip.startswith(("http://", "https://", "/")):
        out.append(aip)
    ips = meta.get("image_paths")
    if isinstance(ips, list):
        for p in ips:
            if isinstance(p, str) and p and not p.startswith(("http://", "https://", "/")):
                out.append(p)
    return out


def _message_image_rel_paths(row: dict) -> list[str]:
    out: list[str] = []
    messages = row.get("messages")
    if messages is None:
        return out
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except json.JSONDecodeError:
            return out
    if not isinstance(messages, list):
        return out
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image":
                continue
            image = part.get("image")
            if not isinstance(image, str):
                continue
            if image.startswith(("http://", "https://", "/")):
                continue
            out.append(image)
    return out


def _all_image_rel_paths_for_row(row: dict) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for rel in _message_image_rel_paths(row) + _metadata_extra_rel_paths(row):
        if rel in seen:
            continue
        seen.add(rel)
        ordered.append(rel)
    return ordered


def _group_missing_roots(rel_under_root: list[str], *, max_groups: int = 12) -> list[tuple[str, int]]:
    """Group relative paths by top bucket (e.g. ``images/NuTonic__sat-bbox-metadata-sft-v1``)."""
    counts: dict[str, int] = {}
    for rel in rel_under_root:
        rel = rel.replace("\\", "/").strip()
        parts = [p for p in rel.split("/") if p]
        if len(parts) >= 2:
            key = f"{parts[0]}/{parts[1]}"
        elif parts:
            key = parts[0]
        else:
            key = "(empty)"
        counts[key] = counts.get(key, 0) + 1
    items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return items[:max_groups]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--mix-dir", type=Path, required=True, help="Directory of *.parquet mix shards.")
    p.add_argument("--image-root", type=Path, required=True, help="Dataset root (contains images/, etc.).")
    p.add_argument("--max-rows", type=int, default=500, help="Max table rows to scan from the mix.")
    p.add_argument(
        "--max-missing-report",
        type=int,
        default=24,
        help="Stop after collecting this many missing files (avoids huge stderr when whole subtrees are absent).",
    )
    p.add_argument(
        "--include-metadata-paths",
        action="store_true",
        help="Also require ``metadata.image_paths`` and ``metadata.analysis_image_path`` when present.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mix_dir = args.mix_dir.expanduser().resolve()
    root = args.image_root.expanduser().resolve()

    if not mix_dir.is_dir():
        print(f"Mix directory not found: {mix_dir}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"image_root not found: {root}", file=sys.stderr)
        return 2

    parquets = sorted(mix_dir.glob("*.parquet"))
    if not parquets:
        print(f"No *.parquet under {mix_dir}", file=sys.stderr)
        return 2

    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("Install pyarrow: pip install pyarrow", file=sys.stderr)
        return 2

    max_rows = max(0, int(args.max_rows))
    max_missing = max(1, int(args.max_missing_report))
    missing: list[str] = []
    missing_rel: list[str] = []
    checked_paths: set[str] = set()
    rows_scanned = 0

    def _paths_for_row(row_dict: dict) -> list[str]:
        if args.include_metadata_paths:
            return _all_image_rel_paths_for_row(row_dict)
        return _message_image_rel_paths(row_dict)

    def _consume_row(row_dict: dict) -> bool:
        """Return True if caller should stop scanning (missing cap hit)."""
        nonlocal missing, missing_rel, rows_scanned
        for rel in _paths_for_row(row_dict):
            if len(missing) >= max_missing:
                return True
            abs_path = root / rel
            key = str(abs_path)
            if key in checked_paths:
                continue
            checked_paths.add(key)
            if not abs_path.is_file():
                missing.append(key)
                missing_rel.append(rel.replace("\\", "/"))
            if len(missing) >= max_missing:
                rows_scanned += 1
                return True
        rows_scanned += 1
        return False

    for path in parquets:
        if rows_scanned >= max_rows:
            break
        try:
            pf = pq.ParquetFile(path)
        except Exception as e:
            print(f"Warning: cannot open {path.name}: {e}", file=sys.stderr)
            continue

        column_names = _top_level_parquet_columns(path, pf)
        msg_col = _pick_conversation_column(column_names)
        if msg_col is None:
            print(
                f"Warning: no conversational column {list(_CONVERSATION_COLUMNS)} in {path.name}; "
                f"have {column_names[:12]}{'...' if len(column_names) > 12 else ''}; skipping.",
                file=sys.stderr,
            )
            continue

        meta_col = "metadata" if "metadata" in column_names and args.include_metadata_paths else None
        read_cols = [msg_col] + ([meta_col] if meta_col else [])
        stop_mix = False
        for batch in pf.iter_batches(columns=read_cols, batch_size=2048):
            if rows_scanned >= max_rows or stop_mix:
                break
            col_msg = batch.column(0)
            col_meta = batch.column(1) if meta_col else None
            for i in range(batch.num_rows):
                if rows_scanned >= max_rows:
                    stop_mix = True
                    break
                row_d: dict = {"messages": col_msg[i].as_py()}
                if col_meta is not None:
                    row_d["metadata"] = col_meta[i].as_py()
                if _consume_row(row_d):
                    stop_mix = True
                    break
            if stop_mix or len(missing) >= max_missing:
                stop_mix = True
                break
        if stop_mix or len(missing) >= max_missing:
            break

    print(
        f"Scanned {rows_scanned:,} row(s) from {len(parquets)} shard(s); "
        f"{len(checked_paths):,} unique relative image path(s) checked.",
        flush=True,
    )

    if not missing:
        print("All checked image paths exist under image_root.", flush=True)
        return 0

    groups = _group_missing_roots(missing_rel)
    cap_note = f" (stopped at --max-missing-report={max_missing})" if len(missing) >= max_missing else ""
    print(f"Missing files{cap_note}: {len(missing)} total; grouped by subtree:", file=sys.stderr)
    for g, n in groups:
        print(f"  {n:>5}  under …/{g}/", file=sys.stderr)
    print("Examples (absolute):", file=sys.stderr)
    for m in missing[: min(12, len(missing))]:
        print(f"  {m}", file=sys.stderr)
    meta_hint = (
        "\nYou used --include-metadata-paths; omit it if you only need paths referenced inside chat messages.\n"
        if args.include_metadata_paths
        else ""
    )
    print(
        "\nThese paths must exist under --image-root (training loads the same files). "
        "Finish mirroring the Hub dataset:\n"
        f"  python train/download_lfm_vl_training_dataset.py --out-dir {root}\n"
        "Use HF_HUB_ENABLE_HF_TRANSFER=1 with hf_transfer for faster pulls. "
        "If the downloader previously stopped early or used a partial snapshot, re-run until it completes.\n"
        f"{meta_hint}"
        "To run LEAP anyway without this gate (smoke / incomplete disk): "
        "python train/run_sat_vl_sft_e2e.py ... --no-verify-mix-assets\n"
        "If your mix references assets outside NuTonic/sat-vl-sft-training-ready-v1, merge those trees into the same root.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
