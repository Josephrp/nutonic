# Contributing to NU:TONIC

Thank you for helping build NU:TONIC. This guide summarizes what maintainers expect; **authoritative product and engineering constraints** live under [`rules/`](rules/README.md) and [`docs/`](docs/).

---

## 1. Read the rules first

**Start here:** [`rules/README.md`](rules/README.md) — reading order, how `rules/` ties to `docs/`, `refs/stitch/`, and the Kotlin app under `nutonic/`.

**Before UI or gameplay work:**

| Order | Document | Why |
|------|-----------|-----|
| 1 | [`rules/00-product-intent.md`](rules/00-product-intent.md) | Solo-first async play, client vs server authority (non-ranked vs ranked), PRO vs SCAN, marketplace posture |
| 2 | [`rules/01-navigation-architecture.md`](rules/01-navigation-architecture.md) | Canonical tabs (**SCAN / INTEL / RANK / SETUP / PRO**), route IDs vs labels, depth limits, auth/session expectations |
| 3 | [`rules/07-screens-checklist.md`](rules/07-screens-checklist.md) | Ship list for screens, BGM + header music toggle, stitch folder pairing |

**When sources disagree:** [`rules/README.md`](rules/README.md) § “Order of authority” — `00` / `01` and **`docs/DESIGN.md`** override older stitch naming; **`rules/02-design-system.md`** is how design lands in Compose (tokens, fonts, glass).

**Topic pointers:** structure [`03`](rules/03-kotlin-multiplatform-structure.md), maps/gameplay [`04`](rules/04-maps-and-gameplay.md), APIs and leaderboards [`05`](rules/05-networking-leaderboard.md), ML/VLM [`06`](rules/06-server-vlm-tim-and-on-device-ml.md), UX footguns [`08`](rules/08-ux-and-performance-footguns.md), HTML/WebView [`09`](rules/09-html-vendoring-and-interface-stack.md), TerraMesh [`10`](rules/10-terramesh-vlm-progressive-zoom-game-engine.md), tooling/CI/PM2 [`11`](rules/11-vscode-testing-linting-and-ci.md), Python/Gradio [`12`](rules/12-python-gradio-terramind-server.md), cache/data plane [`13`](rules/13-client-cache-and-data-plane.md).

---

## 2. Repository layout (short)

- **`nutonic/`** — Gradle root for the **Kotlin Multiplatform + Compose** client (open this folder for VS Code / Android Studio when working on the app).
- **`rules/`** — Implementation constraints (treat as non-negotiable unless product explicitly changes scope).
- **`docs/`** — Long-form specs (game engine, ranked mode, design, APIs, etc.).
- **`inference/`**, **`data/scripts/`** — Inference services and hydration scripts per [`rules/README.md`](rules/README.md) and [`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`](docs/SERVER-AND-INFERENCE-ARCHITECTURE.md).

---

## 3. Local environment

- **JDK:** 17+ for the project; **CI uses Temurin 21**. Set **`JAVA_HOME`** (or user `~/.gradle/gradle.properties` with `org.gradle.java.home`) — **do not** commit machine-specific JDK paths. Details: [`rules/11-vscode-testing-linting-and-ci.md`](rules/11-vscode-testing-linting-and-ci.md) §7 and **`nutonic/gradle.properties.PERSONAL.example`**.
- **Android:** `nutonic/local.properties` is **gitignored** — create it locally with `sdk.dir=...` (and keys as documented); CI uses a stub `MAPS_API_KEY` for builds.
- **Node (repo root):** `npm install` when `package.json` / lockfile changes — used for **PM2** scripts that run Gradle with log capture.

---

## 4. Quality, tests, and formatting

From **`nutonic/`** (see [`rules/11`](rules/11-vscode-testing-linting-and-ci.md) §3–§4):

```bash
./gradlew test
./gradlew quality          # ktlintCheck + detekt
./gradlew formatKotlin     # if ktlint reports style-only issues
```

**KMP rule of thumb:** game rules, non-ranked scoring, and shared UI belong in **`shared/src/commonMain`**; platform folders stay thin ([`rules/03`](rules/03-kotlin-multiplatform-structure.md)).

**Kotlin/JS + Wasm:** if you change JS/Wasm dependencies, follow **`rules/11`** §7 on **`nutonic/kotlin-js-store/`** and lockfile hygiene.

---

## 5. Mandatory checks before merging `nutonic/**` changes

Per [`rules/11`](rules/11-vscode-testing-linting-and-ci.md) **§9** and the broader PM2-first testing policy in [`rules/14`](rules/14-testing-validation-pm2-and-documentation.md), PRs that touch the KMP client must include **local** verification via PM2 so stdout/stderr land under **`logs/`** (gitignored). **Always read logs and fix failures before treating work as complete.** At minimum:

1. From repo root: `npm install` if needed.
2. Run **`nutonic-ci-local`** (quality + test in one Gradle invocation), wait until it stops, and confirm **`BUILD SUCCESSFUL`** in **`logs/nutonic-ci-local.out.log`** (and scan **`.err.log`**).
3. When §9.2 step **B** applies (changes to `webApp`, `androidApp`, `desktopApp`, `shared`, `kotlin-js-store`, or cross-cutting Gradle that affects those), also run **`nutonic-build-verify`** and assess its logs.

State in the PR that §9.2 was run (and which logs you checked). **Do not commit `logs/`.** If PM2/Node is impossible, use the **documented exception** in §9.4: same Gradle commands, capture output locally, paste evidence in the PR.

Full command reference: [`docs/PM2_LOCAL_VERIFICATION.md`](docs/PM2_LOCAL_VERIFICATION.md).

---

## 6. CI and security automation

- **Client CI:** [`.github/workflows/nutonic-ci.yml`](.github/workflows/nutonic-ci.yml) — quality, tests, Android APK, desktop `.deb`, web bundles, iOS Simulator framework (path-filtered to `nutonic/**`, `rules/**`, and that workflow).
- **CodeQL + secret scanning:** [`.github/workflows/security-codeql-and-secrets.yml`](.github/workflows/security-codeql-and-secrets.yml).

Green CI does not replace §9.2 local evidence for `nutonic/**` work.

---

## 7. Git hooks (optional but recommended)

- **[`.pre-commit-config.yaml`](.pre-commit-config.yaml)** — Gitleaks on commit. Install: `pip install pre-commit` then `pre-commit install` from the repo root.
- Never commit secrets, API keys, or personal `local.properties`. **`.env`** and similar belong in **`.gitignore`** (see existing patterns).

---

## 8. Pull requests

- **Scope:** Prefer focused PRs with a clear description of behavior change vs spec alignment.
- **Linked intent:** If the change touches ranked play, leaderboards, PRO, or server contracts, cite the relevant **`docs/`** or **`rules/`** section so reviewers can verify parity.
- **Design:** Follow **`docs/DESIGN.md`** + **`rules/02-design-system.md`** (bundled fonts, semantic colors, header music where the screen checklist requires it).

Questions about intent are best resolved against **`rules/00-product-intent.md`** and **`rules/README.md`** before large refactors.
