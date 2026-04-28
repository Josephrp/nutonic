---
title: NU:TONIC Street View pano
emoji: 🛣️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# NU:TONIC — Street View pano service

Published from `inference/streetview_pano_service` in the NU:TONIC monorepo.

## CI deployment

This Space is deployed by `.github/workflows/huggingface-deploy.yml` using:

```bash
python tools/hf_deploy/deploy_space.py --service streetview_pano --repo-id Tonic/nutonic-streetview-pano
```

The workflow first runs `python -m pytest inference/streetview_pano_service/tests -q`, then mirrors the staged Docker Space tree and syncs runtime settings from `tools/hf_deploy/profiles/streetview_pano.yaml`.

## Hardware

CPU is sufficient. The default CI profile uses stub mode; set `STREETVIEW_PROVIDER=google` plus `GOOGLE_MAPS_API_KEY` to fetch real Google Street View Static imagery.

## Endpoints

- `GET /health`
- `GET /api/v1/pano/metadata`
- `POST /api/v1/panos/sample`
- Legacy alias: `POST /v1/panos/sample`

## Environment variables

| Name | Description |
|------|-------------|
| `STREETVIEW_PROVIDER` | `stub`, `google`, or `auto`. CI profile defaults to `stub`. |
| `GOOGLE_MAPS_API_KEY` | Optional secret for Google Street View Static and metadata calls. |
| `STREETVIEW_EXPOSE_SAMPLING_DEBUG` | `1` exposes sampling debug metadata without secrets. |
| `NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC` | Optional; when `1`, callers must sign requests. |
| `NUTONIC_INFERENCE_HMAC_SECRET` | Shared secret for inbound HMAC verification when required. |
