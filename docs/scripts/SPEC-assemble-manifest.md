# Script specification: `assemble_manifest.py`

**Path:** `data/scripts/assemble_manifest.py`  
**Status:** Planned (**Phase F**).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase F.

---

## 1. Purpose

Merge **catalog**, **still bundle ids**, **`useful_hints`**, optional **`streetview_hint_pack`**, optional **`streetview_assist_narrative`** (fused prose from batch **S3**), **`ai_guesses`**, and **`maps.yaml`** into:

1. **`manifest.full.json`** — includes `locations` with `truth_lat`/`truth_lon` + all assists (for **embedded** non-ranked / dev).
2. **`manifest.public.json`** — **same shape** as server redacted manifest: **omit** or empty `locations` / `ai_guesses` unless policy flag `--expose-round-truth` (lab only); must match **`GET /api/v1/cache/manifest`** redaction semantics in `nutonic_server/main.py`.

---

## 2. Inputs

- `data/catalog/maps.yaml`, `data/catalog/locations/*.yaml`
- `data/cache/<version>/useful_hints/*.json`
- Optional `data/cache/<version>/streetview/*.json`
- `data/cache/<version>/ai_guesses.json`
- Still index from **`render_mapbox_still`** (`bundle_id`, sha256, compose path)

---

## 2.1 Cross-artifact join contract (normative)

All inputs **must** agree on **`content_version`** (or an explicit `--content-version` passed to every producer in the same run). **`location_id`** and **`map_id`** are the only join keys between:

| Artifact | Producer | Consumed fields on `ManifestRoundLocation` / `RankedClue` slice |
|----------|----------|------------------------------------------------------------------|
| Catalog row | `catalog_import_poi` | `map_id`, `location_id`, truth, `still_bundled_resource` / source paths, assist flags |
| Reference still | `render_mapbox_still` | `still_bundle_id`, `still_sha256` (via sidecar or catalog patch), `still_bundled_resource` |
| Useful hints | `compile_useful_hint_tiers` (+ optional `generate_useful_hints_llm`) | `useful_hints` (`UsefulHintsTiers`) |
| Street View pack | `batch_streetview_hints` | **`streetview_hint_pack`** once OpenAPI adds it (see shipped-cache plan §4); until then, stash under extension field only in **full** manifest for forward-compat tests |
| Street View narrative | `batch_streetview_hints` (**`--enable-narrative-pass`**) | Optional **`streetview_assist_narrative`** string (INTEL / chrome); OpenAPI extension in same change as `streetview_hint_pack` unless merged into narrative bundle elsewhere |
| AI marker | `generate_ai_guess_fixture` | `ai_guesses[]` rows (`AiGuessRow`) — **must** align with `docs/GAME-ENGINE.md` §12 / §9.4: primary production source is **TerraMind TiM `Coordinates`** inside modality exports when available; decoy/heuristic modes are **interim** only |

**Footguns**

1. **Partial runs:** If stills exist for 12/12 POIs but `useful_hints` for 11/12, assembly **must** fail closed (or require `--allow-partial` with explicit report) so the client never ships a manifest where SCAN hints reference a missing `location_id`.
2. **Double pipeline labels:** Mapbox-derived **satellite** LFM captions (specialist service) and **Street View** LFM hints (standard service) must **not** share the same manifest field without a **`pipeline`** / provenance sub-object — see `docs/GAME-ENGINE.md` §5.2 and `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md` §4.5.
3. **Ranked disk slice:** `assemble_ranked_clue_pack` output must never embed `geo_context/*.json` or raw `truth` from C0; only compiled tiers + clue-safe assets.

---

## 3. Output schema

Must conform to **`docs/openapi.yaml`** `CacheManifest` (and Kotlin `CacheManifestDocument`):

- `content_version` (monotonic or content-addressed string),
- `engine_version`,
- `maps[]`,
- `locations[]` (full only in `manifest.full.json`),
- `ai_guesses[]` (full only in full manifest).

**Canonical JSON:** `sort_keys=True`, `separators=(",", ":")` for **ETag parity** with server (document if client-only embed uses different hashing).

---

## 4. Validation gates

1. Run **`catalog_lint`** equivalent checks inline.
2. Every `location_id` with `assist_level != none` must have **`useful_hints`** present and **`validate_hint_strings`** passing.
3. If `streetview_hint_pack` present per location, run validator in caption mode.
4. If `streetview_assist_narrative` present, run the same **caption-mode** validator (length cap stricter than single pack line).

---

## 5. CLI

```text
python data/scripts/assemble_manifest.py [--content-version …] [--output-dir data/cache/…] [--expose-round-truth]
```

---

## 6. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 11 | Schema / validation failure |

---

## 7. Related

- [SPEC-assemble-ranked-clue-pack.md](SPEC-assemble-ranked-clue-pack.md)
- [SPEC-sync-server-catalog.md](SPEC-sync-server-catalog.md)

---

*Spec version: 2026-04-14*
