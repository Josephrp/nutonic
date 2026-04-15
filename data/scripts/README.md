# NU:TONIC — `data/scripts`

Operator notes for the shipped-cache / POI / catalog Python pipeline. Normative behavior: [`docs/scripts/README.md`](../docs/scripts/README.md) and each `docs/scripts/SPEC-*.md`. Ordered implementation: [`plans/2026-04-14-data-scripts-implementation-track.md`](../plans/2026-04-14-data-scripts-implementation-track.md).

## Environment

- **Python:** 3.12 recommended (match `server/` CI); 3.11+ supported for scripts tested locally.
- **Install:** from repo root:

```bash
pip install -r data/scripts/requirements.txt
pip install pytest
```

- **Tests:** from repo root:

```bash
python -m pytest data/scripts/tests -q
```

`data/scripts/tests/conftest.py` adds `data/scripts` to `sys.path` so modules such as `geo_nutonic` import without setting `PYTHONPATH`.

## Layout

| Path | Role |
|------|------|
| `geo_nutonic.py` | Shared haversine / bearing helpers (torch-free) |
| `fetch_geo_baselines.py` | Natural Earth 50m zips + optional GeoNames → `data/geo/` |
| `download_geoguessr_poi_imagery.py` | HF POI ingest + STAC / Mapbox fetch |
| `catalog_import_poi.py` | POI download tree → `data/catalog/maps.yaml` + `locations/*.yaml` |
| `catalog_lint.py` | Validate catalog tree before still / geo-context / manifest phases |
| `validate_hint_strings.py` | Spoiler / length / empty-tier checks on `useful_hints` JSON |
| `render_mapbox_still.py` | Reuse POI Mapbox PNGs or call Static Images API → JPEG + `still_index.json` |
| `assemble_manifest.py` | Merge catalog + `still_index.json` + `useful_hints/*.json` + optional `ai_guesses.json` → `manifest.full.json` + redacted `manifest.public.json` |
| `assemble_ranked_clue_pack.py` | From `manifest.full.json` + `maps.yaml` `ranked_pool` → `ranked_clue_pack.json` (cached assists incl. satellite sidecar; **no** golden coordinates) |
| `generate_ai_guess_fixture.py` | `ai_guesses.json`: decoy offset, CSV table, seeded random, or **TiM** NDJSON / `*.json` dir (`tim_modality_outputs.Coordinates` / `coordinates_wgs84`); optional `--tim-export` overlay |
| `requirements.txt` | Pinned deps for ingest + geo/catalog + still rendering (incl. Pillow) |
| `generate_placeholder_bgm_wav.py` | Regenerate silent **WAV** placeholders under `nutonic/shared/.../composeResources/files/music/` (`docs/SCREEN-MUSIC-SPEC.md` §4) |

## Assembly (manifest + ranked pack)

After `catalog_lint`, `render_mapbox_still` (writes `still_index.json`), and `compile_useful_hint_tiers` (writes `useful_hints/*.json`), run from repo root:

```bash
python data/scripts/assemble_manifest.py \
  --catalog-root data/catalog \
  --still-index data/cache/build_stills/still_index.json \
  --useful-hints-dir "data/cache/<content_version>/useful_hints" \
  --ai-guesses "data/cache/<content_version>/ai_guesses.json" \
  --output-dir "data/cache/<content_version>"
```

Then ranked clue slices (maps with `ranked_pool: true` in `maps.yaml`):

```bash
python data/scripts/assemble_ranked_clue_pack.py \
  --manifest "data/cache/<content_version>/manifest.full.json" \
  --catalog-root data/catalog \
  --output-dir "data/cache/<content_version>"
```

Use `--expose-public-round-truth` only for lab builds when `manifest.public.json` must mirror the full envelope.
