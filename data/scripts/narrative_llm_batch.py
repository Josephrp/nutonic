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
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx
import yaml

try:
    import torch
except (ImportError, OSError):
    torch = None  # type: ignore[assignment, misc]

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
except (ImportError, OSError):
    # OSError: rare host metadata/filesystem issues during optional dependency scan (Windows).
    AutoModelForCausalLM = None  # type: ignore[assignment, misc]
    AutoTokenizer = None  # type: ignore[assignment, misc]

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from liquid_ai_defaults import DEFAULT_LFM_TEXT_HF_MODEL_ID  # noqa: E402
from validate_hint_strings import validate_caption_text  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from liquid_ai_defaults import DEFAULT_LFM_TEXT_HF_MODEL_ID  # noqa: E402
from narrative_hydration_clues import (  # noqa: E402
    hydration_clues_for_narrative_prompt,
    load_streetview_hydration_doc,
)
from narrative_fragment_qa import (  # noqa: E402
    narrative_qa_rank_key,
    narrative_qa_retry_user_suffix,
    narrative_qa_should_regenerate,
    narrative_qa_violations,
)
from narrative_sidecar_postprocess import sidecar_postprocess_plaintext  # noqa: E402
from validate_hint_strings import validate_caption_text, violations_to_jsonable  # noqa: E402

_BRIEFING_VOICES: tuple[str, ...] = (
    "Voice: terse orbital analyst — short clauses; no tourism adjectives.",
    "Voice: warm uplink relay — one vivid sensory beat tied to the clues; stay under four sentences.",
    "Voice: ground-team patch notes — practical, a little wry; no fake suspense about 'danger'.",
    "Voice: archival keeper — one phrase hinting at memory fragments or stale telemetry (no real-world politics).",
    "Voice: quiet alien partner — curious diction, cooperative tone; still plain English.",
    "Voice: mission lead — crisp stakes about calibration or reconstruction, not combat.",
)


def _briefing_voice_line(content_version: str, map_id: str) -> str:
    h = hashlib.sha256(f"{content_version}\x00{map_id}".encode("utf-8")).digest()[0]
    return _BRIEFING_VOICES[int(h) % len(_BRIEFING_VOICES)]

EXIT_INPUT = 2
EXIT_TEMPLATE = 14


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Batch optional LLM narrative fragments into llm_sidecar.json")
    p.add_argument("--content-version", type=str, default="dev")
    p.add_argument("--catalog-root", type=Path, default=REPO_ROOT / "data" / "catalog")
    p.add_argument("--output-dir", type=Path, help="Default: data/cache/<content-version>/narrative/")
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

    if args.dry_run:
        try:
            pth, _ = _load_first_prompt_md(prompts_dir)
        except FileNotFoundError:
            print(f"narrative_llm_batch: no *.md under {prompts_dir}; empty sidecar", file=sys.stderr)
            pth = None
        else:
            print(f"narrative_llm_batch: dry-run (prompt template {pth.name})", file=sys.stderr)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "llm_sidecar.json"
        out_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"narrative_llm_batch: wrote {out_path}", file=sys.stderr)
        return 0

    if args.backend == "transformers" and not (args.transformers_model or "").strip():
        print("narrative_llm_batch: --backend transformers requires a non-empty --transformers-model", file=sys.stderr)
        return EXIT_BACKEND

    try:
        prompt_path, template = _load_first_prompt_md(prompts_dir)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return EXIT_TEMPLATE
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "llm_sidecar.json"
    out_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"narrative_llm_batch: wrote {out_path} ({len(entries)} entries)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
