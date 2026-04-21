# Plan: GeoGuessr POIs + Sentinel-2 + Google Dynamic World → LFM-VL satellite finetune (initial pass)

**Date:** 2026-04-21  
**Status:** Implementation plan (initial pass: **Dynamic World** only; WorldCover deferred).  
**Goal:** Build a **custom, reproducible** geospatial vision dataset (captioning + optional grounding) to **fine-tune a specialized LFM-VL** checkpoint, using **POIs sampled from** `stochastic/random_streetview_images_pano_v0.0.2` and **existing download/STAC plumbing** where possible.

**Normative product context:** `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md` (specialized satellite Space + `refs/satellite-vlm/`), `rules/10-terramesh-vlm-progressive-zoom-game-engine.md`, `rules/06-server-vlm-tim-and-on-device-ml.md`.  
**Data pipeline conventions:** `plans/2026-04-14-data-scripts-implementation-track.md` (SPEC parity, default `geoguessr_poi_12` for tests), `docs/scripts/SPEC-download-geoguessr-poi-imagery.md`.

---

## 0. Executive summary

| Layer | Choice (this pass) |
|--------|---------------------|
| **Location / diversity** | Hugging Face **`stochastic/random_streetview_images_pano_v0.0.2`** → same candidate pool + selection logic as **`data/scripts/download_geoguessr_poi_imagery.py`**. |
| **Optical anchor** | **Sentinel-2 L2A** via **Earth Search STAC** (`sentinel-2-l2a`), already wired in **`download_geoguessr_poi_imagery.py`** + **`download_simsat_sources.py`**. |
| **Semantic mask (pixel-aligned)** | **Google Dynamic World** `GOOGLE/DYNAMICWORLD/V1` via **Google Earth Engine (EE)** export — **not** in-repo today; new authenticated batch path. |
| **Training target format** | Mirror **`refs/satellite-vlm/README.md`** §Data Format: **JSONL** for **leap-finetune** `vlm_sft` (captioning prompt + answer; grounding uses **0–1 normalized** `bbox`). |

**Non-goals (initial pass):** ESA WorldCover / `terracatalogueclient`; on-device game integration; changing `catalog_import_poi` contracts; training job execution inside this repo (prepare data + document Modal/leap-finetune handoff).

**Implementation (2026-04-21):** Pipeline shipped as `data/scripts/build_lfm_vl_sft_dataset.py` + `data/scripts/lfm_vl_sft_dataset/` with **downsampled** PNG chips, leap-finetune JSONL splits, and default Hub target **`NuTonic/raw-sft-init`**. Spec: `docs/scripts/SPEC-lfm-vl-sft-dataset.md`.

---

## 1. Validation of the “generic pipeline” claims (with corrections)

### 1.1 Sentinel-2 scene size and tiling

- **Claim:** S2 scenes are on the order of **~10 980 × 10 980 px at 10 m** for native MSI grid products.  
- **Verdict:** **Substantially correct** for a **full Sentinel-2 granule** at **10 m** resolution (L1C/L2A reflectance products use a **10980 × 10980** grid per band at 10 m; 20 m/60 m bands are resampled to that grid in L2A). Training on full granules is impractical; **tiling or patch extraction** around POIs is required.

### 1.2 Land-cover alignment

- **WorldCover (deferred):** 10 m COGs align **well** with S2 **when warped to the exact grid** of your S2 stack (nearest-neighbor resample to destination transform).  
- **Dynamic World (chosen):** Per-image land cover derived from **the same S2 observation family**; when you export the **`label`** band for a **geometry and grid** matched to **your** chosen S2 acquisition, alignment is **as good as the export pipeline** (see §4 — **must** use a **reference grid** from the actual S2 patch you train on, not an independent resize).

### 1.3 Semantic → instance boxes

- **Claim:** Connected components per class → axis-aligned boxes is a standard **weak instance** signal.  
- **Verdict:** **Correct**, with caveats: boxes are **not** “objects” in an OD sense; they are **regions**. Use **minimum area** / **maximum count** filters and optionally merge tiny fragments.

### 1.4 Captions: rule-based vs VLM

- **Verdict:** Rule-based captions from region statistics are **cheap and reproducible**; optional second pass with a VLM can add diversity but couples quality to another model. For **SFT**, prefer **deterministic** captions for the first dataset version so ablations are clean.

### 1.5 Corrections to the pasted skeletons (important for implementers)

1. **`rasterio.warp.reproject`:** With a **NumPy destination**, `reproject` **fills the array in place** and returns **`None`** — not `(mask, _)`. Destination must be pre-allocated; use `dst_transform=`, `dst_crs=`, `dst_nodata=` explicitly.  
2. **Band indexing:** Earth Search **does not** give you a single GeoTIFF with “band 4 = red”. The repo downloads **per-band assets** (`blue`, `green`, `red`, … per `EARTH_SEARCH_S2L2A_ASSET_KEYS` in `inference/terramind_tim_local/.../s2_stac.py`). Any “read band 4” snippet must be replaced with **either** stacking those COGs **or** using the **`visual`** asset only where radiometry is acceptable. **TiM / TerraMind** expects **12-channel reflectance ×10⁴** (`inputs_build.py`); **LFM-VL satellite SFT** in `refs/satellite-vlm` expects **RGB-style consumer images** — decide one **radiometric recipe** (e.g. reflectance RGB with fixed scale → uint8) and document it.  
3. **Caption vs bbox scaling:** If you compute **areas** or **dominant class** from **native** masks but report **512²** images, **percentages must use consistent resolution** (either downsample the mask first with **nearest** neighbor, or aggregate in native space then map boxes with the same transform chain).

---

## 2. What already exists in this repo (reuse map)

| Capability | Location | How this plan reuses it |
|------------|----------|-------------------------|
| HF dataset + lat/lon + spread sampling | `data/scripts/download_geoguessr_poi_imagery.py` | Keep **`--dataset stochastic/random_streetview_images_pano_v0.0.2`**, **`bbox_around_point`**, **`select_pois` / `--auto-min-separation`**, `poi.json` + manifest layout. |
| STAC search + asset download | `download_simsat_sources.py` (loaded dynamically) | Same **`download_sentinel_for_bbox`** pattern; for dataset build prefer **`--sentinel-mode minimal`** during iteration, **`full`** when you need **SCL**, extra bands, or JP2 fallbacks. |
| S2 patch + TerraMind band order | `inference/terramind_tim_local/.../s2_stac.py` | **Reference** for asset keys and reflectance scaling — **optional** dependency for a **shared** “read S2 patch” helper; do **not** force TiM into the dataset job unless you want identical tensors. |
| Satellite VLM SFT format | `refs/satellite-vlm/prepare_vrsbench.py`, `README.md` | **Target JSONL** shape and grounding prompt (**normalized bbox**). New converter should emit the **same** user/assistant structure. |
| Docs / contract for POI downloader | `docs/scripts/SPEC-download-geoguessr-poi-imagery.md` | Any **new** script that **extends** POI tree layout should get a **new SPEC** + README cross-link per `plans/2026-04-14-data-scripts-implementation-track.md`. |

**Gap:** There is **no** in-repo Dynamic World, tiling orchestrator, or JSONL exporter for this use case — **new code** under `data/scripts/` (recommended) or `tools/`.

---

## 3. Product and ML objective (narrow)

- **Downstream:** Specialized checkpoint for **`inference/lfm_vl_satellite_caption_service/`** (and grounding/VQA if you include tasks).  
- **Inputs at train time:** **RGB** chips (PNG or JPEG) + text targets.  
- **Geo truth (optional auxiliary loss / metadata):** store `latitude`, `longitude`, `stac_item_id`, S2 datetime, EE export version in a sidecar JSON per sample — **not** necessarily shown to the VLM during SFT unless you design a “coordinate reasoning” task later.

---

## 4. Technical design: Dynamic World + STAC S2 (initial pass)

### 4.1 Canonical acquisition selection (align EE with STAC)

`download_geoguessr_poi_imagery.py` today picks **`max(items, key=lambda i: i.datetime)`** inside **`--datetime`** / **`--datetime-days`** window (`download_sentinel_for_bbox`). That yields **one** STAC `item.id` per POI (when search succeeds).

**Requirement:** Dynamic World export must use the **same** S2 observation identity where possible:

1. Parse from STAC item: **`datetime`** (or S2 `system:time_start` analogue), **`mgrs_tile`** / **`s2:granule_id`** / product id fields available on Earth Search items (inspect item properties in a debugger once — store the raw **`item.properties` subset** in `poi.json` extension or parallel **`s2_meta.json`**).  
2. In Earth Engine, filter **`GOOGLE/DYNAMICWORLD/V1`** (or harmonized S2 collection used by Google’s pipeline) to the **same UTC day / same product** as the STAC item. EE’s **`system:index`** conventions should be matched to Copernicus product id — **this is the highest-risk integration point**; budget time for **one-off validation** (compare EE `label` vs a manual sanity location).  
3. If EE cannot resolve an exact product match, **fallback:** nearest **Dynamic World** image in ±**N** days with **minimum cloud** — log **`match_quality`** in metadata.

### 4.2 Spatial footprint (crop, not whole granule)

Per POI you already have **`bbox_wgs84`** and **`bbox_km_half`** in `poi.json` (SimSat-style square). **Dataset patches** should be built on a **reference raster** that covers **only** that AOI (e.g. **2×–3×** the POI bbox for context, or fixed **km half-extent**), not the full granule.

**Recommended reference grid:**

1. Choose **`crs`** = **UTM** zone of patch center (reduce distortion) **or** EPSG:4326 with explicit dimensions — UTM is usually better for meter-native S2.  
2. Fix **`resolution_m`** = **10** to match S2 10 m RGB + Dynamic World **`label`**.  
3. `width_px` / `height_px` from AOI bounds ÷ 10 m, rounded consistently.  
4. For each **training tile**, use **`rasterio.windows`** from the **mosaic** or single-read window so every tile shares the **same** affine transform family.

### 4.3 Dynamic World export (Earth Engine)

- **Collection:** `ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1')`.  
- **Band of interest:** **`label`** (0–8 class index; confirm against EE catalog).  
- **Optional probability bands:** `water`, `trees`, … if you later want soft labels or cloud/quality heuristics.  
- **Export:** `Export.image.toDrive` (small runs) or **`geemap.ee_export_image`** / **`ee.batch.Export.image.toCloudStorage`** for scale — plan should default to **Drive or local GeoTIFF** for the first **N ≤ 50** POIs, then scale to GCS once validated.

**Authentication / ops:** one-time `earthengine authenticate`; service account JSON for CI/Jobs if you later automate (secrets **not** in repo — `rules` already imply no tokens in tests).

### 4.4 Pixel-perfect alignment checklist

1. **Same CRS + transform + width/height** for **S2 RGB stack** and **`label`** export.  
2. **Integer class** mask: **nearest** neighbor only; **no** bilinear on labels.  
3. **S2 nodata / SCL:** if you include **SCL** (`scene classification`), mask **cloud / shadow / cirrus** pixels to **ignore** in bbox extraction and captioning (either drop tile or set a **`valid_mask`** channel in metadata).  
4. **Verify:** overlay mask on RGB in QGIS or a **`matplotlib`** sanity notebook; RMSE should be **0** offset when both rasters are read with `rasterio` and differenced on valid pixels.

---

## 5. Dataset construction stages (ordered)

### Stage A — POI + Sentinel cache (existing)

1. Run **`download_geoguessr_poi_imagery.py`** with desired **`--num-points`**, **`--auto-min-separation`**, **`--sentinel-mode`** (`minimal` first).  
2. Confirm each **`poi_*/poi.json`** has **`stac_item_id`**, **`bbox_wgs84`**, **`datetime_query`**.  
3. If you need **SCL** or all bands, re-run affected POIs with **`--sentinel-mode full`** (large downloads).

**Deliverable:** `data/downloads/<run>/poi_*/{poi.json,sentinel-2-l2a/...}`.

### Stage B — EE manifest builder (new)

**Script (proposed):** `data/scripts/build_dynamic_world_export_manifest.py`

- **Input:** POI root (glob `poi_*/poi.json`).  
- **Output:** `dynamic_world_exports.jsonl` — each line: `poi_id`, geometry (GeoJSON polygon), `stac_item_id`, `s2_datetime`, EE collection ids, proposed **`crs`**, **`scale`**, **`dimensions`**, **`label`** asset name, output filename.  
- **Logic:** validate EE is authenticated; optionally **dry-run** print EE expressions.

**Deliverable:** manifest file drives manual or batched EE export.

### Stage C — EE export executor (new, can be notebook first)

**Options (pick one for initial pass):**

1. **Notebook** (`notebooks/dynamic_world_export.ipynb`) using `geemap` — fastest human-in-the-loop.  
2. **Python CLI** using `ee.batch.Export...` + wait on task list — better for repeatability.

**Deliverable:** per POI (or per AOI), **`label.tif`** (and optional **`probability`** multi-band) coregistered to the **same grid** as the S2 RGB GeoTIFF you will read in Stage D.

### Stage D — Unified raster + tiling (new)

**Script (proposed):** `data/scripts/tile_s2_dynamicworld_patches.py`

- Read **aligned** `rgb.tif` + `label.tif` (or stack on the fly).  
- Parameters: **`tile_px`** (e.g. 512), **`stride`** (≤ tile for overlap), **`min_valid_fraction`**, **`max_cloud_fraction`** (if SCL available).  
- Emit: `images/{poi_id}_{i}_{j}.png`, `masks/{poi_id}_{i}_{j}.png` (optional), `metadata/*.json` with transform snippet + lat/lon center.

**Important:** Implement **tiling in native 10 m space**, then optionally **downscale RGB** with bilinear and **mask** with nearest if you need **non–10 m** model input size — **do not** only downscale RGB while leaving mask at native without the **same** decimation strategy.

### Stage E — Instance-ish boxes + captions (new)

**Module or script:** `data/scripts/extract_landcover_instances.py`

1. For each tile mask, **per class id**, `skimage.measure.label` → `regionprops`.  
2. Filter by **`min_area_px`**, cap **`max_boxes_per_class`**, optionally **merge** regions separated by ≤**k** px (morphology opening/closing — keep conservative).  
3. **Class names:** map Dynamic World **0–8** to stable English strings (reuse the names from your message; verify against EE docs when coding).  
4. **Rule caption:** deterministic template from **sorted** class areas (top‑k + percentages), plus optional **“mostly cloudy”** flag from SCL.

### Stage F — JSONL for leap-finetune (new)

**Script (proposed):** `data/scripts/to_satellite_vlm_jsonl.py`

- **Captioning rows:** user prompt = `refs/satellite-vlm` `CAPTIONING_PROMPT` (or a variant that mentions “Sentinel-2”). Assistant = your rule caption.  
- **Grounding rows (optional):** user prompt uses `GROUNDING_PROMPT` with `{target}` replaced per class or per region; assistant JSON with **normalized 0–1** boxes relative to **tile width/height**.  
- **Split:** deterministic hash split by `poi_id` (e.g. 80/10/10) so tiles from same POI do not leak across train/val.

**Deliverable:** `train.jsonl`, `eval.jsonl` compatible with **`refs/satellite-vlm/configs/*.yaml`** patterns.

### Stage G — Training handoff (document only in this pass)

1. Copy/adapt **`refs/satellite-vlm/configs/vrsbench_multitask_modal.yaml`** → new yaml pointing at **your** JSONL + image directory (Modal volume or Hub dataset).  
2. Run **`leap-finetune`** per satellite-vlm README.  
3. Push checkpoint to Hub; pin **`revision`** in `lfm_vl_satellite_caption_service` config (`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`).

---

## 6. Testing, CI, and documentation (repo rules)

Per **`plans/2026-04-14-data-scripts-implementation-track.md`** and **`rules/11-vscode-testing-linting-and-ci.md`**:

| Item | Approach |
|------|-----------|
| **Unit tests** | Pure functions: bbox scaling, JSONL row schema, class-id maps — **no EE**, no network. |
| **Integration** | Mark `@pytest.mark.integration` any test that needs **`EE_TOKEN`** / network; default CI stays offline. |
| **SPEC** | Add **`docs/scripts/SPEC-tile-s2-dynamicworld.md`** (or combined SPEC) when scripts stabilize. |
| **requirements** | Add optional extra file **`data/scripts/requirements-gee.txt`** (`earthengine-api`, `geemap`, `rasterio` — note **`rasterio`** often needs GDAL wheels on Windows; document **WSL2** or **conda** as recommended dev env). |

---

## 7. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| **STAC item vs EE product mismatch** | Store full STAC properties; build explicit **join key**; visual diff 10 random patches. |
| **Huge downloads (`--sentinel-mode full`)** | Iterative **`minimal`** + selective full re-fetch for POIs that pass quality gates. |
| **Windows + GDAL/rasterio** | Prefer **WSL2** for tiling pipeline; document in SPEC. |
| **Boxes are meaningless for “built” sprawl** | Raise **`min_area_px`**; restrict to **caption-only** SFT first, add grounding when IoU on manual review is acceptable. |
| **License / ToS** | HF dataset **MIT** (per downloader docstring); **Copernicus** S2 open; **Dynamic World** / **EE** usage must follow **Google’s terms**; document attribution in dataset card. |

---

## 8. Acceptance criteria (initial pass = “done”)

1. **≥ 12** POIs (smoke) from **`geoguessr_poi_12`**-equivalent run produce **aligned** `rgb` + `label` rasters for a **single** chosen **`tile_px`** (e.g. 512).  
2. **Automated check:** random tiles pass **`np.all`** valid-class agreement when mask is reproject-read against EE reference **or** difference is **≤ 1 px** boundary tolerance (document which).  
3. **≥ 1000** JSONL rows generated (captioning at minimum) with **schema validated** by a small pydantic model in tests.  
4. **One** **`leap-finetune`** dry run (e.g. 50 steps) completes on a **tiny** shard without dataloader errors.  
5. **Dataset README** (Hub or `data/downloads/.../README.md` only if you already document downloads there — otherwise keep metadata in the plan until a Hub card exists) lists: S2 collection, EE collections, date policy, radiometry, and known failure modes.

---

## 9. Suggested file / module layout (new)

```text
data/scripts/
  build_dynamic_world_export_manifest.py   # STAC → EE export spec
  tile_s2_dynamicworld_patches.py          # AOI raster → tiles
  extract_landcover_instances.py           # mask → boxes + stats
  to_satellite_vlm_jsonl.py                # tiles → JSONL
  tests/test_dynamic_world_dataset_*.py    # offline tests
docs/scripts/
  SPEC-tile-s2-dynamicworld.md             # after behavior stabilizes
data/downloads/<your_run>/...
  dynamic_world/label.tif                  # per POI or per mosaic
  lfm_vl_satellite_sft/                    # JSONL + image chips
```

**Refactor opportunity (later):** extract **`bbox_around_point`** + STAC download entrypoints into a shared **`data/scripts/stac_nutonic.py`** — **only** if a second script needs them; avoid scope creep in the first PR.

---

## 10. Open questions (resolve in first implementation week)

1. **Radiometry:** uint8 from **percentile stretch** vs **true reflectance** scaled to 0–255 — which matches your **inference** Mapbox/Sentinel policy (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` / game stills)?  
2. **Tile policy:** fixed **512** everywhere vs **multi-scale** (256/512) for progressive zoom research — product decision.  
3. **Street-view image field:** the HF dataset includes **`image`**; for **this** satellite dataset, do you want **zero** streetview bytes (recommended) and only coordinates, or paired multimodal rows later?  
4. **Ranking of POIs:** keep **`--min-separation-km`** for diversity vs **dense** regional sampling for **class balance** — may need a **second** selection mode.

---

## 11. References (in-repo)

- `data/scripts/download_geoguessr_poi_imagery.py` — HF default dataset + STAC download.  
- `data/scripts/download_simsat_sources.py` — STAC + href resolution.  
- `inference/terramind_tim_local/src/nutonic_terramind_tim_local/s2_stac.py` — band/asset order.  
- `refs/satellite-vlm/README.md` — JSONL + normalized bbox contract.  
- `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md` — where the finetuned model ships.  
- `docs/scripts/SPEC-download-geoguessr-poi-imagery.md` — POI tree contract.

---

**End state:** You can go from **HF coordinates** → **cached S2** → **EE Dynamic World label** → **tiling** → **JSONL** → **`leap-finetune`** with **clear provenance** and **pixel alignment** guarantees, while staying consistent with NU:TONIC’s existing **GeoGuessr POI** tooling and the **satellite VLM** training reference.
