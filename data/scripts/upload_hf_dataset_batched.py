#!/usr/bin/env python3
"""
Upload a large local dataset tree to a Hugging Face **dataset** repo in **multiple commits**.

Why this exists
---------------
* ``hf upload ... .`` tries to land **everything in one commit**. The Hub rejects that when a
  single commit would contain more than **~25k LFS pointers** (HTTP **413**), or the non-LFS
  payload would exceed limits.
* ``hf upload-large-folder`` / ``HfApi.upload_large_folder`` commits in **small adaptive chunks**
  (often tens–hundreds of files per commit), which can exceed the **~320 commits / hour** quota
  on very large trees.

This script walks your local folder, batches paths, and calls ``HfApi.create_commit`` once per
batch with ``CommitOperationAdd``. You control **files per commit** and **minimum seconds between
commits** so you stay under Hub limits. On **413**, a batch is **split in half** and retried.

Usage (from repo root, venv active)::

  export HF_TOKEN=hf_...
  python data/scripts/upload_hf_dataset_batched.py \\
    NuTonic/sat-image-boundingbox-sft \\
    ./data/downloads/lfm_vl_sft_full \\
    --repo-type dataset \\
    --max-files-per-commit 8000 \\
    --min-seconds-between-commits 15 \\
    --skip-existing

Resume: re-run the same command with ``--skip-existing`` so files already on the Hub are skipped.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lfm_vl_sft_dataset.hf_upload import _resolve_hf_token, _validate_repo_id


def _should_skip(rel_posix: str) -> bool:
    parts = rel_posix.split("/")
    if ".git" in parts:
        return True
    if ".cache" in parts:
        return True
    if parts and parts[-1] == ".DS_Store":
        return True
    if "__pycache__" in parts:
        return True
    return False


def _iter_local_files(local_root: Path) -> list[tuple[Path, str]]:
    """Return sorted (absolute_path, path_in_repo posix) pairs."""
    root = local_root.resolve()
    out: list[tuple[Path, str]] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if _should_skip(rel):
            continue
        out.append((p, rel))
    out.sort(key=lambda x: x[1])
    return out


def _list_remote_files(
    api,
    repo_id: str,
    *,
    repo_type: str,
    revision: str | None,
    token: str,
) -> set[str]:
    from huggingface_hub.hf_api import RepoFile

    paths: set[str] = set()
    for entry in api.list_repo_tree(
        repo_id,
        recursive=True,
        repo_type=repo_type,
        revision=revision,
        token=token,
    ):
        if isinstance(entry, RepoFile):
            paths.add(entry.path)
    return paths


def _chunked(items: list[tuple[Path, str]], size: int) -> list[list[tuple[Path, str]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _commit_batch(
    api,
    *,
    repo_id: str,
    repo_type: str,
    revision: str | None,
    token: str,
    batch: list[tuple[Path, str]],
    commit_message: str,
    parent_commit: str | None,
    num_threads: int,
) -> str:
    from huggingface_hub import CommitOperationAdd

    operations: list[CommitOperationAdd] = []
    for abs_path, rel in batch:
        operations.append(
            CommitOperationAdd(
                path_in_repo=rel,
                path_or_fileobj=abs_path,
            )
        )
    info = api.create_commit(
        repo_id=repo_id,
        repo_type=repo_type,
        revision=revision,
        operations=operations,
        commit_message=commit_message,
        token=token,
        parent_commit=parent_commit,
        num_threads=num_threads,
    )
    return info.oid


def _sleep_rate_limit(min_seconds: float) -> None:
    if min_seconds > 0:
        time.sleep(min_seconds)


def _retry_after_seconds(exc: BaseException) -> float | None:
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    h = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    if not h:
        return None
    try:
        return float(h)
    except ValueError:
        return None


def main() -> int:
    p = argparse.ArgumentParser(
        description="Upload a large folder to a Hub dataset repo using batched commits "
        "(avoids 413 single-commit LFS limits and upload-large-folder commit storms).",
    )
    p.add_argument("repo_id", help="e.g. NuTonic/sat-image-boundingbox-sft")
    p.add_argument("local_dir", type=Path, help="Local dataset root (e.g. ./data/downloads/lfm_vl_sft_full)")
    p.add_argument("--repo-type", default="dataset", choices=("dataset", "model", "space"))
    p.add_argument("--revision", default=None, help="Branch or tag (default: main)")
    p.add_argument("--private", action="store_true", help="Create dataset repo as private if missing")
    p.add_argument("--max-files-per-commit", type=int, default=8000, help="Cap files per commit (< 25k LFS)")
    p.add_argument(
        "--min-seconds-between-commits",
        type=float,
        default=15.0,
        help="Sleep after each successful commit (default 15s ≈ 240 commits/hour, under 320/h cap)",
    )
    p.add_argument(
        "--num-threads",
        type=int,
        default=8,
        help="Threads for LFS preupload inside create_commit",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="List remote files once and skip paths already present (for resume)",
    )
    p.add_argument("--dry-run", action="store_true", help="Print batch plan only")
    p.add_argument("--hf-token", default=None, help="Override HF_TOKEN / HUGGING_FACE_HUB_TOKEN")
    args = p.parse_args()

    _validate_repo_id(args.repo_id)
    token = _resolve_hf_token(args.hf_token)
    local_root = args.local_dir.resolve()
    if not local_root.is_dir():
        print(f"Not a directory: {local_root}", file=sys.stderr)
        return 2

    try:
        from huggingface_hub import HfApi
        from huggingface_hub.errors import HfHubHTTPError
    except ImportError as e:
        print("Install huggingface_hub: pip install -U huggingface_hub", file=sys.stderr)
        raise SystemExit(2) from e

    api = HfApi(token=token)

    pairs = _iter_local_files(local_root)
    if args.skip_existing:
        print("Fetching remote file list (recursive)...", flush=True)
        remote = _list_remote_files(
            api,
            args.repo_id,
            repo_type=args.repo_type,
            revision=args.revision,
            token=token,
        )
        before = len(pairs)
        pairs = [(p, r) for p, r in pairs if r not in remote]
        print(f"Skip-existing: {before - len(pairs)} already on Hub, {len(pairs)} to upload.", flush=True)

    if not pairs:
        print("Nothing to upload.", flush=True)
        return 0

    max_per = max(1, min(args.max_files_per_commit, 24_000))

    def plan_batches() -> list[list[tuple[Path, str]]]:
        return _chunked(pairs, max_per)

    batches = plan_batches()
    print(
        f"Local files to upload: {len(pairs)} in {len(batches)} commit(s) "
        f"(<={max_per} files/commit, >={args.min_seconds_between_commits}s between commits)",
        flush=True,
    )
    if args.dry_run:
        return 0

    api.create_repo(args.repo_id, repo_type=args.repo_type, private=args.private, exist_ok=True)

    parent_commit: str | None = None
    total_commits = 0

    def commit_recursive(batch: list[tuple[Path, str]], label: str, depth: int) -> None:
        nonlocal parent_commit, total_commits
        if depth > 24:
            raise RuntimeError("Too many recursive splits; lower --max-files-per-commit")
        if not batch:
            return
        msg = f"{label} ({len(batch)} files)"
        attempt = 0
        while True:
            attempt += 1
            try:
                oid = _commit_batch(
                    api,
                    repo_id=args.repo_id,
                    repo_type=args.repo_type,
                    revision=args.revision,
                    token=token,
                    batch=batch,
                    commit_message=msg,
                    parent_commit=parent_commit,
                    num_threads=args.num_threads,
                )
                parent_commit = oid
                total_commits += 1
                print(f"Committed {msg} -> {oid[:7]}... (commit #{total_commits})", flush=True)
                _sleep_rate_limit(args.min_seconds_between_commits)
                return
            except HfHubHTTPError as e:
                code = e.response.status_code if e.response is not None else None
                ra = _retry_after_seconds(e)
                if code == 429:
                    wait = ra if ra is not None else min(120.0, 5.0 * attempt)
                    print(f"429 rate limit; sleeping {wait:.1f}s then retrying...", flush=sys.stderr)
                    time.sleep(wait)
                    continue
                if code == 413 and len(batch) > 1:
                    mid = len(batch) // 2
                    print(
                        f"413 payload too large for {len(batch)} files; splitting into "
                        f"{mid} + {len(batch) - mid}...",
                        file=sys.stderr,
                    )
                    commit_recursive(batch[:mid], f"{label} [a]", depth + 1)
                    commit_recursive(batch[mid:], f"{label} [b]", depth + 1)
                    return
                raise

    for i, batch in enumerate(batches, start=1):
        commit_recursive(batch, f"batched dataset upload {i}/{len(batches)}", 0)

    if args.repo_type == "dataset":
        hub_url = f"https://huggingface.co/datasets/{args.repo_id}"
    elif args.repo_type == "space":
        hub_url = f"https://huggingface.co/spaces/{args.repo_id}"
    else:
        hub_url = f"https://huggingface.co/{args.repo_id}"
    print(f"Done. {total_commits} commit(s) to {hub_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
