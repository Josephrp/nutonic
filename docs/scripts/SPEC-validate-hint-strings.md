# Script specification: `validate_hint_strings.py`

**Path:** `data/scripts/validate_hint_strings.py`  
**Status:** Planned (**Phase C2**); **mandatory gate** in CI.  
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

1. **Coordinate regex:** reject patterns resembling decimal degrees (e.g. `-?\d{1,3}\.\d{4,}` paired with comma-separated second coordinate). Tune false positives (years, scores) via allowlist in policy YAML.
2. **Length:** per-tier max from policy or CLI flags.
3. **Empty tiers:** if `assist_level != none`, all three tiers must be non-empty strings (after strip).
4. **Monotonicity heuristic:** tier_3 must not be **geographically broader** than tier_2 (optional NLP-free check: e.g. tier_3 admin-0 name must appear in `facts_used.admin0_name` or alias table).
5. **Profanity / banned tokens:** configurable list.

---

## 4. Output

- **stdout:** `OK` or pretty-printed violation list.
- **Machine-readable:** optional `--json-out violations.json` for CI artifacts.

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

*Spec version: 2026-04-14*
