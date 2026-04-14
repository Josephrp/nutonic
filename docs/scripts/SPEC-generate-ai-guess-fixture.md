# Script specification: `generate_ai_guess_fixture.py`

**Path:** `data/scripts/generate_ai_guess_fixture.py`  
**Status:** **Phase E — implemented** (torch-free; consumes **TiM JSON/NDJSON exports** with `tim_modality_outputs.Coordinates` per `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`).  
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
| **`terramind_tim_jsonl`** | `--mode terramind_tim_jsonl --tim-export path.jsonl` | NDJSON: each line **must** include `location_id`, `map_id`, and coordinates via top-level `ai_lat` / `ai_lon` **or** `tim_modality_outputs.Coordinates`. Prefer PRO-shaped **`coordinates_wgs84`**: `{ "kind": "coordinates_wgs84", "latitude": number, "longitude": number, "confidence"?: number }` (see **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`** table — `Coordinates` / `coordinates_wgs84`). Shorthand `{ "lat", "lon" }` inside `Coordinates` is accepted. |
| **`terramind_tim_dir`** | `--mode terramind_tim_dir --tim-dir exports/tim_runs/` | Directory of per-location `*.json`; each file **must** include `map_id` + `location_id` + the same coordinate extraction rules as JSONL. |

**Precedence:** With **`--tim-export`** and/or **`--tim-dir`** alongside **`decoy_offset`**, **`fixed_table`**, or **`random_seeded`**, **`--prefer-tim`** (default **true**) replaces base rows where TiM has `(map_id, location_id)`; **`--no-prefer-tim`** requires base and TiM agree within **`--tim-match-tol-km`** (default **0.05** km) or exit **13**.

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
python data/scripts/generate_ai_guess_fixture.py --mode decoy_offset --delta-km 50 --bearing-deg 127 \
  [--catalog-root data/catalog] [--output data/cache/<v>/ai_guesses.json] [--content-version <v>]

python data/scripts/generate_ai_guess_fixture.py --mode fixed_table --csv path.csv [--output …]

python data/scripts/generate_ai_guess_fixture.py --mode random_seeded --seed 42 --min-km 200 --max-km 800 \
  [--min-random-sep-km 10] [--output …]

python data/scripts/generate_ai_guess_fixture.py --mode terramind_tim_jsonl --tim-export runs.jsonl [--output …]

python data/scripts/generate_ai_guess_fixture.py --mode terramind_tim_dir --tim-dir exports/tim_runs/ [--output …]

# Optional TiM overlay on decoy/fixed/random:
python data/scripts/generate_ai_guess_fixture.py --mode decoy_offset --delta-km 100 --bearing-deg 0 \
  --tim-export tim.jsonl [--prefer-tim | --no-prefer-tim] [--tim-match-tol-km 0.05]

# Optional separation / sanity:
[--min-ai-vs-truth-km 5] [--max-ai-vs-truth-km 12000]
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
- **Local TerraTorch TiM → JSONL:** `inference/terramind_tim_local/` (`python -m nutonic_terramind_tim_local run …`) then **`ingest`** (wraps this script) or direct **`--mode terramind_tim_jsonl`** on the emitted `tim_export.jsonl`.

---

*Spec version: 2026-04-14 (2026-04-14c: implemented script + `coordinates_wgs84` + overlay precedence)*
