---
name: ZeroGPU PRO Gradio Space
overview: ""
todos:
  - id: contract-and-models
    content: Lock the PRO API contract for the Space (ProJobCreateIn/StatusOut/OnDevicePayload/VlmImageRef + ProVlmModelManifest) and mirror it as Pydantic models.
    status: completed
  - id: server-client-and-polling
    content: Implement the HTTP client layer (create job, poll job, fetch artifacts/by-url, fetch model-manifest) with robust timeouts and clear error handling.
    status: completed
  - id: gradio-aoi-ui
    content: Build the Gradio UI for PRO-like AOI selection (map click or lat/lon + zoom/bbox mapping) and wire it to job submission + progress display.
    status: completed
  - id: image-fetch-and-normalization
    content: Fetch the `vlm_image_set` images from completed jobs (role-priority logic) and normalize them into the format required by the Transformers VLM runtime.
    status: completed
  - id: local-transformers-vlm
    content: Run the final analysis locally in the Space on ZeroGPU using Transformers+Torch (download/cache `NuTonic/lspace` from model-manifest, validate sha256, lazy-load, `@spaces.GPU` inference).
    status: completed
  - id: parse-caption-boxes
    content: Parse model output into client-compatible `caption` + normalized `boxes[]` (aliases, JSON-first parsing, bbox validation/clamping) and emit `ProVlmResult`-shaped JSON.
    status: completed
  - id: render-outputs
    content: "Produce final outputs: raw image, annotated image with boxes+labels, and a JSON panel (job summary + prompt injection + model id/revision + timing)."
    status: completed
  - id: hf-space-deploy-integration
    content: Add `pro_gradio_demo` to `tools/hf_deploy` (profile YAML + README template + deploy registry) and optionally wire it into `.github/workflows/huggingface-deploy.yml`.
    status: completed
  - id: verification-and-guardrails
    content: Add smoke validation + runtime guardrails (polling timeout, model cache checks, friendly failure states when upstream services or model download fails).
    status: completed
isProject: false
---

# ZeroGPU PRO-tab Gradio Space Workaround

## What we’re building
A new Gradio SDK Space `Tonic/nutonic-pro-demo` that replicates the PRO tab flow by **calling the existing inference/game server APIs**, then presenting:
- **Map selection** (lat/lon + bbox radius/zoom like the client)
- **Run PRO analysis** (submit job → poll → fetch VLM image set / artifacts)
- **Return images** (raw + annotated overlay) plus caption/boxes JSON

This avoids on-device Liquid Leap entirely while preserving the same backend contract the app uses.

## Current system (investigation findings)
- **PRO job APIs used by clients** live in Kotlin client code:
  - `POST /api/v1/pro/jobs` and `GET /api/v1/pro/jobs/{job_id}` in [`nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiClient.kt`](C:/Users/MeMyself/nutonic/nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiClient.kt)
  - Image bytes via `GET /api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}` and/or `download_url` in [`NutonicApiClient.kt`](C:/Users/MeMyself/nutonic/nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiClient.kt)
- **Server-provided on-device payload** structure (we’ll reuse it in Space):
  - `ProJobCreateIn`, `ProJobStatusOut`, `ProOnDevicePayload`, `ProVlmImageRef` in [`nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiModels.kt`](C:/Users/MeMyself/nutonic/nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiModels.kt)
- **Overlay expectations** (what the Gradio demo should output):
  - `ProVlmResult` with `caption` + `boxes[]` normalized 
  - Rendering logic exists in [`nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/ProCoordinateDashboardDetail.kt`](C:/Users/MeMyself/nutonic/nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/ProCoordinateDashboardDetail.kt)
- **Map selection semantics** (zoom → bbox radius) exist in [`nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProAnalysisLocationPicker.kt`](C:/Users/MeMyself/nutonic/nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProAnalysisLocationPicker.kt)
- **Existing repo deployment pattern for ZeroGPU Spaces** is already implemented via `tools/hf_deploy`:
  - `tools/hf_deploy/deploy_space.py` stages a Gradio Space from an `inference/*` package + `app.py` + generated `requirements.txt` + template README, then uploads with `hf` CLI and syncs variables/secrets/hardware.

## Key decisions (locked in)
- **Space**: `Tonic/nutonic-pro-demo`
- **Integration**: continue to rely on the existing services/Spaces for PRO job materialization + brief fusion, but do the **final VLM analysis locally in this new Space** (ZeroGPU), using the fine-tuned model `NuTonic/lspace`.
- **Server origin config**: Space variable `NUTONIC_SERVER_ORIGIN`.
- **Auth**: none (Space will call public endpoints).

## Architecture / data flow
```mermaid
flowchart TD
  User[User] --> GradioUI[GradioUI]
  GradioUI -->|submit| ProJobCreate[POST_/api/v1/pro/jobs]
  GradioUI -->|poll| ProJobPoll[GET_/api/v1/pro/jobs/{job_id}]
  ProJobPoll -->|on_device_payload| Payload[ProOnDevicePayload]
  Payload --> ImageRefs[vlm_image_set[]]
  ImageRefs -->|fetch| ArtifactFetch[GET_/api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}]
  GradioUI -->|fetch| ModelManifest[GET_/api/v1/pro/vlm/model-manifest]
  ModelManifest -->|download| ModelWeights[model.safetensors]
  ArtifactFetch --> LocalVlm[Local_VLM_inference_ZeroGPU]
  ModelWeights --> LocalVlm
  LocalVlm --> Parse[Parse_caption_and_boxes_JSON]
  Parse --> Annotate[Draw_boxes_on_image]
  Annotate --> Outputs[Annotated_image+JSON]
```

## Project breakdown (with activities, file-level tasks, line-level subtasks)

### Project A — Mirror PRO-tab contract and run final VLM locally in a Gradio Space

#### Activity A1 — Implement the Space package skeleton
- **Add new service package directory**
  - **File-level tasks**:
    - Create [`inference/pro_gradio_demo/pyproject.toml`](inference/pro_gradio_demo/pyproject.toml)
      - Line-level subtasks:
        - Define `project.name` (e.g. `nutonic-pro-gradio-demo`).
        - Dependencies (orchestration/parsing/rendering): `httpx`, `pydantic`, `pillow`, `python-dotenv` (optional), `numpy` (only if needed).
        - Dependencies (local VLM via Transformers): `transformers`, `torch`, `accelerate`, `safetensors`, `huggingface_hub`.
        - Keep `gradio`/`spaces` out of dependencies (repo deploy script already filters them).
    - Create [`inference/pro_gradio_demo/app.py`](inference/pro_gradio_demo/app.py)
      - Line-level subtasks:
        - `from nutonic_pro_gradio_demo.gradio_app import build_demo`
        - `demo = build_demo()`
        - `if __name__ == "__main__": demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7860")))`
    - Create package module tree under [`inference/pro_gradio_demo/src/nutonic_pro_gradio_demo/`](inference/pro_gradio_demo/src/nutonic_pro_gradio_demo/)
      - `__init__.py`
      - `settings.py` (read `NUTONIC_SERVER_ORIGIN`, request timeouts)
      - `client.py` (httpx wrapper)
      - `models.py` (Pydantic models mirroring the minimal JSON contract)
      - `vlm_runtime.py` (download/cache model + local inference entrypoint)
      - `vlm_parse.py` (parse model output → caption + normalized boxes)
      - `render.py` (draw boxes + image utilities)
      - `gradio_app.py` (UI)

#### Activity A2 — Define minimal request/response schemas (match Kotlin)
- **File-level tasks**:
  - Implement Pydantic models in [`inference/pro_gradio_demo/src/nutonic_pro_gradio_demo/models.py`](inference/pro_gradio_demo/src/nutonic_pro_gradio_demo/models.py)
- **Line-level subtasks**:
  - Add `ProJobCreateIn` fields (at least): `center_lat`, `center_lon`, `bbox_half_km`, `mapbox_zoom`, `analysis_profile`, `enable_tim`, `tim_branch`, `vlm_contract_id`, `sentinel_fetch_mode`, `datetime_interval`, `scene_id_t0/t1/t2`.
    - Source of truth: [`nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiModels.kt`](C:/Users/MeMyself/nutonic/nutonic/shared/src/commonMain/kotlin/com/nutonic/api/NutonicApiModels.kt)
  - Add minimal `ProJobStatusOut` parse fields: `job_id`, `status`, `on_device_payload`, `bundle_download_url`, `artifacts` (optional).
  - Add `ProOnDevicePayload` subset: `vlm_image_set[]`, `vlm_prompt_injection`, `brief_sections`, `overlay_refs`.
  - Add `ProVlmImageRef` fields used for fetch: `role`, `url`, `inline_ref`, `artifact_id`, `width`, `height`, `mime`.
  - Add server `ProVlmModelManifest` subset: `model_bundle_id`, `revision`, `download_url`, `sha256`, `size_bytes`, `runtime`, `contract_ids`.

#### Activity A3 — Implement robust API calls + polling
- **File-level tasks**:
  - Implement `NutonicServerClient` in [`inference/pro_gradio_demo/src/nutonic_pro_gradio_demo/client.py`](inference/pro_gradio_demo/src/nutonic_pro_gradio_demo/client.py)
- **Line-level subtasks**:
  - `post_pro_job(create_in) -> job_id`
  - `get_pro_job(job_id) -> ProJobStatusOut`
  - `get_artifact(job_id, artifact_id) -> bytes`
  - `get_bytes_by_url(url) -> bytes`
    - Mirror Kotlin behavior: treat relative URLs as relative to `NUTONIC_SERVER_ORIGIN`.
  - `poll_until_complete(job_id, timeout_s, interval_s)`
    - Status mapping: stop on `completed`, fail fast on `failed/cancelled`, otherwise sleep.

#### Activity A4 — Implement map selection UI (PRO-tab-like)
- **File-level tasks**:
  - Build UI in [`inference/pro_gradio_demo/src/nutonic_pro_gradio_demo/gradio_app.py`](inference/pro_gradio_demo/src/nutonic_pro_gradio_demo/gradio_app.py)
- **Line-level subtasks**:
  - Inputs:
    - Map picker (preferred): `gr.Map` (click → lat/lon)
    - Fallback: `gr.Number` for lat/lon + `gr.Slider` for zoom/bbox_half_km
  - Re-implement `bboxHalfKmForZoom` logic from [`ProAnalysisLocationPicker.kt`](C:/Users/MeMyself/nutonic/nutonic/shared/src/commonMain/kotlin/com/nutonic/screens/pro/ProAnalysisLocationPicker.kt) so the demo matches client semantics.
  - Show computed AOI: (lat, lon, zoom, bbox_half_km) and optionally a preview overlay (rectangle) on the map if supported.

#### Activity A5 — Fetch VLM image set and produce “return images” outputs
- **File-level tasks**:
  - Implement image fetching and annotation helpers in `gradio_app.py` or a new `render.py` module.
- **Line-level subtasks**:
  - From `ProJobStatusOut.on_device_payload.vlm_image_set`, fetch the best image(s) (role-based priority) using:
    - `url || inline_ref` → `get_bytes_by_url`
    - else `artifact_id` → `get_artifact`
    - Mirror Kotlin logic in [`nutonic/shared/src/commonMain/kotlin/com/nutonic/vlm/ProOnDeviceVlm.kt`](C:/Users/MeMyself/nutonic/nutonic/shared/src/commonMain/kotlin/com/nutonic/vlm/ProOnDeviceVlm.kt)
  - Do **not** expect the backend to return boxes/caption here. Treat these images as inputs to the local VLM step below.

#### Activity A6 — Run the fine-tuned model locally (NuTonic/lspace) on ZeroGPU
- **File-level tasks**:
  - Implement model download/cache + inference in `vlm_runtime.py`.
- **Line-level subtasks**:
  - Call `GET /api/v1/pro/vlm/model-manifest` to retrieve `download_url`, `sha256`, `size_bytes`, `model_bundle_id`, `revision`.
  - Download weights if missing; validate sha256/size.
  - Cache by `{model_bundle_id}-{revision}` in a writable directory.
  - Wrap inference entrypoint with `@spaces.GPU` so GPU is allocated per request.
  - Load and run the model via **Transformers**:
    - Prefer `huggingface_hub` download helpers (so caching works across restarts when Space storage is enabled).
    - Load model/processor with `transformers` (exact classes depend on the model’s config):
      - Try `AutoProcessor` + a vision-to-text model class (e.g. `AutoModelForVision2Seq` or equivalent) first.
      - If the model does not support that path, fall back to a `pipeline(...)` that accepts an image + prompt.
    - Use `torch_dtype=torch.float16` (or bf16 if supported) and `device_map="auto"` for ZeroGPU.
    - Keep the model/processor as a lazy global singleton to avoid re-loading per request.
  - Compose prompt from:
    - a fixed instruction block matching the intent of `ProModelPromptContract`, plus
    - `on_device_payload.vlm_prompt_injection` from the job.
  - Run inference on the fetched image set; return raw model text.

#### Activity A7 — Parse output into `caption` + normalized `boxes[]` (client-compatible)
- **File-level tasks**:
  - Implement parsing in `vlm_parse.py`.
- **Line-level subtasks**:
  - Parse JSON-first; fall back to free-text caption extraction.
  - Accept aliases: `caption|summary`, `boxes|bboxes|detections`, `bbox|box`, `confidence|score`.
  - Validate/clamp bbox to `[x1,y1,x2,y2]` in \(0..1\).
  - Emit a `ProVlmResult`-shaped dict for the UI output panel.

#### Activity A8 — Produce final outputs (raw image + annotated image + JSON)
- **File-level tasks**:
  - Implement drawing helpers in `render.py` and wire outputs in `gradio_app.py`.
- **Line-level subtasks**:
  - Draw rectangles + labels on the main VLM image using normalized coordinates.
  - Return from Gradio:
    - Raw image
    - Annotated image
    - JSON with: job status, brief sections, `vlm_prompt_injection`, parsed `ProVlmResult`, model bundle id/revision, and inference timing.

### Project B — Add Hugging Face Space deployment integration (repo-standard)

#### Activity B1 — Add hf_deploy profile + template
- **File-level tasks**:
  - Add [`tools/hf_deploy/profiles/pro_gradio_demo.yaml`](tools/hf_deploy/profiles/pro_gradio_demo.yaml)
    - Line-level subtasks:
      - `hf_space_owner_org: Tonic`
      - `space_sdk: gradio`
      - `space_hardware: zero-a10g`
      - Variables: `PORT=7860`, `NUTONIC_SERVER_ORIGIN` (point at prod server URL), optional polling config.
  - Add [`tools/hf_deploy/templates/readme_pro_gradio_demo.md`](tools/hf_deploy/templates/readme_pro_gradio_demo.md)
    - Line-level subtasks:
      - Explain this is a demo surface mirroring PRO tab.
      - Document required env vars.
      - Document endpoints the Space calls.

#### Activity B2 — Register service in deploy tool
- **File-level tasks**:
  - Update [`tools/hf_deploy/deploy_space.py`](tools/hf_deploy/deploy_space.py)
- **Line-level subtasks**:
  - Add a `SERVICE_SPECS["pro_gradio_demo"]` entry mapping:
    - `source_dir = inference/pro_gradio_demo`
    - `readme_template = tools/hf_deploy/templates/readme_pro_gradio_demo.md`
    - `gradio_extras` if needed (likely none)
  - Add `SERVICE_PROFILE["pro_gradio_demo"] = profiles/pro_gradio_demo.yaml`

#### Activity B3 — Wire CI deploy workflow (optional but consistent)
- **File-level tasks**:
  - Update [`.github/workflows/huggingface-deploy.yml`](.github/workflows/huggingface-deploy.yml)
- **Line-level subtasks**:
  - Add a job/service option for `pro_gradio_demo` with default repo id `Tonic/nutonic-pro-demo`.
  - Ensure it uses `HF_TOKEN_TONIC`.

### Project C — Verification and guardrails

#### Activity C1 — Add a smoke test (lightweight)
- **File-level tasks**:
  - Add a tiny test module under `inference/pro_gradio_demo/tests/` or reuse `tools/live_inference_smoke.py` patterns.
- **Line-level subtasks**:
  - Validate that `NUTONIC_SERVER_ORIGIN` is set.
  - Hit `POST /api/v1/pro/jobs` with a known coordinate and poll `GET /api/v1/pro/jobs/{job_id}` until terminal status.
  - If no backend available in CI, mark test as optional/skipped based on env var.

#### Activity C2 — Operational UX
- **File-level tasks**:
  - Enhance Gradio UI with progress and clear error messages.
- **Line-level subtasks**:
  - Show job id and status updates while polling.
  - Cap polling timeout; show next-steps when backend is down.

## Deployment steps (after implementation)
- Local dry-run stage:
  - `pip install -r tools/hf_deploy/requirements.txt`
  - `python tools/hf_deploy/deploy_space.py --service pro_gradio_demo --repo-id Tonic/nutonic-pro-demo --dry-run`
- Real deploy (CI or local with `HF_TOKEN_TONIC`):
  - `python tools/hf_deploy/deploy_space.py --service pro_gradio_demo --repo-id Tonic/nutonic-pro-demo`
- Verify on Space:
  - Select a location, run analysis, confirm images render and annotated output appears.

## Known constraints / implications
- **Split responsibility**: upstream PRO materialization/brief fusion stays on existing Spaces/services; this Space runs the final VLM step locally.
- **Model/runtime compatibility risk**: the server manifest includes a `runtime` label (defaults to `leap`). This Space will run a Python inference stack against `model.safetensors`; if the weights aren’t compatible with the selected stack, adjust the runtime or add a dedicated worker Space for the final VLM.
- **Public endpoints**: since you selected no-auth, the server endpoints must accept unauthenticated demo calls or the Space must switch to a Space secret token later.
- **Map UX**: if `gr.Map` isn’t available in the pinned HF Gradio runtime, the fallback is lat/lon + zoom sliders plus a static map preview (optional, requires map tiles provider).
