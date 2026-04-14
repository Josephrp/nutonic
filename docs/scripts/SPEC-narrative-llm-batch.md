# Script specification: `narrative_llm_batch.py`

**Path:** `data/scripts/narrative_llm_batch.py`  
**Status:** Planned (**optional Phase G**).  
**Plan:** [`docs/NARRATIVE-AND-PROMPTS.md`](../NARRATIVE-AND-PROMPTS.md) §3–§4, [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase G.

---

## 1. Purpose

Generate **optional** LLM-backed narrative fragments (mission descriptions, debrief lines, INTEL one-liners) from **`prompts/llm/*.md`** templates + **variables** derived from catalog ( **`map_id`**, sector bins, **admin0** from `geo_context` — **not** golden coordinates in ranked mode).

Output merges into **`PromptBundle`** sidecar JSON consumed by Gradle **`generatePromptBundle`** or post-processing step.

---

## 2. Inputs

- `data/catalog/`, `data/cache/<version>/geo_context/*.json`
- `prompts/llm/*.md`
- **`--model-profile tiny`**

---

## 3. Output

- **`data/cache/<version>/narrative/llm_sidecar.json`** keyed by `map_id` + `slot`.

---

## 4. Constraints

- Same **model_pins** logging as [SPEC-generate-useful-hints-llm.md](SPEC-generate-useful-hints-llm.md).
- **No** assist strings in narrative outputs (assists stay in **`useful_hints`** / **`streetview_hint_pack`** per `docs/NARRATIVE-AND-PROMPTS.md` §3).

---

## 5. CLI

```text
python data/scripts/narrative_llm_batch.py [--content-version …] [--backend ollama|openai] [--dry-run]
```

---

## 6. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 14 | Template parse / missing variable |

---

## 7. Related

- Gradle task spec note in [SPEC-catalog-lint.md](SPEC-catalog-lint.md) (companion `generatePromptBundle` for authorial MD only).

---

*Spec version: 2026-04-14*
