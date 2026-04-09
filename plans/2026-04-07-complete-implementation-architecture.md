# NU:TONIC — Complete implementation architecture plan

**Date:** 2026-04-07  
**Authority:** This plan **implements** the binding constraints in `rules/00`–`rules/13`, `rules/GAME-ENGINE.md`, and `rules/README.md` (reading order and conflict resolution). It **extends** the backend-focused document `plans/2026-04-07-gradio-terramind-backend.md` with **end-to-end** client + server + contracts + delivery.

**Visual and UX references (non-runtime):** `refs/DESIGN.md`, `refs/stitch/nu_tonic_interface_design_specification.html`, per-screen `refs/stitch/<screen>/code.html` + `screen.png` (`rules/07-screens-checklist.md`).

**Conflict resolution (`rules/README.md`):** Product intent (`00`, `01`) overrides individual mockups. Tokens default to `refs/DESIGN.md`; stitch-only extras (e.g. Orbitron) require explicit mapping in theme code.

---

## 1. Goals and success criteria

| Goal | Rule source | Measurable outcome |
|------|-------------|---------------------|
| **Multiplatform parity** | `00-product-intent.md`, `03-kotlin-multiplatform-structure.md` | Same routes, game loop, and hydrated data on Android, iOS, Desktop, and Web (where in scope); differences only at platform ports (map, secure storage). |
| **Server authority** | `00`, `04`, `05`, `GAME-ENGINE.md` | Scores, zoom tier, VLM text, match outcome, leaderboard rows, and embedding-driven behavior come from the reference server; clients do not reimplement hidden game rules. |
| **Design fidelity** | `02-design-system.md`, `08-ux-and-performance-footguns.md` | Structure and hierarchy match stitch mocks; tokens and behaviors (glass, glow discipline, bottom bar indicator **above** icon) match DESIGN. |
| **Contract-first integration** | `05-networking-leaderboard.md` | OpenAPI (or equivalent) co-located with server; Kotlin `commonMain` DTOs match versioned `/api/v1/...` paths. |
| **No HTML-as-ship** | `00`, `09-html-vendoring-and-interface-stack.md` | Compose Multiplatform primary UI; stitch HTML is reference only; no production CDN-coupled UI. |
| **Engine semantics** | `10-terramesh-vlm-progressive-zoom-game-engine.md`, `GAME-ENGINE.md` | Street View / VLM / progressive zoom / multiplayer / **mandatory** AI marker phase (**cache-first**); TerraMesh/TerraMind optional as **labeled** `round_type`. |
| **Quality gate** | `11-vscode-testing-linting-and-ci.md` | `./gradlew quality test` and CI jobs green for agreed targets. |

---

## 2. Monorepo target layout

Illustrative tree (names may be adjusted; **boundaries** are normative):

```text
nutonic/                          # Gradle root (KMP client) — rules/03, 11
  shared/
    src/commonMain/kotlin/        # UI shell, theme, ViewModels, domain, API interfaces, DTOs
    src/androidMain/ ... iosMain/ ... jvmMain/ ... webMain|jsMain|wasmJsMain/
  androidApp/
  iosApp/                         # (or Xcode project consuming shared.framework)
  desktopApp/
  webApp/
  mapview-desktop/                # or absorbed into shared jvm map actual
server/                           # rules/12, plans/2026-04-07-gradio-terramind-backend.md
  pyproject.toml
  src/nutonic_server/
    main.py                       # FastAPI + mount_gradio_app
    api/                          # route modules
    services/                     # game state, VLM, TerraTorch, leaderboard store, hf_artifacts
    gradio_app/
  tests/
docs/
  openapi.yaml                    # rules/05 — single evolving artifact or generated
rules/                            # non-negotiable constraints
plans/                            # this file + backend plan
refs/                             # design + research reference (not shipped to clients)
```

**Process model (server):** One ASGI app: **FastAPI** owns `/api/*`; **Gradio** mounted at e.g. `/ops` for operator leaderboard view only (`12-python-gradio-terramind-server.md`). GPU-heavy **batch** work runs in **HF Jobs** (and optionally **Spaces ZeroGPU** for burst fill); the **match hot path** reads **precomputed AI guesses** and embeddings from a **local sync** of Hub Datasets (`13-client-cache-and-data-plane.md`, `plans/2026-04-07-gradio-terramind-backend.md` §6–6b).

### 2.1 Data plane: Jobs → Dataset → server → client (no Hub on device)

1. **Curate `location_id`s** using **`refs/terramind-geogen-main`** discipline (metadata, `geo_utils.haversine` for scoring parity) and **GeoGuessr-style** location datasets on Hugging Face (examples: [stochastic/random_streetview_images_pano_v0.0.2](https://huggingface.co/datasets/stochastic/random_streetview_images_pano_v0.0.2), [marcelomoreno26/geoguessr](https://huggingface.co/datasets/marcelomoreno26/geoguessr); larger corpora such as [ShirohAO/tuxun](https://huggingface.co/datasets/ShirohAO/tuxun) require separate compliance review).  
2. **HF Jobs** generate **known** artifacts: TiM/pooled embeddings, **`ai_lat` / `ai_lon`** (and `ruleset_version`, `model_version`), static hints metadata—**commit Parquet** to a **private Dataset**.  
3. **Server** syncs shards to disk, exposes **`GET /api/v1/cache/manifest`**, **`GET /api/v1/bundles/...`**, and uses **`AiGuessStore`** so **`AI_GUESS_PLACED`** is **always** satisfiable from cache when the pool row is covered (`GAME-ENGINE.md` §12.2).  
4. **Clients** persist responses **locally**; they **only** talk to the NU:TONIC server—**no `hf` CLI**, no Hub tokens (`13-client-cache-and-data-plane.md`). Optional **static assets** (pre-baked JSON/binary) may ship **in-repo** for first-run UX if product wants offline shells.

### 2.2 Auth default

- **Light or anonymous** play by default; enable **JWT** from **FastAPI** when product requires accounts (`05-networking-leaderboard.md`).

---

## 3. Layered architecture (client)

### 3.1 Presentation (`shared` / `commonMain`)

- **Single navigation graph** — sealed routes / typed destinations (`01-navigation-architecture.md`). Canonical tabs: **Home, Map, Play, Leaderboard, Settings**; stitch labels (SCAN / RANK / SQUAD) **map** to these routes in one enum with a one-line comment (`01`).
- **Shell** — bottom bar with elevated **Play** node (`02-design-system.md`); max **two** levels beyond tab roots for core flows; mode pickers as sheets/dialogs (`01`).
- **Screens** — implement checklist `07-screens-checklist.md` as composables: Splash, Authentication, Role selection, Dashboard, World map gameplay, Success overlay, Final results (with **API-hydrated** global ranks), Settings.
- **Overlays** — game launch (Solo / Multi / AI), glass **chat** over map (`GAME-ENGINE.md` §11, `02`, `08`).
- **Design system** — `NutonicTheme` (colors as semantic tokens from `refs/DESIGN.md`), `NutonicTypography` (Space Grotesk + Inter; Orbitron/monospace only for tactical HUD — `02`), optional scanline/grid overlay respecting **reduced motion** (`02`, `08`).
- **Strings** — centralized resource layer for localization (`07`).

### 3.2 State and use cases (`commonMain`)

- **ViewModels / presenters** — one per major flow or shared coordinator for match + round; consume repository interfaces only.
- **Reducers** — optional MVI for match event ordering; must handle reconnect and idempotent actions (`GAME-ENGINE.md` §14).
- **No platform APIs** in use-case layer (no `java.time`, no direct map SDK calls).

### 3.3 Data (`commonMain` + thin platform)

- **ApiClient** — Ktor client; engines configured per target (`03-kotlin-multiplatform-structure.md`).
- **Repositories** — `AuthRepository`, `MatchRepository`, `LeaderboardRepository`, `SettingsRepository`, **`ContentCacheRepository`** (manifest ETags, downloaded bundles, last-known leaderboard—`13-client-cache-and-data-plane.md`).
- **DTOs** — `kotlinx.serialization`; field names match OpenAPI (`05`).
- **Secure token storage** — expect/actual **when JWT enabled**; otherwise anonymous id only (`05`).
- **Mock mode** — compile-time or debug-only `MockApi`; **never** default in release (`05`).

### 3.4 Platform ports (`expect` / `actual`)

| Port | Responsibility | Rules |
|------|----------------|-------|
| **MapViewport** / `GameMapController` | Apply server `viewport_bounds`, tap-to-place, optimistic marker, optional peer ghosts | `04-maps-and-gameplay.md`, `GAME-ENGINE.md` §10 |
| **Biometric / QR** (if shipped) | Thin wrappers | Auth UX from stitch; secrets still server-validated |
| **Fonts** | Load Space Grotesk, Inter (and Orbitron if approved) per platform | `02` |
| **Imagery keys** | Build config / plist / env — **not** `commonMain` | `04` |

**Map engine matrix (document in one file, e.g. `docs/map-engines.md`):** Android (Google Maps or agreed), iOS (MapKit or agreed), Desktop (OSM / existing `mapview-desktop`), Web (MapLibre/Leaflet or Canvas fallback). All implement the **same** interface (`04`).

---

## 4. Layered architecture (server)

### 4.1 API surface (FastAPI)

- **Versioned REST** — `/api/v1/...` for auth, matches, rounds, guesses, hints, chat, leaderboard, **cache manifest / static bundles** (client hydration), health, config (`05`, `13`).
- **Realtime** — WebSocket (or SSE) channel for `ROUND_STARTED`, `ZOOM_CHANGED`, `VLM_MESSAGE`, `PLAYER_GUESS`, `AI_GUESS_PLACED`, `ROUND_RESOLVED` (`GAME-ENGINE.md` §14–15).
- **Idempotency** — client keys on guess and hint (`GAME-ENGINE.md` §14).
- **CORS** — explicit origins for web clients; `/ops` Gradio separate (`05`, `12`).

### 4.2 Core services

| Service | Role |
|---------|------|
| **GameStateService** | Match and round state machines (`GAME-ENGINE.md` §8); join-in-progress `sync_payload` |
| **DifficultyRegistry** | Easy/Medium/Hard profiles with published tunables (`GAME-ENGINE.md` §7) |
| **LocationPoolService** | Immutable pool entries: WGS84 truth, imagery handles, tags, `round_type`; **seed** from HF GeoGuessr-style datasets + `refs/terramind-geogen-main` metadata patterns (server/Job only) |
| **DatasetSyncService** | Pull Hub Dataset revisions → local Parquet index for `AiGuessStore` |
| **AiGuessStore** | **Primary** source for **`AI_GUESS`** coords on hot path (Jobs output); live TerraTorch optional |
| **VlmService** | Street View–style inputs → moderated text; timeouts and fallbacks (`GAME-ENGINE.md` §9, `06`) |
| **ZoomService** | Authoritative tier → `viewport_bounds`; no client-inferred tier (`10`, `GAME-ENGINE` §8.3) |
| **ScoringService** | Haversine km + breakdown (time, streak, role modifiers) (`GAME-ENGINE` §13, `10` geo_utils alignment) |
| **AiGuessPolicy** | Resolves **mandatory** AI marker: **read `AiGuessStore` first**; fall back to live TerraTorch/VLM only if allowed; never skip `AI_GUESS_PLACED` on normal resolve (`06`, `GAME-ENGINE` §12.2, `13`) |
| **LeaderboardStore** | Source of truth for ranks; same read path as Gradio (`05`, `12`) |
| **TerraMindService** (optional) | TerraTorch backbone / TiM; feature-flagged; pooled outputs (`06`, `12`, `plans/2026-04-07-gradio-terramind-backend.md`) |
| **HfArtifactsService** (optional) | Parquet manifests, Hub upload — not on critical latency path (`06`, `12`) |

### 4.3 Data stores

- **Transactional:** SQLite (reference) → Postgres (scale): matches, rounds, guesses, players, sessions.
- **Cache:** Redis optional for presence / rate limits.
- **Analytics:** Binned error heatmaps offline (pattern from `refs/terramind-geogen-main/scripts/plot_error_heatmap.py`) — not player PII (`10`).

### 4.4 Gradio (`/ops`)

- Read-only leaderboard (or admin-approved views) from **LeaderboardStore**; authenticated or network-restricted (`12`).

---

## 5. End-to-end flows (binding)

### 5.1 Onboarding (offline-capable UI only)

1. **Splash** → **Authentication** → **Role selection** → **Main shell** defaulting to **Home** (`01`, `07`).
2. Role persisted locally + registered with server when online (`05`).

### 5.2 Core play loop (online)

Aligns `04-maps-and-gameplay.md` with `GAME-ENGINE.md`:

1. Client creates/joins **match**; server starts **round** with `round_type`, `difficulty_profile_id`, `max_zooms`, initial **viewport_bounds**, initial **VLM** line.
2. Client renders **map** + **glass chat**; user places **guess** (optimistic ≤ ~100ms feedback — `08`).
3. Server advances **zoom tier** only via contract (chat-turn, hint, or hybrid — pick one in OpenAPI).
4. Humans **lock** guesses; server emits **`AI_GUESS_PLACED`** from **cache** (preferred) or live policy; **resolve** with `score_breakdown` and events.
5. Client shows **success overlay** then **final results**; **Global ranks** from `GET /leaderboard?role=...` (`05`, `07`).

### 5.3 Leaderboard hydration

- On screen enter + pull-to-refresh; loading / empty / error + retry with themed copy (`05`, `08` “UPLINK INTERRUPTED” pattern).
- **YOU** row requires stable `player_id` from server (`05`).

### 5.4 TerraMind / TerraMesh rounds (optional product mode)

- Separate **`round_type`** (e.g. `SATELLITE_TERRAMESH`) in API; never mix semantics with `STREETVIEW_VLM` in one client assumption (`10`, `12`, `GAME-ENGINE` §5.2, §18).
- TiM constraints: full band sets, `*_tim` models, documented `tim_modalities` (`06`, `12`).

---

## 6. API and event contracts (deliverables)

**Normative artifacts** (co-located with `server/`):

1. **openapi.yaml** — REST resources and models; bump on breaking changes (`05`).
2. **asyncapi.yaml** or **WebSocket event schema** appendix — event names and payloads (`GAME-ENGINE.md` §15).
3. **Engine versioning** — `engine_version` / `ruleset_version` in match and round payloads (`GAME-ENGINE.md` §6.2, §18).

**Kotlin:** Generate or hand-maintain serializers to match OpenAPI; CI check drift optional but recommended.

**TypeScript** (if any web shell): consume OpenAPI only for `/api/*`, not Gradio queue (`12`).

---

## 7. Security and compliance

- No secrets in `commonMain`; maps/Street View keys per platform (`04`).
- Rate limits on chat/hint; moderation on VLM output (`GAME-ENGINE.md` §16).
- Logs: trace ids, no raw tokens; ground truth obfuscation for non-admin (`GAME-ENGINE` §16).
- Ops Gradio behind auth or network policy (`12`).

---

## 8. Observability

- Distributed tracing: `match_id`, `round_id`, VLM latency (`GAME-ENGINE.md` §17).
- Client: non-user-facing technical logs + themed user errors (`05`).

---

## 9. Phased delivery plan (full game + parity)

Phases are **sequential** where noted; some client phases can overlap with server P0–P1 from `plans/2026-04-07-gradio-terramind-backend.md`.

| Phase | Scope | Exit criteria |
|-------|--------|----------------|
| **C0** | Repo hygiene: rename `rootProject.name`, migrate package from `example.imageviewer` to `com.nutonic.*`, strip or isolate unused imageviewer code (`03`) | Clean build all targets; CI still green (`11`) |
| **C1** | `NutonicTheme`, typography, bottom shell with **canonical** 5 tabs (stub content) (`01`, `02`) | Active indicator above icon; Play node elevated |
| **C2** | Screen shells for all `07` checklist (placeholder data) | Navigation depth rules satisfied (`01`) |
| **C3** | Settings persistence + accessibility toggles **wire to UI** (`02`, `08`) | Reduced motion / high contrast change rendering |
| **S0** | FastAPI OpenAPI + in-memory leaderboard + mock auth (`05`, backend plan P0) | Client can call real HTTP in debug |
| **S1** | Persistent DB + optional JWT + LeaderboardStore + Gradio `/ops` (backend plan P1) | Gradio rows == REST rows |
| **S1b** | Dataset sync + `AiGuessStore` + client cache manifest API (backend plan P1b) | AI guess from Parquet row for canned `location_id` |
| **C4** | Wire Auth + Leaderboard tabs to S1 | No hardcoded production leaderboard rows (`05`) |
| **C5** | `MapViewport` interface + **one** engine (e.g. Android) + desktop second (`04`) | Tap-to-place + slop + optimistic marker |
| **S2** | Match/round REST + WebSocket skeleton; state machine **LOBBY** → **IN_PROGRESS** (`GAME-ENGINE` §8) | Integration test with fake VLM |
| **S3** | VLM integration + progressive zoom + moderated hints (`GAME-ENGINE` §8–9) | Contract tests; fallback on timeout (`06`) |
| **C6** | Gameplay HUD + glass chat + server-driven bounds (`GAME-ENGINE` §10–11) | Parity on 2+ platforms |
| **S4** | Guess + **mandatory AI phase** (cache-backed) + scoring + leaderboard write (`GAME-ENGINE` §12–13) | End-to-end round; `AI_GUESS_PLACED` always in happy path |
| **C7** | Success + final results + share hook (platform actuals as needed) (`07`) | Results match server breakdown |
| **S5** | TerraTorch tiny/base embed path feature-flagged (backend plan P2–P3) | Documented `merge_method` + timeouts (`06`) |
| **S6** | HF Jobs → Dataset artifacts + server sync (backend plan P4–P5) | Schema + retention documented; clients still server-only |
| **C8** | iOS + Web map actuals if in scope (`04`, `03`) | Full parity matrix signed off |
| **Hardening** | Load tests, abuse limits, reconnect replay (`GAME-ENGINE` §14, §16) | SLO defined for match join and hint latency |

---

## 10. Testing strategy

| Layer | What | Rule / doc |
|-------|------|------------|
| **commonTest** | Serializers, reducers, client-side **preview** math only (not authoritative score) | `03`, `11` |
| **server tests** | State machine, haversine, idempotency, VLM mock | `GAME-ENGINE.md` §19 |
| **desktopTest** | Compose UI tests for shell / critical flows | `11` |
| **CI** | `quality`, `test`, APK, deb, web bundles, iOS framework | `11` |
| **Local PM2 threads** | Optional background Gradle runs (`test`, `quality`, `--continuous`, smoke build); logs under gitignored repo-root **`logs/`**; verified runbook **`docs/PM2_LOCAL_VERIFICATION.md`** | `11` §9 |
| **Contract** | Optional Pact or OpenAPI response tests between client and server | `05` |

---

## 11. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| **Nav drift** between stitch and spec | Enforce `01` canonical routes only; map labels in one enum |
| **Map parity** | Single `MapViewport` contract + documented engine matrix (`04`) |
| **VLM latency** | Queue limits, cached fallbacks, never block map thread (`06`, `GAME-ENGINE` §9.4) |
| **TiM misuse** | Server validates inputs; reject with 400 + docs (`06`, `12`) |
| **Leaderboard / Gradio drift** | Single `LeaderboardStore` (`05`, `12`) |
| **Web blur/glow cost** | Degraded solid surfaces (`02`, `09`) |
| **CDN / HTML temptation** | Default Compose-only path (`09`) |

---

## 12. Document map (rules ↔ implementation)

| Rule | Primary implementation home |
|------|----------------------------|
| `00-product-intent.md` | Whole stack |
| `01-navigation-architecture.md` | `shared` navigation module |
| `02-design-system.md` | `NutonicTheme`, components |
| `03-kotlin-multiplatform-structure.md` | Gradle modules, packages, tests |
| `04-maps-and-gameplay.md` | `MapViewport` + actuals |
| `05-networking-leaderboard.md` | Ktor, OpenAPI, repositories |
| `06-server-embedding-and-ai.md` | Python services, timeouts, fallbacks |
| `07-screens-checklist.md` | Composable screen list |
| `08-ux-and-performance-footguns.md` | QA checklist, motion/a11y |
| `09-html-vendoring-and-interface-stack.md` | No WebView-first; `kotlin-js-store` = build only |
| `10-terramesh-vlm-progressive-zoom-game-engine.md` | Server round types, zoom authority, haversine |
| `11-vscode-testing-linting-and-ci.md` | `.github/workflows`, Gradle tasks |
| `12-python-gradio-terramind-server.md` | `server/` layout, FastAPI + Gradio, Jobs, ZeroGPU |
| `13-client-cache-and-data-plane.md` | Local persistence, no Hub on clients, manifest/bundles |
| `GAME-ENGINE.md` | Server state machines, events, scoring, AI phase |

---

## 13. Next actions (ordered)

1. Approve **monorepo layout** §2 and **map engine matrix** for v1.  
2. Land **OpenAPI skeleton** + **FastAPI** P0 (leaderboard + health) per `plans/2026-04-07-gradio-terramind-backend.md`.  
3. Execute client **C0 → C2** in parallel with server **S0 → S1**.  
4. Implement **MapViewport** + **match WebSocket** before polishing visual effects.  
5. Freeze **zoom transition model** (A/B/C in `GAME-ENGINE.md` §8.3) in AsyncAPI.  
6. Run **full E2E** round in CI or nightly against dockerized server.

---

*This plan is a proposal for implementation sequencing; product may narrow Web target or TerraMind scope without changing the architectural rules above.*
