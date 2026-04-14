# Inference plane (optional batch / PRO / EO tooling)

This directory hosts **deployables that are not the game server**. Kotlin clients never call these URLs directly (`rules/13-client-cache-and-data-plane.md`). **Initially**, **`data/scripts/`** and **HF Jobs** hydrate **Datasets** and bundles (`docs/GAME-ENGINE.md` §9, **`plans/2026-04-07-gradio-terramind-backend.md` §2**); each package here is a **Python service** built **from that validated script logic** when the pipeline must be **addressable over HTTP** (batch refresh, PRO, ops). The **game API** serves bundles and runs **`httpx`** to these workers when enabled — **`plans/2026-04-07-game-server-thin-orchestrator.md`** (thin **`server/`**: no torch in-process).

| Package | Role |
|---------|------|
| **`streetview_pano_service/`** | **Street View** batch plane: **`GET /health`**, **`POST /api/v1/panos/sample`** (preferred; legacy **`POST /v1/panos/sample`** alias), local **Pillow** stub frames when no Google keys. Production replaces sampling with real Street View Static / agreed provider. |
| **`lfm_vl_hint_service/`** | **Street View captions:** **`POST /v1/suggestions/from_frames`** (+ **`POST /v1/narrative/fuse`**). **`LFM_VL_BACKEND`**: **`stub`** (CI default), **`transformers`** (official **Liquid** HF weights, `pip install -e ".[model]"`), or **`openai_compatible`** (vLLM/SGLang OpenAI API per [Liquid docs](https://docs.liquid.ai/lfm/models/lfm25-vl-450m)). |
| **`lfm_vl_satellite_caption_service/`** | **Specialized** LFM-VL (your `refs/satellite-vlm/` finetune): satellite RGB → **caption / VQA / grounding JSON**; **Gradio demo** + FastAPI for the game server. |
| **`pro_materialization_service/`** *(planned scaffold)* | **PRO tab**: lat/lon → **Mapbox** still + optional **Sentinel-2** via STAC, **downsampled** to sizes for on-device VLM (`vlm_image_set`) and TerraMind **TiM** / **`_generate`** inputs; called only from the **game server** (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §5.3). |
| **`terramind_tim_local/`** | **Local TerraTorch TiM** forward + **capped** `tim_modality_outputs` JSON / JSONL + optional batch over catalog rows; **`ingest`** subcommand drives `data/scripts/generate_ai_guess_fixture.py` (`RUN_TERRATORCH_TIM=1` tests). |

**Normative plans:** Master — [`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`](../plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md). Street View A→B drill-down — [`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`](../plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md). **PRO materialization** (Sentinel + Mapbox, dual LFM-VL / TerraMind contracts) — [`plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md`](../plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md).

### Runtime backends (VLMs and TerraMind)

Implementations of **`lfm_vl_*`** and TerraMind workers **must not** run inside the thin **`server/`** process, but **may** use any of these **inside `inference/*`, `tools/`, Jobs, or `demos/terramind_space/`**:

| Stack | Typical use | Notes |
|-------|-------------|--------|
| **vLLM** | Serve supported **VLM / LM** checkpoints with an OpenAI-compatible HTTP API | Batch scripts and the game node point **`--lfm-vl-url`** (or env) at the vLLM base URL; adapter layer maps responses to **`suggestions[]`** / internal DTOs. Verify model card compatibility with vLLM before committing. |
| **`transformers` + PyTorch** | **LFM-VL** (or other HF models) in-process behind FastAPI | Matches current Space / Docker patterns (`uvicorn`, optional `@spaces.GPU`). |
| **TerraTorch** | **TerraMind TiM** and **`terramind_v1_*_generate`** on EO tensors | Per IBM TerraMind docs and `rules/12-python-gradio-terramind-server.md`; **not** used for Street View pano fetch (CPU-only there). |

Mixing all three in one giant process is **discouraged**; separate deployables keep blast radius and VRAM planning clear.

**TerraMind TiM (local batch):** `terramind_tim_local/` is the **repo-local** TerraTorch runner for **NDJSON → `generate_ai_guess_fixture`**. Broader **Gradio** demos may still live under **`demos/terramind_space/`** when that tree exists.

**Status:** **`streetview_pano_service/`**, **`lfm_vl_hint_service/`**, and **`lfm_vl_satellite_caption_service/`** ship **FastAPI** surfaces exercised by **`tools/batch_streetview_hints.py`** (where wired) and by **`pytest`** in **`.github/workflows/nutonic-ci.yml`** (`data-scripts-unit-tests`). **`lfm_vl_hint_service`** can run **real LFM-VL** via **Hugging Face Transformers** or an **OpenAI-compatible** upstream; default remains **stub** for fast CI. **`terramind_tim_local/`** is present; TerraTorch tests are **opt-in** (`RUN_TERRATORCH_TIM=1`). **`pro_materialization_service/`** remains **planned** (PRO tab materialization; no package in this tree yet).

**Game server wiring (IMP-092):** set **`NUTONIC_INFERENCE_WORKER_BASE_URL`** on the thin **`server/`** process to a worker origin (e.g. `http://127.0.0.1:7861` where pano service exposes **`GET /health`**). With **`FEATURE_PRO_JOBS=true`**, **`POST /api/v1/pro/jobs`** probes that URL via **`InferenceClient`** and returns **`inference_upstream_ok`** on the stub **`ProJobCreateOut`** payload.
