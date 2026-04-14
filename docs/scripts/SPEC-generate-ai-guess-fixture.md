# Script specification: `generate_ai_guess_fixture.py`

**Path:** `data/scripts/generate_ai_guess_fixture.py`  
**Status:** Planned (**Phase E** / **IMP-082**).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase E.

---

## 1. Purpose

Emit **`AiGuessRow`** entries (`map_id`, `location_id`, `ai_lat`, `ai_lon`) for manifest **`ai_guesses[]`** until **S6** Parquet / TiM exports exist.

**Trust:** Non-ranked display only; must be **deterministic** or **seeded** for QA reproducibility.

**Normative production path (`docs/GAME-ENGINE.md` §9.4, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`):** When TerraMind TiM runs exist for `(map_id, location_id)`, emit **`ai_lat` / `ai_lon` from `tim_modality_outputs.Coordinates`** (full WGS84). Decoy / random / fixed-table modes are **interim** until TiM exports are available.

---

## 2. Modes (normative)

| Mode | CLI | Behavior |
|------|-----|------------|
| **`decoy_offset`** | `--mode decoy_offset --delta-km 50 --bearing-deg 127` | Place AI guess at offset from truth along geodesic (uses [SPEC-geo-nutonic.md](SPEC-geo-nutonic.md) math). |
| **`fixed_table`** | `--mode fixed_table --csv ai_guesses.csv`** | Read explicit coordinates per `location_id`. |
| **`random_seeded`** | `--mode random_seeded --seed 42 --min-km 200 --max-km 800`** | Global guess excluding buffer around truth (for stress only). |
| **`terramind_tim_jsonl`** | `--mode terramind_tim_jsonl --tim-export path.jsonl` | NDJSON: each object has `location_id`, `map_id`, and `tim_modality_outputs.Coordinates` as `{ "lat", "lon" }` (or `latitude` / `longitude`) **or** top-level `ai_lat` / `ai_lon`. |
| **`terramind_tim_dir`** | `--mode terramind_tim_dir --tim-dir exports/tim_runs/` | Directory of per-location `*.json` using the same object schema as one JSONL line. |

**Precedence:** `--prefer-tim` (default **true**) chooses TiM export over CSV/decoy when both exist; **false** → conflicting rows are a **hard error**.

**TiM validation:** reject missing `Coordinates` when catalog requires TiM-backed AI marker; optional `--max-error-vs-truth-km` catches swapped lat/lon or near-truth collapse.

---

## 3. Output

- **`data/cache/<version>/ai_guesses.json`** — array of OpenAPI-shaped objects.

---

## 4. Validation

- `ai_lat` ∈ `[-90,90]`, `ai_lon` ∈ `[-180,180]`.
- Optional: **minimum haversine** distance from truth ≥ product floor (e.g. 5 km) so AI marker is not visually identical to golden.

---

## 5. CLI

```text
python data/scripts/generate_ai_guess_fixture.py [--catalog-root …] [--mode …] [--content-version …]
```

---

## 6. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 10 | Invalid CSV / missing rows for catalog locations |
| 12 | TiM export schema mismatch / missing `Coordinates` where required |
| 13 | Conflicting coordinates for same `location_id` when `--prefer-tim=false` |

---

## 7. Related

- [SPEC-assemble-manifest.md](SPEC-assemble-manifest.md)
- `docs/openapi.yaml` — `AiGuessRow`
- `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` — **`Coordinates` → `ai_lat` / `ai_lon`**
- `plans/2026-04-07-complete-implementation-architecture.md` — **S6** Parquet / HF Jobs follow-up

---

*Spec version: 2026-04-14 (2026-04-14b: TerraMind TiM coordinate modes)*
