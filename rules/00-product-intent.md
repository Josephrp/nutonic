# Product intent

## What NU:TONIC is

- A **multi-user geo-guessing game**: players infer real-world locations from fragmented cues (memory / satellite / distorted map data).
- **Roles** matter for fiction and mechanics: Human, Astronaut, Alien (and any server-defined variants). UI must present roles consistently; **game logic that depends on embeddings or AI style runs on the server**, not duplicated ad hoc per platform.
- **Game-first UX**: low cognitive load, **few taps to act**, clear feedback loops. Not a utility app.

## Success criteria for any implementation

1. **Parity**: The same **routes**, **game loop**, and **data shown** on Android, iOS, Desktop, and (if in scope) Web—differences are only where platform APIs require it (e.g. map provider, secure storage).
2. **Server authority**: Scores, leaderboard placement, match outcome, and embedding-driven behavior are **validated or computed on the reference server** unless explicitly offline-only mock mode.
3. **Design fidelity**: Screens match the **structure and hierarchy** of `refs/stitch` mocks and the **tokens and rules** in `refs/DESIGN.md` (glass surfaces, glow discipline, typography roles).

## Out of scope for “pixel-perfect HTML port”

- Do not ship the Tailwind/HTML as the app. **Compose** (and native map/embed where needed) is the implementation; HTML is **reference only**.

For a full technical breakdown of vendoring HTML, WebView hybrids, and how that relates to `kotlin-js-store` / Kotlin/JS builds, see **`09-html-vendoring-and-interface-stack.md`**. Deviations require an explicit product/ADR decision.

## Reference assets map

| Area | Primary refs |
|------|----------------|
| Global UX copy & footguns | `refs/stitch/nu_tonic_interface_design_specification.html` |
| Tokens & components | `refs/DESIGN.md` |
| Per screen | `refs/stitch/<screen>/code.html` + `screen.png` |
