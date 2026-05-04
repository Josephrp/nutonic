#!/usr/bin/env python3
"""
Download and verify the final NU:TONIC LFM-VL training dataset.

**Speed:** For very large file counts (100k+ PNGs), prefer ``--download-strategy snapshot``
(default), which uses ``huggingface_hub.snapshot_download`` and is usually much faster than
per-file ``hf_hub_download`` threads. Also install ``hf_transfer`` and set
``HF_HUB_ENABLE_HF_TRANSFER=1`` for faster transfers.

**Iterative / smoke training:** Use a small Parquet mix (``--mix-main-max-rows`` on the
e2e/materialize path) so you only need media for a subset of rows—or point training at
the Hub id with ``--limit`` for LEAP smoke tests without mirroring the whole tree.

**Small missing tails:** When only a few paths are left (default: up to 5000), this script
uses parallel per-file downloads instead of ``snapshot_download``, which otherwise
re-scans the whole repo and can appear stuck for a long time.

**HF CLI:** You can pull the same blobs with ``hf download <repo_id> --repo-type dataset
--local-dir ...`` (install ``huggingface_hub[cli]``). It uses the same Hub stack as
``snapshot_download``; enable ``HF_HUB_ENABLE_HF_TRANSFER=1`` and ``hf_transfer`` for speed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import fnmatch
import json
import os
import time
from pathlib import Path
from typing import Any


DEFAULT_REPO_ID = "NuTonic/sat-vl-sft-training-ready-v1"
DEFAULT_OUT_DIR = "/data/nutonic/sat-vl-sft-training-ready-v1"
DEFAULT_ALLOW_PATTERNS = (
    "data/**",
    "images/**",
    "mapbox_stills/**",
    "analysis_images/**",
    "overlays/**",
    "README.md",
    "dataset_infos.json",
)


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


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


def _du_bytes(path: Path) -> int | None:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        return None
    return total


def _download_one(
    *,
    repo_id: str,
    revision: str | None,
    token: str | None,
    local_dir: Path,
    path_in_repo: str,
    max_retries: int,
) -> str:
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
            return path_in_repo
        except Exception as e:
            if not _retryable(e) or attempt >= max_retries:
                raise
            wait = min(120.0, 2.0**attempt)
            print(
                f"retry {attempt}/{max_retries}: {path_in_repo} after {type(e).__name__}: {e!s}; "
                f"sleeping {wait:.1f}s",
                flush=True,
            )
            time.sleep(wait)
    raise RuntimeError(f"unreachable download failure: {path_in_repo}")


def _iter_jsonl_rows(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                yield json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}") from e


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
                image = part["image"]
                if not image.startswith(("http://", "https://", "/")):
                    out.append(image)
    return out


def _verify_training_tree(local_dir: Path, *, verify_media_refs: bool, media_sample_rows: int) -> dict[str, Any]:
    data_dir = local_dir / "data"
    jsonls = sorted(data_dir.glob("*.jsonl")) if data_dir.is_dir() else []
    if not jsonls:
        raise RuntimeError(f"No data/*.jsonl files found under {local_dir}")

    report: dict[str, Any] = {
        "local_dir": str(local_dir),
        "jsonl_files": [str(p.relative_to(local_dir)) for p in jsonls],
        "rows_scanned": 0,
        "image_refs_checked": 0,
        "missing_image_refs": [],
    }
    if not verify_media_refs:
        return report

    missing: list[str] = []
    rows_left = max(0, int(media_sample_rows))
    for js in jsonls:
        for row in _iter_jsonl_rows(js):
            if rows_left == 0:
                break
            rows_left -= 1
            report["rows_scanned"] += 1
            if not isinstance(row, dict):
                continue
            for rel in _message_image_paths(row):
                report["image_refs_checked"] += 1
                if not (local_dir / rel).is_file():
                    missing.append(rel)
                    if len(missing) >= 25:
                        break
            if len(missing) >= 25:
                break
        if rows_left == 0 or len(missing) >= 25:
            break

    report["missing_image_refs"] = missing
    if missing:
        raise RuntimeError(
            f"Missing {len(missing)} sampled image references under {local_dir}. "
            f"First missing: {missing[:5]}"
        )
    return report


def _download_via_snapshot(
    *,
    repo_id: str,
    revision: str,
    local_dir: Path,
    allow_patterns: list[str],
    ignore_patterns: list[str],
    token: str | None,
    max_workers: int,
) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=str(local_dir),
        allow_patterns=allow_patterns,
        ignore_patterns=ignore_patterns if ignore_patterns else None,
        token=token,
        max_workers=max(1, int(max_workers)),
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    p.add_argument("--revision", default="main")
    p.add_argument("--out-dir", type=Path, default=Path(DEFAULT_OUT_DIR))
    p.add_argument("--allow-pattern", action="append", default=list(DEFAULT_ALLOW_PATTERNS))
    p.add_argument("--ignore-pattern", action="append", default=[])
    p.add_argument(
        "--download-strategy",
        choices=("snapshot", "files"),
        default="snapshot",
        help=(
            "snapshot: huggingface_hub.snapshot_download (recommended for huge file counts). "
            "files: one hf_hub_download per missing path (legacy; slower for many small files)."
        ),
    )
    p.add_argument(
        "--snapshot-if-missing-gt",
        type=int,
        default=5000,
        help=(
            "With strategy=snapshot: use snapshot_download only when more than this many paths "
            "are missing; otherwise download just those paths in parallel (avoids full-repo "
            "reconcile hangs when finishing a nearly-complete tree, e.g. last dozen files)."
        ),
    )
    p.add_argument("--max-workers", type=int, default=32)
    p.add_argument("--max-retries", type=int, default=12)
    p.add_argument("--progress-every", type=int, default=250)
    p.add_argument("--hf-token", default=None, help="Override HF_TOKEN / HUGGING_FACE_HUB_TOKEN.")
    p.add_argument("--no-verify-media-refs", dest="verify_media_refs", action="store_false")
    p.set_defaults(verify_media_refs=True)
    p.add_argument("--media-sample-rows", type=int, default=2000)
    p.add_argument("--manifest-out", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    try:
        from huggingface_hub import HfApi
    except ImportError as e:
        raise SystemExit("Install huggingface_hub first: pip install -U huggingface_hub hf_transfer") from e

    args = parse_args()
    token = args.hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    local_dir = args.out_dir.expanduser().resolve()
    local_dir.mkdir(parents=True, exist_ok=True)

    allow_patterns = [p for p in args.allow_pattern if p]
    ignore_patterns = [p for p in args.ignore_pattern if p]

    print(f"Listing dataset files: {args.repo_id}@{args.revision}", flush=True)
    api = HfApi(token=token)
    files = [
        p
        for p in api.list_repo_files(repo_id=args.repo_id, repo_type="dataset", revision=args.revision)
        if _matches(p, allow_patterns) and not _matches(p, ignore_patterns)
    ]
    if not files:
        raise SystemExit("No files matched the requested allow/ignore patterns.")

    missing = [p for p in files if not (local_dir / p).is_file()]
    print(
        f"Download plan: expected={len(files):,}, present={len(files) - len(missing):,}, "
        f"missing={len(missing):,}, out={local_dir}",
        flush=True,
    )
    if args.dry_run:
        return 0

    if missing:
        use_bulk_snapshot = (
            args.download_strategy == "snapshot"
            and len(missing) > int(args.snapshot_if_missing_gt)
        )
        if use_bulk_snapshot:
            print(
                f"Downloading {len(missing):,} missing path(s) via snapshot_download "
                f"(max_workers={args.max_workers})...",
                flush=True,
            )
            _download_via_snapshot(
                repo_id=args.repo_id,
                revision=args.revision,
                local_dir=local_dir,
                allow_patterns=allow_patterns,
                ignore_patterns=ignore_patterns,
                token=token,
                max_workers=args.max_workers,
            )
        else:
            if args.download_strategy == "snapshot":
                print(
                    f"Downloading {len(missing):,} missing path(s) via parallel hf_hub_download "
                    f"(snapshot skipped: ≤{args.snapshot_if_missing_gt} missing; full snapshot "
                    f"would rescan the whole repo and often appears hung on small tails).",
                    flush=True,
                )
            # Small tails: sequential + per-file logs. Parallel as_completed prints nothing until
            # the first file finishes; one slow/hung hf_hub_download then looks like a total stall.
            small_tail = len(missing) <= 64
            if small_tail:
                for i, p in enumerate(missing, 1):
                    print(f"  [{i}/{len(missing)}] hf_hub_download: {p}", flush=True)
                    t0 = time.monotonic()
                    _download_one(
                        repo_id=args.repo_id,
                        revision=args.revision,
                        token=token,
                        local_dir=local_dir,
                        path_in_repo=p,
                        max_retries=max(1, int(args.max_retries)),
                    )
                    dt = time.monotonic() - t0
                    print(f"  [{i}/{len(missing)}] ok ({dt:.1f}s)", flush=True)
            else:
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
                            size = _du_bytes(local_dir)
                            suffix = f", local_size~{size / (1024**3):.1f} GiB" if size is not None else ""
                            print(
                                f"  progress: {done:,}/{len(missing):,} missing files downloaded "
                                f"({done / elapsed:.1f} files/s){suffix}",
                                flush=True,
                            )

    still_missing = [p for p in files if not (local_dir / p).is_file()]
    if still_missing:
        raise SystemExit(f"Download incomplete: {len(still_missing):,} files still missing; first={still_missing[:10]}")

    report = _verify_training_tree(
        local_dir,
        verify_media_refs=bool(args.verify_media_refs),
        media_sample_rows=int(args.media_sample_rows),
    )
    report.update(
        {
            "repo_id": args.repo_id,
            "revision": args.revision,
            "expected_files": len(files),
            "local_size_bytes": _du_bytes(local_dir),
            "allow_patterns": allow_patterns,
            "ignore_patterns": ignore_patterns,
        }
    )
    manifest = args.manifest_out or (local_dir / "download_manifest.json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Dataset ready: {local_dir}")
    print(f"Manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
