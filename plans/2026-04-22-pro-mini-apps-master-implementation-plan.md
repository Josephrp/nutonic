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
   - VesselWatch (ocean vessel monitoring)
   - LandShift (land use / land cover change)
   - FloodPulse (water expansion/change)
   - Brief Composer (cross-app synthesis)
3. Produce machine + human outputs from the same run:
   - TiM artifacts and overlays
   - LFM-VL narrative and action summary
   - Shareable map-ready frames

### Engineering outcomes
1. Remove known orchestration and security footguns.
2. Keep OpenAPI, server models, and Kotlin DTOs in sync.
3. Add testable contracts for each mini-app profile and output bundle.

---

## 1) Delivery waves

| Wave | Goal | Exit criteria |
|---|---|---|
| W0 | Contract freeze + risk gates | OpenAPI and schema updates merged; footgun acceptance criteria written |
| W1 | Control-plane hardening | Persistent PRO jobs + correct status lifecycle + no poll-side effects |
| W2 | Security and worker consistency | Replay-safe HMAC on workers; aligned STAC loading behavior |
| W3 | Analytics primitives | TiM outputs normalized into profile-ready analytics payloads |
| W4 | PRO UI + API wiring | Real PRO dashboard + Kotlin API methods + status polling UX |
| W5 | Mini-app verticals | FireWatch + LandShift + VesselWatch + FloodPulse + Brief Composer |
| W6 | Reliability and launch | Perf/soak tests, observability, runbooks, rollout flags |

---

## 2) Project P0 - Contract and architecture freeze

### Activity P0.1: Align PRO API contracts before implementation

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P0.1-T1 | `docs/openapi.yaml` | `449`, `472`, `870`, `907`, `939` | 1. At `/api/v1/pro/jobs` and `/api/v1/pro/jobs/{job_id}`, change semantics from pseudo-queue to true async (`queued/running/completed/failed`).<br>2. Expand `ProJobStatusOut` with `status_reason`, `started_at`, `finished_at`, `progress_pct`, `profile`, `analysis_artifacts`, `brief_artifacts`.<br>3. Keep backwards fields (`materialization_id`, `cache_key`) but mark as compatibility fields. | API contract explicitly models async lifecycle and mini-app profile outputs. |
| P0.1-T2 | `server/src/nutonic_server/schemas.py` | `150-179` | 1. Update `ProJobCreateIn` for `analysis_profile` enum (`wildfire`, `vessel_monitoring`, `land_use_change`, `flood_pulse`, `brief_only`).<br>2. Expand `ProJobCreateOut` and `ProJobStatusOut` to mirror OpenAPI changes exactly.<br>3. Add Pydantic models for typed artifact refs instead of raw free-form dicts where possible. | OpenAPI and runtime schemas are isomorphic. |
| P0.1-T3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiModels.kt` | `1-206` | 1. Add `ProJobCreateIn`, `ProJobCreateOut`, `ProJobStatusOut`, `ProArtifactRef`, `ProJobProfile` models.<br>2. Keep nullable fields for compatibility with older servers.<br>3. Add serializer-safe enums with fallback handling for unknown future profile values. | Kotlin DTOs decode current and next contract versions safely. |
| P0.1-T4 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiClient.kt` | `33-347` | 1. Add methods: `postProJob(...)`, `getProJob(jobId, ...)`, `cancelProJob(...)` (if endpoint added).<br>2. Reuse existing `decodeResponse` path and map feature-disabled handling for `pro_jobs`.<br>3. Add retry/backoff utility for status polling. | Client can create and poll PRO jobs through typed methods only. |

### Activity P0.2: Route and screen topology for mini-apps

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P0.2-T1 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/navigation/NutonicRoute.kt` | `28-46`, `133-158` | 1. Extend `ShellDetail` with dedicated routes: `ProFireWatch`, `ProVesselWatch`, `ProLandShift`, `ProFloodPulse`, `ProBriefComposer`.<br>2. Add token encode/decode mappings after current `pro` token handling.<br>3. Preserve backwards token `pro` for entry dashboard route. | Typed routing supports each mini-app without ad hoc strings. |
| P0.2-T2 | `rules/07-screens-checklist.md` | N/A | 1. Add explicit PRO mini-app screen checklist entries.<br>2. Add acceptance criteria for "no placeholder in production route". | Checklist reflects shipping PRO surface, not placeholder shell. |

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
| P2.2-T3 | `inference/pro_materialization_service/src/pro_materialization_service/geospatial/asset_policy.py` | `19-38` | 1. Add explicit profile-to-mode matrix validation (wildfire, vessel, land_use, flood).<br>2. Keep current mode matrix as base constraints. | Profile contracts cannot request impossible mode combinations. |
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
| P4.1-T2 | `inference/lfm_vl_hint_service/src/lfm_vl_hint_service/dispatch.py` | `25-37`, `40-52` | 1. Add profile prompt templates and response guards for wildfire/vessel/land/flood narratives.<br>2. Enforce "no invented certainty" policy via output schema constraints. | Narratives are profile-specific and confidence-aware. |
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
| P5.1-T2 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/ProCoordinateDashboardDetail.kt` (new) | new file | 1. Lines `1-120`: coordinate entry, profile selector, run action.<br>2. Lines `121-260`: polling state machine, progress and error rendering.<br>3. Lines `261-420`: artifact gallery and mini-app navigation handoff. | Main PRO dashboard screen shipped and connected. |
| P5.1-T3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiClient.kt` | `33-83`, `293-347` | 1. Implement `postProJob` and `getProJob` typed methods.<br>2. Add lightweight jittered polling helper for composables.<br>3. Reuse existing error model and feature-disabled copy. | Client API supports dashboard actions natively. |
| P5.1-T4 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiModels.kt` | `148-206` | 1. Add PRO models and profile enums.<br>2. Add artifact model classes with clear discriminator fields (`kind`, `uri`, `mimeType`). | UI can render artifacts without ad hoc json parsing. |

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

### Activity P6.2: VesselWatch (ocean vessel monitoring)

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P6.2-T1 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/inputs_build.py` | `146-194`, `229-265` | 1. Add vessel profile defaults optimized for coastal/ocean tiles and small-object sensitivity.<br>2. Add multi-frame delta extraction inputs. | Inputs produce vessel-sensitive tensors reproducibly. |
| P6.2-T2 | `inference/terramind_tim_local/src/nutonic_terramind_tim_local/geoguessr_materialize.py` | `147-183`, `238-355` | 1. Add candidate-point and tracklet preview generation from temporal outputs.<br>2. Emit `vessel_candidates.json` artifact. | VesselWatch gets map-ready candidate overlays. |
| P6.2-T3 | `nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProVesselWatchScreen.kt` (new) | new file | 1. Candidate track visualization and confidence filters.<br>2. Compare two timestamps with synchronized pan/zoom views. | VesselWatch user flow supports screening suspicious movement. |

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
| P8.1-T2 | `.plans/2026-04-22-pro-mini-apps-master-implementation-plan.md` | this file | 1. Track milestone updates with dated version history.<br>2. Keep risk register current as projects close. | Plan remains living source of truth. |

### Activity P8.2: Rule and spec sync

| Task ID | File | Current anchors | Line-level subtasks | DoD |
|---|---|---|---|---|
| P8.2-T1 | `rules/04-maps-and-gameplay.md` | existing doc | 1. Add explicit boundary: PRO outputs are opt-in overlays, not automatic ranked truth mutation.<br>2. Add provenance requirement for AI marker source labels. | Gameplay integrity rules remain clear while enabling PRO handoff. |
| P8.2-T2 | `docs/GAME-ENGINE.md` | existing doc | 1. Add section describing optional PRO-to-gameplay handoff path and constraints.<br>2. Keep ranked integrity constraints unchanged. | Product docs align with implemented behavior and guardrails. |

---

## 11) Detailed critical-path order

1. P0 contract freeze (`docs/openapi.yaml`, `server/schemas.py`, Kotlin models/client).
2. P1 control-plane hardening (persistent jobs + true async + status correctness).
3. P2 security and STAC consistency (nonce replay protection + shared loader behavior).
4. P5 baseline dashboard implementation (real create/poll UX).
5. P3 analytics primitives (profile outputs).
6. P6 mini-app screens and profile branches (FireWatch and LandShift first, then VesselWatch and FloodPulse).
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
2. VesselWatch
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

---

## 14) Version history

| Version | Date | Notes |
|---|---|---|
| 0.1 | 2026-04-22 | Initial comprehensive master plan with projects, activities, file-level tasks, and line-level subtasks. |

