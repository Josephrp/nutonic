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

**Skip-existing performance:** by default the remote inventory is fetched **per top-level prefix**
(``data/``, ``images/``, …) derived from your local tree, instead of one giant recursive listing of the
entire repo (which can look “hung” for a long time on large datasets). Use
``--skip-existing-remote-mode full`` only if you need a full-repo scan.

**“Hung” on a commit:** ``create_commit`` can sit at ~80% in tqdm while the Hub ingests LFS;
that is often still working. Use ``--upload-heartbeat-interval 45`` (default) for periodic log
lines during each commit. Very large files (e.g. multi-hundred-MiB ``data/*.jsonl``) are **isolated**
into their own commits by default (see ``--isolate-lfs-files-mib``) so they are not mixed with
thousands of small PNGs in one LFS batch. For stalls, try smaller ``--max-files-per-commit`` (e.g. 2000)
and ``--num-threads`` in the 8–16 range (40+ can hurt on some networks). Optional: ``pip install hf_transfer``
and ``HF_HUB_ENABLE_HF_TRANSFER=1`` for faster transfers.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
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


def _top_level_prefixes_from_pairs(pairs: list[tuple[Path, str]]) -> list[str]:
    """Stable sorted list of first path segment for each file (used for scoped Hub tree walks)."""
    return sorted({rel.split("/", 1)[0] for _, rel in pairs})


def _list_remote_files(
    api,
    repo_id: str,
    *,
    repo_type: str,
    revision: str | None,
    token: str,
    prefixes: list[str] | None,
    progress_every: int = 25_000,
) -> set[str]:
    """
    Build a set of ``path_in_repo`` strings for files already on the Hub.

    When ``prefixes`` is set, call ``list_repo_tree`` once per prefix (much less opaque than a
    single unbounded full-repo walk on resume). When ``prefixes`` is None, list the entire repo
    recursively (legacy / escape hatch).

    Missing prefixes (new or empty repo) return **404** from the Hub; those are treated as **no
    remote files** under that prefix so ``--skip-existing`` can run on first upload.
    """
    from huggingface_hub.errors import HfHubHTTPError, RemoteEntryNotFoundError
    from huggingface_hub.hf_api import RepoFile

    paths: set[str] = set()
    total = 0

    def _consume(it: object, label: str) -> None:
        nonlocal total
        for entry in it:
            if isinstance(entry, RepoFile):
                paths.add(entry.path)
                total += 1
                if total % progress_every == 0:
                    print(f"  remote inventory: {total} paths listed so far ({label})...", flush=True)

    if prefixes is None:
        print("Listing entire remote repo (recursive). This can take a long time on large datasets.", flush=True)
        _consume(
            api.list_repo_tree(
                repo_id,
                recursive=True,
                repo_type=repo_type,
                revision=revision,
                token=token,
            ),
            "full tree",
        )
        print(f"Remote inventory complete: {len(paths)} file paths.", flush=True)
        return paths

    print(
        f"Listing remote files under {len(prefixes)} prefix(es) derived from local paths "
        f"(not the whole repo tree).",
        flush=True,
    )
    for prefix in prefixes:
        print(f"  prefix {prefix!r}...", flush=True)
        try:
            it = api.list_repo_tree(
                repo_id,
                path_in_repo=prefix,
                recursive=True,
                repo_type=repo_type,
                revision=revision,
                token=token,
            )
            _consume(it, prefix)
        except RemoteEntryNotFoundError:
            print(f"  prefix {prefix!r}: not on remote yet (empty).", flush=True)
            continue
        except HfHubHTTPError as e:
            code = e.response.status_code if e.response is not None else None
            if code == 404:
                print(f"  prefix {prefix!r}: remote 404 (empty).", flush=True)
                continue
            raise
    print(f"Remote inventory complete: {len(paths)} file paths.", flush=True)
    return paths


def _chunked(items: list[tuple[Path, str]], size: int) -> list[list[tuple[Path, str]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _plan_batches_with_isolated_large_files(
    pairs: list[tuple[Path, str]],
    *,
    max_per: int,
    isolate_mib: float,
) -> tuple[list[list[tuple[Path, str]]], int]:
    """
    Normal files are chunked to ``max_per`` per commit.

    Files at or above ``isolate_mib`` each get their **own** commit after all smaller batches.
    This avoids one giant JSONL sharing a single ``create_commit`` with thousands of PNGs, which
    often stalls tqdm near the end of the large file.
    """
    if isolate_mib <= 0:
        batches = _chunked(pairs, max_per)
        return batches, 0
    limit = int(float(isolate_mib) * 1024 * 1024)
    small: list[tuple[Path, str]] = []
    large: list[tuple[Path, str]] = []
    for p, rel in sorted(pairs, key=lambda x: x[1]):
        try:
            sz = p.stat().st_size
        except OSError:
            small.append((p, rel))
            continue
        if sz >= limit:
            large.append((p, rel))
        else:
            small.append((p, rel))
    batches: list[list[tuple[Path, str]]] = list(_chunked(small, max_per))
    for item in large:
        batches.append([item])
    return batches, len(large)


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


def _commit_batch_with_heartbeat(
    api: object,
    *,
    repo_id: str,
    repo_type: str,
    revision: str | None,
    token: str,
    batch: list[tuple[Path, str]],
    commit_message: str,
    parent_commit: str | None,
    num_threads: int,
    heartbeat_interval: float,
) -> str:
    """Wrap ``_commit_batch`` so long LFS phases do not look like a silent hang."""
    if heartbeat_interval <= 0:
        return _commit_batch(
            api,
            repo_id=repo_id,
            repo_type=repo_type,
            revision=revision,
            token=token,
            batch=batch,
            commit_message=commit_message,
            parent_commit=parent_commit,
            num_threads=num_threads,
        )

    stop = threading.Event()
    started = time.monotonic()

    def _heartbeat_loop() -> None:
        while not stop.wait(heartbeat_interval):
            elapsed = time.monotonic() - started
            print(
                f"  ... still inside create_commit ({elapsed:.0f}s elapsed); "
                f"LFS/Hub may be busy; tqdm can pause here without the process being stuck.",
                flush=True,
            )

    th = threading.Thread(target=_heartbeat_loop, name="hf-upload-heartbeat", daemon=True)
    th.start()
    try:
        return _commit_batch(
            api,
            repo_id=repo_id,
            repo_type=repo_type,
            revision=revision,
            token=token,
            batch=batch,
            commit_message=commit_message,
            parent_commit=parent_commit,
            num_threads=num_threads,
        )
    finally:
        stop.set()
        th.join(timeout=min(120.0, heartbeat_interval + 30.0))


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
        "--isolate-lfs-files-mib",
        type=float,
        default=48.0,
        help="Files this large (MiB) or larger are uploaded alone in their own commit after smaller "
        "batches (0 disables). Avoids huge JSONL + thousands of PNGs in one create_commit. Default 48.",
    )
    p.add_argument(
        "--min-seconds-between-commits",
        type=float,
        default=15.0,
        help="Sleep after each successful commit (default 15s ≈ 240 commits/hour, under 320/h cap)",
    )
    p.add_argument(
        "--num-threads",
        type=int,
        default=4,
        help="Threads for LFS preupload inside create_commit (lower can reduce stalls on some hosts)",
    )
    p.add_argument(
        "--upload-heartbeat-interval",
        type=float,
        default=45.0,
        help="Seconds between log lines while each create_commit runs (0 disables). "
        "Helps when tqdm appears frozen during long LFS batches.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="List remote files once and skip paths already present (for resume)",
    )
    p.add_argument(
        "--skip-existing-remote-mode",
        default="prefixes",
        choices=("prefixes", "full"),
        help="With --skip-existing: list remote per top-level prefix from local paths (default), "
        "or one full recursive repo scan (slow on huge repos).",
    )
    p.add_argument(
        "--remote-inventory-progress-every",
        type=int,
        default=25_000,
        help="Log every N remote paths while building skip-existing inventory (0 disables).",
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

    if args.num_threads > 24:
        print(
            f"Note: --num-threads={args.num_threads} is high; Hub LFS sometimes contends or stalls "
            f"with very large pools. If a batch sits with no new tqdm output, try 8–16 threads and/or "
            f"a smaller --max-files-per-commit.",
            file=sys.stderr,
        )

    pairs = _iter_local_files(local_root)
    if args.skip_existing:
        if args.skip_existing_remote_mode == "prefixes":
            prefixes = _top_level_prefixes_from_pairs(pairs)
        else:
            prefixes = None
        prog = max(0, int(args.remote_inventory_progress_every))
        remote = _list_remote_files(
            api,
            args.repo_id,
            repo_type=args.repo_type,
            revision=args.revision,
            token=token,
            prefixes=prefixes,
            progress_every=prog if prog > 0 else 10**12,
        )
        before = len(pairs)
        pairs = [(p, r) for p, r in pairs if r not in remote]
        print(f"Skip-existing: {before - len(pairs)} already on Hub, {len(pairs)} to upload.", flush=True)

    if not pairs:
        print("Nothing to upload.", flush=True)
        return 0

    max_per = max(1, min(args.max_files_per_commit, 24_000))

    batches, n_isolated = _plan_batches_with_isolated_large_files(
        pairs,
        max_per=max_per,
        isolate_mib=float(args.isolate_lfs_files_mib),
    )
    iso_note = (
        f", including {n_isolated} isolated large-file commit(s) (>= {args.isolate_lfs_files_mib:g} MiB each)"
        if n_isolated
        else ""
    )
    print(
        f"Local files to upload: {len(pairs)} in {len(batches)} commit(s) "
        f"(<={max_per} files/commit for multi-file batches{iso_note}, "
        f">={args.min_seconds_between_commits}s between commits)",
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
                print(
                    f"  create_commit attempt {attempt}: uploading {len(batch)} file(s) "
                    f"(LFS may take a long time per batch)...",
                    flush=True,
                )
                oid = _commit_batch_with_heartbeat(
                    api,
                    repo_id=args.repo_id,
                    repo_type=args.repo_type,
                    revision=args.revision,
                    token=token,
                    batch=batch,
                    commit_message=msg,
                    parent_commit=parent_commit,
                    num_threads=args.num_threads,
                    heartbeat_interval=float(args.upload_heartbeat_interval),
                )
                parent_commit = oid
                total_commits += 1
                print(f"Committed {msg} -> {oid[:7]}... (commit #{total_commits})", flush=True)
                if args.min_seconds_between_commits > 0:
                    print(
                        f"  Waiting {args.min_seconds_between_commits}s before next commit "
                        f"(Hub rate-limit safety; not stuck).",
                        flush=True,
                    )
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
                if code in (408, 500, 502, 503, 504) and attempt <= 12:
                    wait = ra if ra is not None else min(180.0, 5.0 * attempt)
                    print(
                        f"HTTP {code} on create_commit; sleeping {wait:.1f}s then retrying "
                        f"(attempt {attempt}/12)...",
                        flush=sys.stderr,
                    )
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
