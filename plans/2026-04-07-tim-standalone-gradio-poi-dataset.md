# Plan: Standalone TiM + TerraMind **generation** demo (Gradio.server), POI dataset wiring, and modality truth

**Date:** 2026-04-07  
**Audience:** Implementers of the **standalone TerraMind** demo service (**Thinking-in-Modalities `*_tim`** and **`terramind_v1_*_generate`** via **`FULL_MODEL_REGISTRY`**) and anyone packaging **`data/downloads/geoguessr_poi_120/poi_####`** (e.g. `poi_0015`) for TerraTorch.

**Normative product rules (this repo):** **`*_tim`** and **`terramind_v1_*_generate`** are **in scope** for reference APIs, HF Jobs, and standalone Gradio (`rules/06-server-vlm-tim-and-on-device-ml.md`, `rules/12-python-gradio-terramind-server.md`). **Backbone-only** TerraMind encoders (no `_tim` / `_generate` suffix) remain **out of scope** unless an ADR adds them. This plan keeps **TiM** and **generation** **separate mental models**—token imagination vs diffusion decoders ([TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/)).

---

## 1. Executive summary

| Question | Answer |
|----------|--------|
| Can TiM run on **only** Mapbox PNG + three Sentinel bands ripped from COGs? | **Not as `S2L2A` with a `bands` subset.** IBM documents that **TiM requires full pre-trained raw inputs (all bands, no `bands` parameter)** for each declared **raw** modality. A 3-band “S2L2A” stack **violates** that contract. |
| What **is** allowed for a tight demo? | (A) **Full `S2L2A`** (12 bands in TerraMind’s expected order + scaling) from your STAC COGs, **or** (B) treat the Mapbox still as **`RGB`** (3×uint8, B-G-R order per TerraTorch’s `RGB` band list) with **no** `bands` subset for that modality—then set **`tim_modalities`** to a **subset** of IBM’s allowed imagined modalities. |
| Where does `poi_0015` come from? | Canonical layout is produced by **`data/scripts/download_geoguessr_poi_imagery.py`** (and documented in **`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`**). The folder may not exist until you run the script. |
| Standalone server UX? | **`gradio`** `Blocks` app launched with **`launch(server_name=..., server_port=...)`** (a.k.a. **Gradio server** mode) or mounted under FastAPI later; this **standalone demo deployable** can host **TiM** and **`_generate`** behind separate tabs or toggles (separate model loads / semaphores)—**not** the NU:TONIC thin **`server/`** game API. See [Gradio server / sharing](https://www.gradio.app/main/guides/server-mode/). |
| **SCAN `useful_hints` / `streetview_hint_pack`?** | **Offline only**—**§2.5**: existing **`data/scripts/download_*.py`** for imagery; add **`data/scripts/generate_scan_useful_hints.py`** + **`data/scripts/materialize_streetview_hint_pack.py`** (or CI Jobs) per **`docs/GAME-ENGINE.md` §9**—**not** emitted by a TiM forward in the player hot path. |

---

## 2. What a POI directory actually contains (repo-grounded)

### 2.1 Layout (authoring reference)

From **`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`** §1 and **`data/scripts/download_geoguessr_poi_imagery.py`** (lines 547–626):

```text
<dataset_root>/          # e.g. data/downloads/geoguessr_poi_120
  poi_0015/
    poi.json
    mapbox/
      satellite-v9_{lon}_{lat}_z{zoom}.png
    sentinel-2-l2a/
      <STAC_ITEM_ID>/     # one folder per selected Sentinel-2 L2A item
        <asset_key><.tif|.jp2|.jpg|...>   # one file per STAC asset key (Earth Search)
```

### 2.2 `poi.json` (machine-readable truth for packaging)

The downloader writes **`poi_id`**, **`latitude`**, **`longitude`**, **`bbox_wgs84`**, STAC id, Sentinel mode, Mapbox fetch metadata, and provenance blobs (`hf_row_meta`, etc.). See **`download_geoguessr_poi_imagery.py`** JSON structure at lines 597–625.

**Implication for TiM:** geolocation is **metadata** for the demo UI and for **dataset manifests**; **TiM forward** itself consumes **tensors** built from rasters. Do not confuse `poi.json` fields with model `Coordinates` modality unless you explicitly add that tensor per TerraTorch docs (requires **`terratorch>=1.1`** for coordinate support—[TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/)).

### 2.3 Mapbox folder

- **Source:** Mapbox Static Images API, `mapbox/satellite-v9`, same URL pattern as **`data/scripts/download_simsat_sources.py`** / SimSat (`fetch_mapbox_static`, lines 127–150).
- **File:** Single **PNG** (default **1280×1280** `@2x` optional), **`--mapbox-zoom`** default **12** (`download_geoguessr_poi_imagery.py` lines 445–446, 567).
- **Role in TiM demo:** natural use is **(1) human preview** in Gradio and/or **(2) `RGB` modality** after resize + channel order fix—**not** a substitute for full **`S2L2A`** unless you adopt the **`RGB`-only** branch in §5.2.

### 2.4 `sentinel-2-l2a/` folder

- **Source:** STAC API **`https://earth-search.aws.element84.com/v1`**, collection **`sentinel-2-l2a`** (`download_geoguessr_poi_imagery.py` lines 432–433; `download_simsat_sources.py` lines 33–35).
- **`--sentinel-mode`:** `minimal` restricts to asset keys `thumbnail`, `visual`, `tileinfo_metadata`, `granule_metadata` only (lines 457–462). **`full`** downloads **every** STAC asset (can be **very large**—`download_simsat_sources.py` docstring lines 10–12).
- **For TiM:** **`full`** (or a **custom allowlist** that includes the **10m/20m band COGs** you need) is required if **`S2L2A`** is your backbone input—you must assemble **all 12** S2L2A bands in the order TerraTorch expects.

### 2.5 SCAN assist bundles — explicit generation scripts (`useful_hints`, `streetview_hint_pack`)

**Product contract:** Optional SCAN assists are **pre-cached** bundle fields documented in **`docs/GAME-ENGINE.md` §9** and **`docs/NARRATIVE-AND-PROMPTS.md` §4** (three-tier **`useful_hints`**, **`streetview_hint_pack`** text). They are **not** produced by an in-round **TiM** forward; they are **offline** artifacts from **data scripts** and/or **HF Jobs**, same discipline as Mapbox stills.

| Script / entrypoint | Status | Role |
|---------------------|--------|------|
| **`data/scripts/download_geoguessr_poi_imagery.py`** | **In repo** | Canonical **POI** tree: **`poi.json`**, **`mapbox/`** PNG, **`sentinel-2-l2a/`** assets—**inputs** for Jobs that also emit round manifests (`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`). |
| **`data/scripts/download_simsat_sources.py`** | **In repo** | STAC + Mapbox static fetch semantics shared with SimSat / TerraMesh-style pipelines—reuse for **batch** imagery pulls aligned with **`poi.json`** centroids. |
| **`data/scripts/generate_scan_useful_hints.py`** | **To add** (recommended name) | Offline generator: reads golden **`(lat, lon)`** (+ optional `map_id` / `content_version`) and emits **`useful_hints`** `{ tier_1, tier_2, tier_3 }` (continent → regional EO landmark / hydrology → country). Implement via **gazetteer / admin-boundary datasets** and/or **batch LLM** with **schema-capped** JSON; must be **reproducible** for CI when deterministic sources only. |
| **`data/scripts/materialize_streetview_hint_pack.py`** | **To add** (recommended name) | Offline orchestrator: drives **`inference/streetview_pano_service`** (multi-pano sample around target, **not** at golden unless product allows) + **`inference/lfm_vl_hint_service`** → normalized **`suggestions[]`** merged into **`streetview_hint_pack`** on the bundle row. See **`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`** and **`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`**. |

**CI wiring:** Add Gradle / GitHub Actions steps that run the **new** scripts **after** imagery exists (typically post-`download_geoguessr_poi_imagery.py`), write Parquet or JSON manifest slices keyed by **`round_id`** + **`content_version`**, and fail CI on **placeholder / empty** tiers if the mission marks assists as required.

**Ranked note:** Client assist consumption rules (**`forfeit-assists`**) are server/API policy (`docs/RANKED-MODE.md`); scripts only ensure **redacted, capped** strings ship in ranked clue bundles.

---

## 3. TerraMind TiM: authoritative constraints (external + internal)

### 3.1 What TiM is (and is not)

- **Definition (IBM):** TiM lets TerraMind **imagine missing modalities in token space** before the encoder continues—see the **Thinking-in-Modalities** section of the [TerraTorch TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/) and the paper linked there: [arXiv:2504.11171](https://arxiv.org/pdf/2504.11171).
- **Different surface — `terramind_v1_*_generate`:** **Full generation** uses **`FULL_MODEL_REGISTRY.build(...)`** with **`modalities`**, **`output_modalities`**, and **shared diffusion decoders** ([same guide — Generation](https://terrastackai.github.io/terratorch/stable/guide/terramind/)). Both **TiM** and **generation** are **in scope** for this API + demo track; treat **`_generate`** as **higher latency / GPU memory** than a TiM-only forward unless you batch offline in **Jobs**.

### 3.2 Hard prerequisite (quoted policy)

From [TerraTorch — Thinking-in-Modalities (TiM)](https://terrastackai.github.io/terratorch/stable/guide/terramind/) (emphasis preserved):

> **TiM only works with fully pre-trained raw inputs (all bands, no `bands` parameter).** The generator model is frozen and cannot adapt to unseen inputs such as subsets of pre-trained bands or new modalities. **If this is the case for you, you cannot use the TiM models.**

**Claim:** A pipeline that feeds **`S2L2A`** with only **Blue/Green/Red** via the `bands=` subset **cannot** use **`terramind_v1_*_tim`** without violating IBM’s documented constraint.

### 3.3 Allowed raw modalities and band names

From the [TerraMind guide — Model Input / band lists](https://terrastackai.github.io/terratorch/stable/guide/terramind/):

- Raw modalities include **`S2L2A`**, **`RGB`**, **`S1GRD`**, etc.
- **`S2L2A` / `S2L1C`** band enums include **`COASTAL_AEROSOL`, `BLUE`, `GREEN`, `RED`, … `SWIR_2`** (see guide; canonical names also referenced from [terratorch `terramind_register.py`](https://github.com/IBM/terratorch/blob/53768e684a50e3f7e37d654f499dcccb4373940b/terratorch/models/backbones/terramind/model/terramind_register.py#L77) as linked in the guide).
- **`RGB`** modality is **three channels**: **`BLUE`, `GREEN`, `RED`**.
- **Note in guide:** *“RGB patch embedding was pre-trained on Sentinel-2 RGB inputs [0–255].”* — supports using **uint8**-style optical stacks mapped into **`RGB`**.

### 3.4 What `tim_modalities` may contain

Same guide section lists modalities usable as **`tim_modalities`** or **`output_modalities`:**

`S2L2A`, `S1GRD`, `S1RTC`, `DEM`, `LULC`, `NDVI`, `Coordinates`

**Claim:** “Generate all possible modalities” is **not** a free-form goal—you choose **`tim_modalities`** from this **closed set** (plus obeying coordinate/TerraTorch version constraints).

### 3.5 Model registry names (TiM)

From the guide’s **Model Versions** list: `terramind_v1_{tiny,small,base,large}_tim`. **Demo default:** `terramind_v1_small_tim` or `terramind_v1_tiny_tim` per compute ([sizing guidance in guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/)), aligned with `plans/2026-04-07-gradio-terramind-backend.md` §3.1.

### 3.6 Full generation (`FULL_MODEL_REGISTRY`, `*_generate`)

- **Build:** `FULL_MODEL_REGISTRY.build("terramind_v1_*_generate", pretrained=True, modalities=[…], output_modalities=[…], standardize=True, …)` per the [Generation section](https://terrastackai.github.io/terratorch/stable/guide/terramind/) (same band-completeness discipline on **inputs** as TiM; **`output_modalities`** declares what the decoder renders).
- **Registry names:** `terramind_v1_{tiny,small,base,large}_generate` — **IBM note:** decoder cost dominates; **tiny/small are not much faster than base/large**—pick size for **quality**, not cold-start fantasy.
- **POI reuse:** **Branch A / B** tensor builders in §5 feed **`modalities`** the same way; you may **reuse one raster stack** for a TiM tab and a generation tab **only** if you accept **two** model loads in memory or **unload** between runs.
- **API / OpenAPI:** label responses with **`pipeline": "tim"`** vs **`"terramind_generate"`**, **`model_id`**, **`output_modalities`**, and **artifact URIs** (PNG/GeoTIFF pointers) so clients never conflate token summaries with decoded rasters.
- **Reference notebooks:** IBM [terramind_generation.ipynb](https://github.com/IBM/terramind/blob/main/notebooks/terramind_generation.ipynb), [any_to_any_generation.ipynb](https://github.com/IBM/terramind/blob/main/notebooks/terramind_any_to_any_generation.ipynb), [large_tile_generation.ipynb](https://github.com/IBM/terramind/blob/main/notebooks/large_tile_generation.ipynb).

---

## 4. Internal references (`refs/`) — what exists in *this* repo today

| Reference | Role |
|-----------|------|
| **`rules/10-terramesh-vlm-progressive-zoom-game-engine.md`** | Maps **`refs/terramind-geogen-main/`** (when present) to **TerraMesh** batch patterns, **`geo_utils.py` haversine**, and **zarr** metadata conventions—**not** a substitute for reading TerraTorch TiM docs. |
| **`data/scripts/download_geoguessr_poi_imagery.py`** | **Normative** for how **`poi_####`**, **`poi.json`**, **`mapbox/`**, and **`sentinel-2-l2a/`** are created; cites TerraMesh metadata patterns (file header lines 11–15). |
| **`data/scripts/download_simsat_sources.py`** | STAC client, asset download naming, Mapbox static URL parity with **`refs/SimSat-main`** (comment lines 5–8). |
| **`data/scripts/generate_scan_useful_hints.py`** | **Planned** — emits **`useful_hints`** tiers for SCAN bundles (**§2.5**). |
| **`data/scripts/materialize_streetview_hint_pack.py`** | **Planned** — emits **`streetview_hint_pack`** via pano + LFM-VL batch (**§2.5**). |

**If `refs/terramind-geogen-main/` is not checked in:** treat **`rules/10`** as the pointer to expected research layout; **do not** block the TiM demo on that tree—TerraTorch + your POI rasters are sufficient.

---

## 5. Data → tensor pipelines (two supported demo branches)

### 5.1 Branch A — **Full `S2L2A` (recommended for “real EO” TiM)**

**Goal:** Satisfy IBM’s “all bands, no `bands` parameter” for **`S2L2A`**.

**Steps:**

1. Ensure POI was built with **`--sentinel-mode full`** (or a **custom asset allowlist** that retains all **S2L2A** band COGs required for the 12-channel stack—not only `visual` RGB).
2. **Read** per-band GeoTIFFs/JP2s from `sentinel-2-l2a/<item_id>/…` (keys depend on Earth Search item; discover at runtime or map from STAC `assets`).
3. **Resample** all bands to a **common grid** (e.g. 224×224) with one reference geotransform (nearest or bilinear—document choice).
4. **Stack** channels in **TerraMind `S2L2A` order** (must match TerraTorch / `terramind_register` ordering—**verify** against the version you pin).
5. **Standardize:** use **`standardize=True`** on `BACKBONE_REGISTRY.build` where supported, or apply documented normalization constants from the [guide’s standardization link](https://github.com/IBM/terratorch/blob/53768e684a50e3f7e37d654f499dcccb4373940b/terratorch/models/backbones/terramind/model/terramind_register.py#L130) (cited in the Generation section of the same guide).
6. **Build model:**

   ```python
   from terratorch.registry import BACKBONE_REGISTRY

   model = BACKBONE_REGISTRY.build(
       "terramind_v1_small_tim",
       pretrained=True,
       modalities=["S2L2A"],
       tim_modalities=["LULC"],  # example; pick from allowed set + task sanity
   )
   ```

7. **Forward:** `model({"S2L2A": tensor_bchw})` — capture last-layer tokens and any **auxiliary outputs** your TerraTorch version exposes for TiM (consult pinned **terratorch** version docs / source).

**Mapbox in Branch A:** use only in Gradio for **side-by-side** display of the clue scene; **optional** second forward with **`RGB`** modality is a **separate** experiment (second model build), not a silent merge into the same TiM forward unless you design a multi-modal tensor dict per IBM.

### 5.2 Branch B — **`RGB` only (Mapbox or 3-band “visual”)**

**Goal:** Use **exactly three** optical channels under the **`RGB`** modality name so “all bands” = **B,G,R only**.

**Steps:**

1. Load PNG → numpy **`[H, W, 3]`** → reorder to **B,G,R** if your reader is RGB.
2. Resize to model input (e.g. **224×224**).
3. Cast to **`float32`** tensor **`[1, 3, H, W]`** scaled **0–255** (per guide’s RGB pretraining note).
4. **Build:**

   ```python
   model = BACKBONE_REGISTRY.build(
       "terramind_v1_small_tim",
       pretrained=True,
       modalities=["RGB"],
       tim_modalities=["NDVI"],  # example — must be in IBM’s allowed tim list
   )
   ```

**Risk / validation:** IBM examples emphasize **`S2L2A` + SAR**; **`RGB`-only TiM** with aggressive **`tim_modalities`** should be treated as **demo-grade** until you run smoke checks for NaNs/OOM and **qualitative** plausibility. Log **`terratorch` + `torch` + CUDA** versions in the demo README.

### 5.3 What **not** to do (still common mistakes)

| Anti-pattern | Why |
|--------------|-----|
| Pass **`S2L2A`** with **`bands={"S2L2A": ["BLUE","GREEN","RED"]}`** into **`*_tim`** | Violates IBM “no `bands` parameter” rule for TiM ([guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/)). |
| Assume **`visual`** JPEG is calibrated like L2A reflectance | Map to **`RGB`** with documented scaling, **or** use true L2A COGs for **`S2L2A`**. |
| Ship **`minimal`** Sentinel mode for EO TiM | **`minimal`** drops most spectral assets (`download_geoguessr_poi_imagery.py` lines 457–462)—insufficient for **12-band `S2L2A`**. |
| Run **`_generate`** on the **guess-submit** hot path without timeout | Use **Jobs** + Dataset artifacts or **async job id** + poll; **`_generate`** is not a sub-100ms primitive for ranked play (`rules/06`, `rules/12`). |

### 5.4 Branch C — **`_generate`** (same POI tensors, different registry)

**Goal:** From the **same** `S2L2A` or **`RGB`** tensor dict as Branch A/B, call **`FULL_MODEL_REGISTRY`** with explicit **`output_modalities`** (e.g. `LULC`, `NDVI`, or multi-output per guide).

**Sketch:**

```python
from terratorch.registry import FULL_MODEL_REGISTRY

model = FULL_MODEL_REGISTRY.build(
    "terramind_v1_small_generate",
    pretrained=True,
    modalities=["S2L2A"],  # or ["RGB"] — must match tensor keys
    output_modalities=["LULC"],  # example; validate against guide for your build
    standardize=True,
)
# forward per TerraTorch / notebook patterns; export rasters or thumbnails + JSON sidecar
```

**Operational note:** Prefer **one semaphore** per GPU for TiM vs generation if both tabs exist, or **separate processes** (two workers) to avoid OOM when operators click both.

---

## 6. Standalone **Gradio.server** TiM + **generation** demo (process shape)

### 6.1 Minimal architecture

- **One Python process**, **`torch` + `terratorch` + `gradio`**.
- **Model load:** once at startup (lazy on first request if cold-start matters).
- **GPU:** optional; CPU with **`terramind_v1_tiny_tim`** for CI.

### 6.2 Gradio UI blocks (suggested)

1. **Input:** Dropdown **`poi_id`** scanning `data/downloads/geoguessr_poi_120/poi_*/poi.json` **or** file upload of a zip/tar of one POI.
2. **Branch selector:** `S2L2A_full` vs `RGB_mapbox`.
3. **Pipeline tabs (or accordion):**
   - **TiM:** **`tim_modalities`** multi-select → **Run TiM** → token stats + optional **`.npz` / `.pt`** export + JSON sidecar (`tim_modalities`, `merge_method`, `content_version`) per `plans/2026-04-07-gradio-terramind-backend.md` §5.
   - **Generation:** **`output_modalities`** multi-select (guide-allowed set) → **Run generate** → decoded **PNG / GeoTIFF** previews where TerraTorch returns decode-friendly tensors + same **`poi_id` / `model_id` / `terratorch_version`** provenance.
4. **Run** buttons → `torch.inference_mode()` → **wall time + peak GPU mem** logged in UI.
5. **Outputs:** TiM tab emphasizes **internal summaries**; generation tab emphasizes **raster products**—do not merge into one ambiguous “AI output” blob without schema labels.

### 6.3 “`gradio.server`” wording

Gradio’s **server mode** is **`Blocks.launch(...)`** (or **`Interface.launch`**). For embedding inside FastAPI later, use **`gr.mount_gradio_app`** as in **`rules/12-python-gradio-terramind-server.md`**. The standalone demo does **not** require FastAPI unless you want **`/healthz`** or **versioned REST** mirrors of the Gradio actions (recommended before shipping any **game** integration).

**Spaces, ZeroGPU, and manual GitHub → Hub deploy:** For a full implementation breakdown (projects **P1–P10**), HF **`README.md`** SDK headers, **`@spaces.GPU`** boundaries, and **`workflow_dispatch`** CI, see **`plans/2026-04-07-terramind-gradio-spaces-comprehensive-demo.md`**.

---

## 7. Hugging Face **Dataset** rows (optional persistence)

**Goal:** store **reproducible** demo outputs without bloating the Hub.

**Suggested Parquet / JSONL schema (per forward):**

| Field | Type | Notes |
|-------|------|-------|
| `poi_id` | string | e.g. `poi_0015` |
| `branch` | enum | `S2L2A_full` \| `RGB_mapbox` |
| `pipeline` | enum | `tim` \| `terramind_generate` |
| `tim_modalities` | list[str] | e.g. `["LULC"]` (TiM only) |
| `output_modalities` | list[str] | e.g. `["NDVI"]` (generation only) |
| `model_id` | string | e.g. `terramind_v1_small_tim` or `terramind_v1_small_generate` |
| `terratorch_version` | string | pip freeze |
| `input_manifest` | JSON | paths + SHA256 of source rasters |
| `output_uri` | string | pointer to **compressed** tensor blob or **omitted** if too large |
| `tim_modality_outputs` | JSON | **Normative for NU:TONIC:** one capped sub-object **per key** in **`tim_modalities`** (same schema as `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` **`tim_modality_outputs`**). The **game server** uses this shape for **PRO** bundles and for **`AiGuessStore`** **only** when the job row is **`map_id`** clue / catalog ingest — **not** for ad-hoc PRO user pins (**`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §1.1.1**). |
| `ai_lat` / `ai_lon` | float (optional) | **Denormalized convenience columns** when **`Coordinates`** was imagined — copy from **`tim_modality_outputs.Coordinates`** for **`AI_GUESS`** / manifest joins (`docs/GAME-ENGINE.md` §12.2). |

**Claim:** Do **not** store full patch-token streams every click—follow **`plans/2026-04-07-gradio-terramind-backend.md`** §5 retention discipline. **Do** store **structured per-modality summaries** (and **`Coordinates` → WGS84**) so **HF Jobs** and the **serving TiM worker** stay **contract-identical** for cache hydration.

---

## 8. Phased delivery

| Phase | Deliverable | Exit criteria |
|-------|-------------|---------------|
| **T0** | Pin **`terratorch`**, **`torch`**, CUDA Dockerfile/README | `python -c "import terratorch; import torch"` on target GPU/CPU |
| **T1** | **POI scanner** + JSON schema validation for `poi.json` | Loads `poi_0015` without network |
| **T2** | **Branch A** tensor builder + one successful `_*_tim` forward | No `bands=` in TiM build; logs tensor shape `[B,12,H,W]` |
| **T3** | **Branch B** Mapbox→`RGB` path | Document channel order + resize |
| **T4** | **Gradio** UI + `launch()` | Screenshot + README with run command |
| **T5** (opt) | **HF Dataset** upload script | One sample row reproducible from CI |
| **T5b** (opt) | **`generate_scan_useful_hints.py`** + **`materialize_streetview_hint_pack.py`** (or CI equivalents) | Bundle rows include **`useful_hints`** + optional **`streetview_hint_pack`**; CI validates caps + `content_version` (**§2.5**) |
| **T6** | **`_generate`** path + one **PNG** (or COG) artifact from canned POI | Schema includes `pipeline`, `output_modalities`; no OOM at default resolution on target GPU |

---

## 9. Open questions (explicit)

1. **Exact channel order** for your assembled **`S2L2A`** tensor vs Earth Search COG band ordering—must be verified against the **`terratorch` version** you pin (automated test: sum of means within expected tolerance vs reference notebook).
2. **Whether `RGB`-only TiM** with **`tim_modalities=["S2L2A"]`** is even permitted by IBM’s implementation (vs only “lower-dimensional” targets like `NDVI`). **Validate empirically** before marketing copy claims “imagines full hyperspectral cube.”
3. **README:** document which **Mapbox** / **Sentinel** assets the demo touches for operator clarity.

---

## 10. Primary references (URLs)

1. **TerraTorch TerraMind guide (TiM, modalities, `bands`, `tim_modalities`, registries):** https://terrastackai.github.io/terratorch/stable/guide/terramind/  
2. **TiM paper (linked from guide):** https://arxiv.org/pdf/2504.11171  
3. **IBM TerraMind hub (model cards / extra context):** https://ibm.github.io/terramind/ and https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-large  
4. **TerraTorch `terramind_register.py` (band names, line refs in guide):** https://github.com/IBM/terratorch/blob/53768e684a50e3f7e37d654f499dcccb4373940b/terratorch/models/backbones/terramind/model/terramind_register.py  
5. **Example TiM config (IBM terramind repo):** https://github.com/IBM/terramind/blob/main/configs/terramind_v1_base_tim_lulc_sen1floods11.yaml  
6. **Gradio server mode / FastAPI mount:** https://www.gradio.app/main/guides/server-mode/  
7. **Earth Search STAC API (Sentinel-2 L2A):** `https://earth-search.aws.element84.com/v1` (used in `data/scripts/download_simsat_sources.py`)  
8. **Mapbox Static Images API:** `https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/...` (same file as §7)  
9. **NU:TONIC POI packaging intent:** `docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`  
10. **NU:TONIC downloader implementation:** `data/scripts/download_geoguessr_poi_imagery.py`  
11. **Comprehensive Gradio + Space + ZeroGPU + manual CI plan (this monorepo):** `plans/2026-04-07-terramind-gradio-spaces-comprehensive-demo.md`  
12. **SCAN assist bundle fields + ranked forfeit policy:** `docs/GAME-ENGINE.md` §9, `docs/RANKED-MODE.md` §4  
13. **Narrative / generated inventory (assist rows):** `docs/NARRATIVE-AND-PROMPTS.md` §4  
14. **Street View + LFM-VL inference plane (batch → `streetview_hint_pack`):** `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`, `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`  

---

*This plan is intentionally strict about IBM’s **TiM** and **generation** input contracts (`all bands` on declared **raw** modalities). **Backbone-only** or **subset-band** shortcuts still require an **ADR** and explicit **`rules/06`** updates—do not “paper over” constraints in demo code comments.*
