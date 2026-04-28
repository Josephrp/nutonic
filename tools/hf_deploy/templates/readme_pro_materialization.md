---
title: NU:TONIC PRO materialization
emoji: 🗺️
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

# NU:TONIC — PRO materialization service

Published from `inference/pro_materialization_service` (CPU / IO — **no** `torch` in `pyproject` core deps).

## CI deployment

This Space is deployed by `.github/workflows/huggingface-deploy.yml` using:

```bash
python tools/hf_deploy/deploy_space.py --service pro_materialization --repo-id NuTonic/nutonic-pro-materialization
```

The workflow first runs `python -m pytest inference/pro_materialization_service/tests -q`, then mirrors the staged Docker Space tree and syncs runtime settings from `tools/hf_deploy/profiles/pro_materialization.yaml`.

## Hardware

**CPU** Space is expected (Mapbox fetch, optional Sentinel / STAC when extras installed).

## Environment variables

| Name | Description |
|------|-------------|
| `MAPBOX_ACCESS_TOKEN` | Required for Mapbox static / tile fetches (secret) |
| `NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC` | Current CI profile sets this to `1`; unsigned internal requests receive `401`. |
| `NUTONIC_INFERENCE_HMAC_SECRET` | Shared secret used to verify game-server or smoke-test signatures. Must match the game server `NUTONIC_INFERENCE_HMAC_SECRET` when live PRO is enabled. |
| Additional STAC / AWS keys | If you enable Sentinel paths — see package README |
