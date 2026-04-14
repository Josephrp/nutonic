# Script specification: `catalog_lint.py`

**Path:** `data/scripts/catalog_lint.py`  
**Status:** **Implemented** (v1 — checks §2; optional `--json-errors` for one JSON line per violation on stderr).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase A; CI gate in §8.

---

## 1. Purpose

Validate **`data/catalog/`** for structural integrity **before** expensive phases (Mapbox re-render, geo context, manifest assembly). Intended for **local** runs and **CI**.

---

## 2. Checks (normative)

1. **`maps.yaml`**: unique `map_id`; every referenced `location_id` has a **`locations/*.yaml`** file.
2. **Location files**: required keys `location_id`, `map_id`, `truth_lat`, `truth_lon`; lat in `[-90,90]`, lon in `[-180,180]`.
3. **`still_source`**: if `bundled_relative`, path exists under repo root.
4. **No duplicate `location_id`** across files.
5. **Optional:** JSON Schema validation if `catalog.schema.json` is introduced.

---

## 3. CLI

```text
python data/scripts/catalog_lint.py [--catalog-root data/catalog] [--verbose] [--json-errors]
```

---

## 4. Exit codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | One or more violations (print human-readable list + machine-readable JSON line per error to stdout/stderr policy TBD) |

---

## 5. Related — Gradle `:shared:validateCatalog`

**Implemented:** `:shared:validateCatalog` runs **`data/scripts/validate_shipped_compose_resources.py`** against **`composeResources/files/cache/manifest.full.json`**, resolving each **`still_bundled_resource`** under the **`composeResources/`** root (e.g. `files/3.jpg` → `composeResources/files/3.jpg`; path traversal rejected). The root **`quality`** task depends on it.

---

## 6. Related

- [SPEC-catalog-import-poi.md](SPEC-catalog-import-poi.md)

---

*Spec version: 2026-04-14*
