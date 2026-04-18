# Street View: real Google imagery, road-perpendicular headings, and full-scope follow-ons

**Status:** Normative implementation breakdown (WBS).  
**Authority:** Product intent from chat (2026-04-18); aligns with `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` (§2.2 internal REST, “heading/pitch policy stays in `streetview_pano_service`” — **§2.2 JSON updated 2026-04-18** to reference this WBS), `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md` §5 Phase **D**, `plans/2026-04-13-prioritized-implementation-task-backlog.md` (**IMP-110** / **W8**), `plans/2026-04-13-repo-state-gap-analysis.md` **v1.3**, `plans/2026-04-16-stub-replacement-implementation-plan.md` (**STUB-A**), `plans/2026-04-14-data-scripts-implementation-track.md` §8 **P6.7**, `plans/2026-04-13-implementation-planning-series-index.md`, `docs/scripts/SPEC-batch-streetview-hints.md`, `rules/06-server-vlm-tim-and-on-device-ml.md`, `inference/README.md`.

**Scope:** Everything in the 2026-04-18 investigation thread, **including all items previously marked optional**: single-pano `pano=` Static requests, implemented `heading_mode`, road-tangent providers (OSM, Mapbox, Google Roads), optional **Street View Tile API** / multi-pano graph walks, pitch and FOV schedules, disk cache, batch + HF Jobs wiring, health/`model_pins`, structured errors, CI/VCR strategy, doc and backlog cross-links.

**Non-goals (unchanged):** game Kotlin clients do not call Google; golden coordinates never enter ranked client packs; LFM still enforces caption policy via `data/scripts/validate_hint_strings.py` + prompts.

---

## 0. Executive summary

| Gap today | Target |
|-----------|--------|
| `heading_mode` is a string default with **no implementation** in stub or Google paths. | Enum-like modes with **documented semantics** and tests. |
| Google path uses **per-frame `location=` at offset lat/lon** (`google_sample.py` L30–L35) + compass headings `i*360/n`. | Default: **one metadata-resolved pano**, **`pano=`** on Static for all frames, headings derived from **road tangent ± 90°** (and optional spreads). |
| Classic Metadata JSON has **no `links`** graph ([Street View Image Metadata](https://developers.google.com/maps/documentation/streetview/metadata)). | **External** road geometry (OSM / Mapbox / Roads) **or** optional **Tile API** metadata for native graph. |
| Batch hardcodes `heading_mode: RADIAL_OR_RANDOM` and `radius_m: 120` (`tools/batch_streetview_hints.py` L135–L142). | CLI mirrors service policy; `radius_m` meaningful only for legacy / decoy modes. |

---

## 1. Work breakdown structure (projects)

| ID | Project | Outcome |
|----|---------|---------|
| **PR-A** | **API contract & DTOs** | Versioned `PanosSampleRequest` / `PanosSampleResponse` extensions; backward compatible defaults. |
| **PR-B** | **Google HTTP layer** | `pano=` vs `location=` Static URLs; metadata error taxonomy; optional digital signature hooks. |
| **PR-C** | **Sampling core** | Replace radial-offset loop with mode router + cache_key includes policy + bearing provenance. |
| **PR-D** | **Road bearing providers** | Pluggable `RoadBearingProvider` with OSM / Mapbox / Google Roads; optional Tile API adapter. |
| **PR-E** | **Stub & parity** | Stub implements same `heading_mode` surface (synthetic headings) for CI contract tests. |
| **PR-F** | **Batch & Jobs** | `batch_streetview_hints.py` + HF hydration entrypoints pass new fields; `model_pins` extended. |
| **PR-G** | **Observability & resilience** | HTTP status mapping, retries, rate-limit awareness, structured logging. |
| **PR-H** | **Testing & CI** | Unit + integration tests; optional VCR/small JPEG fixtures; no secret leakage. |
| **PR-I** | **Documentation & plans** | SPEC + master streetview plan + backlog rows + `inference/README.md`. |
| **PR-J** | **Optional advanced** | Multi-pano walk, Tile API, pitch/FOV sweeps, game-server forward (IMP-092 extension). |

Dependencies: **PR-A** → **PR-B**, **PR-C**; **PR-D** feeds **PR-C**; **PR-E** parallel to **PR-B**; **PR-F** after **PR-A**+**PR-C** stable; **PR-H** throughout.

---

## 2. Project PR-A — API contract & DTOs

### Activity A1: Normalize `heading_mode` and optional request fields

**File:** `inference/streetview_pano_service/src/streetview_pano_service/models.py`

| Task | Detail |
|------|--------|
| **A1.T1** | Introduce a **literal union** or **Enum** for `heading_mode` values: `OMNI`, `PERPENDICULAR_TO_ROAD`, `LEGACY_RADIAL_OFFSET` (preserve old geographic offset behavior). Map legacy client string `RADIAL_OR_RANDOM` → `LEGACY_RADIAL_OFFSET` **or** treat as alias in validator (document breaking vs non-breaking choice). |
| **A1.T2** | Add optional `road_bearing_deg: float | None` (0–360, clockwise from north): when set by trusted batch, pano service **skips** external road provider for that request. |
| **A1.T3** | Add optional `fov_deg: int | None` (bounded 10–120 per Static API); default `75` when unset. |
| **A1.T4** | Add optional `pitch_spread_deg: float` default `0` for symmetric ± spread around `pitch_deg` baseline (see PR-J). |
| **A1.T5** | Extend `PanosSampleResponse` with optional **`sampling_debug: dict`** (gated by env `STREETVIEW_EXPOSE_SAMPLING_DEBUG=1`) containing `heading_mode_effective`, `road_bearing_source`, `road_bearing_deg`, `fallback_reason` — **never** include API keys. |

**Line-level subtasks (`models.py`):**

- **L13–L21** (current `PanosSampleRequest`): replace free `heading_mode: str` with constrained type + Field description referencing this plan §4.
- **L23–L28** (`PanoFrame`): consider optional `sampling_mode_tag: str | None` per frame (`"facade_left"`, `"omni_3"`, `"legacy_offset_2"`) for downstream `model_pins` / audit without breaking OpenAPI clients that ignore unknown fields (Pydantic extra policy: `ignore`).

### Activity A2: OpenAPI / internal doc sync (if any generated client consumes pano DTO)

**Files:** `docs/openapi.yaml` (only if public or partner-facing doc includes pano sample); otherwise **`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`** §2.2 JSON sketch only.

| Task | Detail |
|------|--------|
| **A2.T1** | Update §2.2 example JSON in `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` request/response with new fields. |

---

## 3. Project PR-B — Google HTTP layer (`google_static.py`)

### Activity B1: Metadata requests

**File:** `inference/streetview_pano_service/src/streetview_pano_service/google_static.py`

| Task | Detail |
|------|--------|
| **B1.T1** | Keep `fetch_metadata(lat, lon, …)` **L33–L39**; add typed wrapper returning a small **`MetadataResult`** dataclass: `status`, `pano_id`, `location_lat`, `location_lng`, `raw` dict for debug. |
| **B1.T2** | **Line L34:** ensure `location` formatting matches Google expectations (7 dp already fine); add optional `radius` query if product wants nearest-within-meters (Static Metadata documents accuracy ~50 m; evaluate `radius` parameter per [metadata](https://developers.google.com/maps/documentation/streetview/metadata)). |
| **B1.T3** | Classify `status` not in `OK`: raise **`StreetViewMetadataError`** subclass with `status`, `lat`, `lon` for HTTP mapping in `main.py`. |

### Activity B2: Static imagery — `pano=` vs `location=`

**File:** same `google_static.py`

| Task | Detail |
|------|--------|
| **B2.T1** | Refactor `fetch_static_jpeg` **L42–L73**: signature becomes `fetch_static_jpeg(*, api_key, heading, pitch, fov, width, height, location=(lat,lon)|None, pano_id=str|None, timeout=...)`. **Exactly one** of `location` or `pano_id` required. |
| **B2.T2** | **Lines L54–L61:** build `urlencode` dict: if `pano_id`: `pano`, `key`; else `location`, `key`; always `size`, `heading`, `pitch`, `fov`. |
| **B2.T3** | **Lines L67–L72:** preserve JPEG magic-byte check; add distinct error messages for HTML error bodies vs quota. |
| **B2.T4** | **Optional:** read `GOOGLE_STREETVIEW_URL_SIGNING_SECRET` (or documented name) and append `signature` when URL signing required for production keys ([Get a Key and Signature](https://developers.google.com/maps/documentation/streetview/get-api-key)). |

---

## 4. Project PR-C — Sampling core (`google_sample.py`, `sample_frames.py`, `sample_dispatch.py`)

### Activity C1: Google sampling router

**File:** `inference/streetview_pano_service/src/streetview_pano_service/google_sample.py`

Replace monolithic **L13–L62** with decomposed functions:

| Task | Detail |
|------|--------|
| **C1.T1** | **Delete conceptual use** of per-frame `offset_lat_lon` for default mode; retain in **`sample_panos_google_legacy_radial`** (callable from router when `heading_mode==LEGACY_RADIAL_OFFSET`). |
| **C1.T2** | **New `sample_panos_google_single_pano`:** after metadata OK, resolve `pano_id` + snapped `location`; for each `i in range(n)`, call `fetch_static_jpeg(..., pano_id=..., heading=schedule[i], pitch=pitch_schedule[i], fov=fov_i)`. |
| **C1.T3** | **Heading schedules:** implement `_headings_omni(n)`, `_headings_perpendicular(road_bearing_deg, n, spread_policy)` returning `list[float]`. |
| **C1.T4** | **`pano_id` on `PanoFrame`:** use stable per-frame id **without** fabricating `{pid}-{i}` if product wants true pano id for dedupe — e.g. `pano_id` field = logical pano + `viewpoint_suffix` optional; **minimum:** document that `viewpoint_id` in batch uses `pano_id` string from frame (today batch uses `fr.get("pano_id")`). Align with LFM `HintFrame.pano_id`. |
| **C1.T5** | **`cache_key` L56:** extend digest inputs: `[center_lat, center_lon, n, heading_mode, road_bearing_deg|None, fov, pitch_digest]` sorted JSON. |

**Line-level subtasks (current `google_sample.py`):**

- **L15–L17:** update docstring: remove “radial offsets for decoy diversity” as default; point to `LEGACY_RADIAL_OFFSET`.
- **L30–L35:** **remove** default path; move to legacy function only.
- **L46–L49:** when using single pano, `pano_id` field may be identical across frames; if downstream requires uniqueness, set `PanoFrame.pano_id` to `f"{base_pano_id}#h{int(heading)}"` **without** breaking Static `pano=` (use base id for HTTP, display id for LFM).

### Activity C2: Stub sampling parity

**File:** `inference/streetview_pano_service/src/streetview_pano_service/sample_frames.py`

| Task | Detail |
|------|--------|
| **C2.T1** | **L27–L56 `sample_panos_stub`:** read `req.heading_mode`; for `OMNI` keep headings `i*360/n`; for `PERPENDICULAR_TO_ROAD` use `req.road_bearing_deg` if provided else behave as `OMNI` and set synthetic `road_bearing_deg=0` in debug; for `LEGACY_RADIAL_OFFSET` emulate offset diversity in **hue** or **pano_id** suffix only (no real geo). |
| **C2.T2** | **L37–L38:** derive `heading` from schedule helper shared with google module (**new** `heading_schedules.py` to avoid circular imports). |

### Activity C3: Dispatch wiring

**File:** `inference/streetview_pano_service/src/streetview_pano_service/sample_dispatch.py`

| Task | Detail |
|------|--------|
| **C3.T1** | **L12–L22:** before `sample_panos_google`, resolve effective road bearing: if `req.road_bearing_deg is not None`, use it; else call `RoadBearingProvider` from PR-D when mode requires it. |
| **C3.T2** | Pass resolved bearing into `sample_panos_google(..., road_bearing_deg=...)`. |

---

## 5. Project PR-D — Road bearing providers (required + optional)

### Activity D1: Abstract interface + cache

**New file:** `inference/streetview_pano_service/src/streetview_pano_service/road_bearing.py`

| Task | Detail |
|------|--------|
| **D1.T1** | Define `Protocol` / ABC: `def nearest_tangent_bearing_deg(self, lat: float, lon: float) -> float | None`. |
| **D1.T2** | Implement **`FileCachedProvider`** wrapper: cache key `sha256(provider_name|lat_round|lon_round)` JSON `{"bearing":..., "ts":...}` under `${STREETVIEW_ROAD_CACHE_DIR:-~/.cache/nutonic-streetview-road}`}. |

### Activity D2: OSM Overpass (MVP provider)

**New file:** `inference/streetview_pano_service/src/streetview_pano_service/road_bearing_osm.py`

| Task | Detail |
|------|--------|
| **D2.T1** | Build Overpass QL: ways with `highway` in allowed classes within `radius_m` (env `OSM_OVERPASS_RADIUS_M` default 60). |
| **D2.T2** | Parse response; project (lat,lon) to closest segment; compute bearing of segment (atan2 of projected vector in local ENU). |
| **D2.T3** | Env: `OSM_OVERPASS_URL` (default public instance with **rate limit** warning), `OSM_OVERPASS_TIMEOUT_SEC`. |
| **D2.T4** | **Line-level:** isolate HTTP in `_post_overpass(query: str) -> dict` for mock injection in tests. |

### Activity D3: Mapbox provider (optional implementation)

**New file:** `inference/streetview_pano_service/src/streetview_pano_service/road_bearing_mapbox.py`

| Task | Detail |
|------|--------|
| **D3.T1** | Use **Mapbox Directions API** or **Map Matching**: e.g. request walking route from `(lon,lat)` to a second point 25 m along a cardinal; first step bearing = tangent approximation — **document limitation** in module docstring. |
| **D3.T2** | Env: reuse `MAPBOX_ACCESS_TOKEN` (same as `data/scripts/render_mapbox_still.py` / `.env` pattern). |
| **D3.T3** | **Line-level:** single function `mapbox_bearing_from_directions(lon, lat, token) -> float | None`. |

### Activity D4: Google Roads API (optional implementation)

**New file:** `inference/streetview_pano_service/src/streetview_pano_service/road_bearing_roads_api.py`

| Task | Detail |
|------|--------|
| **D4.T1** | Call **Snap to Roads** with points along a micro polyline around `(lat,lon)`; infer tangent from consecutive snapped points (handle collinearity). |
| **D4.T2** | Env: `GOOGLE_ROADS_API_KEY` or reuse maps key if product allows; document **separate billing** SKU. |

### Activity D5: Street View Tile API metadata (optional advanced)

**New file:** `inference/streetview_pano_service/src/streetview_pano_service/streetview_tiles_metadata.py`

| Task | Detail |
|------|--------|
| **D5.T1** | Implement OAuth / API key flow per [Street View Tiles](https://developers.google.com/maps/documentation/tile/streetview); fetch metadata including **`links`** when available. |
| **D5.T2** | Derive tangent from **vector of link headings** (mean of opposite pairs) or graph BFS “forward” link closest to catalog approach vector. |
| **D5.T3** | **Implications:** new GCP enablement, possible **org policy** review, **transient pano IDs** per Google warnings — persist only coordinates + policy version in manifests. |

### Activity D6: Provider selection config

**File:** `inference/streetview_pano_service/src/streetview_pano_service/pano_config.py`

| Task | Detail |
|------|--------|
| **D6.T1** | **L16–L22:** extend `PanoServiceSettings` with `road_bearing_provider: Literal["none","osm","mapbox","google_roads","tiles"]`, timeouts, cache dir. |
| **D6.T2** | Env matrix documented in `inference/streetview_pano_service/README.md` (create if missing) + `inference/README.md` table row update. |

---

## 6. Project PR-E — HTTP surface & errors (`main.py`)

**File:** `inference/streetview_pano_service/src/streetview_pano_service/main.py`

| Task | Detail |
|------|--------|
| **E1.T1** | **`pano_metadata` L41–L53:** return structured errors instead of generic `error` string when metadata fails; include `status` from Google body. |
| **E1.T2** | **`_panos_sample_impl` L56–L61:** map `StreetViewMetadataError` → **503**; map quota / timeout → **429** / **504** via FastAPI `HTTPException`. |
| **E1.T3** | **`health` L29–L38:** add fields: `road_bearing_provider`, `road_bearing_cache_enabled`, `heading_modes_supported[]`, `static_supports_pano_param: true`. |

**Line-level:**

- **L56–L61:** wrap `sample_panos` in try/except translating domain errors.

---

## 7. Project PR-F — Batch, hydration, `model_pins`

### Activity F1: Batch driver request body

**File:** `tools/batch_streetview_hints.py`

| Task | Detail |
|------|--------|
| **F1.T1** | **`_pano_sample` L126–L152:** extend `body` with `heading_mode` from new CLI `--pano-heading-mode` (default `PERPENDICULAR_TO_ROAD`). |
| **F1.T2** | **`L139` `radius_m`:** document as **legacy-only**; default `120` when `LEGACY_RADIAL_OFFSET`; for perpendicular modes optionally `0` or omit when API allows. |
| **F1.T3** | Add `--pano-road-bearing-deg` optional float for lab reproducibility (passed through to service). |
| **F1.T4** | **`BatchConfig` L44–L68:** add fields; **L504–L528** argparse + `BatchConfig(...)` wiring. |
| **F1.T5** | **`_pano_model_pin` L266–L276:** include `heading_mode`, `road_bearing_provider`, `cache_key` prefix version bump `api: "api/v1/panos/sample@v2"` for manifest reproducibility. |

### Activity F2: Chunked LFM merge ranks (bugfix adjacent to batch)

**File:** `tools/batch_streetview_hints.py`

| Task | Detail |
|------|--------|
| **F2.T1** | When merging chunked LFM responses **L377–L388**, reassign **`rank`** globally 1..N after merge **before** `_validate_pack_suggestions` **L389**, or sort by `(chunk_index, intra_rank)` — **line-level:** after **L388** `extend`, run `_renumber_ranks(merged_suggestions)`. |

### Activity F3: HF Jobs hydration

**Files:** `tools/hf_jobs/entrypoint_hf_hydration.py`, `tools/run_hf_hydration_full.py`, `tools/run_local_full_hydration.py`

| Task | Detail |
|------|--------|
| **F3.T1** | Pass env vars for `STREETVIEW_ROAD_BEARING_PROVIDER`, Mapbox/OSM secrets from Hub secrets into subprocess that runs `batch_streetview_hints.py`. |
| **F3.T2** | Document in `tools/hf_jobs/README.md` the required secret names. |

---

## 8. Project PR-G — Observability, resilience, quotas

| Task | File | Detail |
|------|------|--------|
| **G1** | `google_static.py` | Exponential backoff wrapper for **429** / **5xx** on Static GET (configurable max retries, jitter). |
| **G2** | `google_sample.py` | Structured `logging` per POI `request_id`: metadata ms, per-frame static ms, bearing source. |
| **G3** | `plans/2026-04-13-prioritized-implementation-task-backlog.md` | Row **IMP-110**: mark sub-deliverables for Google prod sampling + rate limits **done** when PR-G lands. |
| **G4** | `server/docs/TOPOLOGY.md` | If game server later proxies pano calls, note quota fan-out (optional PR-J). |

---

## 9. Project PR-H — Testing & CI

### Activity H1: Unit tests (pano package)

**Directory:** `inference/streetview_pano_service/tests/`

| File / test | Tasks |
|-------------|-------|
| `test_google_static_mocked.py` | Assert query string contains `pano=` when `pano_id` passed; assert `location=` when not. **Line-level:** patch `httpx.Client.get` and inspect URL in **L36–L38** style tests. |
| **New** `test_heading_schedules.py` | Golden vectors for `_headings_perpendicular(τ, n=6)`. |
| **New** `test_road_bearing_osm.py` | Mock Overpass JSON; assert bearing for known synthetic way geometry. |
| `test_panos_sample.py` | Extend payload with `heading_mode`; assert stub frames differ by heading. |

### Activity H2: Integration tests (batch tool)

**Directory:** `tools/tests/`

| Task | Detail |
|------|--------|
| **H2.T1** | `test_batch_streetview_hints.py`: mock pano response including new JSON fields; verify forwarded body keys. |

### Activity H3: Optional VCR / golden JPEG

**Files:** `tools/tests/fixtures/streetview/` (new, **minimal** binary policy per `plans/2026-04-16-stub-replacement-implementation-plan.md`)

| Task | Detail |
|------|--------|
| **H3.T1** | One **tiny** valid JPEG (e.g. 32×32) returned by mocked Static for decode smoke. |
| **H3.T2** | Optional **vcrpy** cassette for Overpass (gzip JSON) — **no** real API keys in cassettes. |

### Activity H4: CI workflow

**File:** `.github/workflows/nutonic-ci.yml`

| Task | Detail |
|------|--------|
| **H4.T1** | Ensure new tests do not require `MAPBOX_*` / Google keys; use mocks only on default job. |
| **H4.T2** | Optional **nightly** job with `workflow_dispatch` + secrets for real Google smoke (document in workflow comments). |

---

## 10. Project PR-I — Documentation & cross-plan edits

| File | Tasks |
|------|-------|
| `docs/scripts/SPEC-batch-streetview-hints.md` | §1.1 **S1** table: replace “RADIAL_OR_RANDOM” with mode list; document CLI flags; document `model_pins` v2. |
| `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` | §2.2 JSON; §3 sampling narrative; reference this plan. |
| `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md` | Phase **D** bullet: link bearing providers + manifest `model_pins`. |
| `inference/README.md` | Extend **`streetview_pano_service/`** row with env vars summary. |
| `inference/streetview_pano_service/README.md` | **Create** full env + mode matrix + troubleshooting (ZERO_RESULTS, OVER_QUERY_LIMIT). |
| `tools/README.md` | Update example `uvicorn` + batch command lines with new flags. |

---

## 11. Project PR-J — Optional advanced (explicitly in scope)

### J1: Multi-pano “walk” along Street View graph

| Task | Detail |
|------|--------|
| **J1.T1** | When `heading_mode=WALK_GRAPH` (new), use Tile metadata **links** or repeated metadata `pano=` neighbor discovery to collect **K** distinct `pano_id`s along **shortest graph path** away from center (cap **max_walk_m**). |
| **J1.T2** | Static requests: mix of `pano=` per step; headings mostly **perpendicular** at each stop for facade richness **or** forward link heading ±90° policy switch. |
| **J1.T3** | **Implications:** higher Static **quota** (K panos); longer batch latency; `cache_key` must include walk seed + graph version. |

### J2: Pitch and FOV schedules

| Task | File | Detail |
|------|------|--------|
| **J2.T1** | `models.py` | Optional `fov_per_frame: list[int] | None` or `fov_deg` + `fov_jitter`. |
| **J2.T2** | `google_sample.py` | `pitch = base_pitch + schedule[i]` for small ±5° to capture signs / sky; **ranked_clue_safe** review (more readable text). |

### J3: LFM prompt alignment

**File:** `inference/lfm_vl_hint_service/src/lfm_vl_hint_service/prompts.py`

| Task | Detail |
|------|--------|
| **J3.T1** | **L8–L27 `streetview_user_prompt`:** mention “facade / sidewalk orthogonal views” when `mission_flavor` or new optional request field `view_axis=facade` passed from batch (requires **PR-K** small extension to `SuggestionsFromFramesRequest` in `lfm_vl_hint_service/models.py` **L17–L22**). |

### J4: Game server / IMP-092 forward

**Files:** `server/src/nutonic_server/…` (when product enables live pano fetch)

| Task | Detail |
|------|--------|
| **J4.T1** | Forward `heading_mode` from server config to worker URL builder — **only** if orchestrator plan requires; otherwise **explicit non-goal** for ranked live fetch (batch-only remains default). |

### J5: Kotlin / manifest consumer hints

**Files:** `nutonic/shared/...` (DTOs), `docs/openapi.yaml` if `streetview_hint_pack` gains optional provenance

| Task | Detail |
|------|--------|
| **J5.T1** | Optional non-breaking fields on manifest sidecar: `streetview_sampling_version`, `road_bearing_provider` string — gated by `assemble_manifest.py` merge rules (`data/scripts/assemble_manifest.py`). |

---

## 12. Risk register & mitigations

| Risk | Mitigation |
|------|------------|
| Overpass public instance throttled | File cache + backoff + self-hosted Overpass option env. |
| Mapbox tangent from Directions is coarse | Document; prefer OSM geometry when available; allow `road_bearing_deg` override from curated dataset column (future catalog field). |
| Perpendicular views increase readable PII in ranked | Tune `ranked_clue_safe` prompts (`prompts.py` **L16–L21**); optional blur pre-step (out of scope unless product requests). |
| `pano` IDs transient | Google doc: refresh via saved lat/lon; manifests store **policy + model_pins**, not pano id as sole key. |
| Breaking API clients sending `RADIAL_OR_RANDOM` | Pydantic validator maps alias → `LEGACY_RADIAL_OFFSET` + log **once** at startup. |

---

## 13. Definition of done (program-level)

1. **Default** Google batch run: **real Static JPEGs**, **single pano**, **`pano=`**, headings **`PERPENDICULAR_TO_ROAD`** with OSM (or configured provider) and **OMNI** fallback when bearing unknown.  
2. **`heading_mode`** fully implemented in **stub + google** paths; **legacy** mode preserves old behavior for regression.  
3. **Docs + SPEC + streetview plan** updated; **IMP-110** backlog text updated.  
4. **Tests** green without secrets; optional nightly proves real Google path.  
5. **Optional PR-J** items either merged behind feature flags **or** tracked as checkboxes in this file with owner/date when deferred.

---

## 14. Checkbox tracker (optional items)

- [ ] **J1** Multi-pano `WALK_GRAPH` + Tile API  
- [ ] **J2** Pitch / FOV schedules  
- [ ] **J3** LFM `view_axis` / prompt tuning  
- [ ] **J4** Game server forward IMP-092  
- [ ] **J5** Manifest provenance fields + `assemble_manifest`  
- [ ] **B2.T4** URL signing for Static  
- [ ] **D4** Google Roads provider  
- [ ] **D5** Tile API metadata provider  
- [ ] **H3** VCR / golden JPEG  
- [ ] **H4.T2** Nightly real Google CI job  

---

## 15. References (external)

- [Street View Static API overview](https://developers.google.com/maps/documentation/streetview/overview)  
- [Street View Image Metadata](https://developers.google.com/maps/documentation/streetview/metadata)  
- [Street View Tiles API](https://developers.google.com/maps/documentation/tile/streetview)  

---

**Document history**

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| 0.1 | 2026-04-18 | Planning agent | Initial full-scope WBS with file/line tasks. |
| 0.2 | 2026-04-18 | Planning agent | **Aligned plans:** authority block lists backlog, gap analysis **v1.3**, shipped-cache **v1.0**, streetview inference plane §2.2, stub-replacement **STUB-A**, data-scripts **P6.7**, planning series index **v1.0**. |
