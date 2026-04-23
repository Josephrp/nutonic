#!/usr/bin/env python3
"""
Shard high-file-count media directories for Hugging Face Hub **dataset** uploads.

Problem
-------
The Hub enforces a **hard limit of 10_000 entries per directory** in the underlying git tree.
LFM-VL SFT builds place almost all PNGs directly under ``images/`` (and similarly under
``mapbox_stills/``, optionally ``overlays/``), and one JSON sidecar per tile under
``metadata/``. Full runs exceed the Hub limit (10k **files per directory**); commits fail with
HTTP **400** for ``/images/``, ``/mapbox_stills/``, and/or ``/metadata/``.

This script copies the dataset to a new root and:

* When a folder has **more than** ``--max-files-per-dir`` direct children files, moves them into
  ``<dir>/s00000/``, ``<dir>/s00001/``, … (default **8000** children per shard, under 10k).
  Applies to ``images/*.png``, ``mapbox_stills/*.png``, ``overlays/*.png``, and ``metadata/*.json``.
* Re-writes **relative path strings** inside ``data/*.jsonl`` and every ``metadata/**/*.json``
  so they match the new layout (e.g. ``images/poi_....png`` → ``images/s00003/poi_....png``,
  ``metadata/poi_....json`` → ``metadata/s00012/poi_....json`` when sharded).

Shard assignment is **deterministic** (sorted filenames, contiguous blocks) so re-runs are
stable and easy to reason about.

Usage::

  python data/scripts/shard_lfm_vl_dataset_for_hub.py \\
    --src ./data/downloads/lfm_vl_sft_full \\
    --dst ./data/downloads/lfm_vl_sft_full_hub \\
    --max-files-per-dir 8000

Then upload ``--dst`` (e.g. ``upload_hf_dataset_batched.py`` or ``hf upload-large-folder``).

Prerequisites: standard library only (no extra pip packages).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

# Intermediate directory names we reserve for sharding (must not collide with flat basenames).
_SHARD_DIR_RE = re.compile(r"^s\d{5}$")

_IMAGE_SUFFIX = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_JSON_SUFFIX = frozenset({".json"})

# (directory name under dataset root, allowed file suffixes for flat children to shard/copy)
_SHARD_TARGETS: tuple[tuple[str, frozenset[str]], ...] = (
    ("images", _IMAGE_SUFFIX),
    ("mapbox_stills", _IMAGE_SUFFIX),
    ("overlays", _IMAGE_SUFFIX),
    ("metadata", _JSON_SUFFIX),
)


def _list_flat_files(media_root: Path, suffixes: frozenset[str]) -> list[Path]:
    """Direct files with allowed suffix only (ignore subdirectories)."""
    if not media_root.is_dir():
        return []
    out: list[Path] = []
    for child in media_root.iterdir():
        if child.is_file() and child.suffix.lower() in suffixes:
            out.append(child)
    return sorted(out, key=lambda p: p.name)


def _compute_shards(files: list[Path], max_per: int) -> list[tuple[Path, str]]:
    """
    Return (src_path, new_relative_posix_under_media_dir) for each file.

    new_relative: ``s00007/basename.png`` (no leading media prefix).
    """
    if not files:
        return []
    n = len(files)
    n_shards = max(1, (n + max_per - 1) // max_per)
    assignments: list[tuple[Path, str]] = []
    for idx, p in enumerate(files):
        shard = min(idx // max_per, n_shards - 1)
        rel = f"s{shard:05d}/{p.name}"
        assignments.append((p, rel))
    return assignments


def _copy_or_link(src: Path, dst: Path, *, link: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {dst}")
    if link == "hard":
        os.link(src, dst)
    else:
        shutil.copy2(src, dst)


def _materialize_shard_trees(
    src_root: Path,
    dst_root: Path,
    *,
    max_per: int,
    link: str,
) -> dict[str, str]:
    """
    Copy/link files under shard targets; return merged path remap old_posix -> new_posix.

    If a directory has at most ``max_per`` matching flat files, files are copied flat
    (no remap). If it has more, they are spread into ``sNNNNN/`` subfolders (remap entries).
    """
    remap: dict[str, str] = {}
    for media, suffixes in _SHARD_TARGETS:
        mdir = src_root / media
        if not mdir.is_dir():
            continue
        dst_media = dst_root / media
        dst_media.mkdir(parents=True, exist_ok=True)

        files = _list_flat_files(mdir, suffixes)
        shard_subdirs = [c for c in mdir.iterdir() if c.is_dir() and _SHARD_DIR_RE.match(c.name)]
        if files and shard_subdirs:
            raise RuntimeError(
                f"{mdir}: cannot mix flat files with sNNNNN shard directories. "
                "Use a single layout (all flat under this folder, or only shard subfolders)."
            )

        if not files:
            shutil.copytree(mdir, dst_media, dirs_exist_ok=True)
            continue

        if len(files) <= max_per:
            for src_file in files:
                dest = dst_media / src_file.name
                _copy_or_link(src_file, dest, link=link)
            continue

        for src_file, new_under_media in _compute_shards(files, max_per):
            old_posix = f"{media}/{src_file.name}"
            new_posix = f"{media}/{new_under_media}"
            remap[old_posix] = new_posix
            dest = dst_root / new_posix
            _copy_or_link(src_file, dest, link=link)

    return remap


def _remap_obj(obj: Any, remap: dict[str, str]) -> Any:
    """Recursively replace exact string values found in ``remap``."""
    if isinstance(obj, str):
        return remap.get(obj, obj)
    if isinstance(obj, list):
        return [_remap_obj(x, remap) for x in obj]
    if isinstance(obj, dict):
        return {k: _remap_obj(v, remap) for k, v in obj.items()}
    return obj


def _rewrite_json_file(src: Path, dst: Path, remap: dict[str, str]) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(_remap_obj(data, remap), indent=2), encoding="utf-8")


def _rewrite_jsonl_stream(src: Path, dst: Path, remap: dict[str, str]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line_no, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON at {src}:{line_no}") from e
            fout.write(json.dumps(_remap_obj(obj, remap), ensure_ascii=False) + "\n")


def _copy_aux_tree(src_root: Path, dst_root: Path, *, skip_names: set[str]) -> None:
    """Copy top-level entries except shard-managed media dirs handled separately."""
    for entry in sorted(src_root.iterdir(), key=lambda p: p.name):
        if entry.name in skip_names:
            continue
        dest = dst_root / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, dest)


def _verify_max_files_per_dir(root: Path, limit: int) -> list[tuple[str, int]]:
    """Return list of (posix_dir_path, file_count) for directories exceeding ``limit``."""
    bad: list[tuple[str, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        n_files = len(filenames)
        if n_files > limit:
            rel = Path(dirpath).relative_to(root).as_posix() or "."
            bad.append((rel, n_files))
    return sorted(bad, key=lambda x: -x[1])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", type=Path, default=None, help="Built dataset root (e.g. lfm_vl_sft_full)")
    p.add_argument("--dst", type=Path, default=None, help="Output root; created/replaced")
    p.add_argument(
        "--max-files-per-dir",
        type=int,
        default=8000,
        help="Max files per shard directory (Hub hard limit is 10000; default 8000)",
    )
    p.add_argument(
        "--link",
        choices=("none", "hard"),
        default="none",
        help="Use hardlinks instead of copying PNG bytes (same filesystem only)",
    )
    p.add_argument(
        "--verify-only",
        type=Path,
        default=None,
        metavar="ROOT",
        help="Scan ROOT and print directories with more than --max-files-per-dir files, then exit",
    )
    p.add_argument(
        "--overwrite-dst",
        action="store_true",
        help="Delete --dst if it exists before writing",
    )
    args = p.parse_args()

    if args.verify_only is None and (args.src is None or args.dst is None):
        p.error("--src and --dst are required unless --verify-only is used")

    if args.verify_only is not None:
        root = args.verify_only.resolve()
        bad = _verify_max_files_per_dir(root, args.max_files_per_dir)
        if not bad:
            print(f"OK: no directory under {root} has more than {args.max_files_per_dir} files.", flush=True)
            return 0
        print(f"Directories exceeding {args.max_files_per_dir} files:")
        for rel, n in bad[:50]:
            print(f"  {n:6d}  {rel}")
        if len(bad) > 50:
            print(f"  ... and {len(bad) - 50} more")
        return 1

    src_root = args.src.resolve()
    dst_root = args.dst.resolve()
    if not src_root.is_dir():
        print(f"Missing source directory: {src_root}", file=sys.stderr)
        return 2
    if dst_root == src_root:
        print("--dst must differ from --src (non-destructive copy).", file=sys.stderr)
        return 2

    max_per = max(1, min(args.max_files_per_dir, 10_000))

    if dst_root.exists():
        if not args.overwrite_dst:
            print(f"Destination exists: {dst_root} (pass --overwrite-dst to replace)", file=sys.stderr)
            return 2
        shutil.rmtree(dst_root)

    dst_root.mkdir(parents=True, exist_ok=True)

    # 1) Copy everything except dirs we rebuild (images, mapbox_stills, overlays, metadata)
    skip = {name for name, _sfx in _SHARD_TARGETS}
    for media, _sfx in _SHARD_TARGETS:
        if (src_root / media).is_dir():
            (dst_root / media).mkdir(parents=True, exist_ok=True)

    _copy_aux_tree(src_root, dst_root, skip_names=skip)

    # 2) Materialize sharded (or flat) images / mapbox_stills / overlays / metadata
    remap = _materialize_shard_trees(src_root, dst_root, max_per=max_per, link=args.link)

    # 3) Rewrite JSONL under data/
    data_src = src_root / "data"
    if data_src.is_dir():
        data_dst = dst_root / "data"
        data_dst.mkdir(parents=True, exist_ok=True)
        for js in sorted(data_src.glob("*.jsonl")):
            _rewrite_jsonl_stream(js, data_dst / js.name, remap)

    # 4) Rewrite metadata JSON (image paths etc.); emit to mirrored or remapped paths under dst
    meta_src = src_root / "metadata"
    if meta_src.is_dir():
        for js in sorted(meta_src.rglob("*.json")):
            if not js.is_file():
                continue
            rel = js.relative_to(meta_src)
            if len(rel.parts) == 1:
                key = f"metadata/{rel.name}"
                dest_path = dst_root / Path(remap.get(key, key))
            else:
                dest_path = dst_root / "metadata" / rel
            _rewrite_json_file(js, dest_path, remap)

    # 5) Append layout note to README if present
    readme_dst = dst_root / "README.md"
    if readme_dst.is_file():
        note = (
            "\n\n---\n\n## Hub layout (sharded)\n\n"
            "This snapshot was processed with "
            "`python data/scripts/shard_lfm_vl_dataset_for_hub.py` so that "
            f"``images/``, ``mapbox_stills/``, ``overlays/``, and ``metadata/`` use at most **{max_per}** "
            "files per leaf directory (Hub git limit: 10k files per directory). "
            "JSONL paths may include ``sNNNNN/`` shard segments where needed.\n"
        )
        readme_dst.write_text(readme_dst.read_text(encoding="utf-8") + note, encoding="utf-8")

    print(f"Remapped {len(remap)} media paths.")
    print(f"Output: {dst_root}")

    bad = _verify_max_files_per_dir(dst_root, max_per)
    if bad:
        print("WARNING: post-verify still found over-limit directories:", file=sys.stderr)
        for rel, n in bad[:20]:
            print(f"  {n:6d}  {rel}", file=sys.stderr)
        return 1

    print(f"Verified: every directory under {dst_root} has at most {max_per} files.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
