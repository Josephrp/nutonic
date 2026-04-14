# Script specification: `build_poi_geo_context.py`

**Path:** `data/scripts/build_poi_geo_context.py`  
**Status:** Planned (**Phase C0**).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) §5 Phase C.

---

## 1. Purpose

For each catalog location, compute **offline** geographic **context** used to compile **`useful_hints`** — admin polygons, **nearest** hydrology features within radius **R**, coastline distance, optional populated places — without calling game server or Hub.

**Primary data:** vector layers under **`data/geo/`** from [SPEC-fetch-geo-baselines.md](SPEC-fetch-geo-baselines.md).

---

## 2. Inputs

| Input | Description |
|-------|-------------|
| **`--catalog-root`** | `data/catalog/locations/*.yaml` |
| **`--geo-root`** | `data/geo` (Natural Earth shapefiles / geopackage) |
| **`--poi-root`** | Optional; used only if extra fields must be re-read from original `poi.json` |
| **`--r-max-km`** | Default **200** |
| **`--r-scale-k`** | Multiplier on `bbox_km_half`: **`R = min(R_max, k * bbox_km_half)`**; default **k=3** |
| **`--fallback-country-iso`** | Use `country_iso` from catalog when point-in-polygon misses ocean / antimeridian edge cases |

---

## 3. Output schema (`context.json`)

One file per location, e.g. **`data/cache/<content_version>/geo_context/<location_id>.json`**:

```json
{
  "location_id": "poi_0067",
  "schema_version": "nutonic.geo_context.v1",
  "truth": { "lat": -8.7414, "lon": 115.5996 },
  "admin0_name": "Indonesia",
  "admin1_name": "Bali",
  "continent": "Asia",
  "nearest_river": { "name": "…", "distance_km": 12.4 },
  "nearest_lake": { "name": null, "distance_km": null },
  "coast_distance_km": 8.2,
  "feature_distances": [],
  "sources": { "natural_earth_version": "5.1.2", "layers": ["admin_0", "admin_1", "rivers", "lakes", "coastline"] }
}
```

**Privacy:** This file is **internal** to the pipeline; it **may** contain precise coordinates — **never** ship `context.json` to client ranked packs without redaction policy (only **compiled tiers** ship for ranked assists).

**Consumers**

| Downstream | Uses `context.json` for |
|------------|-------------------------|
| **`compile_useful_hint_tiers`** | Deterministic `tier_*` strings (names + distance buckets). |
| **`generate_useful_hints_llm`** | Sector binning + hydrology labels; **must not** forward raw `truth` decimals into prompts when `ranked_safe` (see [SPEC-generate-useful-hints-llm.md](SPEC-generate-useful-hints-llm.md) §4). |
| **`batch_streetview_hints`** | **Does not** read `context.json` by default — pano sampling uses **catalog** WGS84 only; optional **`--geo-context-coast-hint`** future hook must stay **non-spoiler** (no street addresses). |

---

## 4. Implementation constraints

- **Libraries:** `geopandas`, `shapely`, `pyproj` (see `data/scripts/requirements.txt` when implemented).
- **CRS:** Use a **projected CRS** per POI for distance queries (e.g. UTM zone from centroid, or EPSG:3857 with acceptance of error at poles — document choice).
- **Performance:** Pre-spatial-index rivers/lakes for bbox subset around each POI buffer polygon.

---

## 5. CLI

```text
python data/scripts/build_poi_geo_context.py [--catalog-root …] [--geo-root …] [--content-version …]
```

---

## 6. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 6 | Missing `data/geo` layers (run `fetch_geo_baselines`) |
| 7 | Geometry engine error |

---

## 7. Related

- [SPEC-compile-useful-hint-tiers.md](SPEC-compile-useful-hint-tiers.md) — consumer.
- [SPEC-geo-nutonic.md](SPEC-geo-nutonic.md) — distance helpers.
- **`refs/terramind-geogen-main/src/geo_utils.py`** — conceptual haversine parity only (no import).

---

*Spec version: 2026-04-14*
