# PRO Mini-Apps Operations

## SLOs

- Create job route returns `queued` in under 500 ms for healthy control-plane dependencies.
- Poll route is read-only and should stay under 200 ms p95.
- Terminal job states are `completed`, `failed`, or `cancelled`; no job should remain `running` beyond the worker timeout budget without an operator alert.

## Alerts

- Queue depth above `pro_max_concurrent_jobs * 10` for 10 minutes.
- `worker_unreachable` or `worker_timeout` failures above 10% for 15 minutes.
- HMAC replay rejections above normal baseline.
- Artifact disk usage above 80% of the configured volume.

## Degraded Modes

- PRO materialization unavailable: jobs fail with `worker_unreachable`; UI should show retryable service-unavailable copy.
- TiM unavailable: profile jobs fail unless the profile explicitly supports brief-only mode.
- LFM briefing unavailable: analysis artifacts can still be shown; Brief Composer should display limited synthesis.

## Triage

1. Check `/api/v1/config` exposes `features.pro_jobs = true`.
2. Check worker `/health` endpoints and required/optional origin settings.
3. Inspect PRO job rows by status and `error_class`.
4. Verify inbound HMAC secrets match server outbound `InferenceClient` settings.
5. Confirm artifact root has free space and cleanup is running.

## CI / Space Deployment

PRO runtime pieces are deployed by **`.github/workflows/huggingface-deploy.yml`** after targeted pytest:

| Piece | Source | Space | Required deploy secrets |
|-------|--------|-------|-------------------------|
| Game server control plane | `server/` | `NuTonic/nutonic-game-server` | `HF_TOKEN_NUTONIC` or fallback write token; `NUTONIC_JWT_SECRET`; optional DB URLs |
| PRO materialization worker | `inference/pro_materialization_service/` | `NuTonic/nutonic-pro-materialization` | `HF_TOKEN_NUTONIC` or fallback write token; `NUTONIC_MAPBOX_ACCESS_TOKEN`; `NUTONIC_INFERENCE_HMAC_SECRET` |
| Street View pano worker | `inference/streetview_pano_service/` | `Tonic/nutonic-streetview-pano` | `HF_TOKEN_TONIC` or fallback write token; optional `TONIC_GOOGLE_MAPS_API_KEY` |
| LFM brief worker | `inference/lfm_vl_hint_service/` | `Tonic/nutonic-lfm-vl-streetview` | `HF_TOKEN_TONIC` or fallback write token; optional OpenAI-compatible secrets |
| Satellite caption worker | `inference/lfm_vl_satellite_caption_service/` | `Tonic/nutonic-lfm-vl-satellite` | `HF_TOKEN_TONIC` or fallback write token; optional satellite OpenAI-compatible secrets |
| TerraMind TiM Space | `inference/terramind_tim_local/` | `Tonic/nutonic-terramind-tim` | `HF_TOKEN_TONIC` or fallback write token; optional `TONIC_TERRAMIND_HF_TOKEN` |

The game server Space profile currently leaves `FEATURE_PRO_JOBS=false`, so a successful deploy does not automatically enable live PRO. To run end-to-end PRO jobs against deployed Spaces, enable the game server flag, set `NUTONIC_PRO_MATERIALIZATION_SERVICE_URL`, optionally set `NUTONIC_LFM_VL_HINT_SERVICE_URL`, and use the same `NUTONIC_INFERENCE_HMAC_SECRET` on the game server and HMAC-protected workers.

Post-deploy smoke reports are uploaded as `hf-smoke-game`, `hf-smoke-pro`, `hf-smoke-streetview`, `hf-smoke-lfm`, `hf-smoke-satellite`, and `hf-smoke-terramind` artifacts. For cross-service readiness, run `tools/live_inference_smoke.py --preset pro-readiness` from a trusted environment with the relevant URLs and secrets.
