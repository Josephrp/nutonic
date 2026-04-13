# Inference plane (optional batch / PRO / EO tooling)

This directory hosts **deployables that are not the game server**. Kotlin clients never call these URLs directly (`rules/13-client-cache-and-data-plane.md`). **Initially**, **`data/scripts/`** and **HF Jobs** hydrate **Datasets** and bundles (`docs/GAME-ENGINE.md` §9, **`plans/2026-04-07-gradio-terramind-backend.md` §2**); each package here is a **Python service** built **from that validated script logic** when the pipeline must be **addressable over HTTP** (batch refresh, PRO, ops). The **game API** serves bundles and runs **`httpx`** to these workers when enabled — **`plans/2026-04-07-game-server-thin-orchestrator.md`** (thin **`server/`**: no torch in-process).

| Package | Role |
|---------|------|
| **`streetview_pano_service/`** | **Street View** pano sampling + still fetch (CPU-first, no PyTorch) for **batch / ops** pipelines. |
| **`lfm_vl_hint_service/`** | **Standard** LFM-VL (Hub base checkpoint): multi-image in → **JSON suggestions** out; GPU / ZeroGPU on Hugging Face Spaces. |
| **`lfm_vl_satellite_caption_service/`** | **Specialized** LFM-VL (your `refs/satellite-vlm/` finetune): satellite RGB → **caption / VQA / grounding JSON**; **Gradio demo** + FastAPI for the game server. |
| **`pro_materialization_service/`** *(planned scaffold)* | **PRO tab**: lat/lon → **Mapbox** still + optional **Sentinel-2** via STAC, **downsampled** to sizes for on-device VLM (`vlm_image_set`) and TerraMind **TiM** / **`_generate`** inputs; called only from the **game server** (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §5.3). |

**Normative plans:** Master — [`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`](../plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md). Street View A→B drill-down — [`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`](../plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md). **PRO materialization** (Sentinel + Mapbox, dual LFM-VL / TerraMind contracts) — [`plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md`](../plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md).

**TerraMind TiM is elsewhere:** EO **TiM** / **`_generate`** inference and Gradio demos live under **`demos/terramind_space/`** (and related plans)—**not** under `inference/streetview_pano_service` or `inference/lfm_vl_hint_service`.

**Status:** `streetview_pano_service/` now contains a minimal **FastAPI** stub (`IMP-110` scaffold). Remaining packages are still **planned** until their PR series land.

**Game server wiring (IMP-092):** set **`NUTONIC_INFERENCE_WORKER_BASE_URL`** on the thin **`server/`** process to a worker origin (e.g. `http://127.0.0.1:7861` where pano service exposes **`GET /health`**). With **`FEATURE_PRO_JOBS=true`**, **`POST /api/v1/pro/jobs`** probes that URL via **`InferenceClient`** and returns **`inference_upstream_ok`** on the stub **`ProJobCreateOut`** payload.
