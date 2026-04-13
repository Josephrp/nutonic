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

**Repo snapshot date:** 2026-04-13 (workspace inspection).

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

**Repo reality:** `nutonic/settings.gradle.kts` still has `rootProject.name = "imageviewer"`; shared sources still use `package example.imageviewer` — **C0 not started** (confirms §9 C0 is still applicable).

---

### 2.4 “Thin server: FastAPI health + OpenAPI first; keep `torch` out of `server/`.”

| Verdict | **Verified** |
|---------|--------------|
| Evidence | `plans/2026-04-07-game-server-thin-orchestrator.md` §8 **P0** (FastAPI skeleton, **`GET /api/v1/health`**, OpenAPI stub, Dockerfile); §0 dependency table (“exclude torch, transformers, terratorch”); `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §0–§0.2. |

**Repo reality:** No `server/` directory present; no `openapi.yaml` at repo root — **P0/S0 not landed**.

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

**Repo reality:** `inference/` contains only `README.md` (contractual anchor) — aligns with “not started,” consistent with deferral after spine.

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
| No `server/` tree | All S* / P* server work is greenfield. |
| §9 **S1c** prose used unversioned `/api/maps` | **Corrected** in `plans/2026-04-07-complete-implementation-architecture.md` §9 — implement paths only from **`docs/openapi.yaml`**. |
| `inference/*` packages absent | Inference plans are preparatory until spine + contracts exist. |
| KMP still template identity | C0 is prerequisite to avoid shipping wrong package IDs. |

---

## 4. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-13 | Initial verification memo tied to advisory + repo inspection |
| 0.2 | 2026-04-13 | Health path reconciliation (`/api/v1/health`); S1c versioned paths note; cross-links to backlog contract invariants |
