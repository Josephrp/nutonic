# Script specification: `sync_server_catalog.py`

**Path:** `data/scripts/sync_server_catalog.py`  
**Status:** Planned (**Phase F** bridge to **IMP-120**).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase F.

---

## 1. Purpose

Translate **`manifest.full.json`** (or catalog YAML) into artifacts the **reference Python server** can load:

- **Short term:** emit **`server/src/nutonic_server/catalog_generated.py`** (or patch file) defining `PUBLISHED_MAPS`, `MANIFEST_LOCATIONS`, `MANIFEST_AI_GUESSES` — **or** print unified diff for manual review.
- **Long term:** upsert rows into DB / Parquet index (**IMP-120**); this spec’s CLI remains **`--mode codegen|sql|noop`** with `codegen` default until DB lands.

---

## 2. Inputs

- **`--manifest`** path to `manifest.full.json`
- **`--mode codegen`** (default)

---

## 3. Safety

- **Never** write secrets.
- **Dry-run default in CI:** require `--write` to modify files under `server/`.
- Generated file header: **AUTO-GENERATED** + content hash + git commit suggestion.

---

## 4. CLI

```text
python data/scripts/sync_server_catalog.py --manifest data/cache/v1/manifest.full.json [--mode codegen] [--write]
```

---

## 5. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (or dry-run diff printed) |
| 13 | Manifest incompatible with server schema |

---

## 6. Related

- [SPEC-assemble-manifest.md](SPEC-assemble-manifest.md)
- `server/src/nutonic_server/catalog.py`

---

*Spec version: 2026-04-14*
