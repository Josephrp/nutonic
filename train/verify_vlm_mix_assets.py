#!/usr/bin/env python3
"""
Fail-fast check that image paths referenced in a Parquet mix exist under ``image_root``.

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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--mix-dir", type=Path, required=True, help="Directory of *.parquet mix shards.")
    p.add_argument("--image-root", type=Path, required=True, help="Dataset root (contains images/, etc.).")
    p.add_argument("--max-rows", type=int, default=500, help="Max table rows to scan from the mix.")
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
        from datasets import load_dataset
    except ImportError as e:
        print("Install datasets: pip install datasets", file=sys.stderr)
        return 2

    data_files = [str(p) for p in parquets]
    ds = load_dataset("parquet", data_files=data_files, split="train")
    n = min(max(0, int(args.max_rows)), len(ds))

    missing: list[str] = []
    checked_files: set[str] = set()
    for i in range(n):
        row = ds[i]
        for rel in _message_image_rel_paths(row):
            abs_path = root / rel
            key = str(abs_path)
            if key in checked_files:
                continue
            checked_files.add(key)
            if not abs_path.is_file():
                missing.append(key)
                if len(missing) >= 12:
                    break
        if len(missing) >= 12:
            break

    print(f"Scanned {n:,} row(s) from {len(parquets)} shard(s); {len(checked_files):,} unique relative image path(s) checked.", flush=True)

    if not missing:
        print("All checked image paths exist under image_root.", flush=True)
        return 0

    print("Missing files (first batch):", file=sys.stderr)
    for m in missing:
        print(f"  {m}", file=sys.stderr)
    print(
        "\nDownload the dataset files into the **same** directory you pass as --image-root "
        f"(so e.g. {root}/images/... exists). For the main corpus:\n"
        f"  python train/download_lfm_vl_training_dataset.py --out-dir {root}\n"
        "If your mix references other Hub datasets, download/merge their image trees into that root as well.\n"
        "Optional: HF_HUB_ENABLE_HF_TRANSFER=1 for faster Hub pulls.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
