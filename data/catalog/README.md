# `data/catalog`

Normalized **maps** index (`maps.yaml`) and per-**location** YAML for the shipped-cache pipeline (`catalog_import_poi.py` → `catalog_lint.py` → `render_mapbox_still.py` → `build_poi_geo_context.py` → `compile_useful_hint_tiers.py` → `assemble_manifest.py` → `assemble_ranked_clue_pack.py`). Heavy rasters stay under **`data/downloads/`** (often gitignored); this tree is small YAML suitable for Git or CI checkouts.

## POI sources (`data/downloads/`)

| Directory | Role |
|-----------|------|
| **`geoguessr_poi_12/`** | Smoke set: **`geoguessr_poi_manifest.json`** (Layout A) plus **`poi_*/poi.json`** when present. Fast CI and laptop loops. |
| **`geoguessr_poi_120/`** | Scale set: Layout B — glob **`poi_*/poi.json`** (the folder name is historical; the tree may contain fewer than 120 rows depending on the last download). Same import script; larger `NE_FIXTURE_ROOT` / geo work for **`build_poi_geo_context`**. |

Both layouts are supported by **`catalog_import_poi.py`** (Layout A is preferred when a manifest exists at the POI root).

## Import (full dataset)

From repo root:

```bash
pip install -r data/scripts/requirements.txt

# Smoke (12 points) — default POI root
python data/scripts/catalog_import_poi.py --poi-root data/downloads/geoguessr_poi_12 --force \
  --content-version nutonic.catalog.geoguessr_poi_12.v1 \
  --ranked-split half

# Scale (120-style tree)
python data/scripts/catalog_import_poi.py --poi-root data/downloads/geoguessr_poi_120 --force \
  --content-version nutonic.catalog.geoguessr_poi_120.v1 \
  --ranked-split half

python data/scripts/catalog_lint.py
```

### `--ranked-split half`

After merge, **`maps.yaml`** rows are sorted by **`map_id`**. The first **`n // 2`** maps get **`ranked_pool: false`** (non-ranked pool: no ranked clue slice / no ranked server round for that `map_id`). The remainder get **`ranked_pool: true`** (ranked pool: included in **`assemble_ranked_clue_pack`** output and eligible for **`POST /api/v1/ranked/rounds/start`** when the game server catalog matches).

All maps still appear in **`manifest.full.json`** with golden truth for **local / non-ranked** play when the client merges a shipped full manifest or the server exposes truth.

Overrides in **`--maps-file`** (per-`map_id` YAML) still win for individual flags after the split is applied to the import batch.

## Serialization and the game server

1. Run **`assemble_manifest.py`** (with still index, useful hints, optional Street View dir, optional `ai_guesses.json`) to emit **`manifest.full.json`** / **`manifest.public.json`** under e.g. **`data/cache/<version>/`**.
2. Point the reference server at the full manifest so **`GET /api/v1/maps`** and ranked start use the same rows:

   **`NUTONIC_MANIFEST_FULL_PATH`** = absolute or repo-relative path to **`manifest.full.json`**.

3. Bump **`nutonic/shared/.../files/cache/manifest.full.json`** (and optional **`files/ranked/ranked_clue_pack.json`**) for **embedded** clients so **`content_version`** matches the server and **`mergeShippedRoundTruth`** can overlay redacted wire payloads.

Without **`NUTONIC_MANIFEST_FULL_PATH`**, the server keeps the small **builtin** demo catalog (`demo`, `idempotency-map`).

## Ranked vs non-ranked cache

- **`manifest.full.json`**: every imported location (non-ranked + ranked pool) with **`truth_lat`/`truth_lon`** for local scoring when shipped.
- **`ranked_clue_pack.json`**: only locations whose **`maps.yaml`** row has **`ranked_pool: true`** — no golden coordinates; safe for on-device ranked SCAN assists per **`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`**.
