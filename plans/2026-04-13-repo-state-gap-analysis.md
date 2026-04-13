# NU:TONIC — Repo state vs target architecture (gap analysis)

**Date:** 2026-04-13  
**Audience:** Implementers prioritizing first milestones.  
**Target reference:** `plans/2026-04-07-complete-implementation-architecture.md` §2 (layout), §9 (phases).

---

## 1. Summary table

| Area | Target (normative) | Current repo state (2026-04-13) | Gap severity |
|------|---------------------|----------------------------------|--------------|
| Gradle root identity | `nutonic/` as KMP root; product package `com.nutonic.*` (`rules/03`, complete plan **C0**) | `rootProject.name = "imageviewer"` in `nutonic/settings.gradle.kts`; Kotlin packages `example.imageviewer` | **High** — do **C0** first |
| Thin game `server/` | FastAPI app, `docs/openapi.yaml` or export, Dockerfile (`plans/2026-04-07-game-server-thin-orchestrator.md`) | **No `server/` directory** | **High** |
| OpenAPI artifact | Co-located with server (`rules/05`, complete plan §6); versioned **`/api/v1/*`** including **`GET /api/v1/health`** | No `openapi.yaml` located | **High** |
| `inference/*` workers | Discrete services per `inference/README.md` | Only `inference/README.md` (anchor) | **Medium** — expected pre-spine |
| Client shell (5 tabs, theme) | **C1** complete plan | Image Viewer sample UI / structure | **High** — product shell not yet NU:TONIC |
| `server/docs/TOPOLOGY.md` | Required when multi-deploy (`game-server-thin-orchestrator` §3) | N/A (no server) | **Low** until first HTTP fan-out |
| CI / quality | `rules/11`, `docs/PM2_LOCAL_VERIFICATION.md` for `nutonic/**` | Workflows may exist — not re-audited here | **TBD** in backlog |

---

## 2. Kotlin multiplatform (`nutonic/`)

**Present modules (from `settings.gradle.kts`):** `:androidApp`, `:shared`, `:webApp`, `:desktopApp`, `:mapview-desktop`.

**Implication:** Map desktop port exists (`mapview-desktop`), aligning with complete plan **C5** (“Android first + desktop second”) once `MapViewport` is defined — but **C0–C2** and **server contracts** should precede multi-engine polish.

---

## 3. Backend and inference

| Path | Expected | Actual |
|------|----------|--------|
| `server/src/nutonic_server/` | Thin orchestrator layout §3 | Missing |
| `inference/streetview_pano_service/` | CPU pano / static URL builder (batch) | Missing |
| `inference/lfm_vl_hint_service/` | GPU hint JSON | Missing |
| `inference/lfm_vl_satellite_caption_service/` | Satellite specialist | Missing |
| `inference/pro_materialization_service/` | PRO fetch/resample (`plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md`) | Missing |

**Conclusion:** All inference and game-server implementation work remains **ahead** of the current tree; sequencing should follow `plans/2026-04-13-prioritized-implementation-task-backlog.md`.

---

## 4. Documentation completeness (informational)

Multiple product specs exist under `docs/` (GAME-ENGINE, SOCIAL-AND-COMPETITION, RANKED-MODE, PRO tab, INTEL, etc.) — **authoritative for behavior**. This gap analysis does **not** judge doc freshness; implementation tasks link to those docs in the backlog.

---

## 5. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-13 | Initial gap table from workspace glob + settings scan |
| 0.2 | 2026-04-13 | OpenAPI row: explicit **`/api/v1/health`** + versioned paths (align orchestrator §6–§8 + backlog invariants) |
