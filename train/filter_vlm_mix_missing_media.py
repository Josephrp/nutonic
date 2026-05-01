#!/usr/bin/env python3
"""
Drop Parquet rows whose image paths are missing under ``--image-root``.

Use when you **cannot** mirror the full Hub tree but still want to train on the subset
that exists locally. This **changes the data distribution** (biased toward whatever
finished downloading first); prefer completing ``download_lfm_vl_training_dataset.py``
for serious runs.

Path rules match ``verify_vlm_mix_assets.py`` (messages image parts; optional metadata paths).

Example::

  python train/filter_vlm_mix_missing_media.py \\
    --mix-dir /data/nutonic/vlm_mix_parquet \\
    --image-root /data/nutonic/sat-vl-sft-training-ready-v1 \\
    --out-dir /data/nutonic/vlm_mix_parquet_filtered

Then point training at ``--out-dir`` and re-run ``verify_vlm_mix_assets.py`` on it.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_verify_helpers():
    """Load private helpers from verify script without package imports."""
    path = Path(__file__).resolve().parent / "verify_vlm_mix_assets.py"
    spec = importlib.util.spec_from_file_location("verify_vlm_mix_assets", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._message_image_rel_paths, mod._all_image_rel_paths_for_row


_message_image_rel_paths, _all_image_rel_paths_for_row = _load_verify_helpers()


def _row_media_complete(row: dict, root: Path, *, include_metadata: bool) -> bool:
    rels = (
        _all_image_rel_paths_for_row(row)
        if include_metadata
        else _message_image_rel_paths(row)
    )
    for rel in rels:
        rel = rel.replace("\\", "/").strip()
        if not rel:
            continue
        if rel.startswith(("http://", "https://", "/")):
            continue
        if not (root / rel).is_file():
            return False
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--mix-dir", type=Path, required=True, help="Input directory of *.parquet shards.")
    p.add_argument("--image-root", type=Path, required=True, help="Local dataset root to test paths against.")
    p.add_argument("--out-dir", type=Path, required=True, help="Output directory for filtered *.parquet (created).")
    p.add_argument("--overwrite", action="store_true", help="Remove existing *.parquet under out-dir before writing.")
    p.add_argument(
        "--include-metadata-paths",
        action="store_true",
        help="Also require metadata.image_paths and metadata.analysis_image_path (same as verify).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mix_dir = args.mix_dir.expanduser().resolve()
    root = args.image_root.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()

    if not mix_dir.is_dir():
        print(f"Mix directory not found: {mix_dir}", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"image_root not found: {root}", file=sys.stderr)
        return 2

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        print(f"Install pyarrow: {e}", file=sys.stderr)
        return 2

    inputs = sorted(mix_dir.glob("*.parquet"))
    if not inputs:
        print(f"No *.parquet under {mix_dir}", file=sys.stderr)
        return 2

    existing = list(out_dir.glob("*.parquet")) if out_dir.is_dir() else []
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

    out_dir.mkdir(parents=True, exist_ok=True)

    total_in = 0
    total_out = 0
    empty_shards = 0

    for in_path in inputs:
        table = pq.read_table(in_path)
        try:
            rows = table.to_pylist()
        except Exception:
            rows = table.to_pandas().to_dict("records")

        kept = [
            r
            for r in rows
            if _row_media_complete(
                r,
                root,
                include_metadata=bool(args.include_metadata_paths),
            )
        ]
        n_in = len(rows)
        n_out = len(kept)
        total_in += n_in
        total_out += n_out

        if n_out == 0:
            empty_shards += 1
            print(f"  skip {in_path.name}: 0/{n_in} rows kept (all dropped)", flush=True)
            continue

        out_path = out_dir / in_path.name
        pq.write_table(pa.Table.from_pylist(kept), out_path, compression="snappy")
        print(
            f"  {in_path.name}: kept {n_out:,}/{n_in:,} rows -> {out_path.name}",
            flush=True,
        )

    print(
        f"\nDone. Total kept {total_out:,}/{total_in:,} rows across "
        f"{len(inputs) - empty_shards:,} non-empty shard(s); "
        f"{empty_shards} shard(s) had no keepable rows (no file written).",
        flush=True,
    )
    print(f"Filtered mix: {out_dir}", flush=True)
    if total_out == 0:
        print("Warning: no rows kept; check --image-root and downloads.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
