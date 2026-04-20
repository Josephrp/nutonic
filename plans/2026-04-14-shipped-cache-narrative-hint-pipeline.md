# NU:TONIC — Shipped cache, narrative, and hint production pipeline (multiplatform Kotlin)

**Date:** 2026-04-14  
**Status:** Implementation plan (normative for engineering sequencing; product sign-off on catalog size vs app binary caps).  
**Authority:** Aligns with `rules/00-product-intent.md`, `rules/13-client-cache-and-data-plane.md`, `docs/GAME-ENGINE.md` §9–§10, `docs/NARRATIVE-AND-PROMPTS.md`, `docs/RANKED-MODE.md` §3–§4, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`, existing inference plans (`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`, `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`, **`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`** for **IMP-110** Street View sampling WBS), and backlog items **IMP-081**, **IMP-082**, **IMP-120** / architecture **S3**, **S6**.

**Intent (shipped builds):** Store builds ship **as much precomputed SCAN content as practical**: Mapbox (or equivalent) **reference stills**, **three-tier coordinate-scoped useful hints**, **optional Street View description packs** (batch LFM-VL), **precomputed AI marker coordinates**, **authorial + LLM narrative** keyed by `mission_id` / `map_id` / slots, and **catalog metadata**—so **gameplay never depends on live inference** on the hot path. **Ranked** ships the **same clue assets and assists** on-device **except** the **golden answer** (WGS84 truth): truth remains **server-held** until `submit`; hints that materially narrow search space remain **behind ranked forfeit** UX per `docs/RANKED-MODE.md`.

---

## 1. Trust and packaging model (local vs ranked)

| Mode | What ships **inside the app** | What may ship from **reference server / CDN** | Must **not** ship to disk pre-submit (ranked) |
|------|-------------------------------|-----------------------------------------------|-----------------------------------------------|
| **Non-ranked (“local map”)** | Full `ManifestRoundLocation`: `truth_lat` / `truth_lon`, still, `useful_hints`, optional `streetview_hint_pack`, `ai_guesses` row, narrative blocks | Optional refresh of manifest / stills between releases | N/A |
| **Ranked** | **Ranked clue pack** per published `map_id`: same **still**, **hints**, **Street View pack**, **narrative**, **`location_id`**, **`ai_lat`/`ai_lon`** (for post-human marker), `play_budget_ms` (cosmetic), flags — **all** keyed so the client can render SCAN without network | `POST .../ranked/rounds/start` returns **`round_id`**, **`round_ticket`**, **`expires_in`**, and a **thin clue overlay** if server rotates variants (optional) | **Golden coordinates** (`truth_lat` / `truth_lon`) and any **raw pano id** that trivially resolves to golden if product policy forbids it |

**Rule:** The **Kotlin client** loads ranked **SCAN** UI from **on-disk ranked clue slice** merged with **start** response metadata only. Server **start** already returns `RankedClue` without truth (`docs/openapi.yaml`); production should treat **start** as **session binding** (ticket, TTL) while **heavy bytes** load from **bundled** `still_bundle_id` / compose resources. If **start** ever omits duplicated hint fields, client uses **bundled ranked pack** by `(map_id, location_id)` from JWT/catalog binding.

**Alignment with `rules/13`:** Ranked **in-flight** rounds do not persist server golden truth; **post-submit** verified payload may be cached for UX. Coordinate hints and SV prose are **not** “golden truth”; they are **assists** — still subject to **forfeit** policy when ranked.

---

## 2. Content taxonomy (what gets produced)

Everything below is **versioned** with at least **`content_version`** (manifest) and/or **`ruleset_version`** (round row) and a **build id** baked into QA artifacts.

| Layer | Description | Generator | Primary consumer |
|-------|-------------|-----------|------------------|
| **L0 — Catalog** | `map_id`, `title`, `engine_version`, optional `mission_id` links | Curated YAML/JSON + lint | SCAN hub, manifest `maps[]` |
| **L1 — Reference still** | Downsampled static map image (PNG/JPEG/WebP) | Script: Mapbox Static Images (keys in CI secret), width/height policy per `docs/GAME-ENGINE.md` §9 | `still_bundle_id` + `GET /api/v1/bundles/...` and/or `still_bundled_resource` under `nutonic/shared/src/.../composeResources/` |
| **L2 — Coordinate useful hints** | `useful_hints.tier_1..N` (default **N=6**): monotonic bands from continental → marine/hydro → subnational → country-scale synthesis; **no lat/lon literals in any tier (including strongest)**; length caps | **`build_poi_geo_context`** → **`hint_compile_facts`** → **`compile_useful_hint_tiers`** (+ optional LLM polish) + **`validate_hint_strings`** | `ManifestRoundLocation` / `RankedClue` (OpenAPI optional **`tier_4`–`tier_6`**) |
| **L3 — Street View hint pack** | Ordered text entries + viewpoint metadata; **decoy viewpoints** per `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` | **Batch job**: `streetview_pano_service` → images → `lfm_vl_hint_service` → JSON | Optional assist panel; **ranked forfeit** if revealed before submit |
| **L4 — Narrative (authorial)** | `prompts/` Markdown + YAML front matter: slots (`mission_select`, `map_select`, `map_overlay`, …) per `docs/NARRATIVE-AND-PROMPTS.md` §7 | Authors + CI lint | Gradle-serialized **PromptBundle** in compose resources |
| **L5 — Narrative / chrome (generated)** | Mission one-liners, debrief templates, INTEL flavor | **Composable prompts**: `prompts/llm/*.md` with `{{vars}}`; HF Job or local `openai`-compatible runner in CI | Same bundle or sidecar JSON merged by `content_version` |
| **L6 — AI guess row** | `ai_lat` / `ai_lon` per `(map_id, location_id)` | TiM/Dataset job (future) or **scripted decoy** for early ships | `ai_guesses[]` / `AiGuessStore` |
| **L7 — Golden truth (non-ranked only)** | `truth_lat` / `truth_lon` | Curated from `data/` POI pools / exports | `locations[]` in **private** manifest slice or **embedded** local pack only |

**Ranked packaging:** L1–L6 for each ranked-eligible `map_id` ship in the **app ranked pack**; L7 **excluded** from client disk for ranked. Server `MANIFEST_LOCATIONS` (or DB) retains full rows for **`ranked_round_start`** to read truth internally (`server/src/nutonic_server/catalog.py` pattern today).

---

## 3. Target directory layout (repo)

Create and maintain **one canonical tree** (paths can be adjusted in one ADR; **boundaries** are normative):

```text
prompts/                              # repo root (per docs/NARRATIVE-AND-PROMPTS.md §5)
  index.md
  missions/<mission_id>.md
  maps/<map_id>.md
  shared/strings.md
  llm/
    useful_hints_system.md            # composable: variables = gazetteer facts only
    mission_description_system.md
    streetview_caption_user.md         # per-viewpoint, schema-bounded JSON
    debrief_user.md
  vlm/…                                # PRO-adjacent only; not SCAN hot path

data/
  catalog/                             # NEW: curated source of truth for maps/locations
    maps.yaml                          # list of published map_id + title + flags (local_only, ranked)
    locations/                         # one file per location_id OR split by map
      <map_id>.yaml                    # truth, bundle refs, assist policy knobs
  cache/                               # NEW: machine-generated, gitignored in dev; CI commits pins
    <content_version>/
      manifest.full.json               # full internal manifest (includes truth + ai_guesses)
      manifest.public.json             # redacted for world-readable GET (current server behavior)
      ranked_clues/<map_id>.json       # clue-only slice for app ranked pack
      reports/validate.json            # validator output

nutonic/shared/src/commonMain/composeResources/files/
  maps/                                # shipped stills + optional sidecars
    <bundle_id>.jpg
  narrative/                           # NEW: PromptBundle.json (+ optional locale)
    prompt_bundle.json
  ranked/                              # NEW: optional per-map clue JSON or single envelope
    ranked_clue_pack.json
```

**Existing assets:** Continue to use `data/downloads/...` and `data/scripts/` for POI ingestion (`download_geoguessr_poi_imagery.py`, etc.); **new** scripts read **normalized** rows from `data/catalog/` rather than ad hoc globbing.

**Per-script specifications:** [`docs/scripts/README.md`](../docs/scripts/README.md) (`SPEC-*.md` for each script / module).  
**Implementation plans:** [`plans/2026-04-14-data-scripts-implementation-track.md`](2026-04-14-data-scripts-implementation-track.md), [`plans/2026-04-14-data-scripts-testing-and-ci.md`](2026-04-14-data-scripts-testing-and-ci.md).

**Authoritative local datasets (v1 loop):**

| Path | Role |
|------|------|
| **`data/downloads/geoguessr_poi_12/`** | **Smoke / dev default:** `geoguessr_poi_manifest.json` lists **12** points (`poi_0000` …) with lat/lon, `stac_item_id`, Mapbox PNG paths — fastest iteration for pipeline wiring, validators, and “smallest model” LFM-VL smoke. |
| **`data/downloads/geoguessr_poi_120/`** | **Scale rehearsal:** per-POI **`poi.json`** adds **`bbox_wgs84`**, **`bbox_km_half`**, **`hf_row_meta`** (e.g. `country_iso_alpha2`, free-text `address`), **`selection`** metadata — use for **proximity feature** tuning and CI that must not melt laptops. |
| **`data/scripts/download_geoguessr_poi_imagery.py`** | **Already** documents **`refs/terramind-geogen-main`** context (TerraMesh metadata / **lon,lat** haversine order). New scripts should **import or copy** its **`haversine_km`** semantics rather than re-deriving Earth radius. |

---

## 4. OpenAPI, server, and Kotlin model extensions

**Landed (2026-04-14):** `docs/openapi.yaml`, Kotlin **`ManifestRoundLocation`** / **`RankedClue`**, FastAPI **`ManifestLocationOut`** / **`RankedClueOut`**, and **`data/scripts/assemble_manifest.py`** all carry optional **`streetview_hint_pack`** (+ optional **`streetview_assist_narrative`**) with caption validation. **`POST /api/v1/ranked/rounds/start`** echoes catalog **`streetview_*`** fields on **`RankedClueOut`** (no golden coordinates).

**Remaining / polish:**

1. **Shipped compose validation (landed):** **`:shared:validateCatalog`** runs **`data/scripts/validate_shipped_compose_resources.py`** against embedded **`manifest.full.json`** and resolves **`still_bundled_resource`** paths under **`nutonic/shared/.../composeResources/`** (see [`docs/scripts/SPEC-catalog-lint.md`](../docs/scripts/SPEC-catalog-lint.md) §5). **`git`** tracks the referenced **`files/maps/*.jpg`** and the embedded manifest so **normal clones** pass validation without a generate step. **`data/scripts/sync_server_catalog.py`** (**`--write`**) emits **`server/src/nutonic_server/catalog_generated.py`** from that manifest for static server hydration — see [`docs/scripts/SPEC-sync-server-catalog.md`](../docs/scripts/SPEC-sync-server-catalog.md); matching **JPEGs** under **`server/src/nutonic_server/bundles/`** are also **tracked** for **`GET /api/v1/bundles/{id}`**. **Still ahead:** **`sync_server_catalog --mode sql`** (**IMP-120**) and **workflow** docs for re-running **`render_mapbox_still`** / **`assemble_manifest`** / **`sync_server_catalog --write`** when **`data/catalog/`** or still policy changes (**IMP-081** maintenance, not first-time asset creation). **Street View batch (Phase D)** consumes **`streetview_pano_service`**; core **§13.1–§13.3** sampling is **landed** in **`inference/streetview_pano_service`** per **[`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](2026-04-18-streetview-google-perpendicular-sampling-full-scope.md) v0.3** — track remaining **§13.4**/**§14** polish under **IMP-110**, not road-bearing research.
2. **Public** manifest redaction unchanged (**`locations`** / **`ai_guesses`** empty by default); **shipped** **`composeResources/files/cache/manifest.full.json`** + **`mergeShippedRoundTruth`** and **`files/ranked/ranked_clue_pack.json`** + client **`mergeRankedClueWithPack`** keep SCAN/ranked assists coherent when the wire slice is thin.
3. **`NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH`** remains for **lab** and **contract tests** only.

---

## 5. Script and job inventory (phased)

Phases are **ordered**; later phases depend on stable IDs from earlier ones.

### 5.0 Local-first execution (developer machine)

**Goal:** Every script in §5 runs **locally** first (laptop or workstation), with **no HF Jobs requirement** until the pipeline is green on **`geoguessr_poi_12`**.

| Convention | Detail |
|--------------|--------|
| **Default POI root** | `--poi-root data/downloads/geoguessr_poi_12` for wiring, schema validation, and cheapest LFM-VL runs (**12** rows). |
| **Scale pass** | `--poi-root data/downloads/geoguessr_poi_120` for full **useful_hints** + still + SV batch overnight / weekend. |
| **Secrets** | Mapbox / Google / HF tokens only via **`.env`** at repo root (already supported by `download_geoguessr_poi_imagery.py`); never commit. |
| **Paths in `poi.json`** | May contain machine-specific absolute paths under `mapbox.path` — **`catalog_import_poi.py`** must rewrite to **repo-relative** paths (e.g. `data/downloads/geoguessr_poi_120/poi_0067/mapbox/...`) so artifacts are portable. |
| **Outputs** | Write under **`data/cache/<content_version>/`** (gitignored locally); optional **`--commit-cache`** flag for CI-only commits of pinned JSON. |

**Smallest-model policy (Phase D + optional C3):**

| Stage | Model / stack | Notes |
|-------|----------------|-------|
| **Local smoke** | **Smallest** documented LFM-VL (e.g. **`LiquidAI/LFM2.5-VL-450M`** per `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`) or smaller successor in ML ADR; **batch size 1**; **short max_new_tokens** | Enough to validate JSON contract + image+text path on **12** POIs. |
| **CPU-only dev** | Skip LFM entirely: **`--skip-streetview-hints`**; useful hints come from **§5 Phase C** only | Keeps inner loop fast. |
| **Scale-up** | Larger checkpoints + HF ZeroGPU / dedicated GPU per master LFM plan | After local contract is frozen. |

---

### `refs/` usage (scripts must not import training stacks)

| `refs/` path | Role for **NU:TONIC `data/scripts/`** | Discipline |
|---------------|----------------------------------------|------------|
| **`refs/terramind-geogen-main/src/geo_utils.py`** | **Reference** for **haversine in km** and **(lon, lat)** point order when comparing distances, scoring parity notes, or **unit tests** that reimplement haversine in **pure Python / NumPy** | **Do not** `import torch` or add TerraTorch to `data/scripts/` — keep the data plane **lightweight**; mirror math only. **VLMs / TerraMind** run in **`inference/*`**, **`tools/`**, or Jobs using **vLLM** and/or **`transformers`+PyTorch** and/or **TerraTorch** per `inference/README.md`. |
| **`refs/terramind-geogen-main/scripts/plot_error_heatmap.py`** | **Optional QA:** after playtests, bin **hint difficulty** or **distance error** by lat/lon (same CSV patterns as eval pipelines) | Offline analytics only. |
| **`data/scripts/download_geoguessr_poi_imagery.py`** | **Canonical** patterns: HF `datasets` load, **STAC** + Mapbox fetch, **`haversine_km`** (already matches geogen **lon,lat** convention in file docstring) | New ingest scripts **load as module** or share a small **`data/scripts/geo_nutonic.py`** extracted from duplicated logic. |
| **`refs/satellite-vlm/README.md`** (and related JSON eval shapes) | **Optional** strict JSON / schema habits for **LFM-VL caption** outputs (Street View pack entries) | Not required for **useful_hints** tiers. |
| **`refs/VLMExample/`** | **PRO tab** on-device path only (`rules/06`) | **Out of scope** for SCAN useful-hints generation. |

---

### Phase A — Catalog ingestion and normalization

| Script / task | Input | Output | Notes |
|---------------|-------|--------|-------|
| **`data/scripts/catalog_import_poi.py`** (new) | **`--poi-root`** default `data/downloads/geoguessr_poi_12`; optional `.../geoguessr_poi_120`. Accepts **`geoguessr_poi_manifest.json`** (12-point layout) **or** glob `poi_*/poi.json` (120 layout). | `data/catalog/locations/<map_id>.yaml` (or per `location_id`) with stable **`map_id`** / **`location_id`**, WGS84 truth, **`bbox_wgs84`** when present, **`country_iso`** from `hf_row_meta`, normalized still path | **Dedupes** on `poi_id`; maps `poi_id` → canonical `location_id`; links optional `mission_id`. |
| **`data/scripts/catalog_lint.py`** (new) | `data/catalog/` | exit non-zero on duplicate ids, missing truth, broken still path | Called from CI |
| **`data/scripts/fetch_geo_baselines.py`** (new, one-time / rare) | None | **`data/geo/natural_earth/`** (1:50m admin-0, admin-1, rivers, lakes, coastline — versions pinned in script) | **Offline** proximity queries for Phase C; license **Public Domain** (Natural Earth). Optional: GeoNames `countryInfo.txt` for alt names. |
| **Gradle: `:shared:validateCatalog`** (new) | packaged subset | fails build if referenced `still_bundled_resource` missing | Ties KMP to `data/catalog` |

### Phase B — Reference still materialization (IMP-081)

| Script / task | Input | Output | Notes |
|---------------|-------|--------|-------|
| **`data/scripts/render_mapbox_still.py`** (new) | `locations/*.yaml` + Mapbox token (CI secret) **or** **reuse** existing PNG under `poi_*/mapbox/` (copy + downscale to product width) | `nutonic/.../composeResources/files/maps/<bundle_id>.jpg` + bytes for server `bundles/` | Prefer **reuse** when `poi.json` already has Mapbox still; re-render only when zoom/size policy changes. Store **`still_sha256`** in catalog. |
| **Server bundle register** | JPEG bytes | `resolve_bundle_bytes` map or object storage manifest | Already pattern in `server/src/nutonic_server/bundles.py` — extend registry from generated index |

### Phase C — Useful hints: **programmatic proximity + templates** (primary); LLM optional polish (secondary)

**Design intent:** **`useful_hints`** are **hydrated from geographic structure near the POI**, not from a single LLM call that “knows” the answer. LLM (**smallest** checkpoint, **Phase C3**) may **rephrase** fact JSON only when enabled; **validator** is always mandatory.

#### C0 — Context assembly (per POI)

| Step | Source fields | Output (intermediate JSON) |
|------|---------------|----------------------------|
| Load POI | `latitude`, `longitude` from `poi.json` / manifest; optional **`bbox_wgs84`**, **`bbox_km_half`** (120-set) | `context.json` candidate |
| Admin / continent | **Point-in-polygon** vs **Natural Earth** admin-0 / admin-1 (from **`data/geo/`**); fallback: **`hf_row_meta.country_iso_alpha2`** for admin-0 label | `admin0_name`, `admin1_name`, `continent` |
| Linear / area features **near** POI | Within radius **`R = min(R_max, k * bbox_km_half)`** (e.g. `k=3`, `R_max=200` km): nearest **river** line, **lake** polygon, **coastline** distance (km) from NE layers | `nearest_river`, `nearest_lake`, `coast_distance_km`, `feature_distances` |
| Population / relief (optional v2) | NE **populated places** “nearest city above N inhabitants”; optional **SRTM** tile sample for “major relief nearby” | Optional slots for tier_2 variety |

**Implementation sketch:** Python **`geopandas` + `shapely` + `pyproj`** (add to `data/scripts/requirements.txt`); precompute projected CRS (e.g. **EPSG:3857** or local UTM) **per POI** for distance queries inside bbox buffer. **Normative script names:** **`build_poi_geo_context.py`** (C0) → **`compile_useful_hint_tiers.py`** (C1) — see [`docs/scripts/README.md`](../docs/scripts/README.md).

#### C1 — Tier compilation (deterministic strings)

| Tier | Rule (default) | Example pattern |
|------|----------------|-----------------|
| **tier_1** | Continent + hemisphere + latitude **band** (ordinal, not numeric lat/lon) | “Indonesian archipelago · tropical maritime Southeast Asia” |
| **tier_2** | **Marine / coastline framing** from C0 buckets (still **no** numeric coordinates) | Ordinal “very coastal / inland / deep interior” phrasing |
| **tier_3** | **Hydrology synthesis** — named river/lake labels from NE + proximity **enum** (immediate / near / regional / distant) | “Named linear water …; standing water …” |
| **tier_4** | **Subnational** emphasis (admin-1 name when resolved) | “First-order admin context: **Bali** …” |
| **tier_5** | **Admin-0** country label | “Indonesia” |
| **tier_6** | **Strongest scripted assist** — may combine admin1 + admin0 + compact hydro recap; **still no coordinate literals** | “Interior district pattern within **Indonesia**; hydro: …” |

**Hard bans:** no digit sequences matching **lat/lon** in **any** tier; no **street address** precision in early tiers unless explicitly allowed; max length per `docs/GAME-ENGINE.md` §9.1.

#### C2 — Validation (always on)

| Script / task | Input | Output |
|---------------|-------|--------|
| **`data/scripts/validate_hint_strings.py`** | `tier_1..N` + optional `facts_used` JSON | exit non-zero on coordinate regex hits on **any** tier, length caps, empty tiers when `assist_level != none`, optional **`enforce_max_tier_contains_admin0`** |

#### C3 — Optional LLM polish (local, smallest model)

| Script / task | Input | Output | Notes |
|---------------|-------|--------|-------|
| **`data/scripts/generate_useful_hints_llm.py`** (optional) | **Only** structured fact JSON from C0 (binned sectors, feature **names** and **distance buckets** — no raw lat/lon in prompt text) + `prompts/llm/useful_hints_system.md` | candidate tiers | **Must** pass **`validate_hint_strings.py`**; log **`model_id`**, **`revision`**, **`prompt_template_version`** to `data/cache/.../reports/model_pins.json` |

**Policy:** Every **published** `map_id` in `data/catalog/maps.yaml` **must** have non-empty tiers **or** explicit `assist_level: none` with UI hiding assist panels (per `docs/GAME-ENGINE.md` §7.1) — avoids the current Kotlin fallback where unknown maps silently use wrong truth.

### Phase D — Street View + LFM-VL batch (optional per map, ranked-safe)

**Sampling / pano policy (normative WBS):** **[`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](2026-04-18-streetview-google-perpendicular-sampling-full-scope.md)** — **`streetview_pano_service`** implements **`sampling_mode`** (**`STOCHASTIC_S2_FOOTPRINT`** default: seeded disk anchors + **`pano=`** when metadata supplies a pano + random headings), **`LEGACY_RADIAL_OFFSET`**, and **`OMNI_SINGLE_PANO`**; retries on Static **429**/5xx; **`tools/batch_streetview_hints.py`** forwards **`--pano-*`** flags, **`model_pins`** (**`sampling_mode`**, **`s2_area_policy_version`**), and **renumbers `rank` 1..N** after chunked LFM merges. Road graph / external bearing providers remain **deferred** in that WBS.

| Script / task | Input | Output | Notes |
|---------------|-------|--------|-------|
| **`tools/batch_streetview_hints.py`** (new, monorepo `tools/`) | Configurable **`--poi-limit`** / location subset; **`--sv-screenshots-per-location`**; **`--poi-root`**; **`--model-profile tiny`**; **`--pano-sampling-mode`** / **`--pano-jitter-seed`** / **`--pano-area-radius-m`** / **`--pano-min-anchor-separation-m`** / **`--pano-legacy-radius-m`** (per **IMP-110** WBS **PR-F**) | **`streetview_pano_service`** → **K** frames → **`lfm_vl_hint_service`** captioning → optional **text-only** narrative pass (`streetview_assist_narrative`) | Writes `streetview_hint_pack` (+ optional narrative field) per `SPEC-batch-streetview-hints.md` §1.1; **default local run: 12 POIs** before 120. |
| **Optional same driver** | **`render_mapbox_still`** index + **`lfm_vl_satellite_caption_service`** URL | **Separate** caption lines / Intel sidecar with **`pipeline: satellite_lfm_vl_specialist`** | **Not** mixed into `streetview_hint_pack` without provenance (`docs/GAME-ENGINE.md` §5.2). |
| **CI matrix** | HF_TOKEN, GPU | publishes Dataset shard or commits **pinned** `data/cache/<version>/` | Per `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` §2 + **`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`** (**PR-H**/**PR-G**) |

**Ranked:** Same generated packs ship **on device**; ranked integrity unchanged because **truth** is not in pack.

**Cross-modal footgun:** Mapbox still center/zoom **must** match the catalog row used to sample Street View frames; otherwise the primary still and SV prose **disagree** visually (`SPEC-render-mapbox-still.md` §7).

### Phase E — AI guess rows

| Script / task | Input | Output | Notes |
|---------------|-------|--------|-------|
| **`data/scripts/generate_ai_guess_fixture.py`** (new) | policy (fixed decoy, **TerraMind TiM JSON/NDJSON export** with `Coordinates`, or random seeded) | `ai_guesses` entries | Until **S6** Parquet sync exists, commit **versioned** JSON consumed by manifest assembler; **TiM `Coordinates` is the normative lat/lon source** when exports exist (`docs/GAME-ENGINE.md` §9.4). |

### Phase F — Manifest and ranked pack assembly

| Script / task | Input | Output | Notes |
|---------------|-------|--------|-------|
| **`data/scripts/assemble_manifest.py`** (new) | all rows above | `data/cache/.../manifest.full.json`, `manifest.public.json` | Public copy = current server redaction semantics |
| **`data/scripts/assemble_ranked_clue_pack.py`** (new) | same + strip truth | `ranked_clues/<map_id>.json` + single **`ranked_clue_pack.json`** envelope | Client merges with `RankedClue` from API (server may duplicate fields for forward compatibility) |
| **`data/scripts/sync_server_catalog.py`** (new) | `manifest.full.json` | Python snippet or SQL for `nutonic_server/catalog.py` | Short-term: codegen **PUBLISHED_MAPS** / **MANIFEST_*** ; long-term: **IMP-120** DB |

### Phase G — Narrative: Gradle + optional LLM merge

| Task | Input | Output | Notes |
|------|-------|--------|-------|
| **Gradle `:shared:generatePromptBundle`** | `prompts/**/*.md` (non-llm authorial) | `generated/.../prompt_bundle.json` → copy into `composeResources/files/narrative/` | Per `docs/NARRATIVE-AND-PROMPTS.md` §6: front matter, `slot`, `roles`, `content_hash` |
| **`data/scripts/narrative_llm_batch.py`** (optional) | mission/map vars | JSON sidecar keyed by `map_id` | Merged into PromptBundle with **`template_version`** |

---

## 6. Composable prompts (contract)

**Principle:** LLM prompts **never** receive raw golden coordinates for **ranked** jobs. For **useful_hints**, the **primary** input to any optional LLM (**§5 Phase C3**) is the **structured fact JSON** from **§5 Phase C0** (admin names, **nearest hydrology feature labels**, **coast distance bucket**, binned sectors) — not prose scraped from the web.

They receive:

- **Gazetteer + proximity feature labels** (continent, admin-0, admin-1, **named river/lake within R km**, coastline bucket) from **offline** vectors;
- **Distances** only as **binned** labels (e.g. `coastal_lt_25km`, `inland_gt_100km`) in the prompt text;
- **Style tokens** from `prompts/index.md`.

**Output contract:** JSON schema, e.g. `{ "tier_1": "...", … "tier_6": "..." }` with `maxLength` per tier (OpenAPI optional **`tier_4`–`tier_6`** for backward compatibility). **Validator** (Phase C) is mandatory on CI merge to `main`.

**Street View captions:** Separate prompt file per **viewpoint** with **image attachments** only; model returns `{ "caption": "...", "confidence": 0-1 }`; strip coordinates from model output via validator.

---

## 7. Multiplatform Kotlin consumption (implementation tasks)

| Task | Description |
|------|-------------|
| **Embed default manifest** | Ship `manifest.full.json` (or protobuf) under compose resources for **first-run offline**; `ContentCacheRepository` seeds from disk if HTTP fails — satisfies “every local map fully cached.” |
| **Ranked clue resolver** | **Partial (2026-04-14):** `readShippedRankedCluePack` + **`mergeRankedClueWithPack`** merge **`files/ranked/ranked_clue_pack.json`** into `POST …/ranked/rounds/start` clues (API values win when set). A dedicated `RankedCluePackRepository` DI layer remains optional polish. |
| **Remove dangerous fallbacks** | **Landed:** `WorldMapGameplayScreen.kt` no longer fabricates Vienna/NYC truth or AI coordinates; non-ranked rounds **fail closed** when no manifest row exists; **`readShippedFullManifest`** seeds gameplay when **`ContentCacheRepository`** is absent (tests / offline stub). |
| **Street View assist UI** | **Landed (SCAN dock):** `AssistDock` lists **`streetview_hint_pack`** lines + optional narrative from **`ManifestRoundLocation`** / ranked clue merge; ranked **forfeit** gating unchanged (`docs/RANKED-MODE.md` §6). |
| **Idempotency fix** | Stable `Idempotency-Key` for ranked submit (separate small PR, prerequisite for ranked E2E). |

**Web (Kotlin/JS):** Large binary caps — consider **splitting** `ranked_clue_pack` by `map_id` lazy fetch from same origin or gzip; document in `docs/map-engines.md` annex.

---

## 8. CI and release gates

1. **`catalog_lint`** + **`validate_hint_strings`** + **OpenAPI check** (existing pytest parity) on every PR touching `data/catalog` or `docs/openapi.yaml`.
2. **PR smoke (recommended):** `catalog_import_poi` + Phase **C** (no LLM) on **`data/downloads/geoguessr_poi_12`** only — fast, no GPU; fails if Natural Earth cache missing (runner caches `data/geo/`).
3. **`assemble_manifest`** produces ETag-friendly canonical JSON (`sort_keys` policy matches server `nutonic_server/main.py` manifest hashing approach or document divergence).
4. **Size budget job:** total composeResources `files/` MB ≤ threshold per target (Android AAB analyzer step optional).
5. **Reproducibility:** Lock **`model_id` + `revision` + `prompt_template_version`** in `data/cache/.../reports/model_pins.json` for any LLM/VLM output committed to repo.

---

## 9. Sequencing vs existing backlog

| Wave | This plan feeds |
|------|-----------------|
| **IMP-081** | Phases B, F + server bundle registry (**shipped JPEGs + `registry.json` are git-tracked** — maintenance is re-running scripts when catalog changes) |
| **IMP-082** | Phase E + F + client `AiGuessStore` from embedded pack |
| **IMP-083** exit | Phase A–**C2** minimum (deterministic hints on **`geoguessr_poi_12`**, no SV, no LLM) + §7 fail-closed UX + E2E |
| **IMP-090** | §1 ranked pack + §7 merge resolver + stable idempotency |
| **IMP-110 / 111** | Phase D |
| **IMP-120** | Phase F server sync → Parquet / DB instead of codegen |

---

## 10. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-14 | Initial plan: shipped cache intent, local vs ranked split, script phases, Kotlin gaps, CI gates |
| 0.2 | 2026-04-14 | Cross-linked from **`plans/2026-04-13-repo-state-gap-analysis.md` v0.9**, **`plans/2026-04-13-prioritized-implementation-task-backlog.md` v0.7**, **`plans/2026-04-13-implementation-planning-series-index.md` v0.6**, **`plans/2026-04-07-complete-implementation-architecture.md` §13**, **`plans/2026-04-13-claims-verification-baseline.md` v0.8** |
| 0.3 | 2026-04-14 | **§5.0** local-first roots (**`geoguessr_poi_12`** / **`geoguessr_poi_120`**), smallest-model policy, **`refs/`** usage table; **Phase C** split into **C0–C3** (proximity features + deterministic tiers + validator + optional LLM polish); **`fetch_geo_baselines.py`**; Phase **B** still reuse; **§6**/**§8**/**§9** aligned |
| 0.4 | 2026-04-14 | **`docs/scripts/`** index + **`SPEC-*.md`** per pipeline script; §3 link to per-script specs |
| 0.5 | 2026-04-14 | Link **`plans/2026-04-14-data-scripts-implementation-track.md`** + **testing-and-ci** supplement |
| 0.6 | 2026-04-14 | Phase **D**: explicit LFM hint route + optional **satellite caption** hop from Mapbox stills; Phase **E**: TerraMind **`Coordinates`** as primary **`ai_lat`/`ai_lon`** source; cross-modal centering footgun |
| 0.7 | 2026-04-14 | Phase **D** row: configurable POI count + **K** SV screenshots per POI + optional **LFM LLM** narrative pass (`streetview_assist_narrative`) per **`SPEC-batch-streetview-hints.md`** §1.1 |
| 0.8 | 2026-04-14 | **§4 / §7:** `streetview_hint_pack` **landed** on OpenAPI, Kotlin, server ranked clues, **`assemble_manifest`**, bundled **`ranked_clue_pack.json`** merge, **AssistDock** wiring, **fail-closed** non-ranked gameplay. |
| 0.9 | 2026-04-14 | **§4:** **`:shared:validateCatalog`** + **`validate_shipped_compose_resources.py`** and **`sync_server_catalog.py`** (**codegen**) documented as **landed**; **IMP-120** SQL sync called out as remaining. |
| 1.0 | 2026-04-18 | **Authority** + **Phase D:** cross-ref **`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`**; Phase D table rows for batch CLI / CI matrix aligned to **IMP-110** WBS (**PR-F**/**PR-H**/**PR-G**). |
| 1.1 | 2026-04-21 | **§4:** Clarify **git-tracked** **`files/maps/*.jpg`**, **`manifest.full.json`**, and **`server/.../bundles/*.jpg`**; **IMP-081** = workflow maintenance + **IMP-120** SQL; **§9** IMP-081 row note; gap analysis **v1.6** cross-ref. |

---

*End of plan.*
