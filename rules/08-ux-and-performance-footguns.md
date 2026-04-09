# UX and performance footguns (mandatory)

Derived from `refs/stitch/nu_tonic_interface_design_specification.html` and `refs/DESIGN.md`. **Violations require explicit product waiver.**

1. **Map touch targets** — Guessing interactions must use **generous invisible hit slop**; small pins are visual only.
2. **Cognitive load** — Readability over ornament; sci-fi effects never obscure primary numbers (score, timer, distance).
3. **Multiplayer sync** — When applicable, show opponent/ghost state or explicit “waiting / reconnecting”; no silent desync.
4. **Feedback timing** — Interactions feel immediate (~100ms); use local optimistic UI where network lags.
5. **Role clarity** — Icons + short descriptions everywhere roles appear; same icons server and client.
6. **Glow discipline** — Rare, high-value actions only (DESIGN); avoid neon fatigue.
7. **Pure black** — Use designated void surfaces (`surface_container_lowest`), not `#000000`, unless a11y high-contrast mode dictates otherwise.
8. **Motion** — Honor **reduced motion** system setting and in-app toggle; particles and parallax off when requested.
