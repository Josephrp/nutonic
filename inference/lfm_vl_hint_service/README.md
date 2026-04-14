# LFM-VL hint service (Street View batch)

Discrete **`inference/*`** worker: **`POST /v1/suggestions/from_frames`** per `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`, using **official Liquid LFM-VL** weights when you enable a non-stub backend.

**Liquid documentation (authoritative inference patterns):** [LFM2.5-VL-450M](https://docs.liquid.ai/lfm/models/lfm25-vl-450m) (Transformers, vLLM, SGLang, llama.cpp).

## Backends (`LFM_VL_BACKEND`)

| Value | When to use | Dependencies |
|--------|-------------|--------------|
| **`stub`** (default) | CI, dry runs, no GPU | Base `pip install -e .` only |
| **`transformers`** | In-process Hugging Face inference with **`LiquidAI/LFM2.5-VL-450M`** (or another LFM-VL id) | `pip install -e ".[model]"` (`torch`, `transformers`, `accelerate`) |
| **`openai_compatible`** (aliases: `openai`, `vllm`, `sglang`) | vLLM / SGLang / any **OpenAI-compatible** server exposing **`/v1/chat/completions`** with vision messages | Base install (`httpx` only) |

Environment variables (see [`.env.example`](.env.example)):

- **`LFM_VL_MODEL_ID`** — default `LiquidAI/LFM2.5-VL-450M` (HF id; also default OpenAI `model` field).
- **`LFM_VL_MAX_NEW_TOKENS`** — default `256`.
- **`LFM_VL_TORCH_DTYPE`** — `bfloat16` \| `float16` \| `float32` \| `auto` (transformers only).
- **`LFM_OPENAI_BASE_URL`** — e.g. `http://127.0.0.1:8000/v1` (no trailing slash required).
- **`LFM_OPENAI_API_KEY`** — sent as `Authorization: Bearer …` (many local servers accept `dummy`).
- **`LFM_OPENAI_MODEL`** — overrides the `model` JSON field when different from `LFM_VL_MODEL_ID`.

## Quick start

### A — Stub (default)

```bash
cd inference/lfm_vl_hint_service
pip install -e ".[dev]"
uvicorn lfm_vl_hint_service.main:app --host 127.0.0.1 --port 7862
```

### B — Official weights via Transformers (GPU recommended)

```bash
pip install -e ".[model,dev]"
set LFM_VL_BACKEND=transformers
uvicorn lfm_vl_hint_service.main:app --host 127.0.0.1 --port 7862
```

Uses `AutoProcessor` + `AutoModelForImageTextToText` as in Liquid’s docs (per-frame generation, coordinate-safe prompts).

### C — Official weights via vLLM / SGLang (OpenAI-compatible)

1. Start upstream server per Liquid docs, e.g. vLLM with `LiquidAI/LFM2.5-VL-450M`.
2. Point this service at it:

```bash
set LFM_VL_BACKEND=openai_compatible
set LFM_OPENAI_BASE_URL=http://127.0.0.1:8000/v1
set LFM_OPENAI_API_KEY=dummy
uvicorn lfm_vl_hint_service.main:app --host 127.0.0.1 --port 7862
```

## HTTP routes

- `GET /health` — `backend`, `model_id`, optional `openai_base_url`
- `POST /v1/suggestions/from_frames` — batch Street View captions
- `POST /v1/narrative/fuse` — text-only fusion (stub concatenation, or same backend as captions when not stub)

## Tests

```bash
pytest inference/lfm_vl_hint_service/tests -q
```
