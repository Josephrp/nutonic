# NU:TONIC game server — topology (stub)

**Status:** Initial stub for IMP-012; expand when HTTP fan-out to workers is merged.

## Process

- **Single ASGI app:** FastAPI on port **7860** (HF Spaces / Docker).
- **Normative health:** `GET /api/v1/health` — same path in OpenAPI and runtime.
- **Client bootstrap:** `GET /api/v1/config` — **`features`** toggles (IMP-001); canonical source; do not duplicate conflicting `features` on `/health`.

## Invariants

- **No torch** in this deployable — no TerraTorch, transformers, or pano math in-process (`plans/2026-04-07-game-server-thin-orchestrator.md`).
- **Future outbound HTTP** (not wired in this slice): `httpx` → `inference/*` and TerraMind workers with per-upstream timeouts and size limits (orchestrator §5).

## Environment (future URLs — TBD)

| Variable | Role |
|----------|------|
| `STREETVIEW_PANO_SERVICE_URL` | Internal pano / still URL builder |
| `LFM_VL_HINT_SERVICE_URL` | LFM-VL hint JSON |
| `LFM_VL_SATELLITE_CAPTION_SERVICE_URL` | Satellite caption / VQA |
| `PRO_MATERIALIZATION_SERVICE_URL` | PRO fetch + downsample |
| `TERRAMIND_WORKER_URL` | Optional collapsed TiM + generate router |
| `INFERENCE_HMAC_SECRET` | Server → inference request signing |
| `DATABASE_URL` | SQLite / Postgres for ranked + stores (future; community LB uses `NUTONIC_LEADERBOARD_DATABASE_URL` today) |
| `NUTONIC_LEADERBOARD_DATABASE_URL` | SQLAlchemy URL for community leaderboard table (**IMP-060**); default file under `data/` |
| `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` | Auth material |
| `HF_TOKEN` | Dataset sync (server-side only) |
| `CORS_ORIGINS` | Browser allowlist (comma-separated) |

## Timeout policy (placeholder)

Document per-upstream connect/read ceilings when `InferenceClient` lands (IMP-092). Ranked **`submit`** must not block on hint Spaces (orchestrator §5, `rules/06-server-vlm-tim-and-on-device-ml.md`).

## Related

- Env table for current slice: `server/README.md`
- Architecture: `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`, `plans/2026-04-07-game-server-thin-orchestrator.md`
