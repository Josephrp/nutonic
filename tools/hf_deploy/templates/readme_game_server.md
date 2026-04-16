---
title: NU:TONIC game server
emoji: 🎮
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# NU:TONIC — thin game server (FastAPI)

Published from `server/` in the NU:TONIC monorepo (orchestrator only — **no** `torch`).

## Hardware

**CPU** is sufficient for the reference thin server. For production ranked + DB, use managed Postgres (see `server/README.md` and `plans/2026-04-07-game-server-thin-orchestrator.md`).

## Environment variables

Configure in **Space Settings → Variables and secrets** (see `server/src/nutonic_server/settings.py` for the full list). Common entries:

| Name | Description |
|------|-------------|
| `NUTONIC_LEADERBOARD_DATABASE_URL` | SQLAlchemy URL (default SQLite under `/app/data` in Docker) |
| `NUTONIC_RANKED_DATABASE_URL` | Ranked round store |
| `JWT_SECRET` / session signing | Required for gated routes in real deployments |
| `CORS_ORIGINS` | Comma-separated origins for browser clients |
| `FEATURE_RANKED`, `FEATURE_COMMUNITY_LB_POST`, `FEATURE_PRO_JOBS` | Runtime feature toggles |
| `NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH` | Dev-only; keep `false` on public Spaces |
