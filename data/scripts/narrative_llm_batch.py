#!/usr/bin/env python3
"""
Optional LLM narrative sidecar generation (catalog + prompts; no golden coords in ranked-safe mode).

Backends (``--no-dry-run``):
  ``openai`` — OpenAI-compatible ``POST …/v1/chat/completions`` (vLLM, OpenAI, LiteLLM, etc.).
  ``ollama`` — ``POST …/api/generate``.
  ``transformers`` — in-process Hugging Face **Liquid LFM** text checkpoint (default id in ``liquid_ai_defaults``).

Normative: docs/scripts/SPEC-narrative-llm-batch.md
"""

from __future__ import annotations

import argparse
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

EXIT_INPUT = 2
EXIT_TEMPLATE = 14
EXIT_BACKEND = 15
EXIT_VALIDATE = 11

_tf_model_cache: dict[str, object] = {}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except ValueError:
        return default


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


def _ollama_generate(*, base_url: str, model: str, prompt: str, timeout_sec: float) -> str:
    url = base_url.rstrip("/") + "/api/generate"
    with httpx.Client(timeout=timeout_sec) as client:
        r = client.post(
            url,
            json={"model": model, "prompt": prompt, "stream": False},
        )
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
) -> str:
    """Single-turn user message → assistant text (vLLM / OpenAI-compatible servers)."""
    root = _normalize_openai_v1_base(openai_v1_base)
    url = f"{root}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
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


def _transformers_generate_text(
    *,
    model_id: str,
    prompt: str,
    max_new_tokens: int,
) -> str:
    if torch is None or AutoModelForCausalLM is None or AutoTokenizer is None:
        raise RuntimeError(
            'narrative_llm_batch: --backend transformers needs torch+transformers (e.g. pip install "transformers>=4.44")'
        )

    if _tf_model_cache.get("model_id") != model_id:
        tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
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
    inputs = tok(prompt, return_tensors="pt")
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    with torch.inference_mode():
        out_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
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
    p.add_argument("--max-chars", type=int, default=_int_env("NUTONIC_NARRATIVE_ENTRY_MAX", 2400))
    args = p.parse_args(argv)

    out_dir = args.output_dir or (REPO_ROOT / "data" / "cache" / args.content_version / "narrative")
    prompts_dir = REPO_ROOT / "prompts" / "llm"
    if not prompts_dir.is_dir():
        print(f"narrative_llm_batch: prompts/llm missing ({prompts_dir})", file=sys.stderr)
        return EXIT_TEMPLATE

    cap = max(200, int(args.max_chars))
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

    rows = _iter_location_rows(args.catalog_root.resolve())
    if not rows:
        print("narrative_llm_batch: no catalog locations/*.yaml rows", file=sys.stderr)
        return EXIT_INPUT

    http_timeout = float(
        os.environ.get(
            "NUTONIC_NARRATIVE_HTTP_TIMEOUT_SEC",
            os.environ.get("NUTONIC_OLLAMA_TIMEOUT_SEC", "600"),
        )
    )
    max_chat_tokens = _int_env("NUTONIC_NARRATIVE_OPENAI_MAX_TOKENS", 1024)

    entries: list[dict[str, object]] = []
    for row in rows:
        mid = row["map_id"]
        lid = row["location_id"]
        prompt = template.replace("{{map_id}}", mid).replace("{{location_id}}", lid)
        try:
            if args.backend == "ollama":
                text = _ollama_generate(
                    base_url=args.ollama_url,
                    model=args.ollama_model,
                    prompt=prompt,
                    timeout_sec=http_timeout,
                )
            elif args.backend == "openai":
                text = openai_compatible_chat_text(
                    openai_v1_base=args.openai_base,
                    model=args.openai_model,
                    prompt=prompt,
                    api_key=args.openai_api_key or None,
                    timeout_sec=http_timeout,
                    max_tokens=max_chat_tokens,
                )
            elif args.backend == "transformers":
                text = _transformers_generate_text(
                    model_id=args.transformers_model,
                    prompt=prompt,
                    max_new_tokens=max(8, int(args.transformers_max_new_tokens)),
                )
            else:
                print(f"narrative_llm_batch: unsupported backend {args.backend!r}", file=sys.stderr)
                return EXIT_BACKEND
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"narrative_llm_batch: inference error for {mid}: {e}", file=sys.stderr)
            return EXIT_BACKEND

        viol = validate_caption_text(
            text,
            max_len=cap,
            path=f"narrative.entries[{mid}].text",
            coordinate_literal_check=False,
        )
        if viol:
            print("; ".join(v.format_line() for v in viol), file=sys.stderr)
            return EXIT_VALIDATE
        entries.append({"map_id": mid, "location_id": lid, "slot": "fragment", "text": text})

    sidecar["entries"] = entries
    pins: dict[str, object] = {
        "script": "narrative_llm_batch",
        "backend": args.backend,
        "dry_run": False,
        "prompt_file": prompt_path.as_posix(),
    }
    if args.backend == "ollama":
        pins["ollama_model"] = args.ollama_model
        pins["ollama_url"] = args.ollama_url
    elif args.backend == "openai":
        pins["openai_base"] = _normalize_openai_v1_base(args.openai_base)
        pins["openai_model"] = args.openai_model
    else:
        pins["transformers_model"] = args.transformers_model
    sidecar["model_pins"] = pins

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "llm_sidecar.json"
    out_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"narrative_llm_batch: wrote {out_path} ({len(entries)} entries)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
