# NU:TONIC — Publishable UI, vendored parity, and release-ready shell

**Date:** 2026-04-21  
**Status:** Normative implementation plan — supersedes ad-hoc “prototype polish” scope for **client-facing** work not already closed under **IMP-040–IMP-084**, **IMP-090**, **IMP-110+**.  
**Authority:** [`docs/DESIGN.md`](../docs/DESIGN.md), [`rules/02-design-system.md`](../rules/02-design-system.md), [`rules/07-screens-checklist.md`](../rules/07-screens-checklist.md), [`rules/08-ux-and-performance-footguns.md`](../rules/08-ux-and-performance-footguns.md), [`rules/01-navigation-architecture.md`](../rules/01-navigation-architecture.md), [`docs/GAME-ENGINE.md`](../docs/GAME-ENGINE.md), [`docs/SCREEN-MUSIC-SPEC.md`](../docs/SCREEN-MUSIC-SPEC.md), [`docs/CLIENT-SETTINGS-SPEC.md`](../docs/CLIENT-SETTINGS-SPEC.md), [`docs/INTEL-TAB-SPEC.md`](../docs/INTEL-TAB-SPEC.md), [`docs/RANKED-MODE.md`](../docs/RANKED-MODE.md), [`docs/VENDORED-UI-CONTRACT-PACK.md`](../docs/VENDORED-UI-CONTRACT-PACK.md), [`docs/PUBLISHABLE-UI-EXIT-CRITERIA.md`](../docs/PUBLISHABLE-UI-EXIT-CRITERIA.md) (exit checklist), [`rules/15-publishable-ui-and-release-readiness.md`](../rules/15-publishable-ui-and-release-readiness.md). Where **`§0.1`** conflicts with stricter release-readiness prose elsewhere, **`§0.1` wins** for this plan iteration (e.g. telemetry / banner priority, CI screenshot gates).  
**Prerequisite artifacts (updated):** Do **not** require wiring `refs/stitch/` into the repo. Treat `refs/stitch/` as optional local input and keep it **gitignored**. Publishable parity is evaluated against **vendored first-party contracts** in `docs/` + `rules/` (especially `docs/VENDORED-UI-CONTRACT-PACK.md`, `docs/NU_TONIC_ARTIFACT_REFERENCE.md`, `rules/07-screens-checklist.md`, `docs/DESIGN.md`, and this plan).

**Relationship to existing plans:** This plan **does not** replace `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`, `plans/2026-04-16-stub-replacement-implementation-plan.md`, or `plans/2026-04-13-prioritized-implementation-task-backlog.md`; it **binds** them to **shippable player UI** and introduces a dedicated task band **IMP-140–IMP-149** (register in backlog §0.1 on next backlog edit). When implementation outpaces backlog prose (e.g. Web **IMP-084** share), update **`plans/2026-04-13-prioritized-implementation-task-backlog.md`** in the same PR as the code change (**§8.1.1**).

---

## 0. Definitions

| Term | Meaning |
|------|---------|
| **Publishable interface** | No `rules/07` screen shows **placeholder-only** primary content; no **IMP-** / `docs/…` **§** debug strings on **player-facing** surfaces; **localization-ready** string tables (or Compose resources) for en-US v1; **TalkBack / VoiceOver** labels on primary actions (`rules/08` §10). |
| **Structure parity (vendored)** | **Information architecture** and **control grouping** match vendored contracts in `docs/` + `rules/` (e.g. SCAN hub converges **4b + 4c + leaderboard slice + play** on one scrollable hub, not four stub buttons). |
| **Token parity** | Colors, radii, typography roles, glow discipline per `docs/DESIGN.md` + `rules/02` — implemented via **semantic theme** (`NutonicColors` / extended tokens), not raw `Color(0x…)` in feature composables. |
| **Engine parity** | **Player copy** uses product names (“Play”, “Round complete”) not internal phase codes on surfaces players see. **Debug and release binaries behave the same** (§2.1); internal labels are not a separate “debug flavor” concern. |

---

## 0.1 Product architecture decisions (normative — 2026-04-21)

These decisions **override** earlier optional / strict language elsewhere in this document where they conflict.

| ID | Decision |
|----|----------|
| **AD-1 Offline-first & version skew** | **Very permissive:** prioritize **full app access without forced updates**. **Persist guesses locally**; **upload / sync when the network is available**. When server manifest and shipped bundle disagree on `content_version`, **still allow playable rounds** by merging or falling back to shipped round truth as needed. **Clear, short user messaging** is required; **telemetry and decorative banners are explicitly not priorities** (ship without dedicated telemetry pipelines or banner-heavy UX if needed). |
| **AD-2 Build parity & CI** | **Debug and release are identical** in behavior: no UI or gameplay forks keyed on `debug` vs `release`. Configuration comes from **committed files** plus **CI-injected** values so the **same** CI-built artifacts exercise the pipeline. **CI builds target the appropriate Hugging Face** (and related) **servers** via committed config layout + CI secrets/env (document the variable names next to `NutonicApiClient` / server base URL wiring). |
| **AD-3 Share UX** | Either keep **`shareNutonicScorecard` synchronous** from the caller’s perspective **or** go async — in **both** cases, implement the **full set of overlays** a synchronous design would need: **loading**, **success**, **failure**, dismissible surfaces, and the ability to **close** overlays, **navigate**, and **continue using the app** (including optionally proceeding while a share finishes in the background). |
| **AD-4 Module layout & naming** | Everything that **should** be shared across tabs, routes, or platforms lives in **well-named** `commonMain` (and platform `actual`s where required). **Refactor and rename files** so names match responsibilities (e.g. split oversized `WorldMapGameplayScreen.kt`, rename shells vs. gameplay vs. share). |
| **AD-5 CI & visual regression** | **Do not require CI changes solely for UI** or add visual-regression gates for this track. **IMP-148** (screenshot baselines) is **out of scope / deferred** unless product revisits. |
| **AD-6 Manifest refresh ordering** | **Not a planning priority** for this iteration (no normative ordering work beyond “keep app usable”). |
| **AD-7 Ranked assists / forfeit** | **Not strict, not a priority** for this iteration; existing behavior may evolve without blocking publishable UI work. |

---

## 1. Executive summary

| Track | Outcome | New task IDs |
|-------|---------|--------------|
| **A — IA & routes** | Remove **stub-only** SCAN hub; implement **mission (4c)** + **map/level (4b)** as real surfaces; keep **one** `mapContextId` + `rankFocusMapId` contract (`IMP-071`). | **IMP-140**, **IMP-141** |
| **B — Design system in Compose** | Glass/surface components, CTA radius **12–16dp**, bottom bar per `DESIGN.md` §5 (indicator **above** label cluster; SCAN elevation), no debug Material-only chrome on shipped routes. | **IMP-142** |
| **C — Screen completion** | Splash, auth, role, INTEL, RANK, SETUP, PRO, success (#6), final results (#7) per `rules/07` + `docs/INTEL-TAB-SPEC.md` where applicable. | **IMP-143**, **IMP-144** |
| **D — SCAN / gameplay polish** | Short **clear messaging** for offline / skew (no banner/telemetry product requirements); HUD timer **cosmetic** labeling; **Web** share with **overlay-complete** UX per **AD-3** (`IMP-084` / **IMP-146**). | **IMP-145**, **IMP-146** |
| **E — Audio** | Replace silence WAV with mastered loops + crossfade per `docs/SCREEN-MUSIC-SPEC.md` §3 `track_id` table. | **IMP-051** (close remainder) |
| **F — Data plane (permissive)** | **Offline-first merge & sync** per **AD-1**: overlay / fallback so **gameplay stays available** without app updates; **local guess persistence** + **retry when online**; avoid blocking the shell on `content_version` skew. | **IMP-147** |
| **G — QA & release** | Manual vendored-contract + store checklist (**IMP-149**). **No CI work for UI screenshots**; **IMP-148 deferred** per **AD-5**. | **IMP-149** |

---

## 2. Precise parameters (normative)

### 2.1 Builds, CI parity, and endpoints (**AD-2**)

| Rule | Normative text |
|------|----------------|
| **No debug/release UI fork** | **Do not** branch player-visible behavior on Gradle `buildType` or Xcode configuration. **Debug and release artifacts must behave the same** for UI, merge policy, and share flows. |
| **Committed configuration** | Server base URLs, Hugging Face–related hostnames, and defaults ships need live in **committed** sources (typed config, versioned properties, or documented defaults next to `NutonicApiClient` / DI wiring). |
| **CI → Hugging Face** | CI sets **documented env vars or injected config** so the same client binary stack talks to **CI-appropriate** Hugging Face (and game) endpoints; document variable names in `CONTRIBUTING.md` or `server/README.md`. Local dev uses the **same mechanism** with different values — not alternate code paths. |
| **Quality gates** | `./gradlew :shared:validateCatalog` and `./gradlew quality test` stay per `rules/11`; **no** new CI jobs for UI screenshots (**AD-5**). |

**Internal engine labels:** If still useful for engineering, they must follow **the same** visibility rules in all build types (e.g. always off for player-facing surfaces) — **no** separate “debug flavor” that exposes `HUMAN_PLAY` strings to players.

### 2.2 Theme tokens (extend `NutonicTheme`)

| Token (code name) | `docs/DESIGN.md` § | Default (hex) | Usage |
|-------------------|-------------------|-----------------|-------|
| `NutonicTheme.colors.surfaceGlass` | §2 Glass | `surface` @ **55%** alpha over blur fallback | Assist dock, guess modal, narrative sheet. |
| `NutonicTheme.colors.outlineGhost` | §2 No-Line | `#3B494C` @ **15%** opacity | Optional card boundary (a11y). |
| `NutonicTheme.shapes.cta` | §5 Buttons | **12.dp** corner (min) — **16.dp** max for primary CTA | `RoundedCornerShape` shared. |
| `NutonicTheme.motion.crossfadeMs` | `CLIENT-SETTINGS` + `SCREEN-MUSIC` | **400ms** default BGM crossfade | Align with `PlatformBgmPlayer`. |

**Implementation rule:** New UI in `nutonic/shared/src/commonMain/kotlin/com/nutonic/` must consume **only** theme tokens for color/shape; **exceptions** listed in a single `ThemeExceptions.kt` with product waiver comment (`rules/08`).

### 2.3 SCAN hub layout parameters

| UI region | Min height / width | Notes |
|-----------|-------------------|-------|
| Mission grid row | **minHeight 72.dp** | Touch target `rules/08` §1. |
| Map catalog card | **thumb 3:2** + title + **chevron** to per-map RANK | Tapping row sets `mapContextId` + `mapContextTitle`; **≤1** extra action to community/RANK slice (`rules/07` #4b). |
| “Play” primary CTA | **full width**, **16.dp** vertical margin from list | Single cyan CTA; ranked secondary CTA **outline** style when `features.ranked == true`. |

### 2.4 Manifest / offline copy (replace raw errors)

| Condition | User-visible title | User-visible body (en-US template) |
|-----------|-------------------|-------------------------------------|
| `ManifestSyncResult.Failed` + **no** persisted envelope | “Couldn’t reach NU:TONIC” | “You’re offline or the game server isn’t running. **Maps below** use the copy bundled with this app.” |
| `ManifestSyncResult.Failed` + persisted envelope | “Couldn’t refresh” | “Showing **saved** maps from your device (**{content_version}**). Pull to refresh when online.” |
| `mergeShippedRoundTruthDetailed` → **`VERSION_MISMATCH`** (informational only) | *(Optional one-liner)* | “Catalog **{server_cv}** differs from bundled **{shipped_cv}**. You can keep playing; guesses are saved and will send when possible.” **Do not** block the app, force updates, or rely on heavy banners (**AD-1**). |

**Parameters:** `{content_version}`, `{server_cv}`, `{shipped_cv}` read from `CacheManifestDocument.contentVersion` and shipped `readShippedFullManifest()?.contentVersion`.

**Merge implementation note:** Client merge logic in `cache/ShippedManifestMerge.kt` (and callers in `ContentCacheRepository.kt` / `WorldMapGameplayScreen.kt`) must be updated so **`VERSION_MISMATCH` does not prevent** using shipped `locations` / `ai_guesses` when the server snapshot is empty, redacted, or otherwise unplayable — **permissive default** aligned with **AD-1**.

### 2.5 Engine HUD (gameplay)

| Element | Parameter | Rule |
|---------|-----------|------|
| Play timer label | `string.play_timer_cosmetic` = **“Sector time (not scored)”** | Must appear on **every** elapsed/budget line shown, or product hides budget entirely (`GAME-ENGINE` §7.3). **Do not** label only the countdown row while leaving a separate “Elapsed” line unlabeled — avoids competitive misread. |
| Budget display | **Hidden** if product prefers count-up only (same rule all build types, **AD-2**); if shown, **no red color** (not a warning). | Removes competitive misread. |

### 2.6 Offline-first merge & sync (**AD-1** — single permissive policy)

| Requirement | Normative behavior |
|-------------|---------------------|
| **Play without updates** | App remains **fully navigable** and rounds **start** using bundled and/or merged manifest data even when `content_version` differs from server. |
| **Guess persistence** | Guesses and score-relevant payloads are **written to local storage** immediately; network `POST` / sync runs **when connectivity and server acceptance allow**, with **retry** (queue or idempotent replay — implementation choice). |
| **Messaging** | At most **light** inline or one-shot copy (§2.4 optional row); **no** requirement for telemetry, sticky banners, or multi-step “update required” flows. |
| **Blocking** | **Do not** set `nonRankedContentBlocked` (or equivalent) solely because of `VERSION_MISMATCH` if shipped data can supply a round. |

### 2.7 Shared code, refactors, and file naming (**AD-4**)

| Rule | Normative text |
|------|----------------|
| **Extract common UI** | Tab chrome, manifest status strings, share overlay state machine, HUD cards, and SCAN map list rows move into **dedicated** composable files under `screens/` or `shell/` (new package OK) rather than growing monoliths. |
| **Rename for clarity** | Files should read as **nouns** for surfaces (`ScanHubScreen.kt`, `GameplayHud.kt`) vs. catch-alls; rename `WorldMapGameplayScreen.kt` when split so imports stay obvious. |
| **Platform boundaries** | `expect`/`actual` only for true platform I/O (share, persistence, URLs if env-specific); **not** for debug-vs-release UI. |

---

## 3. Phased work breakdown

### Phase P0 — Vendored UI contracts (blocking)

| ID | Deliverable | Acceptance | Deps |
|----|-------------|------------|------|
| **IMP-140** | Vendor required UI parity inputs into first-party docs/rules and keep `refs/stitch/` optional + gitignored. | Ship/maintain `docs/VENDORED-UI-CONTRACT-PACK.md` (screen composition, copy anchors, control inventory) and remove submodule dependency from contributor workflow. | — |

### Phase P1 — IA: converged SCAN hub (**IMP-141**)

| Step | File / module | Action |
|------|---------------|--------|
| 1.1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/shell/ScanHubScreen.kt` (+ `NutonicMainShell.kt` tab wiring) | **SCAN tab:** `ScanHubScreen` converges hub sections — finish **IMP-141** by removing **player-visible** spec/debug strings, upgrading map rows to **card + chevron** pattern (§2.3), and tightening manifest status styling. **Other tabs:** replace remaining `NavStubButton` entry points in `RankTabRoot` / `IntelTabRoot` / `SetupTabRoot` with first-run **inline** content or real `ShellDetail` composables so players never hit placeholder-only primary surfaces. |
| 1.2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/navigation/NutonicRoute.kt` (`sealed class ShellDetail`) | **Deprecate** or remove unused `MissionSelection` / `MapLevelSelection` from default player flows (KDoc + `@Deprecated` + no tab routes). **Do not** introduce alternate navigation graphs for “debug” vs “release” (**AD-2**). Optional: `NutonicRoute.Debug` **only** if it compiles in all flavors and is off by default in committed config. Update `ShellDetailPlaceholder` in `screens/NutonicChecklistScreens.kt` as routes are retired. |
| 1.3 | Data | **Mission** rows sourced from **`prompts/`** serialized bundle (`docs/NARRATIVE-AND-PROMPTS.md`) + optional `mission_id` in OpenAPI `MapSummary` extension — if schema not ready, **client-only** mission table keyed by `map_id` until **IMP-011** bump. |

**Acceptance:** `rules/07` #4b and #4c **must-include** rows satisfied on **SCAN** without **player-facing** placeholder-only **primary** surfaces. **Non-SCAN** tabs must not rely on `NavStubButton` as the only path to real checklist content (**§8.2**). **Refactors** follow **§2.7** (extract `ScanHubScreen.kt` etc. as files grow).

### Phase P2 — Design system components (**IMP-142**)

| Component | API sketch | Spec |
|-----------|------------|------|
| `NutonicGlassCard` | `(modifier, content)` — blur on Android/desktop where supported; solid + gradient fallback on Web/iOS if blur costly | `DESIGN.md` §2 Glass |
| `NutonicPrimaryButton` / `NutonicGhostButton` | scale hover **desktop only**; pressed alpha | `DESIGN.md` §5 |
| `NutonicBottomBar` | Icons (Material **Symbols** mapped in `NU_TONIC_ARTIFACT_REFERENCE.md` §6.2) + SCAN elevated node | `DESIGN.md` §5 Navigation |

**Acceptance:** SCAN/gameplay chrome uses **`NutonicColors`** / **`MaterialTheme`** (token parity per §0); **no** raw `Color(0x…)` in feature composables. The retired KMP **photo gallery** sample (**`NutonicPhotoGalleryColors`**, SETUP shortcut, gallery flow) is **removed** from the client tree.

### Phase P3 — Checklist screens (**IMP-143**, **IMP-144**)

| Screen (#) | Legacy ref id (optional) | Work |
|------------|---------------|------|
| 1 Splash | `splash_screen` | Animated globe optional; **Initialize** CTA; footer build/version from `BuildConfig` / expect **actual**. |
| 2 Auth | `authentication` | Skippable path unchanged; styled fields. |
| 3 Role | `role_selection` | Three cards with perk copy from `prompts/` or resource table. |
| 4 INTEL | `dashboard` | Implement **`docs/INTEL-TAB-SPEC.md`** §1 layout minimum: XP strip, session card, daily protocols **stub data OK** with real layout. |
| 8 SETUP | `settings_protocol` | Full sections from `docs/CLIENT-SETTINGS-SPEC.md` §6 (grouped); link audio to BGM. |
| 9 PRO | `refs/VLMExample/` | Port checklist: minimal **functional** VLM strip per `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` (not placeholder title only). |
| 6 Success | `success_overlay` | Distinct route or modal from gameplay with score/distance/CTA **Next** / **RANK**. |
| 7 Final results | `final_results` | Tactical breakdown layout + local history + **AI vs golden** row. |

**Acceptance:** Each route plays correct `track_id` per `docs/SCREEN-MUSIC-SPEC.md`; music toggle on every surface (`rules/07` header rule).

### Phase P4 — World map & SCAN data UX (**IMP-145**, **IMP-146**)

| ID | Scope |
|----|-------|
| **IMP-145** | **Player-facing** surfaces: no internal phase codes; cosmetic timer copy per §2.5. **Same** rules in all build types (**AD-2**). **Street View** assist title remains **“Location assist (text)”** when no pano player. |
| **IMP-146** | **Share flows (`jsMain` + common):** implement **AD-3** — **loading / success / error** overlays (or sheets), dismiss + navigate + app remains usable; sync API **or** async with equivalent UX. Refactor share + overlay state into dedicated files per **§2.7**. |

### Phase P5 — Permissive manifest merge & offline sync (**IMP-147**)

| Step | Detail |
|------|--------|
| 5.1 | **`ShippedManifestMerge.kt`:** Per **§2.6 / AD-1**, when the server document **cannot** supply a playable `ManifestRoundLocation` for the player’s context (including **`VERSION_MISMATCH`** with empty/redacted `locations`, or empty `ai_guesses` when needed), **merge in shipped** `locations` / `ai_guesses` so rounds remain playable **without** an app update. When server rows are present and sufficient, **prefer server** truth. Update `ShippedManifestMergeTest.kt`. |
| 5.2 | **`WorldMapGameplayScreen.kt`:** Remove **blocking** UX tied only to skew (`nonRankedContentBlocked` must not fire solely on mismatch when shipped can serve the round). Optional one-line info per §2.4; **no** telemetry or banner stack requirements. |
| 5.3 | **Guess / score sync:** Extend `LocalNonRankedLeaderboardRepository` and/or `NutonicApiClient` usage so records are **persisted locally first**, then **POST when online** (retry queue or equivalent). Idempotency keys already used where applicable — preserve. |
| 5.4 | **`com/nutonic/shell/ScanHubCatalog.kt` (`refreshScanHubCatalog`):** Keep SCAN usable when manifest HTTP fails (existing fallbacks); **no** new normative ordering work (**AD-6**). |

### Phase P6 — BGM production (**IMP-051** completion)

| `track_id` | File pattern under `composeResources/files/music/` | Loop length target |
|------------|-----------------------------------------------------|---------------------|
| `music_scan_hub` | `scan_hub_loop.wav` (or `.ogg` if supported) | **30–90s** seamless loop |
| `music_gameplay` | `gameplay_loop.wav` | same |
| (complete table in `docs/SCREEN-MUSIC-SPEC.md` §3) | … | … |

**Acceptance:** No **silent** WAV in **shipped** artifacts (same expectation all build types per **AD-2**); Web autoplay policy documented in `SCREEN-MUSIC-SPEC` §6 (`rules/08` §12).

### Phase P7 — Visual regression (**IMP-148**) — **deferred / out of scope**

Per **AD-5**, **do not** add Paparazzi, Roborazzi, or CI screenshot gates for this track. Re-open **IMP-148** only if product reverses **AD-5**.

### Phase P8 — Release checklist (**IMP-149**)

- Execute [`docs/PUBLISHABLE-UI-EXIT-CRITERIA.md`](../docs/PUBLISHABLE-UI-EXIT-CRITERIA.md) **§3** table sign-off.  
- App store assets: **1024×1024** icon, **feature graphic**, privacy policy URL (placeholder forbidden in **release** build).

---

## 4. Dependency graph (summary)

```text
IMP-140 (vendored UI contract pack)
   └── IMP-142 (theme components) ∥ IMP-141 (SCAN IA) ∥ §2.7 refactors (AD-4)
           └── IMP-143 (shell screens)
                   └── IMP-144 (INTEL/SETUP/PRO depth)
                           └── IMP-145/146 (gameplay polish + share overlays)
                                   └── IMP-147 (permissive merge + offline sync)
IMP-051 (BGM) ∥ above where possible
IMP-149 (release checklist) last
# IMP-148 (visual regression): deferred — AD-5
```

---

## 5. OpenAPI / server touchpoints (when UI needs schema)

| Change | Field | Notes |
|--------|-------|------|
| Optional **`GET /api/v1/maps`** extension | `mission_id`, `mission_title`, `thumbnail_bundle_id` | Backward compatible nullable fields; **FastAPI** + `docs/openapi.yaml` in one PR. |
| Manifest | Document **`content_version`** bump playbook in `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md` §5 | Reduces skew; client remains **permissive** when skew occurs (**AD-1**). |
| **CI / Hugging Face** | Document env vars for HF + game server URLs consumed by the client in CI | **AD-2**; no duplicate “debug only” URL tables. |

### 5.1 Local-first guess sync (outbox) — implementation contract (**AD-1**)

| Concern | Decision |
|--------|----------|
| **Write timing** | On submit, always persist a local guess row first (already done for non-ranked history). Network send is a separate step. |
| **Outbox record** | Add a persisted outbox row (new store or extension) with: `idempotency_key`, `map_id`, `round_instance_id`, payload JSON, `attempt_count`, `next_attempt_at`, `last_error`, `created_at`, `last_attempt_at`. |
| **Retry trigger** | Attempt flush on app launch, SCAN entry, gameplay entry, and after successful network calls. Optional periodic timer while app is foregrounded. |
| **Retry policy** | Exponential backoff with jitter (e.g. 1s, 5s, 15s, 60s, 5m, 15m, cap). Retry only for transient failures; stop permanently on clear 4xx contract failures except idempotent 409-equivalent success cases. |
| **Idempotency** | Reuse deterministic key (`guess-record\|{round_instance_id}` or stronger canonical key) so replays are safe server-side. |
| **User messaging** | Lightweight only: non-blocking status (“Saved locally, syncing…”, “Synced”, “Will retry when online”). No heavy modal flows required. |
| **Data retention** | Keep successful outbox rows only as needed for diagnostics (short TTL), then purge. Keep failed rows bounded (max rows + oldest-drop strategy) to avoid unbounded growth. |

**File-level landing (initial):**

- `nutonic/shared/src/commonMain/kotlin/com/nutonic/leaderboard/LocalNonRankedLeaderboardRepository.kt` — keep round-history concerns; do not overload with retry scheduling logic.
- `nutonic/shared/src/commonMain/kotlin/com/nutonic/persistence/` — add an outbox blob store abstraction (`GuessSyncOutboxStore`).
- `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/WorldMapGameplayScreen.kt` — enqueue outbox payload on submit; invoke lightweight flush kick.
- `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiClient.kt` — expose replay-friendly send method that accepts caller-provided idempotency key.
- `nutonic/shared/src/commonTest/...` — add unit tests for enqueue, retry backoff progression, transient/permanent failure branching, and idempotency replay behavior.

---

## 6. Non-goals (this plan)

- Replacing **Compose** with **Stitch HTML** runtime (`rules/09` forbids primary ship).  
- **Road-bearing** Street View graph (`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md` deferred items).  
- **DB-backed** `GET /api/v1/maps` (remains optional per gap analysis).  
- **CI changes solely for UI visual regression** or screenshot diff gates (**AD-5** / **IMP-148**).  
- **Strict** ranked assist / forfeit policy rework (**AD-7**).  
- **Normative manifest refresh ordering** beyond “keep SCAN playable” (**AD-6**).  
- **Telemetry pipelines** and **banner-heavy** manifest UX (**AD-1**).  

---

## 7. Verified assessment baseline (repo snapshot)

**Purpose:** Anchor this plan to an explicit **as-implemented** snapshot so future edits do not re-litigate “already landed.” Line anchors refer to `nutonic/shared` **as of 2026-04-20**; after refactors, use `rg`/symbol search to re-locate.

### 7.1 Strengths (keep)

| Item | Evidence |
|------|----------|
| Converged SCAN hub (missions + maps + leaderboard preview + play) | `NutonicMainShell.kt` — `ScanHubRoot` (~L369–L618). |
| Shared `mapContextId` / `rankFocusMapId` | `NutonicMainShell.kt` (~L78–L82, L157–L165); `NutonicRoute.kt` shell encoding. |
| Bottom bar indicator **above** cluster + SCAN elevation | `NutonicMainShell.kt` — `NutonicBottomBar` (~L831+). |
| Header music master on all app routes | `NutonicApp.kt` — `NutonicMusicMasterTopBar` (~L90–L94). |
| Merge outcome type + version banner on gameplay | `ShippedManifestMerge.kt`; `WorldMapGameplayScreen.kt` — `manifestVersionNotice` (~L150–L181). |
| “Location assist (text)” assist title | `WorldMapGameplayScreen.kt` — `AssistDock` / `AssistSection` (~L1115–L1117). |
| Web share paths (`navigator.share`, clipboard, legacy copy) | `ShareNutonicScorecard.js.kt`. |

### 7.2 Gaps (drive §8)

| Issue | Evidence | Note vs **§0.1** |
|-------|----------|-------------------|
| Implementation metadata in player UI | `NutonicMainShell.kt` — SETUP ~L732–L735; RANK ~L690–L694; SCAN `mission_id:` ~L458–L462. | Still fix (**IMP-141**). |
| Internal labels / const gate | `WorldMapGameplayScreen.kt` — `SHOW_ENGINE_DEBUG_LABELS` ~L91. | Replace with **same** rule all builds: hide from players or remove (**AD-2**, **IMP-145**). |
| HUD timer semantics incomplete | `GameplayHudCard` ~L932–L938. | **IMP-145**. |
| **Strict** merge blocks play on skew | `ShippedManifestMerge.kt` + `WorldMapGameplayScreen.kt` blocking paths ~L170–L181, L225. | **Superseded** — implement **§2.6** permissive merge (**AD-1**, **IMP-147**). |
| Share UX lacks full overlay lifecycle | `RoundSuccessOverlay` + `ShareNutonicScorecard.js.kt`. | **AD-3** / **IMP-146**. |
| Monolithic files / naming | `NutonicMainShell.kt`, `WorldMapGameplayScreen.kt` size. | **§2.7** / **AD-4**. |
| Backlog stale vs Web share | `plans/2026-04-13-prioritized-implementation-task-backlog.md` IMP-084 row. | **§8.1.1**. |

---

## 8. File-level resolution backlog

**How to use:** Execute tasks in **IMP-ID** order where deps apply; within one IMP-ID, row order is suggested. **“Verify”** = confirm already true and update docs/backlog only. **§0.1 (AD-1–AD-7)** overrides older rows where they conflict.

### 8.0 Cross-cutting — refactors, naming, CI config (**AD-2**, **AD-4**, **AD-5**)

| # | File / area | Task |
|---|-------------|------|
| 8.0.1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/` | Extract **`ScanHubRoot`** (and related catalog helpers) from `NutonicMainShell.kt` into e.g. `shell/ScanHubScreen.kt` or `screens/scan/ScanHubScreen.kt`; keep `NutonicMainShell.kt` as thin composition. |
| 8.0.2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/WorldMapGameplayScreen.kt` | Split into **`GameplayScreen.kt`** (or keep name) + `GameplayHud.kt`, `AssistDock.kt`, `RoundSuccessOverlay.kt`, `ShareScorecardFlow.kt` (names negotiable — must reflect ownership). |
| 8.0.3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/share/` + `NutonicApp.kt` | Centralize **share overlay** state (loading/success/error) so all platforms share the same **Composable contract**; `jsMain` implements transport only. |
| 8.0.4 | `CONTRIBUTING.md` / `server/README.md` / CI workflow yaml | Document **env vars** for game server + **Hugging Face** endpoints consumed at runtime; **no** CI job additions for UI screenshots (**AD-5**). |

### 8.1 IMP-140 — Vendored contracts & contributor flow

| # | File | Task |
|---|------|------|
| 8.1.1 | `plans/2026-04-13-prioritized-implementation-task-backlog.md` | Update **§0.1** / **IMP-084** / **IMP-147** / **IMP-148** rows: permissive merge (**AD-1**), debug=release (**AD-2**), **IMP-148** deferred (**AD-5**). |
| 8.1.2 | `docs/PUBLISHABLE-UI-EXIT-CRITERIA.md` | Align exit rows with **§0.1**: optional skew copy, **no** telemetry/banner sign-off; remove strict “policy A/B” gate if present. |

### 8.2 IMP-141 — IA & stub elimination

| # | File | Task |
|---|------|------|
| 8.2.1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/NutonicMainShell.kt` | Remove **player-visible** `mission_id:` debug line (`ScanHubRoot`, ~L458–L462). Replace with nothing or localized “Mission” label only. |
| 8.2.2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/NutonicMainShell.kt` | Rewrite `RankTabRoot` intro (~L689–L694): remove `rules/01` string; use product copy (“Pick a map…”). |
| 8.2.3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/NutonicMainShell.kt` | Rewrite `SetupTabRoot` subtitle (~L731–L735): remove `IMP-051` / `CLIENT-SETTINGS-SPEC §4`; use one plain-language sentence + link to Audio section inside SETUP body. |
| 8.2.4 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/NutonicMainShell.kt` | Replace `NavStubButton("Global / map leaderboard flow")` (~L695): embed primary **RANK** content (e.g. open `ShellDetail.RankGlobal` behind a **primary** CTA that is not ghost-only stub), or inline `CommunityLeaderboardPanel` without extra stub row if redundant. |
| 8.2.5 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/NutonicMainShell.kt` | Replace `NavStubButton("Full protocol / security screen (#8)")` (~L761): either implement grouped `SetupProtocol` composable per `docs/CLIENT-SETTINGS-SPEC.md` §6 or rename CTA to user language without “#8”. |
| 8.2.6 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/NutonicMainShell.kt` | `IntelTabRoot` (~L658–L661): replace “Open full INTEL dashboard” stub with **§1 minimum** INTEL layout per `docs/INTEL-TAB-SPEC.md` or fold content into tab without `ShellDetail` placeholder. |
| 8.2.7 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/navigation/NutonicRoute.kt` | Trim KDoc that cites `IMP-071` on `rankFocusMapId` (~L20) if visible in generated doc portals; keep in code comment only if needed for engineers. |

### 8.3 IMP-142 — Theme tokens & raw color

| # | File | Task |
|---|------|------|
| 8.3.1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/style/` | Add `ThemeExceptions.kt` (waived raw colors) per §2.2 rule; migrate **new** surfaces off ad-hoc hex except listed exceptions. |
| 8.3.2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/style/Palette.kt` (`NutonicTheme`) + `NutonicComponents.kt` | Plumb §2.2 tokens: `surfaceGlass`, `outlineGhost`, `shapes.cta`, `motion.crossfadeMs`; refactor `NutonicComponents.kt` to read **cta** shape + glass colors from theme (~L16–L27, L43–L47). |
| 8.3.3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/WorldMapGameplayScreen.kt` | `ReferenceStillCard` placeholder colors ~L1054, L1061–L1062: replace raw `Color(0x…)` with theme tokens or add to `ThemeExceptions.kt` with waiver. |
| 8.3.4 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/WorldMapGameplayScreen.kt` | Replace default `Button` on world map header (~L645–L647) with `NutonicGhostButton` / `NutonicPrimaryButton` per design system. |

### 8.4 IMP-143 / IMP-144 — Checklist depth

| # | File | Task |
|---|------|------|
| 8.4.1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/NutonicChecklistScreens.kt` | Splash: add build/version footer (expect/actual for `BuildConfig` / platform); ensure `track_id` parity per `NutonicRouteBgmResolver.kt`. |
| 8.4.2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/NutonicChecklistScreens.kt` | Role: three explicit cards + perk strings (resources or `prompts/` bundle), not only `GameRolePicker` list. |
| 8.4.3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/NutonicChecklistScreens.kt` | `ShellDetailPlaceholder` / `FinalResultsWithLocalSummary` (~L152+ in shell): replace placeholder **final results** with tactical layout + AI vs truth + RANK CTA per `rules/07` #7. |
| 8.4.4 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/NutonicMainShell.kt` | INTEL / SETUP / PRO tab roots: implement **IMP-144** minimum sections (grouped SETUP, functional PRO strip per `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`). |

### 8.5 IMP-145 — Gameplay copy (no debug/release fork)

| # | File | Task |
|---|------|------|
| 8.5.1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/WorldMapGameplayScreen.kt` | Remove `SHOW_ENGINE_DEBUG_LABELS` **or** set behavior **identical** for all Gradle flavors: **never** show `HUMAN_PLAY` / `AI_RESOLVE` on player HUD (**AD-2**). |
| 8.5.2 | Same | Remove or rephrase engineering captions (~L625–L628, ranked lines ~L630–L635). |
| 8.5.3 | Same — `GameplayHudCard` | Cosmetic timer copy on **all** visible timer lines per §2.5; use string resources. |

### 8.6 IMP-146 — Share overlays (**AD-3**)

| # | File | Task |
|---|------|------|
| 8.6.1 | `commonMain` + `jsMain` / other `actual`s | Implement **loading → success / partial → error** UI for share; overlays **dismissible**; user may **navigate away**; optional background completion without blocking shell. |
| 8.6.2 | `ShareNutonicScorecard.js.kt` | If keeping `Boolean` return, document semantics (“handoff initiated” vs “finished”); prefer driving **§8.6.1** state machine from Promise callbacks where practical. |
| 8.6.3 | `RoundSuccessOverlay` (post-split **§8.0.2**) | Wire overlay flow; remove one-line-only feedback if it conflicts with **AD-3**. |

### 8.7 IMP-147 — Permissive merge + offline sync (**AD-1**)

| # | File | Task |
|---|------|------|
| 8.7.1 | `cache/ShippedManifestMerge.kt` | Implement **§2.6** and Phase **P5** step **5.1**: overlay shipped round truth when server cannot supply a playable row (includes many `VERSION_MISMATCH` + redacted cases); update `ShippedManifestMergeTest.kt`. |
| 8.7.2 | `screens/WorldMapGameplayScreen.kt` | Clear `nonRankedContentBlocked` when shipped supplies a round after merge; optional informational `manifestVersionNotice` per §2.4 (not blocking). |
| 8.7.3 | `leaderboard/` + `api/` usage | **Outbox or retry:** persist guess rows / `POST` payloads locally; flush when online (**AD-1**). |

### 8.8 IMP-051 / IMP-149 (IMP-148 out)

| # | File / area | Task |
|---|-------------|------|
| 8.8.1 | `composeResources/files/music/` | Replace silent / stub WAVs per `docs/SCREEN-MUSIC-SPEC.md` §3 (all build types). |
| 8.8.2 | **—** | **IMP-148:** no Paparazzi / CI screenshot work (**AD-5**). |
| 8.8.3 | Release runbook | **IMP-149:** manual `docs/PUBLISHABLE-UI-EXIT-CRITERIA.md` + store assets. |

---

## 9. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-21 | Initial plan: IMP-140–149 band, parameters, phases, manifest copy matrix. |
| 0.2 | 2026-04-21 | Removed Stitch submodule requirement; switched parity gate to vendored first-party contracts + gitignored `refs/stitch/`. |
| 0.3 | 2026-04-21 | Assessment baseline (§7); file-level resolution backlog (§8); §2.4/§2.6 merge-policy clarity; P1/P4/P5 corrections (`NutonicRoute.kt`, Web share, IMP-147 steps); HUD/timer note in §2.5. |
| 0.4 | 2026-04-21 | **§0.1** product decisions (**AD-1–AD-7**): permissive offline-first merge + guess sync; debug/release parity + CI→HF config; share overlay requirements; §2.7 refactors; **IMP-148** deferred; **IMP-147** / §2.6 rewritten; graph + §6 non-goals + §8 backlog updated. |
| 0.5 | 2026-04-21 | Added **§5.1 local-first guess sync outbox** implementation contract (payload shape, retry policy, idempotency, file-level landing points, and tests). |
| 0.6 | 2026-04-21 | **Implementation alignment:** SCAN hub extracted to **`com.nutonic.shell`**; **P2** acceptance and **P5** step **5.4** updated for **`NutonicColors`** + removed photo-gallery sample; catalog helper name **`refreshScanHubCatalog`**. |

---

*End of document.*
