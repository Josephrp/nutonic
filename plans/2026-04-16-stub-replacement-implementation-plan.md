# NU:TONIC — Stub replacement: detailed implementation plans (full scope)

**Date:** 2026-04-16  
**Status:** Actionable engineering plan — **all items below are in scope** per product direction to replace development stubs with **production-capable** data generation, inference surfaces, and client hooks.  
**Authority:** `plans/2026-04-16-cached-poi-hydration-ranked-and-nonranked-plan.md` **§7**, `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`, `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`, **`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`** (**IMP-110** / **STUB-A** file-level WBS), `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`, `plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md`, `plans/2026-04-13-prioritized-implementation-task-backlog.md` (**IMP-051**, **IMP-084**, **IMP-092**, **IMP-110–114**), `rules/06-server-vlm-tim-and-on-device-ml.md`, `rules/12-python-gradio-terramind-server.md`, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`, `docs/scripts/SPEC-*.md`.

**Companion:** [`plans/2026-04-16-cached-poi-hydration-ranked-and-nonranked-plan.md`](2026-04-16-cached-poi-hydration-ranked-and-nonranked-plan.md) (client manifest / ranked pack / bundle cache — this document covers **generators and services** that feed those artifacts).

---

## 0. Executive summary

| Workstream | ID | Outcome |
|------------|-----|---------|
| A — Street View pano | **STUB-A** | **Google (or agreed) real pano + metadata** path is default in **deployed** images; stub remains **explicit opt-in** for CI and air-gapped dev. |
| B — LFM-VL hints | **STUB-B** | **Non-stub default** in GPU/ZeroGPU images: **`transformers`** or **`openai_compatible`**; stub only for **`pytest`** and local dry-run. |
| C — Satellite captions | **STUB-C** | Same pattern as B for **`lfm_vl_satellite_caption_service`**. |
| D — PRO materialization | **STUB-D** | **`/api/v1/materialize/stub`** retained **deprecated**; primary path **`/internal/v1/materialize`** + STAC/S2 per **IMP-113**; server jobs use **IMP-092** client. |
| E — LLM batch scripts | **STUB-E** | **`narrative_llm_batch`** and **`generate_useful_hints_llm`** perform **real HTTP** to Ollama/OpenAI-compatible endpoints with **schema + policy validation** on output. |
| F — BGM placeholders | **STUB-F** | Replace silent WAV stubs with **shipped loops** per **`docs/SCREEN-MUSIC-SPEC.md`** + **IMP-051** (or document licensed source pipeline). |
| G — TerraMind TiM local inputs | **STUB-G** | **No `NotImplementedError`** on **catalog-supported** `tim_modalities`; unsupported modalities **fail fast at catalog lint** with a clear matrix doc. |
| H — Game server orchestration | **STUB-H** | **`InferenceClient`** (timeouts, HMAC, retries) reads **`STREETVIEW_*`**, **`LFM_VL_*`**, **`PRO_MATERIALIZATION_*`** from env; integration tests mock upstreams. |
| I — Client share hook | **STUB-I** | **IMP-084**: platform **`expect`/`actual`** share for scorecard / deep link per **`rules/04`** / **`docs/SOCIAL-AND-COMPETITION.md`**. |

**Sequencing rule:** **STUB-H** should land **early** (interfaces + tests) so **A–D** can be validated from **`server/`** without copy-pasting **`httpx`** blocks. **STUB-E** can parallel **B** (different repo paths). **STUB-F** and **STUB-I** are **client/audio** and can ship independently of GPU inference.

---

## 1. Global conventions (all workstreams)

### 1.1 Secrets and config

- **Never** commit API keys; document in **`server/README.md`**, **`inference/*/README.md`**, and **`.env.example`** at repo root.
- **Inference HMAC:** align on **`NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC`**, **`NUTONIC_INFERENCE_HMAC_SECRET`** (already partially used in pano service).
- **Log pins:** every batch output and inference response logs **`model_id`**, **`revision`**, **`prompt_template_version`**, **`lfm_backend` / `streetview_provider`** for manifest **`model_pins`** (see **`shipped-cache`** plan L2/L5).

### 1.2 CI strategy (dual lane)

| Lane | Purpose |
|------|---------|
| **Fast lane** (default PR) | **`pytest`** with **stub** backends; **`data-scripts`** job unchanged in spirit — no GPU, no network to Google. |
| **Quality lane** (nightly / `workflow_dispatch` / protected branch) | Optional job: **smoke** `batch_streetview_hints` with **real** services behind secrets **or** pre-recorded **VCR**/golden JPEG fixtures checked into `data/scripts/tests/fixtures/` (prefer **no** binary growth — use **small** 1×1 real JPEG once if policy allows). |

### 1.3 OpenAPI and prose cleanup

- Remove “stub only” wording from **`docs/openapi.yaml`** where behavior is **real**; keep **“optional deployment”** language for features behind **`features.*`**.

---

## 2. Workstream A — `streetview_pano_service` (STUB-A, **IMP-110**)

**Normative drill-down:** `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` §2. **File/line WBS (supersedes table granularity below until closed):** [`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](2026-04-18-streetview-google-perpendicular-sampling-full-scope.md) (**PR-A–PR-J**). Treat **§2 A.1–A.3** in *this* document as narrative phases; implementers follow the **2026-04-18** plan for concrete modules (`road_bearing_*.py`, `heading_schedules`, `pano=` Static, batch flags).

### A.0 Current state

- **`sample_dispatch`**: Google when key + provider; else **Pillow stub** (`sample_frames.py`).
- **`pano_metadata`**: stub echo when not Google.

### A.1 Phase A1 — Metadata and availability (CPU)

| Task | Detail |
|------|--------|
| A1.1 | Implement **`fetch_metadata`** success path coverage: **`pano_id`**, **`location`**, **`copyright`**, **`date`**, **`status`** per [Street View Image Metadata](https://developers.google.com/maps/documentation/streetview/metadata) — **Classic Metadata does not return `links`**; graph **`links`** / native navigation only on optional **Street View Tiles** track (**`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`** **PR-D**/**PR-J**). Map **all** error codes to **HTTP 4xx/502** with stable JSON **`{ "error_code", "message" }`** (no key leakage). |
| A1.2 | Add **retry + backoff** for transient failures (`httpx` + jitter). |
| A1.3 | **Tests:** mock `httpx` responses; assert no network in default **`pytest`**. |

**Exit:** `GET /api/v1/pano/metadata` returns **`status: "ok"`** with real **`pano_id`** when **`STREETVIEW_PROVIDER=google`** and key present in CI **quality lane** (or VCR).

### A.2 Phase A2 — Static image sampling

| Task | Detail |
|------|--------|
| A2.1 | **`sampling.py`** (or extend existing modules): heading/pitch policy, **`count`**, **`radius_m`**, size caps per **`docs/GAME-ENGINE.md` §9**. |
| A2.2 | **`fetch.py`**: Street View Static URL builder, **max dimensions** server-side clamp. |
| A2.3 | **Optional disk cache:** key = hash(lat, lon, policy, size); LRU under **`NUTONIC_PANO_CACHE_DIR`** with max MB env. |
| A2.4 | **Tests:** golden file hash for **one** fixed request (stub or recorded). |

**Exit:** `POST /api/v1/panos/sample` returns **JPEG** frames with **`pano_id`** set for Google path; stub path unchanged for fast lane.

### A.3 Phase A3 — Ops and deploy

| Task | Detail |
|------|--------|
| A3.1 | **Dockerfile** CPU-only image size budget; document **`GOOGLE_MAPS_API_KEY`** rotation. |
| A3.2 | **`tools/hf_deploy`** profile for **`streetview_pano_service`** (if not already): env table in **`tools/hf_deploy/README.md`**. |
| A3.3 | **Rate limit** middleware optional: IP + API key quota headers surfaced in **`/health`**. |

**Exit:** Space or container deploy doc + **`huggingface-deploy.yml`** matrix entry verified once manually.

### A.4 Dependencies

- **Before:** none blocking.  
- **Consumers:** **`tools/batch_streetview_hints.py`**, future **server** batch orchestration (**STUB-H**).

---

## 3. Workstream B — `lfm_vl_hint_service` (STUB-B, **IMP-111**)

### B.0 Current state

- **`dispatch.py`**: **`stub`**, **`transformers`**, **`openai_compatible`** branches exist; **default stub** for CI.
- **`narrative_fuse_text`**: stub = string join.

### B.1 Phase B1 — Make non-stub the deploy default

| Task | Detail |
|------|--------|
| B1.1 | **HF Docker image / Space:** set **`LFM_VL_BACKEND=transformers`** (or **`openai_compatible`** pointing at vLLM) in **`tools/hf_deploy/profiles/lfm_vl_hint.yaml`** + README. |
| B1.2 | **Pin** `LFM_VL_MODEL_ID` revision in env; document upgrade playbook (change pin → rerun batch → bump **`content_version`**). |
| B1.3 | **CI:** keep **`stub`** for **`pytest`**; add **optional** nightly job: pull image with **`[model]`** extra and run **one** `test_from_frames_transformers` if GPU runner available **or** skip. |

**Exit:** Deployed profile README states **“production = non-stub”**; local default remains stub unless developer opts in.

### B.2 Phase B2 — Narrative fuse (non-stub)

| Task | Detail |
|------|--------|
| B2.1 | Implement **`narrative_fuse_transformers`** / **`narrative_fuse_openai`** to produce **single** fused string under **max length** (reuse caption model or lightweight text-only model per cost analysis). |
| B2.2 | **`validate_hint_strings`**-style validation: **no coordinate literals** in fused output (regex + tests). |
| B2.3 | Wire **`POST /v1/narrative/fuse`** to use fused path when backend ≠ stub. |

**Exit:** `test_narrative_fuse.py` covers **stub** (join) and **mocked** non-stub path.

### B.3 Phase B3 — Gradio / ZeroGPU

| Task | Detail |
|------|--------|
| B3.1 | **`LFM_VL_MOUNT_GRADIO=1`**: ensure **`spaces.GPU`** decorator on forward if required by HF; document cold start. |
| B3.2 | Ops panel: model pin, VRAM smoke, **no** secrets in UI. |

**Exit:** Manual HF Space smoke checklist in **`inference/lfm_vl_hint_service/README.md`**.

---

## 4. Workstream C — `lfm_vl_satellite_caption_service` (STUB-C, **IMP-112**)

**Normative:** `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`.

### C.1 Phase C1 — Parity with B

| Task | Detail |
|------|--------|
| C1.1 | Mirror **`dispatch.py`** pattern: **`LFM_SATELLITE_BACKEND`** = **`stub` | `transformers` | `openai_compatible`**. |
| C1.2 | **`infer_transformers.py`** (or extend): specialist model id env; **input** = Mapbox still bytes (same contract as today **`POST /v1/infer`**). |
| C1.3 | **Tests:** stub default; one **mocked** transformers test optional. |

### C.2 Phase C2 — Batch integration

| Task | Detail |
|------|--------|
| C2.1 | **`tools/batch_streetview_hints.py`**: when **`satellite_caption_service_url`** set, call **`POST /v1/infer`** with **`task=caption`**; merge **`satellite_caption_sidecar`** into per-location JSON **already** supported downstream. |
| C2.2 | Document **latency** and **timeout** in **`SPEC-batch-streetview-hints.md`**. |

**Exit:** End-to-end batch run produces **non-stub** `satellite_caption_sidecar` in output JSON when URL + backend configured.

---

## 5. Workstream D — `pro_materialization_service` (STUB-D, **IMP-113** / **IMP-114**)

### D.0 Current state

- **`POST /api/v1/materialize/stub`**: thin pin response.
- **Internal** **`/internal/v1/materialize`**: Mapbox branch + optional S2 with **`[s2]`** extra.

### D.1 Phase D1 — Deprecate stub path in docs, keep in code

| Task | Detail |
|------|--------|
| D1.1 | Mark **`/materialize/stub`** **`deprecated`** in OpenAPI + FastAPI **`deprecated=True`**; README: “use internal materialize or server **PRO jobs**”. |
| D1.2 | Ensure **internal** path returns **same schema fields** server **`_summarize_materialize_worker_response`** expects — **add contract test** server ↔ worker. |

### D.2 Phase D2 — STAC / TiM NPZ completeness

| Task | Detail |
|------|--------|
| D2.1 | Implement remaining **`RGB_mapbox`** / **`S2L2A`** matrix rows from **`plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md`**. |
| D2.2 | Byte caps + **error body** when cap exceeded (already partially specified). |

### D.3 Phase D3 — Server PRO jobs (**IMP-114** + **STUB-H**)

| Task | Detail |
|------|--------|
| D3.1 | Replace ad-hoc **`httpx`** in **`server/main.py`** with **`InferenceClient.post_materialize`** (timeouts, HMAC, retry **idempotent** GET status if added). |
| D3.2 | Persist job rows in SQLite. |

**Exit:** `test_pro_job_stub_when_enabled` renamed/supplemented with **“real worker URL mock”** test asserting headers and timeout.

---

## 6. Workstream E — `data/scripts` LLM batches (STUB-E)

### E.1 `narrative_llm_batch.py`

| Phase | Tasks | Exit |
|-------|-------|------|
| **E1.1** | Parse **`prompts/llm/*.md`**; build variable map from **`data/cache/.../geo_context`** + catalog (**no golden coords** in ranked-safe mode per SPEC). | Dry-run produces **non-empty** `entries[]` template preview in stdout (no network). |
| **E1.2** | Implement **`--backend ollama`**: `httpx` POST to **`OLLAMA_HOST`** with **timeout**, stream off, JSON parse. | Integration test behind **`pytest.mark.integration`** + env skip. |
| **E1.3** | Implement **`--backend openai`**: OpenAI-compatible **`chat/completions`** with **system** + **user** messages from templates. | Same. |
| **E1.4** | Write **`llm_sidecar.json`** schema version bump if needed; **`validate`** step: length caps, banned substrings (coords). | **`SPEC-narrative-llm-batch.md`** status → **implemented**; **`data/scripts/tests`** new file. |

### E.2 `generate_useful_hints_llm.py`

| Phase | Tasks | Exit |
|-------|-------|------|
| **E2.1** | Refactor shared **`llm_http.py`** in `data/scripts/` (used by E1 and E2): retries, JSON mode, **model_pins** logging. | Unit tests with **`httpx.MockTransport`**. |
| **E2.2** | **`--enable-llm-polish --no-dry-run`**: read compiled tiers JSON, send to backend, **`validate_hint_strings`** on response; write polished output dir. | Exit 0 on fixture; **`SPEC-generate-useful-hints-llm.md`** §5 implemented. |
| **E2.3** | Document **cost** and **determinism** (temperature 0 for reproducible CI lane optional). | |

---

## 7. Workstream F — BGM placeholders (STUB-F, **IMP-051**)

### F.1 Phase F1 — Asset sourcing

| Task | Detail |
|------|--------|
| F1.1 | Per **`docs/SCREEN-MUSIC-SPEC.md`**: define **loop count**, **format** (OGG vs WAV), **LUFS** target, **license** (original or licensed library). |
| F1.2 | Replace **`generate_placeholder_bgm_wav.py`** outputs under **`composeResources`** with **real** short loops **or** keep generator but emit **non-silent** 0.5s tone for dev only and **ship** real assets in **`main`**. |

### F.2 Phase F2 — Client wiring

| Task | Detail |
|------|--------|
| F2.1 | **`resolveNutonicBgmTrack`** per route (**IMP-051** backlog): wire **`PlatformBgmPlayer`** to **decode** shipped assets (expect/actual already pattern in rules). |

**Exit:** SETUP audio toggles affect **audible** loop; master mute still instant.

---

## 8. Workstream G — `terramind_tim_local` inputs (STUB-G)

### G.1 Phase G1 — Modality matrix

| Task | Detail |
|------|--------|
| G1.1 | Extract supported **`tim_modalities`** from **`rules/06`** + **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`** into **`terramind_tim_local/docs/MODALITY_MATRIX.md`**. |
| G1.2 | **`data/scripts`** catalog lint (or **`validate_catalog`**) rejects **`locations`** referencing unsupported modalities **before** TiM job. |

### G.2 Phase G2 — Implement or delegate

| Task | Detail |
|------|--------|
| G2.1 | For each **required** modality in v1 catalog: implement branch in **`inputs_build.py`** **or** call **external** preprocessor that returns NPZ path. |
| G2.2 | Replace bare **`NotImplementedError`** with **`ValueError`** with **actionable** message + link to matrix (still fail, but operator-friendly). |

**Exit:** **`RUN_TERRATORCH_TIM=1`** CI job passes for **smallest** modality set used by **`geoguessr_poi_12`**.

---

## 9. Workstream H — Server `InferenceClient` (STUB-H, **IMP-092**)

### H.1 Phase H1 — Module layout

| Task | Detail |
|------|--------|
| H1.1 | Add **`server/src/nutonic_server/inference_client.py`**: class **`InferenceClient`** with **`get_timeout`**, **`nutonic_hmac_headers`**, **`get_json`**, **`post_bytes`**, **`probe_health_origin`**. |
| H1.2 | Read env: **`STREETVIEW_PANO_SERVICE_URL`**, **`LFM_VL_HINT_SERVICE_URL`**, **`LFM_VL_SATELLITE_CAPTION_SERVICE_URL`**, **`PRO_MATERIALIZATION_SERVICE_URL`** (names aligned with **`server/README.md`**). |

### H.2 Phase H2 — Migrate call sites

| Task | Detail |
|------|--------|
| H2.1 | **`pro_create_job`**: use **`InferenceClient`** for health + materialize (already partial **httpx** — consolidate). |
| H2.2 | **Future:** ranked assist **forfeit** telemetry or **server-side** batch kick — stub hooks return **501** until implemented; client unchanged. |

### H.3 Phase H3 — Tests

| Task | Detail |
|------|--------|
| H3.1 | **`pytest`** with **`respx`** or **`httpx.MockTransport`**: timeout raises mapped exception; HMAC header present when secret set. |

**Exit:** **`server/README.md`** “Future variables” table updated — implemented vars **removed** from placeholder list.

---

## 10. Workstream I — Client share hook (STUB-I, **IMP-084**)

### I.1 Phase I1 — Contract

| Task | Detail |
|------|--------|
| I1.1 | Define share payload: **`map_id`**, **`location_id`**, last **distance_km** / **score** (non-ranked), **role**, **deep link** token per **`rules/01`**. |
| I1.2 | **Ranked:** share only **post-submit** summary or **disabled** until server confirms (product pick — document). |

### I.2 Phase I2 — Platform actuals

| Task | Detail |
|------|--------|
| I2.1 | **`expect fun shareNutonicScorecard(...)`** in `commonMain`; **`actual`** Android (**Chooser**), iOS (**UIActivityViewController** bridge or KMP lib), Desktop (**Desktop.getClipboard()` + optional file), Web (**navigator.share` or copy**). |
| I2.2 | Replace **`worldMapShareScoreStub`** onClick with real call + error snackbar. |

**Exit:** Manual test on **two** platforms; **`desktopTest`** smoke if clipboard assertable.

---

## 11. Dependency diagram

```text
STUB-H (InferenceClient)
    ├─► STUB-D (server → pro worker)
    └─► future batch orchestrator (optional)

STUB-A (pano) ──┐
STUB-B (LFM)  ├──► tools/batch_streetview_hints ──► assemble_manifest ──► client embed
STUB-C (sat)  ──┘

STUB-E (scripts) ──► shipped-cache narrative / hints tiers (parallel to A–C)

STUB-G (TiM inputs) ──► generate_ai_guess_fixture tim_only ──► manifest ai_guesses

STUB-F (BGM) ──► IMP-051 client audio (orthogonal)

STUB-I (share) ──► IMP-084 (orthogonal)
```

---

## 12. PR slicing recommendation

| PR | Contents |
|----|----------|
| **PR1** | **STUB-H** module + tests + README env table (**no** behavior change to PRO if URL unset). |
| **PR2** | **STUB-A** A1–A2 + tests (metadata + sample Google path behind mock). |
| **PR3** | **STUB-B** B1–B2 + hf_deploy profile bump. |
| **PR4** | **STUB-C** C1–C2. |
| **PR5** | **STUB-E** E1 + E2 + shared `llm_http.py`. |
| **PR6** | **STUB-D** D1–D3 + server uses **InferenceClient**. |
| **PR7** | **STUB-G** matrix + inputs + CI opt-in. |
| **PR8** | **STUB-F** + **STUB-I** (can split). |

---

## 13. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-16 | Initial stub-replacement implementation plan (workstreams A–I, CI dual lane, PR slices). |
| 0.2 | 2026-04-16 | Repo doc sync: cross-refs remain valid after **`docs/openapi.yaml`**, **`server/README.md`**, **`server/docs/TOPOLOGY.md`**, gap analysis **v1.2**, claims baseline **v0.9**, backlog **§0.1 v0.8** updates. |
| 0.3 | 2026-04-18 | **Authority** + **§2 STUB-A:** cross-ref **`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`**; **A1.1** corrected (Classic Metadata has no **`links`**; Tiles optional per **PR-J**). |
| 0.4 | 2026-04-20 | Cross-ref gap analysis **v1.4** — **`inference/pro_materialization_service/`** is **present** in the tree (§3 row corrected); **STUB-D** / **IMP-113** scope unchanged (hardening remains). |
