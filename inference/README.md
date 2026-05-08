# Inference plane: satellite intelligence services

This directory contains the Python services behind the NU:TONIC Earth intelligence demo. The top-level app artifacts are the easiest way to try the product, but these services explain how the system combines map selection, satellite imagery, temporal TiM signals, and VLM explanations.

The competition-facing architecture is:

1. A place or area is selected.
2. The system materializes satellite and map imagery.
3. TerraMind TiM-style processing adds temporal memory.
4. A satellite VLM turns the imagery and temporal context into readable explanations.
5. The app or PRO surface presents a bundle people can inspect.

Kotlin clients do not call these URLs directly (`rules/13-client-cache-and-data-plane.md`). The thin `server/` process or offline tools orchestrate workers when live inference is enabled.

| Package | Competition-facing role |
| --- | --- |
| **`lfm_vl_satellite_caption_service/`** | The satellite VLM explainer: satellite imagery to captions, VQA-style answers, and grounding-oriented JSON. This is the main "explain the Earth" service. |
| **`terramind_tim_local/`** | The temporal memory path: TerraMind TiM exports that help the system reason about change instead of only a still image. |
| **`pro_materialization_service/`** | The PRO bundle builder: map/Sentinel materialization, VLM image contracts, and TiM-ready arrays. |
| **`streetview_pano_service/`** | Street-level image sampling for non-satellite demo surfaces and comparison workflows. |
| **`lfm_vl_hint_service/`** | General LFM-VL caption/hint service for non-satellite imagery and narrative support. |

For the Patagonia competition narrative, the most relevant packages are `lfm_vl_satellite_caption_service/`, `terramind_tim_local/`, and `pro_materialization_service/`.

## Reviewer path

Most reviewers should not run these services locally. Use the app artifacts described in the root [`README.md`](../README.md), then read:

- Public article: [`../Patagonia_Eval/patagonia_eval_runs/eval.md`](../Patagonia_Eval/patagonia_eval_runs/eval.md)
- Satellite VLM service: [`lfm_vl_satellite_caption_service/README.md`](lfm_vl_satellite_caption_service/README.md)
- TerraMind TiM service: [`terramind_tim_local/README.md`](terramind_tim_local/README.md)
- PRO materialization: [`pro_materialization_service/README.md`](pro_materialization_service/README.md)

## CI and deployment status

There are two distinct GitHub Actions paths:

| Workflow | Trigger | What it does |
| --- | --- | --- |
| **`.github/workflows/nutonic-ci.yml`** | Pull requests, manual dispatch | Runs Python tests for `data/scripts`, `tools`, `server/`, and tested inference packages, then builds app artifacts such as APKs and desktop installers. |
| **`.github/workflows/huggingface-deploy.yml`** | Push to `main` on deploy-relevant paths, or manual dispatch | Runs targeted pytest for selected deploy targets, stages Docker Space trees, uploads them to Hugging Face, syncs Space runtime variables/secrets/hardware, then runs live smoke checks. |

Current **Hugging Face deployment targets** cover the required long-lived server and inference services:

| Deploy target | Source path | Space repo | Owner token | Runtime profile |
| --- | --- | --- | --- | --- |
| `streetview_pano` | `inference/streetview_pano_service/` | `Tonic/nutonic-streetview-pano` | `HF_TOKEN_TONIC` fallback chain | `tools/hf_deploy/profiles/streetview_pano.yaml` (`cpu-basic`, stub provider by default) |
| `lfm_vl_hint` | `inference/lfm_vl_hint_service/` | `Tonic/nutonic-lfm-vl-streetview` | `HF_TOKEN_TONIC` fallback chain | `tools/hf_deploy/profiles/lfm_vl_hint.yaml` (`zero-a10g`, `LFM_VL_BACKEND=transformers`, Gradio mounted) |
| `lfm_vl_satellite` | `inference/lfm_vl_satellite_caption_service/` | `Tonic/nutonic-lfm-vl-satellite` | `HF_TOKEN_TONIC` fallback chain | `tools/hf_deploy/profiles/lfm_vl_satellite.yaml` (`zero-a10g`, `LFM_SATELLITE_BACKEND=transformers`) |
| `terramind_tim` | `inference/terramind_tim_local/` | `Tonic/nutonic-terramind-tim` | `HF_TOKEN_TONIC` fallback chain | `tools/hf_deploy/profiles/terramind_tim.yaml` (`zero-a10g`) |
| `game_server` | `server/` | `NuTonic/nutonic-game-server` | `HF_TOKEN_NUTONIC` fallback chain | `tools/hf_deploy/profiles/game_server.yaml` (`cpu-basic`, feature flags default off) |
| `pro_materialization` | `inference/pro_materialization_service/` | `NuTonic/nutonic-pro-materialization` | `HF_TOKEN_NUTONIC` fallback chain | `tools/hf_deploy/profiles/pro_materialization.yaml` (`cpu-basic`, inbound HMAC required) |

The deploy script is **`tools/hf_deploy/deploy_space.py`**. For each target, it stages only the service `Dockerfile`, `pyproject.toml`, `src/`, optional package README, and a Space README template from `tools/hf_deploy/templates/`; then it mirrors that staged directory to the Space with `hf upload --delete "*"`. Runtime variables, secrets, and requested hardware are synced from the matching profile through the Hugging Face Hub API.

**Normative plans:** Master — [`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`](../plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md). Street View A→B drill-down — [`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`](../plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md). **PRO materialization** (Sentinel + Mapbox, dual LFM-VL / TerraMind contracts) — [`plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md`](../plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md).

### Runtime backends (VLMs and TerraMind)

Implementations of **`lfm_vl_*`** and TerraMind workers **must not** run inside the thin **`server/`** process, but **may** use any of these **inside `inference/*`, `tools/`, Jobs, or `demos/terramind_space/`**:

| Stack | Typical use | Notes |
| --- | --- | --- |
| **vLLM** | Serve supported **VLM / LM** checkpoints with an OpenAI-compatible HTTP API | Batch scripts and the game node point **`--lfm-vl-url`** (or env) at the vLLM base URL; adapter layer maps responses to **`suggestions[]`** / internal DTOs. Verify model card compatibility with vLLM before committing. |
| **`transformers` + PyTorch** | **LFM-VL** (or other HF models) in-process behind FastAPI | Matches current Space / Docker patterns (`uvicorn`, optional `@spaces.GPU`). |
| **TerraTorch** | **TerraMind TiM** and **`terramind_v1_*_generate`** on EO tensors | Per IBM TerraMind docs and `rules/12-python-gradio-terramind-server.md`; **not** used for Street View pano fetch (CPU-only there). |

Mixing all three in one giant process is **discouraged**; separate deployables keep blast radius and VRAM planning clear.

**TerraMind TiM (local batch):** `terramind_tim_local/` is the **repo-local** TerraTorch runner for **NDJSON → `generate_ai_guess_fixture`**. Broader **Gradio** demos may still live under **`demos/terramind_space/`** when that tree exists.

**Status:** **`streetview_pano_service/`**, **`lfm_vl_hint_service/`**, **`lfm_vl_satellite_caption_service/`**, and **`pro_materialization_service/`** (health + **internal materialize** P1–P2; CI installs package deps including STAC/rasterio — spectral tests **mock** STAC) ship **FastAPI** surfaces exercised by **`pytest`** in **`.github/workflows/nutonic-ci.yml`**. **`lfm_vl_hint_service`** can run **real LFM-VL** via **Hugging Face Transformers** or an **OpenAI-compatible** upstream; default remains **stub** for fast CI. **`terramind_tim_local/`** is present; TerraTorch tests are **opt-in** (`RUN_TERRATORCH_TIM=1`). **`pro_materialization_service/`** byte caps / **`FULL_STAC`** stress (**IMP-113** P5) and extra VLM roles remain ahead.

**Game server wiring (IMP-092):** set **`NUTONIC_INFERENCE_WORKER_BASE_URL`** on the thin **`server/`** process to a worker origin (e.g. `http://127.0.0.1:7860` where a Docker Space-style worker exposes **`GET /health`**). With **`FEATURE_PRO_JOBS=true`**, **`POST /api/v1/pro/jobs`** probes that URL (and optional **`NUTONIC_PRO_MATERIALIZATION_SERVICE_URL`**) via **`InferenceClient`**. When **`NUTONIC_INFERENCE_HMAC_SECRET`** is set on the **server**, probes add **`X-Nutonic-Signature`** (HMAC-SHA256 over `{ts}\\n{nonce}\\n{METHOD}\\n{path}\\n`).

**Worker inbound verification (optional):** on **`streetview_pano_service`** and **`pro_materialization_service`**, set **`NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC=1`** and the **same** **`NUTONIC_INFERENCE_HMAC_SECRET`** / **`INFERENCE_HMAC_SECRET`** as the game server. Unsigned requests then receive **401**. **`tools/batch_streetview_hints.py`** sends the same headers when the secret is present in its environment (`tools/nutonic_hmac.py`). Other callers (curl, k8s probes) must sign or leave verification disabled.
