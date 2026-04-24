# Plan: PRO Mini-Apps LFM-VL SFT Datasets for Fine-Tuning

**Date:** 2026-04-24  
**Status:** Implementation plan.  
**Goal:** Produce **multi-image, multi-task VLM SFT datasets** targeting the **five PRO mini-app verticals** (FireWatch, OceanScout, LandShift, FloodPulse, Brief Composer). Each dataset teaches the LFM-VL model to accept **one or more geospatial images** and produce **bounding boxes + explanatory text** aligned with the specific analysis profile. Datasets are formatted for **`leap-finetune` `vlm_sft`** training and upload to **HuggingFace**.

**Normative context:**
- `plans/2026-04-22-pro-mini-apps-master-implementation-plan.md` — PRO mini-app verticals and inference contracts
- `plans/2026-04-21-lfm-vl-geoguessr-dynamic-world-dataset-plan.md` — existing Dynamic World SFT pipeline
- `docs/scripts/SPEC-lfm-vl-sft-dataset.md` — existing dataset builder spec
- `refs/leap-finetune-main/README.md` — target training framework and VLM SFT format

---

## 0. Executive summary

The existing `build_lfm_vl_sft_dataset.py` pipeline produces **single-image captioning + grounding** from Sentinel-2 + Dynamic World. PRO mini-apps require **richer tasks**: temporal change detection (multi-image), domain-specific grounding (fire scars, vessels, flood extent, land transitions), and structured analytical briefs. This plan extends the pipeline into **five profile-specific dataset builders** that share a common multi-image JSONL format, common image acquisition infrastructure, and push to HuggingFace Hub repos.

| Dataset | Images per sample | Primary output | Training signal source |
|---------|-------------------|----------------|------------------------|
| **FireWatch-SFT** | 2 (t0, t1) | Burn scar bboxes + change narrative | dNBR change mask from S2 bands |
| **OceanScout-SFT** | 1–2 | Vessel candidate bboxes + evidence text | NDWI water mask + bright target detection |
| **LandShift-SFT** | 2 (t0, t1) | Land class transition bboxes + summary | Dynamic World label diff |
| **FloodPulse-SFT** | 2 (t0, t1) | Inundation extent bboxes + stats | NDWI/MNDWI water expansion mask |
| **BriefComposer-SFT** | 1–4 (mixed) | Structured analytical brief text | Composited annotations from above |

---

## 1. Target format: `leap-finetune` VLM SFT with multi-image

### 1.1 JSONL row structure

Per `refs/leap-finetune-main/README.md` §VLM SFT, the collate function in `tokenize_data.py` expects:

```json
{
  "messages": [
    {
      "role": "system",
      "content": [{"type": "text", "text": "You are a geospatial analyst..."}]
    },
    {
      "role": "user",
      "content": [
        {"type": "image", "image": "images/sample_001_t0.png"},
        {"type": "image", "image": "images/sample_001_t1.png"},
        {"type": "text", "text": "Compare these two Sentinel-2 images taken 3 months apart. Identify and locate areas of significant land cover change."}
      ]
    },
    {
      "role": "assistant",
      "content": [{"type": "text", "text": "I observe significant change in two regions:\n\n1. **Agricultural expansion** at [0.32, 0.41, 0.58, 0.67]: A forested area in the northeast has been cleared for farming...\n2. **Urban development** at [0.71, 0.12, 0.89, 0.28]: New construction is visible..."}]
    }
  ]
}
```

**Key points verified from `tokenize_data.py:67-119`:**
- Multiple `{"type": "image", "image": path}` entries in a single user message are supported — the collate function iterates all content items and loads each image via `load_image()`
- Images can be local paths (relative to `image_root` in config), URLs, or bytes
- Loss is masked to **assistant content only** via ChatML `<|im_start|>assistant\n....<|im_end|>` template matching
- Bboxes in assistant text use **0–1 normalized** `[x1, y1, x2, y2]` format (verified by `metrics.py:_parse_bbox` which normalizes 0–1000 to 0–1)

### 1.2 Bbox format in assistant text

From `metrics.py:score_grounding_iou` and `_parse_bbox`:
- Bboxes are embedded in assistant response as `[x1, y1, x2, y2]` 
- Coordinates are **0–1 normalized** relative to image dimensions
- Multiple bboxes per response are supported (JSON array of objects with `"bbox"` key, or nested lists)
- `grounding_iou` metric evaluates at `iou_threshold=0.5` by default

### 1.3 Existing pipeline reuse

The existing pipeline (`data/scripts/lfm_vl_sft_dataset/`) provides:
- **`instances.py`**: `find_regions()` → connected components per class → axis-aligned bboxes
- **`jsonl_format.py`**: `make_vlm_message()` → correct VLM SFT JSONL structure
- **`tile_io.py`**: raster tiling with stride/overlap
- **`s2_rgb.py`**: Sentinel-2 RGB stack from STAC
- **`ee_dynamic_world.py`**: Earth Engine Dynamic World label fetch
- **`bbox_overlay.py`**: QA overlay rendering
- **`image_aug.py`**: flip/rotate augmentation
- **`geo_jitter.py`**: offset-based data diversification
- **`hf_upload.py`**: Hub dataset push
- **`orchestrator_lib.py`**: multi-batch parallel execution

---

## 2. Dataset-specific designs

### 2.1 FireWatch-SFT (wildfire / burn scar detection)

**Training task:** Given two Sentinel-2 images (pre-fire t0, post-fire t1), identify burn scars and fire-affected areas with bounding boxes and narrative.

**Image acquisition:**
1. Source fire event catalogs: NASA FIRMS active fire data, EFFIS burn area products, or curated lat/lon from known wildfire events (e.g. California 2023-2025, Australia, Mediterranean, Amazon)
2. For each event: STAC search for **two** S2 L2A scenes — one **pre-event** (30–90 days before), one **post-event** (7–60 days after)
3. Both scenes tiled to aligned patches (same CRS/transform per pair)

**Change signal extraction:**
1. Compute **dNBR** (differenced Normalized Burn Ratio) from S2 bands B08 (NIR) and B12 (SWIR):
   - `NBR = (B08 - B12) / (B08 + B12)`
   - `dNBR = NBR_pre - NBR_post`
2. Threshold dNBR into severity classes: unburned (<0.1), low (0.1–0.27), moderate-low (0.27–0.44), moderate-high (0.44–0.66), high (>0.66) — per USGS standard
3. Connected components on thresholded mask → bounding boxes per severity class

**JSONL tasks (per tile pair):**

| Task | User prompt | Assistant output |
|------|-------------|-----------------|
| **Change captioning** | "These two satellite images show the same area before and after a fire event. Describe what changed." | Narrative with burn area %, severity distribution, affected land types |
| **Burn grounding** | "Locate the burn scars in the post-fire image." | `[{"label": "high_severity_burn", "bbox": [x1,y1,x2,y2]}, ...]` with normalized coords |
| **Severity assessment** | "Assess the fire damage severity comparing these images." | Structured text: area stats, severity bins, confidence notes |

**Target volume:** 5,000–10,000 tile pairs from 50–100 fire events globally.

### 2.2 OceanScout-SFT (vessel / maritime detection)

**Training task:** Given one or two coastal/ocean S2 images, identify vessel candidates and characterize maritime activity.

**Image acquisition:**
1. Sample ports, shipping lanes, and marine protected areas worldwide
2. STAC search for low-cloud S2 scenes; prefer scenes with known AIS-correlated vessel presence
3. Single-image (snapshot detection) and optional dual-image (temporal aggregation) samples

**Detection signal extraction:**
1. Compute **NDWI** = (B03 - B08) / (B03 + B08) to create water mask
2. On water pixels, detect **bright targets** (anomalously high reflectance in B02/B03/B04 relative to water background) via local contrast filter
3. Apply shoreline buffer (500m from coastline) to retain harbor vessels
4. Minimum target size filter (≥ 3×3 px at 10m = ~30m objects)
5. Generate bounding boxes around detected bright targets

**JSONL tasks (per tile):**

| Task | User prompt | Assistant output |
|------|-------------|-----------------|
| **Vessel detection** | "Identify potential vessels visible in this satellite image of a coastal area." | `[{"label": "vessel_candidate", "confidence": "high/medium", "bbox": [...]}]` + evidence text |
| **Maritime captioning** | "Describe the maritime activity visible in this satellite image." | Narrative: vessel count estimate, activity pattern, water conditions, observation quality notes |
| **Coverage assessment** | "Assess the observation quality of this maritime image." | Cloud %, sun-glint extent, water fraction, limitations text |

**Claim safety:** All assistant text must include evidence qualifiers ("potential vessel", "candidate detection", "optical-only observation"). No text implies certainty from optical-only EO (per master plan §0.2 item 4).

**Target volume:** 3,000–5,000 tiles from 100+ coastal/port locations.

### 2.3 LandShift-SFT (land use / land cover change)

**Training task:** Given two S2 images from different dates, identify and describe land cover transitions.

**Image acquisition:**
1. Reuse existing Dynamic World pipeline (`build_lfm_vl_sft_dataset.py`) but acquire **temporal pairs**: same location, 6–24 months apart
2. Both scenes need valid Dynamic World labels

**Change signal extraction:**
1. Compute **transition matrix** from Dynamic World `label` at t0 vs t1
2. For each significant transition (e.g. `trees → crops`, `bare → built`), locate changed regions via connected components on the transition mask
3. Filter by minimum area (100px at 10m) and compute transition statistics

**JSONL tasks (per tile pair):**

| Task | User prompt | Assistant output |
|------|-------------|-----------------|
| **Change detection** | "Compare these satellite images taken {N} months apart. What land cover changes occurred?" | Narrative: top transitions with area %, direction of change |
| **Transition grounding** | "Locate areas where forest was converted to agricultural land." | `[{"label": "trees_to_crops", "bbox": [...]}, ...]` |
| **Change summary** | "Provide a structured land use change analysis for this area." | Transition matrix text + bbox highlights + confidence |

**Target volume:** 8,000–15,000 tile pairs from 200+ global locations (diverse biomes).

### 2.4 FloodPulse-SFT (water extent / flood detection)

**Training task:** Given two S2 images (pre-flood baseline, during/post-flood), identify expanded water bodies and estimate inundation extent.

**Image acquisition:**
1. Source flood event catalogs: Copernicus EMS, DFO Global Archive, or curated events
2. STAC search for pre-event (dry season baseline) and post-event (flood peak or recession) S2 scenes
3. Cloud filtering critical — flood events often have high cloud cover

**Change signal extraction:**
1. Compute **MNDWI** (Modified NDWI) = (B03 - B11) / (B03 + B11) for both dates
2. Water mask: MNDWI > threshold (calibrated per scene) or Dynamic World `water` class
3. **Flood extent** = water_t1 AND NOT water_t0 (newly inundated areas)
4. Connected components on flood extent → bounding boxes

**JSONL tasks (per tile pair):**

| Task | User prompt | Assistant output |
|------|-------------|-----------------|
| **Flood detection** | "Compare these satellite images to identify areas of flooding or water expansion." | Narrative: inundated area estimate, affected land types, extent description |
| **Inundation grounding** | "Locate the flooded areas in the second image." | `[{"label": "inundation", "bbox": [...], "area_pct": 12.3}, ...]` |
| **Impact assessment** | "Assess the flood impact comparing these two images." | Affected area stats, proximity to built areas, observation quality |

**Target volume:** 3,000–6,000 tile pairs from 50–80 flood events globally.

### 2.5 BriefComposer-SFT (multi-source analytical synthesis)

**Training task:** Given 1–4 images from various analysis profiles + structured metadata, produce a consolidated analytical brief.

**Sample construction:**
1. Draw from completed FireWatch, OceanScout, LandShift, and FloodPulse samples
2. Each brief sample includes 1–4 images from the same or nearby geographic areas
3. Input includes structured metadata summaries (area stats, severity levels, transition counts) as text context alongside images

**JSONL tasks (per composite):**

| Task | User prompt | Assistant output |
|------|-------------|-----------------|
| **Executive brief** | "[4 images + metadata] Compose a brief synthesizing these analysis results for the area around {location}." | Structured: Executive Summary, Key Findings (with bbox refs), Confidence Assessment, Recommended Actions |
| **Single-profile brief** | "[1-2 images + metadata] Write a concise analytical summary of this {profile} analysis." | Profile-specific brief with findings, limitations, and confidence |

**Target volume:** 2,000–4,000 composite samples.

---

## 3. Shared infrastructure

### 3.1 Multi-temporal STAC acquisition module

**New module:** `data/scripts/lfm_vl_sft_dataset/temporal_stac.py`

Extends the existing S2 STAC search to support **paired temporal queries**:

```python
def search_temporal_pair(
    lat: float, lon: float, bbox_half_km: float,
    event_date: str,
    pre_window_days: int = 90,
    post_window_days: int = 60,
    max_cloud_pct: float = 30.0,
) -> tuple[STACItem | None, STACItem | None]:
    """Search for pre/post event S2 scenes."""
```

Returns the best (lowest cloud) pre-event and post-event STAC items. Reuses existing `s2_stac` helpers for asset download and band stacking.

### 3.2 Spectral index computation module

**New module:** `data/scripts/lfm_vl_sft_dataset/spectral_indices.py`

Centralizes index computation from S2 L2A bands:

```python
def compute_nbr(nir: np.ndarray, swir2: np.ndarray) -> np.ndarray: ...
def compute_ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray: ...
def compute_mndwi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray: ...
def compute_dnbr(nbr_pre: np.ndarray, nbr_post: np.ndarray) -> np.ndarray: ...
```

All functions handle nodata masking and return float32 arrays with NaN for invalid pixels.

### 3.3 Change detection instance extraction

**New module:** `data/scripts/lfm_vl_sft_dataset/change_instances.py`

Extends `instances.py` for binary change masks:

```python
def find_change_regions(
    change_mask: np.ndarray,
    min_area_px: int = 100,
    max_regions: int = 20,
    label_name: str = "change",
) -> list[Region]:
    """Connected components on binary change mask → Region list with bboxes."""
```

Returns `Region` objects compatible with existing `jsonl_format.make_vlm_message()`.

### 3.4 Multi-image JSONL formatter

**Extended in:** `data/scripts/lfm_vl_sft_dataset/jsonl_format.py`

Add new function alongside existing `make_vlm_message`:

```python
def make_multi_image_vlm_message(
    image_paths: list[str],
    user_text: str,
    assistant_text: str,
    system_text: str | None = None,
    regions: list[Region] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build VLM SFT row with multiple images in the user message."""
```

Produces the same `{"messages": [...]}` structure but with N image entries in the user content list.

### 3.5 Event catalog and sampling

**New module:** `data/scripts/lfm_vl_sft_dataset/event_catalog.py`

Provides curated event locations for each profile:

```python
@dataclass
class GeoEvent:
    event_id: str
    lat: float
    lon: float
    event_date: str  # ISO8601
    profile: str  # "wildfire", "flood", "land_use_change"
    source: str  # "FIRMS", "EFFIS", "DFO", "manual"
    metadata: dict = field(default_factory=dict)

def load_fire_events(source: str = "firms_csv") -> list[GeoEvent]: ...
def load_flood_events(source: str = "dfo_csv") -> list[GeoEvent]: ...
def sample_coastal_locations(n: int, min_separation_km: float = 50) -> list[GeoEvent]: ...
def sample_land_change_locations(n: int) -> list[GeoEvent]: ...
```

Event sources:
- **FIRMS:** NASA Fire Information for Resource Management System CSV (public, global, daily)
- **DFO:** Dartmouth Flood Observatory archive (public, global, event-level)
- **Manual:** Curated JSON of known events with verified S2 availability
- **Coastal ports:** Natural Earth ports + OpenStreetMap coastline sampling

### 3.6 Prompt templates

**New file:** `data/scripts/lfm_vl_sft_dataset/pro_prompts.py`

```python
SYSTEM_GEOSPATIAL_ANALYST = (
    "You are a geospatial analyst specializing in satellite imagery interpretation. "
    "Analyze the provided Sentinel-2 satellite images and report your findings. "
    "Use [x1, y1, x2, y2] bounding box coordinates normalized to 0-1 relative to image dimensions. "
    "Always state confidence levels and limitations of optical-only analysis."
)

FIREWATCH_CHANGE_CAPTION = (
    "These two Sentinel-2 satellite images show the same {area_desc} area. "
    "The first image was captured on {date_t0} and the second on {date_t1}. "
    "Identify and describe any wildfire damage or burn scars visible between the two dates."
)

FIREWATCH_GROUNDING = (
    "Locate all burn scars and fire-affected areas visible in the post-fire satellite image. "
    "Report each area with a bounding box and severity assessment."
)

OCEANSCOUT_DETECT = (
    "Examine this Sentinel-2 satellite image of {area_desc}. "
    "Identify any potential vessels or maritime activity visible in the water areas."
)

# ... (additional templates per profile)
```

### 3.7 Rule-based caption generation

**New module:** `data/scripts/lfm_vl_sft_dataset/caption_rules.py`

Generates deterministic training captions from computed change masks and region statistics:

```python
def firewatch_caption(regions: list[Region], stats: ChangeStats) -> str:
    """Deterministic burn scar caption from dNBR regions + area stats."""

def oceanscout_caption(regions: list[Region], water_frac: float, obs_quality: str) -> str:
    """Maritime activity caption from bright-target regions + observation quality."""

def landshift_caption(transition_matrix: dict, regions: list[Region]) -> str:
    """Land cover change narrative from transition matrix + change regions."""

def floodpulse_caption(regions: list[Region], stats: FloodStats) -> str:
    """Flood extent caption from inundation regions + area stats."""

def brief_caption(findings: list[dict], profile_mix: list[str]) -> str:
    """Composite analytical brief from multiple profile findings."""
```

All captions follow rules:
1. No invented certainty — always include observation quality and limitations
2. Optical-only caveats where applicable (especially OceanScout)
3. Area statistics use consistent resolution (mask resolution, not display resolution)
4. Bounding box references use 0–1 normalized coordinates

---

## 4. Per-profile builder scripts

### 4.1 Common builder pattern

Each profile gets a builder script that follows the same pattern as `build_lfm_vl_sft_dataset.py`:

```
data/scripts/
  build_lfm_vl_firewatch_sft.py          # FireWatch dataset builder
  build_lfm_vl_oceanscout_sft.py         # OceanScout dataset builder
  build_lfm_vl_landshift_sft.py          # LandShift dataset builder (extends existing DW pipeline)
  build_lfm_vl_floodpulse_sft.py         # FloodPulse dataset builder
  build_lfm_vl_brief_sft.py             # BriefComposer dataset builder (consumes other outputs)
```

Each script:
1. Loads event catalog or location samples
2. Downloads temporal S2 pairs via shared STAC infrastructure
3. Computes profile-specific masks/indices
4. Extracts regions via change detection instances
5. Generates multi-image JSONL rows with rule-based captions
6. Writes images, metadata, and split JSONL files
7. Optionally uploads to HuggingFace

### 4.2 Unified orchestrator

**New script:** `data/scripts/run_pro_sft_orchestrator.py`

Coordinates building all five datasets:

```bash
python data/scripts/run_pro_sft_orchestrator.py \
  --profiles firewatch,oceanscout,landshift,floodpulse \
  --events-per-profile 50 \
  --out-dir data/downloads/pro_sft \
  --upload-repo NuTonic/pro-mini-apps-sft \
  --ee-project $EE_PROJECT
```

Can also build a single profile:

```bash
python data/scripts/build_lfm_vl_firewatch_sft.py \
  --events data/events/fires_2024.csv \
  --out-dir data/downloads/firewatch_sft \
  --upload-repo NuTonic/firewatch-sft-v1
```

---

## 5. Hub dataset layout

### 5.1 Per-profile repos

| HuggingFace repo | Content |
|-------------------|---------|
| `NuTonic/firewatch-sft-v1` | FireWatch temporal pairs + burn grounding |
| `NuTonic/oceanscout-sft-v1` | OceanScout maritime detection + captioning |
| `NuTonic/landshift-sft-v1` | LandShift temporal pairs + transition grounding |
| `NuTonic/floodpulse-sft-v1` | FloodPulse temporal pairs + inundation grounding |
| `NuTonic/brief-composer-sft-v1` | BriefComposer composite samples |
| `NuTonic/pro-mini-apps-sft-combined-v1` | Union of all profiles for mixed training |

### 5.2 Repo structure

Each repo follows the existing `raw-sft-init` pattern:

```
images/
  {event_id}_{tile_idx}_t0.png      # Pre-event RGB (224×224 default)
  {event_id}_{tile_idx}_t1.png      # Post-event RGB (when temporal)
overlays/
  {event_id}_{tile_idx}__{row_idx}_{task}.png  # QA bbox overlays
metadata/
  {event_id}_{tile_idx}.json        # Geo sidecar (lat, lon, dates, STAC IDs, mask stats)
data/
  train.jsonl                       # 80% split
  validation.jsonl                  # 10% split
  test.jsonl                        # 10% split
README.md                           # Dataset card
```

### 5.3 leap-finetune training config

```yaml
project_name: "nutonic_pro_firewatch"
model_name: "LFM2-1.2B"
training_type: "vlm_sft"

dataset:
  path: "NuTonic/firewatch-sft-v1"
  type: "vlm_sft"
  image_root: "images/"

training_config:
  extends: "DEFAULT_VLM_SFT"
  num_train_epochs: 5
  per_device_train_batch_size: 1
  learning_rate: 1e-5
  vision_encoder_lr_multiplier: 0.1

peft_config:
  extends: "DEFAULT_VLM_LORA"
  use_peft: true

benchmarks:
  benchmarks:
    - name: "firewatch_grounding"
      path: "data/test.jsonl"
      metric: "grounding_iou"
    - name: "firewatch_caption"
      path: "data/test.jsonl"
      metric: "rouge_l"
```

---

## 6. Implementation stages

### Stage 0: Shared infrastructure (Week 1)

1. `temporal_stac.py` — multi-temporal STAC search
2. `spectral_indices.py` — NBR, NDWI, MNDWI, dNBR
3. `change_instances.py` — binary change mask → regions + bboxes
4. Extend `jsonl_format.py` with `make_multi_image_vlm_message()`
5. `pro_prompts.py` — system/user/assistant prompt templates
6. `caption_rules.py` — deterministic caption generators per profile
7. `event_catalog.py` — event source loaders + samplers
8. Tests for all new modules (offline, no EE/network)

### Stage 1: FireWatch + LandShift builders (Week 2)

Priority: these two profiles share the most with the existing DW pipeline.

1. `build_lfm_vl_firewatch_sft.py` — full pipeline from FIRMS events → JSONL
2. `build_lfm_vl_landshift_sft.py` — extends existing DW pipeline for temporal pairs
3. Smoke test: 12 events each → ~500 JSONL rows
4. QA: manual review of 20 random overlay images per profile
5. Upload smoke datasets to Hub

### Stage 2: FloodPulse + OceanScout builders (Week 3)

1. `build_lfm_vl_floodpulse_sft.py` — DFO events → temporal pairs → MNDWI flood extent
2. `build_lfm_vl_oceanscout_sft.py` — coastal ports → single/dual image → vessel detection
3. OceanScout-specific: implement bright-target detection on water mask, shoreline buffer
4. Smoke test and QA as above

### Stage 3: BriefComposer + unified orchestrator (Week 4)

1. `build_lfm_vl_brief_sft.py` — composite from other profile outputs
2. `run_pro_sft_orchestrator.py` — all-profiles coordinator
3. Combined dataset upload
4. `leap-finetune` dry-run validation on each profile + combined dataset

### Stage 4: Scale + training handoff (Week 5+)

1. Scale event catalogs to target volumes (§2 targets)
2. Full dataset builds via orchestrator (likely HF Jobs for compute)
3. Training configs for each profile + combined multitask
4. Push trained checkpoints; pin revision in `lfm_vl_hint_service` / `lfm_vl_satellite_caption_service` configs

---

## 7. Sentinel-2 band requirements per profile

| Profile | Required S2 L2A bands | Purpose |
|---------|----------------------|---------|
| **FireWatch** | B03 (Green), B04 (Red), B08 (NIR), B12 (SWIR 2.2µm) | RGB display + NBR computation |
| **OceanScout** | B02 (Blue), B03 (Green), B04 (Red), B08 (NIR) | RGB display + NDWI + bright target detection |
| **LandShift** | B02, B03, B04 (RGB display) + Dynamic World label | Visual + existing DW pipeline |
| **FloodPulse** | B03 (Green), B04 (Red), B08 (NIR), B11 (SWIR 1.6µm) | RGB display + MNDWI flood detection |
| **BriefComposer** | Inherits from input profiles | N/A |

The existing STAC download (`download_simsat_sources.py`) supports `--sentinel-mode full` which fetches all bands. For profiles needing specific bands, add `--sentinel-bands` flag or use the existing per-asset download in `s2_stac.py`.

---

## 8. Task taxonomy and row expansion

Each tile (or tile pair) produces **multiple JSONL rows** at different task levels:

| Row type | Images | Output | Volume multiplier |
|----------|--------|--------|-------------------|
| **Global caption** | All images for sample | Full narrative description | 1× |
| **Full grounding** | All images | All bboxes + labels JSON | 1× |
| **Per-class/region grounding** | Relevant image(s) | Single region bbox + description | up to N× per detected region |
| **VQA** | All images | Answer to specific question | 2–3× per sample |
| **Structured brief** | All images | Formatted analytical brief | 1× (BriefComposer only) |

**Expected per-tile expansion:** 4–8 rows per tile/tile-pair on average.

---

## 9. Quality and safety controls

### 9.1 Caption quality

- All captions are **deterministic** (rule-based from mask statistics) for the v1 dataset
- No LLM-generated captions in v1 to maintain ablation purity
- Optional v2 pass: VLM-generated caption diversity (document as separate experiment)

### 9.2 Claim safety (OceanScout especially)

- Assistant text must never use: "illegal", "suspicious activity", "confirmed vessel"
- Approved vocabulary: "potential vessel candidate", "bright target consistent with vessel", "optical-only detection"
- Evidence labels: `optical_only`, `ndwi_filtered`, `size_consistent` — emitted per detection

### 9.3 Bbox quality

- Minimum region area: 100px at native 10m resolution (= ~10,000 m²)
- Maximum regions per tile: 20 (avoid noise-dominated tiles)
- Tiles with < 5% valid (non-cloud) pixels are discarded
- Bbox coordinates validated: all within [0, 1], x2 > x1, y2 > y1

### 9.4 Temporal alignment

- Pre/post scenes must cover > 80% overlapping footprint
- Maximum cloud cover per scene: 30% (configurable)
- Scene provenance (STAC item IDs, datetimes) recorded in metadata JSON

---

## 10. Testing strategy

| Test type | Coverage | Network? |
|-----------|----------|----------|
| **Unit** | Spectral index math, bbox normalization, JSONL schema validation, caption templates, prompt formatting | No |
| **Integration (synthetic)** | Full pipeline with `--synthetic-labels` (random masks), multi-image JSONL correctness | No |
| **Integration (EE)** | Real Dynamic World + STAC scenes for 3 smoke POIs per profile | Yes (`@pytest.mark.integration`) |
| **Schema validation** | Pydantic model for every JSONL row; verify `leap-finetune` collate doesn't error on 50-row sample | No (if images exist) |
| **Training dry-run** | 50-step `leap-finetune` on tiny shard per profile | Yes (GPU) |

---

## 11. File layout

```
data/scripts/
  build_lfm_vl_firewatch_sft.py
  build_lfm_vl_oceanscout_sft.py
  build_lfm_vl_landshift_sft.py
  build_lfm_vl_floodpulse_sft.py
  build_lfm_vl_brief_sft.py
  run_pro_sft_orchestrator.py
  lfm_vl_sft_dataset/
    temporal_stac.py           # Multi-temporal STAC search
    spectral_indices.py        # NBR, NDWI, MNDWI, dNBR
    change_instances.py        # Binary change mask → regions
    pro_prompts.py             # Profile-specific prompt templates
    caption_rules.py           # Deterministic caption generators
    event_catalog.py           # Fire/flood/coastal event sources
    jsonl_format.py            # (extended) Multi-image JSONL support
    instances.py               # (existing) Connected component regions
    tile_io.py                 # (existing) Raster tiling
    s2_rgb.py                  # (existing) S2 RGB stack
    ee_dynamic_world.py        # (existing) Dynamic World labels
    bbox_overlay.py            # (existing) QA overlay rendering
    image_aug.py               # (existing) Flip/rotate augmentation
    hf_upload.py               # (existing) Hub dataset push
    orchestrator_lib.py        # (existing) Multi-batch coordination
  tests/
    test_spectral_indices.py
    test_change_instances.py
    test_multi_image_jsonl.py
    test_caption_rules.py
    test_pro_prompts.py
    test_event_catalog.py
    test_firewatch_pipeline.py
    test_oceanscout_pipeline.py
docs/scripts/
  SPEC-pro-mini-apps-sft-datasets.md
data/events/
  fires_curated.csv            # Curated fire event locations
  floods_curated.csv           # Curated flood event locations
  coastal_ports.csv            # Port/coastal sampling locations
```

---

## 12. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| **Temporal pair cloud contamination** | Strict SCL filtering; discard tiles with > 30% cloud in either scene; log match quality |
| **dNBR false positives from agriculture** | Cross-reference with Dynamic World labels; agricultural areas flagged in metadata |
| **Vessel detection noise from sun glint** | Sun-glint masking from B08/B12 ratio; observation quality label in every sample |
| **STAC temporal gaps** | Widen search windows (±120 days pre, ±90 days post); document gap policy per event |
| **EE quota limits for Dynamic World** | Batch export with rate limiting; fallback to pre-downloaded label archives |
| **Bbox meaningfulness** | Manual QA pass on 100 random overlays per profile before full-scale build |
| **Caption template diversity** | Add 3–5 template variants per task; geo-jitter for spatial diversity |

---

## 13. Acceptance criteria

1. **Shared infrastructure** passes all unit tests (offline).
2. **Each profile builder** produces ≥100 valid JSONL rows from ≥5 events in smoke mode.
3. **Multi-image JSONL rows** load without error in `leap-finetune` collate function (50-row validation).
4. **Bounding boxes** overlay correctly on QA images (visual check on 20 random tiles per profile).
5. **Caption text** contains no claim-safety violations (automated regex check for banned terms).
6. **Combined dataset** produces ≥1,000 rows per profile for `leap-finetune` dry-run (50 training steps, no data errors).
7. **Hub upload** succeeds for each per-profile repo and combined repo.
8. **Dataset cards** document: data sources, licensing (S2 Copernicus open, Dynamic World Google ToS, FIRMS public), known limitations, and provenance chain.

---

## 14. References

- `data/scripts/build_lfm_vl_sft_dataset.py` — existing single-image SFT builder
- `data/scripts/lfm_vl_sft_dataset/` — existing pipeline modules
- `docs/scripts/SPEC-lfm-vl-sft-dataset.md` — existing builder spec
- `plans/2026-04-21-lfm-vl-geoguessr-dynamic-world-dataset-plan.md` — existing DW dataset plan
- `plans/2026-04-22-pro-mini-apps-master-implementation-plan.md` — PRO mini-app verticals and inference contracts
- `refs/leap-finetune-main/` — target training framework
- `refs/leap-finetune-main/src/leap_finetune/data_loaders/tokenize_data.py` — VLM collate and loss masking
- `refs/leap-finetune-main/src/leap_finetune/evaluation/metrics.py` — `grounding_iou` bbox format

---

## 15. Version history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-24 | Initial plan: 5 profile-specific dataset builders, shared multi-temporal infrastructure, multi-image VLM SFT format, event-driven sampling, rule-based captions, claim safety controls. |
