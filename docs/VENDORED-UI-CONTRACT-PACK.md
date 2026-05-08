# NU:TONIC — Vendored UI contract pack

**Purpose:** First-party, in-repo UI contract baseline for publishable builds when `refs/stitch/` is absent or intentionally gitignored.  
**Primary consumers:** `plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md` (**IMP-140**), `docs/PUBLISHABLE-UI-EXIT-CRITERIA.md`, `rules/15-publishable-ui-and-release-readiness.md`.  
**Scope:** IA, control inventory, copy constraints, and visual-role contracts (not pixel-perfect mockups).

---

## 1. Contract precedence

When sources disagree, apply this order:

1. `rules/00-product-intent.md`
2. `rules/01-navigation-architecture.md`
3. `rules/07-screens-checklist.md`
4. `docs/DESIGN.md` + `rules/02-design-system.md`
5. `docs/GAME-ENGINE.md`, `docs/INTEL-TAB-SPEC.md`, `docs/CLIENT-SETTINGS-SPEC.md`
6. Optional local references (`refs/stitch/*`) — **never required for release gating**

---

## 2. Shell and IA contracts

| Area | Contract |
|------|----------|
| Tabs | Exactly **SCAN / INTEL / RANK / SETUP / PRO** (route IDs canonical in `rules/01`). |
| Default shell destination | **SCAN** after splash/role/auth flow. |
| SCAN convergence | `rules/07` #4b + #4c + leaderboard slice + gameplay entry are on the SCAN route, not placeholder-only detours. |
| Bottom bar indicator | Active indicator appears **above** icon/label cluster (`docs/DESIGN.md` §5). |

---

## 3. Screen-level must-have controls

| Screen | Mandatory controls/content |
|--------|----------------------------|
| Splash | Initialize CTA, brand + status line, header music toggle. |
| Authentication | Optional/skippable auth path, header music toggle. |
| Role selection | Three explicit choices: Human, Astronaut, Alien; continue CTA. |
| SCAN hub | Missions list, map list/grid, per-map leaderboard entry (<=1 action), play CTA(s), map context continuity. |
| World map gameplay | Basemap mode toggle, reference still, guess flow (single submit), collapsible assists, narrative surface, header music toggle. |
| Success overlay | Score/distance summary + next action, route-correct BGM. |
| Final results | Tactical breakdown, AI-vs-truth row, jump to RANK with `map_id`. |
| INTEL | XP/progression + session card + daily protocol section. |
| RANK | Community/ranked slices with map context support. |
| SETUP | Grouped settings from `docs/CLIENT-SETTINGS-SPEC.md` §6, including music master. |
| PRO | Functional VLM strip per `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` (not title-only placeholder). |

---

## 4. Copy and debug constraints

- Release builds must not expose implementation metadata (`IMP-*`, `rules/*`, `docs/*`, internal phase enums).
- Timer copy must indicate cosmetic semantics when shown (e.g. “Sector time (not scored)”).
- Offline/manifest copy follows the matrix in `plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md` §2.4.

---

## 5. Visual-role contracts

| Role | Contract |
|------|----------|
| Color usage | Semantic theme tokens only; no raw ad-hoc hex in feature screens. |
| Primary CTA | 12–16dp corner radius, cyan-tech emphasis, rare glow discipline. |
| Glass surfaces | Blur where available; solid+gradient fallback where blur is expensive/unsupported. |
| Typography roles | Display/headers distinct from body; tactical numeric role limited to HUD-like fields. |

---

## 6. Verification checklist reference

Use this contract pack with:

- `docs/PUBLISHABLE-UI-EXIT-CRITERIA.md`
- `rules/15-publishable-ui-and-release-readiness.md`
- `plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md`

---

## 7. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-21 | Initial vendored contract pack for IMP-140. |

