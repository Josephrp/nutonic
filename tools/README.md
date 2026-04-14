# Operator tools (`tools/`)

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
