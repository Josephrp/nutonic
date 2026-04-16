# NU:TONIC — Complete implementation architecture plan

**Date:** 2026-04-07 (**solo-first / REST amendment:** 2026-04-12 — removed optional synchronized “live session” delivery phasing; aligned with **`docs/GAME-ENGINE.md` §14** and **`docs/INTEL-TAB-SPEC.md` §10**.)  
**Authority:** This plan **implements** the binding constraints in `rules/00`–`rules/13`, **`docs/GAME-ENGINE.md`**, and `rules/README.md` (reading order and conflict resolution). It **extends** the backend-focused document `plans/2026-04-07-gradio-terramind-backend.md` with **end-to-end** client + server + contracts + delivery.

**Game server scope:** The **`server/`** process is the **thin orchestrator** in **`plans/2026-04-07-game-server-thin-orchestrator.md`** (auth, ranked, leaderboards, **`httpx`** to **multiple** **`inference/*`** services and TerraMind workers). **TerraMind TiM / `generate`**, Street View viewpoint math, and LFM-VL tensors stay **off** that process; they live in **`inference/*`**, TerraMind workers, and **Jobs**, after **`data/scripts/`**-first hydration (`plans/2026-04-07-gradio-terramind-backend.md` **§2**, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` **§0.1–§0.2**).

**Visual and UX references (non-runtime):** **`docs/DESIGN.md`** (shipped product design system—including **vendored typography** for build/CI), **`refs/DESIGN.md`** (optional legacy token sheet **if** present—does **not** override `docs/DESIGN.md` for type), `refs/stitch/nu_tonic_interface_design_specification.html`, per-screen `refs/stitch/<screen>/code.html` + `screen.png` (`rules/07-screens-checklist.md`). **Precedence** matches the **Order of authority** paragraph in **`rules/README.md`**.

**Conflict resolution (`rules/README.md`):** Product intent (`00`, `01`) overrides individual mockups. **Semantic tokens, “Neon Relic” prose, and the full shipped type stack** (Space Grotesk + Inter + **Orbitron** for tactical/HUD) default to **`docs/DESIGN.md`** §3; **implementation** details (semantic tokens in Kotlin, font file paths, `NutonicTypography`, degraded blur fallbacks) live in **`rules/02-design-system.md`** and theme code. Use **`refs/DESIGN.md`** only when reconciling older stitch assets until mocks are refreshed—it does not override **`docs/DESIGN.md`** for typography.

---

## 1. Goals and success criteria

| Goal | Rule source | Measurable outcome |
|------|-------------|---------------------|
| **Multiplatform parity** | `00-product-intent.md`, `03-kotlin-multiplatform-structure.md` | Same routes, game loop, and hydrated data on Android, iOS, Desktop, and Web (where in scope); differences only at platform ports (map, secure storage). |
| **Client authority + optional server** | `00`, `04`, `05`, `docs/GAME-ENGINE.md` | **Gameplay** (ground truth for the round, distance/score math, guess eligibility) is **client-owned**; **non-ranked leaderboards default to local persist** (no score POST). The reference server may serve **cached hints**, POIs, optional bundles, and—if shipped—**optional** community leaderboard ingest; **no** cryptographic validation of non-ranked local rows. Optional server-driven zoom/VLM is **feature-flagged**, not the default trust path. |
| **Design fidelity** | `docs/DESIGN.md`, `02-design-system.md`, `08-ux-and-performance-footguns.md` | Structure and hierarchy match stitch mocks; tokens, **vendored typography**, and behaviors (glass, glow discipline, bottom bar indicator **above** icon) match **`docs/DESIGN.md`**. |
| **Contract-first integration** | `05-networking-leaderboard.md` | OpenAPI (or equivalent) co-located with server; Kotlin `commonMain` DTOs match versioned `/api/v1/...` paths. |
| **No HTML-as-ship** | `00`, `09-html-vendoring-and-interface-stack.md` | Compose Multiplatform primary UI; stitch HTML is reference only; no production CDN-coupled UI. |
| **Engine semantics** | `10-terramesh-vlm-progressive-zoom-game-engine.md`, `docs/GAME-ENGINE.md` | **Default social model:** async on **shared `map_id`** (**no lobbies**, solo-first submit)—**`docs/SOCIAL-AND-COMPETITION.md`**. **SCAN:** primary Mapbox still + **optional collapsible assists** (pre-cached Street View descriptions, **three-tier useful hints**, optional peer marker hint); **ranked forfeit** on assist use (`docs/RANKED-MODE.md`). Single-guess + narrative (`docs/NARRATIVE-AND-PROMPTS.md`). Optional progressive map zoom; **default-on, flag-off** AI marker phase (**cache-first**); TerraMesh / **TerraMind TiM** / **`terramind_v1_*_generate`** optional as **labeled** `round_type`. |
| **Quality gate** | `11-vscode-testing-linting-and-ci.md` | `./gradlew quality test` and CI jobs green for agreed targets. |

---

## 2. Monorepo target layout

Illustrative tree (names may be adjusted; **boundaries** are normative):

```text
nutonic/                          # Gradle root (KMP client) — rules/03, 11
  shared/
    src/commonMain/kotlin/        # UI shell, theme, ViewModels, domain, API interfaces, DTOs
    src/androidMain/ ... iosMain/ ... jvmMain/ ... webMain|jsMain/
  androidApp/
  iosApp/                         # (or Xcode project consuming shared.framework)
  desktopApp/
  webApp/
  mapview-desktop/                # or absorbed into shared jvm map actual
inference/                        # plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md — NOT game server
  streetview_pano_service/        # Google Street View stills / pano sampling (CPU)
  lfm_vl_hint_service/            # Standard LFM-VL → JSON Street View hint suggestions (GPU Space)
  lfm_vl_satellite_caption_service/  # Specialist LFM-VL → caption / VQA / grounding; Gradio demo + API (GPU Space)
  pro_materialization_service/    # PRO: Mapbox + Sentinel-2 fetch, downsample for on-device VLM + TiM contracts (CPU/IO); `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §5.3
server/                           # plans/2026-04-07-game-server-thin-orchestrator.md (+ rules/12)
  pyproject.toml                   # no torch/terratorch in thin layout
  src/nutonic_server/
    main.py                       # FastAPI + mount_gradio_app
    api/                          # auth, ranked, leaderboard, maps/manifests, POI, PRO proxy
    services/                     # jwt, official_client_registry, inference_client (httpx→inference/*), ranked_store, leaderboard_store, manifest_sync — NOT TerraTorch
    gradio_app/
  tests/
docs/
  openapi.yaml                    # rules/05 — single evolving artifact or generated
rules/                            # non-negotiable constraints
plans/                            # this file + backend plan
refs/                             # design + research reference (not shipped to clients)
```

**Process model (server):** One ASGI app: **FastAPI** owns `/api/*`; **Gradio** mounted at e.g. `/ops` for operator leaderboard view only (`12-python-gradio-terramind-server.md`). GPU-heavy **batch** work runs in **HF Jobs** (and optionally **Spaces ZeroGPU** for burst fill) on **inference or worker Spaces** — the **game server** only **syncs** Dataset shards / serves manifests and **calls** inference over HTTP (`13-client-cache-and-data-plane.md`, `plans/2026-04-07-gradio-terramind-backend.md` §6–6b, **`plans/2026-04-07-game-server-thin-orchestrator.md`**).

### 2.1 Data plane: Jobs → Dataset → server → client (no Hub on device)

1. **Curate `location_id`s** using **`refs/terramind-geogen-main`** discipline (metadata, `geo_utils.haversine` for scoring parity) and **location datasets** (e.g. Hugging Face GeoGuessr-style shards) plus **export scripts** that emit **downsampled Mapbox stills** per round (`docs/GAME-ENGINE.md` §9).  
2. **HF Jobs** generate **known** artifacts: **`tim_modality_outputs`** per forward (all **`tim_modalities`**, schema-capped — **`Coordinates`** supplies **`ai_lat` / `ai_lon`** when enabled), **`_generate`** clue renders when used, **`ruleset_version`**, **`model_version`**, static hints metadata—**commit Parquet** to a **private Dataset**.  
3. **Server** syncs shards to disk, exposes **`GET /api/v1/cache/manifest`**, **`GET /api/v1/bundles/...`**, and uses **`AiGuessStore`** so **`AI_GUESS_PLACED`** is **always** satisfiable from cache when the pool row is covered (`docs/GAME-ENGINE.md` §12.2).  
4. **Clients** persist responses **locally**; they **only** talk to the NU:TONIC server—**no `hf` CLI**, no Hub tokens (`13-client-cache-and-data-plane.md`). Optional **static assets** (pre-baked JSON/binary) may ship **in-repo** for first-run UX if product wants offline shells.

### 2.2 Auth default

- **Light or anonymous** play by default; enable **JWT** from **FastAPI** when product requires accounts (`05-networking-leaderboard.md`).

---

## 3. Layered architecture (client)

### 3.1 Presentation (`shared` / `commonMain`)

- **Single navigation graph** — sealed routes / typed destinations (`01-navigation-architecture.md`). **Five** shell tabs with tactical labels: **SCAN · INTEL · RANK · SETUP · PRO** (IDs `ScanHub`, `Intel`, `Rank`, `Setup`, `Pro`). **SCAN** merges former Map+Play hub; **RANK** is global leaderboard + pick `map_id` → play in **SCAN**; **SETUP** is settings; **PRO** is the **coordinate dashboard** (server materialization + optional TerraMind + **on-device** VLM layered UI — `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §3.1 initial entitlement). Document ID→label **once** in the route enum (`01`).
- **SCAN hub (social default)** — **Mission selection**, **map / level selection**, **per-map leaderboard slice**, and **entry into play** share **one hub surface** inside the **SCAN** tab (segments/sheets) so players never “join a lobby”—they **pick a published map** and compete via **aggregated rows** (`docs/SOCIAL-AND-COMPETITION.md`, `rules/05-networking-leaderboard.md`).
- **Shell** — bottom bar with elevated **SCAN** node by default (`02-design-system.md`, `01`); max **two** levels beyond tab roots for core flows; mode pickers as sheets/dialogs (`01`).
- **Screens** — implement checklist `07-screens-checklist.md` as composables: Splash, Role selection, **session bootstrap** (game-server token, **not** necessarily account UI), optional gated **Authentication** (accounts when shipped), Dashboard (**INTEL**), **SCAN** hub (map hub + entry to world map gameplay), World map gameplay, Success overlay, Final results (with **API-hydrated** ranks; **deeplink RANK** + `map_id`), Settings (**SETUP**), **PRO** per **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`**.
- **Overlays** — optional game launch (**solo-first**; any extra entry labels must **not** read as live PvP or rooms—`docs/SOCIAL-AND-COMPETITION.md`); optional glass **chat** over map (`docs/GAME-ENGINE.md` §11, `02`, `08`).
- **Design system** — `NutonicTheme` (colors as semantic tokens from **`docs/DESIGN.md`**), `NutonicTypography` (**Space Grotesk + Inter + Orbitron** for tactical/HUD per **`docs/DESIGN.md`** §3 and **`rules/02-design-system.md`**—vendored under KMP `composeResources`, no font CDN), optional scanline/grid overlay respecting **reduced motion** (`02`, `08`).
- **Strings** — centralized resource layer for localization (`07`).

### 3.2 State and use cases (`commonMain`)

- **ViewModels / presenters** — prefer a **map-hub coordinator** (mission → map → leaderboard → play) for the default **async `map_id`** model (`docs/SOCIAL-AND-COMPETITION.md`). **Round** state and phases live in **`commonMain`** per **`docs/GAME-ENGINE.md` §8.2**—**no** separate synchronized-opponent coordinator. Consume repository interfaces only.
- **Reducers** — optional MVI for **round / UI** event ordering in the client engine; **idempotent** actions for **REST** retries (`docs/GAME-ENGINE.md` §14).
- **No platform APIs** in use-case layer (no `java.time`, no direct map SDK calls).

### 3.3 Data (`commonMain` + thin platform)

- **ApiClient** — Ktor client; engines configured per target (`03-kotlin-multiplatform-structure.md`).
- **Repositories** — `AuthRepository`, **`LeaderboardRepository`** (per-`map_id` **required** for async comparison), **`MapsRepository`** or equivalent (list published `map_id`s), `SettingsRepository`, **`ContentCacheRepository`** (manifest ETags, downloaded bundles, last-known leaderboard—`13`); optional **`RankedRoundRepository`** (or equivalent) for **REST** ranked **start/submit** + ticket handles—**not** a push/stream channel (`docs/GAME-ENGINE.md` §14).
- **DTOs** — `kotlinx.serialization`; field names match OpenAPI (`05`).
- **Secure token storage** — expect/actual **when JWT enabled**; otherwise anonymous id only (`05`).
- **Mock mode** — compile-time or debug-only `MockApi`; **never** default in release (`05`).

### 3.4 Platform ports (`expect` / `actual`)

| Port | Responsibility | Rules |
|------|----------------|-------|
| **MapViewport** / `GameMapController` | Basemap + reference still + guess modal; optional server `viewport_bounds` when progressive zoom is on; tap-to-place, optimistic marker, optional peer ghosts | `04-maps-and-gameplay.md`, `docs/GAME-ENGINE.md` §10 |
| **Biometric / QR** (if shipped) | Thin wrappers | Auth UX from stitch; secrets still server-validated |
| **Fonts** | Load **Space Grotesk**, **Inter**, and **Orbitron** from repo-bundled assets per platform (same files CI packages—no runtime font CDN) | `docs/DESIGN.md` §3, `02` |
| **Imagery keys** | Build config / plist / env — **not** `commonMain` | `04` |

**Map engine matrix (document in one file, e.g. `docs/map-engines.md`):** Android (Google Maps or agreed), iOS (MapKit or agreed), Desktop (OSM / existing `mapview-desktop`), Web (MapLibre/Leaflet or Canvas fallback). All implement the **same** interface (`04`).

---

## 4. Layered architecture (server)

### 4.1 API surface (FastAPI)

- **Versioned REST** — `/api/v1/...` for auth, **maps**, **optional** per-map **community** leaderboard **`GET`/`POST`**, **optional POI** (including share-friendly ids), **cache manifest / static bundles** (client hydration), **ranked** round **start/submit** when shipped, health, config (`05`, `13`). **Non-ranked score POST is not required** for core play. **Normative:** player integration stays **HTTP (REST)** + **local engine state**—**no** player-surface push/stream “live session” API for core NU:TONIC (`docs/GAME-ENGINE.md` §14, `docs/SOCIAL-AND-COMPETITION.md`).
- **Idempotency** — client keys on guess and optional refresh (`docs/GAME-ENGINE.md` §14).
- **CORS** — explicit origins for web clients; `/ops` Gradio separate (`05`, `12`).

### 4.2 Core services

| Service | Role |
|---------|------|
| **GameStateService** | **Omit** for shipped product: **round** phases are **client-held** (`docs/GAME-ENGINE.md` §8.2). Server holds **ranked** secrets + tickets + verified rows via normal **REST** persistence—**not** a synchronized-opponent coordinator |
| **AssistRegistry** | Mission / **`assist_level`** metadata (replaces heavy Easy/Medium/Hard server registry—`docs/GAME-ENGINE.md` §7) |
| **LocationPoolService** | Immutable pool entries: WGS84 truth, **Mapbox still** refs, optional **`streetview_hint_pack`** / **`useful_hints`** (3 tiers), tags, `round_type`; **seed** from Dataset + export scripts + batch Street View / LFM-VL jobs (`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`) + `refs/terramind-geogen-main` metadata patterns (server/Job only) |
| **DatasetSyncService** | Pull Hub Dataset revisions → local Parquet index for `AiGuessStore` |
| **AiGuessStore** | **Primary** source for **`AI_GUESS`** coords on hot path — **`ai_lat`/`ai_lon`** hydrated from **TiM `tim_modality_outputs.Coordinates`** (preferred when enabled) and/or legacy **TerraMesh** / Jobs rows; live **TiM** / **`_generate`** optional |
| **ManifestBundleService** (or sync cron) | **Thin `server/`:** index **Dataset / CI** outputs and serve **`GET` manifests** with **`ETag` / `content_version`**; **large** clue bytes via **redirect / signed URL** to CDN or static bucket—**avoid** proxying multi‑MiB SCAN assets through the game Python process when possible (`docs/GAME-ENGINE.md` §9, `13`, **`plans/2026-04-07-game-server-thin-orchestrator.md`** §0.1) |
| **ProJobOrchestrator** | **`POST .../pro/jobs`**: **`httpx`** **control plane** only → **`inference/pro_materialization_service`** (all STAC/Mapbox/resample work **there**) → optional **`TERRAMIND_*`** with **handles** → persist **job status + signed `bundle_download_url` / caps-only JSON** for poll responses; **no** Sentinel custody, **no** `torch`, **no** mandatory in-process **`ProVisionBundle`** byte assembly (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`, **`plans/2026-04-07-game-server-thin-orchestrator.md`** §0.1, §1.6) |
| **ZoomService** | **Optional** — tier → `viewport_bounds` when server-assisted progressive zoom is enabled (`10`, `docs/GAME-ENGINE.md` §8.3) |
| **ScoringService** | **Ranked only** on thin game server — verified haversine vs server secret (`docs/RANKED-MODE.md`). **Non-ranked:** client remains source (`docs/GAME-ENGINE.md` §13); optional analytics mirror is out-of-scope unless OpenAPI adds it |
| **AiGuessPolicy** | Resolves **mandatory** AI marker: **read `AiGuessStore` first** (rows keyed by **`map_id`** / `content_version`, **`ai_lat`/`ai_lon`** from **TiM `Coordinates`** and/or TerraMesh); fall back to **HTTP call** to TerraMind **worker** / Jobs-backed cache only if allowed; never skip `AI_GUESS_PLACED` on normal resolve — **no in-process TerraTorch** on thin game server (`06`, `docs/GAME-ENGINE.md` §12.2, `13`, thin game server plan) |
| **LeaderboardStore** | Source of truth for ranks; same read path as Gradio (`05`, `12`) |
| **TerraMindService** (optional, **worker or Job path only**) | TerraMind **TiM** / **`_generate`** — **not** imported by thin `server/`; game server passes **`TERRAMIND_WORKER_URL`** jobs if needed (`06`, `12`, `plans/2026-04-07-gradio-terramind-backend.md`, thin game server plan) |
| **HfArtifactsService** (optional) | Parquet manifests, Hub upload — not on critical latency path (`06`, `12`) |

### 4.3 Data stores

- **Transactional:** SQLite (reference) → Postgres (scale): **sessions**, **ranked rounds** / tickets, **verified submits**, **players**/identity as needed, optional community aggregates. **Avoid** schema and **admin UI** copy that imply **live rooms** or **waiting for opponents**; if a legacy **`match_id`** column exists, treat it as **correlation only** (`docs/GAME-ENGINE.md` §6.2).
- **Cache:** Redis optional for presence / rate limits.
- **Analytics:** Binned error heatmaps offline (pattern from `refs/terramind-geogen-main/scripts/plot_error_heatmap.py`) (`10`).

### 4.4 Gradio (`/ops`)

- Read-only leaderboard (or admin-approved views) from **LeaderboardStore**; authenticated or network-restricted (`12`).

---

## 5. End-to-end flows (binding)

### 5.0 Social competition (default — no lobbies)

See **`docs/SOCIAL-AND-COMPETITION.md`**.

1. Player chooses **Human / Astronaut / Alien** (role tags **local leaderboard rows** and filters—not a lobby team assignment).
2. From the **SCAN** hub (mission + map list + leaderboard segment), player selects a **published `map_id`**—the same id every other player uses for that arena.
3. Client loads **round truth** from bundle/manifest (**client authority**); renders **basemap + reference still + guess modal** (`04`, `docs/GAME-ENGINE.md`).
4. Player submits **one guess**; client computes score/distance; **persists** to **local** per-**`map_id`** leaderboard (`05`, `13`). **Optional:** **`POST .../scores/self-report`** if product ships community sync; **optional** **`POST .../guesses/record`** for **non-ranked telemetry** (guess coords + client distance—**not** authoritative; **`docs/GAME-ENGINE.md` §12.3**).
5. **Markers (`docs/GAME-ENGINE.md` §10.1):** **self** pin after lock-in; **AI** marker **after** human phase (`AI_GUESS` / results) from cached `ai_lat`/`ai_lon`; **peer** marker **only** after **Reveal uplink**. **Non-ranked:** narrative / SCAN hints are **orthogonal** to reveal. **Ranked:** peer reveal **forfeits** verified placement—**`POST .../forfeit-reveal`** or **hide** peer reveal in UI until the server ships it (`docs/RANKED-MODE.md` §4).
6. When the product ships **optional** community **`GET .../leaderboard`**, that endpoint shows **aggregated** remote rows for the **`map_id`**; otherwise the UI stays on **device-local** history. **Human vs Human**, **Human vs Alien**, etc. are **presentation dimensions**—not proof of pairwise live duels unless product adds that field explicitly.

**POI share:** optional **`POST .../poi`** returns a stable **`poi_id`** (or client-generated id registered server-side) so **share links** can deep-link into the map hub (`05`).

### 5.1 Onboarding (offline-capable UI only)

1. **Splash** → **Role selection** → **Main shell** defaulting to **SCAN**; **Authentication** only when entering **ranked** play, **Mode B** writes, or optional account — not a wall before casual shell (`01`, `07`, `05`).
2. Role persisted locally + registered with server when online (`05`).

### 5.2 Core play loop (online)

**Default:** continues **§5.0** — **SCAN** hub → play → **local** leaderboard update → **optional** **`GET`** community/reference when configured (`05`, `07`); **RANK** for map pick and post-results deep link (`01`). **No** parallel “live session” or synchronized multiplayer overlay in current product scope (`docs/GAME-ENGINE.md` §8.1).

### 5.3 Leaderboard hydration

- On screen enter + pull-to-refresh; loading / empty / error + retry with themed copy (`05`, `08` “UPLINK INTERRUPTED” pattern).
- **“YOU” row:** use **local session id** / last submit handle for **open** builds; prefer **stable server-issued** subject when JWT accounts exist (`rules/05-networking-leaderboard.md` §Auth and identity).

### 5.4 TerraMind / TerraMesh rounds (optional product mode)

- Separate **`round_type`** (e.g. `SATELLITE_TERRAMESH`) in API; never mix semantics with `STREETVIEW_VLM` in one client assumption (`10`, `12`, `docs/GAME-ENGINE.md` §5.2, §18).
- TiM constraints: full band sets, `*_tim` models, documented `tim_modalities` (`06`, `12`).  
- **Generation** constraints: **`FULL_MODEL_REGISTRY`**, `*_generate`, `output_modalities`, same input-band completeness (`06`, `12`).

---

## 6. API and event contracts (deliverables)

**Normative artifacts** (co-located with `server/`):

1. **openapi.yaml** — REST resources and models; bump on breaking changes (`05`).
2. **Optional:** short **`docs/engine-events.md`** (or OpenAPI **x-** notes) listing **in-process** client/engine event names for telemetry/UI parity (`docs/GAME-ENGINE.md` §15)—**not** a wire protocol and **not** a substitute for REST contracts.
3. **Engine versioning** — `engine_version` / `ruleset_version` on **round** payloads (`docs/GAME-ENGINE.md` §6.2, §18).

**Kotlin:** Generate or hand-maintain serializers to match OpenAPI; CI check drift optional but recommended.

**TypeScript** (if any web shell): consume OpenAPI only for `/api/*`, not Gradio queue (`12`).

---

## 7. Build and config hygiene

- No API **keys** in `commonMain`; Mapbox / provider keys in build config or server env (`04`).
- Ops **`/ops`** Gradio may be network-restricted (`12`).

---

## 8. Observability

- Distributed tracing: **`round_id`**, optional **`match_id`** (correlation **only**), bundle load latency (`docs/GAME-ENGINE.md` §17).
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
| **C4** | Wire gated **Auth** + **RANK** tab (and **SCAN**-embedded leaderboard) to S1 | No hardcoded production leaderboard rows (`05`); **final results → RANK** + `map_id` (`01`) |
| **C5** | `MapViewport` interface + **one** engine (e.g. Android) + desktop second (`04`) | Tap-to-place + slop + optimistic marker |
| **S1c** | **Map-centric optional API:** `GET /api/v1/maps`, optional `GET /api/v1/maps/{map_id}/leaderboard`, optional `POST /api/v1/.../scores/self-report`, optional `POST /api/v1/.../poi` + **share** metadata (`docs/SOCIAL-AND-COMPETITION.md`, `05`) — **normative paths are versioned**; implement from **`docs/openapi.yaml`**, not unversioned shorthand | **Core** play uses **local** boards; **async** server-visible ranks only when community paths ship |
| **S3** | **Bundle + manifest** integration + optional progressive zoom (`docs/GAME-ENGINE.md` §8–9) | Contract tests; fallback on missing assets (`06`) |
| **C6** | Gameplay HUD + optional glass chat + optional server-driven bounds (`docs/GAME-ENGINE.md` §10–11) | Parity on 2+ platforms |
| **S4** | Guess + **mandatory AI phase** (cache-backed) + scoring + leaderboard write (`docs/GAME-ENGINE.md` §12–13) | End-to-end round; `AI_GUESS_PLACED` always in happy path |
| **C7** | Success + final results + share hook (platform actuals as needed) (`07`) | **Non-ranked:** on-screen distances/scores/ranks match **`commonMain`** resolution + **local** leaderboard write; **ranked:** match **server-returned** verified payload. Optional community **`GET`** slices must not be treated as replacing local math unless product merges them with labels. |
| **S5** | TerraMind **TiM** + optional **`_generate`** tiny/base paths feature-flagged (backend plan P2–P2b–P3) | Documented `merge_method` / `output_modalities` + timeouts (`06`) |
| **S6** | HF Jobs → Dataset artifacts + server sync (backend plan P4–P5) | Schema + retention documented; clients still server-only |
| **C8** | iOS + Web map actuals if in scope (`04`, `03`) | Full parity matrix signed off |
| **Hardening** | Load tests on **optional** community **`POST`** + POI; **REST** retry/idempotency behavior (`docs/GAME-ENGINE.md` §14) | SLO defined for optional leaderboard fetch + manifest latency |

---

## 10. Testing strategy

| Layer | What | Rule / doc |
|-------|------|------------|
| **commonTest** | Serializers, reducers, client-side **preview** math only (not authoritative score) | `03`, `11` |
| **server tests** | State machine, haversine, idempotency, VLM mock | `docs/GAME-ENGINE.md` §19 |
| **desktopTest** | Compose UI tests for shell / critical flows | `11` |
| **CI** | `quality`, `test`, APK, deb, web bundles, iOS framework | `11` |
| **Local PM2 verification** | **Mandatory** before PR/merge for **`nutonic/**`**: §9.2 in `11` (`nutonic-ci-local` + conditional `nutonic-build-verify`); logs under gitignored **`logs/`**; runbook **`docs/PM2_LOCAL_VERIFICATION.md`** | `11` §9 |
| **Contract** | Optional Pact or OpenAPI response tests between client and server | `05` |

---

## 11. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| **Nav drift** between stitch and spec | Enforce `01` canonical routes only; map labels in one enum |
| **Map parity** | Single `MapViewport` contract + documented engine matrix (`04`) |
| **VLM latency** | Queue limits, cached fallbacks, never block map thread (`06`, `docs/GAME-ENGINE.md` §9.4) |
| **TiM misuse** | Server validates inputs; reject with 400 + docs (`06`, `12`) |
| **Leaderboard / Gradio drift** | Single `LeaderboardStore` (`05`, `12`) |
| **Web blur/glow cost** | Degraded solid surfaces (`02`, `09`) |
| **CDN / HTML temptation** | Default Compose-only path (`09`) |
| **False “live PvP” cues** | Shell + INTEL copy stay **solo / async** (`docs/INTEL-TAB-SPEC.md` §10); **no** player push channel in architecture docs |

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
| `06-server-vlm-tim-and-on-device-ml.md` | VLM, TerraMind **TiM** and **generation**, on-device ML, timeouts, fallbacks |
| `07-screens-checklist.md` | Composable screen list |
| `08-ux-and-performance-footguns.md` | QA checklist, motion/a11y |
| `09-html-vendoring-and-interface-stack.md` | No WebView-first; `kotlin-js-store` = build only |
| `10-terramesh-vlm-progressive-zoom-game-engine.md` | Server round types, zoom authority, haversine |
| `11-vscode-testing-linting-and-ci.md` | `.github/workflows`, Gradle tasks |
| `12-python-gradio-terramind-server.md` | `server/` layout, FastAPI + Gradio, Jobs, ZeroGPU |
| `13-client-cache-and-data-plane.md` | Local persistence, no Hub on clients, manifest/bundles |
| `docs/GAME-ENGINE.md` | Client engine, **solo-first** **round** lifecycle, **in-process** events, **REST** networking norms, scoring, AI phase |
| `docs/SOCIAL-AND-COMPETITION.md` | Async competition by `map_id`, no lobbies, POI share, roles vs leaderboards |

---

## 13. Next actions (ordered)

1. Approve **monorepo layout** §2 and **map engine matrix** for v1 — **matrix + v1 parity direction:** [`docs/map-engines.md`](../docs/map-engines.md); **product flags, PRO day-one, all tabs, `/api/v1`, optional server `features`:** [`plans/2026-04-13-product-flags-v1.md`](2026-04-13-product-flags-v1.md) (sign-off tables in both files).  
2. Land **OpenAPI skeleton** + **FastAPI** P0 (leaderboard + health) per `plans/2026-04-07-gradio-terramind-backend.md`.  
3. Execute client **C0 → C2** in parallel with server **S0 → S1**.  
4. Implement **MapViewport** + **per-map leaderboard REST** (S1c), then **bundle + manifest** (S3) — **scripted shipped content** (stills, coordinate-tier hints, optional Street View + LFM-VL batches, `prompts/` serialization, **embedded** non-ranked manifest vs **ranked clue packs** without golden on device): [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](2026-04-14-shipped-cache-narrative-hint-pipeline.md).  
5. If shipping progressive zoom, freeze **zoom transition model** (A/B/C in `docs/GAME-ENGINE.md` §8.3) in **OpenAPI** or a short **ADR**.  
6. Run **full E2E** round in CI or nightly against dockerized server.

---

*This plan is a proposal for implementation sequencing; product may narrow Web target or TerraMind scope without changing the architectural rules above.*
