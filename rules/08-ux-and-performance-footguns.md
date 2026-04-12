# UX and performance footguns (mandatory)

Derived from `refs/stitch/nu_tonic_interface_design_specification.html`, **`docs/DESIGN.md`**, and **`rules/02-design-system.md`**. **Violations require explicit product waiver.**

1. **Map touch targets** — Guessing interactions must use **generous invisible hit slop**; small pins are visual only.
2. **Cognitive load** — Readability over ornament; sci-fi effects never obscure primary numbers (score, timer, distance).
3. **Leaderboard freshness** — Show **last updated** (or version) and offer **pull-to-refresh** / **Update**; **auto-refetch is off by default** (`rules/05-networking-leaderboard.md`, `docs/SOCIAL-AND-COMPETITION.md`).
4. **Feedback timing** — Interactions feel immediate (~100ms); use local optimistic UI where network lags.
5. **Role clarity** — Icons + short descriptions everywhere **Human / Astronaut / Alien** appear; same icons across **all platforms** and on **local** leaderboard rows (and in **optional** community payloads if the server echoes role—`rules/05-networking-leaderboard.md`).
6. **Glow discipline** — Rare, high-value actions only (DESIGN); avoid neon fatigue.
7. **Pure black** — Use designated void surfaces (`surface_container_lowest`), not `#000000`, unless a11y high-contrast mode dictates otherwise.
8. **Motion** — Honor **reduced motion** system setting and in-app toggle; particles and parallax off when requested.
9. **Narrative readability** — Text boxes use **comfortable line length**, sufficient contrast, and **no tiny monospace** for long mission prose; optional typewriter effects **off** under reduced motion.
10. **Guess modal** — **Expand/collapse** preserves map discoverability; **focus order** and **screen reader** labels for search field, results list, and submit; **do not** trap keyboard users inside the modal without a clear dismiss.
11. **Music toggle discoverability** — The **header music on/off** control must appear on **every** shipped screen ([`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md)); toggling must **feel instant** (~100ms fade) and stay **in sync** with SETUP Audio ([`docs/CLIENT-SETTINGS-SPEC.md`](../docs/CLIENT-SETTINGS-SPEC.md) §6.7).
12. **Audio / Web autoplay** — On Web targets, respect browser **autoplay** policies: prime audio after explicit user gesture if needed; do not loop error silence — document or degrade gracefully ([`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md) §6).
