# Script specification: `compile_useful_hint_tiers.py`

**Path:** `data/scripts/compile_useful_hint_tiers.py`  
**Status:** Planned (**Phase C1**).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) §5 Phase C.

---

## 1. Purpose

Transform **`geo_context/*.json`** from **`build_poi_geo_context`** into **`useful_hints`** object matching OpenAPI **`UsefulHintsTiers`**:

- `tier_1` — broad continental / oceanic framing (**no** country name unless product flag `easy_hints: true`).
- `tier_2` — **one** primary signal: nearest named river/lake within R, or coastline distance bucket, or admin-1 physiographic phrasing **using only NE names**.
- `tier_3` — admin-0 common name or ISO expansion.

**Deterministic:** same `context.json` + same policy YAML → same output strings.

---

## 2. Inputs

- **`--geo-context-dir`** — directory of `context.json` files.
- **`--tier-policy tier_policy.yaml`** (optional) — templates, max lengths, `easy_hints`, banned substrings list.

---

## 3. Output

- **`data/cache/<content_version>/useful_hints/<location_id>.json`**:

```json
{
  "location_id": "poi_0067",
  "useful_hints": {
    "tier_1": "…",
    "tier_2": "…",
    "tier_3": "…"
  },
  "facts_used_ref": "geo_context/poi_0067.json"
}
```

---

## 4. Hard bans (must enforce before write)

- No **latitude/longitude literals** in any tier (regex sweep).
- No **street-level** address from `hf_row_meta.address` in tier_1 or tier_2 unless `tier_policy` explicitly allows sanitized country-level extraction.
- **Max length** per tier (defaults: tier_1 ≤ 280, tier_2 ≤ 320, tier_3 ≤ 120 — tune per `docs/GAME-ENGINE.md` §9.1).

---

## 5. Pipeline integration

After write, **always** invoke **`validate_hint_strings`** (subprocess or shared library API) — spec [SPEC-validate-hint-strings.md](SPEC-validate-hint-strings.md).

---

## 6. CLI

```text
python data/scripts/compile_useful_hint_tiers.py [--geo-context-dir …] [--tier-policy …] [--content-version …]
```

---

## 7. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 8 | Validation failed after compile (validator integration) |

---

## 8. Related

- [SPEC-build-poi-geo-context.md](SPEC-build-poi-geo-context.md)
- [SPEC-generate-useful-hints-llm.md](SPEC-generate-useful-hints-llm.md) — optional post-pass.

---

*Spec version: 2026-04-14*
