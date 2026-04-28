---
title: NU:TONIC TerraMind TiM local
emoji: 🌎
colorFrom: green
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
---

# NU:TONIC — TerraMind TiM (Gradio ZeroGPU Space)

Published from `inference/terramind_tim_local` in the NU:TONIC monorepo.

## CI deployment

This Space is deployed by `.github/workflows/huggingface-deploy.yml` using:

```bash
python tools/hf_deploy/deploy_space.py --service terramind_tim --repo-id Tonic/nutonic-terramind-tim
```

The workflow first runs `python -m pytest inference/terramind_tim_local/tests -q`, then mirrors the staged Gradio SDK Space tree and syncs runtime settings from `tools/hf_deploy/profiles/terramind_tim.yaml`.

## Hardware

This service is deployed as **sdk: gradio** because Hugging Face ZeroGPU only supports Gradio SDK Spaces. Use **ZeroGPU** so TerraTorch forwards have CUDA. CPU-only is suitable only for tiny smoke configs outside the ZeroGPU deployment.

## Endpoints

- Gradio API `api_name="health"` — patch and service diagnostics.
- Gradio API `api_name="tim_infer"` — JSON body: `{ "config": { ... } }` or `{ "config_yaml": "<yaml>" }` matching the CLI YAML schema.

The package still exposes FastAPI routes when run locally or as a Docker Space, but the production ZeroGPU deployment uses the Gradio SDK app.

## Environment variables

| Name | Description |
|------|-------------|
| `TERRAMIND_ZERO_GPU_DURATION` | Optional `@spaces.GPU(duration=...)` seconds |
| `HF_TOKEN` | Optional; improves Hugging Face Hub download rate limits for `pretrained: true` weights |
