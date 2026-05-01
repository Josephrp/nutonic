#!/usr/bin/env python3
"""
Materialize a single-folder Parquet shard mix for LEAP ``vlm_sft`` local loading.

LEAP accepts one ``dataset.path`` that is either a Hugging Face hub id or a local
directory of ``*.parquet`` shards. This script concatenates:

* The main satellite SFT corpus (streamed so memory stays bounded), e.g. ~800k rows
* Each task hub (expected smaller), repeated ``--task-repeat`` times so ~5k combined
  tasks are not drowned out by main
* A tiny hub (e.g. Firewatch ~200 rows), repeated ``--small-repeat`` times so it
  still sees meaningful gradient mass next to main

Effective mix is still **main-heavy**; tune repeats using rough counts:
``task_share ≈ (task_rows × task_repeat) / (main_rows + tasks_effective + small_effective)``.

All rows are written as Parquet under ``--out-dir``. Training will shuffle globally
inside LEAP, so append order is not critical.

Requires: ``datasets``, ``pyarrow`` (installed with typical HF stacks).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterator

from datasets import Dataset, load_dataset


def _rows_from_hf(
    repo_id: str,
    *,
    subset: str | None,
    split: str,
    streaming: bool,
) -> Iterator[dict[str, Any]]:
    if subset:
        ds = load_dataset(repo_id, subset, split=split, streaming=streaming)
    else:
        ds = load_dataset(repo_id, split=split, streaming=streaming)
    for row in ds:
        yield dict(row)


def _flush_shard(out_dir: Path, prefix: str, shard_idx: int, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return shard_idx
    path = out_dir / f"{prefix}-{shard_idx:05d}.parquet"
    Dataset.from_list(rows).to_parquet(str(path))
    rows.clear()
    return shard_idx + 1


def _stream_main_to_shards(
    repo_id: str,
    out_dir: Path,
    *,
    subset: str | None,
    split: str,
    chunk_rows: int,
    prefix: str,
    max_rows: int | None,
) -> int:
    rows: list[dict[str, Any]] = []
    shard_idx = 0
    total = 0
    for row in _rows_from_hf(repo_id, subset=subset, split=split, streaming=True):
        rows.append(row)
        total += 1
        if len(rows) >= chunk_rows:
            shard_idx = _flush_shard(out_dir, prefix, shard_idx, rows)
        if max_rows is not None and total >= max_rows:
            break
    shard_idx = _flush_shard(out_dir, prefix, shard_idx, rows)
    return total


def _materialize_whole_split(
    repo_id: str,
    out_dir: Path,
    *,
    subset: str | None,
    split: str,
    chunk_rows: int,
    prefix: str,
    repeat: int = 1,
) -> int:
    if subset:
        ds = load_dataset(repo_id, subset, split=split, streaming=False)
    else:
        ds = load_dataset(repo_id, split=split, streaming=False)
    rows: list[dict[str, Any]] = []
    shard_idx = 0
    total = 0
    for _ in range(max(1, repeat)):
        for row in ds:
            rows.append(dict(row))
            total += 1
            if len(rows) >= chunk_rows:
                shard_idx = _flush_shard(out_dir, prefix, shard_idx, rows)
    shard_idx = _flush_shard(out_dir, prefix, shard_idx, rows)
    return total


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--out-dir", type=Path, required=True, help="Directory for *.parquet shards (must be empty or --overwrite).")
    p.add_argument("--overwrite", action="store_true", help="Delete existing *.parquet under out-dir before writing.")
    p.add_argument("--subset", default=None, help="HF dataset config/subset name when required.")
    p.add_argument("--split", default="train", help="Split to read from each hub dataset.")
    p.add_argument("--chunk-rows", type=int, default=4096, help="Rows per Parquet shard.")
    p.add_argument("--main-repo-id", default="NuTonic/sat-vl-sft-training-ready-v1")
    p.add_argument("--main-max-rows", type=int, default=None, help="Cap main corpus rows (smoke tests).")
    p.add_argument(
        "--task-repo-id",
        action="append",
        default=[
            "NuTonic/brief-composer-sft-v1",
            "NuTonic/oceanscout-sft-v1",
            "NuTonic/floodpulse-sft-v1",
            "NuTonic/landshift-sft-v1",
        ],
        help="Additional hub dataset id (repeat flag for multiple).",
    )
    p.add_argument("--small-repo-id", default="NuTonic/firewatch-sft-v1")
    p.add_argument(
        "--task-repeat",
        type=int,
        default=8,
        help="Repeat each task hub this many times (e.g. 5k*8 ~ 40k rows vs ~800k main => a few %% task mass).",
    )
    p.add_argument(
        "--small-repeat",
        type=int,
        default=80,
        help="Repeat small hub rows (~200×80≈16k vs ~800k main ≈ ~2%% Firewatch mass).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = list(out_dir.glob("*.parquet"))
    if existing and not args.overwrite:
        print(
            f"Refusing to write: {len(existing)} parquet file(s) already exist under {out_dir}. "
            "Pass --overwrite to replace.",
            file=sys.stderr,
        )
        return 2
    if existing and args.overwrite:
        for f in existing:
            f.unlink()

    print(f"Streaming main dataset {args.main_repo_id!r}...", flush=True)
    n_main = _stream_main_to_shards(
        args.main_repo_id,
        out_dir,
        subset=args.subset,
        split=args.split,
        chunk_rows=args.chunk_rows,
        prefix="main",
        max_rows=args.main_max_rows,
    )
    print(f"  wrote {n_main:,} main rows", flush=True)

    for repo_id in args.task_repo_id:
        print(f"Materializing task dataset {repo_id!r}...", flush=True)
        safe = repo_id.replace("/", "__")
        n_task = _materialize_whole_split(
            repo_id,
            out_dir,
            subset=args.subset,
            split=args.split,
            chunk_rows=args.chunk_rows,
            prefix=f"task__{safe}",
            repeat=max(1, args.task_repeat),
        )
        print(f"  wrote {n_task:,} rows", flush=True)

    print(
        f"Materializing small dataset {args.small_repo_id!r} x{args.small_repeat}...",
        flush=True,
    )
    safe_small = args.small_repo_id.replace("/", "__")
    n_small = _materialize_whole_split(
        args.small_repo_id,
        out_dir,
        subset=args.subset,
        split=args.split,
        chunk_rows=args.chunk_rows,
        prefix=f"small__{safe_small}",
        repeat=max(1, args.small_repeat),
    )
    print(f"  wrote {n_small:,} rows (including repeats)", flush=True)

    shards = sorted(out_dir.glob("*.parquet"))
    print(f"Done. {len(shards)} parquet shard(s) under {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
