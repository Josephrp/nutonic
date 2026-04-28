# NU:TONIC PRO Mini-Apps Master Implementation Plan

**Date:** 2026-04-22  
**Scope:** End-to-end implementation plan for PRO offerings built on:
- Remote TerraTorch TiM prediction service(s)
- Existing `pro_materialization_service`
- On-device and/or server-side LFM-VL synthesis services

This plan is organized into **projects -> activities -> file-level tasks -> line-level subtasks** and prioritizes current footguns first.

---

## 0) Program outcomes

### Product outcomes
1. Ship a reliable PRO job pipeline (true async semantics, persistent state, resilient health policy).
2. Ship first PRO mini-app suite:
   - FireWatch (wildfire)
   - OceanScout (ship detection and maritime activity intelligence)
   - LandShift (land use / land cover change)
   - FloodPulse (water expansion/change)
   - Brief Composer (cross-app synthesis)
3. Produce machine + human outputs from the same run:
   - TiM artifacts and overlays
   - LFM-VL narrative and action summary
   - Shareable map-ready frames
4. **Map-first AOI entry:** Users set the PRO analysis center **by interacting with a map** (tap / drag pin, pan, zoom); manual lat/lon fields remain as an **advanced / accessibility** path that stay in sync with the pin (see §15.19, P5.1-T2, P5.1-T5).

### Engineering outcomes
1. Remove known orchestration and security footguns.
2. Keep OpenAPI, server models, and Kotlin DTOs in sync.
3. Add testable contracts for each mini-app profile and output bundle.

### 0.1 Repository implementation baseline (verified 2026-04-24)

| Surface | Current state in repo | Risk if unchanged |
|---|---|---|
| PRO job lifecycle (`server/src/nutonic_server/main.py`) | In-memory `_pro_job_status` and `_pro_job_materialization`; create route performs worker call inline; poll route mutates `queued -> completed` | State loss on restart, incorrect async semantics, racey user UX |
| PRO contracts (`docs/openapi.yaml`, `server/schemas.py`) | `ProJob*` exists but minimal fields and pseudo-queue semantics | Mini-app outputs cannot be typed or versioned safely |
| Kotlin API (`NutonicApiModels.kt`, `NutonicApiClient.kt`) | No typed PRO job request/response models or client methods | UI cannot integrate with stable contracts; ad hoc JSON risk |
| PRO tab UI (`NutonicMainShell.kt`) | Placeholder `ProTabRoot` with local-only probe string and no backend polling UX | Ship blocker for real PRO workflows |
| Worker request integrity (`inference/*/inference_hmac.py`) | Signature + timestamp skew checks implemented, but nonce replay cache missing | Signed requests can be replayed within skew window |
| STAC loaders (`pro_materialization_service` vs `terramind_tim_local`) | Near-duplicate logic with drift-prone divergence (`include_scl`, errors, params) | Subtle modality mismatch bugs and harder maintenance |
| TiM profile analytics (`terramind_tim_local`) | Emits generic modality outputs, no profile-normalized analytics blocks | Mini-apps cannot rely on stable machine-readable fields |
| Gameplay boundary (`AiGuessStore`) | Correctly map-scoped today, but PRO integration path is still undefined | Easy to accidentally persist ad hoc PRO coordinates as gameplay truth |

### 0.2 Critical footguns and unobvious logical risks to close in W0-W2

1. **Pseudo-async control plane drift:** if `POST /api/v1/pro/jobs` keeps synchronous side effects, queue semantics and SLA reporting are misleading.
2. **Replay window abuse:** HMAC without nonce memory is integrity theater under repeated capture/replay.
3. **Ocean heatmap bias:** raw detection counts overstate busy lanes where observation frequency is higher (cloud-free revisit bias); outputs must be normalized by valid-observation coverage.
4. **Pseudo-SAR overclaim:** TiM-generated pseudo-SAR from optical scenes is useful but not equivalent to true SAR; UX and brief text must mark confidence/evidence class explicitly.
5. **Water-mask edge clipping:** naive LULC `water` masks can remove harbor/near-shore vessels; shoreline buffer and morphology policy must be versioned.
6. **PRO-to-gameplay contamination:** never write ad hoc PRO `Coordinates` into `AiGuessStore` unless a `map_id`-bound registration path is explicit in OpenAPI.

---

## 1) Delivery waves

| Wave | Goal | Exit criteria |
|---|---|---|
| W0 | Contract freeze + risk gates | OpenAPI and schema updates merged; footgun acceptance criteria written |
| W1 | Control-plane hardening | Persistent PRO jobs + correct status lifecycle + no poll-side effects |
| W2 | Security and worker consistency | Replay-safe HMAC on workers; aligned STAC loading behavior |
| W3 | Analytics primitives | TiM outputs normalized into profile-ready analytics payloads + observation-quality metadata |
| W4 | PRO UI + API wiring | Real PRO dashboard + Kotlin API methods + status polling UX + **map-based center selection** (§15.19) on every supported target |
| W5 | Mini-app verticals | FireWatch + LandShift + OceanScout + FloodPulse + Brief Composer |
| W6 | Reliability and launch | Perf/soak tests, observability, runbooks, rollout flags |

---

## 2) Project P0 - Contract and architecture freeze

### Activity P0.1: Align PRO API contracts before implementation

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P0.1-T1 | `docs/openapi.yaml` | `449`, `472`, `870`, `907`, `939` | 1. At `/api/v1/pro/jobs` and `/api/v1/pro/jobs/{job_id}`, change semantics from pseudo-queue to true async (`queued/running/completed/failed`).<br>2. Expand `ProJobStatusOut` with `status_reason`, `started_at`, `finished_at`, `progress_pct`, `profile`, `analysis_artifacts`, `brief_artifacts`.<br>3. Keep backwards fields (`materialization_id`, `cache_key`) but mark as compatibility fields. | API contract explicitly models async lifecycle and mini-app profile outputs. |
| P0.1-T2 | `server/src/nutonic_server/schemas.py` | `150-179` | 1. Update `ProJobCreateIn` for `analysis_profile` enum (`wildfire`, `oceanscout_ship_detection`, `land_use_change`, `flood_pulse`, `brief_only`) and accept `vessel_monitoring` as compatibility alias.<br>2. Expand `ProJobCreateOut` and `ProJobStatusOut` to mirror OpenAPI changes exactly.<br>3. Add Pydantic models for typed artifact refs instead of raw free-form dicts where possible. | OpenAPI and runtime schemas are isomorphic. |
| P0.1-T3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiModels.kt` | `1-206` | 1. Add `ProJobCreateIn`, `ProJobCreateOut`, `ProJobStatusOut`, `ProArtifactRef`, `ProJobProfile` models.<br>2. Keep nullable fields for compatibility with older servers.<br>3. Add serializer-safe enums with fallback handling for unknown future profile values. | Kotlin DTOs decode current and next contract versions safely. |
| P0.1-T4 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiClient.kt` | `33-347` | 1. Add methods: `postProJob(...)`, `getProJob(jobId, ...)`, `cancelProJob(...)` (if endpoint added).<br>2. Reuse existing `decodeResponse` path and map feature-disabled handling for `pro_jobs`.<br>3. Add retry/backoff utility for status polling. | Client can create and poll PRO jobs through typed methods only. |
| P0.1-T5 | `docs/openapi.yaml` + `docs/pro-mini-apps/OCEANSCOUT.md` (new) | `449`, `870` | 1. Define typed OceanScout artifacts: `vessel_candidates`, `lane_heatmap`, `incursion_events`, `observation_coverage`, `evidence_level`.<br>2. Add claim-safety fields (`confidence`, `notices`, `limitations`) to prevent "illegal activity detected" wording from EO-only signals.<br>3. Include explicit semantics for base-model-vs-TiM comparison overlays (green vs blue in demo mode). | OceanScout outputs are contract-safe, explainable, and legally conservative. |

### Activity P0.2: Route and screen topology for mini-apps

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P0.2-T1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/navigation/NutonicRoute.kt` | `28-46`, `133-158` | 1. Extend `ShellDetail` with dedicated routes: `ProFireWatch`, `ProOceanScout`, `ProLandShift`, `ProFloodPulse`, `ProBriefComposer`.<br>2. Add token encode/decode mappings after current `pro` token handling.<br>3. Preserve backwards token `pro` for entry dashboard route. | Typed routing supports each mini-app without ad hoc strings. |
| P0.2-T2 | `rules/07-screens-checklist.md` | N/A | 1. Add explicit PRO mini-app screen checklist entries.<br>2. Add acceptance criteria for "no placeholder in production route".<br>3. Add checklist row: **PRO dashboard must offer map-based center selection** (primary) + optional numeric fields (advanced). | Checklist reflects shipping PRO surface, not placeholder shell. |
| P0.2-T3 | `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` | new § | 1. Document **map-first coordinate workflow**: basemap, pin placement, zoom ↔ effective `bbox_half_km` / `mapbox_zoom` mapping, and sync with `center_lat`/`center_lon` sent to `POST /api/v1/pro/jobs`.<br>2. Note platform matrix (`rules/04-maps-and-gameplay.md`, `docs/map-engines.md`): reuse **`MapViewport`** patterns; Web may use simplified picker until parity.<br>3. Accessibility: manual fields + screen-reader labels for pin coordinates. | PRO orchestration spec matches shipped UX; no doc-only WGS84 typing as the only path. |

---

## 3) Project P1 - PRO control plane hardening (highest priority)

### Activity P1.1: Replace faux queue semantics with real persisted jobs

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P1.1-T1 | `server/src/nutonic_server/main.py` | `59-60` | 1. Remove `_pro_job_status` and `_pro_job_materialization` globals.<br>2. Inject `ProJobStore` dependency (sqlite-backed first) through app startup/deps.<br>3. Add bounded retention policy (TTL + cleanup job). | No process-local ephemeral job store for PRO status. |
| P1.1-T2 | `server/src/nutonic_server/main.py` | `424-504` | 1. `POST /api/v1/pro/jobs` should only validate + enqueue + return `queued`.<br>2. Move worker invocation to background worker loop (thread/task/worker process) with explicit state transitions (`queued -> running -> completed/failed`).<br>3. Replace `all(origins healthy)` gate with capability-aware policy (`required_origins`, `optional_origins`). | Create route is non-blocking and lifecycle is accurate. |
| P1.1-T3 | `server/src/nutonic_server/main.py` | `506-534` | 1. Remove poll-time mutation (`_pro_job_status[job_id] = "completed"`).<br>2. Status route becomes pure read with deterministic payload.<br>3. Populate `bundle_download_url` when artifacts are published. | Polling never mutates job state. |
| P1.1-T4 | `server/src/nutonic_server/settings.py` | `107-143` | 1. Add settings for `pro_job_backend`, `pro_job_database_url`, `pro_required_origins`, `pro_optional_origins`, `pro_job_ttl_seconds`.<br>2. Add defaults suitable for local/dev and safe production failure behavior. | Config supports persistent jobs and explicit health policy. |
| P1.1-T5 | `server/src/nutonic_server/deps.py` | N/A | 1. Provide singleton accessors for `ProJobStore` and `ProJobRunner`.<br>2. Ensure clean startup/shutdown hooks. | Store/runner lifecycle is framework-managed. |
| P1.1-T6 | `server/src/nutonic_server/pro_jobs_store.py` (new) | new file | 1. Lines `1-80`: define `ProJobRecord`, `ProArtifactRecord`, `ProJobStore` protocol.<br>2. Lines `81-220`: implement `SqliteProJobStore` with indexes on status and timestamps.<br>3. Lines `221-280`: cleanup and migration helpers. | Durable store with tested CRUD and status updates. |
| P1.1-T7 | `server/src/nutonic_server/pro_jobs_runner.py` (new) | new file | 1. Lines `1-120`: dequeue/claim loop, idempotent claim transitions.<br>2. Lines `121-260`: invoke materialization/TiM/LFM stages with per-stage retries and terminal failure codes.<br>3. Lines `261-340`: write artifacts and final status atomically. | Separate runner handles execution; API remains thin. |

### Activity P1.2: Control-plane tests for lifecycle and failure modes

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P1.2-T1 | `server/tests/test_pro_job_materialize.py` | `24`, `94`, `70-120` | 1. Replace current immediate-call assumptions with enqueue + async progression tests.<br>2. Add tests for `running`, `completed`, `failed`, and retry-exhausted states.<br>3. Add test: optional-origin unhealthy still allows run when required origin is healthy. | Tests match true runtime semantics. |
| P1.2-T2 | `server/tests/test_inference_client.py` | existing file | 1. Add matrix tests for per-origin probe policy evaluation.<br>2. Add timeout and partial-health behavior tests. | Health gating behavior is explicit and locked. |

---

## 4) Project P2 - Security and worker consistency

### Activity P2.1: Add nonce replay protection to inbound HMAC middleware

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P2.1-T1 | `inference/pro_materialization_service/src/pro_materialization_service/inference_hmac.py` | `30-61`, `64-70` | 1. Add nonce cache check inside `verify_inbound_hmac` after signature verification.<br>2. Reject duplicate nonce within skew/TTL window with deterministic error code.<br>3. Add configurable nonce TTL and max cache size. | Replay within skew window is blocked. |
| P2.1-T2 | `inference/streetview_pano_service/src/streetview_pano_service/inference_hmac.py` | `31-69`, `72-80` | 1. Apply same nonce replay mechanism to stay protocol-consistent.<br>2. Keep canonical string unchanged to preserve client compatibility. | Both worker families enforce identical anti-replay behavior. |
| P2.1-T3 | `inference/*/tests/test_pro_inbound_hmac.py` and streetview HMAC tests | `24`, `34`, `47` | 1. Add test: first signed request accepted, replayed nonce rejected.<br>2. Add expiry-window test for nonce eviction behavior. | Replay protection covered by tests. |

### Activity P2.2: Align STAC loader behavior across services

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P2.2-T1 | `inference/pro_materialization_service/src/pro_materialization_service/geospatial/s2_stac_load.py` | `101`, `258` | 1. Extract shared STAC load primitives into a common module to avoid divergence.<br>2. Preserve current behavior for cloud filtering and scaling but centralize implementation. | Single source of truth for STAC patch loading. |
| P2.2-T2 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/s2_stac.py` | `104`, `217`, `227` | 1. Migrate to shared STAC core or import the shared utility layer.<br>2. Keep package-level optional dependency handling. | TiM local runner and materialization service are behaviorally aligned. |
| P2.2-T3 | `inference/pro_materialization_service/src/pro_materialization_service/geospatial/asset_policy.py` | `19-38` | 1. Add explicit profile-to-mode matrix validation (wildfire, oceanscout_ship_detection, land_use, flood).<br>2. Keep current mode matrix as base constraints. | Profile contracts cannot request impossible mode combinations. |
| P2.2-T4 | `inference/pro_materialization_service/src/pro_materialization_service/geospatial/mapbox_static.py` | `17-20`, `77-145` | 1. Externalize attribution string into config constant and include source/license metadata in artifact manifest.<br>2. Add timeout/retry budget settings by profile. | Mapbox outputs are policy-compliant and traceable. |

---

## 5) Project P3 - TiM analytics primitives for mini-apps

### Activity P3.1: Extend TiM pipeline outputs into profile-ready analytics

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P3.1-T1 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/run.py` | `45-55`, `85-112`, `144-200`, `288-378` | 1. Add `analysis_profile` routing in export row assembly.<br>2. Compute normalized analytics sections by profile (`burn_change`, `water_change`, `land_transition`, `vessel_candidates`).<br>3. Emit stable confidence fields and threshold metadata in each section. | TiM export rows carry profile-aware analytics, not only raw modality dumps. |
| P3.1-T2 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/serialize.py` | `99-155` | 1. Add compact schema blocks for profile summaries.<br>2. Keep full-mode introspection for debug but provide product-mode deterministic keys for API contracts. | API consumers receive stable JSON shape per profile. |
| P3.1-T3 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/inputs_build.py` | `90-143`, `197-265` | 1. Add multi-temporal input support (`t0`, `t1`, optional `t2`) for change detection profiles.<br>2. Share STAC retrieval across temporal slices where possible to reduce network cost.<br>3. Add profile-specific defaults (window size, cloud ceiling, modality set). | Inputs support temporal change workflows without ad hoc scripts. |
| P3.1-T4 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/geoguessr_materialize.py` | `238-355`, `357-402` | 1. Add materialized visual overlays per profile (change heatmaps, land transition palettes, candidate points).<br>2. Emit a profile artifact index JSON to ease UI rendering. | Materialized outputs are directly consumable by PRO screens. |

### Activity P3.2: Stabilize TerraTorch patch surface

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P3.2-T1 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/terramind_patches.py` | `97-106`, `115-165`, `167-203` | 1. Add patch capability/version checks with explicit warnings and fail-fast mode in CI.<br>2. Emit patch diagnostics in `/health` and export metadata.<br>3. Add test fixtures that catch upstream API drift. | Patch behavior is observable and upgrade-safe. |
| P3.2-T2 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/space_api.py` | `24-30`, `83-86` | 1. Add `/v1/tim/infer` alias with profile-first payload contract while keeping `/v1/tim/export` compatibility.<br>2. Include patch/version diagnostics in health payload. | Service endpoint naming aligns with product language and health diagnostics. |

---

## 6) Project P4 - LFM-VL synthesis and frame-to-brief pipeline

### Activity P4.1: Add profile-aware briefing endpoints

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P4.1-T1 | `inference/lfm_vl_hint_service/src/lfm_vl_hint_service/main.py` | `66-87` | 1. Add new endpoint `/v1/pro/brief/fuse` that accepts profile + TiM summary + artifact refs.<br>2. Keep existing caption routes unchanged for backward compatibility. | PRO briefing endpoint exists with typed request/response. |
| P4.1-T2 | `inference/lfm_vl_hint_service/src/lfm_vl_hint_service/dispatch.py` | `25-37`, `40-52` | 1. Add profile prompt templates and response guards for wildfire/oceanscout/land/flood narratives.<br>2. Enforce "no invented certainty" policy via output schema constraints. | Narratives are profile-specific and confidence-aware. |
| P4.1-T3 | `inference/lfm_vl_satellite_caption_service/src/lfm_vl_satellite_caption_service/dispatch.py` | `7`, `20` | 1. Add optional profile context to caption generation for map layer descriptions.<br>2. Return compact caption metadata used by brief composer. | Satellite captions become composable building blocks for briefs. |
| P4.1-T4 | `inference/lfm_vl_satellite_caption_service/src/lfm_vl_satellite_caption_service/main.py` | `27-43` | 1. Add `/v1/pro/caption` alias with profile + contract id fields.<br>2. Keep `/v1/infer` compatibility path. | Caption service supports explicit PRO profile payload. |

### Activity P4.2: On-device handoff contract

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P4.2-T1 | `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` | existing doc | 1. Add section for on-device finetuned model handoff format: input frames, metadata, confidence, summary text.<br>2. Define max payload size and truncation rules. | Server and client use one handoff contract. |
| P4.2-T2 | `server/src/nutonic_server/schemas.py` | `172-179` | 1. Add `on_device_payload` descriptor (frames refs + compact feature json + narrative seed).<br>2. Keep payload optional so older clients still parse status. | On-device model receives deterministic, bounded payload schema. |

---

## 7) Project P5 - PRO client shell and dashboard implementation

### Activity P5.1: Replace PRO placeholder with working dashboard

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P5.1-T1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/NutonicMainShell.kt` | `109`, `140`, `483`, `489` | 1. Replace `localProbeStatus = "Healthy (local check)"` with real probe request and status mapping.<br>2. Route `ShellDetail.ProCoordinateDashboard` to concrete screen instead of placeholder branch.<br>3. Show recent job cards with live status polling. | PRO tab drives real backend and renders real dashboard screen. |
| P5.1-T2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/ProCoordinateDashboardDetail.kt` (new) | new file | 1. **Primary:** embedded **map region** (half-screen min height on phone) with **movable center pin** (tap map or drag pin); pan/zoom update `center_lat`/`center_lon` and job preview ring for `bbox_half_km` (visual circle or corner readout).<br>2. **Secondary:** collapsible **"Enter coordinates"** numeric fields (lat/lon) bi-directionally bound to pin; validate range before Run.<br>3. Profile selector + Run action; optional **"Use my location"** (system permission) fills pin when allowed.<br>4. Lines `~121-280`: polling state machine, progress, **error_class**-aware copy (§15.4).<br>5. Lines `~281-460`: artifact gallery + mini-app navigation handoff. | Dashboard ships **map-first** coordinate selection; manual entry never required for happy path. |
| P5.1-T3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiClient.kt` | `33-83`, `293-347` | 1. Implement `postProJob` and `getProJob` typed methods.<br>2. Add lightweight jittered polling helper for composables.<br>3. Reuse existing error model and feature-disabled copy. | Client API supports dashboard actions natively. |
| P5.1-T4 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiModels.kt` | `148-206` | 1. Add PRO models and profile enums.<br>2. Add artifact model classes with clear discriminator fields (`kind`, `uri`, `mimeType`). | UI can render artifacts without ad hoc json parsing. |
| P5.1-T5 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProAnalysisLocationPicker.kt` (new, optional split) | new file | 1. Extract **reusable** composable: `MapViewport` (or thin wrapper) + pin state + `rememberSaveable` last center per session.<br>2. Single source of truth: `MutableState`/`StateFlow` for `(lat, lon)` consumed by dashboard and by `postProJob` builder.<br>3. Unit/UI tests: pin move updates model; manual field edit moves pin. | Map picker logic is testable and not duplicated across mini-apps. |

### Activity P5.2: Controlled gameplay handoff from PRO outputs

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P5.2-T1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/cache/ManifestPlayResolution.kt` | `13-23` | 1. Add optional overlay store path for PRO-generated AI coordinates (separate from shipped manifest `ai_guesses`).<br>2. Keep default gameplay behavior unchanged unless user explicitly publishes PRO output. | PRO outputs do not silently mutate ranked/non-ranked defaults. |
| P5.2-T2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/WorldMapGameplayScreen.kt` | `343`, `348` | 1. Read optional user-selected PRO AI guess source before fallback to manifest.<br>2. Add UX label showing source provenance ("manifest" vs "PRO run"). | Gameplay integration is explicit and provenance-visible. |

---

## 8) Project P6 - Mini-app verticals inside PRO

### Activity P6.1: FireWatch (wildfire)

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P6.1-T1 | `server/src/nutonic_server/pro_jobs_runner.py` (new) | new file | 1. Add wildfire profile branch with temporal pair fetch (`t0`, `t1`) and TiM run.<br>2. Compute burn/change masks and hotspot ranking output contract. | FireWatch run emits hotspot overlays + summary stats. |
| P6.1-T2 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/run.py` | `203-273` | 1. Add wildfire analytics block: changed area %, heat clusters, confidence bins.<br>2. Emit fixed keys consumed by UI and brief composer. | Fire analytics are stable and machine-readable. |
| P6.1-T3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProFireWatchScreen.kt` (new) | new file | 1. Map overlay rendering for burn/change layer.<br>2. Hotspot list with jump-to-location action.<br>3. "Send to Brief Composer" action. | FireWatch mini-app runs and contributes to brief pipeline. |

### Activity P6.2: OceanScout (ship detection and maritime activity intelligence)

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P6.2-T1 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/inputs_build.py` | `146-194`, `229-265` | 1. Add `oceanscout_ship_detection` profile defaults for coastal/ocean tiles (cloud ceiling, sun-glint proxy, temporal windows).<br>2. Support temporal slices (`t0`, `t1`, optional `t2`) with deterministic STAC selection and per-slice quality metadata.<br>3. Emit observation-quality metadata used later for heatmap normalization. | Inputs produce reproducible vessel-sensitive tensors with explicit quality metadata. |
| P6.2-T2 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/run.py` + `serialize.py` | `144-200`, `99-155` | 1. Fuse pseudo-SAR-like TiM outputs with LULC `water` mask into `vessel_candidates` scored objects.<br>2. Include shoreline-buffer policy so near-port detections are not erased by strict water masking.<br>3. Emit evidence labels (`optical_only`, `tim_pseudosar_plus_lulc`) and confidence bins per candidate. | Candidate detections are explainable and bounded by explicit evidence semantics. |
| P6.2-T3 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/geoguessr_materialize.py` | `147-183`, `238-355` | 1. Generate overlays for base model detections (green) and TiM-enhanced detections (blue).<br>2. Emit `vessel_candidates.json`, `vessel_overlay.geojson`, and `observation_coverage.json` artifacts.<br>3. Include cloud/glint/no-observation masks for UI transparency. | OceanScout gets map-ready overlays with provenance and quality masks. |
| P6.2-T4 | `server/src/nutonic_server/pro_jobs_runner.py` (new) | new file | 1. Aggregate multi-run detections into `lane_heatmap` normalized by valid-observation count, not raw detections.<br>2. Support geofenced incursion summaries (`incursion_events`) for marine protected areas (e.g., Channel Islands).<br>3. Keep outputs as "presence indicators", not legal assertions. | Heatmaps and reserve alerts are statistically defensible and policy-safe. |
| P6.2-T5 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProOceanScoutScreen.kt` (new) | new file | 1. Provide side-by-side/overlay compare for base model (green) vs TiM model (blue).<br>2. Add time-aggregation view (3-month lane heatmap) and geofence-incursion panel.<br>3. Surface confidence, observation coverage, and "insufficient observation" warnings inline. | OceanScout user flow supports detection review without overclaiming certainty. |
| P6.2-T6 | `docs/pro-mini-apps/OCEANSCOUT.md` (new) | new file | 1. Document scientific limitations: optical-only constraints, pseudo-SAR caveats, and cloud/glint blind spots.<br>2. Define approved language for alerts and briefs.<br>3. Add New York Harbor and Channel Islands validation scenarios with expected outputs. | Team-wide claim discipline and repeatable validation criteria are documented. |

### Activity P6.3: LandShift (land use change)

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P6.3-T1 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/serialize.py` | `133-154` | 1. Add transition-matrix extraction (`class_from -> class_to`) and top transitions list.<br>2. Emit both raw counts and normalized percentages. | LandShift outputs include actionable transition statistics. |
| P6.3-T2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProLandShiftScreen.kt` (new) | new file | 1. Transition matrix table + map hotspots.<br>2. Timeline selector for monthly/seasonal comparison windows. | LandShift mini-app provides visual + tabular change analysis. |

### Activity P6.4: FloodPulse (water change)

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P6.4-T1 | `server/src/nutonic_server/pro_jobs_runner.py` (new) | new file | 1. Add flood profile stage selecting water-sensitive modalities and thresholds.<br>2. Emit inundation polygons and affected-area metrics. | FloodPulse outputs risk-ready water expansion products. |
| P6.4-T2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProFloodPulseScreen.kt` (new) | new file | 1. Before/after water extent layer comparison.<br>2. Affected area stats and export action. | FloodPulse mini-app is fully navigable and shareable. |

### Activity P6.5: Brief Composer (cross-mini-app synthesis)

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P6.5-T1 | `inference/lfm_vl_hint_service/src/lfm_vl_hint_service/main.py` | `82-87` | 1. Extend narrative fuse route or add dedicated composer route for multi-profile bundle inputs.<br>2. Return structured brief sections (`executive_summary`, `key_findings`, `confidence`, `recommended_actions`). | Brief output is sectioned and deterministic. |
| P6.5-T2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProBriefComposerScreen.kt` (new) | new file | 1. Compose selected mini-app outputs into a single brief.<br>2. Allow inclusion/exclusion toggles per signal source.<br>3. Export/share markdown and json summary. | Users can generate one consolidated mission brief from multiple runs. |

---

## 9) Project P7 - Observability, testing, and operations

### Activity P7.1: End-to-end tests and performance gates

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P7.1-T1 | `server/tests/test_pro_job_materialize.py` | `24-120` | 1. Add E2E-ish tests for profile routing and status transitions.<br>2. Add regression test proving no poll-induced state mutation. | Core PRO control-plane behaviors are regression-protected. |
| P7.1-T2 | `inference/pro_materialization_service/tests/test_health_and_stub.py` | existing file | 1. Add profile validation and artifact mode matrix tests.<br>2. Add payload-size boundary tests for artifact serialization. | Materialization profile behavior and limits are tested. |
| P7.1-T3 | `inference/terramind_tim_local/tests/test_space_api.py` and `test_run_export.py` | existing files | 1. Add tests for new `/v1/tim/infer` alias and profile payload handling.<br>2. Add smoke tests for profile output schema keys (without heavy GPU requirement). | TiM API and export contract changes are covered in CI-safe tests. |
| P7.1-T4 | `.github/workflows/nutonic-ci.yml` | existing workflow | 1. Add targeted matrix jobs for PRO profile schema tests.<br>2. Add optional nightly heavy test stage (`RUN_TERRATORCH_TIM=1`) with artifacts upload. | CI catches contract drift and periodic real-model regressions. |
| P7.1-T5 | `inference/terramind_tim_local/tests/test_oceanscout_profile.py` (new) | new file | 1. Verify shoreline-buffered LULC masking keeps valid harbor detections while suppressing land false positives.<br>2. Verify heatmap normalization uses observation coverage denominator.<br>3. Verify "no-observation" conditions produce explicit warnings instead of zero detections. | OceanScout outputs are robust against common maritime interpretation failures. |

### Activity P7.2: Telemetry and runbooks

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P7.2-T1 | `server/docs/TOPOLOGY.md` | existing doc | 1. Add full PRO execution sequence diagram (API -> store -> runner -> workers -> artifact store).<br>2. Document required vs optional origins and fallback behavior. | Operators have a precise topology and failure-mode guide. |
| P7.2-T2 | `docs/PM2_LOCAL_VERIFICATION.md` | existing doc | 1. Add PRO mini-app local verification checklist and sample curl flows.<br>2. Include replay-protection and queue-health checks. | Local verification covers new PRO operational paths. |
| P7.2-T3 | `docs/pro-mini-apps/OPERATIONS.md` (new) | new file | 1. Capture SLOs, alert thresholds, and triage steps per mini-app profile.<br>2. Include known degraded-mode behavior for each upstream dependency. | Ops can run and troubleshoot production PRO services quickly. |

---

## 10) Project P8 - Docs/plans/rules coherence and refs transfer

### Activity P8.1: Convert refs learnings into internal implementation guidance

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P8.1-T1 | `docs/pro-mini-apps/REFS-PATTERNS.md` (new) | new file | 1. Capture anomaly workflow patterns from `refs/terramind-ad-main` for wildfire and flood timelines.<br>2. Capture vector retrieval and anti-location-leak patterns inspired by `refs/urban-embeddings-explorer-main`.<br>3. Capture fallback modality strategy inspired by `refs/volcano-eruption-risk-master`. | Refs insights are codified into actionable internal patterns. |
| P8.1-T2 | `plans/2026-04-22-pro-mini-apps-master-implementation-plan.md` | this file | 1. Track milestone updates with dated version history.<br>2. Keep risk register current as projects close. | Plan remains living source of truth. |

### Activity P8.2: Rule and spec sync

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P8.2-T1 | `rules/04-maps-and-gameplay.md` | existing doc | 1. Add explicit boundary: PRO outputs are opt-in overlays, not automatic ranked truth mutation.<br>2. Add provenance requirement for AI marker source labels. | Gameplay integrity rules remain clear while enabling PRO handoff. |
| P8.2-T2 | `docs/GAME-ENGINE.md` | existing doc | 1. Add section describing optional PRO-to-gameplay handoff path and constraints.<br>2. Keep ranked integrity constraints unchanged. | Product docs align with implemented behavior and guardrails. |
| P8.2-T3 | `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` | existing doc | 1. Align **§ map / AOI** narrative with §15.19 (map-first picker, zoom ↔ bbox semantics).<br>2. Cross-link `docs/map-engines.md` for per-target parity expectations. | PRO tab spec describes the same coordinate UX as the implementation plan. |

---

## 11) Detailed critical-path order

1. P0 contract freeze (`docs/openapi.yaml`, `server/schemas.py`, Kotlin models/client).
2. P1 control-plane hardening (persistent jobs + true async + status correctness).
3. P2 security and STAC consistency (nonce replay protection + shared loader behavior).
4. P5 baseline dashboard implementation (real create/poll UX + **map-first** center selection per §15.19).
5. P3 analytics primitives (profile outputs).
6. P6 mini-app screens and profile branches (FireWatch and LandShift first, then OceanScout and FloodPulse).
7. P4 briefing synthesis and on-device handoff.
8. P7 and P8 reliability/docs finalization and rollout.

---

## 12) Recommended first release slices

### Release R1 (fastest value, lowest additional risk)
1. FireWatch
2. LandShift
3. Brief Composer (basic)

### Release R2
1. FloodPulse
2. OceanScout
3. Brief Composer (full multi-source confidence calibration)

---

## 13) Explicit footgun closure checklist

1. No in-memory-only PRO job lifecycle in production path.
2. No poll endpoint side-effect transitions.
3. No all-or-nothing health gate when optional origins fail.
4. No inbound HMAC without nonce replay protection.
5. No unsynchronized OpenAPI/server/Kotlin PRO contracts.
6. No placeholder-only PRO routes in shipping tab.
7. No silent gameplay truth mutation from PRO outputs.
8. No replay-accepting HMAC middleware (nonce cache required on all workers).
9. No raw-count maritime heatmaps without observation-coverage normalization.
10. No claim text that implies legal certainty from optical-only/pseudo-SAR evidence.
11. **No PRO dashboard that requires typed lat/lon as the only way to set the analysis center** — map picker (or documented platform-limited equivalent) must be primary per §15.19.

---

## 14) Deep assessment: implementation state and gap analysis (v0.3)

### 14.1 Platform implementation state (verified 2026-04-24)

| Surface | Implementation maturity | Evidence |
|---|---|---|
| **Server core** (health, config, auth, maps, manifest, bundles, community LB, ranked flow, guess telemetry, Gradio /ops) | **Complete** | `main.py` routes match OpenAPI; `test_health.py` enforces route parity; ranked round lifecycle fully exercised by `test_ranked_flow.py` |
| **PRO job create/poll** (`POST /api/v1/pro/jobs`, `GET .../jobs/{job_id}`) | **Prototype** | In-memory dicts (`_pro_job_status`, `_pro_job_materialization`); synchronous 120s worker call blocks event loop; poll mutates state |
| **PRO materialization worker** (`inference/pro_materialization_service`) | **Complete** for v1 | FastAPI with HMAC middleware, `/internal/v1/materialize`, STAC modes, VLM contracts, optional TiM NPZ; full test suite |
| **TiM local inference** (`inference/terramind_tim_local`) | **Complete** for batch/export; **absent** for live PRO profiles | `run.py` ensemble, `serialize.py` JSON-safe export, `space_api.py` HF Space; no `analysis_profile` routing or scene provenance |
| **LFM-VL hint service** | **Complete** for batch street-view hints and narrative fuse | `POST /v1/suggestions/from_frames`, `POST /v1/narrative/fuse`; pluggable backends (transformers/openai/stub) |
| **LFM-VL satellite caption service** | **Complete** for single-image satellite captions | `POST /v1/infer`; same backend pattern; no profile context |
| **HMAC auth** (outbound `InferenceClient` + inbound workers) | **Signatures complete; nonce replay unprotected** | Both workers verify timestamp+sig but lack nonce cache; replay within 5-min skew window |
| **Kotlin API models** (`NutonicApiModels.kt`) | **Complete** for gameplay; **absent** for PRO | `FeatureFlags.proJobs` parsed but unused; no `ProJobCreateIn`, `ProJobStatusOut`, `ProArtifactRef`, or `ProJobProfile` DTOs |
| **Kotlin API client** (`NutonicApiClient.kt`) | **Complete** for gameplay; **absent** for PRO | No `postProJob`, `getProJob`, `cancelProJob`, or polling helpers |
| **PRO tab UI** (`NutonicMainShell.kt`) | **Placeholder** | `ProTabRoot` renders copy + fake probe; `ProCoordinateDashboard` routes to generic `ShellDetailPlaceholder` |
| **Navigation routing** (`NutonicRoute.kt`) | **Complete** | `ShellDetail.ProCoordinateDashboard` wired; token `"pro"` in encode/decode |
| **Gameplay boundary** (`ManifestPlayResolution.kt`, `WorldMapGameplayScreen.kt`) | **Clean** | No PRO imports; `AiGuessStore` manifest-scoped; no contamination vectors |
| **Data pipeline scripts** (`data/scripts/`) | **Complete** for phases A–F | Catalog import, geo context, hint tiers, validation, stills, manifest assembly, AI guess fixtures, batch SV hints; LLM narrative = dry-run/stub |
| **STAC loader alignment** | **Diverged** | `s2_stac_load.py` returns 3-tuple (stack, meta, scl_patch); `s2_stac.py` returns 2-tuple (stack, meta); SCL logic only in pro service |
| **OpenAPI ↔ server parity** | **Enforced** | `test_health.py::test_openapi_operations_match_fastapi_routes` validates route set |
| **OpenAPI ↔ PRO-TAB spec naming** | **Drifted** | OpenAPI: `center_lat/center_lon`, `/internal/v1/materialize`; PRO spec: `latitude/longitude`, `/internal/pro/materialize` |

### 14.2 Obvious implementation footguns (present in code today)

| # | Footgun | Severity | Location | Consequence if unchanged |
|---|---|---|---|---|
| F1 | **Blocking synchronous worker call in `pro_create_job`** | **Critical** | `main.py:459-476` | FastAPI event loop blocked for up to 120s per PRO job; concurrent gameplay requests (ranked start, manifest fetch) stall |
| F2 | **In-memory PRO job dicts lost on restart** | **Critical** | `main.py:59-60` | Process restart loses all job state; multi-worker deploys see inconsistent job sets |
| F3 | **Poll endpoint mutates state** (`queued → completed` on first GET) | **High** | `main.py:518-519` | First poll returns `"queued"` while setting internal state to `"completed"`; second poll returns `"completed"` — impossible for client to distinguish "still running" from "done but first poll" |
| F4 | **No session ownership check on job poll** | **High** | `main.py:507-535` | Any valid JWT can poll any `job_id` by guessing UUID hex (not secret); cross-session data leakage |
| F5 | **HMAC without nonce replay cache** | **Medium** | `inference_hmac.py:30-61` (both workers) | Captured signed request replayable within 300s skew window — integrity theater under active adversary |
| F6 | **STAC 3-tuple vs 2-tuple return divergence** | **Medium** | `s2_stac_load.py:return (stack, meta, scl)` vs `s2_stac.py:return (stack, meta)` | Shared calling code must handle different arities; future change in one breaks the other silently |
| F7 | **`jwt_secret` hardcoded default** | **Medium** | `settings.py:179` | Dev default `"dev-only-change-in-production-min-32b!!"` in production = session forgery |
| F8 | **Health probe succeeds on any 2xx JSON** | **Low** | `inference_client.py:102-111` | Worker returning `{"status": "degraded"}` still passes; false positive health |
| F9 | **`claims` discarded in `pro_create_job`** | **Low** | `main.py:433-434` | `_ = claims` — session_id never extracted; foundation for F4 |
| F10 | **Global RNG mutation in TiM ensemble** | **Low** | `run.py:_set_ensemble_iteration_seed` | Non-isolated RNG seeding affects concurrent batch exports |

### 14.3 Unobvious logical problems in the v0.2 plan

| # | Problem | Where in plan | Why it's unobvious | Resolution |
|---|---|---|---|---|
| L1 | **Concurrency model unspecified** | P1.1-T2 "background worker loop" | Plan says "background worker loop (thread/task/worker process)" without choosing. `InferenceClient` is synchronous httpx — `asyncio.create_task` would deadlock the event loop. | Specify `asyncio.to_thread` for worker invocations; cap concurrent threads via `pro_max_concurrent_jobs` semaphore. See §15.1. |
| L2 | **SQLite WAL + connection strategy unspecified** | P1.1-T6 "SqliteProJobStore" | SQLite under concurrent `asyncio.to_thread` writes needs WAL mode, busy timeout, and `pool_pre_ping`. Default journal mode causes `SQLITE_BUSY` under contention. | Specify `PRAGMA journal_mode=WAL` on connect event, `connect_args={"timeout": 15}`, `pool_pre_ping=True`. See §15.2. |
| L3 | **No error taxonomy** | P1.1-T7 "terminal failure codes" | Plan says "terminal failure codes" without defining them. UI cannot distinguish "no satellite imagery" from "worker crashed" — user gets same generic "failed". | Define 8 error classes with UI copy mapping. See §15.4. |
| L4 | **No cancellation contract** | Absent | Plan has no cancel endpoint. Long-running TiM jobs (up to 120s) have no abort mechanism; user must wait or abandon. | Add `POST /api/v1/pro/jobs/{job_id}/cancel`; runner checks cancel flag between stages. See §15.3. |
| L5 | **Session isolation missing from job store** | P1.1-T6 store schema | Plan defines `ProJobRecord` without `session_id` column. Job access control requires matching session, but the store has no field to match against. | Add `session_id TEXT NOT NULL` to store; poll/list routes verify ownership. See §15.5. |
| L6 | **Artifact storage and serving undefined** | P1.1-T7 "write artifacts" | Plan says "write artifacts and final status atomically" without defining where bytes go or how clients fetch them. `bundle_download_url` is null forever. | Define `data/pro_artifacts/{job_id}/` disk layout + `GET /api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}` route. See §15.6. |
| L7 | **STAC scene selection nondeterminism** | P3.1-T3 "multi-temporal input support" | Both STAC loaders pick "lowest cloud among max_items" — ties and STAC API ordering changes produce different scenes for same coordinates. Change detection profiles (FireWatch, LandShift, FloodPulse) require reproducible scene pairs. | Record selected scene IDs in artifact manifest; support optional `scene_id_t0/t1` pinning in `ProJobCreateIn`. See §15.7. |
| L8 | **Brief Composer cross-AOI combination** | P6.5-T1 "multi-profile bundle inputs" | No validation that input jobs cover the same geographic area. User could compose a FireWatch run over California with a FloodPulse run over Bangladesh — meaningless brief. | Add AOI centroid overlap check (500km threshold) with `force_compose` override. See §15.8. |
| L9 | **OceanScout shoreline buffer versioning mechanism undefined** | P6.2-T2 "shoreline-buffer policy" | Plan says "versioned" without defining the versioning scheme. Policy changes silently affect downstream composability. | Version string emitted in every artifact manifest; Brief Composer warns on version mismatch. See §15.9. |
| L10 | **On-device payload size unbounded** | P4.2-T2 "on_device_payload descriptor" | Plan says "frames refs + compact feature json + narrative seed" without byte limits. TiM can produce multi-MB NPZ that crashes mobile devices. | Max 4MB compressed; no raw NPZ to device; overlay PNGs ≤ 1024x1024, max 4; narrative ≤ 2000 chars × 5 sections. See §15.10. |
| L11 | **OpenAPI ↔ PRO-TAB spec naming inconsistency** | P0.1-T1 vs `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` | OpenAPI uses `center_lat/center_lon` and `/internal/v1/materialize`; PRO spec uses `latitude/longitude` and `/internal/pro/materialize`. Neither plan task calls this out. | Canonicalize on OpenAPI naming; update PRO spec to match. |
| L12 | **`InferenceClient.post_json` HMAC does not cover request body** | P2.1-T1 "nonce cache check" | Canonical string is `ts\nnonce\nmethod\npath\n` — body is excluded. Man-in-the-middle within TLS-terminated proxy could alter JSON body without invalidating signature. | **Accept** for TLS-only deployments; document in threat model. Consider body hash in canonical string for untrusted networks. |
| L13 | **`auto` backend selection in LFM services** | P4.1-T2 "profile prompt templates" | `effective_lfm_backend` returns `transformers` if importable, else `stub`. In CI or dev, transformers may be accidentally importable, making tests non-deterministic. | Explicit `LFM_VL_BACKEND` env in all deployment configs; `auto` only for local dev. |
| L14 | **No `proJobs` feature flag gating in Kotlin UI** | P5.1-T1 "real probe request" | `FeatureFlags.proJobs` is parsed from config but never checked in `NutonicMainShell.kt`. PRO tab is always visible regardless of server feature state. | Gate `ProTabRoot` visibility and "Run PRO" action on `serverFeatureFlags.proJobs`. |
| L15 | **Rules/docs "mini-apps" terminology absent** | P8.2-T1 "rules/04-maps-and-gameplay.md" | The plan introduces "mini-apps" (FireWatch, OceanScout, etc.) but no rule or doc file uses this term. Risk of terminology drift between plan and the 55+ docs/rules files. | Add vocabulary entry to `rules/00-product-intent.md` or `rules/README.md`. |
| L16 | **Form-only coordinate entry** | P5.1-T2 (pre-v0.4) | Typed lat/lon without a map is the implicit default; hemisphere mistakes and coarse AOI picking hurt trust and completion rates on mobile. | **§15.19** map-first UX; **P5.1-T5** reusable picker; P0.2-T3 / P8.2-T3 doc sync. |

---

## 15) Detailed interface and process specifications (v0.3 additions)

### 15.1 Async runner concurrency model

**Problem:** Plan P1.1-T2 proposes a "background worker loop" without specifying the concurrency model. `InferenceClient` uses synchronous `httpx.Client`; running it in a raw `asyncio.create_task` deadlocks the event loop.

**Specification:**

1. **Dispatch pattern:** Use `asyncio.to_thread` for all blocking `InferenceClient` calls. The runner claims a job from `ProJobStore`, then dispatches:

```python
async def _run_job(store: ProJobStore, ic: InferenceClient, job: ProJobRecord) -> None:
    store.transition(job.job_id, "queued", "running")
    try:
        result = await asyncio.to_thread(_invoke_worker_pipeline, ic, job)
        store.complete(job.job_id, result.artifacts, result.summary)
    except Exception as exc:
        store.fail(job.job_id, error_class=classify_error(exc), detail=str(exc)[:500])
```

2. **Startup hook:** Register a single `asyncio.Task` in FastAPI's `lifespan` context manager that polls the store for `status='queued'` jobs every `pro_job_poll_interval_seconds` (default 2.0). Claimed jobs are dispatched via `asyncio.to_thread`.

3. **Concurrency cap:** An `asyncio.Semaphore(pro_max_concurrent_jobs)` (default 2) wraps `_run_job`. When the semaphore is full, queued jobs wait until a slot opens. This prevents worker thread starvation affecting gameplay.

4. **Pipeline stages:** Each job runs a 3-stage pipeline with cancel checks between stages:
   - **Stage 1: Materialize** — `InferenceClient.post_json` to `pro_materialization_service_url`
   - **Stage 2: TiM inference** — `InferenceClient.post_json` to TiM service (when `enable_tim=True` or profile requires it)
   - **Stage 3: LFM brief** — `InferenceClient.post_json` to `lfm_vl_hint_service` `/v1/pro/brief/fuse` (when profile requests narrative)

5. **Progress reporting:** After each stage completes, update `progress_pct` in the store (33%, 66%, 100%).

6. **Graceful shutdown:** On `lifespan` exit, set a shutdown flag. In-flight jobs complete (up to `pro_job_shutdown_grace_seconds`, default 30); unclaimed queued jobs survive in SQLite for restart.

### 15.2 ProJobStore SQLite contract

**Problem:** P1.1-T6 says "sqlite-backed" without specifying WAL, connection strategy, or schema.

**Specification:**

1. **Settings additions** (to `server/src/nutonic_server/settings.py`):

```python
pro_job_database_url: str = Field(
    default="sqlite:///data/nutonic_pro_jobs.db",
    validation_alias=AliasChoices("NUTONIC_PRO_JOB_DATABASE_URL", "PRO_JOB_DATABASE_URL"),
)
pro_job_ttl_seconds: int = Field(default=86400, ...)  # 24h retention
pro_max_concurrent_jobs: int = Field(default=2, ...)
pro_job_poll_interval_seconds: float = Field(default=2.0, ...)
```

2. **Engine configuration:** SQLAlchemy engine with:
   - `connect_args={"timeout": 15}` (SQLite busy timeout)
   - `pool_pre_ping=True`
   - On first connection: `PRAGMA journal_mode=WAL`

3. **ProJobRecord schema:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `job_id` | TEXT | PK | UUID hex |
| `session_id` | TEXT | NOT NULL | From JWT claims; enables ownership filtering |
| `status` | TEXT | NOT NULL, CHECK IN (`queued`, `running`, `completed`, `failed`, `cancelled`) | Lifecycle state |
| `error_class` | TEXT | NULL | Non-null only when `status='failed'`; see §15.4 |
| `error_detail` | TEXT | NULL | Truncated to 500 chars |
| `analysis_profile` | TEXT | NOT NULL | Enum: `wildfire`, `oceanscout_ship_detection`, `land_use_change`, `flood_pulse`, `brief_only` |
| `request_params` | TEXT | NULL | JSON snapshot of `ProJobCreateIn` |
| `created_at` | TEXT | NOT NULL | ISO8601 UTC |
| `started_at` | TEXT | NULL | Set when `status → running` |
| `finished_at` | TEXT | NULL | Set when `status → completed/failed/cancelled` |
| `progress_pct` | INTEGER | DEFAULT 0 | 0–100 |
| `artifact_manifest` | TEXT | NULL | JSON array of `ProArtifactRef` on completion |
| `scene_provenance` | TEXT | NULL | JSON: `{t0: {item_id, datetime, cloud_pct}, t1: {...}}` |

4. **Indexes:** `(status, created_at)` for dequeue; `(session_id, created_at DESC)` for list.

5. **Cleanup:** Background task runs every 15 minutes, deleting rows where `finished_at < now - pro_job_ttl_seconds` and their artifact directories.

6. **State transitions (valid):**
   - `queued → running` (runner claim)
   - `queued → cancelled` (user cancel)
   - `running → completed` (pipeline success)
   - `running → failed` (pipeline error)
   - `running → cancelled` (user cancel; runner checks flag between stages)
   - No other transitions; invalid transitions raise and are logged.

### 15.3 Job cancellation contract

**Problem:** No cancel mechanism exists in v0.2.

**Specification:**

1. **Endpoint:** `POST /api/v1/pro/jobs/{job_id}/cancel`

2. **Authorization:** Session JWT required; `session_id` must match job's `session_id`. Return 404 (not 403) if mismatched, to avoid leaking job existence.

3. **Behavior by current status:**

| Current status | Action | Response |
|---|---|---|
| `queued` | Immediate transition to `cancelled` | `{"ok": true, "status": "cancelled"}` |
| `running` | Set `cancel_requested` flag in store; runner checks between pipeline stages | `{"ok": true, "status": "cancelling"}` (poll returns `cancelled` once runner acknowledges) |
| `completed` | No-op | `409 Conflict: "Job already completed"` |
| `failed` | No-op | `409 Conflict: "Job already failed"` |
| `cancelled` | Idempotent | `{"ok": true, "status": "cancelled"}` |

4. **Runner cancel check:** Between each pipeline stage, the runner re-reads the job record. If `cancel_requested=True`, transition `running → cancelled`, skip remaining stages, and clean up partial artifacts.

5. **Pydantic models:**

```python
class ProJobCancelOut(BaseModel):
    ok: bool = True
    status: str
```

### 15.4 Error taxonomy

**Problem:** v0.2 defines `failed` status without failure categories. The UI cannot distinguish retryable from terminal errors.

**Specification:**

| `error_class` | Meaning | Retryable | UI copy |
|---|---|---|---|
| `stac_no_coverage` | No Sentinel-2 scenes found for AOI/time range | No (different params needed) | "No satellite imagery available for this area and date range" |
| `stac_cloud_ceiling` | All scenes exceed cloud cover threshold | Yes (try wider date range) | "Too cloudy — try a wider date range" |
| `worker_timeout` | Materialization or TiM call exceeded read deadline | Yes (transient) | "Processing took too long — try again" |
| `worker_unreachable` | Health probe or connect failed for required origin | Yes (transient) | "Analysis service temporarily unavailable" |
| `worker_error` | Worker returned non-2xx or invalid JSON | Depends | "Analysis failed — our team has been notified" |
| `input_validation` | Invalid coordinates, bbox, profile params | No (fix input) | "Invalid input: {detail}" |
| `cancelled` | User-initiated cancellation | N/A | "Cancelled" |
| `internal` | Catch-all for unexpected exceptions | Yes (transient) | "Unexpected error — try again later" |

**Classification function:**

```python
def classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "no items found" in msg or "empty search" in msg:
        return "stac_no_coverage"
    if "cloud" in msg and "threshold" in msg:
        return "stac_cloud_ceiling"
    if isinstance(exc, httpx.TimeoutException):
        return "worker_timeout"
    if isinstance(exc, httpx.ConnectError):
        return "worker_unreachable"
    if isinstance(exc, httpx.HTTPStatusError):
        return "worker_error"
    if isinstance(exc, ValueError):
        return "input_validation"
    return "internal"
```

### 15.5 Session-scoped job isolation

**Problem:** Current `GET /api/v1/pro/jobs/{job_id}` has no ownership check.

**Specification:**

1. **Poll route:** Extract `session_id` from JWT claims. Query store for `(job_id, session_id)`. Return 404 if not found (prevents session enumeration).

2. **List route:** `GET /api/v1/pro/jobs?limit=20&status=running,completed`
   - Returns only jobs owned by the requesting session
   - Default limit 20, max 100
   - Filter by comma-separated status values

3. **SQL query pattern:**

```sql
SELECT * FROM pro_jobs
WHERE session_id = :sid AND status IN (:statuses)
ORDER BY created_at DESC
LIMIT :limit
```

4. **OpenAPI additions:** Add `GET /api/v1/pro/jobs` with query params `limit` and `status`.

### 15.6 Artifact storage and serving

**Problem:** v0.2 defines artifact metadata but not where bytes live or how clients fetch them.

**Specification:**

1. **Disk layout:** `data/pro_artifacts/{job_id}/{artifact_id}.{ext}` + `manifest.json`

2. **Serve route:** `GET /api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}`
   - Session-scoped (same ownership check as job poll)
   - Serves bytes from disk with `Content-Type` from manifest
   - `Cache-Control: private, max-age=3600`
   - Returns 404 if job/artifact not found or session mismatch

3. **ProArtifactRef schema:**

```python
class ProArtifactRef(BaseModel):
    artifact_id: str          # e.g. "vessel_overlay", "burn_change_heatmap"
    kind: str                 # "geojson", "png", "json", "npz"
    mime_type: str            # "application/geo+json", "image/png", etc.
    size_bytes: int | None = None
    profile: str | None = None  # which mini-app produced this
    download_url: str | None = None  # populated by status route
```

4. **URL population:** When `status == "completed"`, the poll route populates `download_url` as `/api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}` for each artifact.

5. **Cleanup:** TTL-based job cleanup (§15.2) also deletes `data/pro_artifacts/{job_id}/` directories.

6. **Size limits:** Individual artifact max 50MB; total per job max 200MB. Enforced at write time by the runner.

### 15.7 Temporal STAC determinism and scene provenance

**Problem:** Change detection profiles need reproducible scene selection, but STAC queries are nondeterministic.

**Specification:**

1. **Provenance recording:** The runner records selected scene IDs in the job's `scene_provenance` column:

```json
{
  "t0": {"item_id": "S2B_MSIL2A_20260301...", "datetime": "2026-03-01T10:30:00Z", "cloud_pct": 12.3},
  "t1": {"item_id": "S2A_MSIL2A_20260415...", "datetime": "2026-04-15T10:28:00Z", "cloud_pct": 8.1}
}
```

2. **Scene pinning:** `ProJobCreateIn` gains optional fields:

```python
scene_id_t0: str | None = None  # Pin specific STAC item for t0
scene_id_t1: str | None = None  # Pin specific STAC item for t1
```

When provided, the runner fetches those exact scenes instead of searching. When omitted, the runner selects lowest-cloud scenes and records them.

3. **Brief Composer:** Includes scene provenance metadata in its output, enabling consumers to verify temporal consistency.

4. **STAC search ordering:** Both loaders must use `sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}]` (where supported) and take the first result, making ties deterministic.

### 15.8 Brief Composer AOI validation

**Problem:** Multi-profile briefs may combine runs from incompatible geographic areas.

**Specification:**

1. **Validation:** The `/v1/pro/brief/fuse` endpoint computes centroid distance between all input job AOIs. If any pair exceeds `max_compose_distance_km` (default 500), return:

```json
{
  "error": "aoi_mismatch",
  "detail": "FireWatch AOI (34.05, -118.24) is 12,400 km from FloodPulse AOI (23.81, 90.41). Max allowed: 500 km.",
  "job_ids": ["abc123", "def456"]
}
```

2. **Override:** Client can re-submit with `force_compose: true` to bypass the check. UI shows a warning with toggle.

3. **Haversine reuse:** Use the existing `haversine_km` from `nutonic_server.haversine` (server-side) or the Brief Composer's own geodesy (inference-side).

### 15.9 OceanScout shoreline buffer versioning

**Problem:** Plan mentions versioning the shoreline buffer policy without defining the mechanism.

**Specification:**

```python
OCEANSCOUT_SHORELINE_POLICY = {
    "version": "1.0",
    "buffer_m": 500,           # meters from coastline kept as "nearshore"
    "morphology_kernel_px": 3, # dilation kernel for harbor retention
    "min_water_fraction": 0.3, # tile must be >= 30% water to apply vessel detection
}
```

1. **Version string** is emitted in every OceanScout artifact manifest.
2. **Policy changes** increment the version (semver minor for parameter changes, major for algorithmic changes).
3. **Brief Composer** includes a `"policy_version_mismatch"` warning if composing runs from different versions.
4. **Storage:** Config constant in `inference/terramind_tim_local/src/nutonic_terramind_tim_local/oceanscout_policy.py` (new file).

### 15.10 On-device handoff payload bounds

**Problem:** No concrete size limits specified for on-device payloads.

**Specification:**

1. **Max total payload:** 4 MB (compressed JSON + artifact refs, not raw NPZ)
2. **No raw NPZ transfer to device.** TiM outputs are server-side only; the device receives:
   - Summary JSON ≤ 4KB (top-5 findings by confidence score if exceeds)
   - Overlay PNGs: max 1024×1024 each, max 4 overlays
   - Narrative text: max 2000 characters per brief section, max 5 sections
3. **Truncation rule:** If TiM summary exceeds 4KB JSON, emit only top-5 findings by confidence score.

4. **Kotlin model:**

```kotlin
@Serializable
data class ProOnDevicePayload(
    @SerialName("brief_sections") val briefSections: List<ProBriefSection>,
    @SerialName("overlay_refs") val overlayRefs: List<ProArtifactRef>,
    @SerialName("confidence_summary") val confidenceSummary: String? = null,
)

@Serializable
data class ProBriefSection(
    @SerialName("title") val title: String,
    @SerialName("body") val body: String,
    @SerialName("confidence") val confidence: String? = null,
)
```

### 15.11 Expanded ProJobStatusOut schema

**Current schema** (`schemas.py:172-179`) is minimal. Replace with:

```python
class ProJobStatusOut(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    error_class: str | None = None
    error_detail: str | None = None
    progress_pct: int | None = None
    analysis_profile: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    artifacts: list[ProArtifactRef] | None = None
    scene_provenance: dict | None = None
    # Compatibility fields (kept for existing callers)
    materialization_id: str | None = None
    cache_key: str | None = None
    bundle_download_url: str | None = None
    materialization_summary: dict | None = None
```

### 15.12 Expanded ProJobCreateIn schema

Add `analysis_profile` enum and temporal pinning:

```python
class ProJobCreateIn(BaseModel):
    center_lat: float = Field(ge=-90.0, le=90.0)
    center_lon: float = Field(ge=-180.0, le=180.0)
    bbox_half_km: float = Field(default=5.0, gt=0, le=500.0)
    mapbox_zoom: int = Field(default=12, ge=0, le=18)
    analysis_profile: Literal[
        "wildfire", "oceanscout_ship_detection", "land_use_change",
        "flood_pulse", "brief_only"
    ] = "brief_only"
    enable_tim: bool = False
    tim_branch: Literal["S2L2A_full", "RGB_mapbox"] = "RGB_mapbox"
    vlm_contract_id: str = Field(default="nutonic.pro.vlm.v1_512", max_length=128)
    sentinel_fetch_mode: Literal["MINIMAL_RGB", "TERRAMIND_SPECTRAL", "FULL_STAC"] = "MINIMAL_RGB"
    datetime_interval: str | None = Field(default=None, max_length=128)
    scene_id_t0: str | None = None
    scene_id_t1: str | None = None
```

### 15.13 HMAC body integrity consideration

**Current state:** Canonical string is `ts\nnonce\nmethod\npath\n` — request body is not covered. This means a proxy within the TLS-terminated boundary could alter JSON body without invalidating the HMAC.

**Recommendation for v1:** Accept current behavior for TLS-only deployments. Document in `docs/pro-mini-apps/THREAT-MODEL.md` that body integrity relies on TLS.

**Future option:** Add body hash to canonical string:

```
{ts}\n{nonce}\n{method}\n{path}\n{sha256(body)}\n
```

This requires updating both `InferenceClient._sign_headers` and all worker `verify_inbound_hmac` implementations simultaneously.

### 15.14 Nonce replay cache specification

**Implementation for both `inference_hmac.py` files:**

```python
import collections
import threading

_NONCE_LOCK = threading.Lock()
_NONCE_CACHE: collections.OrderedDict[str, float] = collections.OrderedDict()
_MAX_NONCE_CACHE = 10_000

def _check_and_record_nonce(nonce: str, ts: float, max_skew_s: int) -> str | None:
    """Returns error string if nonce is replayed; None if OK."""
    with _NONCE_LOCK:
        if nonce in _NONCE_CACHE:
            return "replayed X-Nutonic-Nonce"
        # Evict expired entries
        cutoff = time.time() - max_skew_s
        while _NONCE_CACHE:
            oldest_nonce, oldest_ts = next(iter(_NONCE_CACHE.items()))
            if oldest_ts < cutoff:
                _NONCE_CACHE.pop(oldest_nonce)
            else:
                break
        # Enforce max size
        while len(_NONCE_CACHE) >= _MAX_NONCE_CACHE:
            _NONCE_CACHE.popitem(last=False)
        _NONCE_CACHE[nonce] = ts
    return None
```

Insert call in `verify_inbound_hmac` after signature verification succeeds.

### 15.15 STAC loader unification strategy

**Problem:** `s2_stac_load.py` (pro) and `s2_stac.py` (TiM local) have near-duplicate logic with divergent return arities and SCL handling.

**Specification:**

1. Create `inference/shared_geospatial/s2_stac_core.py` with the unified loader:
   - Returns `S2PatchResult(stack, meta, scl_patch=None)` named tuple
   - `scl_patch` populated when `include_scl=True` (preserves pro service behavior)
   - Both packages import from `shared_geospatial` as an optional dependency

2. Migration path:
   - W2: Create shared module; pro service migrates first (has test suite)
   - W3: TiM local migrates; adjust `inputs_build.py` to use named tuple access

3. **Band order contract:** Document the canonical 10-band order as a constant in the shared module, not implicitly in each loader.

### 15.16 Kotlin PRO DTO specifications

**Required additions to `NutonicApiModels.kt`:**

```kotlin
@Serializable
enum class ProJobProfile {
    @SerialName("wildfire") WILDFIRE,
    @SerialName("oceanscout_ship_detection") OCEANSCOUT_SHIP_DETECTION,
    @SerialName("land_use_change") LAND_USE_CHANGE,
    @SerialName("flood_pulse") FLOOD_PULSE,
    @SerialName("brief_only") BRIEF_ONLY;
    companion object {
        fun fromStringOrNull(value: String): ProJobProfile? =
            entries.firstOrNull { it.name.equals(value, ignoreCase = true) }
    }
}

@Serializable
data class ProJobCreateIn(
    @SerialName("center_lat") val centerLat: Double,
    @SerialName("center_lon") val centerLon: Double,
    @SerialName("bbox_half_km") val bboxHalfKm: Double = 5.0,
    @SerialName("mapbox_zoom") val mapboxZoom: Int = 12,
    @SerialName("analysis_profile") val analysisProfile: ProJobProfile = ProJobProfile.BRIEF_ONLY,
    @SerialName("enable_tim") val enableTim: Boolean = false,
    @SerialName("tim_branch") val timBranch: String = "RGB_mapbox",
    @SerialName("vlm_contract_id") val vlmContractId: String = "nutonic.pro.vlm.v1_512",
    @SerialName("sentinel_fetch_mode") val sentinelFetchMode: String = "MINIMAL_RGB",
    @SerialName("datetime_interval") val datetimeInterval: String? = null,
    @SerialName("scene_id_t0") val sceneIdT0: String? = null,
    @SerialName("scene_id_t1") val sceneIdT1: String? = null,
)

@Serializable
data class ProJobCreateOut(
    @SerialName("job_id") val jobId: String,
    @SerialName("status") val status: String = "queued",
)

@Serializable
data class ProArtifactRef(
    @SerialName("artifact_id") val artifactId: String,
    @SerialName("kind") val kind: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    @SerialName("profile") val profile: String? = null,
    @SerialName("download_url") val downloadUrl: String? = null,
)

@Serializable
data class ProJobStatusOut(
    @SerialName("job_id") val jobId: String,
    @SerialName("status") val status: String,
    @SerialName("error_class") val errorClass: String? = null,
    @SerialName("error_detail") val errorDetail: String? = null,
    @SerialName("progress_pct") val progressPct: Int? = null,
    @SerialName("analysis_profile") val analysisProfile: String? = null,
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("finished_at") val finishedAt: String? = null,
    @SerialName("artifacts") val artifacts: List<ProArtifactRef>? = null,
    // Compatibility
    @SerialName("materialization_id") val materializationId: String? = null,
    @SerialName("cache_key") val cacheKey: String? = null,
    @SerialName("bundle_download_url") val bundleDownloadUrl: String? = null,
)

@Serializable
data class ProJobCancelOut(
    @SerialName("ok") val ok: Boolean = true,
    @SerialName("status") val status: String,
)
```

### 15.17 Kotlin PRO API client methods

**Required additions to `NutonicApiClient.kt`:**

```kotlin
suspend fun postProJob(baseUrl: String, token: String, body: ProJobCreateIn): ApiResult<ProJobCreateOut>

suspend fun getProJob(baseUrl: String, token: String, jobId: String): ApiResult<ProJobStatusOut>

suspend fun cancelProJob(baseUrl: String, token: String, jobId: String): ApiResult<ProJobCancelOut>

suspend fun listProJobs(
    baseUrl: String,
    token: String,
    limit: Int = 20,
    status: String? = null,
): ApiResult<List<ProJobStatusOut>>

suspend fun getProArtifact(
    baseUrl: String,
    token: String,
    jobId: String,
    artifactId: String,
): ApiResult<ByteArray>
```

**Polling helper:**

```kotlin
suspend fun pollProJob(
    baseUrl: String,
    token: String,
    jobId: String,
    intervalMs: Long = 2000,
    maxAttempts: Int = 90, // 3 minutes at 2s intervals
    onProgress: (ProJobStatusOut) -> Unit = {},
): ApiResult<ProJobStatusOut> {
    repeat(maxAttempts) {
        val result = getProJob(baseUrl, token, jobId)
        if (result is ApiResult.Success) {
            val status = result.data.status
            onProgress(result.data)
            if (status in listOf("completed", "failed", "cancelled")) return result
        } else {
            return result
        }
        delay(intervalMs + Random.nextLong(0, intervalMs / 4)) // jitter
    }
    return ApiResult.Error("Polling timeout after ${maxAttempts * intervalMs / 1000}s")
}
```

### 15.18 Feature flag gating for PRO UI

**Problem:** `FeatureFlags.proJobs` is parsed but never used in the shell.

**Specification:**

1. `ProTabRoot` checks `serverFeatureFlags?.proJobs == true` before enabling "Run PRO" actions.
2. When `proJobs` is `false` or `null` (server unreachable), show informational copy with "PRO features are not available on this server."
3. The PRO tab itself remains visible (it's a navigation constant), but interactive elements are disabled.

### 15.19 PRO map-first coordinate selection (primary AOI entry)

**Problem:** Typed `center_lat` / `center_lon` alone is slow, error-prone, and a poor fit for mobile; the plan previously implied form-first entry in P5.1-T2.

**Product rule:** On every **tier-A** target (Android, iOS, Desktop) where `MapViewport` ships for SCAN, the PRO dashboard **must** show an interactive basemap with a **single analysis center pin** as the default path to set `POST /api/v1/pro/jobs` coordinates. Manual numeric fields are **advanced**, collapsed by default, and **bi-directionally synced** with the pin.

**UX specification:**

1. **Layout:** Upper or dominant **map card** (min ~240dp height phone, ~40% viewport tablet); below: profile selector, `bbox_half_km` / zoom controls, Run, job list.
2. **Interactions:** Tap empty map → move pin to tap; **drag pin**; pan/zoom map — center always equals pin WGS84. Optional **"Use my location"** uses platform geolocation API when permission granted; on deny, no-op with inline message.
3. **Visual feedback:** Dashed circle or shaded **AOI footprint** derived from `bbox_half_km` (haversine approximation acceptable for preview); updating copy: `Center 12.3456°, -98.7654°`.
4. **Manual fields:** Expanding "Advanced" reveals lat/lon text fields; editing commits to pin and re-centers map camera when valid.
5. **State:** Single `StateFlow` / `MutableState` holding `(centerLat, centerLon)` is the only source passed to `postProJob`; avoid duplicate mutable text state drifting from pin.
6. **Web (tier-B):** If full `MapViewport` parity lags per `docs/map-engines.md`, ship **either** (a) embedded map with same pin semantics when SDK ready, or (b) interim **clickable static basemap** + pin (documented ADR) until interactive parity — **never** web-only raw lat/lon without a map affordance.
7. **Accessibility:** Pin move announces updated coordinates; manual fields labeled; large hit target for pin drag per `rules/08-ux-and-performance-footguns.md`.
8. **Tests:** Compose/UI or unit: moving pin updates model; editing fields updates pin; invalid lat/lon blocks Run with `input_validation`-style client message before POST.

**API:** No OpenAPI change required — client still sends `center_lat` / `center_lon`; map is purely client UX. Optional future: `location_source: "map_pin" | "manual" | "device_gps"` on create body for analytics (non-breaking optional field).

**Implementation anchors:** Reuse `MapViewport` / map controller patterns from `rules/04-maps-and-gameplay.md`; extract `ProAnalysisLocationPicker` per **P5.1-T5** if the dashboard file grows too large.

---

## 16) Updated critical-path order with v0.3 specifications

```
1. P0: Contract freeze (OpenAPI, schemas, Kotlin DTOs)
   ├─ Add error taxonomy to schemas (§15.4)
   ├─ Add cancel endpoint to OpenAPI (§15.3)
   ├─ Add session isolation to contracts (§15.5)
   ├─ Add analysis_profile enum (§15.12)
   └─ Add Kotlin PRO DTOs (§15.16)

2. P1: Control plane hardening
   ├─ ProJobStore with WAL + SQLAlchemy (§15.2)
   ├─ Async runner via asyncio.to_thread (§15.1)
   ├─ Artifact storage on disk + serve route (§15.6)
   ├─ Job cancellation implementation (§15.3)
   └─ Feature flag gating in Kotlin UI (§15.18)

3. P2: Security + STAC consistency
   ├─ Nonce replay cache (§15.14)
   ├─ STAC loader unification (§15.15)
   └─ Body integrity documentation (§15.13)

4. P5: PRO Dashboard UI
   ├─ Kotlin API client methods (§15.17)
   ├─ Map-first center selection (§15.19) + `ProAnalysisLocationPicker` (P5.1-T5)
   └─ Real create/poll UX with progress

5. P3: TiM Analytics Primitives
   ├─ Scene provenance recording (§15.7)
   ├─ Profile-aware analytics blocks
   └─ OceanScout shoreline versioning (§15.9)

6. P6: Mini-App Verticals
   ├─ FireWatch + LandShift (R1)
   ├─ FloodPulse + OceanScout (R2)
   ├─ Brief Composer with AOI validation (§15.8)
   └─ On-device payload enforcement (§15.10)

7. P4: LFM Briefs + On-Device Handoff
   └─ Payload size enforcement (§15.10)

8. P7 + P8: Reliability, docs, rules coherence
```

---

## 17) Cross-document consistency fixes required

| Issue | Source A | Source B | Resolution |
|---|---|---|---|
| Field naming: `center_lat/lon` vs `latitude/longitude` | `docs/openapi.yaml` | `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §9 | Canonicalize on `center_lat/center_lon` (matches implementation) |
| Internal path: `/internal/v1/materialize` vs `/internal/pro/materialize` | `main.py:472`, `openapi.yaml` description | PRO spec §9 sketch | Canonicalize on `/internal/v1/materialize` (matches implementation) |
| Hint tier count: "three" vs "six" | `rules/04-maps-and-gameplay.md` | `rules/00`, `05`, `06`, `10`; `docs/openapi.yaml` `UsefulHintsTiers` | Update `rules/04` to "up to six monotonic tiers" |
| PRO gating flag: `pro_jobs` vs `pro` | `openapi.yaml`, `settings.py` | `PRO-TAB-VLM-ORCHESTRATION-SPEC.md` ("features.pro") | Canonicalize on `pro_jobs` (matches implementation); add `pro` as alias if needed |
| "Mini-apps" terminology | This plan; `.cursor/plans/` | All 17 rules + 39 docs files (term absent) | Add vocabulary entry to `rules/00-product-intent.md`: "PRO mini-apps = FireWatch, OceanScout, LandShift, FloodPulse, Brief Composer" |
| Forfeit endpoint naming: split vs merged | Various docs cross-refs | `openapi.yaml`: single `.../forfeit-ranked-integrity` | OpenAPI is normative; update prose cross-refs |
| PRO AOI entry UX | This plan §15.19, P5.1-T2 | `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` (coordinate prose) | Add map-first workflow to PRO tab spec (P8.2-T3); keep API fields `center_lat`/`center_lon` |

---

## 18) Explicit footgun closure checklist (expanded for v0.3)

1. ~~No in-memory-only PRO job lifecycle in production path.~~ → §15.2
2. ~~No poll endpoint side-effect transitions.~~ → §15.2 state transitions
3. ~~No all-or-nothing health gate when optional origins fail.~~ → P1.1-T2 capability-aware policy
4. ~~No inbound HMAC without nonce replay protection.~~ → §15.14
5. ~~No unsynchronized OpenAPI/server/Kotlin PRO contracts.~~ → §15.11, §15.12, §15.16
6. ~~No placeholder-only PRO routes in shipping tab.~~ → §15.18 + P5
7. ~~No silent gameplay truth mutation from PRO outputs.~~ → P5.2
8. ~~No replay-accepting HMAC middleware.~~ → §15.14
9. ~~No raw-count maritime heatmaps without observation-coverage normalization.~~ → P6.2-T4
10. ~~No claim text that implies legal certainty from optical-only/pseudo-SAR evidence.~~ → P6.2-T6
11. **No event loop blocking from synchronous worker calls.** → §15.1
12. **No session-unscoped PRO job access.** → §15.5
13. **No unclassified failure states in PRO jobs.** → §15.4
14. **No absent cancel mechanism for long-running jobs.** → §15.3
15. **No unbounded on-device PRO payloads.** → §15.10
16. **No divergent STAC loaders across services.** → §15.15
17. **No undocumented HMAC body-integrity assumptions.** → §15.13
18. **No STAC scene nondeterminism in change-detection profiles.** → §15.7
19. **No cross-AOI brief composition without validation.** → §15.8
20. **No unversioned OceanScout shoreline buffer policy.** → §15.9
21. **No ship-blocking PRO coordinate UX that omits an interactive map** on targets where SCAN already ships `MapViewport` → §15.19, P5.1-T2, P5.1-T5

---

## 14) Version history

| Version | Date | Notes |
|---|---|---|
| 0.1 | 2026-04-22 | Initial comprehensive master plan with projects, activities, file-level tasks, and line-level subtasks. |
| 0.2 | 2026-04-24 | Added repository baseline audit, explicit risk register, OceanScout integration (contracts, analytics, UI, tests), and corrected plan path typo in P8.1-T2. |
| 0.3 | 2026-04-24 | Deep assessment of full platform implementation state across server, inference services, Kotlin client, docs, rules, and 22 plans. Added 10 footgun identifications (F1–F10), 15 unobvious logical problems (L1–L15), 18 detailed interface and process specifications (§15.1–§15.18), cross-document consistency fixes (§17), and expanded footgun closure checklist (20 items). Specified: async runner concurrency model, SQLite WAL contract, job cancellation, error taxonomy, session isolation, artifact storage/serving, STAC scene determinism, AOI validation, shoreline versioning, on-device payload bounds, expanded Pydantic schemas, Kotlin DTOs, API client methods, nonce replay cache, STAC loader unification, and feature flag gating. |
| 0.4 | 2026-04-24 | **Map-first PRO coordinate selection:** product outcome #4; W4 exit criteria; P0.2-T2/T3 (checklist + PRO-TAB doc); P5.1-T2/T5 (dashboard + reusable picker); P8.2-T3; critical-path P5 note; §13 checklist item 11; **§15.19** full UX/process spec (pin, AOI preview, manual sync, web interim, a11y, tests); §16 P5 subtree; §17 row; §18 item 21. |

