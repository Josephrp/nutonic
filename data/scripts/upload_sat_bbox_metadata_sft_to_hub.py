#!/usr/bin/env python3
"""
Upload a **sat-bbox metadata SFT** build (``build_sat_bbox_metadata_sft.py`` output) to Hugging Face.

Steps
-----
1. If any Hub-managed media directory has more than ``--max-files-per-dir`` **direct** file
   children (same rule as ``shard_lfm_vl_dataset_for_hub.py``), materialize a sibling
   ``<src_stem>_hub/`` tree with ``sNNNNN/`` shards and **rewritten** paths inside
   ``data/*.jsonl`` and ``metadata/**/*.json``.
2. Upload the Hub-safe tree (either ``--src`` or the ``*_hub`` staging dir) using
   ``upload_hf_dataset_batched.py`` (default) or ``lfm_vl_sft_dataset.hf_upload.upload_dataset_folder``.

Requires ``HF_TOKEN`` or ``HUGGING_FACE_HUB_TOKEN`` with write access to ``--repo-id``.

With ``--skip-existing``, the batched uploader lists the remote repo **per top-level prefix**
(``data/``, ``images/``, …) derived from your local tree so resume does not block on one giant
recursive API walk. Use ``--skip-existing-remote-mode full`` only if you need a full-repo scan.

Example::

  export HF_TOKEN=hf_...
  python data/scripts/upload_sat_bbox_metadata_sft_to_hub.py \\
    --src ./data/downloads/sat_bbox_metadata_sft_full \\
    --repo-id NuTonic/sat-bbox-metadata-sft-v1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

# Keep in sync with ``shard_lfm_vl_dataset_for_hub._SHARD_TARGETS`` top-level dir names.
_HUB_SHARD_MEDIA = (
    "images",
    "mapbox_stills",
    "overlays",
    "analysis_images",
    "metadata",
)
_DEFAULT_MAX_FILES = 8000


def _flat_file_count(dirpath: Path) -> int:
    if not dirpath.is_dir():
        return 0
    return sum(1 for p in dirpath.iterdir() if p.is_file())


def hub_sharding_recommended(src: Path, *, max_flat_files: int) -> bool:
    """True when ``shard_lfm_vl_dataset_for_hub`` should run before upload."""
    root = src.resolve()
    for name in _HUB_SHARD_MEDIA:
        if _flat_file_count(root / name) > max_flat_files:
            return True
    # Sat-bbox metadata SFT: one JSON per row under metadata/sft_metadata_rows/ (not metadata/ root).
    sft_rows = root / "metadata" / "sft_metadata_rows"
    if _flat_file_count(sft_rows) > max_flat_files:
        return True
    return False


def _default_staging_dir(src: Path) -> Path:
    return src.resolve().parent / f"{src.resolve().name}_hub"


def _run_shard(*, src: Path, dst: Path, max_files: int, link: str, overwrite: bool) -> None:
    shard_script = _SCRIPTS / "shard_lfm_vl_dataset_for_hub.py"
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
        str(max_files),
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
    hf_token: str | None,
    dry_run: bool,
) -> None:
    batched = _SCRIPTS / "upload_hf_dataset_batched.py"
    if not batched.is_file():
        raise FileNotFoundError(f"Missing: {batched}")
    cmd = [
        sys.executable,
        str(batched),
        repo_id,
        str(local_dir.resolve()),
        "--repo-type",
        "dataset",
        "--max-files-per-commit",
        str(max_files_per_commit),
        "--min-seconds-between-commits",
        str(min_seconds),
        "--num-threads",
        str(num_threads),
    ]
    if private:
        cmd.append("--private")
    if skip_existing:
        cmd.append("--skip-existing")
        cmd.extend(["--skip-existing-remote-mode", skip_existing_remote_mode])
        cmd.extend(["--remote-inventory-progress-every", str(remote_inventory_progress_every)])
    if dry_run:
        cmd.append("--dry-run")
    if hf_token:
        cmd.extend(["--hf-token", hf_token])
    subprocess.run(cmd, check=True)


def _run_simple_upload(*, local_dir: Path, repo_id: str, private: bool) -> None:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    from lfm_vl_sft_dataset.hf_upload import upload_dataset_folder

    upload_dataset_folder(local_dir.resolve(), repo_id, private=private)


def resolve_upload_directory(
    *,
    src: Path,
    staging_dir: Path | None,
    max_files_per_dir: int,
    force_shard: bool,
    no_shard: bool,
    shard_link: str,
    overwrite_staging: bool,
) -> Path:
    """Return the local directory tree to upload (possibly a ``*_hub`` shard copy)."""
    src = src.resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"--src is not a directory: {src}")

    need_shard = (not no_shard) and (force_shard or hub_sharding_recommended(src, max_flat_files=max_files_per_dir))
    if not need_shard:
        return src

    dst = (staging_dir or _default_staging_dir(src)).resolve()
    if dst == src:
        raise ValueError("--staging-dir must differ from --src when sharding.")

    if dst.is_dir() and not overwrite_staging:
        print(
            f"Reusing existing Hub staging layout at {dst} (pass --overwrite-staging to rebuild from --src).",
            flush=True,
        )
        return dst

    print(
        f"Sharding for Hub (>{max_files_per_dir} flat files in a managed dir, or --force-shard): "
        f"{src} -> {dst}",
        flush=True,
    )
    _run_shard(src=src, dst=dst, max_files=max_files_per_dir, link=shard_link, overwrite=overwrite_staging)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--src",
        type=Path,
        required=True,
        help="Output root from build_sat_bbox_metadata_sft.py (contains data/, images/, …).",
    )
    ap.add_argument(
        "--repo-id",
        required=True,
        help="Hugging Face dataset repo id (org/name).",
    )
    ap.add_argument(
        "--staging-dir",
        type=Path,
        default=None,
        help=f"Shard output directory (default: sibling ``<src_name>_hub`` next to --src).",
    )
    ap.add_argument(
        "--max-files-per-dir",
        type=int,
        default=_DEFAULT_MAX_FILES,
        help="Shard when a managed top-level dir has more than this many direct files (default 8000; Hub hard limit 10000).",
    )
    ap.add_argument(
        "--force-shard",
        action="store_true",
        help="Always run shard_lfm_vl_dataset_for_hub to staging before upload (even if counts are low).",
    )
    ap.add_argument(
        "--no-shard",
        action="store_true",
        help="Never shard; upload --src as-is (Hub will reject if any directory exceeds ~10k files).",
    )
    ap.add_argument(
        "--overwrite-staging",
        action="store_true",
        help="If staging exists, delete it and re-shard from --src.",
    )
    ap.add_argument(
        "--shard-link",
        choices=("none", "hard"),
        default="hard",
        help="Pass-through to shard script (default hard: same-filesystem hardlinks).",
    )
    ap.add_argument("--private", action="store_true", help="Create dataset repo as private if missing.")
    ap.add_argument(
        "--no-batched-upload",
        action="store_true",
        help="Use huggingface_hub upload_folder / upload_large_folder instead of upload_hf_dataset_batched.py.",
    )
    ap.add_argument(
        "--max-files-per-commit",
        type=int,
        default=8000,
        help="Only for batched upload (default 8000).",
    )
    ap.add_argument(
        "--min-seconds-between-commits",
        type=float,
        default=15.0,
        help="Only for batched upload.",
    )
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Only for batched upload: skip files already on the Hub.",
    )
    ap.add_argument(
        "--skip-existing-remote-mode",
        default="prefixes",
        choices=("prefixes", "full"),
        help="Only with --skip-existing: forwarded to upload_hf_dataset_batched.py.",
    )
    ap.add_argument(
        "--remote-inventory-progress-every",
        type=int,
        default=25_000,
        help="Only with --skip-existing: log every N remote paths (0 disables).",
    )
    ap.add_argument(
        "--num-threads",
        type=int,
        default=4,
        help="Only for batched upload (LFS preupload threads; lower can reduce stalls).",
    )
    ap.add_argument("--hf-token", default=None, help="Override HF_TOKEN for batched upload.")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions only; for batched mode forwards --dry-run to the uploader.",
    )
    args = ap.parse_args()

    if args.no_shard and args.force_shard:
        print("error: --no-shard and --force-shard are mutually exclusive", file=sys.stderr)
        return 2

    try:
        upload_root = resolve_upload_directory(
            src=args.src,
            staging_dir=args.staging_dir,
            max_files_per_dir=args.max_files_per_dir,
            force_shard=bool(args.force_shard),
            no_shard=bool(args.no_shard),
            shard_link=args.shard_link,
            overwrite_staging=bool(args.overwrite_staging),
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"Upload root: {upload_root}", flush=True)

    if args.dry_run and args.no_batched_upload:
        print("Dry-run: would upload via upload_dataset_folder (no network).", flush=True)
        return 0

    if args.dry_run and not args.no_batched_upload:
        _run_batched_upload(
            repo_id=args.repo_id,
            local_dir=upload_root,
            private=args.private,
            max_files_per_commit=args.max_files_per_commit,
            min_seconds=args.min_seconds_between_commits,
            skip_existing=args.skip_existing,
            skip_existing_remote_mode=args.skip_existing_remote_mode,
            remote_inventory_progress_every=args.remote_inventory_progress_every,
            num_threads=args.num_threads,
            hf_token=args.hf_token,
            dry_run=True,
        )
        return 0

    if args.no_batched_upload:
        _run_simple_upload(local_dir=upload_root, repo_id=args.repo_id, private=args.private)
    else:
        _run_batched_upload(
            repo_id=args.repo_id,
            local_dir=upload_root,
            private=args.private,
            max_files_per_commit=args.max_files_per_commit,
            min_seconds=args.min_seconds_between_commits,
            skip_existing=args.skip_existing,
            skip_existing_remote_mode=args.skip_existing_remote_mode,
            remote_inventory_progress_every=args.remote_inventory_progress_every,
            num_threads=args.num_threads,
            hf_token=args.hf_token,
            dry_run=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
