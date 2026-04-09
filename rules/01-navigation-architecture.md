# Navigation architecture (canonical)

## Rule: single source of truth for routes

Define **one** navigation graph in shared code (e.g. sealed classes or typed routes in `commonMain`). **Do not** fork different tab sets per platform.

## Canonical primary navigation (product spec)

The **interface specification** defines the persistent bottom bar as:

1. **Home** — dashboard, progress, daily protocols, primary “Play” entry.
2. **Map** — world / sector context as needed (may combine with Play flow per product).
3. **Play** — central action; **visually elevated** (circular CTA, neon bloom per DESIGN).
4. **Leaderboard** — global ranks, filters by role where UI requires it.
5. **Settings** — protocol configuration, audio, accessibility, account.

**Active tab indicator:** A **short line above the icon** (not below), per `refs/DESIGN.md`.

## Stitch mock inconsistency rule

Some stitch files use **SCAN / INTEL / RANK / SQUAD** or other labels. Treat those as **alternate visual explorations** unless product explicitly adopts them.

- When implementing: **map mock labels to canonical routes** (e.g. “RANK” → Leaderboard, “SQUAD” → Settings or social surface as product defines).
- Document any intentional rename in code comments **once** next to the route enum, not scattered across UI strings.

## Depth limit

**Maximum two levels** of navigation beyond a root tab for core flows (per spec footgun). Prefer overlays/sheets for mode pickers (solo / multi / AI) instead of deep stacks.

## Required flows (order)

1. Splash → optional **Initialize** CTA  
2. Authentication (sign in / register paths)  
3. Role selection → confirm  
4. Main shell (tabs) → Dashboard default on Home  
5. Play → map gameplay → success overlay → full results (leaderboard section hydrates from server)  
6. Settings persist across sessions  

Deep links (if added) must resolve into this graph without a third parallel navigation system.
