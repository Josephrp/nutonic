#!/usr/bin/env python3
"""Aggregate ``judge_pack.jsonl`` from Patagonia TiM E2E runs (no external LLM).

Use this as a scaffold: pipe rows into your rubric / LLM judge, or extend this script.

Example:

  python tools/summarize_patagonia_judge_pack.py eval_out/judge_pack.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("judge_pack", type=Path, help="Path to judge_pack.jsonl")
    args = p.parse_args(argv)
    path = args.judge_pack
    if not path.is_file():
        print(f"not found: {path}", file=sys.stderr)
        return 1

    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    by_pair: dict[str, list[float]] = defaultdict(list)
    errors = sum(1 for r in rows if r.get("error"))

    for r in rows:
        resp = r.get("contrastive_responsiveness_vs_flip")
        grp = r.get("contrastive_pair_group")
        if isinstance(resp, (int, float)) and isinstance(grp, str) and grp:
            by_pair[grp].append(float(resp))

    pair_means = {k: round(statistics.mean(v), 4) for k, v in by_pair.items() if v}

    out = {
        "path": str(path.resolve()),
        "row_count": len(rows),
        "error_rows": errors,
        "contrastive_pair_mean_responsiveness": pair_means,
        "note": "Extend this script with LLM rubric scoring over caption + tim_compact fields.",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
