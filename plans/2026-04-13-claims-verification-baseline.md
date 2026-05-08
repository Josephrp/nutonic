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
**Eighth pass:** 2026-04-16 — **§2.8** + **§3** inference wording corrected (**packages present**; “stub” = **default CI / no-key** behavior, not missing repos); aligns with gap analysis **v1.2** and [`plans/2026-04-16-stub-replacement-implementation-plan.md`](2026-04-16-stub-replacement-implementation-plan.md); this memo **v0.9**.  
**Ninth pass:** 2026-04-18 — **IMP-110** normative WBS filed as [`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](2026-04-18-streetview-google-perpendicular-sampling-full-scope.md) (filename retains earlier “perpendicular” working title; **v0.3** pivots DoD to **stochastic S2 disk + random headings** and **defers** road-bearing / Tile graph research — see that plan **§0** / **§13–§15**).  
**Tenth pass:** 2026-04-20 — gap analysis **v1.4** ( **`inference/pro_materialization_service/`** §3 row **Present**; §1 inference + client shell corrections; backlog **IMP-083** manifest refresh note); this memo **v1.1**.  
**Eleventh pass:** 2026-04-20 — **IMP-110** vs repo: `inference/streetview_pano_service/` implements **§13** items **1–3** (default **`STOCHASTIC_S2_FOOTPRINT`**, **`pano=`** Static when metadata supplies id, stub parity, legacy + **`OMNI_SINGLE_PANO`**); **`tools/batch_streetview_hints.py`** forwards **`sampling_mode`** / **`area_radius_m`** / seeds. **Remaining** for “close IMP-110” is **§13 item 4** (batch **`model_pins`** / LFM rank merge discipline, docs, observability) plus **§14** optional **J*** checklist — **not** road-bearing providers (explicitly **not DoD** in plan **v0.3**). Gap analysis **v1.5**; this memo **v1.2**.  
**Twelfth pass:** 2026-04-21 — **Shipped stills:** **`git ls-files`** + **`validate_shipped_compose_resources.py`** confirm **`composeResources/files/maps/*.jpg`**, **`manifest.full.json`**, and **`server/.../bundles/*.jpg`** are **tracked** — prior “empty maps / registry-only” snapshots were **workspace incomplete**, not repo truth. **IMP-081** reframed as **regeneration workflow**, not missing first assets. **IMP-110 §13.4 partial:** **`batch_streetview_hints.py`** chunked LFM **`rank`** merge + **`reports/model_pins.json`**. Gap analysis **v1.6**; this memo **v1.3**.  
**Thirteenth pass:** 2026-04-21 — **Client:** retired photo gallery removed; **`refreshScanHubCatalog`** + gap **v1.7**; this memo **v1.4** (§2.3, §2.4, §3).

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

**Repo reality (reverified 2026-04-13; gallery sample 2026-04-21):** `nutonic/settings.gradle.kts` has **`rootProject.name = "nutonic"`**; shared and app sources use **`package com.nutonic...`** (no `example.imageviewer` under `nutonic/`). **Verdict: Corrected** — prior “C0 not started” claim was **false** for identity/namespace; **C0 template-only surfaces:** the retired **photo gallery** sample is **removed** (no SETUP entry; see gap analysis **v1.7**).

---

### 2.4 “Thin server: FastAPI health + OpenAPI first; keep `torch` out of `server/`.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `plans/2026-04-07-game-server-thin-orchestrator.md` §8 **P0** (FastAPI skeleton, **`GET /api/v1/health`**, OpenAPI stub, Dockerfile); §0 dependency table (“exclude torch, transformers, terratorch”); `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §0–§0.2. |

**Repo reality (reverified 2026-04-13; SCAN catalog naming 2026-04-21):** All **2026-04-14** items **plus** **`GET /api/v1/cache/manifest`** (ETag, comma-separated **`If-None-Match`**, **`locations`** / **`ai_guesses`** omitted by default unless **`NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH`** is set for full fixture assertions in **`server/tests/`**); **`Settings`** exposes safer **`features`** defaults and configurable **`jwt_secret`**. **Client:** **`NutonicApiClient`**, SCAN **`refreshScanHubCatalog`** in **`com.nutonic.shell.ScanHubCatalog`** (manifest-first catalog when **`ContentCacheRepository`** returns maps), **`WorldMapGameplayDetail`** wired with **`contentCacheRepository`** + **`LocalNonRankedLeaderboardRepository`** (**IMP-083** core). **`docs/openapi.yaml`** + pytest route parity unchanged. **Verdict:** Thin server **P0 + S0 + S1c/manifest slice** **landed**; spine completion per gap **v0.8** / backlog **section 0.1** (**IMP-081**, **IMP-083** E2E exit, **IMP-084**, **IMP-090**).

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

| Verdict | **Partial — nuance** |
|---------|--------------|
| Evidence | `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §0.1 script-first, §0.2 topology; `inference/README.md` (optional batch/PRO; thin game server **no torch**); phased tables defer **S5**/**S6** and full orchestrator **P4+** after manifests (`plans/2026-04-07-complete-implementation-architecture.md` §9). |
| Correction | **“Defer” ≠ “no packages”:** `inference/*` **services exist** and ship in CI with **stub/default backends**; **game server** may **`httpx`** to **`pro_materialization_service`** via **`InferenceClient`** when **`FEATURE_PRO_JOBS`** and URLs are set (**IMP-092** partial). **Still deferred for production trust path:** non-stub GPU deploys, **IMP-110** batch/docs/observability polish (and optional **§14 J*** items), full **TerraMind** demos — see repo reality paragraph below. **Street View:** per **[`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](2026-04-18-streetview-google-perpendicular-sampling-full-scope.md) v0.3**, **road-bearing providers are not required to ship** — they are **deferred** research, not DoD. |

**Repo reality (2026-04-16, reverified 2026-04-20):** `inference/` contains **deployable FastAPI packages** with **`pytest`** in **`.github/workflows/nutonic-ci.yml`**: **`streetview_pano_service/`** (health + **`POST /api/v1/panos/sample`**; **Google** path when keyed — **`google_sample.sample_panos_google_stochastic`** implements **seeded disk anchors**, **`pano=`** + **random headings**, **`LEGACY_RADIAL_OFFSET`**, **`OMNI_SINGLE_PANO`** — else **synthetic JPEG** stub frames), **`lfm_vl_hint_service/`** (**`stub` | `transformers` | `openai_compatible`**), **`lfm_vl_satellite_caption_service/`**, **`pro_materialization_service/`** (internal materialize + public **stub** route), optional **`terramind_tim_local/`**. **`tools/batch_streetview_hints.py`** forwards **`sampling_mode`**, **`area_radius_m`**, **`jitter_seed`**, **`min_anchor_separation_m`** to the worker. **Normative** batch → bundle → KMP embed sequencing: **`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`** (Phase **D**). **Corrected claim:** services are **not** absent — **production-hardening** (non-stub Space defaults, **`InferenceClient`** full fan-out, **IMP-110** §13.4 / §14 checklist) remains **ahead**, per **`plans/2026-04-16-stub-replacement-implementation-plan.md`**.

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
| `inference/*` **production** workers | Packages **exist** and run in CI with **stub / default-CPU** paths; **IMP-110** remaining work tracks **§13.4** (batch + docs + **`model_pins`** / LFM merge discipline) and **§14** optional **J*** items, not road-bearing-only features (**[`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](2026-04-18-streetview-google-perpendicular-sampling-full-scope.md)** v0.3). **IMP-111/112** (non-stub VLM deploy defaults), **IMP-113** (PRO materialization completeness), and **`plans/2026-04-16-stub-replacement-implementation-plan.md`** cover other hardening. **Normative batch + embed** sequencing: **`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`**. |
| ~~KMP still template identity~~ | **Largely resolved** — `com.nutonic` + `nutonic` root name; retired **photo gallery** template **removed** (**gap analysis v1.7**). |
| ~~**KMP ↔ server wire-up**~~ | **Largely resolved** — **`NutonicApiClient`** in `shared` (**Ktor** + **`kotlinx.serialization`** DTOs aligned to **`docs/openapi.yaml`**); **SCAN** / **RANK** call **GET maps**, **GET/POST leaderboard**, **GET config**, **auth token** paths (**IMP-070**). **Partial** **IMP-071**: shared hub **`map_id`**, **Final results → RANK** + saveable route **`rankFocusMapId`** / **`#`** fragment (not yet production “no hardcoded rows” / full C4). |
| ~~**Community `LeaderboardStore` only in-memory**~~ | **Resolved** — **`IMP-060`**: **`SqliteLeaderboardStore`** + idempotency table, env-configurable URL, **`pytest`** file persistence + **`TestClient`** hermetic in-memory default. |
| **`MapViewport` / gameplay spine** | **Updated (2026-04-21)** — **`MapViewport`** interactive + **`WorldMapGameplayDetail`** wired; **local** non-ranked **`appendRow`** on submit (**`IMP-083`** **partial**). **`WorldMapGameplayPersistenceTest`** (`nutonic/shared` **`desktopTest`**) exercises shipped manifest **`poi_0000`**, overlay, and **`LocalNonRankedLeaderboardRepository`** persistence (**2026-04-20**). **Shipped stills + server bundles:** **git-tracked** JPEGs + **`manifest.full.json`** (**gap analysis v1.6**). **Remaining:** **IMP-081** = document **regeneration** when catalog changes; **IMP-083** broader acceptance (optional **`POST .../guesses/record`**, full **`docs/GAME-ENGINE.md` §10** state machine), **IMP-084** polish (**Web** share), **ranked clue-pack** merge polish (**§7** shipped-cache plan). |
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
| 0.9 | 2026-04-16 | **Eighth pass** header; **§2.8** repo reality + **§3** gap row: inference packages **landed**; production hardening per **stub-replacement plan**; gap analysis **v1.2** cross-ref. |
| 1.0 | 2026-04-18 | **Ninth pass** header (initial WBS cross-ref); gap analysis **v1.3**. **Superseded** for **IMP-110** DoD wording by **v1.2** (plan **v0.3** pivot + repo verification). |
| 1.1 | 2026-04-20 | **Tenth pass** header; gap analysis **v1.4** cross-ref (PRO materialization doc fix + gameplay **`refreshManifest()`** note; backlog **§0.1** / **IMP-083** aligned). |
| 1.2 | 2026-04-20 | **Eleventh pass** header; **§2.4** repo reality encoding fix; **§2.8** + **§3** aligned with **IMP-110** plan **v0.3** (stochastic DoD in repo; road-bearing deferred) + **`streetview_pano_service`** / batch forwarding evidence; gap analysis **v1.5**. |
| 1.3 | 2026-04-21 | **Twelfth pass** header; §3 spine gap row: **git-shipped** map stills + server **`bundles/`**; **IMP-081** / **IMP-110 §13.4** wording; gap analysis **v1.6**. |
| 1.4 | 2026-04-21 | **Thirteenth pass:** §2.3 / §2.4 / §3 gallery wording aligned with **gap analysis v1.7** (photo gallery removed; **`refreshScanHubCatalog`** naming). |

