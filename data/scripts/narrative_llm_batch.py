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
EXIT_BACKEND = 15

_tf_model_cache: dict[str, object] = {}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)).strip())
    except ValueError:
        return default


def _bool_env(name: str, *, default: bool) -> bool:
    raw = (os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _normalize_openai_v1_base(url: str) -> str:
    u = url.strip().rstrip("/")
    if u.endswith("/v1"):
        return u
    return f"{u}/v1"


def _load_first_prompt_md(prompts_dir: Path) -> tuple[Path, str]:
    files = sorted(prompts_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No prompts in {prompts_dir}")
    p = files[0]
    return p, p.read_text(encoding="utf-8")


def _hydration_included_filter_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    raw = (os.environ.get("NUTONIC_HYDRATION_INCLUDED_LOCATION_IDS") or "").strip()
    if not raw:
        return rows
    only = frozenset(p.strip() for p in raw.split(",") if p.strip())
    if not only:
        return rows
    return [r for r in rows if r.get("location_id") in only]


def _iter_location_rows(catalog_root: Path) -> list[dict[str, str]]:
    loc = catalog_root / "locations"
    if not loc.is_dir():
        return []
    rows: list[dict[str, str]] = []
    for yp in sorted(loc.glob("*.yaml")):
        data = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
        lid = str(data.get("location_id") or yp.stem)
        mid = str(data.get("map_id") or lid)
        rows.append({"location_id": lid, "map_id": mid})
    return rows


def _ollama_generate(
    *,
    base_url: str,
    model: str,
    prompt: str,
    timeout_sec: float,
    num_predict: int | None,
) -> str:
    url = base_url.rstrip("/") + "/api/generate"
    body: dict[str, object] = {"model": model, "prompt": prompt, "stream": False}
    if num_predict is not None and num_predict > 0:
        body["options"] = {"num_predict": int(num_predict)}
    with httpx.Client(timeout=timeout_sec) as client:
        r = client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
    return str(data.get("response", "")).strip()


def openai_compatible_chat_text(
    *,
    openai_v1_base: str,
    model: str,
    prompt: str,
    api_key: str | None,
    timeout_sec: float,
    max_tokens: int,
    temperature: float,
) -> str:
    """Single-turn user message → assistant text (vLLM / OpenAI-compatible servers)."""
    root = _normalize_openai_v1_base(openai_v1_base)
    url = f"{root}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    temp = min(2.0, max(0.0, float(temperature)))
    body: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temp,
        "max_tokens": max(16, min(int(max_tokens), 8192)),
    }
    with httpx.Client(timeout=timeout_sec) as client:
        r = client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"openai chat: missing choices in response keys={list(data)[:12]}")
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
    # Some servers return legacy text field
    t = choices[0].get("text") if isinstance(choices[0], dict) else None
    if isinstance(t, str):
        return t.strip()
    raise RuntimeError("openai chat: could not parse assistant message from response")


def _transformers_tokenize_user_prompt(tok: object, prompt: str) -> dict[str, object]:
    """
    Prefer ``apply_chat_template`` for Instruct checkpoints; raw string tokenization otherwise.

    Raw document-style tokenization often yields degenerate generations (empty or instruction echoes)
    on chat-tuned models.
    """
    chat_template = getattr(tok, "chat_template", None)
    apply_fn = getattr(tok, "apply_chat_template", None)
    if chat_template is not None and callable(apply_fn):
        try:
            out = apply_fn(
                [{"role": "user", "content": prompt}],
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            )
            if isinstance(out, dict):
                return out
            return dict(out)
        except Exception:
            pass
    enc = getattr(tok, "__call__", None)
    if enc is None:
        raise RuntimeError("narrative_llm_batch: tokenizer is not callable")
    return enc(prompt, return_tensors="pt")


def _transformers_generate_text(
    *,
    model_id: str,
    prompt: str,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
) -> str:
    if torch is None or AutoModelForCausalLM is None or AutoTokenizer is None:
        raise RuntimeError(
            'narrative_llm_batch: --backend transformers needs torch+transformers (e.g. pip install "transformers>=4.44")'
        )

    if _tf_model_cache.get("model_id") != model_id:
        tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        try:
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                device_map="auto",
                dtype=torch.bfloat16,
                trust_remote_code=True,
            )
        except TypeError:
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                device_map="auto",
                torch_dtype=torch.bfloat16,
                trust_remote_code=True,
            )
        if getattr(tok, "pad_token_id", None) is None and tok.eos_token_id is not None:
            tok.pad_token = tok.eos_token
        _tf_model_cache.clear()
        _tf_model_cache["model_id"] = model_id
        _tf_model_cache["tokenizer"] = tok
        _tf_model_cache["model"] = model

    tok = _tf_model_cache["tokenizer"]
    model = _tf_model_cache["model"]
    inputs = _transformers_tokenize_user_prompt(tok, prompt)
    inputs = {k: v.to(model.device) for k, v in inputs.items() if hasattr(v, "to")}
    temp = min(2.0, max(0.05, float(temperature)))
    tp = min(1.0, max(0.05, float(top_p)))
    with torch.inference_mode():
        out_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temp,
            top_p=tp,
            pad_token_id=tok.pad_token_id,
        )
    in_len = inputs["input_ids"].shape[1]
    new_tokens = out_ids[0, in_len:]
    return tok.decode(new_tokens, skip_special_tokens=True).strip()


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
    p.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip())
    p.add_argument("--ollama-model", default=os.environ.get("NUTONIC_OLLAMA_MODEL", "llama3.2").strip())
    p.add_argument(
        "--openai-base",
        default=os.environ.get("NUTONIC_NARRATIVE_OPENAI_BASE", "http://127.0.0.1:8000/v1").strip(),
        help="OpenAI-compatible root ending in /v1 (vLLM default).",
    )
    p.add_argument(
        "--openai-model",
        default=(
            os.environ.get("NUTONIC_NARRATIVE_OPENAI_MODEL", "").strip()
            or os.environ.get("NUTONIC_VLLM_MODEL", "").strip()
            or DEFAULT_LFM_TEXT_HF_MODEL_ID
        ),
    )
    p.add_argument(
        "--openai-api-key",
        default=(
            os.environ.get("NUTONIC_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        ).strip(),
    )
    p.add_argument(
        "--transformers-model",
        default=(
            os.environ.get("NUTONIC_NARRATIVE_TRANSFORMERS_MODEL", "").strip() or DEFAULT_LFM_TEXT_HF_MODEL_ID
        ),
    )
    p.add_argument(
        "--transformers-max-new-tokens",
        type=int,
        default=_int_env("NUTONIC_NARRATIVE_TRANSFORMERS_MAX_NEW", 512),
    )
    p.add_argument(
        "--transformers-temperature",
        type=float,
        default=None,
        help="Sampling temperature for transformers backend (default: NUTONIC_NARRATIVE_TRANSFORMERS_TEMPERATURE or 0.7).",
    )
    p.add_argument(
        "--transformers-top-p",
        type=float,
        default=None,
        help="Top-p for transformers backend (default: NUTONIC_NARRATIVE_TRANSFORMERS_TOP_P or 0.9).",
    )
    p.add_argument(
        "--openai-max-tokens",
        type=int,
        default=None,
        help="max_tokens for OpenAI-compatible chat (default: NUTONIC_NARRATIVE_OPENAI_MAX_TOKENS or 1024).",
    )
    p.add_argument(
        "--openai-temperature",
        type=float,
        default=None,
        help="Sampling temperature for OpenAI-compatible chat (default: NUTONIC_NARRATIVE_OPENAI_TEMPERATURE or 0.7).",
    )
    p.add_argument(
        "--ollama-num-predict",
        type=int,
        default=-1,
        metavar="N",
        help="Ollama num_predict (-1: use NUTONIC_NARRATIVE_OLLAMA_NUM_PREDICT if set, else model default).",
    )
    p.add_argument(
        "--max-chars",
        type=int,
        default=_int_env("NUTONIC_NARRATIVE_ENTRY_MAX", 8000),
        help="Max stored characters per entry after postprocess (default: NUTONIC_NARRATIVE_ENTRY_MAX or 8000).",
    )
    p.add_argument(
        "--hydration-cache-root",
        type=Path,
        default=None,
        help="Cache segment with streetview/<location_id>.json (default: data/cache/<--content-version>).",
    )
    p.add_argument(
        "--clue-inject-max-chars",
        type=int,
        default=_int_env("NUTONIC_NARRATIVE_CLUE_INJECT_MAX", 2400),
        help="Max characters per injected streetview/satellite clue in the prompt (default 2400 each).",
    )
    g_strip = p.add_mutually_exclusive_group()
    g_strip.add_argument(
        "--strip-markdown",
        dest="strip_markdown",
        action="store_true",
        default=None,
        help="Normalize model output to plain text (default: follow NUTONIC_NARRATIVE_STRIP_MARKDOWN, else on).",
    )
    g_strip.add_argument(
        "--no-strip-markdown",
        dest="strip_markdown",
        action="store_false",
        default=None,
        help="Disable markdown stripping.",
    )
    args = p.parse_args(argv)

    out_dir = args.output_dir or (REPO_ROOT / "data" / "cache" / args.content_version / "narrative")
    prompts_dir = REPO_ROOT / "prompts" / "llm"
    if not prompts_dir.is_dir():
        print(f"narrative_llm_batch: prompts/llm missing ({prompts_dir})", file=sys.stderr)
        return EXIT_TEMPLATE

    cap = max(200, min(int(args.max_chars), 100_000))
    if args.strip_markdown is None:
        strip_md = _bool_env("NUTONIC_NARRATIVE_STRIP_MARKDOWN", default=True)
    else:
        strip_md = bool(args.strip_markdown)
    openai_max_tokens = (
        int(args.openai_max_tokens)
        if args.openai_max_tokens is not None
        else _int_env("NUTONIC_NARRATIVE_OPENAI_MAX_TOKENS", 1024)
    )
    openai_temperature = (
        float(args.openai_temperature)
        if args.openai_temperature is not None
        else _float_env("NUTONIC_NARRATIVE_OPENAI_TEMPERATURE", 0.7)
    )
    tf_temperature = (
        float(args.transformers_temperature)
        if args.transformers_temperature is not None
        else _float_env("NUTONIC_NARRATIVE_TRANSFORMERS_TEMPERATURE", 0.7)
    )
    tf_top_p = (
        float(args.transformers_top_p)
        if args.transformers_top_p is not None
        else _float_env("NUTONIC_NARRATIVE_TRANSFORMERS_TOP_P", 0.9)
    )
    ollama_num_predict: int | None
    if int(args.ollama_num_predict) >= 0:
        ollama_num_predict = int(args.ollama_num_predict)
    else:
        raw_onp = (os.environ.get("NUTONIC_NARRATIVE_OLLAMA_NUM_PREDICT", "") or "").strip()
        if raw_onp:
            try:
                ollama_num_predict = int(raw_onp)
            except ValueError:
                ollama_num_predict = None
        else:
            ollama_num_predict = None
    sidecar: dict[str, object] = {
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

    rows = _hydration_included_filter_rows(_iter_location_rows(args.catalog_root.resolve()))
    if not rows:
        print("narrative_llm_batch: no catalog locations/*.yaml rows (after hydration filter)", file=sys.stderr)
        return EXIT_INPUT

    http_timeout = float(
        os.environ.get(
            "NUTONIC_NARRATIVE_HTTP_TIMEOUT_SEC",
            os.environ.get("NUTONIC_OLLAMA_TIMEOUT_SEC", "600"),
        )
    )
    cache_root = (
        args.hydration_cache_root.resolve()
        if args.hydration_cache_root is not None
        else (REPO_ROOT / "data" / "cache" / args.content_version).resolve()
    )
    clue_cap = max(200, min(int(args.clue_inject_max_chars), 16_000))
    street_clue_budget = min(
        clue_cap,
        max(400, _int_env("NUTONIC_NARRATIVE_STREET_CLUE_CHARS", 1100)),
    )
    sat_clue_budget = min(
        clue_cap,
        max(200, _int_env("NUTONIC_NARRATIVE_SAT_CLUE_CHARS", 750)),
    )
    qa_regenerate = _bool_env("NUTONIC_NARRATIVE_QA_REGENERATE", default=True)

    if args.backend not in ("ollama", "openai", "transformers"):
        print(f"narrative_llm_batch: unsupported backend {args.backend!r}", file=sys.stderr)
        return EXIT_BACKEND

    def _run_infer(pr: str, temp: float) -> str:
        if args.backend == "ollama":
            return _ollama_generate(
                base_url=args.ollama_url,
                model=args.ollama_model,
                prompt=pr,
                timeout_sec=http_timeout,
                num_predict=ollama_num_predict,
            )
        if args.backend == "openai":
            return openai_compatible_chat_text(
                openai_v1_base=args.openai_base,
                model=args.openai_model,
                prompt=pr,
                api_key=args.openai_api_key or None,
                timeout_sec=http_timeout,
                max_tokens=openai_max_tokens,
                temperature=temp,
            )
        return _transformers_generate_text(
            model_id=args.transformers_model,
            prompt=pr,
            max_new_tokens=max(8, int(args.transformers_max_new_tokens)),
            temperature=temp,
            top_p=tf_top_p,
        )

    entries: list[dict[str, object]] = []
    for row in rows:
        mid = row["map_id"]
        lid = row["location_id"]
        doc = load_streetview_hydration_doc(cache_root, lid)
        street, sat = hydration_clues_for_narrative_prompt(
            doc,
            street_budget=street_clue_budget,
            sat_budget=sat_clue_budget,
        )
        street = street[:clue_cap]
        sat = sat[:clue_cap]
        voice = _briefing_voice_line(args.content_version, mid)
        base_prompt = (
            template.replace("{{map_id}}", mid)
            .replace("{{location_id}}", lid)
            .replace("{{briefing_voice}}", voice)
            .replace("{{streetview_clue}}", street)
            .replace("{{satellite_clue}}", sat)
        )
        text = ""
        regen_used = False
        try:
            text = _run_infer(base_prompt, tf_temperature)
            if strip_md:
                text = sidecar_postprocess_plaintext(text)
            viol1 = narrative_qa_violations(text)
            if (
                qa_regenerate
                and viol1
                and narrative_qa_should_regenerate(viol1)
            ):
                retry_temp = min(0.95, tf_temperature + 0.12)
                prompt2 = base_prompt + narrative_qa_retry_user_suffix(viol1)
                text2 = _run_infer(prompt2, retry_temp)
                if strip_md:
                    text2 = sidecar_postprocess_plaintext(text2)
                if narrative_qa_rank_key(text2) > narrative_qa_rank_key(text):
                    text = text2
                    regen_used = True
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"narrative_llm_batch: inference error for {mid}: {e}", file=sys.stderr)
            return EXIT_BACKEND

        final_qa = narrative_qa_violations(text)
        if final_qa:
            suffix = " (after qa retry)" if regen_used else ""
            print(
                f"narrative_llm_batch: qa note for {mid}{suffix}: {', '.join(final_qa)}",
                file=sys.stderr,
            )

        if not text.strip():
            print(
                f"narrative_llm_batch: warning: empty narrative after postprocess for map_id={mid!r} "
                "(writing entry with metadata; cache row is not dropped).",
                file=sys.stderr,
            )

        viol = validate_caption_text(
            text,
            max_len=cap,
            path=f"narrative.entries[{mid}].text",
            coordinate_literal_check=False,
        )
        entry: dict[str, object] = {"map_id": mid, "location_id": lid, "slot": "fragment", "text": text}
        meta: dict[str, object] = {}
        if not text.strip():
            meta["empty_after_postprocess"] = True
        if regen_used:
            meta["narrative_qa_regenerated"] = True
        if final_qa:
            meta["narrative_qa_violations"] = final_qa
        if viol:
            print(
                f"narrative_llm_batch: warning: caption validation for {mid}: "
                + "; ".join(v.format_line() for v in viol),
                file=sys.stderr,
            )
            meta["caption_validation"] = violations_to_jsonable(viol)
        if meta:
            entry["narrative_metadata"] = meta
        entries.append(entry)

    sidecar["entries"] = entries
    pins: dict[str, object] = {
        "script": "narrative_llm_batch",
        "backend": args.backend,
        "dry_run": False,
        "prompt_file": prompt_path.as_posix(),
        "strip_markdown": strip_md,
        "max_chars_cap": cap,
        "hydration_cache_root": cache_root.as_posix(),
        "clue_inject_max_chars": clue_cap,
        "narrative_street_clue_chars": street_clue_budget,
        "narrative_sat_clue_chars": sat_clue_budget,
        "narrative_qa_regenerate": qa_regenerate,
    }
    if args.backend == "ollama":
        pins["ollama_model"] = args.ollama_model
        pins["ollama_url"] = args.ollama_url
        if ollama_num_predict is not None:
            pins["ollama_num_predict"] = ollama_num_predict
    elif args.backend == "openai":
        pins["openai_base"] = _normalize_openai_v1_base(args.openai_base)
        pins["openai_model"] = args.openai_model
        pins["openai_max_tokens"] = openai_max_tokens
        pins["openai_temperature"] = openai_temperature
    else:
        pins["transformers_model"] = args.transformers_model
        pins["transformers_max_new_tokens"] = max(8, int(args.transformers_max_new_tokens))
        pins["transformers_temperature"] = tf_temperature
        pins["transformers_top_p"] = tf_top_p
    sidecar["model_pins"] = pins

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "llm_sidecar.json"
    out_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"narrative_llm_batch: wrote {out_path} ({len(entries)} entries)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
