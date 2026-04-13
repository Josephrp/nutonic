# NU:TONIC — Prioritized implementation task backlog

**Date:** 2026-04-13  
**Status:** Actionable backlog derived from verified guidance in `plans/2026-04-13-claims-verification-baseline.md`, normative phases in `plans/2026-04-07-complete-implementation-architecture.md` §9, `plans/2026-04-07-game-server-thin-orchestrator.md` §8, and repo gaps in `plans/2026-04-13-repo-state-gap-analysis.md`.

**How to use:** Execute **waves** in order unless tasks explicitly allow parallel tracks (**∥**). Each task has acceptance criteria suitable for PR boundaries.

---

## 0. Conventions

| Field | Meaning |
|-------|---------|
| **ID** | Stable reference for dependencies (`IMP-xxx`). |
| **Wave** | Sequenced milestone bucket. |
| **Deps** | Hard prerequisites (IDs). |
| **∥** | May run in parallel with other tasks in the same wave when deps satisfied. |
| **Refs** | Normative docs/plans (read before implement). |

**Contract invariants (2026-04-13 hardening):**

- **Health:** **`GET /api/v1/health`** only in OpenAPI + FastAPI for P0; aligns `plans/2026-04-07-game-server-thin-orchestrator.md` §6 and §8 **P0** (see §7 there). Avoid a second undocumented health URL.
- **S1c / maps:** Route shapes come from **`docs/openapi.yaml`** under **`/api/v1/...`**; do not copy unversioned `/api/...` snippets from prose tables.
- **Deps column:** “Hard” prerequisites only; task text notes **soft** gates (e.g. JWT before gated `POST`).
- **Inference workers (`IMP-110+`):** Do **not** depend on ranked (**IMP-090**). They may list **`IMP-010`** only for shared Docker/compose smoke patterns; game-server **`InferenceClient`** (**IMP-092**) is for orchestration hardening (**P4**), not for building worker images.

### 0.1 Repo verification (2026-04-13 reassessment)

Cross-check against `plans/2026-04-13-repo-state-gap-analysis.md` **v0.8** and `plans/2026-04-13-claims-verification-baseline.md` **v0.7**.

| ID band | Status vs repo (high level) — **verified 2026-04-13** |
|---------|------------------------------|
| **IMP-000 / IMP-001** | **`docs/map-engines.md`** and **`plans/2026-04-13-product-flags-v1.md`** present; server **`GET /api/v1/config`** → `features` (defaults: **`feature_ranked`** / **`feature_pro_jobs`** **false** until routes ship; **`feature_community_lb_post`** **false** unless enabled). |
| **IMP-010–012** | **`server/`**, **`docs/openapi.yaml`**, **`server/docs/TOPOLOGY.md`**, Dockerfile **7860**, no **`torch`** — **landed**. **`GET /api/v1/cache/manifest`**: ETag, comma **`If-None-Match`**, default **redaction** of **`locations`** / **`ai_guesses`** (**`NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH`** for full fixture tests). |
| **IMP-020** | **`rootProject.name = "nutonic"`**, **`com.nutonic.*`** — **landed**; legacy gallery optional. |
| **IMP-030 / IMP-031** | JWT + gated routes + community LB + **403** `feature_disabled` — **present**. |
| **IMP-040–050 (client)** | Five tabs, theme, shells — **landed**. **IMP-051:** music **master** top bar — **landed**; **per-route BGM** loops — **open** (`docs/SCREEN-MUSIC-SPEC.md`). |
| **IMP-070** | **`NutonicApiClient`** — **landed**. **`NutonicJson`**: **`isLenient = false`** (stricter parse). |
| **IMP-071** | **Partial:** REST + shared **`mapContextId`** + **`rankFocusMapId`** / **`#`** + **Final results → RANK** + **`FinalResultsWithLocalSummary`** (reads **`LocalNonRankedLeaderboardRepository`**). **Remaining:** **C4** release/demo row policy, richer results HUD vs **`rules/07`**. |
| **IMP-072** | **Client:** **manifest-first** SCAN catalog via **`scanHubRefreshCatalog`** when **`ContentCacheRepository.refreshManifest()`** yields map rows; else **`GET /api/v1/maps`**. **Server:** static **`PUBLISHED_MAPS`** (DB-backed index still future). **Verdict:** client **S1c catalog path** **landed** alongside **IMP-080**; normative “full **S1c**” still allows **DB-backed** catalog later. |
| **IMP-073** | **MapViewport** + gameplay route — **landed** (plumbing). |
| **IMP-080** | **Landed (core):** **`ContentCacheRepository`**, platform **`ManifestBlobStore`**, **`ContentCacheRepositoryTest`**, OpenAPI + FastAPI manifest. **Partial:** **80.1** richer “missing bundle / still asset” fallback UX (`docs/GAME-ENGINE.md` §9) vs compose-resource **`files/3.jpg`** only. |
| **IMP-081** | **Open:** no shipped **`bundles/...`** artifact + versioned download path per wave table; stills remain **resources** + manifest **string** refs. |
| **IMP-082** | **Partial:** server fixtures + client **`AiGuessStore`** when manifest includes **`ai_guesses`** (requires **`NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH=true`** or cached full envelope). **No** Parquet / HF sync (**S6** still future). |
| **IMP-083** | **Partial:** **`NutonicApp`** wires **`contentCacheRepository`** + **`LocalNonRankedLeaderboardRepository`** into **`WorldMapGameplayDetail`**; **submit** sets **`roundInstanceId`** and persists **local** row. **Open:** backlog **acceptance** “E2E non-ranked round on device/desktop” — **`WorldMapGameplayUiTest`** is **UI smoke** only (no persisted-row assertion); optional **`POST .../guesses/record`**; full **`docs/GAME-ENGINE.md` §10** state machine; optional **`refreshManifest()`** on gameplay entry (currently **`cachedDocument()`** only). |
| **IMP-084** | **Partial:** final results surface + local summary + RANK navigation. **Open:** **Success overlay** product HUD (**C6**), game-specific **share** hooks (**C7**); gallery **Share** is unrelated. |
| **IMP-060** | **Landed** as before. **Optional:** refresh-token table — **not** implemented. |
| **IMP-060+** | **Still open:** **IMP-090** ranked, **IMP-092**, **`inference/*`**. **Closed vs earlier text:** “manifest depth” is **no longer** a blanket blocker — server + client manifest **landed**; **bundle** + **ranked** work remains. |

---

## Wave W0 — Decisions (short, blocking)

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-000** | **ADR: v1 platform matrix** — v1 is **full multiplatform** (Android, iOS, desktop Windows/macOS/Linux, Web) with **strict parity**; document engines in one file (e.g. `docs/map-engines.md` **or** issue-linked ADR). | 0.1 List targets + OS coverage. 0.2 Pick first `MapViewport` engine per target. 0.3 Annex: HF Jobs, game server, scripts **outside** the client. | — | Matrix + sign-off; linked from `plans/2026-04-07-complete-implementation-architecture.md` §13 item 1. | `rules/04-maps-and-gameplay.md`, complete plan §3.4 |

| **IMP-001** | **Product flags** — v1 ships ranked, community LB `GET`/`POST`, and **full PRO**; **all shell tabs**; optional **`features`** on **`GET /api/v1/config`** (or documented **`/api/v1/health`** extension). | 1.1 Boolean / capability table + runtime toggles. 1.2 Map to **`/api/v1/...`** OpenAPI presence. | IMP-000 | `plans/2026-04-13-product-flags-v1.md` (+ OpenAPI under **IMP-011**). | `docs/RANKED-MODE.md`, `rules/05-networking-leaderboard.md`, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` |

---

## Wave W1 — Contracts and repository hygiene (∥ tracks)

### Track A — OpenAPI + server skeleton

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-010** | Create **`server/`** tree per thin orchestrator §3: `pyproject.toml` (no torch), `src/nutonic_server/main.py`, `Dockerfile` (EXPOSE 7860), `README.md` (env var table stub). | 10.1 Dependencies: fastapi, uvicorn, pydantic, httpx (for future); add **sqlalchemy + aiosqlite** (or asyncpg) **only when** first persistence task needs it—avoid unused DB stack in a pure in-memory S0 slice. 10.2 Implement **`GET /api/v1/health`** (and list it in OpenAPI in **IMP-011**); optional legacy **`GET /health`** redirect only if documented in OpenAPI. 10.3 CORS stub (explicit origins env). | IMP-000 | `uvicorn` local boot; container build succeeds; health answers at **`/api/v1/health`**. | `plans/2026-04-07-game-server-thin-orchestrator.md` §3, §6–§7, §8 P0 |
| **IMP-011** | Add **`docs/openapi.yaml`** (or FastAPI export script) with **versioned** `/api/v1/*` paths; include health + placeholder schemas for future maps/manifest. | 11.1 Document `engine_version` / `content_version` placeholders if used. 11.2 CI or Makefile step to validate YAML (optional). | IMP-010 | Single source of truth agreed (handwritten vs generated). | Complete plan §6; `rules/05-networking-leaderboard.md` |
| **IMP-012** | **`server/docs/TOPOLOGY.md`**: URLs diagram stub, env var names matching README, timeout policy placeholders. | 12.1 List future worker URLs as “TBD”. 12.2 Note “no torch in server” invariant. | IMP-010 | File exists; linked from `server/README.md`. | `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §9 |

### Track B — Client C0 (KMP hygiene)

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-020** | **C0** — Rename `rootProject.name` to product name; migrate packages `example.imageviewer` → `com.nutonic.*` (or agreed base); remove or isolate template-only code. | 20.1 Update all `sourceSets` imports. 20.2 Android namespace / iOS if applicable. 20.3 `./gradlew quality test` green. | IMP-000 | Clean build all included targets from complete plan C0 exit. | Complete plan §9 **C0**; `rules/03-kotlin-multiplatform-structure.md` |

---

## Wave W2 — First vertical slice (server S0 ∥ client C1)

### Server S0 (extends thin P0)

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-030** | Mock **anonymous JWT** issuance + validation dependency for **debug** and optional gated routes. | 30.1 `POST /api/v1/auth/token` or equivalent per `rules/05`. 30.2 Document claims: `sub` optional, `session_id`, `exp`. | IMP-011 | Integration test: missing token → 401 on gated route. | `docs/GAME-ENGINE.md` §0; thin orchestrator §1.1 |
| **IMP-031** | **In-memory leaderboard** `GET` (+ optional `POST` dev-only) for one canned `map_id` — satisfies architecture **S0** without requiring DB yet. | 31.1 Sanitize fields per `rules/05`. 31.2 Match OpenAPI models. 31.3 If this PR ships a **gated** `POST` (or any 401-tested route), land **IMP-030** first; **GET-only** debug leaderboard may ship after **IMP-011** alone. | IMP-011 | Ktor/curl can fetch JSON from running server. | Complete plan §9 **S0** |

### Client C1

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-040** | **C1** — `NutonicTheme` + **Space Grotesk / Inter / Orbitron** vendoring plan (fonts in `composeResources` per platform). | 40.1 Token mapping from `docs/DESIGN.md`. 40.2 Bottom shell **5 tabs**: SCAN · INTEL · RANK · SETUP · PRO with **SCAN** elevated. 40.3 Active indicator **above** icon. | IMP-020 | Visual checklist vs `rules/02-design-system.md`; stub screens per tab. | Complete plan §9 **C1**; `docs/DESIGN.md` |

---

## Wave W3 — Client C2, early C3 ∥ server S1 start

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-050** | **C2** — Screen shells for `rules/07-screens-checklist.md` / complete plan §3.1 list (placeholders OK). | 50.1 Navigation graph sealed routes (`rules/01`). 50.2 Max depth rules. | IMP-040 | All checklist routes reachable. | Complete plan §9 **C2** |
| **IMP-051** | **C3** (can start after C2 partial) — Wire **CLIENT-SETTINGS-SPEC** toggles that affect rendering (reduced motion, contrast). | 51.1 `SettingsRepository` persistence sketch. | IMP-050 | Toggles observable on UI. | `docs/CLIENT-SETTINGS-SPEC.md`; complete plan **C3** |
| **IMP-060** | **S1** — Swap in **SQLite** (or Postgres) for `LeaderboardStore`; optional refresh token table stub. | **2026-04-14:** **Landed** for community LB — 60.1 SQLAlchemy models + idempotency table; 60.2 store interface + **`memory`** URL for tests/dev; **`NUTONIC_LEADERBOARD_DATABASE_URL`**; restart survives **`POST`** rows on default file DB. **Open:** refresh-token table stub (optional). | IMP-031 | Restart survives rows (where POST enabled). | Complete plan §9 **S1**; thin orchestrator P1 overlap |

| **IMP-061** | **Official client registry** stub (in-memory → DB) if any gated `POST` ships in this wave. | 61.1 Registration schema per `docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md` (subset). | IMP-060 | Gated POST rejects unknown client when flag on. | Thin orchestrator §1.2; `rules/05` |

---

## Wave W4 — Networking + map hub (C4 / C5 / S1c)

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-070** | Ktor **`ApiClient`** in `commonMain`; baseUrl from build config; DTOs from OpenAPI (`kotlinx.serialization`). | 70.1 Error mapping + themed retry copy stub (`rules/08`). | IMP-011, IMP-020 | Debug build calls IMP-031 leaderboard. | `rules/05`; complete plan §3.3 |
| **IMP-071** | **C4** — Wire **RANK** + SCAN-embedded leaderboard to REST; **final results → RANK** + `map_id` deep link stub. | **2026-04-14:** REST + route **`rankFocusMapId`** / **`#`** fragment + shared **`mapContextId`** landed. **2026-04-13 verify:** **`FinalResultsWithLocalSummary`** surfaces last **local** non-ranked row + **→ RANK**. **Remaining:** release/demo row policy, richer HUD. | IMP-050, IMP-070 | No hardcoded production rows in release. | Complete plan §9 **C4** |
| **IMP-072** | **S1c** — `GET /api/v1/maps`; optional `GET .../leaderboard`; optional `POST .../scores/self-report` behind flags. | **2026-04-13 verify:** Client SCAN prefers **manifest** snapshot (**`scanHubRefreshCatalog`**) when **`ContentCacheRepository`** is non-null; server lists match manifest **`maps`**. **Remaining:** DB-backed catalog index when product schedules it. | IMP-060 | OpenAPI + server routes match; client consumes catalog (manifest-first or maps). | Complete plan §9 **S1c**; `docs/SOCIAL-AND-COMPETITION.md` |
| **IMP-073** | **C5** — Define **`MapViewport`** `expect`/`actual`; implement **one** engine (per IMP-000). | 73.1 Tap-to-place, optimistic marker. 73.2 Second engine if in matrix. | IMP-071 | Interactive map in SCAN flow (stub mission). | `rules/04`; complete plan §9 **C5** |

---

## Wave W5 — Bundles + manifest (S3) + gameplay spine (C6 / S4 / C7)

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-080** | **`ContentCacheRepository`** + manifest fetch (`ETag` / `content_version`) + local persist (`rules/13`). | **2026-04-13 verify:** **Landed** — client + server + **`ContentCacheRepositoryTest`** + redacted public manifest. **Open:** **80.1** deeper missing-asset / bundle-miss UX. | IMP-072 | Contract tests for manifest parse + cache (**present**). | Complete plan §9 **S3**; `rules/13` |
| **IMP-081** | Ship **one canned bundle** (Mapbox still + metadata) for dev — no HF Jobs required. | **2026-04-13 verify:** **Not started** as a **versioned bundle** download — stills load from **compose resources** via manifest **`still_bundled_resource`** string. | IMP-080 | Client renders still + map; round loads offline-capable. | `docs/GAME-ENGINE.md` §9 |
| **IMP-082** | **S1b** (can parallelize partially) — Dataset sync **stub**: local Parquet or single fixture row for **`AiGuessStore`** keyed by `map_id` + `location_id`. | **2026-04-13 verify:** **Partial** — server **`MANIFEST_AI_GUESSES`** + client **`AiGuessStore`** when manifest exposes rows; **no** Parquet/HF driver. | IMP-080 | For fixture round, `ai_lat`/`ai_lon` resolves after human submit (when manifest not redacted or cache warm). | Complete plan §9 **S1b** |
| **IMP-083** | **S4** — Engine: human phase → **AI_GUESS_PLACED** from cache; client scoring + **local** leaderboard write. | **2026-04-13 verify:** **Partial** — wiring + **local** **`appendRow`** on lock-in + **`roundInstanceId`**; **no** dedicated **E2E** test meeting wave acceptance; optional telemetry **`POST`** absent. | IMP-082, IMP-073 | E2E non-ranked round on device/desktop. | Complete plan §9 **S4**; `docs/GAME-ENGINE.md` §12–13 |
| **IMP-084** | **C6** + **C7** — HUD, success/final results, share hook stubs. | **2026-04-13 verify:** **Partial** — gameplay HUD exists; **final results** + local summary + RANK; **Success overlay** still checklist-level; **share** stubs for scorecard not done. | IMP-083 | Matches trust: non-ranked numbers from `commonMain`. | Complete plan §9 **C6**, **C7** |

---

## Wave W6 — Ranked + thin orchestration hardening

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-090** | **P2** — Ranked `start` / `submit`; `scoring/haversine.py`; ticket store; **no** server play timer fields. | 90.1 Idempotency keys. 90.2 OpenAPI bump. | IMP-060, IMP-011, IMP-083 | `test_ranked_flow.py` with mocked inference URLs. **IMP-083** is the spine-first gate: non-ranked E2E green before ranked merges unless **IMP-001** explicitly waives. | Thin orchestrator §1.3, §8 P2; `docs/RANKED-MODE.md` |
| **IMP-091** | Optional **forfeit-*** routes per ranked spec. | | IMP-090 | State machine tests. | Thin orchestrator §1.8; `docs/RANKED-MODE.md` §4 |
| **IMP-092** | **`InferenceClient`** with timeouts, HMAC headers toward stub upstreams (**P4**). | 92.1 Circuit breaker optional. | IMP-010, IMP-090 | Matches orchestrator **P2 → P4** ordering. Mocked upstreams in CI; ranked submit never awaits hint Spaces. | Thin orchestrator §5, §8 P4 |

---

## Wave W7 — Ops UI + optional community (P3 / P6)

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-100** | **P3** — Community leaderboard `GET`/`POST` + idempotency + sanitization. | | IMP-060 | Matches `rules/05`. | Thin orchestrator §8 P3 |
| **IMP-101** | **P6** — Mount Gradio **`/ops`** read-only from same `LeaderboardStore` queries as REST. | | IMP-100 | Gradio rows == REST rows. | `plans/2026-04-07-gradio-terramind-backend.md` §4; `rules/12` |

---

## Wave W8 — Inference workers (defer until W5 happy path)

Execute sub-plans in **recommended** order (each is its own PR series):

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-110** | `inference/streetview_pano_service` MVP per streetview plan P0–P1. | | IMP-010 | Docker build; health + one pano path. **Does not** require **IMP-092** / ranked. | `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` |
| **IMP-111** | `inference/lfm_vl_hint_service` per LFM-VL master plan. | | IMP-110 (optional ordering) | GPU/ZeroGPU Space boots; JSON contract tests. | `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md` |
| **IMP-112** | `inference/lfm_vl_satellite_caption_service` (optional Intel / EO). | | IMP-111 | Caption JSON matches OpenAPI internal stub. | Same master plan |
| **IMP-113** | **`inference/pro_materialization_service`** per PRO materialization plan P0–P1 (Mapbox-only branch first). | | IMP-010 | `RGB_mapbox` end-to-end; no torch in container if policy holds. **Does not** require **IMP-092** / ranked. | `plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md` |
| **IMP-114** | **P7** — `server` `POST .../pro/jobs` control plane + poll (**feature-flagged**). | 114.1 Prefer **`InferenceClient`** (**IMP-092**) for worker calls when **IMP-092** exists; until then, **`httpx`** in `routes_pro` with the same timeouts/HMAC policy is acceptable. | IMP-113, IMP-011, IMP-030, IMP-060, IMP-001 | **Does not** require ranked (**IMP-090**). Job status JSON only; signed URL pattern documented; PRO routes gated per **IMP-001**. | Thin orchestrator §8 P7; `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` |

**Parallel research / demos (non-blocking for game spine):** `plans/2026-04-07-terramind-gradio-spaces-comprehensive-demo.md`, `plans/2026-04-07-tim-standalone-gradio-poi-dataset.md` — schedule after **IMP-083** or in a separate contributor track.

---

## Wave W9 — Jobs → Dataset → server sync (S6)

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-120** | HF Jobs drivers + Parquet schema for manifests / `tim_modality_outputs` summaries. | 120.1 Retention policy documented. | IMP-080, IMP-082 | Server sync job pulls revision; client unchanged contract. | `plans/2026-04-07-gradio-terramind-backend.md` §2; complete plan §9 **S6** |

---

## Wave W10 — TerraMind orchestration + parity (S5 / C8 / hardening)

| ID | Task | Subtasks | Deps | Acceptance | Refs |
|----|------|----------|------|------------|------|
| **IMP-130** | **S5** — Feature-flagged TerraMind worker calls from server; merge metadata caps into poll responses only. | | IMP-120 | Timeouts documented in TOPOLOGY. | Complete plan §9 **S5**; `rules/06` |
| **IMP-131** | **C8** — Remaining map engines from IMP-000 matrix. | | IMP-073 | Parity sign-off table. | Complete plan §9 **C8** |
| **IMP-132** | **Hardening** — Load tests + REST idempotency soak on **shipped** surfaces (`docs/GAME-ENGINE.md` §14). | 132.1 Minimum soak: **manifest** (**IMP-080**) + **ranked** (**IMP-090**) if ranked shipped; add **community `POST`** when **IMP-100** exists. 132.2 Record SLOs + explicitly list deferred surfaces. | IMP-080, IMP-011 | SLO numbers recorded; soak covers all **merged** idempotent routes (not blocked on optional **IMP-100**). | Complete plan §9 **Hardening** |

---

## Dependency diagram (high level)

```text
IMP-000 / IMP-001
       │
       ├──────────────────────────────┐
       ▼                              ▼
  IMP-010–012 (server)            IMP-020 (C0)
       │                              │
       └──────────┬───────────────────┘
                  ▼
       IMP-030 / IMP-031 (S0)  ∥  IMP-040 (C1)
                  │                    │
                  └────────┬──────────┘
                           ▼
              IMP-050+060+070… (W3–W5 spine)
                           ▼
              IMP-083 (E2E non-ranked)
                           ▼
         IMP-090 (ranked; blocked until 083 unless IMP-001 waives)
                           ▼
         IMP-092 (InferenceClient — orchestrator P4)

  Parallel track (no ranked prereq): IMP-010 → IMP-110 / IMP-113 → IMP-114
  (IMP-111 → IMP-112 chain optional; see W8 table)
```

---

## Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-13 | Initial backlog: waves W0–W10, IDs IMP-000–IMP-132 |
| 0.2 | 2026-04-13 | Hardening: `/api/v1/health` invariant; S1c path wording; IMP-031/090/092/114/132 deps + contract-invariants block |
| 0.3 | 2026-04-13 | **§0.1** repo reassessment table (aligned with gap analysis **v0.3** / claims baseline **v0.3**) |
| 0.4 | 2026-04-14 | **§0.1** reassessment: **IMP-070** landed; **IMP-071** / **IMP-072** **partial**; **IMP-040–050** row split (C2 shells vs BGM asset loops); cross-refs gap analysis **v0.5** / claims **v0.5**; **IMP-071** wave table note |
| 0.5 | 2026-04-14 | **§0.1:** **IMP-060** community **`LeaderboardStore`** / SQLite **landed**; **`IMP-060+`** row narrowed to ranked / inference / manifest; **IMP-072** row clarifies manifest still gates full **S1c**; cross-refs gap + claims **v0.6**; **W3** **IMP-060** wave row annotated **Landed** |
| 0.6 | 2026-04-13 | **§0.1 completeness pass:** cross-ref gap **v0.8** / claims **v0.7**; **IMP-072**/**080**/**082**/**083**/**084** rows rewritten from repo verification; **W5** wave table annotations; **`IMP-060+`** clarified (manifest landed; bundle + ranked still open) |
