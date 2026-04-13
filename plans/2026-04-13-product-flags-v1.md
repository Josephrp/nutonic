# IMP-001 — Product flags v1 (ranked, community leaderboard, PRO tab, server feature toggles)

**Status:** Aligned to v1 direction: **full multiplatform parity**, **PRO day-one**, **all shell tabs visible**, **`/api/v1`** versioning, **optional server-driven features in scope** (runtime toggles without implying every tier is always on for every deployment).  
**Date:** 2026-04-13  
**Depends on:** **IMP-000** (`docs/map-engines.md`) for per-target auth / attestation expectations.  
**Normative sources:** `docs/RANKED-MODE.md`, `rules/05-networking-leaderboard.md`, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`, `plans/2026-04-07-complete-implementation-architecture.md` §4.1.

---

## Annex (off game client)

**v1 includes** orchestration and batch work **outside** the Kotlin client: **Hugging Face Jobs**, the **game server**, **inference / materialization services**, and **`data/scripts/`** (and related) pipelines. Clients talk only to the **documented game-server** surface under **`/api/v1`**; Jobs and workers feed datasets, manifests, and PRO materialization as in architecture + PRO specs (`docs/map-engines.md` annex table).

---

## Shell (v1)

- **All five tabs** are **shown** in v1 on every shipped target: **SCAN · INTEL · RANK · SETUP · PRO** (`rules/01-navigation-architecture.md`, complete plan §3.1).
- No “hide PRO until v2” — **PRO is day-one**: functional **`POST /api/v1/pro/jobs`** (and poll/status contract) per **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`**, subject to same JWT / rate rules as other gated writes in `rules/05`.

---

## 1.1 Boolean flags table (v1 — capabilities + runtime toggles)

Flags mean **“ship the integration in v1”**. Whether a **given deployment** exposes a tier to players is controlled by **optional server feature payload** (below), not by stripping code from the client.

| Flag | Meaning | **v1** | Notes |
|------|---------|--------|-------|
| **`FEATURE_RANKED`** | Ranked rounds: `round_ticket`, JWT start/submit, verified scores, ranked leaderboard slice | **Ship: true** | OpenAPI + client flows per `docs/RANKED-MODE.md`; forfeits if UI exposes peer reveal / assists. Server may set `features.ranked: false` to hide entry points without removing routes. |
| **`FEATURE_COMMUNITY_LB_GET`** | `GET /api/v1/maps/{map_id}/leaderboard` (non-ranked aggregate / presentation) | **Ship: true** | `rules/05`: presentation-only trust; client merges with local per `13`. |
| **`FEATURE_COMMUNITY_LB_POST`** | Community self-report **`POST`** (schema-defined; JWT when store-gated) | **Ship: true** | Still **non-authoritative** for non-ranked math; idempotency + caps per `rules/05`. |
| **`FEATURE_PRO_TAB`** | PRO tab + **`POST /api/v1/pro/jobs`** + poll / bundle delivery | **Ship: true (day-one)** | Full orchestration path per PRO spec; not a stub. |

Default **non-ranked solo** play and **local** leaderboards remain when network or flags disable server slices.

---

## 1.2 OpenAPI: `/api/v1` + optional server `features` (in scope for v1)

- **All** REST paths are versioned under **`/api/v1/...`** (single prefix in **`docs/openapi.yaml`** — **IMP-011**). Illustrative paths in `docs/RANKED-MODE.md` §4 map to this prefix (e.g. `POST /api/v1/ranked/rounds/start`).
- **Optional server features (required v1 artifact):** expose at least one of:
  - **`GET /api/v1/config`** with a stable JSON object, e.g. `{ "features": { "ranked": bool, "community_lb_get": bool, "community_lb_post": bool, "pro_jobs": bool } }`, **or**
  - extend **`GET /api/v1/health`** with the same `features` block (document which is canonical; avoid two conflicting sources).

Clients **read** `features` on bootstrap / session refresh to align tab affordances (e.g. disable ranked CTA when `ranked: false`) **without** a new app build. **Ops** can run annex Jobs and server scripts independently; toggles describe **player-visible** availability.

---

## 1.3 Map each flag to OpenAPI route presence (when flag capability is on)

| Area | Minimal `/api/v1` surface (when shipped for that deployment) |
|------|----------------------------------------------------------------|
| **Ranked** | `POST /api/v1/ranked/rounds/start`, `POST /api/v1/ranked/rounds/{round_id}/submit`; optional forfeit endpoints if UI exposes peer reveal / SCAN assists in ranked; ranked leaderboard via `GET /api/v1/maps/{map_id}/leaderboard` + `tier=ranked` **or** dedicated ranked path (`docs/RANKED-MODE.md`). |
| **Community** | `GET` + optional `POST .../scores/self-report` (or documented paths) under **`map_id`** (`rules/05`). |
| **PRO** | `POST /api/v1/pro/jobs` + documented poll/status + caps per **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`**. |
| **Auth** | Token issuance / validation per `rules/05` wherever writes require JWT. |

When **`features.*`** is false, servers should return **stable 403/404** (document which) for the matching routes **or** keep routes but return empty/disabled payloads — **pick one policy in OpenAPI** and stay consistent. **As of 2026-04-13:** community leaderboard **GET/POST** use **403** with JSON body **`{"error":"feature_disabled","feature":"community_lb_get"|"community_lb_post"}`** (see **`docs/openapi.yaml`** and `nutonic_server/main.py` exception handler).

---

## Resolved vs earlier draft

| Topic | Resolution |
|-------|------------|
| PRO stub vs full | **Full PRO jobs v1**; all tabs visible. |
| Android + desktop only first | **Superseded:** v1 is **Android + iOS + Desktop (Win/Mac/Linux) + Web** with strict parity. |
| Optional server `features` | **In scope** — normative for v1 client/server contract. |

---

## Remaining implementation choices (not product scope cuts)

1. **403 vs 404** when a feature is off — document in OpenAPI once.
2. **`POST .../guesses/record`** (telemetry) — separate optional flag in config if product wants it distinct from community POST.
3. **Web + community POST** — CORS allowlist + JWT + official client program per `rules/05` §Official client.

---

## Sign-off

| Item | Owner | Date |
|------|-------|------|
| v1 multiplatform + parity | | |
| PRO day-one + all tabs | | |
| `/api/v1` + `features` in config/health | | |
