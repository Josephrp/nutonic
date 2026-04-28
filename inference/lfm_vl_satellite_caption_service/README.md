# LFM-VL satellite caption service

Discrete `inference/*` worker for satellite / Mapbox still captioning and PRO caption aliases.

## Endpoints

- `GET /health`
- `POST /v1/infer` — satellite still image to caption.
- `POST /v1/pro/caption` — PRO alias with optional profile and contract context.

## Run locally

```bash
cd inference/lfm_vl_satellite_caption_service
pip install -e ".[dev]"
uvicorn lfm_vl_satellite_caption_service.main:app --host 127.0.0.1 --port 7863
```

Use `LFM_SATELLITE_BACKEND=stub` for fast local and CI checks. Use `transformers` or `openai_compatible` only when the matching runtime and secrets are available.

## Docker

```bash
docker build -f inference/lfm_vl_satellite_caption_service/Dockerfile -t nutonic-lfm-vl-satellite inference/lfm_vl_satellite_caption_service
```
