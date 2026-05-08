---
title: "NU:TONIC PRO (ZeroGPU demo)"
colorFrom: blue
colorTo: purple
sdk: gradio
app_file: app.py
pinned: false
---

# NU:TONIC — PRO ZeroGPU demo (local Transformers VLM)

Published from `inference/pro_gradio_demo` in the NU:TONIC monorepo.

This Space:

- Submits and polls **PRO jobs** via the game server (`/api/v1/pro/jobs`).
- Fetches the job’s `on_device_payload.vlm_image_set` image(s).
- Runs the **final VLM analysis locally** on **ZeroGPU** using **Transformers** and the fine-tuned model bundle advertised by the server manifest (default `NuTonic/lspace`).
- Returns:
  - raw image
  - annotated image (bounding boxes)
  - JSON payload (`caption` + normalized `boxes[]`) compatible with the client PRO overlay contract.

## CI deployment

This Space is deployed by `.github/workflows/huggingface-deploy.yml` using:

```bash
python tools/hf_deploy/deploy_space.py --service pro_gradio_demo --repo-id Tonic/nutonic-pro-demo
```

## Environment variables

| Name | Description |
|------|-------------|
| `NUTONIC_SERVER_ORIGIN` | Base origin for the game server API (must expose `/api/v1/pro/jobs` + `/api/v1/pro/vlm/model-manifest`). |
| `NUTONIC_PRO_POLL_TIMEOUT_SECONDS` | Poll timeout for upstream PRO jobs. |
| `NUTONIC_PRO_POLL_INTERVAL_SECONDS` | Poll interval for upstream PRO jobs. |

