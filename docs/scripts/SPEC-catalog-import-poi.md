# Script specification: `catalog_import_poi.py`

**Path:** `data/scripts/catalog_import_poi.py`  
**Status:** **Implemented** (v1 — Layout A/B, `maps.yaml` merge, `--maps-file` overrides, `render_policy` fallback when still missing).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase A.

---

## 1. Purpose

Ingest POI trees produced by **`download_geoguessr_poi_imagery.py`** (or compatible layouts) into **`data/catalog/`** — normalized YAML (or JSON) rows that downstream phases (**still render**, **geo context**, **manifest assemble**) consume.

---

## 2. Inputs

| Input | Description |
|-------|-------------|
| **`--poi-root`** | Default **`data/downloads/geoguessr_poi_12`**. May point to **`data/downloads/geoguessr_poi_120`**. |
| **Layout A** | **`geoguessr_poi_manifest.json`** at root of `poi-root` listing points (12-set). |
| **Layout B** | Glob **`poi_*/poi.json`** (120-set). |
| **`--maps-file`** | Optional override for `data/catalog/maps.yaml` merge rules (titles, `ranked_eligible`, `mission_id`). |

---

## 3. Outputs

| Path | Content |
|------|---------|
| **`data/catalog/maps.yaml`** | Appended or merged: `map_id`, `title`, flags (`local_only`, `ranked_pool`), `content_version` hint. |
| **`data/catalog/locations/<location_id>.yaml`** | One file per canonical **`location_id`** (see §4). |

Each **location** file **must** include:

- `location_id` (string, stable),
- `map_id` (string; 1:1 or N:1 mapping policy per product — default 1:1 `map_id == location_id` unless `maps.yaml` defines bundle),
- `truth_lat`, `truth_lon` (float, WGS84),
- `still_source` — either `bundled_relative: data/downloads/.../mapbox/*.png` or `render_policy: { zoom, width, style }`,
- `country_iso` (from `hf_row_meta.country_iso_alpha2` when present),
- `bbox_wgs84`, `bbox_km_half` when present in source `poi.json`,
- `assist_level` default `standard` or `none` per product.

---

## 4. ID mapping rules

- **`poi_id`** from source (e.g. `poi_0067`) → canonical **`location_id`** (default: same string).
- **`map_id`**: default equals **`location_id`** for solo maps; if product groups POIs under one map, **`maps.yaml`** supplies the many-to-one table and import script validates consistency.

---

## 5. Path normalization (required)

- Read `mapbox.path` from `poi.json`; if absolute, rewrite to **path relative to repository root** using `Path.resolve()` relative to `REPO_ROOT`.
- Fail import with **clear error** if path escapes repo (e.g. `..` abuse).

---

## 6. CLI

```text
python data/scripts/catalog_import_poi.py [--poi-root PATH] [--dry-run] [--force]
```

- **`--dry-run`**: validate + print planned writes; no files touched.
- **`--force`**: overwrite existing catalog entries (use with caution).

---

## 7. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Validation error (missing fields, path escape, duplicate `location_id`) |
| 3 | I/O error |

---

## 8. Related

- [SPEC-catalog-lint.md](SPEC-catalog-lint.md)
- [SPEC-download-geoguessr-poi-imagery.md](SPEC-download-geoguessr-poi-imagery.md)

---

*Spec version: 2026-04-14*
