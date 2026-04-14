# NU:TONIC — Verification baseline for prior implementation-priority advice

**Date:** 2026-04-13  
**Purpose:** Record **evidence-backed** verification (or correction) of the priority guidance given in the 2026-04-13 conversation: contract-first thin `server/`, client-owned non-ranked loop, defer heavy inference until the spine exists.  
**Authority:** Normative plans and docs cited below override this memo when they conflict.

---

## 1. Method

| Step | Action |
|------|--------|
| A | Restate each advisory claim in testable form. |
| B | Locate **primary** normative source (`plans/*`, `docs/*`, `rules/*`). |
| C | Spot-check **repo reality** (Gradle tree, packages, presence of `server/`, `inference/*` scaffolds). |
| D | Verdict: **Verified**, **Partial** (nuance), or **Corrected**. |

**Repo snapshot date:** 2026-04-13 (initial workspace inspection).  
**Reassessment date:** 2026-04-13 (second pass: reverified `nutonic/`, `server/`, `docs/openapi.yaml` against claims in §2.3–§2.4 and §3).  
**Third pass:** 2026-04-14 — **IMP-070** / partial **IMP-071** / **IMP-072** (static maps) + **CI** `server/` pytest reflected in §3 (gap analysis **v0.5**).  
**Fourth pass:** 2026-04-14 — **IMP-060** SQLite **`LeaderboardStore`** (gap analysis **v0.6**).  
**Fifth pass:** 2026-04-14 — gap **v0.7** / **v0.8** prep: manifest route, redaction, gameplay + SCAN wiring (**IMP-080** / **IMP-083** partial).  
**Sixth pass:** 2026-04-13 — backlog **§0.1** table re-verified vs `nutonic/` + `server/`; gap analysis **v0.8**; this memo **v0.7**.  
**Seventh pass:** 2026-04-14 — gap analysis **v0.9** ( **`inference/streetview_pano_service/`** stub noted); **shipped-cache / narrative / hint pipeline** plan added — [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](2026-04-14-shipped-cache-narrative-hint-pipeline.md); this memo **v0.8**.

---

## 2. Claim-by-claim results

### 2.1 “Lock scope: OpenAPI `/api/v1`, Kotlin DTOs aligned, single public `baseUrl`.”

| Aspect | Verdict | Evidence |
|--------|---------|----------|
| Versioned REST + contract-first | **Verified** | `plans/2026-04-07-complete-implementation-architecture.md` §6 (OpenAPI co-located with server; Kotlin serializers match); `plans/2026-04-07-game-server-thin-orchestrator.md` §7–§8 **P0** (health **`GET /api/v1/health`** aligned with §6 HF); `docs/GAME-ENGINE.md` §0 / §3 (contract-first). **Note:** §8 **P0** previously said `GET /health`; **reconciled 2026-04-13** to **`/api/v1/health`** — see `plans/2026-04-13-prioritized-implementation-task-backlog.md` contract invariants. |
| Single `baseUrl` for clients | **Verified** | `plans/2026-04-07-game-server-thin-orchestrator.md` §0 executive table (“One public `baseUrl`”); `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §0 (client invariant: documented HTTP only). |

---

### 2.2 “Add `server/docs/TOPOLOGY.md` early for env vars, URLs, timeouts.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `plans/2026-04-07-game-server-thin-orchestrator.md` §3 target layout lists `server/docs/TOPOLOGY.md` as mandatory when split deploys land; `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §9 and end of §5.3 echo “add TOPOLOGY with URLs, env vars, sequence diagrams.” |

---

### 2.3 “Client phases C0–C2 (hygiene, theme + five tabs, screen shells) before deep features.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `plans/2026-04-07-complete-implementation-architecture.md` §9 table rows **C0**, **C1**, **C2** with exit criteria; §13 next actions explicitly: “Execute client **C0 → C2** in parallel with server **S0 → S1**.” |

**Repo reality (reverified 2026-04-13):** `nutonic/settings.gradle.kts` has **`rootProject.name = "nutonic"`**; shared and app sources use **`package com.nutonic...`** (no `example.imageviewer` under `nutonic/`). **Verdict: Corrected** — prior “C0 not started” claim was **false** for identity/namespace; **Partial** for strict C0 “remove all template-only surfaces” (legacy **photo gallery** sample remains reachable from SETUP for dev/demo).

---

### 2.4 “Thin server: FastAPI health + OpenAPI first; keep `torch` out of `server/`.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `plans/2026-04-07-game-server-thin-orchestrator.md` §8 **P0** (FastAPI skeleton, **`GET /api/v1/health`**, OpenAPI stub, Dockerfile); §0 dependency table (“exclude torch, transformers, terratorch”); `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §0–§0.2. |

**Repo reality (reverified 2026-04-13):** All **2026-04-14** items **plus** GET /api/v1/cache/manifest (ETag, comma-separated If-None-Match, locations/i_guesses omitted by default unless NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH is set for full fixture assertions in server/tests/test_health.py); Settings exposes safer eatures defaults and configurable jwt_secret. **Client:** NutonicApiClient, SCAN scanHubRefreshCatalog (manifest-first catalog when ContentCacheRepository returns maps), WorldMapGameplayDetail wired with contentCacheRepository + LocalNonRankedLeaderboardRepository (**IMP-083** core). docs/openapi.yaml + pytest route parity unchanged. **Verdict:** Thin server **P0 + S0 + S1c/manifest slice** **landed**; spine completion per gap **v0.8** / backlog **section 0.1** (**IMP-081**, **IMP-083** E2E exit, **IMP-084**, **IMP-090**).

---

### 2.5 “First server milestone can combine thin P0 with architecture S0 (in-memory leaderboard + mock auth).”

| Verdict | **Partial — nuance** |
|---------|----------------------|
| Correction | The **thin orchestrator** table **P0** does **not** list an in-memory leaderboard; **P3** is optional community leaderboard and **P2** is ranked. The **complete architecture** **S0** row *does* include “in-memory leaderboard + mock auth” alongside FastAPI OpenAPI (`plans/2026-04-07-complete-implementation-architecture.md` §9). §13 also says “Land OpenAPI skeleton + FastAPI P0 (**leaderboard + health**) **per** `plans/2026-04-07-gradio-terramind-backend.md`” — i.e. the **merged** client+server roadmap expects a **slightly richer** first server slice than P0 alone. |
| Practical merge | For **first vertical slice**, implement **P0** plus **S0 extras** (debug `GET` leaderboard + token stub) as one milestone — see backlog **WAVE-S0**. |

---

### 2.6 “Anonymous session JWT for rate limits is consistent with product stance.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `docs/GAME-ENGINE.md` §0 (game-server session JWT, anonymous OK, for rate limits / cache keys); `plans/2026-04-07-game-server-thin-orchestrator.md` §1.1 (anonymous device sessions). |

---

### 2.7 “Non-ranked core loop: client authority; manifests/bundles; local per-`map_id` leaderboard; optional community `POST` later.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `docs/GAME-ENGINE.md` §0 (client-owned gameplay; local leaderboards default); `docs/SOCIAL-AND-COMPETITION.md` (async by `map_id`); `plans/2026-04-07-complete-implementation-architecture.md` §5.0, §9 **S1c** / **S3**. |

---

### 2.8 “Defer live LFM-VL, pano service, TerraMind demos, PRO materialization until spine stable.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §0.1 script-first, §0.2 topology; `inference/README.md` (services are optional batch/PRO; game server `httpx` only); phased tables defer **S5**/**S6** and orchestrator **P4+** after manifests (`plans/2026-04-07-complete-implementation-architecture.md` §9). |

**Repo reality:** `inference/` contains **`README.md`** plus **`streetview_pano_service/`** **stub** (FastAPI health + placeholder metadata route); **`lfm_vl_hint_service/`** etc. still **absent**. **Normative** batch → bundle → KMP embed sequencing: **`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`** (Phase **D**). Deferral after spine remains **correct** for **full IMP-110+**.

---

### 2.9 “Ranked after skeleton + auth; haversine co-located with secret store.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `plans/2026-04-07-game-server-thin-orchestrator.md` §8 **P2** after **P1**; §1.3 (haversine in server for ranked verification); `docs/RANKED-MODE.md` (referenced from GAME-ENGINE §0). |

---

### 2.10 “`AiGuessStore` / `AI_GUESS` is cache/catalog scoped; do not treat PRO job `Coordinates` as catalog rows by default.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `plans/2026-04-07-game-server-thin-orchestrator.md` §1.6 (AiGuessStore vs PRO); `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §1.1.1 (cited in same §1.6); `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §5.3 persistence reminder. |

---

### 2.11 “`/ops` Gradio after `LeaderboardStore` shares REST read model.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `plans/2026-04-07-game-server-thin-orchestrator.md` §8 **P6** after **P3**; `plans/2026-04-07-gradio-terramind-backend.md` §4.1 (Gradio fed from same read model). |

---

### 2.12 Sequencing summary from normative “Next actions”

**Verified** against `plans/2026-04-07-complete-implementation-architecture.md` §13:

1. Approve monorepo layout §2 + map engine matrix.  
2. Land OpenAPI + FastAPI (health; §13 also mentions leaderboard in same breath — see §2.5).  
3. Client C0–C2 ∥ server S0–S1.  
4. MapViewport + S1c REST, then S3 bundles.  
5. Progressive zoom ADR/OpenAPI if shipped.  
6. E2E round in CI vs dockerized server.

---

## 3. Gaps discovered (not claims, but blockers)

| Gap | Impact |
|-----|--------|
| ~~No `server/` tree~~ | **Resolved** for thin reference slice — see §2.4 reassessment. |
| §9 **S1c** prose used unversioned `/api/maps` | **Corrected** in `plans/2026-04-07-complete-implementation-architecture.md` §9 — implement paths only from **`docs/openapi.yaml`**. |
| `inference/*` **full** workers | **`lfm_vl_hint_service/`** etc. still **absent**; **`streetview_pano_service/`** is a **stub** only — **IMP-110** remains open. **Normative batch + embed** sequencing: **`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`**. |
| ~~KMP still template identity~~ | **Largely resolved** — `com.nutonic` + `nutonic` root name; residual template UX (legacy gallery) is optional debt. |
| ~~**KMP ↔ server wire-up**~~ | **Largely resolved** — **`NutonicApiClient`** in `shared` (**Ktor** + **`kotlinx.serialization`** DTOs aligned to **`docs/openapi.yaml`**); **SCAN** / **RANK** call **GET maps**, **GET/POST leaderboard**, **GET config**, **auth token** paths (**IMP-070**). **Partial** **IMP-071**: shared hub **`map_id`**, **Final results → RANK** + saveable route **`rankFocusMapId`** / **`#`** fragment (not yet production “no hardcoded rows” / full C4). |
| ~~**Community `LeaderboardStore` only in-memory**~~ | **Resolved** — **`IMP-060`**: **`SqliteLeaderboardStore`** + idempotency table, env-configurable URL, **`pytest`** file persistence + **`TestClient`** hermetic in-memory default. |
| **`MapViewport` / gameplay spine** | **Updated (2026-04-14)** — **`MapViewport`** interactive + **`WorldMapGameplayDetail`** wired; **local** non-ranked **`appendRow`** on submit (**`IMP-083`** **partial**). **Remaining:** **IMP-081** scripted bundle registry + **embedded** `manifest.full.json` (**`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`**), **IMP-083** **E2E** + optional telemetry **`POST`**, **IMP-084** polish, full **`docs/GAME-ENGINE.md` §10** state machine, **ranked clue-pack** merge (**§7** shipped-cache plan). |
| ~~**CI scope**~~ | **Resolved** for **`server/`** — **`nutonic-ci.yml`** runs **`pytest`** when `server/**` (or related paths) change; PM2 local verification remains manual (`docs/PM2_LOCAL_VERIFICATION.md`). |

---

## 4. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-13 | Initial verification memo tied to advisory + repo inspection |
| 0.2 | 2026-04-13 | Health path reconciliation (`/api/v1/health`); S1c versioned paths note; cross-links to backlog contract invariants |
| 0.3 | 2026-04-13 | **Reassessment:** §2.3–§2.4 repo reality **corrected** (KMP identity + `server/` + OpenAPI landed); §3 gaps table updated; second-pass snapshot called out in header |
| 0.4 | 2026-04-13 | §2.4: note **403** feature gating, **Idempotency-Key** dedupe, OpenAPI **RFC 3986** server URL rule, and **pytest** contract parity vs FastAPI |
| 0.5 | 2026-04-14 | §3: **KMP ↔ server** and **CI** gaps closed per **gap analysis v0.5**; **IMP-071** recorded as **partial**; **MapViewport** / spine gap unchanged |
| 0.6 | 2026-04-14 | **Fourth pass** header; §2.4 repo reality: **`GET /api/v1/maps` → 200** + **IMP-060** SQLite **`LeaderboardStore`**; §3 new resolved gap row; aligns with gap analysis **v0.6** |
| 0.7 | 2026-04-13 | **Sixth pass** header; §2.4 repo reality extended (**cache/manifest**, redaction, client wiring); §3 spine gap narrowed; aligns with gap analysis **v0.8** + backlog **§0.1** refresh |
| 0.8 | 2026-04-14 | **Seventh pass** header; §3 **`inference/*`** row: **streetview** stub nuance + **shipped-cache plan** link; §3 spine gap row: **embed** manifest / ranked clue pack; aligns with gap **v0.9** + backlog **§0.1** **0.7** |

