# Script specification: `assemble_ranked_clue_pack.py`

**Path:** `data/scripts/assemble_ranked_clue_pack.py`  
**Status:** **Phase F — implemented** (`ranked_clue_pack.json` + per-`map_id` slices under `ranked_clues/`).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) §1, §7.

---

## 1. Purpose

Build **client-shippable** JSON for **ranked** SCAN play: **everything except golden ground truth** (`truth_lat` / `truth_lon`).

Includes:

- `map_id`, `location_id`
- `still_bundle_id` / `still_bundled_resource`
- `useful_hints`
- optional `streetview_hint_pack`
- `play_budget_ms`, `ai_marker_phase_enabled`
- **`ai_guesses`** row for post-human marker (product decision: allowed on disk; not golden)

**Explicitly excluded:** `truth_lat`, `truth_lon`; any field that duplicates golden WGS84.

---

## 2. Inputs

- **`manifest.full.json`** OR merged parts from same cache directory as **`assemble_manifest`**.
- **`maps.yaml`** flag `ranked_pool: true` per map.

---

## 3. Outputs

| File | Description |
|------|-------------|
| **`ranked_clues/<map_id>.json`** | Per-map slice |
| **`ranked_clue_pack.json`** | Single envelope: `{ "schema_version": "…", "clues": [ … ] }` for KMP resource |

---

## 4. Consistency with server

- **`RankedClue`** OpenAPI fields must be **subset-compatible** with `POST /api/v1/ranked/rounds/start` response clue (client merge strategy per main pipeline plan §1).

---

## 5. CLI

```text
python data/scripts/assemble_ranked_clue_pack.py [--manifest data/cache/…/manifest.full.json] [--output-dir …]
```

---

## 6. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 12 | Golden leak detected (fail closed) |

---

## 7. Related

- [SPEC-assemble-manifest.md](SPEC-assemble-manifest.md)
- `docs/RANKED-MODE.md` §3

---

*Spec version: 2026-04-14*
