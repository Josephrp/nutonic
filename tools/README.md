# Operator tools (`tools/`)

## Hugging Face Dataset mirror + Jobs (hydration)

- **Pull POI trees from Hub:** [`pull_poidata_from_hub.py`](pull_poidata_from_hub.py) syncs `NuTonic/poidata` into `data/downloads/` via `snapshot_download` (default patterns: `geoguessr_poi_12/**`, `geoguessr_poi_120/**`). Loads `.env` and prefers **`HF_API_READ`** for private snapshots (`pip install huggingface_hub`).
- **Submit GPU Jobs (VLM + TiM):** [`submit_nutonic_hydration_job.py`](submit_nutonic_hydration_job.py) wraps `huggingface_hub.run_job` (dataset volume mount, secrets, flavors). Install `pip install -r tools/hf_jobs/requirements.txt`. Operator guide: [`hf_jobs/README.md`](hf_jobs/README.md).
- **Full hydration (Jobs only — recommended):** [`run_full_hydration.py`](run_full_hydration.py) submits GPU `sv-lfm`, GPU TerraMind `tim`, then CPU `llm-sidecars`, waits, and downloads outputs ([`run_hf_hydration_full.py`](run_hf_hydration_full.py)). **Does not load LFM weights locally.**
- **Build & push Job images:** [`hf_jobs/build_and_push_images.py`](hf_jobs/build_and_push_images.py) — `docker build` + `docker push` for `nutonic-hydration-sv-lfm`, `nutonic-hydration-llm`, and `nutonic-hydration-tim` (requires `docker login`).
- **Local dev (loads weights on your machine):** [`run_local_full_hydration.py`](run_local_full_hydration.py) requires `--allow-local-model-weights`. For a tiny 3-POI smoke test only, [`run_geoguessr_hydration_local.py`](run_geoguessr_hydration_local.py).

## Street View hint batch (`batch_streetview_hints.py`)

**Normative spec:** [`docs/scripts/SPEC-batch-streetview-hints.md`](../docs/scripts/SPEC-batch-streetview-hints.md).

**Full local run (no Google, no GPU):**

1. Install **`data/scripts`** deps plus **`tools/requirements.txt`**, then both inference packages:

   ```bash
   pip install -r data/scripts/requirements.txt -r tools/requirements.txt
   pip install ./inference/streetview_pano_service ./inference/lfm_vl_hint_service
   ```

2. Two terminals (after `pip install -e ./inference/streetview_pano_service` and `pip install -e ./inference/lfm_vl_hint_service`):

   ```bash
   cd inference/streetview_pano_service
   uvicorn streetview_pano_service.main:app --host 127.0.0.1 --port 7861
   ```

   ```bash
   cd inference/lfm_vl_hint_service
   uvicorn lfm_vl_hint_service.main:app --host 127.0.0.1 --port 7862
   ```

3. Ensure **`data/catalog`** exists (`python data/scripts/catalog_import_poi.py --poi-root data/downloads/geoguessr_poi_12`).

4. Run batch:

   ```bash
   python tools/batch_streetview_hints.py --catalog-root data/catalog --content-version dev --lfm-vl-url http://127.0.0.1:7862 --pano-service-url http://127.0.0.1:7861 --poi-limit 12
   ```

For **real LFM-VL** captions, install **`inference/lfm_vl_hint_service`** with **`pip install -e ".[model]"`**, set **`LFM_VL_BACKEND=transformers`**, and restart `uvicorn` (GPU recommended). Alternatively run vLLM/SGLang per [Liquid LFM2.5-VL docs](https://docs.liquid.ai/lfm/models/lfm25-vl-450m) and set **`LFM_VL_BACKEND=openai_compatible`** + **`LFM_OPENAI_BASE_URL`**.

Outputs: **`data/cache/<content-version>/streetview/<location_id>.json`** and **`reports/streetview_failures.json`**.

**CI / tests:** `pytest tools/tests inference/streetview_pano_service/tests inference/lfm_vl_hint_service/tests` (see `.github/workflows/nutonic-ci.yml`).
