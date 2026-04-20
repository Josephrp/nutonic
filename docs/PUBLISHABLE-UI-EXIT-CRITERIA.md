# NU:TONIC — Publishable UI exit criteria

**Purpose:** Binary **ship / no-ship** checklist for **player-facing** builds (store, press demo, public beta).  
**Normative plan:** [`plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md`](../plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md).  
**Rules:** [`rules/07-screens-checklist.md`](../rules/07-screens-checklist.md), [`rules/15-publishable-ui-and-release-readiness.md`](../rules/15-publishable-ui-and-release-readiness.md), [`rules/08-ux-and-performance-footguns.md`](../rules/08-ux-and-performance-footguns.md).

---

## 1. Build and quality gates

| # | Criterion | Verification |
|---|-----------|--------------|
| 1.1 | **`./gradlew :shared:validateCatalog`** succeeds on clean checkout | CI + local |
| 1.2 | **`./gradlew quality test`** (or repo-standard aggregate) green for all shipped targets in matrix | CI |
| 1.3 | **No build-type UI fork**: debug and release artifacts follow the same player-facing behavior and copy | Inspect route rendering + settings under both build types |
| 1.4 | No **TODO** / **FIXME** in `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/` on default play paths | `rg TODO screens` |
| 1.5 | CI endpoint config for game/Hugging Face hosts is documented and consumed from committed config + env injection (not ad-hoc local-only tables) | CI config + docs review |

---

## 2. Product and IA gates (`rules/07`)

| # | Criterion | Verification |
|---|-----------|--------------|
| 2.1 | **SCAN hub** presents **mission** affordances, **map** list/grid, **per-map leaderboard** entry in **≤1** extra action, and **Play** without navigating placeholder-only routes | Manual + UI test |
| 2.2 | **World map gameplay** implements basemap toggle, reference still, bottom-right guess flow, collapsible assists, narrative overlay per `docs/GAME-ENGINE.md` §9–11 | Manual |
| 2.3 | **Success** and **Final results** are distinct surfaces with correct BGM `track_id` per `docs/SCREEN-MUSIC-SPEC.md` | Manual + log |
| 2.4 | **INTEL**, **SETUP**, **PRO** tabs are not title-only stubs; SETUP reflects `docs/CLIENT-SETTINGS-SPEC.md` grouped settings | Manual |
| 2.5 | **Header music toggle** on every checklist surface | Manual |

---

## 3. Design and copy gates

| # | Criterion | Verification |
|---|-----------|--------------|
| 3.1 | No user-visible strings containing **`IMP-`**, **`rules/`**, **`docs/`**, or internal phase codes (`HUMAN_PLAY`, …) on player-facing surfaces | `rg IMP- nutonic/shared/src/commonMain` + manual pass |
| 3.2 | **Cosmetic** play timer (if shown) labeled per `docs/GAME-ENGINE.md` §7.3 | Screenshot review |
| 3.3 | **Offline / server-down** messaging follows the manifest copy matrix in [`plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md`](../plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md) §2.4 with permissive “keep playing” semantics | Manual with server stopped |
| 3.4 | Primary CTAs use **theme** `cta` shape (12–16dp) and semantic colors | Design review vs `docs/DESIGN.md` |
| 3.5 | **Vendored structure parity**: sign-off table references first-party contracts (`docs/VENDORED-UI-CONTRACT-PACK.md`, `rules/07`, `docs/NU_TONIC_ARTIFACT_REFERENCE.md`, publishable plan) with **≥90%** control coverage per screen | Design owner |
| 3.6 | `content_version` mismatch does **not** block core SCAN/gameplay flows when shipped data can provide a playable round; guesses persist locally and sync when possible | Manual offline/online toggle + repository checks |

---

## 4. Audio and Web gates

| # | Criterion | Verification |
|---|-----------|--------------|
| 4.1 | BGM assets are **non-silent** mastered loops for every **`track_id`** shipped in the build | Listen + file size > stub threshold |
| 4.2 | **Web** share flow supports loading / success / error states with dismissible UI and non-blocking navigation; clipboard/native share fallback remains available | Browser manual test |

---

## 5. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-21 | Initial exit criteria aligned with publishable UI plan. |
| 0.2 | 2026-04-21 | Removed `refs/stitch/` dependency from sign-off gate; switched to vendored contract parity checks. |
| 0.3 | 2026-04-21 | Aligned with plan v0.4 AD decisions: permissive skew behavior, debug/release parity, CI endpoint-config documentation, and non-blocking Web share overlays. |
| 0.4 | 2026-04-21 | Note: client **photo gallery** template removed; exit criteria unchanged — no gallery-specific sign-off. |
