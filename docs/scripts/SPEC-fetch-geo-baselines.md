# Script specification: `fetch_geo_baselines.py`

**Path:** `data/scripts/fetch_geo_baselines.py`  
**Status:** Planned.  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase A.

---

## 1. Purpose

Download and unpack **version-pinned** **Natural Earth** vector datasets (and optionally **GeoNames** `countryInfo.txt`) into **`data/geo/`** so **`build_poi_geo_context`** can run **fully offline** (no runtime calls to Natural Earth servers).

---

## 2. Outputs (directory layout)

Under **`data/geo/`** (exact subpaths are implementation-defined but must be **documented in script `--help`** and committed **`data/geo/README.md`** after first fetch):

| Artifact | Natural Earth scale | Role |
|----------|---------------------|------|
| Admin-0 polygons | 1:50m | Country / continent labels, ISO codes |
| Admin-1 polygons | 1:50m | Regional tier_2 strings |
| Rivers | 1:50m | Nearest named linear water |
| Lakes | 1:50m | Nearest named standing water |
| Coastline | 1:50m | Distance-to-coast km |

**Optional:** `data/geo/geonames/countryInfo.txt` for display names / alt spellings.

---

## 3. CLI

```text
python data/scripts/fetch_geo_baselines.py [--output-dir data/geo] [--ne-version 5.1.2] [--skip-geonames]
```

- **Idempotent:** re-run skips files that match expected SHA256 recorded in **`data/geo/MANIFEST.json`** (script-generated manifest of downloaded zips).

---

## 4. Licensing

- **Natural Earth:** Public Domain — cite in `data/geo/README.md`.
- **GeoNames:** Creative Commons Attribution — document attribution file if enabled.

---

## 5. CI / developer workflow

- Developers run once locally; CI may cache `data/geo/` between jobs **or** run fetch step on cold runners (slower).
- **Large files:** `data/geo/` should remain **gitignored** unless product explicitly vendors a minimal subset; if vendored, document size in root README.

---

## 6. Related

- [SPEC-build-poi-geo-context.md](SPEC-build-poi-geo-context.md) — consumer.

---

*Spec version: 2026-04-14*
