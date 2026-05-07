#!/usr/bin/env python3
"""
Download only the media needed for a specific split of an image-based VLM SFT dataset on Hugging Face.

Why: `snapshot_download` of a dataset with 100k+ small PNGs can be slow when you only need `data/test.jsonl`
and the images referenced by those rows for evaluation.

Strategy:
1) Download `data/<split>.jsonl` (+ optional small metadata files) first.
2) Parse image references from `messages[].content[]` image parts.
3) Download only those referenced files (plus the JSONL) using parallel `hf_hub_download`.

This script is compatible with `NuTonic/sat-vl-sft-training-ready-v1` (default).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable


DEFAULT_REPO_ID = "NuTonic/sat-vl-sft-training-ready-v1"


def _retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        s in msg
        for s in (
            "readtimeout",
            "timeout",
            "timed out",
            "504",
            "503",
            "502",
            "500",
            "429",
            "gateway timeout",
            "connection reset",
            "connection aborted",
        )
    )


def _iter_jsonl_rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}") from e
            if isinstance(obj, dict):
                yield obj


def _message_image_paths(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    messages = row.get("messages")
    if not isinstance(messages, list):
        return out
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image" and isinstance(part.get("image"), str):
                image = part["image"].strip().replace("\\", "/")
                if not image:
                    continue
                # Only relative paths inside the dataset repo.
                if image.startswith(("http://", "https://", "/")):
                    continue
                out.append(image)
    return out


def _download_one(
    *,
    repo_id: str,
    revision: str,
    token: str | None,
    local_dir: Path,
    path_in_repo: str,
    max_retries: int,
) -> None:
    from huggingface_hub import hf_hub_download

    for attempt in range(1, max(1, int(max_retries)) + 1):
        try:
            hf_hub_download(
                repo_id=repo_id,
                repo_type="dataset",
                revision=revision,
                token=token,
                filename=path_in_repo,
                local_dir=str(local_dir),
            )
            return
        except Exception as e:
            if not _retryable(e) or attempt >= max_retries:
                raise
            time.sleep(min(120.0, 2.0**attempt))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    p.add_argument("--revision", default="main")
    p.add_argument("--split", choices=("train", "validation", "test"), default="test")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/data/nutonic/sft_subset"),
        help="Destination dataset mirror root (will contain data/<split>.jsonl and referenced media).",
    )
    p.add_argument("--max-rows", type=int, default=0, help="Cap rows scanned from JSONL (0=all).")
    p.add_argument("--max-workers", type=int, default=48)
    p.add_argument("--max-retries", type=int, default=12)
    p.add_argument("--progress-every", type=int, default=250)
    p.add_argument("--hf-token", default=None, help="Override HF_TOKEN / HUGGING_FACE_HUB_TOKEN.")
    p.add_argument(
        "--also-download",
        action="append",
        default=["README.md", "dataset_infos.json"],
        help="Extra repo files to fetch (repeatable).",
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        import huggingface_hub  # noqa: F401
    except ImportError as e:
        raise SystemExit("Install huggingface_hub first: pip install -U huggingface_hub hf_transfer") from e

    args = parse_args(argv)
    token = args.hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    local_dir = args.out_dir.expanduser().resolve()
    local_dir.mkdir(parents=True, exist_ok=True)

    split_jsonl = f"data/{args.split}.jsonl"
    must_get = [split_jsonl, *[p for p in args.also_download if p]]

    print(f"Downloading split JSONL first: {split_jsonl}", flush=True)
    for pth in must_get:
        _download_one(
            repo_id=args.repo_id,
            revision=args.revision,
            token=token,
            local_dir=local_dir,
            path_in_repo=pth,
            max_retries=max(1, int(args.max_retries)),
        )

    jsonl_path = local_dir / split_jsonl
    if not jsonl_path.is_file():
        raise SystemExit(f"Failed to download {split_jsonl} to {jsonl_path}")

    # Parse referenced media
    needed: set[str] = set(must_get)
    rows_left = int(args.max_rows)
    n_rows = 0
    n_refs = 0
    for row in _iter_jsonl_rows(jsonl_path):
        if rows_left > 0 and n_rows >= rows_left:
            break
        n_rows += 1
        for rel in _message_image_paths(row):
            needed.add(rel)
            n_refs += 1

    needed_list = sorted(needed)
    missing = [p for p in needed_list if not (local_dir / p).is_file()]
    print(
        f"Subset plan: rows_scanned={n_rows:,}, image_refs_seen={n_refs:,}, unique_files={len(needed_list):,}, "
        f"missing={len(missing):,}, out={local_dir}",
        flush=True,
    )
    if args.dry_run:
        return 0

    if missing:
        started = time.monotonic()
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, int(args.max_workers))) as ex:
            futures = {
                ex.submit(
                    _download_one,
                    repo_id=args.repo_id,
                    revision=args.revision,
                    token=token,
                    local_dir=local_dir,
                    path_in_repo=p,
                    max_retries=max(1, int(args.max_retries)),
                ): p
                for p in missing
            }
            for fut in concurrent.futures.as_completed(futures):
                fut.result()
                done += 1
                if done == 1 or done % max(1, int(args.progress_every)) == 0 or done == len(missing):
                    elapsed = max(1e-6, time.monotonic() - started)
                    print(f"  progress: {done:,}/{len(missing):,} ({done/elapsed:.1f} files/s)", flush=True)

    still_missing = [p for p in needed_list if not (local_dir / p).is_file()]
    if still_missing:
        raise SystemExit(f"Subset download incomplete: {len(still_missing):,} missing; first={still_missing[:10]}")

    manifest = {
        "repo_id": args.repo_id,
        "revision": args.revision,
        "split": args.split,
        "rows_scanned": n_rows,
        "image_refs_seen": n_refs,
        "unique_files": len(needed_list),
        "out_dir": str(local_dir),
        "extra_files": [p for p in args.also_download if p],
    }
    (local_dir / "subset_download_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Subset ready: {local_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

