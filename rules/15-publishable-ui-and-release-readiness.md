# Publishable UI and release readiness

**Scope:** Rules for when NU:TONIC client UI is **release-grade** vs **engineering prototype**.  
**Plan:** [`plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md`](../plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md).  
**Exit checklist:** [`docs/PUBLISHABLE-UI-EXIT-CRITERIA.md`](../docs/PUBLISHABLE-UI-EXIT-CRITERIA.md).

---

## 1. Non-negotiables

1. **No implementation metadata in player UI** — Forbidden on player-facing surfaces in shipped artifacts: raw `IMP-*` references, `rules/07` fragment citations, OpenAPI path strings, and internal engine phase enum names.

2. **SCAN hub convergence** — `rules/07-screens-checklist.md` **#4b** and **#4c** must not ship as **isolated placeholder routes** in production flavors; primary mission and map discovery live on the **SCAN** tab surface.

3. **Timer semantics** — Any **play budget** or **elapsed** display must be labeled **cosmetic** per `docs/GAME-ENGINE.md` §7.3 and must **not** gate submit.

4. **Manifest honesty + permissive access** — Copy should distinguish **bundled** vs **previously downloaded** server manifest, but `content_version` skew must not force app updates or block core SCAN/gameplay when shipped data can provide a playable round; guesses persist locally and sync when possible.

5. **Vendored parity inputs** — Release readiness must not depend on wiring `refs/stitch/` into git history. `refs/stitch/` may exist locally for reference, but ship/no-ship checks are based on vendored first-party contracts (`docs/VENDORED-UI-CONTRACT-PACK.md`, `rules/07`, `docs/NU_TONIC_ARTIFACT_REFERENCE.md`, `docs/DESIGN.md`, `docs/PUBLISHABLE-UI-EXIT-CRITERIA.md`) per **IMP-140**.

6. **Build parity** — Debug and release must not diverge in player-facing UI behavior. Configuration should come from committed files + documented environment injection (including CI endpoint selection for game/Hugging Face services), not flavor-only code forks.

7. **Share UX completeness** — Share actions may be sync or async under the hood, but player UX must expose loading/success/failure states in dismissible UI without blocking app navigation.

---

## 2. Relationship to other rules

- **`02-design-system.md`** — How tokens land in Kotlin; this file defines **when** the UI is allowed to ship regardless of engine completeness.  
- **`08-ux-and-performance-footguns.md`** — Touch targets, guess modal, music toggle; **this file** adds **copy and debug hygiene**.  
- **`14-testing-validation-pm2-and-documentation.md`** — When changing ship criteria, update **`docs/PUBLISHABLE-UI-EXIT-CRITERIA.md`** in the same PR.
- **`11-vscode-testing-linting-and-ci.md`** — CI quality checks remain required, but this rule does not mandate UI screenshot-gate additions for publishable UI work.

---

## 3. Revision

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-21 | Initial rule set for publishable UI band **IMP-140+**. |
| 0.2 | 2026-04-21 | Removed Stitch submodule dependency from release readiness; parity now anchored to vendored first-party contracts. |
| 0.3 | 2026-04-21 | Aligned with plan v0.4 decisions: permissive skew behavior, no debug/release UI fork, CI endpoint-config parity, and non-blocking share UX expectations. |
| 0.4 | 2026-04-21 | Cross-ref: retired KMP **photo gallery** sample removed from client; publishable UI work no longer coexists with that template path (see **`plans/2026-04-13-repo-state-gap-analysis.md` v1.7**). |
