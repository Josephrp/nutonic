# Script specification: `sync_server_catalog.py`

**Path:** `data/scripts/sync_server_catalog.py`  
**Status:** **Phase F — implemented** (`codegen` default; `--write` updates `server/src/nutonic_server/catalog_generated.py`). **IMP-081:** registry merge on write. **IMP-120:** `--mode sql` emits `server/docs/catalog_seed.sql`.  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase F.

---

## 1. Purpose

Translate **`manifest.full.json`** (or catalog YAML) into artifacts the **reference Python server** can load:

- **Short term:** emit **`server/src/nutonic_server/catalog_generated.py`** (or patch file) defining `PUBLISHED_MAPS`, `MANIFEST_LOCATIONS`, `MANIFEST_AI_GUESSES` — **or** print unified diff for manual review.
- **Bundle registry (IMP-081):** On **`--write`** (codegen), merge manifest `still_bundle_id` keys into **`server/src/nutonic_server/bundles/registry.json`**: preserve existing entries; add `{id}.jpg` when that file exists under `bundles/`; fail if a manifest id cannot be resolved. Use **`--no-update-bundle-registry`** to skip mutating the JSON (validation still runs).
- **SQL seed (IMP-120 near-term):** **`--mode sql`** emits SQLite-oriented **`CREATE TABLE IF NOT EXISTS`** + **`DELETE`/`INSERT`** for `nutonic_catalog_*` tables so operators can rehearse DB-backed catalog loads before full Hub sync.

---

## 2. Inputs

- **`--manifest`** path to `manifest.full.json`
- **`--mode codegen`** (default) or **`sql`** or **`noop`**
- **`--sql-output`** path for SQL when `--mode sql` (default `server/docs/catalog_seed.sql`)

---

## 3. Safety

- **Never** write secrets.
- **Dry-run default in CI:** require `--write` to modify files under `server/`.
- Generated file header: **AUTO-GENERATED** + content hash + git commit suggestion.
- **Registry merge** never deletes existing `bundles` keys that are absent from the manifest (supports extra dev aliases).

---

## 4. CLI

```text
python data/scripts/sync_server_catalog.py --manifest <path> [--mode codegen|sql|noop] [--write]
python data/scripts/sync_server_catalog.py --manifest <path> --mode sql [--write] [--sql-output server/docs/catalog_seed.sql]
python data/scripts/sync_server_catalog.py --manifest <path> --write --no-update-bundle-registry
```

---

## 5. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (or dry-run diff printed, or SQL printed) |
| 13 | Manifest incompatible with server schema |
| 14 | Bundle registry cannot satisfy manifest `still_bundle_id` (missing file or unknown id) (**IMP-081**) |

---

## 6. HMAC / inference (related)

Server **`InferenceClient`** (IMP-092) may send **`X-Nutonic-Timestamp`**, **`X-Nutonic-Nonce`**, **`X-Nutonic-Signature`** on outbound worker **`GET`** requests when **`NUTONIC_INFERENCE_HMAC_SECRET`** is set; bundle sync is orthogonal but often run in the same release pipeline.

---

## 7. Related

- [SPEC-assemble-manifest.md](SPEC-assemble-manifest.md)
- `server/src/nutonic_server/catalog.py`
- `server/docs/catalog_seed.sql` (generated SQL, optional commit)

---

*Spec version: 2026-04-15*
