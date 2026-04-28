---
title: NU:TONIC LFM-VL Street View hints
emoji: 🛰️
colorFrom: purple
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
---

# NU:TONIC — LFM-VL Street View hints (Gradio ZeroGPU Space)

This Space is published from the NU:TONIC monorepo path `inference/lfm_vl_hint_service` via GitHub Actions (`huggingface-deploy` workflow).

## CI deployment

This Space is deployed by `.github/workflows/huggingface-deploy.yml` using:

```bash
python tools/hf_deploy/deploy_space.py --service lfm_vl_hint --repo-id Tonic/nutonic-lfm-vl-streetview
```

The workflow first runs `python -m pytest inference/lfm_vl_hint_service/tests -q`, then mirrors the staged Gradio SDK Space tree and syncs runtime settings from `tools/hf_deploy/profiles/lfm_vl_hint.yaml`.

## Hardware

This service is deployed as **sdk: gradio** because Hugging Face ZeroGPU only supports Gradio SDK Spaces. Select **ZeroGPU** in **Space Settings → Hardware** so `transformers` forwards can run under `@spaces.GPU`.

## Endpoints

- Gradio API `api_name="suggestions_from_frames"` — Street View frame batch → hint JSON.
- Gradio API `api_name="narrative_fuse"` — caption fusion smoke/manual path.

The package still exposes FastAPI routes when run locally or as a Docker Space, but the production ZeroGPU deployment uses the Gradio SDK app.

## Environment variables

| Name | Description |
|------|-------------|
| `LFM_VL_BACKEND` | `stub` (default in image build), `transformers`, or `openai_compatible` |
| `LFM_VL_MODEL_ID` | HF model id when backend is `transformers` |
| `LFM_VL_EAGER_LOAD` | `1` to load weights at startup (outside GPU slice) |
| `LFM_VL_ZERO_GPU_DURATION` | Optional seconds for `@spaces.GPU(duration=...)` |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` | When `LFM_VL_BACKEND=openai_compatible` |

Set secrets in **Space Settings → Variables and secrets** (never commit tokens).
