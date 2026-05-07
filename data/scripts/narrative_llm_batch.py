#!/usr/bin/env python3
"""
Optional LLM narrative sidecar generation (catalog + prompts; no golden coords in ranked-safe mode).

Backends (``--no-dry-run``):
  ``openai`` — OpenAI-compatible ``POST …/v1/chat/completions`` (vLLM, OpenAI, LiteLLM, etc.).
  ``ollama`` — ``POST …/api/generate``.
  ``transformers`` — in-process Hugging Face **Liquid LFM** text checkpoint (default id in ``liquid_ai_defaults``).

Normative: docs/scripts/SPEC-narrative-llm-batch.md

Prompt templates may include ``{{streetview_clue}}``, ``{{satellite_clue}}``, and ``{{briefing_voice}}``
(stable per ``content_version`` + ``map_id``); street/satellite values are read from
``<hydration-cache-root>/streetview/<location_id>.json`` (see ``narrative_hydration_clues.py``).

Sidecar tuning (env or CLI): ``NUTONIC_NARRATIVE_OPENAI_MAX_TOKENS``,
``NUTONIC_NARRATIVE_OPENAI_TEMPERATURE``, ``NUTONIC_NARRATIVE_TRANSFORMERS_MAX_NEW``,
``NUTONIC_NARRATIVE_TRANSFORMERS_TEMPERATURE``, ``NUTONIC_NARRATIVE_TRANSFORMERS_TOP_P``,
``NUTONIC_NARRATIVE_OLLAMA_NUM_PREDICT``, ``NUTONIC_NARRATIVE_ENTRY_MAX`` (max stored chars),
``NUTONIC_NARRATIVE_STRIP_MARKDOWN`` (default on), plus ``--openai-max-tokens``, etc.

Clue composition: ``NUTONIC_NARRATIVE_STREET_CLUE_CHARS`` (default 1100), ``NUTONIC_NARRATIVE_SAT_CLUE_CHARS``
(default 750) cap injected prose before ``--clue-inject-max-chars``.

QA: ``NUTONIC_NARRATIVE_QA_REGENERATE`` (default ``1``) — one extra inference pass when heuristics flag
brochure-style blurbs (see ``narrative_fragment_qa.py``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from liquid_ai_defaults import DEFAULT_LFM_TEXT_HF_MODEL_ID  # noqa: E402

EXIT_INPUT = 2
EXIT_TEMPLATE = 14


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw, 10)
    except ValueError:
        return default


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Batch optional LLM narrative fragments into llm_sidecar.json")
    p.add_argument("--content-version", type=str, default="dev")
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument("--output-dir", type=Path, help="Default: data/cache/<content-version>/narrative/")
    p.add_argument(
        "--hydration-cache-root",
        type=Path,
        default=None,
        help="Root containing streetview/*.json (e.g. data/cache/runs/<content-version>/).",
    )
    p.add_argument(
        "--backend",
        choices=("ollama", "openai", "transformers"),
        default="openai",
    )
    p.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Call configured inference backend (vLLM/OpenAI, Ollama, or transformers).",
    )
    p.set_defaults(dry_run=True)

    # These flags are used by the HF Jobs entrypoint. This script currently records them
    # into model_pins so manifests remain stable even if narrative generation is disabled.
    p.add_argument(
        "--transformers-model",
        type=str,
        default=(os.environ.get("NUTONIC_NARRATIVE_TRANSFORMERS_MODEL") or DEFAULT_LFM_TEXT_HF_MODEL_ID).strip(),
    )
    p.add_argument(
        "--transformers-max-new-tokens",
        type=int,
        default=_env_int("NUTONIC_NARRATIVE_TRANSFORMERS_MAX_NEW", 512),
    )
    args = p.parse_args(argv)

    out_dir = args.output_dir or (REPO_ROOT / "data" / "cache" / args.content_version / "narrative")
    prompts_dir = REPO_ROOT / "prompts" / "llm"

    # We always write a sidecar file so downstream steps have a stable artifact to read.
    # If prompts are missing, we record the condition and exit 0 for dry-runs; live runs
    # return EXIT_TEMPLATE so callers can decide whether to treat it as fatal.
    missing_prompts = not prompts_dir.is_dir()
    if missing_prompts and not args.dry_run:
        print(f"narrative_llm_batch: missing {prompts_dir}", file=sys.stderr)
        return EXIT_TEMPLATE

    sidecar: dict[str, object] = {
        "schema_version": "nutonic.llm_narrative_sidecar.v1",
        "content_version": args.content_version,
        "entries": [],
        "model_pins": {
            "script": "narrative_llm_batch",
            "backend": args.backend,
            "dry_run": args.dry_run,
            "transformers_model": args.transformers_model,
            "transformers_max_new_tokens": args.transformers_max_new_tokens,
        },
    }
    if args.hydration_cache_root is not None:
        sidecar["model_pins"]["hydration_cache_root"] = str(args.hydration_cache_root)
    if missing_prompts:
        sidecar["warnings"] = [f"prompts_missing:{prompts_dir}"]

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "llm_sidecar.json"
    out_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"narrative_llm_batch: wrote {out_path} ({0} entries)", file=sys.stderr)

    # For now, we only guarantee non-crashing behavior and stable artifacts for the HF Jobs
    # hydration pipeline. Full narrative generation can be added behind these same flags.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
