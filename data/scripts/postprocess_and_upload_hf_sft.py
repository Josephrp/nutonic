#!/usr/bin/env python3
"""
End-to-end remote post-processing for existing Hugging Face SFT datasets.

Workflow:
1) Snapshot-download one or more HF *dataset* repos (JSONL + media assets).
2) Post-process rows to reduce leakage/over-precision using deterministic rules:
   - de-precision percentages
   - redact mapbox-style location strings (coords/country/vicinity)
   - redact embedded TiM JSON blobs in prompts
   - trim overly long assistant outputs
3) Optional: merge multiple source datasets into one output dataset folder
   with namespaced media paths to avoid collisions.
4) Optional: shard media directories to satisfy Hub 10k-files-per-directory git tree limit.
5) Upload via the repo's existing batched uploader (recommended).

Requires:
  pip install -U huggingface_hub
Auth:
  set HF_TOKEN or HUGGING_FACE_HUB_TOKEN in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Local modules in this repo.
from lfm_vl_sft_dataset.hf_upload import _resolve_hf_token, _validate_repo_id  # noqa: E402

try:
    # postprocess_sft_dataset.py lives next to this file.
    from postprocess_sft_dataset import filter_overlong_rows, postprocess_rows  # type: ignore  # noqa: E402
except Exception as e:  # pragma: no cover
    raise RuntimeError(f"Failed to import postprocess_rows from postprocess_sft_dataset.py: {e}") from e


MEDIA_PREFIXES: tuple[str, ...] = (
    "images/",
    "mapbox_stills/",
    "analysis_images/",
    "overlays/",
    "metadata/",
)


def _safe_tag(repo_id: str) -> str:
    """Make a stable filesystem-safe namespace tag from org/repo."""
    rid = repo_id.strip().replace("\\", "/")
    return rid.replace("/", "__").replace(" ", "_")


def _rm_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _copytree_hardlink(src: Path, dst: Path) -> None:
    """
    Copy a directory tree but prefer hardlinks for files (fast, no duplication).
    Works only when src/dst are on the same filesystem; falls back to copy.
    """
    src = src.resolve()
    dst = dst.resolve()
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        out = dst / rel
        if p.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        if not p.is_file():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(p, out)
        except OSError:
            shutil.copy2(p, out)


def _rewrite_strings(obj: Any, fn) -> Any:
    """Recursively apply fn(str)->str to all string values."""
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_rewrite_strings(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: _rewrite_strings(v, fn) for k, v in obj.items()}
    return obj


def _namespace_media_path(s: str, *, tag: str) -> str:
    """
    If s looks like a dataset-relative media path, insert tag after the top-level prefix:
      images/foo.png -> images/<tag>/foo.png
    """
    if not tag:
        return s
    ss = s.strip().replace("\\", "/")
    for pref in MEDIA_PREFIXES:
        if ss.startswith(pref):
            rest = ss[len(pref) :]
            if rest.startswith(f"{tag}/"):
                return ss
            return f"{pref}{tag}/{rest}"
    return s


def _namespace_row_media_paths(row: dict[str, Any], *, tag: str) -> dict[str, Any]:
    return _rewrite_strings(row, lambda s: _namespace_media_path(s, tag=tag))


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON at {path}:{line_no}") from e
            if isinstance(obj, dict):
                yield obj


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _postprocess_dataset_tree(
    *,
    src_root: Path,
    dst_root: Path,
    tag: str,
    max_assistant_chars: int,
    redact_tim_json: bool,
    minify_tim_json: bool,
    max_user_chars: int,
    max_total_chars: int,
) -> dict[str, Any]:
    """
    Copy a dataset snapshot tree to dst_root and postprocess `data/*.jsonl`.
    When tag is non-empty, also namespace media paths in JSONL (and metadata JSON).
    """
    src_root = src_root.resolve()
    dst_root = dst_root.resolve()
    if not src_root.is_dir():
        raise FileNotFoundError(f"Missing source dataset root: {src_root}")
    _rm_tree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)

    # Copy everything first (fast via hardlinks), then rewrite the few text files.
    _copytree_hardlink(src_root, dst_root)

    stats: dict[str, Any] = {"src_root": str(src_root), "dst_root": str(dst_root), "tag": tag, "splits": {}}

    data_dir = dst_root / "data"
    if data_dir.is_dir():
        for js in sorted(data_dir.glob("*.jsonl")):
            out_rows: list[dict[str, Any]] = []
            rows = list(_iter_jsonl(js))
            if redact_tim_json:
                for r in rows:
                    if isinstance(r, dict):
                        r.setdefault("_postprocess", {})
                        if isinstance(r["_postprocess"], dict):
                            r["_postprocess"]["redact_tim_json"] = True
            if minify_tim_json:
                for r in rows:
                    if isinstance(r, dict):
                        r.setdefault("_postprocess", {})
                        if isinstance(r["_postprocess"], dict):
                            r["_postprocess"]["minify_tim_json"] = True
            processed, st = postprocess_rows(rows, max_assistant_chars=max_assistant_chars)
            processed = filter_overlong_rows(
                processed,
                max_user_chars=int(max_user_chars),
                max_total_chars=int(max_total_chars),
                stats=st,
            )
            for row in processed:
                if tag:
                    row = _namespace_row_media_paths(row, tag=tag)
                out_rows.append(row)
            _write_jsonl(js, out_rows)
            stats["splits"][js.name] = {"rows": len(out_rows), "changes": st.by_change}

    # Namespace paths inside metadata JSON too (so any image_paths lists remain consistent).
    meta_dir = dst_root / "metadata"
    if tag and meta_dir.is_dir():
        for p in sorted(meta_dir.rglob("*.json")):
            if not p.is_file():
                continue
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            obj2 = _rewrite_strings(obj, lambda s: _namespace_media_path(s, tag=tag))
            if obj2 != obj:
                p.write_text(json.dumps(obj2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # When tagging, also move media files into the new namespaced folders.
    if tag:
        for top in ("images", "mapbox_stills", "analysis_images", "overlays", "metadata"):
            d = dst_root / top
            if not d.is_dir():
                continue
            # Only move *flat* files under these roots; keep subtrees (like metadata/sft_metadata_rows) intact.
            # We put the tag directory at the top-level to avoid collisions across merged datasets.
            tag_dir = d / tag
            tag_dir.mkdir(parents=True, exist_ok=True)
            for child in list(d.iterdir()):
                if child.name == tag or not child.is_file():
                    continue
                shutil.move(str(child), str(tag_dir / child.name))

    return stats


def _merge_jsonl_splits(
    *,
    src_roots: list[Path],
    dst_root: Path,
) -> None:
    """
    Merge by concatenating split JSONLs. Assumes each src_root has already been postprocessed
    and (if needed) namespaced so media path collisions are avoided.
    """
    dst_data = dst_root / "data"
    dst_data.mkdir(parents=True, exist_ok=True)
    split_names = ("train.jsonl", "validation.jsonl", "test.jsonl")
    for split in split_names:
        merged: list[dict[str, Any]] = []
        for r in src_roots:
            p = r / "data" / split
            if p.is_file():
                merged.extend(list(_iter_jsonl(p)))
        if merged:
            _write_jsonl(dst_data / split, merged)


def _materialize_merged_media(
    *,
    src_roots: list[Path],
    dst_root: Path,
) -> None:
    """
    Copy media trees from each src_root into dst_root.
    Because src_roots are expected to be namespaced (images/<tag>/...), this is safe.
    """
    for top in ("images", "mapbox_stills", "analysis_images", "overlays", "metadata"):
        out = dst_root / top
        out.mkdir(parents=True, exist_ok=True)
        for r in src_roots:
            src = r / top
            if src.is_dir():
                shutil.copytree(src, out, dirs_exist_ok=True)


def _run_shard_for_hub(*, src: Path, dst: Path, max_files_per_dir: int, link: str, overwrite: bool) -> None:
    shard_script = SCRIPTS_DIR / "shard_lfm_vl_dataset_for_hub.py"
    if not shard_script.is_file():
        raise FileNotFoundError(f"Missing shard script: {shard_script}")
    cmd = [
        sys.executable,
        str(shard_script),
        "--src",
        str(src.resolve()),
        "--dst",
        str(dst.resolve()),
        "--max-files-per-dir",
        str(int(max_files_per_dir)),
        "--link",
        link,
    ]
    if overwrite:
        cmd.append("--overwrite-dst")
    subprocess.run(cmd, check=True)


def _run_batched_upload(
    *,
    repo_id: str,
    local_dir: Path,
    private: bool,
    max_files_per_commit: int,
    min_seconds: float,
    skip_existing: bool,
    skip_existing_remote_mode: str,
    remote_inventory_progress_every: int,
    num_threads: int,
    upload_heartbeat_interval: float,
    isolate_lfs_files_mib: float,
    hf_token: str | None,
    dry_run: bool,
) -> None:
    uploader = SCRIPTS_DIR / "upload_hf_dataset_batched.py"
    if not uploader.is_file():
        raise FileNotFoundError(f"Missing uploader: {uploader}")
    cmd = [
        sys.executable,
        str(uploader),
        repo_id,
        str(local_dir.resolve()),
        "--repo-type",
        "dataset",
        "--max-files-per-commit",
        str(int(max_files_per_commit)),
        "--min-seconds-between-commits",
        str(float(min_seconds)),
        "--num-threads",
        str(int(num_threads)),
        "--upload-heartbeat-interval",
        str(float(upload_heartbeat_interval)),
        "--isolate-lfs-files-mib",
        str(float(isolate_lfs_files_mib)),
    ]
    if private:
        cmd.append("--private")
    if skip_existing:
        cmd.append("--skip-existing")
        cmd.extend(["--skip-existing-remote-mode", skip_existing_remote_mode])
        cmd.extend(["--remote-inventory-progress-every", str(int(remote_inventory_progress_every))])
    if hf_token:
        cmd.extend(["--hf-token", hf_token])
    if dry_run:
        cmd.append("--dry-run")
    subprocess.run(cmd, check=True)


@dataclass
class SourceSpec:
    repo_id: str
    tag: str


def _snapshot_download_dataset(
    *,
    repo_id: str,
    token: str,
    work_dir: Path,
    revision: str | None,
    allow_patterns: list[str] | None,
    ignore_patterns: list[str] | None,
    max_retries: int,
) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:  # pragma: no cover
        raise ImportError("huggingface_hub is required: pip install -U huggingface_hub") from e

    max_workers = int(os.environ.get("HF_SNAPSHOT_MAX_WORKERS", "0") or "0")
    if max_workers <= 0:
        max_workers = 8

    heartbeat_s = float(os.environ.get("HF_SNAPSHOT_HEARTBEAT_S", "0") or "0")
    if heartbeat_s <= 0:
        heartbeat_s = 30.0

    local_dir = work_dir / "snapshots" / _safe_tag(repo_id)
    local_dir.parent.mkdir(parents=True, exist_ok=True)

    # Persisted incremental scan state for fallback progress reporting (keyed by local_dir).
    scan_state: dict[str, Any] = {"stack": [], "seen_dirs": set(), "bytes": 0, "files": 0, "init": False}

    def _du_bytes(root: Path, *, exclude_hf_cache: bool) -> int | None:
        """
        Return apparent size in bytes using `du -sb` (fast in native code).
        Falls back to None if `du` isn't available.
        """
        root_str = str(root)
        # Try a few common du variants across GNU coreutils / BusyBox.
        excl = "--exclude=.cache/huggingface/download"
        if exclude_hf_cache:
            candidates: list[list[str]] = [
                ["du", "-sb", excl, root_str],  # GNU coreutils
                ["du", "-s", "--block-size=1", excl, root_str],  # GNU coreutils alt
                ["du", "-sk", excl, root_str],  # portable-ish (KiB)
                # Fallbacks without exclude (BusyBox may not support --exclude).
                ["du", "-sb", root_str],
                ["du", "-s", "--block-size=1", root_str],
                ["du", "-sk", root_str],
            ]
        else:
            candidates = [
                ["du", "-sb", root_str],
                ["du", "-s", "--block-size=1", root_str],
                ["du", "-sk", root_str],
            ]
        for cmd in candidates:
            try:
                cp = subprocess.run(
                    cmd,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            except Exception:
                continue
            head = (cp.stdout or "").strip().split(maxsplit=1)
            if not head:
                continue
            try:
                n = int(head[0])
            except ValueError:
                continue
            # If we used -sk, the number is KiB.
            if cmd[:2] == ["du", "-sk"]:
                return n * 1024
            return n
        return None

    def _incremental_size_probe(root: Path, *, budget_ms: float = 200.0) -> tuple[int, int]:
        """
        Best-effort incremental scan that avoids full `os.walk` cost on huge trees.
        Returns (bytes_seen_lower_bound, files_seen_count).

        We scan directory entries in a stack with a small time budget per heartbeat.
        Over time it converges upward as more of the tree is visited.
        """
        if not root.exists():
            return 0, 0
        if not scan_state["init"]:
            scan_state["stack"] = [root]
            scan_state["seen_dirs"] = set()
            scan_state["bytes"] = 0
            scan_state["files"] = 0
            scan_state["init"] = True

        deadline = time.monotonic() + (budget_ms / 1000.0)
        stack: list[Path] = scan_state["stack"]
        seen_dirs: set[str] = scan_state["seen_dirs"]
        while stack and time.monotonic() < deadline:
            d = stack.pop()
            key = str(d)
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            try:
                with os.scandir(d) as it:
                    for ent in it:
                        if time.monotonic() >= deadline:
                            # Put directory back to continue later.
                            stack.append(d)
                            break
                        try:
                            if ent.is_symlink():
                                continue
                            if ent.is_file(follow_symlinks=False):
                                scan_state["files"] += 1
                                try:
                                    scan_state["bytes"] += ent.stat(follow_symlinks=False).st_size
                                except OSError:
                                    continue
                            elif ent.is_dir(follow_symlinks=False):
                                stack.append(Path(ent.path))
                        except OSError:
                            continue
            except OSError:
                continue
        return int(scan_state["bytes"]), int(scan_state["files"])

    def _top_level_file_counts(root: Path) -> dict[str, int]:
        """
        Cheap-ish progress proxy: count files in a few known top-level directories without
        recursively walking the entire tree.
        """
        counts: dict[str, int] = {}
        for name in ("data", "images", "mapbox_stills", "analysis_images", "overlays", "metadata"):
            d = root / name
            if not d.is_dir():
                continue
            try:
                # Only count direct children (fast); sharded layouts will still show growth.
                counts[name] = sum(1 for p in d.iterdir() if p.is_file())
            except OSError:
                continue
        return counts

    result: dict[str, Any] = {}
    err: list[BaseException] = []

    def _run() -> None:
        try:
            # ``snapshot_download`` is resumable when writing to ``local_dir`` (Hub manages partial files under
            # ``<local_dir>/.cache/huggingface/``). Deprecated kwargs removed to reduce noisy warnings.
            #
            # Reliability tips (remote runners):
            # - pip install -U hf_transfer && export HF_HUB_ENABLE_HF_TRANSFER=1
            # - export HF_HUB_DOWNLOAD_TIMEOUT=600  (or higher) if you see ReadTimeout on slow links
            for attempt in range(1, max(1, int(max_retries)) + 1):
                try:
                    result["path"] = snapshot_download(
                        repo_id=repo_id,
                        repo_type="dataset",
                        revision=revision,
                        token=token,
                        local_dir=str(local_dir),
                        max_workers=max_workers,
                        allow_patterns=allow_patterns,
                        ignore_patterns=ignore_patterns,
                    )
                    break
                except Exception as e:
                    # Retry on transient network / Hub overload signals.
                    msg = str(e).lower()
                    retryable = any(
                        s in msg
                        for s in (
                            "readtimeout",
                            "timeout",
                            "timed out",
                            "504",
                            "503",
                            "502",
                            "429",
                            "gateway timeout",
                            "connection reset",
                            "connection aborted",
                        )
                    )
                    if not retryable or attempt >= int(max_retries):
                        raise
                    wait = min(120.0, 2.0**attempt)
                    print(
                        f"snapshot_download retry {attempt}/{max_retries} for {repo_id} after {type(e).__name__}: {e!s}; "
                        f"sleeping {wait:.1f}s",
                        flush=True,
                    )
                    time.sleep(wait)
        except BaseException as e:  # noqa: BLE001
            err.append(e)

    th = threading.Thread(target=_run, name=f"hf-snapshot:{repo_id}", daemon=True)
    print(f"Snapshot download start: {repo_id} -> {local_dir} (max_workers={max_workers})", flush=True)
    th.start()
    last = time.monotonic()
    prev_t = last
    prev_total = _du_bytes(local_dir, exclude_hf_cache=False)
    while th.is_alive():
        th.join(timeout=1.0)
        now = time.monotonic()
        if now - last >= heartbeat_s:
            last = now
            total = _du_bytes(local_dir, exclude_hf_cache=False)
            finalish = _du_bytes(local_dir, exclude_hf_cache=True)
            rate = ""
            if total is not None and prev_total is not None:
                dt = max(1e-6, now - prev_t)
                dmb = (total - prev_total) / (1024 * 1024)
                rate = f", +{dmb/dt:.1f} MiB/s"
            if total is not None:
                mib_total = total / (1024 * 1024)
                suffix = ""
                if finalish is not None:
                    mib_fin = finalish / (1024 * 1024)
                    suffix = f", dataset~{mib_fin:.1f} MiB (excl hf cache)"
                counts = _top_level_file_counts(local_dir)
                extra = f", top-level files={counts}" if counts else ""
                print(f"  snapshot heartbeat: {repo_id}: total~{mib_total:.1f} MiB{rate}{suffix}{extra}", flush=True)
            else:
                # Fallback: incremental lower-bound probe without expensive full tree walk.
                bb, nf = _incremental_size_probe(local_dir, budget_ms=200.0)
                mib2 = bb / (1024 * 1024)
                print(
                    f"  snapshot heartbeat: {repo_id}: still running (du unavailable); "
                    f"scanned>={nf} files, >= {mib2:.1f} MiB so far...",
                    flush=True,
                )
            prev_t = now
            prev_total = total
    if err:
        raise RuntimeError(f"snapshot_download failed for {repo_id}: {err[0]}") from err[0]
    path = str(result.get("path") or local_dir)
    b_final = _du_bytes(Path(path), exclude_hf_cache=False)
    n_bytes = int(b_final) if b_final is not None else 0
    print(
        f"Snapshot download done: {repo_id}: {n_bytes/(1024*1024):.1f} MiB at {path}",
        flush=True,
    )
    return Path(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--src",
        action="append",
        required=True,
        metavar="ORG/NAME",
        help="Source HF dataset repo id. Repeatable (pass twice for your two datasets).",
    )
    ap.add_argument("--src-revision", default=None, help="Optional source revision/branch (default main).")
    ap.add_argument(
        "--download-allow-pattern",
        action="append",
        default=None,
        help="Forwarded to snapshot_download(allow_patterns=...). Repeatable (glob-style).",
    )
    ap.add_argument(
        "--download-ignore-pattern",
        action="append",
        default=None,
        help="Forwarded to snapshot_download(ignore_patterns=...). Repeatable (glob-style). "
        "Example to skip per-row JSON sidecars: --download-ignore-pattern 'metadata/sft_metadata_rows/**'",
    )
    ap.add_argument(
        "--download-max-retries",
        type=int,
        default=8,
        help="Retries for snapshot_download on transient Hub/network failures (default 8).",
    )
    ap.add_argument("--out-repo-id", required=True, help="Destination HF dataset repo id (org/name).")
    ap.add_argument("--private", action="store_true", help="Create destination repo as private if missing.")
    ap.add_argument(
        "--merge",
        action="store_true",
        help="Merge multiple sources into one output dataset (namespaces media paths to avoid collisions).",
    )
    ap.add_argument(
        "--work-dir",
        type=Path,
        default=REPO_ROOT / "data" / "downloads" / "hf_postprocess_work",
        help="Working directory for snapshots + staging outputs.",
    )
    ap.add_argument(
        "--download-max-workers",
        type=int,
        default=32,
        help="Concurrency for Hugging Face snapshot_download (default 32). "
        "Higher helps when downloading many small files on higher-latency links.",
    )
    ap.add_argument(
        "--download-heartbeat-seconds",
        type=float,
        default=30.0,
        help="Seconds between snapshot_download progress heartbeats (default 30s).",
    )
    ap.add_argument(
        "--max-assistant-chars",
        type=int,
        default=900,
        help="Hard cap assistant text length during postprocess.",
    )
    ap.add_argument(
        "--redact-tim-json",
        action="store_true",
        help="Opt-in: redact large embedded TiM JSON blocks in prompts (default: keep).",
    )
    ap.add_argument(
        "--minify-tim-json",
        action="store_true",
        help="Opt-in: keep TiM JSON but minify it (compact JSON, no indentation).",
    )
    ap.add_argument(
        "--max-user-chars",
        type=int,
        default=0,
        help="If >0: drop examples whose user text exceeds this many characters (after processing).",
    )
    ap.add_argument(
        "--max-total-chars",
        type=int,
        default=0,
        help="If >0: drop examples whose combined (user+assistant) text exceeds this many characters (after processing).",
    )
    ap.add_argument(
        "--max-files-per-dir",
        type=int,
        default=8000,
        help="When sharding for Hub, cap files per shard directory (Hub hard limit is 10000).",
    )
    ap.add_argument(
        "--no-shard",
        action="store_true",
        help="Skip sharding step (not recommended for large datasets).",
    )
    ap.add_argument(
        "--max-files-per-commit",
        type=int,
        default=8000,
        help="Upload batching: max files per commit.",
    )
    ap.add_argument("--min-seconds-between-commits", type=float, default=15.0)
    ap.add_argument("--skip-existing", action="store_true", help="Upload resume: skip files already on Hub.")
    ap.add_argument(
        "--skip-existing-remote-mode",
        default="prefixes",
        choices=("prefixes", "full"),
    )
    ap.add_argument("--remote-inventory-progress-every", type=int, default=25_000)
    ap.add_argument("--num-threads", type=int, default=4)
    ap.add_argument("--upload-heartbeat-interval", type=float, default=45.0)
    ap.add_argument("--isolate-lfs-files-mib", type=float, default=48.0)
    ap.add_argument("--hf-token", default=None, help="Override HF_TOKEN / HUGGING_FACE_HUB_TOKEN.")
    ap.add_argument("--dry-run", action="store_true", help="Do everything except the upload step.")
    args = ap.parse_args()

    _validate_repo_id(args.out_repo_id)
    for rid in args.src:
        _validate_repo_id(rid)

    token = _resolve_hf_token(args.hf_token)
    # Pass download concurrency via env so we don't thread it through many helper signatures.
    os.environ["HF_SNAPSHOT_MAX_WORKERS"] = str(max(1, int(args.download_max_workers)))
    os.environ["HF_SNAPSHOT_HEARTBEAT_S"] = str(max(5.0, float(args.download_heartbeat_seconds)))
    work_dir: Path = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    sources: list[SourceSpec] = []
    if args.merge:
        for rid in args.src:
            sources.append(SourceSpec(repo_id=rid, tag=_safe_tag(rid)))
    else:
        # Single-source mode still supports multiple --src, but each will be uploaded separately only
        # if you run the script once per dest. Here we take the first.
        sources.append(SourceSpec(repo_id=args.src[0], tag=""))

    # 1) Download + postprocess each source into a staging root.
    staged_roots: list[Path] = []
    report: dict[str, Any] = {"sources": [], "merge": bool(args.merge)}
    for spec in sources:
        snap = _snapshot_download_dataset(
            repo_id=spec.repo_id,
            token=token,
            work_dir=work_dir,
            revision=args.src_revision,
            allow_patterns=list(args.download_allow_pattern) if args.download_allow_pattern else None,
            ignore_patterns=list(args.download_ignore_pattern) if args.download_ignore_pattern else None,
            max_retries=int(args.download_max_retries),
        )
        stage = work_dir / "staged" / _safe_tag(spec.repo_id)
        st = _postprocess_dataset_tree(
            src_root=snap,
            dst_root=stage,
            tag=spec.tag,
            max_assistant_chars=int(args.max_assistant_chars),
            redact_tim_json=bool(args.redact_tim_json),
            minify_tim_json=bool(args.minify_tim_json),
            max_user_chars=int(args.max_user_chars),
            max_total_chars=int(args.max_total_chars),
        )
        staged_roots.append(stage)
        report["sources"].append({"repo_id": spec.repo_id, "snapshot": str(snap), "stage": str(stage), "stats": st})

    # 2) Build final output tree (merged or single).
    out_root = work_dir / "out" / _safe_tag(args.out_repo_id)
    _rm_tree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    if args.merge:
        _merge_jsonl_splits(src_roots=staged_roots, dst_root=out_root)
        _materialize_merged_media(src_roots=staged_roots, dst_root=out_root)
        # Copy top-level aux files (README, dataset card) from first source if present.
        for name in ("README.md", "dataset_infos.json"):
            p = staged_roots[0] / name
            if p.is_file():
                shutil.copy2(p, out_root / name)
        report["merged_out_root"] = str(out_root)
    else:
        # Single source: out_root is just the staged root.
        _rm_tree(out_root)
        shutil.move(str(staged_roots[0]), str(out_root))
        report["out_root"] = str(out_root)

    # 3) Shard for Hub if requested.
    upload_root = out_root
    if not args.no_shard:
        hub_root = out_root.with_name(out_root.name + "_hub")
        _run_shard_for_hub(
            src=out_root,
            dst=hub_root,
            max_files_per_dir=int(args.max_files_per_dir),
            link="hard",
            overwrite=True,
        )
        upload_root = hub_root
        report["hub_root"] = str(hub_root)

    # 4) Upload.
    report_path = work_dir / "reports" / f"{_safe_tag(args.out_repo_id)}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote report: {report_path}", flush=True)
    print(f"Upload root: {upload_root}", flush=True)

    if args.dry_run:
        print("Dry-run: skipping upload step.", flush=True)
        return 0

    _run_batched_upload(
        repo_id=args.out_repo_id,
        local_dir=upload_root,
        private=bool(args.private),
        max_files_per_commit=int(args.max_files_per_commit),
        min_seconds=float(args.min_seconds_between_commits),
        skip_existing=bool(args.skip_existing),
        skip_existing_remote_mode=str(args.skip_existing_remote_mode),
        remote_inventory_progress_every=int(args.remote_inventory_progress_every),
        num_threads=int(args.num_threads),
        upload_heartbeat_interval=float(args.upload_heartbeat_interval),
        isolate_lfs_files_mib=float(args.isolate_lfs_files_mib),
        hf_token=args.hf_token,
        dry_run=False,
    )

    print(f"Done. Uploaded to https://huggingface.co/datasets/{args.out_repo_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

