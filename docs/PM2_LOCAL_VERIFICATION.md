# PM2 local verification (Gradle → `logs/`)

This document records how NU:TONIC runs **Kotlin Multiplatform** checks under **PM2**, where output lands, what was **verified on a real machine**, and how to avoid common **PM2 / Windows** pitfalls.

**Normative rule:** **`rules/11-vscode-testing-linting-and-ci.md` §9.2** makes PM2-backed runs and **log assessment** **mandatory** before merging changes under **`nutonic/`** (with §9.4 fallback if the toolchain is unavailable). This file is the **operational runbook** for that rule.

**Also see:** `ecosystem.config.cjs`, `scripts/pm2-run-gradle.cjs`.

---

## 1. Purpose

- Satisfy **§9.2**: run **`nutonic-ci-local`** (always) and **`nutonic-build-verify`** (when the rule says so), then **assess** **`logs/*.log`** for **`BUILD SUCCESSFUL`** before PR / merge.
- Run **`quality`**, **`test`**, and **smoke builds** in the **background**, with **timestamped logs** under **`logs/`** (gitignored).
- Same Gradle commands as CI and VS Code tasks, but **supervised by PM2** so you can close the terminal or attach later with `pm2 logs`.

---

## 2. One-time setup

| Step | Action |
|------|--------|
| Repo root | `npm install` (installs **`pm2`** matching `package.json`; currently **v6.x**). |
| JDK | **`JAVA_HOME`** or user `~/.gradle/gradle.properties` per `rules/11` §7. |
| Android | `nutonic/local.properties` with **`sdk.dir`** (and **`MAPS_API_KEY`** if building Android) — same as normal Gradle. |

---

## 3. PM2 applications (`ecosystem.config.cjs`)

| App name | Gradle command (from `nutonic/`) | `autorestart` | Typical duration (warm daemon) |
|----------|-----------------------------------|---------------|----------------------------------|
| `nutonic-test` | `--no-configuration-cache test` | no | ~seconds–minutes |
| `nutonic-quality` | `--no-configuration-cache quality` | no | ~seconds–minutes |
| `nutonic-ci-local` | `--no-configuration-cache --continue quality test` | no | ~tens of seconds |
| `nutonic-build-verify` | `test` + `:androidApp:assembleDebug` + `:desktopApp:compileKotlinJvm` + JS **production** webpack | no | **several minutes** (webpack) |
| `nutonic-test-watch` | `test --continuous` | yes | long-running |

**Start one app at a time** unless you intentionally want parallel Gradle load:

```bash
cd /path/to/nutonic-repo-root
npm run pm2:ci-local
# or
npx pm2 start ecosystem.config.cjs --only nutonic-build-verify
```

**Stop** NU:TONIC PM2 entries (best-effort):

```bash
npm run pm2:stop
```

---

## 4. Log files

All paths are **relative to the repository root**.

| File | Content |
|------|---------|
| `logs/<app>.out.log` | Gradle **stdout** (task lines, `BUILD SUCCESSFUL` / `FAILED`). |
| `logs/<app>.err.log` | Gradle **stderr** (JVM native-access warnings, etc.). |

PM2 may prepend **ISO timestamps** to each line.

**Success check:** search the **out** log for `BUILD SUCCESSFUL`:

```bash
# Unix
grep BUILD logs/nutonic-ci-local.out.log

# PowerShell
Select-String -Path logs\nutonic-ci-local.out.log -Pattern BUILD
```

---

## 5. Verified runs (2026-04-09, Windows 11)

Environment notes: Gradle **8.13**, Kotlin **2.0.21**, launcher JVM **25** (with Gradle native-access warnings in **err** logs), Android SDK present, repo path `C:\Users\MeMyself\nutonic`.

### 5.1 `nutonic-ci-local`

- **PM2:** Started cleanly; process moved to **`stopped`** after Gradle exited.
- **Gradle:** `BUILD SUCCESSFUL in 24s` (many tasks **UP-TO-DATE** after prior work).
- **Warnings in log (non-fatal):** Android `buildConfigFields`, Kotlin hierarchy / redundant `dependsOn`, deprecation notice for Gradle 9.

### 5.2 `nutonic-build-verify`

- **Duration:** `BUILD SUCCESSFUL in 6m 18s`; **189** actionable tasks (**92** executed).
- **Notable output:** Webpack **asset size** hints for large JS bundles (expected for Compose Multiplatform template).
- **Kotlin:** Various **deprecation** and **expect/actual Beta** warnings; build still succeeded.

### 5.3 `nutonic-test`

- **Result:** `BUILD SUCCESSFUL in 6s` in `logs/nutonic-test.out.log`.

---

## 6. PM2 messages and fixes

### 6.1 “Current process list is not synchronized with saved list”

- **Meaning:** Your global PM2 **dump** (`pm2 save`) lists apps that are not in the current in-memory list (e.g. another project’s `shakods-api`).
- **Impact:** **Harmless** for NU:TONIC runs. Optional: `pm2 save` after you are happy with the process list, or ignore.

### 6.2 `pm2 jlist` not valid JSON (banner / version mismatch)

**Symptom:** Lines such as `>>>> In-memory PM2 is out-of-date` appear **before** the `[` JSON array, so `JSON.parse` fails (including **PowerShell** `ConvertFrom-Json`).

**Fixes:**

1. Keep **local** `pm2` (**`package.json` devDependency**) aligned with the **daemon** (e.g. both **6.x**). Run **`npm install`** at repo root after pulling.
2. Use **`node scripts/pm2-jlist-json.cjs`** (or **`npm run pm2:jlist`**) which strips everything before the first `[`.
3. Avoid **`ConvertFrom-Json` on `pm2 jlist`** on Windows: PM2’s embedded `env` can contain duplicate keys differing only by case (`username` vs `USERNAME`), which **PowerShell** rejects.

### 6.3 `pm2 update`

- **Warning:** `pm2 update` **restarts the daemon** and may **restore** processes from **`~/.pm2/dump.pm2`**. You may see NU:TONIC apps **reappear** as **stopped** entries. Prefer **`npm run pm2:stop`** for cleanup after experiments.

### 6.4 Waiting until a one-shot app finishes

Use the poller (works cross-platform):

```bash
npm run pm2:wait-stopped -- nutonic-build-verify 3600000
```

Arguments: **app name**, optional **timeout ms** (default 1 hour).

---

## 7. JVM / Gradle stderr (err logs)

Example from **`logs/nutonic-ci-local.err.log`**:

- `java.lang.System::load` **restricted method** warning when the **Gradle launcher** runs on **JDK 25+**.
- **Mitigation (team):** Prefer **JDK 17–21** for **`JAVA_HOME`** / Gradle per `rules/11` §7.

These warnings do **not** come from PM2; they come from the JVM running **`gradlew`**.

---

## 8. Automation checklist

1. `npm install`
2. `npx pm2 start ecosystem.config.cjs --only <app>`
3. `npm run pm2:wait-stopped -- <app> <timeout-ms>`
4. `grep` / `Select-String` for `BUILD SUCCESSFUL` in `logs/<app>.out.log`
5. Non-zero Gradle exit → PM2 shows **`stopped`**; inspect **out** and **err** logs (PM2’s own exit code handling is per fork; **Gradle’s** code is reflected in log tail and process exit).

---

## 9. Future: Python `server/` tests

When `server/tests` exists, add a PM2 app that runs e.g. **`uv run pytest`** or **`python -m pytest`**, with **`cwd`:** `server`, and **`out_file` / `error_file`** under **`logs/`**, following the same gitignore rule.
