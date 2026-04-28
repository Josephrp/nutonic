# NU:TONIC game server — topology

**Status:** Documents the current deployable topology and CI/Hugging Face deployment path. Expand rows when the game server orchestrates additional `inference/*` callers beyond PRO materialization and LFM brief fusion.

## Process

- **Single ASGI app:** FastAPI on port **7860** (HF Spaces / Docker).
- **Normative health:** `GET /api/v1/health` — same path in OpenAPI and runtime.
- **Client bootstrap:** `GET /api/v1/config` — **`features`** toggles (IMP-001); canonical source; do not duplicate conflicting `features` on `/health`.

## Invariants

- **No torch** in this deployable — no TerraTorch, transformers, or pano math in-process (`plans/2026-04-07-game-server-thin-orchestrator.md`).
- **Outbound HTTP:** **`InferenceClient`** (`nutonic_server/inference_client.py`) signs requests when `NUTONIC_INFERENCE_HMAC_SECRET` is set. PRO jobs probe configured origins, call **`POST {NUTONIC_PRO_MATERIALIZATION_SERVICE_URL}/internal/v1/materialize`** when configured, and call **`POST {NUTONIC_LFM_VL_HINT_SERVICE_URL}/v1/pro/brief/fuse`** when configured. **Not yet:** server-driven Street View / satellite-caption batch; scripts and Jobs call those workers directly today.

## CI / Hugging Face deployment

The live server deploy path is **`.github/workflows/huggingface-deploy.yml`**.

| Service | Source path | HF Space | Runtime profile | Smoke preset |
|---------|-------------|----------|-----------------|--------------|
| Game server | `server/` | `NuTonic/nutonic-game-server` | `tools/hf_deploy/profiles/game_server.yaml` (`cpu-basic`) | `game-deploy` |
| PRO materialization worker | `inference/pro_materialization_service/` | `NuTonic/nutonic-pro-materialization` | `tools/hf_deploy/profiles/pro_materialization.yaml` (`cpu-basic`, inbound HMAC required) | `pro-deploy` |
| Street View pano worker | `inference/streetview_pano_service/` | `Tonic/nutonic-streetview-pano` | `tools/hf_deploy/profiles/streetview_pano.yaml` (`cpu-basic`) | `streetview-deploy` |
| LFM-VL hint / brief worker | `inference/lfm_vl_hint_service/` | `Tonic/nutonic-lfm-vl-streetview` | `tools/hf_deploy/profiles/lfm_vl_hint.yaml` (`zero-a10g`) | `lfm-deploy` |
| LFM-VL satellite caption worker | `inference/lfm_vl_satellite_caption_service/` | `Tonic/nutonic-lfm-vl-satellite` | `tools/hf_deploy/profiles/lfm_vl_satellite.yaml` (`zero-a10g`) | `satellite-deploy` |
| TerraMind TiM Space | `inference/terramind_tim_local/` | `Tonic/nutonic-terramind-tim` | `tools/hf_deploy/profiles/terramind_tim.yaml` (`zero-a10g`) | `terramind-deploy` |

The workflow runs targeted pytest before each deploy, uploads a staged Docker Space tree through `tools/hf_deploy/deploy_space.py`, syncs Space variables/secrets/hardware from the runtime profile, and writes live-smoke JSON reports under `artifacts/hf-smoke-*.json`.

## Environment

**Local batch / HF Jobs (not wired through the game server yet):** operators run `tools/batch_streetview_hints.py` with explicit bases, for example `http://127.0.0.1:7861` for `inference/streetview_pano_service` and `http://127.0.0.1:7862` for `inference/lfm_vl_hint_service` (ports are examples — match your `uvicorn` / Space ports). Optional `--satellite-caption-service-url` for Mapbox-still captions. **`data/cache/<content_version>/reports/model_pins.json`** is written every run (including hard-fail exits without `--allow-partial`): **`model_pins`** from pano/LFM/satellite **`/health`** at batch start, plus **`generated_at`**, **`stats`** (selected/written/failed counts, chunk/frame policy), **`written_location_ids`**, and **`failed_locations`** (mirror of `streetview_failures.json`).

| Variable | Role |
|----------|------|
| `STREETVIEW_PANO_SERVICE_URL` | Internal pano / still URL builder |
| `LFM_VL_HINT_SERVICE_URL` / `NUTONIC_LFM_VL_HINT_SERVICE_URL` | LFM-VL hint JSON and optional PRO brief fusion worker. The game server reads the `NUTONIC_` alias today. |
| `LFM_VL_SATELLITE_CAPTION_SERVICE_URL` | Satellite caption / VQA |
| `PRO_MATERIALIZATION_SERVICE_URL` / `NUTONIC_PRO_MATERIALIZATION_SERVICE_URL` | PRO materialization worker origin; when set, PRO jobs probe health and then call **`POST {origin}/internal/v1/materialize`**. |
| `TERRAMIND_WORKER_URL` | Optional collapsed TiM + generate router |
| `INFERENCE_HMAC_SECRET` / `NUTONIC_INFERENCE_HMAC_SECRET` | When set, **`InferenceClient`** signs outbound worker requests. The PRO materialization Space profile requires inbound HMAC, so the game server and worker must share this value before live PRO calls are enabled. |
| `DATABASE_URL` | SQLite / Postgres for ranked + stores (future umbrella; community LB and ranked use explicit URLs today) |
| `NUTONIC_LEADERBOARD_DATABASE_URL` | SQLAlchemy URL for community leaderboard table (**IMP-060**); default file under `data/` |
| `NUTONIC_RANKED_DATABASE_URL` | SQLAlchemy URL for ranked round rows; default file under `data/`. |
| `JWT_SECRET` / `NUTONIC_JWT_SECRET` | HS256 session token secret. The HF deploy profile maps `NUTONIC_JWT_SECRET` from GitHub Actions to Space secret `JWT_SECRET`. |
| `HF_TOKEN` | Dataset sync (server-side only) |
| `CORS_ORIGINS` | Browser allowlist (comma-separated) |

## Timeout policy (placeholder)

`InferenceClient` implements connect/read/write timeouts and **`GET …/health`** probes for **`POST /api/v1/pro/jobs`** (IMP-092). Ranked **`submit`** must not block on hint Spaces (orchestrator §5, `rules/06-server-vlm-tim-and-on-device-ml.md`).

## Related

- Env table for current slice: `server/README.md`
- Architecture: `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`, `plans/2026-04-07-game-server-thin-orchestrator.md`
