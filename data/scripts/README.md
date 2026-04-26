# NU:TONIC — `data/scripts`

Operator notes for the shipped-cache / POI / catalog Python pipeline. Normative behavior: [`docs/scripts/README.md`](../docs/scripts/README.md) and each `docs/scripts/SPEC-*.md`. Ordered implementation: [`plans/2026-04-14-data-scripts-implementation-track.md`](../plans/2026-04-14-data-scripts-implementation-track.md).

## Environment

- **Python:** 3.12 recommended (match `server/` CI); 3.11+ supported for scripts tested locally.
- **Install:** from repo root:

```bash
pip install -r data/scripts/requirements.txt
pip install -r data/scripts/requirements-lfm-vl-dataset.txt
pip install pytest
```

**Earth Engine (Dynamic World):** after `pip install earthengine-api`, either:

- **Service account (no interactive OAuth):** register your Cloud project for Earth Engine, enable the **Earth Engine API**, create a JSON key, then e.g.  
  `python data/scripts/build_lfm_vl_sft_dataset.py ... --ee-project YOUR_PROJECT --ee-service-account-key path/to/key.json`  
  (or set `EE_PROJECT` + `EE_SERVICE_ACCOUNT_KEY_PATH` / `GOOGLE_APPLICATION_CREDENTIALS` to that JSON). Logic lives in `lfm_vl_sft_dataset/ee_auth.py`; see [Google’s service account guide](https://developers.google.com/earth-engine/guides/service_account#create-a-service-account). The same `--ee-project` / `--ee-service-account-key` / `--ee-service-account-email` flags work on **`run_lfm_vl_sft_orchestrator.py`** (orchestrator initializes EE once, then forwards them to each batch build).
- **Interactive:** `earthengine authenticate` or `python -c "import ee; ee.Authenticate()"`. On Windows, the CLI may live under `%APPDATA%\Python\Python313\Scripts`—add that directory to `PATH` if `earthengine` is not found.

**Mapbox stills (dataset build):** set `MAPBOX_ACCESS_TOKEN` (same as GeoGuessr downloader) so `build_lfm_vl_sft_dataset.py` can fetch `mapbox_stills/*.png`.

- **Tests:** from repo root:

```bash
python -m pytest data/scripts/tests -q
```

`data/scripts/tests/conftest.py` adds `data/scripts` to `sys.path` so modules such as `geo_nutonic` import without setting `PYTHONPATH`.

## LFM-VL orchestrator (`run_lfm_vl_sft_orchestrator.py`)

**What it does (one process):** (1) select geolocated rows from a Hugging Face dataset (same candidate/selection rules as `download_geoguessr_poi_imagery.py`); (2) download Sentinel-2 (STAC) and optional Mapbox stills into **`--work-dir/batch_NNNNN/poi_<six-digit>/`** trees; (3) apply geo-jitter in-place under that batch (`poi_*_g###` siblings, `--geo-variants`); (4) run `build_lfm_vl_sft_dataset.py` with **`--poi-root=<that batch>`** and **`--out-dir`** (shared across batches); (5) **remove the entire batch directory** so Sentinel COGs and POI trees do not accumulate.

**Disk defaults:** streamed JSONL is **on** (orchestrator truncates `out-dir/data/*.jsonl` **once** at start, then each batch uses `--stream-jsonl-skip-init-truncate`); **`--prune-sentinel-after-poi`** is **on** unless you pass **`--no-prune-sentinel`**. Optional **`--prune-poi-mapbox-after-poi`** and **`--prune-allow-external`** match the builder semantics (see `docs/scripts/SPEC-lfm-vl-sft-dataset.md`).

**Concurrency:** **`--download-workers`** parallelizes **batch download + jitter** (each finished batch holds full COGs until a consumer runs the build). **`--max-staging-batches`** is the `Queue` capacity: when full, the producer **blocks** so completed batch dirs do not pile up. **`--process-workers`** runs that many build subprocesses in parallel, each draining the queue.

**Builder-only flags:** pass after **`--`**; they are appended to every batch invocation (for example `--no-upload`, `--image-aug`, `--stride`, `--native-tile`). Orchestrator-native flags must appear **before** `--`.

**Shell note:** examples use Bash line continuation (`\`). On **PowerShell**, use one long line or the backtick `` ` `` continuation character instead of `\`.

### Example full Command

python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_test_micro \
  --work-dir data/downloads/lfm_vl_test_micro_work \
  --clean-work-dir \
  --dataset stochastic/random_streetview_images_pano_v0.0.2 \
  --split train \
  --max-scan 5000 \
  --num-points 2 \
  --min-separation-km 2200.0 \
  --auto-separation-hi-km 2200.0 \
  --seed 42 \
  --bbox-km 5.0 \
  --datetime-days 90 \
  --stac-url https://earth-search.aws.element84.com/v1 \
  --collection sentinel-2-l2a \
  --max-cloud-cover 100.0 \
  --sentinel-mode minimal \
  --no-mapbox \
  --mapbox-zoom 12.0 \
  --mapbox-size 1280 \
  --download-batch-size 1 \
  --download-workers 1 \
  --process-workers 1 \
  --max-staging-batches 1 \
  --geo-variants 0 \
  --geo-max-offset-m 300.0 \
  --jitter-seed 42 \
  --synthetic-labels \
  -- \
  --no-upload --native-tile 512 --stride 128 --output-size 224 \
  --min-area-px 50 --min-valid-fraction 0.35 \
  --min-class-fraction 0.05 --max-classes-per-tile 9

Optional extras : `--no-streaming, --lat-field ..., --lon-field ..., --dataset-config NAME, --auto-min-separation, --skip-existing, --no-stream-jsonl, --no-prune-sentinel, --prune-poi-mapbox-after-poi, --prune-allow-external, --ee-project, --ee-service-account-key, --ee-service-account-email.`

### CLI groups (all orchestrator flags)

| Group | Flags | Role |
|-------|-------|------|
| Output | `--out-dir`, `--work-dir`, `--clean-work-dir` | Final dataset root; ephemeral batch parent (default `<out-dir>_work`); optional wipe of work dir at start. |
| HF pool | `--dataset`, `--dataset-config`, `--split`, `--max-scan`, `--no-streaming` | HF source and scan; `--no-streaming` uses non-streaming `load_dataset`. |
| Lat/lon columns | `--lat-field`, `--lon-field` (repeatable) | Override autodetected geo columns. |
| Selection | `--num-points`, `--min-separation-km`, `--auto-min-separation`, `--auto-separation-hi-km`, `--seed` | `--num-points 0` = use entire geolocated pool under `--max-scan`. |
| STAC / Sentinel | `--bbox-km`, `--datetime-days`, `--stac-url`, `--collection`, `--max-cloud-cover`, `--skip-existing`, `--sentinel-mode {minimal,full}` | Download window and STAC query. |
| Mapbox (download) | `--no-mapbox`, `--mapbox-zoom`, `--mapbox-size` | Skip Mapbox fetch or tune Static Images params. |
| Batching / concurrency | `--download-batch-size`, `--download-workers`, `--process-workers`, `--max-staging-batches` | POIs per batch; parallel download batches; parallel builds; staging back-pressure. |
| Geo-jitter | `--geo-variants`, `--geo-max-offset-m`, `--jitter-seed` | `0` variants skips jitter (base POIs only). |
| Build / disk | `--no-stream-jsonl`, `--no-prune-sentinel`, `--prune-poi-mapbox-after-poi`, `--prune-allow-external` | Mirror builder disk behavior for every batch. |
| EE / synthetic | `--synthetic-labels`, `--ee-project`, `--ee-service-account-key`, `--ee-service-account-email` | Skip EE init + labels, or configure service account / project for Dynamic World. |

### Permutation tables (orchestrator-native)

The axes **A** (disk/stream), **B** (STAC/Mapbox download shape), **C** (HF materialization), **D** (geo-jitter), and **E** (concurrency) are **independent**: you normally pick **one row per table** (not the full Cartesian product of all tables, which would be enormous and redundant).

**A. Streamed JSONL × prune Sentinel × prune Mapbox under `--poi-root`** (eight combinations). Unless noted, base flags are: `--out-dir ... --work-dir ... --clean-work-dir --num-points 4 --download-batch-size 2`. Add only the flags in the row.

| # | `--no-stream-jsonl` | `--no-prune-sentinel` | `--prune-poi-mapbox-after-poi` | `--prune-allow-external` | Effect |
|---|---------------------|----------------------|--------------------------------|---------------------------|--------|
| A1 | off | off | off | off | **Default:** append JSONLs, prune Sentinel per POI, keep `mapbox/` until build finishes (batch dir still deleted after build). |
| A2 | off | off | on | off | Also prune each POI’s `mapbox/` during build (lower disk mid-batch). |
| A3 | off | off | on | on | Prune Mapbox even when POI paths resolve outside `--poi-root` (use with care). |
| A4 | off | on | off | off | Keep Sentinel COGs under each POI (large disk; debugging STAC). |
| A5 | off | on | on | off | Keep Sentinel, still prune Mapbox per POI. |
| A6 | on | off | off | off | Non-streaming JSONL (higher RAM per batch). |
| A7 | on | on | off | off | Worst-case disk + RAM (debug only). |
| A8 | on | off | on | off | Buffered JSONL + prune Mapbox + prune Sentinel. |

Example **A1** (default disk posture, real EE, no Hub upload):

```bash
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orchestrated_a1 \
  --work-dir data/downloads/lfm_vl_orchestrated_a1_work \
  --clean-work-dir \
  --num-points 8 --download-batch-size 4 \
  -- \
  --ee-project YOUR_PROJECT --ee-service-account-key path/to/key.json --no-upload
```

Example **A4** (keep Sentinel for inspection; still one batch tree at a time under `--work-dir`):

```bash
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orchestrated_a4 \
  --work-dir data/downloads/lfm_vl_orchestrated_a4_work \
  --clean-work-dir --no-prune-sentinel \
  --num-points 4 --download-batch-size 2 \
  -- \
  --ee-project YOUR_PROJECT --ee-service-account-key path/to/key.json --no-upload
```

Example **A6** (non-streamed JSONL):

```bash
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orchestrated_a6 \
  --work-dir data/downloads/lfm_vl_orchestrated_a6_work \
  --clean-work-dir --no-stream-jsonl \
  -- \
  --ee-project YOUR_PROJECT --ee-service-account-key path/to/key.json --no-upload
```

**B. Download phase: `--sentinel-mode` × `--no-mapbox`** (four combinations). Same base as A1; only the last-line flags change.

| # | Extra flags | Meaning |
|---|-------------|---------|
| B1 | *(none)* | `full` Sentinel assets + Mapbox (if `MAPBOX_ACCESS_TOKEN` set). |
| B2 | `--sentinel-mode minimal` | Smaller STAC footprint per item. |
| B3 | `--no-mapbox` | STAC only (no Mapbox still fetch at download). |
| B4 | `--sentinel-mode minimal --no-mapbox` | Minimal Sentinel + no Mapbox. |

```bash
# B4
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orch_b4 \
  --work-dir data/downloads/lfm_vl_orch_b4_work \
  --clean-work-dir --sentinel-mode minimal --no-mapbox \
  --num-points 4 --download-batch-size 2 \
  -- \
  --ee-project YOUR_PROJECT --ee-service-account-key path/to/key.json --no-upload
```

**C. HF loading × pool size** (four useful combinations).

| # | HF flags | Meaning |
|---|----------|---------|
| C1 | *(default)* | Streaming scan + `--num-points` subset after separation. |
| C2 | `--no-streaming` | Full split materialized in memory (only for smaller splits). |
| C3 | `--num-points 0` | Use **all** geolocated candidates up to `--max-scan` (can be huge). |
| C4 | `--no-streaming --num-points 0` | Full non-streaming pool (highest RAM; rarely appropriate). |

```bash
# C1 small smoke
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orch_c1 \
  --work-dir data/downloads/lfm_vl_orch_c1_work \
  --clean-work-dir --num-points 6 --download-batch-size 3 \
  --synthetic-labels -- \
  --no-upload
```

**D. Geo-jitter `--geo-variants`**

| # | Flags | Meaning |
|---|-------|---------|
| D0 | `--geo-variants 0` | No `poi_*_g###` folders (download once per base POI). |
| D1 | `--geo-variants 1` | One jitter sibling per base POI. |
| D2 | `--geo-variants 2` *(default)* | Two jitters per base (typical augmentation). |

```bash
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orch_d0 \
  --work-dir data/downloads/lfm_vl_orch_d0_work \
  --clean-work-dir --geo-variants 0 --num-points 4 \
  --synthetic-labels -- \
  --no-upload
```

**E. Concurrency tuples** (`download-workers`, `process-workers`, `max-staging-batches`). Peak disk rises with **`download-workers × download-batch-size`** (multiple batch trees exist until built).

| # | `--download-workers` | `--process-workers` | `--max-staging-batches` | When to use |
|---|----------------------|----------------------|-------------------------|-------------|
| E1 | 1 | 1 | 1 | **Safest disk:** strictly serial pipeline. |
| E2 | 2 | 1 | 2 | Overlap **two** downloads; builds one at a time; queue bounds completed batches. |
| E3 | 1 | 2 | 2 | One download at a time; **two** builds in parallel (rarely helps if EE/STAC bound). |
| E4 | 2 | 2 | 3 | Aggressive overlap (highest transient disk under `--work-dir`). |

```bash
# E4
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orch_e4 \
  --work-dir data/downloads/lfm_vl_orch_e4_work \
  --clean-work-dir \
  --download-workers 2 --process-workers 2 --max-staging-batches 3 \
  --download-batch-size 4 --num-points 16 \
  -- \
  --ee-project YOUR_PROJECT --ee-service-account-key path/to/key.json --no-upload
```

### Combined examples (passthrough + orchestrator)

**Synthetic labels (no EE), image aug, no upload:**

```bash
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orch_syn_aug \
  --work-dir data/downloads/lfm_vl_orch_syn_aug_work \
  --clean-work-dir --synthetic-labels --num-points 4 --download-batch-size 2 \
  -- \
  --no-upload --image-aug
```

**Custom HF dataset + lat/lon fields + auto separation:**

```bash
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orch_custom_hf \
  --work-dir data/downloads/lfm_vl_orch_custom_hf_work \
  --clean-work-dir \
  --dataset your-org/your-dataset --split train \
  --lat-field latitude_gps --lon-field longitude_gps \
  --max-scan 50000 --num-points 24 --auto-min-separation \
  -- \
  --ee-project YOUR_PROJECT --ee-service-account-key path/to/key.json --no-upload
```

**Prune Mapbox per POI + external symlink allowance:**

```bash
python data/scripts/run_lfm_vl_sft_orchestrator.py \
  --out-dir data/downloads/lfm_vl_orch_prune_mx \
  --work-dir data/downloads/lfm_vl_orch_prune_mx_work \
  --clean-work-dir --prune-poi-mapbox-after-poi --prune-allow-external \
  -- \
  --ee-project YOUR_PROJECT --ee-service-account-key path/to/key.json --no-upload
```

Normative details (including builder flag `--stream-jsonl-skip-init-truncate` used only in this multi-batch mode) are in **`docs/scripts/SPEC-lfm-vl-sft-dataset.md`** §7.

## Layout

| Path | Role |
|------|------|
| `geo_nutonic.py` | Shared haversine / bearing helpers (torch-free) |
| `fetch_geo_baselines.py` | Natural Earth 50m zips + optional GeoNames → `data/geo/` |
| `download_geoguessr_poi_imagery.py` | HF POI ingest + STAC / Mapbox fetch |
| `build_lfm_vl_sft_dataset.py` | S2 RGB + Dynamic World → downsampled tiles + leap-finetune JSONL; optional `--image-aug`; optional `--stream-jsonl` + `--prune-sentinel-after-poi` for low-disk CI; optional HF upload — see `docs/scripts/SPEC-lfm-vl-sft-dataset.md`; deps: `requirements-lfm-vl-dataset.txt` |
| `run_lfm_vl_sft_orchestrator.py` | **End-to-end:** HF POI selection (same rules as GeoGuessr downloader) → batched STAC/Mapbox download → geo-jitter per batch → `build_lfm_vl_sft_dataset.py` per batch → **delete** each ephemeral `batch_*` tree under `--work-dir`. Bounded disk: default streamed JSONL + prune Sentinel; optional concurrent download/build. See **§ LFM-VL orchestrator** below and `docs/scripts/SPEC-lfm-vl-sft-dataset.md` §7. |
| `run_lfm_vl_sft_geo_jitter_pipeline.py` | Geo-jitter lat/lon (default `--geo-variants 2`; use `0` to skip), merge with base POIs, then run `build_lfm_vl_sft_dataset.py` (forward extra CLI args). This is the stage that **actually** runs geo-jitter—not the builder alone. **Orchestrator** (`run_lfm_vl_sft_orchestrator.py`) folds geo-jitter into each batch automatically; use this script when you already have a static `--poi-root` and only need jitter + build. |
| `lfm_vl_sft_dataset/` | Package: grid, STAC RGB stack, EE label fetch, tiling/downsample, JSONL, Hub upload |
| `catalog_import_poi.py` | POI download tree → `data/catalog/maps.yaml` + `locations/*.yaml` |
| `catalog_lint.py` | Validate catalog tree before still / geo-context / manifest phases |
| `validate_hint_strings.py` | Spoiler / length / empty-tier checks on `useful_hints` JSON |
| `render_mapbox_still.py` | Reuse POI Mapbox PNGs or call Static Images API → JPEG + `still_index.json` |
| `assemble_manifest.py` | Merge catalog + `still_index.json` + `useful_hints/*.json` + optional `ai_guesses.json` → `manifest.full.json` + redacted `manifest.public.json` |
| `assemble_ranked_clue_pack.py` | From `manifest.full.json` + `maps.yaml` `ranked_pool` → `ranked_clue_pack.json` (cached assists incl. satellite sidecar; **no** golden coordinates) |
| `generate_ai_guess_fixture.py` | `ai_guesses.json`: decoy offset, CSV table, seeded random, or **TiM** NDJSON / `*.json` dir (`tim_modality_outputs.Coordinates` / `coordinates_wgs84`); optional `--tim-export` overlay |
| `requirements.txt` | Pinned deps for ingest + geo/catalog + still rendering (incl. Pillow) |
| `generate_placeholder_bgm_wav.py` | Regenerate silent **WAV** placeholders under `nutonic/shared/.../composeResources/files/music/` (`docs/SCREEN-MUSIC-SPEC.md` §4) |

## Assembly (manifest + ranked pack)

After `catalog_lint`, `render_mapbox_still` (writes `still_index.json`), and `compile_useful_hint_tiers` (writes `useful_hints/*.json`), run from repo root:

```bash
python data/scripts/assemble_manifest.py \
  --catalog-root data/catalog \
  --still-index data/cache/build_stills/still_index.json \
  --useful-hints-dir "data/cache/<content_version>/useful_hints" \
  --ai-guesses "data/cache/<content_version>/ai_guesses.json" \
  --output-dir "data/cache/<content_version>"
```

Then ranked clue slices (maps with `ranked_pool: true` in `maps.yaml`):

```bash
python data/scripts/assemble_ranked_clue_pack.py \
  --manifest "data/cache/<content_version>/manifest.full.json" \
  --catalog-root data/catalog \
  --output-dir "data/cache/<content_version>"
```

Use `--expose-public-round-truth` only for lab builds when `manifest.public.json` must mirror the full envelope.
