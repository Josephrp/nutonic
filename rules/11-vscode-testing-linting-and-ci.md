# VS Code, Kotlin tests, linters, and CI (nutonic monorepo)

This document is the **authoritative rule** for how we develop the Kotlin Multiplatform client under `nutonic/`, how we assess common VS Code + Gradle advice, how CI produces **multiplatform client artifacts** aligned with `03-kotlin-multiplatform-structure.md`, and how **mandatory local verification** uses **PM2** and **`logs/`** before client changes ship.

---

## 1. Assessment of common VS Code + Kotlin guidance

### What is accurate and worth following

- **Open the correct Gradle root:** VS Code Java/Gradle tooling and test discovery work best when the folder you open is the **Gradle project root** (`nutonic/`), not the repository root (`nutonic` parent), unless you use a **multi-root workspace** that includes `nutonic/` as a folder with its own Gradle import.
- **JDK requirement:** Gradle 8.x and Android Gradle Plugin 8.x expect a **modern JDK** (this repo uses **Java 17** toolchain in modules; **JDK 21** is fine for the daemon and is what CI uses). A JRE-only install or very old JDK (e.g. 8) will break Gradle and the Kotlin compiler.
- **Run Gradle once:** Running `./gradlew build` or `./gradlew test` after clone helps the Java/Gradle extensions index the model; this remains true.
- **Monorepo hygiene:** Shared `config/detekt/detekt.yml`, root `.editorconfig`, and **one** set of lint tasks across subprojects are standard practice. This repo uses `nutonic/gradle/libs.versions.toml` as the Gradle **version catalog** (auto-loaded; do not register a second `libs` catalog in `settings.gradle.kts`).
- **IntelliJ vs VS Code:** For heavy Android + Compose Multiplatform work, **IntelliJ IDEA / Android Studio** remain more complete; VS Code is viable for editing, navigation, and terminal-driven Gradle.

### Corrections and caveats

- **“Kotlin by JetBrains” in VS Code:** The ecosystem is moving toward JetBrains’ Kotlin support; marketplace names change. Prefer **whichever extension is currently maintained** and pair it with **Extension Pack for Java** (Microsoft) for Gradle/test integration.
- **`useJUnitPlatform()`:** That applies to **JVM** test tasks. **Kotlin Multiplatform** uses `kotlin("test")` in `commonTest` and platform-specific runners; do not assume a single `tasks.test { useJUnitPlatform() }` in the root covers all KMP targets.
- **ktlint vs detekt:** **ktlint** (Gradle plugin) owns **formatting and style** (`.editorconfig`). **detekt** owns **static analysis** only — we do **not** use `detekt-formatting`, so the two tools do not duplicate the same style rules. Tune `config/detekt/detekt.yml` for analysis noise; use `./gradlew formatKotlin` for ktlint autofixes.
- **Plugin versions in the user-provided guide:** Versions like `ktlint` / `detekt` age quickly. **Source of truth** is `nutonic/settings.gradle.kts` (`pluginManagement`) and `nutonic/gradle/libs.versions.toml`.
- **Test Explorer:** Discovery for **KMP** is not always as smooth as for plain JVM; rely on **`./gradlew test`** and module-scoped tasks when the UI misses tests.
- **`dependencyResolutionManagement` + `libs.versions.toml`:** Gradle auto-imports `gradle/libs.versions.toml` as the `libs` catalog. A **second** `versionCatalogs { create("libs") { from(...) } }` causes **“from method called more than once”** — avoid duplicating catalog registration.

---

## 2. VS Code setup (recommended)

### Extensions (workspace recommendations)

The repository includes `.vscode/extensions.json` with suggested extensions:

- Kotlin language support (fwcd or JetBrains channel, per current marketplace).
- **Extension Pack for Java** (Microsoft).
- **Gradle for Java** (Microsoft).
- Optional: **Error Lens**, **Test Explorer UI** (if still useful alongside built-in Testing).

### Settings

- **Committed `.vscode/settings.json` does not hardcode JDK paths** so macOS/Linux/Windows teammates are not forced to use one install location.
- Point the Java language server at a **JDK 17+** using one of:
  - **`JAVA_HOME`** in the environment (VS Code / Cursor usually discovers it), or
  - **User** `settings.json`: `java.jdt.ls.java.home` and `java.import.gradle.java.home` set to your JDK path, or
  - **Command Palette** → **Java: Configure Java Runtime**.
- If the Kotlin LS exposes **`kotlin.languageServer.java.home`**, align it with the same JDK.
- Open **`nutonic/`** as the Gradle root (or add it in a `.code-workspace`).

### Tasks

`.vscode/tasks.json` defines shortcuts for:

- `./gradlew quality`
- `./gradlew test`
- `./gradlew formatKotlin`

---

## 3. Gradle: testing (nutonic)

### Rules

- **Shared logic tests** belong in **`shared/src/commonTest`** with `kotlin("test")` (see `KmpSanityTest`).
- **Desktop Compose UI tests** stay in **`shared/src/desktopTest`** (existing pattern with `compose.desktop.uiTestJUnit4`).
- **Platform-only** tests (Android instrumented, iOS XCTest bridges) are added only when CI and product require them; they are **not** required for every feature.
- **`./gradlew test`** is the default **aggregate** verification command in CI for JVM-backed test tasks. For **`:shared`**, the Android `test` task **finalizes** **`desktopTest`**, so Compose UI tests under `shared/src/desktopTest` (non-ranked gameplay persistence, etc.) run in the same CI invocation as `./gradlew test`.

### Commands

```bash
cd nutonic
./gradlew test
./gradlew :shared:desktopTest   # optional: run desktop UI tests alone (also runs after :shared:test)
```

---

## 4. Gradle: linting and formatting (nutonic)

### Tools

| Tool | Role |
|------|------|
| **ktlint** (via `org.jlleitschuh.gradle.ktlint`) | Primary **style** check + `ktlintFormat`. |
| **detekt** (via `io.gitlab.arturbosch.detekt`) | Static analysis (no `detekt-formatting` plugin). |
| **`.editorconfig`** | Shared indentation / Kotlin editor defaults at `nutonic/.editorconfig`. |
| **`config/detekt/detekt.yml`** | Shared Detekt config. |

### Commands

```bash
cd nutonic
./gradlew quality        # ktlintCheck + detekt on all subprojects
./gradlew formatKotlin   # ktlintFormat on all subprojects
./gradlew ktlintCheck detekt   # equivalent granular invocations per module
```

### Ktlint vs Compose Multiplatform templates

`nutonic/.editorconfig` disables a few **standard** rules that fight common KMP/Compose patterns (wildcard imports, `platform.*.kt` filenames, `@Composable` entry points named in PascalCase). Private `const val` values should still follow **SCREAMING_SNAKE_CASE** (`property-naming`).

### Baseline (when introducing detekt on a large legacy tree)

If `detekt` reports a large backlog, generate a baseline **once**, commit it, then ratchet down:

```bash
cd nutonic
./gradlew detektBaseline   # per module, or use root if configured
```

Place the generated `baseline.xml` at `nutonic/config/detekt/baseline.xml`. The root build applies it **only if the file exists**.

---

## 5. CI: GitHub Actions (multiplatform clients)

Workflow: **`.github/workflows/nutonic-ci.yml`**

- **Triggers:** **`pull_request`** when the **base branch is `main` or `dev`** (and paths match the filter below), plus **`workflow_dispatch`** for ad-hoc full CI from the Actions tab.
- **Path filters:** PRs / dispatches only run client CI when changes touch listed paths (e.g. `nutonic/**`, `server/**`, `docs/openapi.yaml`, workflows under `.github/workflows/`, `rules/**`) — see the workflow file for the exact list.

| Job | Runner | Purpose |
|-----|--------|---------|
| **quality-and-unit-tests** | `ubuntu-latest` | `./gradlew --continue quality test` (one invocation; `--continue` so lint and tests both run even if one fails); Android SDK via **setup-android before** `local.properties`; **Checks** from JUnit XML; artifacts for tests + detekt. |
| **android-debug-apk** | `ubuntu-latest` | `:androidApp:assembleDebug` → APK artifact; if repository variable **`NUTONIC_DEMO_SERVER_ORIGIN`** is set, passes **`-PnutonicServerOrigin`** so the APK targets the deployed demo (otherwise Gradle default). |
| **desktop-deb** | `ubuntu-latest` | `:desktopApp:packageReleaseDeb` → `.deb` artifact. |
| **desktop-msi** | `windows-latest` | After `:downloadWix` / `:unzipWix`, CI **unsets** inherited `WIX_PATH`, then sets `WIX_PATH` to the folder containing `candle.exe` under `nutonic/build/wix311` (Compose’s WiX 3.11). Packaging uses **short** `TEMP`/`TMP` on `D:/jpktmp` to reduce `jpackage` long-path failures. **MSI metadata** stays WiX-safe (see `desktopApp/build.gradle.kts`: no `:` in Start Menu group, ASCII description). |
| **desktop-dmg** | `macos-latest` | `:desktopApp:packageReleaseDmg` → `.dmg` artifact (unsigned; notarization still manual). |
| **web-bundles** | `ubuntu-latest` | `:webApp:jsBrowserProductionWebpack` → upload **`webApp/build/dist/js/productionExecutable/`** tree. |
| **ios-framework** | `macos-latest` | `:shared:linkDebugFrameworkIosSimulatorArm64` → zip **`shared.framework`** from the resolved `…/iosSimulatorArm64/…Framework/` path (fallback `find` if Gradle layout changes). Kotlin/Native: `Dispatchers.IO` is not public on iOS — use `Dispatchers.Default` in `iosMain` `actual val ioDispatcher` (see `shared/src/iosMain/.../platform.ios.kt`). |

### Release installers + GitHub Release (`.github/workflows/nutonic-release.yml`)

- **Triggers:** **`push`** to **`main`** (path-filtered: `nutonic/**`, release workflow file, `docs/openapi.yaml`, `rules/**`) builds **`.deb` / `.msi` / `.dmg`** and uploads **workflow artifacts** (no GitHub Release on push). **`workflow_dispatch`** runs the same builds, then **publishes** assets to a **GitHub Release** for the **tag** you enter, using **`softprops/action-gh-release@v2.6.2`**.
- **Optional mobile (same workflow, `workflow_dispatch` only):** boolean inputs build a **signed Android release APK** (keystore via secrets + Gradle injected signing), an **iOS archive → IPA** (distribution cert + provisioning profile + shared **`.xcscheme`**), optional **TestFlight upload** via **`apple-actions/upload-testflight-build@v4`**, and optional **attach** of `.apk` / `.ipa` to the same GitHub Release. See the workflow file header comments for the exact secret names. If **`android_nutonic_server_origin`** is left empty, **repository variable** **`NUTONIC_DEMO_SERVER_ORIGIN`** is used when set (same origin used by the tester workflow below).

### Android demo APK for testers (`.github/workflows/nutonic-android-tester-build.yml`)

- **`workflow_dispatch` only.** Builds a **signed** release APK pointed at **`NUTONIC_DEMO_SERVER_ORIGIN`** (or the per-run **origin** input), runs **`GET {origin}/api/v1/health`** before Gradle (optional skip), and uploads artifact **`nutonic-android-demo`** containing **`nutonic-demo.apk`** and **`README-TESTERS.txt`**. Use this for a **stable, documented** handoff to testers; PR CI’s debug APK can also pick up the same variable (see `nutonic-ci` **android-debug-apk** job).
- **Repository settings:** publishing requires **Actions → General → Workflow permissions → Read and write** for the default `GITHUB_TOKEN` (the publish job sets **`contents: write`**; push-only runs use **`contents: read`**).

### CI conventions

- **Themed typography (ship contract):** Release builds must use **bundled** **Space Grotesk**, **Inter**, and **Orbitron** under the KMP resource tree—**no** `fonts.googleapis.com` or other runtime font CDNs (`docs/DESIGN.md` §3, `docs/NU_TONIC_ARTIFACT_REFERENCE.md` §10). APK/DEB/web jobs implicitly verify that theme code resolves `Font` resources; add a dedicated Gradle “font manifest” check later if product wants an explicit gate.
- **`--no-configuration-cache`** is used in CI to avoid known edge cases with some Kotlin/JS and third-party tasks; local builds may still use configuration cache per `gradle.properties`.
- **`android-actions/setup-android`** runs **before** appending `sdk.dir=${ANDROID_SDK_ROOT}` to `local.properties`; otherwise `sdk.dir` can be empty on a clean runner.
- **`MAPS_API_KEY=CI_STUB`** mirrors `default.local.properties`; real keys stay out of CI.
- **Path filters** limit runs to `nutonic/**`, `rules/**`, and this workflow file; unrelated repo-root edits do not trigger client builds.
- **Failures:** Download the **detekt-reports** artifact for HTML/XML from subprojects; **junit-xml** / **test-reports-html** are uploaded on every run for debugging.

### Not in CI (by default)

- **Store-grade signing:** Play/App Store **AAB/APK signing**, Windows **Authenticode** on MSI, or **Apple notarization** for macOS (PR CI still produces **unsigned** `.msi` / `.dmg` for smoke verification).
- **App Store / Play** upload.
- **iOS Xcode archive** for device; only **Simulator** framework linkage is automated here.

Extend the workflow when product requires store-ready artifacts.

---

## 6. Checklist (developer)

1. Install **JDK 17+** (CI uses **21** on Ubuntu). Ensure Gradle can see it (see **section 7 — Team JDK**).
2. Open **`nutonic/`** in VS Code (or multi-root including it).
3. Install recommended extensions; reload window.
4. At **repository root**: **`npm install`** (PM2 + scripts) when `package-lock.json` changes or on first clone.
5. **Mandatory — PM2 local verification** for any PR that touches **`nutonic/**`** (see **§9**): run **`nutonic-ci-local`**, wait for completion, **assess** `logs/nutonic-ci-local.out.log` and `logs/nutonic-ci-local.err.log` (**`BUILD SUCCESSFUL`** required). For PRs that change **`webApp`**, **`androidApp`**, **`desktopApp`**, **`shared`** build logic, or **`nutonic/kotlin-js-store/`**, also run **`nutonic-build-verify`** and assess its logs the same way.
6. Run **`./gradlew test`** and **`./gradlew quality`** from **`nutonic/`** when iterating (or rely on §9 PM2 equivalents); keep in sync with what CI runs.
7. Before pushing, run **`./gradlew formatKotlin`** if ktlint fails on style-only issues.

---

## 7. Team JDK and sharing the repo (no hardcoded paths)

### Why we avoid machine paths in Git

- **Windows vs macOS vs Linux** use different install locations (`Program Files`, `/Library/Java`, `/usr/lib/jvm`, SDKMAN, etc.).
- **Teammates upgrade JDKs**; a hardcoded `org.gradle.java.home` in committed **`gradle.properties`** or **`.vscode/settings.json`** breaks clones or forces everyone to match one path.
- **CI** already pins the JDK via **`actions/setup-java`**; local dev should mirror “17+” without encoding your laptop’s folder.

### What Gradle uses (order of precedence, simplified)

Gradle picks the JVM for the **daemon** from, in practice:

1. **`org.gradle.java.home`** in **project** `nutonic/gradle.properties` (committed — **keep JDK paths out**).
2. **`org.gradle.java.home`** in **user** `gradle.properties`: **`%USERPROFILE%\.gradle\gradle.properties`** (Windows) or **`~/.gradle/gradle.properties`** (macOS/Linux).
3. **`JAVA_HOME`** environment variable.
4. **`java`** on **`PATH`**.

So the portable contract for the team is: **set `JAVA_HOME` to a JDK 17+**, or set **`org.gradle.java.home` only in `~/.gradle/gradle.properties`**.

### JDK 25+ vs Gradle’s embedded Kotlin (daemon)

If the daemon runs on **JDK 25** (or another version not yet handled by the Kotlin compiler bundled with **Gradle’s Kotlin DSL**), configuration can fail early with **`IllegalArgumentException: 25.0.2`** (or similar) inside **`JavaVersion.parse`**. Prefer a **JDK 17–23** (or the **JetBrains Runtime** that ships with **Android Studio**, typically **21**) for **`org.gradle.java.home`** / **`JAVA_HOME`**.

### Kotlin/JS: `kotlin-js-store`

- A failed **`kotlinStoreYarnLock`** task usually means the resolved graph no longer matches the committed lockfile. Run **`./gradlew kotlinUpgradeYarnLock`** (or a full **`jsBrowserProductionWebpack`** with a clean npm install) and **commit** the resulting changes under **`nutonic/kotlin-js-store/`** (including **`yarn.lock`**) so CI and other clones stay reproducible.

### Documented example (copy-paste)

See **`nutonic/gradle.properties.PERSONAL.example`**: it explains putting **`org.gradle.java.home=...`** in the **user** Gradle properties file when you cannot fix global `PATH` (e.g. Oracle Java 8 still wins on Windows).

### VS Code / Cursor

- Rely on **`JAVA_HOME`** or **Java: Configure Java Runtime** per developer.
- Optional **user** settings (not committed): e.g. `java.jdt.ls.java.home` pointing at your JDK, or `terminal.integrated.env.windows` / `.linux` / `.osx` to prepend **`${env:JAVA_HOME}/bin`** to **`PATH`** only if everyone on the team understands **`JAVA_HOME` must be set**.

### Environment variables (summary)

| Variable | Purpose |
|----------|---------|
| **`JAVA_HOME`** | Primary portable knob; Gradle and most Java tools respect it. |
| **`PATH`** | Must include **`$JAVA_HOME/bin`** (or equivalent) if you do not use a global JDK installer that already did this. |
| **`ORG_GRADLE_PROJECT_*`** | Rare; Gradle project properties via env — optional for automation. |

### Android `local.properties`

**`nutonic/local.properties`** remains **gitignored** (SDK path, secrets). It is **not** the standard place for **`org.gradle.java.home`** unless you add custom wiring; prefer **`JAVA_HOME`** or **`~/.gradle/gradle.properties`**.

---

## 8. Build verification (local)

Typical one-liner after clone (from **`nutonic/`**):

```bash
./gradlew --no-configuration-cache test :androidApp:assembleDebug :desktopApp:compileKotlinJvm :webApp:jsBrowserProductionWebpack
```

If **`quality`** fails on **ktlint** for the legacy template tree, run **`./gradlew formatKotlin`** and re-run **`./gradlew quality`**, or ratchet with **`detektBaseline`** (see §4).

---

## 9. PM2 (mandatory): local Gradle test/build threads, assessment, and `logs/`

The repository root includes **`ecosystem.config.cjs`** and **`scripts/pm2-run-gradle.cjs`**. **PM2 is the required way** to run the **mandatory local verification** commands in §9.2 so that **stdout/stderr** are captured under **`logs/*.log`** (gitignored) for **review before merge**. You may still run raw **`./gradlew`** from **`nutonic/`** while iterating (§3–§4), but **assessment for shipping** (PR / merge) must go through §9.2 unless §9.4 fallback applies.

**Detailed runbook (commands, log interpretation, Windows pitfalls):** **`docs/PM2_LOCAL_VERIFICATION.md`**.

### 9.1 Prerequisites

- **Node.js** (LTS) and **`npm install`** at the **repository root** whenever **`package.json`** / **`package-lock.json`** changes (installs **`pm2` v6.x** — keep aligned with your global PM2 daemon to avoid **`pm2 jlist`** banner noise; see runbook §6).
- **`JAVA_HOME`** / JDK as in §7 — Gradle behavior is unchanged; PM2 only supervises the process.

### 9.2 Mandatory testing and assessment (before PR / merge)

**Scope:** Any change under **`nutonic/`** that you intend to merge.

| Step | Action | Pass criteria |
|------|--------|----------------|
| **A. Lint + unit tests (always)** | From **repository root**: `npm install` if needed → `npx pm2 start ecosystem.config.cjs --only nutonic-ci-local` → `npm run pm2:wait-stopped -- nutonic-ci-local 3600000` (or wait until PM2 shows **stopped**). | **`logs/nutonic-ci-local.out.log`** contains **`BUILD SUCCESSFUL`**. **`logs/nutonic-ci-local.err.log`** reviewed (JVM noise vs new errors). |
| **B. Smoke build (when required)** | Same pattern with **`nutonic-build-verify`** and **`npm run pm2:wait-stopped -- nutonic-build-verify 7200000`** (long timeout; includes JS webpack). | **`logs/nutonic-build-verify.out.log`** contains **`BUILD SUCCESSFUL`**. |
| **C. Full Gradle `build` (optional)** | **`npm run pm2:build`** → **`npm run pm2:wait-stopped -- nutonic-build 7200000`** (long timeout; all variants + lint + ktlint). | **`logs/nutonic-build.err.log`** ends with **`BUILD SUCCESSFUL`** (stdout may be merged here when `merge_logs` is true). |

**When step B is required:** The PR modifies **`nutonic/webApp/`**, **`nutonic/androidApp/`**, **`nutonic/desktopApp/`**, **`nutonic/shared/`** in ways that affect compilation or resources, **or** **`nutonic/kotlin-js-store/`**, **or** root Gradle / version catalog under **`nutonic/`** that affects those modules. If in doubt, run **B**.

**Assessment record:** In the PR description (or review comment), state that **§9.2** was run and name the log files checked (or paste the final **`BUILD SUCCESSFUL`** line). Do not commit **`logs/`**.

**CI (§5)** remains the **cross-platform** authority; §9.2 is **mandatory local** evidence that the same Gradle graph passed on **your** machine with **retained logs**.

### 9.3 PM2 apps reference (start one optional app at a time for extra threads)

| PM2 name | Gradle intent |
|----------|----------------|
| **`nutonic-test`** | `./gradlew --no-configuration-cache test` |
| **`nutonic-quality`** | `./gradlew --no-configuration-cache quality` |
| **`nutonic-ci-local`** | **Mandatory** §9.2 step A — `./gradlew --no-configuration-cache --continue quality test` |
| **`nutonic-build-verify`** | **Mandatory** §9.2 step B when triggered — same tasks as §8 one-liner |
| **`nutonic-test-watch`** | `./gradlew test --continuous` — **optional** while editing; long-running; `autorestart` if the watcher crashes |

### 9.4 Fallback (PM2 or Node unavailable)

If **Node**, **npm**, or **PM2** cannot run on the machine (document **why** in the PR), you must run the **identical Gradle invocations** from a terminal, **capture** the full console output to a **local file** (not committed), and paste or attach the **tail** showing **`BUILD SUCCESSFUL`** (or failure) in the PR. This is **exception-only**; fix the toolchain when possible.

### 9.5 Commands (repository root)

```bash
npm install
npm run pm2:ci-local
npm run pm2:wait-stopped -- nutonic-ci-local 3600000
# assess logs/nutonic-ci-local.out.log and .err.log

npm run pm2:build-verify   # when §9.2 step B applies
npm run pm2:wait-stopped -- nutonic-build-verify 7200000
npm run pm2:build          # optional: full `./gradlew build`
npm run pm2:wait-stopped -- nutonic-build 7200000

npm run pm2:stop           # remove nutonic-* PM2 entries when done
npm run pm2:jlist          # clean JSON for tooling
npm run pm2:test           # optional ad-hoc
```

### 9.7 Helper scripts

| Script | Role |
|--------|------|
| **`scripts/pm2-jlist-json.cjs`** | Prints parseable **`pm2 jlist`** JSON (skips leading non-JSON lines). |
| **`scripts/pm2-wait-until-stopped.cjs`** | Async poll until a named app is not **`online`** (timeout arg, default 1h). |
| **`scripts/pm2-stop-nutonic.cjs`** | Deletes registered **`nutonic-*`** PM2 apps without spurious errors. |

### 9.6 Implications and caveats

- **CI is still required:** GitHub Actions (§5) is authoritative for **Ubuntu/macOS** matrix artifacts. **§9.2 is mandatory in addition** for local evidence and **`logs/`** retention, not a replacement for green CI.
- **Gradle parallelism:** Starting **`nutonic-test`** and **`nutonic-quality`** at the same time spins **two** Gradle invocations; they coordinate via the daemon but increase CPU/RAM use. For mandatory checks, use **`nutonic-ci-local`** (single invocation) unless you intentionally split runs.
- **Windows vs Unix:** The launcher selects **`nutonic/gradlew.bat`** vs **`gradlew`** automatically (aligned with **`.vscode/tasks.json`**).
- **Do not pipe raw `pm2 jlist` through PowerShell `ConvertFrom-Json`:** PM2’s payload can include **duplicate env keys** differing only by case; use **`npm run pm2:jlist`** or **`node scripts/pm2-jlist-json.cjs`** and parse in Node.
- **`pm2 update`:** Restarts the PM2 daemon and may **restore** apps from **`~/.pm2/dump.pm2`**; use with care on shared laptops (see runbook §6.3).
- **Web (Kotlin/JS) builds:** **`nutonic-build-verify`** can take a long time and may require a valid **`kotlin-js-store`** / lockfile state per §7.
- **Future `server/` tests:** When **`server/`** lands, extend mandatory assessment with a PM2 app (e.g. **`pytest`**) and **`logs/`** paths; document in **`docs/PM2_LOCAL_VERIFICATION.md`** and add a row to §9.2 (`plans/2026-04-07-gradio-terramind-backend.md`).

---

## 10. Related rules

- **`03-kotlin-multiplatform-structure.md`** — where tests and shared code live.
- **`05-networking-leaderboard.md`** — **local** default leaderboards, optional community API, ranked contracts (not covered by this file).
- **`14-testing-validation-pm2-and-documentation.md`** — PM2-first testing for Kotlin, Kotlin/JS, and Python; **mandatory log review** and fix-before-continue; **complete PM2 environment** per feature; pragmatic **tests vs code** order; **plans/** pinning and **rules/docs** updates when standards shift.
- **`README.md`** (rules) — reading order for product and UX constraints.
