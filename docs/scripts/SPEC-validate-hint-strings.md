# Script specification: `validate_hint_strings.py`

**Path:** `data/scripts/validate_hint_strings.py`  
**Status:** **Implemented** (**Phase C2**); **mandatory gate** in CI for hint-producing scripts.  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) §8.

---

## 1. Purpose

Validate **`useful_hints`** JSON (and optionally **Street View caption** strings) for **schema safety**, **spoiler hygiene**, and **length caps** before merge into manifest or ranked clue pack.

---

## 2. Inputs

| Mode | Input |
|------|-------|
| **File** | `--input path/to/useful_hints.json` |
| **stdin** | JSON object when `--stdin` |
| **Directory** | `--scan-dir` — validate every `*.json` under tree matching `useful_hints` schema |

Optional **`facts_used`** JSON for audit: ensures referenced feature names appear in tiers (anti-hallucination for LLM-generated hints).

---

## 3. Rules (normative)

1. **Coordinate regex:** reject patterns resembling decimal degrees (e.g. `-?\d{1,3}\.\d{4,}` paired with comma-separated second coordinate). Applies to **every** shipped tier (**`tier_1`–`tier_N`**, including the strongest). Tune false positives via policy YAML.
2. **Length:** per-tier max from policy (`max_length.tier_*` or legacy `max_len_tier_*` for the first three bands).
3. **`tier_count`:** policy key (default **6**, max **12**). When `assist_level != none`, **`tier_1` … `tier_{tier_count}`** must all be **present as keys** and **non-empty** strings (after strip).
4. **Optional admin0 check:** when **`enforce_max_tier_contains_admin0`** is true, **`tier_{tier_count}`** must contain **`facts_used.admin0_name`** (case-insensitive substring).
5. **Profanity / banned tokens:** configurable list.

---

## 4. Output

- **stdout:** `OK` or pretty-printed violation list.
- **Machine-readable:** optional `--json-out violations.json` for CI artifacts (JSON array of `{code,message,path}`).

---

## 5. CLI

```text
python data/scripts/validate_hint_strings.py --input useful_hints/poi_0067.json [--policy hint_validate_policy.yaml]
python data/scripts/validate_hint_strings.py --scan-dir data/cache/v1/useful_hints/
```

---

## 6. Exit codes

| Code | Meaning |
|------|---------|
| 0 | All validations passed |
| 1 | One or more violations |

---

## 7. Consumers

- **`compile_useful_hint_tiers`** — always run after compile.
- **`generate_useful_hints_llm`** — must pass before accepting LLM output.
- **`batch_streetview_hints`** — validate each caption line before pack append.
- **`assemble_manifest`** — reject merge if any location fails.

---

## 8. Related

- `docs/GAME-ENGINE.md` §9.1 — product rules for hints.

---

*Spec version: 2026-04-14 (rev. 2 — `tier_count` / six tiers / strongest-tier coordinate ban)*

---

## 9. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-14 | Initial |
| 0.2 | 2026-04-14 | **`tier_count`** (default 6); **`enforce_max_tier_contains_admin0`**; coordinate checks apply to **all** tiers |
