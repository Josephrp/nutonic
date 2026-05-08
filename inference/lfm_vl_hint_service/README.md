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

## D — Gradio server + Hugging Face ZeroGPU (local or Space)

[Hugging Face ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu) Spaces require the **Gradio SDK** and **`@spaces.GPU`** on GPU-bound code. This package:

1. Wraps **transformers** forwards (`infer_from_frames_transformers`, `narrative_fuse_transformers`) with **`spaces.GPU`** when the optional **`spaces`** package is installed (no-op locally if `spaces` is absent).
2. Exposes a small **Gradio** panel at **`/gradio`** when **`LFM_VL_MOUNT_GRADIO=1`** and **`gradio`** is installed (same ASGI app as FastAPI).

**Install:**

```bash
pip install -e ".[serve,model]"
```

**Run (defaults `PORT=7860`, enables Gradio mount):**

```bash
python -m lfm_vl_hint_service.run_serve
```

Or with plain **uvicorn** after exporting **`LFM_VL_MOUNT_GRADIO=1`**:

```bash
set LFM_VL_MOUNT_GRADIO=1
uvicorn lfm_vl_hint_service.main:app --host 0.0.0.0 --port 7860
```

**ZeroGPU duration:** optional **`LFM_VL_ZERO_GPU_DURATION`** (seconds) is forwarded to **`@spaces.GPU(duration=...)`** when set.

**Weight load vs generate (HF-friendly):**

- **`ensure_transformers_model_loaded()`** loads **processor + weights** once, **outside** ``@spaces.GPU`` (or at startup via **`LFM_VL_EAGER_LOAD=1`** + FastAPI lifespan).
- Only **`model.generate(...)`** runs through **`apply_zero_gpu`** (``@spaces.GPU`` when the ``spaces`` package is installed).
- On Hugging Face ZeroGPU / CUDA emulation, set **`LFM_VL_FORCE_MODEL_CUDA=1`** so the model is registered on **``cuda``** after ``from_pretrained`` when not using a multi-device ``hf_device_map``.

**stub** and **openai_compatible** backends do not touch this path. On HF, pick **ZeroGPU** hardware and **`sdk: gradio`** or Docker that runs the same **`uvicorn … main:app`** process.

## Tests

```bash
pytest inference/lfm_vl_hint_service/tests -q
```
