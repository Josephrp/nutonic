#!/usr/bin/env python3
"""
Optional LLM narrative sidecar generation (catalog + prompts; no golden coords in ranked-safe mode).

Normative: docs/scripts/SPEC-narrative-llm-batch.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

EXIT_INPUT = 2
EXIT_TEMPLATE = 14


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Batch optional LLM narrative fragments into llm_sidecar.json")
    p.add_argument("--content-version", type=str, default="dev")
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument("--output-dir", type=Path, help="Default: data/cache/<content-version>/narrative/")
    p.add_argument("--backend", choices=("ollama", "openai"), default="ollama")
    p.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Call backend (not implemented in this stub).",
    )
    p.set_defaults(dry_run=True)
    args = p.parse_args(argv)
    out_dir = args.output_dir or (REPO_ROOT / "data" / "cache" / args.content_version / "narrative")
    prompts_dir = REPO_ROOT / "prompts" / "llm"
    if not prompts_dir.is_dir():
        if args.dry_run:
            print(f"narrative_llm_batch: prompts/llm missing ({prompts_dir}); writing empty sidecar", file=sys.stderr)
        else:
            print(f"narrative_llm_batch: missing {prompts_dir}", file=sys.stderr)
            return EXIT_TEMPLATE
    sidecar = {
        "schema_version": "nutonic.llm_narrative_sidecar.v1",
        "content_version": args.content_version,
        "entries": [],
        "model_pins": {
            "script": "narrative_llm_batch",
            "backend": args.backend,
            "dry_run": args.dry_run,
        },
    }
    if not args.dry_run:
        print("narrative_llm_batch: live LLM batch not implemented in stub", file=sys.stderr)
        return EXIT_TEMPLATE
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "llm_sidecar.json"
    out_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"narrative_llm_batch: wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
