#!/usr/bin/env python3
"""
Optional LLM polish pass for useful_hints (HTTP backends only; no torch in-process).

Normative: docs/scripts/SPEC-generate-useful-hints-llm.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

EXIT_INPUT = 2
EXIT_POLICY = 8


def _sector_summary(geo_path: Path | None) -> str:
    if geo_path is None or not geo_path.is_file():
        return "no_geo_context"
    raw = json.loads(geo_path.read_text(encoding="utf-8"))
    blob = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Optional LLM polish for useful_hints (torch-free client)")
    p.add_argument("--geo-context-dir", type=Path, help="Per-location geo_context JSON directory")
    p.add_argument("--useful-hints-dir", type=Path, help="Compiled useful_hints JSON directory")
    p.add_argument("--content-version", type=str, default="")
    p.add_argument("--system-prompt", type=Path, default=REPO_ROOT / "prompts" / "llm" / "useful_hints_system.md")
    p.add_argument("--tier-policy", type=Path, help="Tier policy YAML (passed to validate_hints after polish)")
    p.add_argument("--backend", choices=("ollama", "openai", "vllm", "lfm_vl_http", "hf"), default="ollama")
    p.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Allow network when combined with --enable-llm-polish (backend wiring not in this stub).",
    )
    p.set_defaults(dry_run=True)
    p.add_argument(
        "--enable-llm-polish",
        action="store_true",
        help="When set with --no-dry-run, call backend (not implemented in this stub — use inference workers).",
    )
    args = p.parse_args(argv)
    if args.enable_llm_polish and args.dry_run:
        print("generate_useful_hints_llm: use --no-dry-run with --enable-llm-polish", file=sys.stderr)
        return EXIT_INPUT
    sample_geo = None
    if args.geo_context_dir and args.geo_context_dir.is_dir():
        for c in sorted(args.geo_context_dir.glob("*.json")):
            sample_geo = c
            break
    summary = _sector_summary(sample_geo)
    print(f"sector_summary_sha16={summary} backend={args.backend}", file=sys.stderr)
    if args.dry_run:
        print("generate_useful_hints_llm: dry-run complete (no network)", file=sys.stderr)
        return 0
    if args.enable_llm_polish:
        print(
            "generate_useful_hints_llm: --enable-llm-polish requires a deployed text backend; "
            "wire Ollama/OpenAI per SPEC §5 (out of scope for this repository stub).",
            file=sys.stderr,
        )
        return EXIT_POLICY
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
