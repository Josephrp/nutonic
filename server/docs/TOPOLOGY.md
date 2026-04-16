# NU:TONIC game server — topology (living stub)

**Status:** **IMP-012** satisfied as a **short topology doc**; **IMP-092 (partial)** merged — expand rows when the game server **orchestrates additional** `inference/*` callers beyond **PRO** health/materialize.

## Process

- **Single ASGI app:** FastAPI on port **7860** (HF Spaces / Docker).
- **Normative health:** `GET /api/v1/health` — same path in OpenAPI and runtime.
- **Client bootstrap:** `GET /api/v1/config` — **`features`** toggles (IMP-001); canonical source; do not duplicate conflicting `features` on `/health`.

## Invariants

- **No torch** in this deployable — no TerraTorch, transformers, or pano math in-process (`plans/2026-04-07-game-server-thin-orchestrator.md`).
- **Outbound HTTP (partial):** **`InferenceClient`** (`nutonic_server/inference_client.py`) — **`GET …/health`** (+ optional HMAC) toward **`NUTONIC_INFERENCE_WORKER_BASE_URL`** and **`NUTONIC_PRO_MATERIALIZATION_SERVICE_URL`** for **`POST /api/v1/pro/jobs`**; optional **`POST …/internal/v1/materialize`** forward. **Not yet:** server-driven **Street View / LFM** batch (scripts and Jobs call workers directly today).

## Environment (future URLs — TBD)

| Variable | Role |
|----------|------|
| `STREETVIEW_PANO_SERVICE_URL` | Internal pano / still URL builder |
| `LFM_VL_HINT_SERVICE_URL` | LFM-VL hint JSON |
| `LFM_VL_SATELLITE_CAPTION_SERVICE_URL` | Satellite caption / VQA |
| `PRO_MATERIALIZATION_SERVICE_URL` / `NUTONIC_PRO_MATERIALIZATION_SERVICE_URL` | PRO materialization worker origin; when set, **`POST /api/v1/pro/jobs`** includes **`GET {origin}/health`** in the IMP-092 probe set (with `NUTONIC_INFERENCE_WORKER_BASE_URL` if present) |
| `TERRAMIND_WORKER_URL` | Optional collapsed TiM + generate router |
| `INFERENCE_HMAC_SECRET` / `NUTONIC_INFERENCE_HMAC_SECRET` | When set, **`InferenceClient`** signs outbound **`GET`** probes toward **`inference/*`** (IMP-092); workers verify when enabled |
| `DATABASE_URL` | SQLite / Postgres for ranked + stores (future; community LB uses `NUTONIC_LEADERBOARD_DATABASE_URL` today) |
| `NUTONIC_LEADERBOARD_DATABASE_URL` | SQLAlchemy URL for community leaderboard table (**IMP-060**); default file under `data/` |
| `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` | Auth material |
| `HF_TOKEN` | Dataset sync (server-side only) |
| `CORS_ORIGINS` | Browser allowlist (comma-separated) |

## Timeout policy (placeholder)

`InferenceClient` implements connect/read/write timeouts and **`GET …/health`** probes for **`POST /api/v1/pro/jobs`** (IMP-092). Ranked **`submit`** must not block on hint Spaces (orchestrator §5, `rules/06-server-vlm-tim-and-on-device-ml.md`).

## Related

- Env table for current slice: `server/README.md`
- Architecture: `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`, `plans/2026-04-07-game-server-thin-orchestrator.md`
