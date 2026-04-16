---
title: NU:TONIC LFM-VL Street View hints
emoji: 🛰️
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# NU:TONIC — LFM-VL Street View hints (Docker Space)

This Space is published from the NU:TONIC monorepo path `inference/lfm_vl_hint_service` via GitHub Actions (`huggingface-deploy` workflow).

## Hardware

Select **ZeroGPU** (or another GPU tier) in **Space Settings → Hardware** so `transformers` forwards can run under `@spaces.GPU`.

## Endpoints

- `GET /health`
- `POST /v1/suggestions/from_frames` — Street View frame batch → hint JSON (see package README).
- Optional `POST /v1/narrative/fuse`
- **Gradio** demo at **`/gradio`** (this image sets `LFM_VL_MOUNT_GRADIO=1`).

## Environment variables

| Name | Description |
|------|-------------|
| `LFM_VL_BACKEND` | `stub` (default in image build), `transformers`, or `openai_compatible` |
| `LFM_VL_MODEL_ID` | HF model id when backend is `transformers` |
| `LFM_VL_EAGER_LOAD` | `1` to load weights at startup (outside GPU slice) |
| `LFM_VL_ZERO_GPU_DURATION` | Optional seconds for `@spaces.GPU(duration=...)` |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | When `LFM_VL_BACKEND=openai_compatible` |

Set secrets in **Space Settings → Variables and secrets** (never commit tokens).
