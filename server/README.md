# NU:TONIC game server (`server/`)

Thin **FastAPI** orchestrator for Kotlin clients: versioned REST under **`/api/v1/*`**, optional Gradio **`/ops`** later, **no** `torch` / TerraTorch / Street View math in-process.

**Topology and fan-out URLs:** see [`docs/TOPOLOGY.md`](docs/TOPOLOGY.md).

## Run locally

```bash
cd server
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
uvicorn nutonic_server.main:app --host 0.0.0.0 --port 7860 --reload
```

Optional: copy **`.env.example`** to **`server/.env`** so local runs pick up **`NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH=true`** (full manifest fixtures) and **`FEATURE_COMMUNITY_LB_POST=true`** (community leaderboard writes) without exporting variables each shell. Process environment variables still override `.env`.

- Health: `GET http://localhost:7860/api/v1/health`
- Config (feature flags): `GET http://localhost:7860/api/v1/config`

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CORS_ORIGINS` | No | Comma-separated browser origins allowed for CORS (e.g. `http://localhost:8080`). Empty = CORS middleware not registered. |
| `FEATURE_RANKED` | No | Default **`false`**. When **`true`**, enables **`POST /api/v1/ranked/rounds/start`**, **`.../submit`**, **`.../forfeit-ranked-integrity`** (**IMP-090** / **IMP-091**). `features.ranked` on **`GET /api/v1/config`**. |
| `FEATURE_COMMUNITY_LB_GET` | No | Default `true`. `features.community_lb_get`. |
| `FEATURE_COMMUNITY_LB_POST` | No | Default **`false`** (enable explicitly for lab/community writes). `features.community_lb_post`. |
| `FEATURE_PRO_JOBS` | No | Default **`false`**. `features.pro_jobs`. |
| `FEATURE_GUESSES_RECORD` / `NUTONIC_FEATURE_GUESSES_RECORD` | No | Default **`false`**. When **`true`**, enables **`POST /api/v1/maps/{map_id}/guesses/record`** and sets `features.guesses_record` on **`GET /api/v1/config`**. Use **`true`** in local dev when exercising telemetry (`rules/05`, `docs/GAME-ENGINE.md` §12.3). |
| `NUTONIC_GUESS_TELEMETRY_DATABASE_URL` | No | Default `sqlite:///data/nutonic_guess_telemetry.db`. SQLite file for optional guess rows (created under `data/` like the leaderboard DB). |
| `NUTONIC_RANKED_DATABASE_URL` | No | Default `sqlite:///data/nutonic_ranked.db`. SQLite for ranked round rows (**IMP-090**). |
| `NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH` | No | Default **`false`**: **`GET /api/v1/cache/manifest`** omits `locations` and `ai_guesses` (public spoiler hygiene). Set **`true`** for local dev / tests that need full fixture slices. |
| `NUTONIC_MANIFEST_FULL_PATH` / `MANIFEST_FULL_PATH` | No | When set to an existing **`manifest.full.json`** (same schema as **`assemble_manifest.py`** output), replaces the builtin demo **`PUBLISHED_MAPS` / `MANIFEST_LOCATIONS` / `MANIFEST_AI_GUESSES`** at process start so **`GET /api/v1/maps`**, **`GET /api/v1/cache/manifest`**, and **`POST /api/v1/ranked/rounds/start`** use the full GeoGuessr-derived catalog. Extra location keys (e.g. `satellite_caption_sidecar`) are ignored by the server DTO. |
| `JWT_SECRET` / `NUTONIC_JWT_SECRET` | No | HS256 key for **`POST /api/v1/auth/token`** session JWTs. Default is **dev-only** — **override in any shared or production deploy**. |
| `JWT_TTL_SECONDS` | No | Default `3600`. Access token lifetime. |
| `NUTONIC_LEADERBOARD_DATABASE_URL` | No | SQLAlchemy URL for **`GET`/`POST`** community leaderboard persistence (**IMP-060**). Default `sqlite:///data/nutonic_leaderboard.db` (directory is created). Tests use in-memory SQLite via `conftest.py`. Set to `memory` to force the legacy in-process store. |
| `NUTONIC_INFERENCE_WORKER_BASE_URL` | No | Optional origin (no trailing path) for **IMP-092** wiring: when set and **`FEATURE_PRO_JOBS=true`**, **`POST /api/v1/pro/jobs`** probes **`GET {base}/health`** via **`InferenceClient`** and returns **`inference_upstream_ok`** on **`ProJobCreateOut`**. Example: `http://127.0.0.1:7861` for `inference/streetview_pano_service`. |

Future variables (placeholders — not read by this slice yet): `DATABASE_URL`, `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `STREETVIEW_PANO_SERVICE_URL`, `LFM_VL_HINT_SERVICE_URL`, `LFM_VL_SATELLITE_CAPTION_SERVICE_URL`, `PRO_MATERIALIZATION_SERVICE_URL`, `TERRAMIND_WORKER_URL`, `INFERENCE_HMAC_SECRET`, `HF_TOKEN`. See `plans/2026-04-07-game-server-thin-orchestrator.md` §4.

## OpenAPI

Normative contract: **`../docs/openapi.yaml`** at repo root (hand-maintained; FastAPI may diverge until a generator step is added). **`servers[0].url`** must be the deployment **origin only** (no `/api/v1` suffix); operation paths include the full **`/api/v1/...`** prefix so URL joiners resolve correctly. **`pytest`** includes a check that documented paths/methods match the FastAPI app.

## Docker

```bash
docker build -t nutonic-server ./server
docker run --rm -p 7860:7860 nutonic-server
```

To **persist** the default SQLite file across container restarts, mount a volume on `/app/data` (matches default `sqlite:///data/nutonic_leaderboard.db`).

### Compose (dev): telemetry + full manifest

From repo root:

```bash
docker compose -f server/docker-compose.dev.yml up --build
```

This sets **`FEATURE_GUESSES_RECORD=true`** and **`NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH=true`** so Kotlin clients can POST guess telemetry and hydrate **`still_bundle_id`** / manifest fixtures without extra env typing.

HF Spaces expect port **7860**.
