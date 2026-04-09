# HTML vendoring vs shared UI (interface stack rules)

This document records the **technical implications** of “fully vendoring” the Stitch HTML screens into the NU:TONIC Kotlin Multiplatform repo, and binds the **allowed interface strategy** for this project.

## What `nutonic/kotlin-js-store` is

- The **`kotlin-js-store/`** directory (notably `yarn.lock`) is part of the **Kotlin/JS (and related browser targets) Gradle toolchain**: Yarn/npm resolution for **Webpack** and transitive JS dependencies used when compiling **Kotlin/JS** or **Kotlin/Wasm** browser binaries.
- It is **not** an application UI module, a design system, or a place to drop vendored screen HTML unless you deliberately extend the JS build with a **packaged web asset pipeline** (see below).
- **Rule:** Treat `kotlin-js-store` as **build infrastructure**. Do not assume “putting HTML there” integrates with Android, iOS, or Desktop Compose targets.

## What “vendoring the HTML screens” actually means

The Stitch artifacts are **single-file HTML** using:

- **Tailwind via CDN** (`cdn.tailwindcss.com`) and runtime config
- **Google Fonts** and **Material Symbols** from the network
- Inline **custom CSS** (scanlines, glitch, etc.)

**Fully vendoring** could mean:

| Level | What you copy | Implication |
|-------|----------------|------------|
| A. Raw copy | HTML as-is, still using CDN | **Unacceptable for production**: offline breaks, CSP/security, non-reproducible builds, flaky CI. |
| B. Static bundle | HTML + **built** Tailwind CSS + **self-hosted** fonts/icons under `resources/` | Feasible as **static web assets** only; still **not** Kotlin Multiplatform *shared* UI. |
| C. WebView shell | B embedded in **WebView** (Android/iOS) or similar desktop wrapper | **Hybrid app**; parity, accessibility, and map integration become **much harder** (see below). |
| D. Reference-only | No vendored runtime UI; **Compose Multiplatform** implements layout | Matches Kotlin’s **shared UI** model and this repo’s existing `shared` + `webApp` layout. |

## Kotlin Multiplatform documentation alignment

Official KMP direction for **one codebase, multiple targets**:

- **Shared logic + shared UI:** [Compose Multiplatform](https://kotlinlang.org/docs/multiplatform/compose-multiplatform.html) compiles to Android, iOS, Desktop, and (with platform maturity caveats) **Web**—UI is **not** the original HTML DOM tree; it is **Compose** rendered via Skia/DOM backends as appropriate.
- **Shared persistence:** Libraries such as **DataStore (KMP)** support **expect/actual** or factory patterns for preferences across platforms—relevant for settings/tokens, independent of whether the shell is WebView or Compose.
- **Standard library / serialization:** Cross-platform models (`kotlinx.serialization`, `kotlinx-datetime`, coroutines) should back **one** navigation and data layer regardless of UI technology.

**Conclusion:** Vendoring Stitch HTML as the **primary** UI for **all** targets **does not** align with the recommended “shared Compose UI” path; it pushes you toward **per-platform WebViews** or **web-only** delivery.

## Material 3 and Compose

- **Compose Multiplatform Material 3** is the idiomatic choice for **new** shared UI when targets support it (see [Compose Multiplatform Material3](https://kotlinlang.org/docs/api-references.html) / project dependencies).
- Stitch HTML is **Tailwind + custom tokens**, not M3. **Rule:** Map Stitch **layout and tokens** into **`NutonicTheme`** (colors, type, shapes); do not treat M3 defaults as the design spec unless tokens are explicitly mapped.

## If HTML is fully vendored (exception path — requires explicit product approval)

Only document this in `README` or ADR when product **opts in**. Then **all** of the following apply:

1. **Build pipeline**  
   - Remove runtime Tailwind CDN; add a **checked-in or CI-built** CSS bundle (PostCSS/Tailwind CLI or equivalent).  
   - **Vendor fonts** (license-compliant) under resources; no required calls to `fonts.googleapis.com` at runtime for core UI.

2. **Targets**  
   - Clarify: **Web-only** (static + small Kotlin/JS bridge) vs **WebView on every native target**. The latter is a **different product architecture** from Compose-parity NU:TONIC.

3. **Bridge contract**  
   - Define a **single JSON/message contract** between Kotlin and the page (navigation, auth state, leaderboard payload). **No** business rules duplicated inside `<script>` without tests.

4. **Maps**  
   - A map inside WebView (MapLibre/Leaflet) vs native map SDKs **will diverge** in gestures, performance, and licensing. **Rule:** One **map strategy** per target family, documented; avoid invisible mixing of WebView map + native Compose map on the same screen without explicit UX sign-off.

5. **Accessibility**  
   - Web content inside WebView must meet the same **high contrast / reduced motion** commitments as native; settings must **drive** CSS classes or media queries via the bridge.

6. **Security**  
   - No arbitrary `file://` loading of untrusted HTML; if using `evaluateJavascript`, sanitize inputs; align with Android WebView best practices and iOS WKWebView configuration.

## Default interface rules for this repository (binding)

Unless an ADR explicitly selects the HTML/WebView exception:

1. **Primary UI:** **Compose Multiplatform** in `shared` (`commonMain`), with **expect/actual** only for platform-specific surfaces (maps, camera, WebAuth, etc.).
2. **Stitch HTML:** **Design reference only**—structure, copy, spacing, token names—not a runtime dependency.
3. **Web target (`webApp`):** Same Compose tree as other targets where feasible; Kotlin/JS Webpack + `kotlin-js-store` support **that** build, not a parallel Tailwind app, unless the exception path is approved.
4. **No CDN-coupled UI** in production builds.
5. **Parity:** Android, iOS, Desktop, and Web must share **navigation and screen inventory** per `01-navigation-architecture.md` and `07-screens-checklist.md`; HTML vendoring as primary UI **breaks** this unless **every** target uses a WebView with proven feature parity (rarely justified).

## Summary assessment

| Approach | Parity | KMP doc fit | Maintenance |
|----------|--------|-------------|-------------|
| Compose shared UI (default) | Strong | Strong | One theme, one component set |
| Vendored HTML + WebView everywhere | Weak | Weak | Two stacks (DOM + native bridges) |
| Vendored HTML web-only + native Compose | Split | Mixed | Two UIs to keep in sync—**avoid** without dedicated team |

**Recommendation for NU:TONIC:** Keep **Compose Multiplatform** as the interface; use Stitch HTML to **extract tokens, copy, and layout metrics** only. If the team later chooses a **web-first** prototype, scope it explicitly as **non-parity** or plan a **rewrite** into Compose before calling the product multiplatform-complete.
