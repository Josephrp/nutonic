# ADR — v1 KMP targets and `MapViewport` engine matrix

**Status:** Product direction (v1 **comprehensive multiplatform** + **strict parity** across shipped clients).  
**Date:** 2026-04-13 (amended same day: full parity, desktop tri-OS, web in matrix).  
**Related:** `rules/04-maps-and-gameplay.md`, `rules/03-kotlin-multiplatform-structure.md`, `plans/2026-04-07-complete-implementation-architecture.md` §3.4 / §13 item 1, `plans/2026-04-13-prioritized-implementation-task-backlog.md` **IMP-000**, `plans/2026-04-13-product-flags-v1.md` **IMP-001**.

---

## Context

- **`MapViewport` / `GameMapController`** lives behind one **`commonMain`** contract; each target ships a **thin** `expect`/`actual` (`rules/04-maps-and-gameplay.md`).
- **Strict v1:** **behavioral parity** across all v1 targets — same routes, shell, tabs, guess flow, leaderboard dimensions, and PRO entry surface; only **platform ports** (map SDK, secure storage, attestation hooks) differ where the OS requires it.
- Gradle **`shared`** already declares **Android**, **iOS** (device + simulators), **JVM desktop** (one **Compose Desktop** line used to ship **Windows, macOS, Linux**), **js**, and **wasmJs** (`nutonic/shared/build.gradle.kts`).
- **`mapview-desktop`** today is **Compose + OSM raster tiles** (`OPENSTREET_MAP_*` in `nutonic/mapview-desktop/.../Config.kt`). Android already depends on **Google Maps Compose**.

---

## v1 target matrix (primary = all; no deferred “v1.1” platform)

| KMP / ship surface | OS coverage | First `MapViewport` engine | Notes |
|--------------------|-------------|----------------------------|--------|
| **Android** | Android devices | **Google Maps** (Maps Compose) | Keys / Play Services policy in Android build config — not `commonMain`. |
| **iOS** | iPhone / iPad (+ simulators for CI) | **MapKit** (or agreed thin Swift/Compose interop wrapper) | Same contract as Android; satellite/road/hybrid mapped per `rules/04`. |
| **Desktop** (`jvm("desktop")`) | **Windows, macOS, Linux** | **OSM + in-repo `mapview-desktop`** (Compose tile stack) | One desktop module; release pipelines produce per-OS installers as product defines. |
| **Web** (`js` + `wasmJs`) | Browser | **MapLibre GL JS or Leaflet** (or documented Canvas fallback for constrained envs) | CORS, key policy, and perf differ from native — parity is **UX + contract**, not identical GPU path (`complete` plan §11). **js** vs **wasmJs** share one Web `MapViewport` design; dual artifacts stay build/test parity. |

**Out of scope for this ADR:** Choosing store listing order or regional rollout — not the same as **code** parity.

---

## Implementation status (IMP-073, 2026-04-13)

- **Desktop:** interactive `MapViewport` via `mapview-desktop` (OSM), provisional/locked markers, peer/AI overlays, and optimistic tap feedback.
- **Android:** interactive `MapViewport` via Google Maps Compose, marker phases, and shared camera/bounds contract.
- **iOS:** interactive `MapViewport` via MapKit with tap-to-place and marker annotations on the shared contract.
- **Web (`js` + `wasmJs`):** interactive Canvas fallback `MapViewport` (pan/zoom/tap + marker layers + bounds) on the shared contract; MapLibre/Leaflet remains an optional future upgrade path.

## Annex and off-client orchestration (normative for v1)

These **do not** run inside the Kotlin game client; they are still **v1 ecosystem** dependencies:

| Component | Role |
|-----------|------|
| **Game server** (`server/`, FastAPI) | **`/api/v1/*`** REST, auth, ranked tickets, PRO job orchestration, optional leaderboard aggregates — per `plans/2026-04-07-game-server-thin-orchestrator.md`. |
| **Hugging Face Jobs** (and related Spaces / workers) | Batch materialization, dataset shards, TiM / cache hydration, PRO-adjacent pipelines — **`data/scripts/`** and backend plans; clients consume **manifests / bundles / job results** via the game server, not Hub tokens on device (`rules/13-client-cache-and-data-plane.md`). |
| **Other scripts / inference services** | **`inference/*`**, TerraMind workers, PRO materialization service — invoked from server or Jobs as already documented in architecture and PRO spec. |

---

## Implications

- **Parity rule** (`rules/04`): gestures, guess submission, feedback timing, and **tab shell** (SCAN · INTEL · RANK · SETUP · **PRO**) align across targets; basemap **skin** may differ by SDK.
- **API versioning:** all game-server paths under **`/api/v1/...`** (this ADR + OpenAPI; illustrative prose in `docs/RANKED-MODE.md` §4 should be read as **`/api/v1/ranked/...`** etc. when implemented).
- **Ranked / JWT / attestation** (`rules/05`): implement on **Android + iOS** to full product bar; **desktop + web** follow the same **OpenAPI** contract with **documented** weaker attestation / official-client limits where applicable.
- **Reference still** (e.g. Mapbox Static) remains provider-agnostic relative to basemap engine (`rules/04`).

---

## Sign-off

| Role | Name | Date | Approved |
|------|------|------|----------|
| Product / tech lead | *TBD* | | ☐ |

Keep this file as the **single** map-engine matrix reference linked from **`plans/2026-04-07-complete-implementation-architecture.md`** §13 item 1.



