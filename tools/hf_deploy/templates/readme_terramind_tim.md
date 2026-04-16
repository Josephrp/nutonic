---
title: NU:TONIC TerraMind TiM local
emoji: 🌎
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# NU:TONIC — TerraMind TiM (Docker Space)

Published from `inference/terramind_tim_local` in the NU:TONIC monorepo.

## Hardware

Use **ZeroGPU** or a **GPU** hardware profile so TerraTorch forwards have CUDA. CPU-only is suitable only for tiny smoke configs.

## Endpoints

- `GET /health`
- `POST /v1/tim/export` — JSON body: `{ "config": { ... } }` or `{ "config_yaml": "<yaml>" }` matching the CLI YAML schema (see package `config.example.yaml`). Full GeoGuessr / STAC pipelines are better run via the **`nutonic-tim-local`** CLI with on-disk assets.

## Environment variables

| Name | Description |
|------|-------------|
| `TERRAMIND_ZERO_GPU_DURATION` | Optional `@spaces.GPU(duration=...)` seconds |
| `HF_TOKEN` | Optional; improves Hugging Face Hub download rate limits for `pretrained: true` weights |
