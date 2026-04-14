# Script specification: `download_geoguessr_poi_imagery.py`

**Path:** `data/scripts/download_geoguessr_poi_imagery.py`  
**Status:** **Shipped** (existing). This document normatively describes behavior contract for downstream scripts.  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) §3, §5.0.

---

## 1. Purpose

Download and package **GeoGuessr-style** POI rows from a Hugging Face dataset (default: `stochastic/random_streetview_images_pano_v0.0.2`) into `data/downloads/<out-dir>/poi_*/` with:

- `poi.json` metadata (WGS84, optional bbox, HF row meta, selection stats),
- Mapbox static satellite PNGs,
- Optional Sentinel-2 L2A via STAC.

Subsequent pipeline scripts (**catalog_import_poi**, **render_mapbox_still**, proximity hints) **consume** this tree.

---

## 2. Non-goals

- Does **not** emit `useful_hints`, manifest JSON, or Kotlin resources.
- Does **not** call LFM-VL or game server APIs.
- Does **not** require TerraTorch / `refs/terramind-geogen-main` imports at runtime (docstring references only).

---

## 3. Coordinate and distance contract

- **`haversine_km(lon1, lat1, lon2, lat2)`** uses **(longitude, latitude)** order to align with **`refs/terramind-geogen-main/src/geo_utils.py`** tensor convention `(lon, lat)` documented in-file.
- Any new shared helpers should move to **`geo_nutonic.py`** (see [SPEC-geo-nutonic.md](SPEC-geo-nutonic.md)) without changing this signature.

---

## 4. Outputs (normative for consumers)

### 4.1 Twelve-point layout (`geoguessr_poi_12/`)

- **`geoguessr_poi_manifest.json`**: `points[]` with `poi_id`, `latitude`, `longitude`, `mapbox.path`, etc.
- Per-POI folder **`poi_NNNN/`** with `mapbox/*.png`.

### 4.2 Hundred-twenty layout (`geoguessr_poi_120/`)

- Per-POI **`poi_*/poi.json`**: includes **`bbox_wgs84`**, **`bbox_km_half`**, **`hf_row_meta`** (`country_iso_alpha2`, `address`, …), **`selection`**, **`mapbox.path`**.

### 4.3 Path portability

- `mapbox.path` may be an **absolute** filesystem path from the machine that ran the download. **`catalog_import_poi`** must normalize to **repo-relative** paths (see [SPEC-catalog-import-poi.md](SPEC-catalog-import-poi.md)).

---

## 5. CLI and environment

- Documented in script docstring: `pip install -r data/scripts/requirements.txt`, `--out-dir`, `--num-points`, `--auto-min-separation`, etc.
- **Secrets:** `.env` at repo root (optional `python-dotenv`); Mapbox / HF / STAC as required by chosen modes.

---

## 6. Related specifications

- [SPEC-catalog-import-poi.md](SPEC-catalog-import-poi.md) — primary consumer of output trees.
- [SPEC-render-mapbox-still.md](SPEC-render-mapbox-still.md) — may reuse or re-render `mapbox` PNGs.

---

*Spec version: 2026-04-14*
