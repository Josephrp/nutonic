# Script specification: `compile_useful_hint_tiers.py`

**Path:** `data/scripts/compile_useful_hint_tiers.py`  
**Status:** **Landed** (**Phase C1** — 2026-04-14).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) §5 Phase C.

---

## 1. Purpose

Transform **`geo_context/*.json`** from **`build_poi_geo_context`** into a **`useful_hints`** object aligned with **`docs/openapi.yaml`** **`UsefulHintsTiers`**:

- **Default product:** **six** monotonic bands (**`tier_1` … `tier_6`**) of increasing usefulness.
- **Hard rule:** **no latitude/longitude literals in any tier**, including **`tier_6`** (validator regex gate).
- **Deterministic:** same `geo_context` row + same **`tier_policy.yaml`** → identical output strings.

**Wire compatibility:** OpenAPI marks **`tier_4`–`tier_6`** optional so older manifests may still ship **three** strings; clients treat absent optional tiers as null.

---

## 2. Inputs

| Input | Description |
|-------|-------------|
| **`--geo-context-dir`** | Directory of per-location `*.json` from **`build_poi_geo_context`** |
| **`--tier-policy`** | YAML with **`tier_count`** (default **6**, max **12**), **`templates.tier_*`**, **`max_length`**, flags — repo default **`data/scripts/tier_policy.default.yaml`** |
| **`--content-version` / `--output-dir`** | Same conventions as **`build_poi_geo_context`** (`data/cache/<v>/useful_hints/`) |

**Facts:** Prefer nested **`hint_compile_facts`** (see [SPEC-build-poi-geo-context.md](SPEC-build-poi-geo-context.md)); legacy geo_context without that block uses degraded fallbacks (still coordinate-free).

---

## 3. Output

**`data/cache/<content_version>/useful_hints/<location_id>.json`:**

```json
{
  "location_id": "poi_0067",
  "useful_hints": {
    "tier_1": "…",
    "tier_2": "…",
    "tier_3": "…",
    "tier_4": "…",
    "tier_5": "…",
    "tier_6": "…"
  },
  "facts_used": { "continent": "…", "admin0_name": "…" },
  "facts_used_ref": "geo_context/poi_0067.json"
}
```

---

## 4. Hard bans (must enforce before write)

- **No coordinate literals** in any tier (delegated to **`validate_hint_strings`**).
- **No street-level** addresses from raw **`hf_row_meta.address`** in early tiers unless a product ADR enables sanitized extraction (default **off**).
- **Max length** per tier from policy (defaults sized for **`docs/GAME-ENGINE.md` §9.1**).

---

## 5. Pipeline integration

After each write, **always** run **`validate_hints`** from **`validate_hint_strings.py`** with the **same** tier policy YAML unless **`--skip-validate`** (debug only). Exit code **8** on validation failure.

---

## 6. CLI

```text
python data/scripts/compile_useful_hint_tiers.py [--geo-context-dir …] [--tier-policy …] [--content-version …] [--output-dir …]
```

---

## 7. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 6 | Missing inputs / bad policy |
| 7 | Compile error |
| 8 | Post-compile validation failed |

---

## 8. Related

- [SPEC-build-poi-geo-context.md](SPEC-build-poi-geo-context.md) — **`hint_compile_facts`**
- [SPEC-validate-hint-strings.md](SPEC-validate-hint-strings.md)
- [SPEC-generate-useful-hints-llm.md](SPEC-generate-useful-hints-llm.md) — optional post-pass

---

*Spec version: 2026-04-14 (rev. 2 — six tiers + coordinate-free strongest band)*
