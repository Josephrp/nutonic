# NU:TONIC implementation rules

These documents define **design patterns and non-negotiable constraints** for implementing the multi-user NU:TONIC game in this repository. They tie together:

- `refs/DESIGN.md` — visual and interaction system
- `refs/stitch/nu_tonic_interface_design_specification.html` — product UX and flows
- `refs/stitch/*/code.html` and `screen.png` — per-screen layout and copy targets
- Kotlin Multiplatform + Compose Multiplatform app under `nutonic/`

**How to use:** Read `00-product-intent.md` first, then `01-navigation-architecture.md` (canonical IA). Implement features only against the checklist in `07-screens-checklist.md` unless product explicitly changes scope.

**VLM + progressive zoom + TerraMesh reference:** For the Street View → VLM description → map zoom-per-turn → multiplayer → AI marker flow, and how `refs/terramind-geogen-main` relates (TerraMesh, haversine, heatmaps), read **`10-terramesh-vlm-progressive-zoom-game-engine.md`**.

**Python reference server (FastAPI + optional Gradio, TerraMind/TerraTorch, Hub uploads):** Read **`12-python-gradio-terramind-server.md`** and **`plans/2026-04-07-gradio-terramind-backend.md`**.

**Client cache vs Hub (no `hf` on device, Jobs → Dataset → server → client):** Read **`13-client-cache-and-data-plane.md`** and the data-plane sections in **`plans/2026-04-07-complete-implementation-architecture.md`**.

**HTML / Web stack:** If you consider embedding or vendoring Stitch HTML, read `09-html-vendoring-and-interface-stack.md` before changing build layout or `kotlin-js-store`.

**Order of authority when sources conflict:** Product intent in `01` and `00` overrides individual mockups. Visual tokens default to `refs/DESIGN.md`; where stitch HTML uses extra fonts (e.g. Orbitron), treat stitch as layout reference and align tokens to DESIGN unless design sign-off extends the palette.

**Tooling, tests, linters, CI:** For VS Code + Gradle (`nutonic/`), ktlint/detekt, GitHub Actions artifacts (Android, desktop `.deb`, JS/Wasm bundles, iOS Simulator framework), **team JDK / no hardcoded paths**, and optional **PM2** local Gradle threads with output under gitignored **`logs/`**, read **`11-vscode-testing-linting-and-ci.md`** and **`docs/PM2_LOCAL_VERIFICATION.md`** (see **`nutonic/gradle.properties.PERSONAL.example`**, repo-root **`ecosystem.config.cjs`**).
