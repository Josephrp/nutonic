# Script specification: `build_lfm_vl_sft_dataset.py`

**Path:** `data/scripts/build_lfm_vl_sft_dataset.py`  
**Package:** `data/scripts/lfm_vl_sft_dataset/`  
**Status:** Shipped (initial).  
**Plan:** [`plans/2026-04-21-lfm-vl-geoguessr-dynamic-world-dataset-plan.md`](../../plans/2026-04-21-lfm-vl-geoguessr-dynamic-world-dataset-plan.md)

---

## 1. Purpose

Build a **leap-finetune–compatible** VLM SFT dataset from:

1. **GeoGuessr-style POI folders** produced by `download_geoguessr_poi_imagery.py` (`poi.json` + `sentinel-2-l2a/<item>/` COGs or **visual** preview).
2. **Google Dynamic World** `label` (Earth Engine), aligned to the same **10 m** reference grid as stacked **S2 blue/green/red** (or **visual** fallback).
3. **Tiling** in native resolution (default stride **128** for denser chips), then **downsampled** RGB + **nearest** mask to `--output-size` (default **224**).
4. Optional **Mapbox Satellite** still per POI when **`MAPBOX_ACCESS_TOKEN`** is set (`mapbox_stills/` + one JSONL overview row).
5. **Per-class rows:** for each tile, extra caption (and optional grounding) per Dynamic World class above **`--min-class-fraction`** (default **0.05**), up to **`--max-classes-per-tile`** (default **9**).
6. Optional **upload** to Hugging Face dataset repo (**default:** `NuTonic/raw-sft-init`).

**Sentinel downloads:** `download_simsat_sources.download_url` uses a **3600 s** timeout so large **visual** COGs can complete.

**Geo-jitter expansion:** `data/scripts/run_lfm_vl_sft_geo_jitter_pipeline.py` samples meter-scale WGS84 offsets per base `poi_NNNN`, re-runs the same STAC Sentinel-2 (+ optional Mapbox) download path as `download_geoguessr_poi_imagery.py` into `poi_NNNN_g001`, …, merges with the base tree, then invokes this builder on `--merged-poi-root`. **`build_lfm_vl_sft_dataset.py` alone does not run geo-jitter** (it only reads whatever `poi_*/` trees exist under `--poi-root`). HF POI counts are configured in `download_geoguessr_poi_imagery.py` via `--num-points` (use `0` for the full candidate pool), `--max-scan` (use `0` to scan the whole split), and spacing flags. Because sorted folder order is `poi_0000`, `poi_0000_g001`, …, **`--max-pois` caps total directories** and often selects only one base POI; use **`--max-base-pois`** to cap distinct `poi_NNNN` bases while keeping every `g###` variant.

**On-chip augmentation (optional):** `--image-aug` adds flipped / 90°-rotated copies of each downsampled tile (same uint8 RGB + label mask), with regions and JSONL recomputed per view (`--image-aug-no-flip`, `--image-aug-no-rotate` to narrow the set).

**Disk / memory budget (optional):** `--stream-jsonl` truncates split JSONLs at job start and **appends** one line per row after each POI (bounded RAM vs holding all rows). `--prune-sentinel-after-poi` deletes `poi_*/sentinel-2-l2a/` after a **successful** POI when that tree resolves under `--poi-root` (skips symlinked POIs that point outside the root, unless `--prune-allow-external`). `--prune-poi-mapbox-after-poi` drops `poi_*/mapbox/` under the same rule. Outputs (`images/`, `metadata/`, `data/*.jsonl`, optional `overlays/`, `mapbox_stills/`) are unchanged; re-running on the same `--out-dir` with streaming still **truncates** JSONLs at startup—use a fresh output directory or accept overwrite of same tile stems. **Multi-batch orchestrator** (`data/scripts/run_lfm_vl_sft_orchestrator.py`) calls `truncate_split_jsonl_files` **once** on `out-dir/data/`, then invokes each batch build with **`--stream-jsonl-skip-init-truncate`** so only the first conceptual “job” truncates; see §7.

**Bbox overlay PNGs (optional):** `--write-bbox-overlays` writes one `overlays/{tile_stem}__{idx}_{tag}.png` per emitted JSONL row, drawing the boxes that belong to that row (global caption / full grounding = all regions; per-class rows = that class only). Rows may include top-level `bbox_overlay_image` (relative path) unless `--no-bbox-overlay-jsonl-key` is set.

---

## 2. Outputs (normative)

Under `--out-dir`:

| Path | Content |
|------|---------|
| `images/*.png` | Downsampled RGB tiles (uint8). |
| `overlays/*.png` | Optional bbox QA images per JSONL row (`--write-bbox-overlays`). |
| `mapbox_stills/*.png` | Mapbox Satellite overview per POI (optional). |
| `metadata/*.json` | Sidecar: `poi_id`, geo, STAC/EE metadata, `regions[]`, `caption`, optional `class_fractions`. |
| `data/train.jsonl` | VLM SFT rows (`messages` with `image` + text). |
| `data/validation.jsonl` | Same schema; split by deterministic hash of `poi_id`. |
| `data/test.jsonl` | Same schema. |
| `README.md` | Hub-facing dataset card (YAML front matter + prose). |

JSONL rows mirror **`refs/satellite-vlm/prepare_vrsbench.py`** `make_vlm_message` shape.

---

## 3. Dependencies

- **Base:** `data/scripts/requirements.txt`
- **This pipeline:** `data/scripts/requirements-lfm-vl-dataset.txt` (`rasterio`, `earthengine-api`, `huggingface_hub`); **scipy** and **Pillow** are required for tiling / connected components (also in `data/scripts/requirements.txt`).
- **Earth Engine:** see §3.1 (service account, ADC, or interactive auth).
- **Upload:** `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` with **write** on the target dataset namespace.

### 3.1 Earth Engine authentication

Implementation: `data/scripts/lfm_vl_sft_dataset/ee_auth.py` (`initialize_earth_engine`). Matches Google’s **Service accounts** guide, including **Application Default Credentials** and **private key** flows: [Service Accounts \| Earth Engine](https://developers.google.com/earth-engine/guides/service_account#create-a-service-account).

| Mechanism | Configuration |
|-----------|----------------|
| **Service account JSON** | JSON with `"type": "service_account"`. Path: `--ee-service-account-key`, or `EE_SERVICE_ACCOUNT_KEY_PATH`, or `GOOGLE_APPLICATION_CREDENTIALS`. Optional email override: `--ee-service-account-email` / `EE_SERVICE_ACCOUNT_EMAIL`. Uses `ee.ServiceAccountCredentials` + `ee.Initialize(credentials=..., project=...)`. |
| **ADC** | `google.auth.default(scopes=[Earth Engine])` when no usable service-account JSON is found. |
| **Legacy** | `ee.Initialize(project=...)` or `ee.Initialize()` for interactive OAuth. |

**Project id** (Earth Engine–registered Cloud project): `--ee-project`, or `EE_PROJECT` / `EARTHENGINE_PROJECT` / `GCP_PROJECT` / `GOOGLE_CLOUD_PROJECT`.

**Never commit** private key JSON; keep keys out of Git (see root `.gitignore` patterns).

---

## 4. Flags (summary)

| Flag | Role |
|------|------|
| `--poi-root` | Input tree (`poi_*/`). |
| `--out-dir` | Build root (default under `data/downloads/lfm_vl_raw_sft_init`). |
| `--native-tile` | Native 10 m tile side (default 512). |
| `--stride` | Sliding stride (default **128**). |
| `--no-mapbox-still` | Skip Mapbox fetch. |
| `--no-per-class-rows` | Disable per-class caption/grounding expansion. |
| `--min-class-fraction` | Threshold for emitting a class-specific row (default 0.05). |
| `--output-size` | Square output after downsample (default 224). |
| `--synthetic-labels` | **No EE**; random `label` map for CI / layout tests. |
| `--no-upload` | Skip Hub push. |
| `--upload-repo` | Dataset id (default `NuTonic/raw-sft-init`). |
| `--ee-project` | Earth Engine / GCP project id (e.g. `radioshaq`). |
| `--ee-service-account-key` | Path to service account JSON. |
| `--ee-service-account-email` | Optional override for `client_email` from JSON. |
| `--stream-jsonl-skip-init-truncate` | With `--stream-jsonl`, do **not** truncate split JSONLs at this process startup. Intended when an **external** coordinator (e.g. `run_lfm_vl_sft_orchestrator.py`) truncates once before multiple batch builds. |

---

## 5. Non-goals

- Does **not** run **leap-finetune** or publish model weights.
- Does **not** modify game **catalog** or Kotlin clients.
- **WorldCover** / `terracatalogueclient` are out of scope (see plan).

---

## 6. Windows note

`rasterio` wheels require a supported Python + platform combo; **WSL2** or **conda-forge** is recommended if native Windows wheels fail.

---

## 7. Multi-batch orchestrator (`run_lfm_vl_sft_orchestrator.py`)

**Path:** `data/scripts/run_lfm_vl_sft_orchestrator.py`  
**Library:** `data/scripts/lfm_vl_sft_dataset/orchestrator_lib.py`

### 7.1 Purpose

Run the **full** raw-SFT hydration pipeline in one command when you do **not** already have a long-lived `poi_*/` tree on disk:

1. **HF selection** — same candidate collection and spacing rules as `download_geoguessr_poi_imagery.py` (`HfSelectionConfig` / `select_hf_points` in `orchestrator_lib.py`).
2. **Batched download** — for each slice of N POIs, materialize `poi_<six-digit>/` directories under `work-dir/batch_KKKKK/` via the same STAC + optional Mapbox path as the GeoGuessr downloader.
3. **Geo-jitter** — in-place under that batch directory (`--geo-variants`, `--geo-max-offset-m`, `--jitter-seed`); `0` variants skips jitter.
4. **Build** — subprocess `build_lfm_vl_sft_dataset.py --poi-root=<batch_dir> --out-dir=<shared out>` for each batch.
5. **Ephemeral disk** — after a batch build exits (success or failure of that subprocess still followed by tree removal on the orchestrator side for the batch dir), the orchestrator **deletes the entire** `work-dir/batch_KKKKK/` tree so Sentinel COGs do not accumulate across batches.

This complements **`run_lfm_vl_sft_geo_jitter_pipeline.py`**, which assumes an existing `--poi-root` on disk. The orchestrator **embeds** jitter per batch so nothing outside `--work-dir` holds raw Sentinel for prior batches.

### 7.2 JSONL and streaming

- On startup (when streaming is enabled), the orchestrator **truncates** `train.jsonl`, `validation.jsonl`, and `test.jsonl` under `--out-dir/data/` **exactly once**.
- Each batch subprocess is invoked with **`--stream-jsonl`** and **`--stream-jsonl-skip-init-truncate`** so splits **append only** across batches.
- If **`--no-stream-jsonl`** is set on the orchestrator, each batch build performs the builder’s normal startup behavior (no skip-truncate flag).

### 7.3 Defaults and forwarded flags

- **Default** orchestrator behavior matches a low-disk single-batch build: streamed JSONL on, **`--prune-sentinel-after-poi`** on (`--no-prune-sentinel` disables).
- **`--prune-poi-mapbox-after-poi`** and **`--prune-allow-external`** are **off** unless set on the orchestrator; they map to the same builder flags.
- **`--synthetic-labels`** skips Earth Engine initialization in the orchestrator and is forwarded to each build.
- **`--ee-project`**, **`--ee-service-account-key`**, **`--ee-service-account-email`** are used for **`initialize_earth_engine`** before downloads and are **repeated** on each build command line.
- Any tokens after **`--`** on the orchestrator CLI are appended verbatim to each **`build_lfm_vl_sft_dataset.py`** invocation (Hub upload, `--image-aug`, tiling, etc.).

### 7.4 Concurrency and back-pressure

- **`--download-workers`:** `ThreadPoolExecutor` runs up to this many **batch** download+jitter tasks concurrently.
- **`--process-workers`:** consumer threads each run **`subprocess.run`** for `build_lfm_vl_sft_dataset.py`; completed batch directories are taken from a bounded queue.
- **`--max-staging-batches`:** `Queue(maxsize=...)`; when the queue is full, the producer **blocks** on `put` until a consumer removes a batch directory, bounding how many finished batch trees wait under `--work-dir`.

### 7.5 Operator documentation

Full **CLI group table** and **permutation examples** (stream × prune × Mapbox, Sentinel mode × Mapbox, HF streaming × pool size, geo-variants, concurrency tuples, passthrough) live in **`data/scripts/README.md`** (section **LFM-VL orchestrator**).

### 7.6 Orchestrator-specific non-goals

- The orchestrator does **not** replace `download_geoguessr_poi_imagery.py` for workflows that want a **persistent** POI download tree for reuse outside LFM-VL builds.
- It does **not** upload the HF dataset by itself; pass **`--no-upload`** or Hub flags after `--` like a normal build.
