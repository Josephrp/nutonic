# Testing, validation, PM2 environments, and documentation upkeep

This document is the **authoritative rule** for **how** verification runs in the monorepo (PM2-first), **when** to treat Kotlin, Kotlin/JS (and Wasm), and Python as **in scope** for a change, **how** agents and humans must react to **logs** and failing builds, and **how** specs and rules stay aligned with shipped or in-flight work. It **extends** `11-vscode-testing-linting-and-ci.md` (Gradle layout, CI matrix, existing PM2 app names, §9.2 merge gate for `nutonic/**`). Where this file adds policy beyond §9, **both** apply.

---

## 1. PM2 is the default way to run tests and builds (not only `nutonic/**`)

### 1.1 Principle

**Long-running or merge-relevant** verification must be launched so that **stdout and stderr are captured under `logs/`** (gitignored), using the repo’s **PM2** wiring (`ecosystem.config.cjs`, `scripts/pm2-run-gradle.cjs`, and any future `scripts/pm2-run-*.cjs`). That gives a **durable artifact** for review—human or agent—without relying on scrollback alone.

### 1.2 Kotlin / KMP / Android / Desktop / Web (Gradle)

- **Source of truth for commands** remains **`11-vscode-testing-linting-and-ci.md`** (§3–§5, §8–§9) and **`.github/workflows/nutonic-ci.yml`**.
- **Kotlin unit tests, `quality`, and the combined `quality`+`test` path** run through the existing PM2 apps: **`nutonic-test`**, **`nutonic-quality`**, **`nutonic-ci-local`**.
- **Kotlin/JS and Kotlin/Wasm** production bundles (and thus JS toolchains invoked by Gradle) are part of **`nutonic-build-verify`**—treat them as **JS-side validation** of the KMP tree. Any feature touching `webApp`, `kotlin-js-store`, or cross-cutting Gradle that affects JS/Wasm **must** go through **`nutonic-build-verify`** when §9.2 step B applies in `11`.

### 1.3 Python (`data/scripts/`, `inference/*`, future `server/`)

- When the change touches **Python** code paths, verification **must** include whatever the repo defines for that subtree today (for example **`pytest`**, **`ruff check`**, or **`python -m`** entrypoints documented next to that package)—**and** those commands should be **wrapped in PM2** as soon as a stable one-shot pattern exists (same log directory, same “wait stopped → read logs” workflow as Gradle).
- **Until** a dedicated PM2 app exists for a given Python surface, the **exception** in `11` §9.4 applies: run the **documented** commands, **redirect full output** to a **local** log file under `logs/` (or equivalent), **read** it, and **paste** pass/fail evidence in the PR. **Adding** a PM2 app + `ecosystem` entry is the preferred follow-up so the next contributor does not rely on exceptions.

### 1.4 Node-only scripts

- Small **`npm run`** checks at repo root are fine for **bootstrap** (`npm install`, `pm2:wait-stopped`). **Merge-grade** evidence for multi-minute Gradle or Python runs still goes through **PM2 + `logs/`** per §2–§3 below.

---

## 2. Every new feature or implementation gets a “complete PM2 environment”

**“Complete”** means: for the **stack surfaces your change touches**, you run the **full** set of PM2-backed (or §9.4-equivalent) jobs **needed to falsify the feature**, not only the fastest single task.

| If you change… | Minimum PM2 / verification environment (in addition to any narrower iteration) |
|----------------|----------------------------------------------------------------------------------|
| `nutonic/shared`, `androidApp`, `desktopApp`, Gradle config affecting them | **`nutonic-ci-local`**; if compile/resources/JS store affected → **`nutonic-build-verify`** (`11` §9.2 A + B) |
| `nutonic/webApp` or `nutonic/kotlin-js-store` | **`nutonic-build-verify`** (includes JS/Wasm webpack paths) |
| Python under `data/scripts/` or `inference/` (or future `server/`) | Documented **Python** test/lint commands; **prefer** PM2 one-shot once defined; otherwise §9.4 with **`logs/`**-style capture |
| Cross-cutting **rules**, **CI workflows**, or **PM2** definitions | Re-run the **smallest** PM2 set that proves the edit did not break client verification—typically **`nutonic-ci-local`** at least |

**New features** that add a **new** long-running verification step (e.g. a new Gradle task suite or a new Python package) should **extend `ecosystem.config.cjs`** (and `docs/PM2_LOCAL_VERIFICATION.md` when user-facing) in the **same PR** or an immediate follow-up so the “complete environment” stays **one command family** for everyone.

---

## 3. Always execute, read logs, fix, then continue

This applies to **humans and agents**.

1. **Actually run** the build or test suite (PM2 preferred). **Do not** claim green without a completed run.
2. **Wait** for the process to finish (`npm run pm2:wait-stopped -- <app> <timeout>` or equivalent).
3. **Read** both **`*.out.log`** and **`*.err.log`** for that app. Gradle often prints failures to stdout; stderr still matters for stack traces and tooling noise.
4. If the run **failed**: **diagnose from the logs**, **change code or tests or config**, **re-run** until green **before** claiming the task is done or opening/updating a PR as ready.
5. **Do not** “continue implementation” on top of a **known-red** baseline without either fixing it or **explicitly** documenting an agreed exception (rare; product/owner call).

**Interpreting success:** same criteria as `11` §9.2 (`BUILD SUCCESSFUL` for Gradle; for Python, documented zero-failure exit and no new errors in the captured log tail).

---

## 4. Tests vs code order (pragmatic)

Either order is allowed; **convergence** is not optional.

- **Test-first** is encouraged when behavior is **already specified** (clear acceptance criteria, API contracts, regressions).
- **Code-first** is allowed for **exploratory** UI, spikes, or when specs are still catching up—**provided** you add or adjust **tests and/or PM2 verification** before merge and **update documentation** (§5) so the next change is not blind.
- **Refactors:** prefer a **behavior-preserving** test run (`nutonic-ci-local` or tighter) **before** and **after** the refactor.

No merge without a **green** verification pass for the **surfaces listed in §2**.

---

## 5. Documentation and standards upkeep (ongoing, not optional at end of quarter)

### 5.1 Pin forthcoming work

- **`plans/`** (dated plans, backlogs, gap analyses) are where **forthcoming** features and sequencing live. When you start a feature that was only sketched before, **add or update a plan entry** (or a short subsection in an existing plan) that **names** the feature, **links** to the relevant `docs/` and `rules/`, and **states** what PM2/CI slice proves it—so implementers do not rely on chat memory.

### 5.2 Update “standards” when implementation requires it

- If the **built behavior** diverges from **`rules/`** or **`docs/`** on purpose, **update those documents in the same change series** (same PR or stacked PRs) so **authority stays single-source**. Prefer **`rules/`** for **constraints** and **`docs/`** for **long-form spec**; do not leave only `plans/` describing shipped behavior.
- **`rules/README.md`** should gain a **pointer** when a **new rule file** is added (this file’s pattern).

### 5.3 Legacy and drift

- When you **touch** an area still described in **legacy** stitch paths, older plans, or deprecated tab names, **fix the obvious drift** (cross-links, “deprecated for IA” notes) **if your change makes the old text wrong**. Larger doc rewrites can be a separate commit but should not block a small fix—**file a follow-up** in `plans/` if the gap is large.

---

## 6. Relationship to CI and security workflows

- **GitHub Actions** remain the **cross-OS** source of truth (`nutonic-ci.yml`, `security-codeql-and-secrets.yml`, any Python CI added later). Local PM2 runs **prove the developer’s machine**; CI proves **shared** automation. **Both** matter; neither replaces the other for `nutonic/**` (`11` §9.6).

---

## 7. Related documents

- **`11-vscode-testing-linting-and-ci.md`** — Gradle commands, CI jobs, PM2 app table, §9.2 merge gate, §9.4 fallback.
- **`docs/PM2_LOCAL_VERIFICATION.md`** — operator runbook.
- **`CONTRIBUTING.md`** (repo root) — contributor-oriented summary with links into `rules/`.
