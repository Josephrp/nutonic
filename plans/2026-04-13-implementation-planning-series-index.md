# NU:TONIC — Implementation planning series (index)

**Date:** 2026-04-13  
**Purpose:** Entry point for the **2026-04-13** planning artifacts that verify earlier priority advice and decompose work into waves and task IDs.

**Repo note (2026-04-13 verification):** Use **`plans/2026-04-13-repo-state-gap-analysis.md` v0.8** and **`plans/2026-04-13-claims-verification-baseline.md` v0.7** as the current snapshot. **Landed:** **IMP-060**, **IMP-070**, **IMP-073** (**`MapViewport`** in gameplay), **IMP-080** (manifest client + server + tests), client **IMP-072** path (**manifest-first** SCAN), **partial** **IMP-071** / **IMP-083** / **IMP-084**. Still **open:** **IMP-081** (versioned **bundle** bytes), **IMP-083** automated **E2E** acceptance, **IMP-084** success overlay + game **share** stubs, **per-route BGM**, **ranked** (**IMP-090**), **`InferenceClient`**, **`inference/*`**. Details: **`plans/2026-04-13-prioritized-implementation-task-backlog.md` §0.1** (table refreshed **2026-04-13**; doc history **0.6**).

| Document | Role |
|----------|------|
| [`2026-04-13-claims-verification-baseline.md`](2026-04-13-claims-verification-baseline.md) | Claim-by-claim verification against normative plans + repo inspection; notes **P0 vs S0** nuance. |
| [`2026-04-13-repo-state-gap-analysis.md`](2026-04-13-repo-state-gap-analysis.md) | Current tree vs target layout (what is missing today). |
| [`2026-04-13-prioritized-implementation-task-backlog.md`](2026-04-13-prioritized-implementation-task-backlog.md) | **Primary execution list:** waves **W0–W10**, task IDs **IMP-000**–**IMP-132**, subtasks, dependencies, acceptance criteria. **Start here for contract invariants** (`/api/v1/health`, versioned routes, dependency gates). |

**Upstream normative plans (unchanged):**  
`plans/2026-04-07-complete-implementation-architecture.md`, `plans/2026-04-07-game-server-thin-orchestrator.md`, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`, `docs/GAME-ENGINE.md`.

---

## Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-13 | Initial index |
| 0.2 | 2026-04-13 | Repo reassessment note + pointer to gap analysis **v0.3** / claims baseline **v0.3** |
| 0.3 | 2026-04-14 | Repo note bumped to gap **v0.5** / claims **v0.5**; **IMP-070** landed, **IMP-071** / **IMP-072** partial, **CI** `server/` |
| 0.4 | 2026-04-14 | Repo note bumped to gap **v0.6** / claims **v0.6**; **IMP-060** SQLite **`LeaderboardStore`** landed; backlog **§0.1** **v0.5** |
| 0.5 | 2026-04-13 | Repo note bumped to gap **v0.8** / claims **v0.7**; **IMP-073**/**080**/**manifest-first** **IMP-072** recorded **landed**; **IMP-081**/**083** exit/**084**/**BGM**/**ranked**/**inference** still open; backlog **§0.1** doc history **0.6** |
