---
title: NU:TONIC LFM-VL satellite captions
emoji: 🛰️
colorFrom: indigo
colorTo: purple
sdk: gradio
app_file: app.py
pinned: false
---

# NU:TONIC — LFM-VL satellite caption service (Gradio ZeroGPU Space)

Published from `inference/lfm_vl_satellite_caption_service` in the NU:TONIC monorepo.

## CI deployment

This Space is deployed by `.github/workflows/huggingface-deploy.yml` using:

```bash
python tools/hf_deploy/deploy_space.py --service lfm_vl_satellite --repo-id Tonic/nutonic-lfm-vl-satellite
```

The workflow first runs `python -m pytest inference/lfm_vl_satellite_caption_service/tests -q`, then mirrors the staged Gradio SDK Space tree and syncs runtime settings from `tools/hf_deploy/profiles/lfm_vl_satellite.yaml`.

## Hardware

This service is deployed as **sdk: gradio** because Hugging Face ZeroGPU only supports Gradio SDK Spaces. Use ZeroGPU for `transformers` inference. Use `LFM_SATELLITE_BACKEND=stub` for cheap health-only smoke tests.

## Endpoints

- Gradio API `api_name="infer"` — satellite image JSON request → caption response.

The package still exposes FastAPI routes when run locally or as a Docker Space, but the production ZeroGPU deployment uses the Gradio SDK app.

## Environment variables

| Name | Description |
|------|-------------|
| `LFM_SATELLITE_BACKEND` | `auto`, `stub`, `transformers`, or `openai_compatible`. CI profile defaults to `transformers`. |
| `LFM_SATELLITE_MODEL_ID` | HF model id for the transformers or OpenAI-compatible backend. |
| `LFM_SATELLITE_EAGER_LOAD` | `1` loads model weights during startup. |
| `LFM_SATELLITE_OPENAI_BASE_URL` / `LFM_SATELLITE_OPENAI_API_KEY` | OpenAI-compatible backend settings. |
