# NU:TONIC — Data and cache pipeline script specifications

**Purpose:** Normative **per-script** specifications for the shipped-cache / catalog / hint production pipeline. **Orchestration plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md).  
**Implementation plans:** [`plans/2026-04-14-data-scripts-implementation-track.md`](../../plans/2026-04-14-data-scripts-implementation-track.md) (ordered tracks + PR boundaries), [`plans/2026-04-14-data-scripts-testing-and-ci.md`](../../plans/2026-04-14-data-scripts-testing-and-ci.md) (fixtures, pytest, CI).  
**Client UI ship criteria (manifest copy, offline strings, release gates):** [`plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md`](../../plans/2026-04-21-publishable-ui-stitch-parity-and-ship-criteria.md), [`docs/PUBLISHABLE-UI-EXIT-CRITERIA.md`](../PUBLISHABLE-UI-EXIT-CRITERIA.md) — align catalog **`content_version`** bumps with embedded `manifest.full.json` to avoid **IMP-147** user-visible skew.

**Authority:** Complements `docs/GAME-ENGINE.md` §9, `docs/NARRATIVE-AND-PROMPTS.md`, `rules/13-client-cache-and-data-plane.md`, `docs/openapi.yaml`.

**Convention:** Each `SPEC-*.md` file matches one **planned or existing** script path. Implementations must satisfy the spec; when code diverges, update the spec in the same PR.

| Spec | Script path | Phase |
|------|-------------|--------|
| [SPEC-download-geoguessr-poi-imagery.md](SPEC-download-geoguessr-poi-imagery.md) | `data/scripts/download_geoguessr_poi_imagery.py` | **Existing** ingest |
| [SPEC-lfm-vl-sft-dataset.md](SPEC-lfm-vl-sft-dataset.md) | `data/scripts/build_lfm_vl_sft_dataset.py` + `data/scripts/run_lfm_vl_sft_orchestrator.py` + `data/scripts/lfm_vl_sft_dataset/` | **S2 + Dynamic World → JSONL + Hub** (builder + optional multi-batch orchestrator; see spec §7) |
| [SPEC-geo-nutonic.md](SPEC-geo-nutonic.md) | `data/scripts/geo_nutonic.py` | **Shared — implemented** |
| [SPEC-fetch-geo-baselines.md](SPEC-fetch-geo-baselines.md) | `data/scripts/fetch_geo_baselines.py` | **A — implemented** |
| [SPEC-catalog-import-poi.md](SPEC-catalog-import-poi.md) | `data/scripts/catalog_import_poi.py` | **A — implemented** |
| [SPEC-catalog-lint.md](SPEC-catalog-lint.md) | `data/scripts/catalog_lint.py` | **A — implemented** |
| [SPEC-render-mapbox-still.md](SPEC-render-mapbox-still.md) | `data/scripts/render_mapbox_still.py` | **B — implemented** |
| [SPEC-build-poi-geo-context.md](SPEC-build-poi-geo-context.md) | `data/scripts/build_poi_geo_context.py` | **C0 — implemented** |
| [SPEC-compile-useful-hint-tiers.md](SPEC-compile-useful-hint-tiers.md) | `data/scripts/compile_useful_hint_tiers.py` | **C1 — implemented** |
| [SPEC-validate-hint-strings.md](SPEC-validate-hint-strings.md) | `data/scripts/validate_hint_strings.py` | **C2 — implemented** |
| [SPEC-generate-useful-hints-llm.md](SPEC-generate-useful-hints-llm.md) | `data/scripts/generate_useful_hints_llm.py` | **C3 — dry-run + CLI** (live polish backends per SPEC §5) |
| [SPEC-batch-streetview-hints.md](SPEC-batch-streetview-hints.md) | `tools/batch_streetview_hints.py` | **D — implemented** (local stubs under `inference/*`) |
| [SPEC-generate-ai-guess-fixture.md](SPEC-generate-ai-guess-fixture.md) | `data/scripts/generate_ai_guess_fixture.py` | **E — implemented** |
| [SPEC-assemble-manifest.md](SPEC-assemble-manifest.md) | `data/scripts/assemble_manifest.py` | **F — implemented** |
| [SPEC-assemble-ranked-clue-pack.md](SPEC-assemble-ranked-clue-pack.md) | `data/scripts/assemble_ranked_clue_pack.py` | **F — implemented** |
| [SPEC-sync-server-catalog.md](SPEC-sync-server-catalog.md) | `data/scripts/sync_server_catalog.py` | **F — implemented** (`catalog_generated.py`) |
| [SPEC-narrative-llm-batch.md](SPEC-narrative-llm-batch.md) | `data/scripts/narrative_llm_batch.py` | **G — dry-run stub** (live LLM per SPEC §5) |

**Gradle (non-Python):** `:shared:validateCatalog` runs **`data/scripts/validate_shipped_compose_resources.py`** against **`composeResources/files/cache/manifest.full.json`** and **`still_bundled_resource`** paths — see [SPEC-catalog-lint.md](SPEC-catalog-lint.md) §5. **`sync_server_catalog.py`** (**`--write`**) keeps **`server/src/nutonic_server/catalog_generated.py`** in sync with that manifest ([SPEC-sync-server-catalog.md](SPEC-sync-server-catalog.md)).

**TerraMind TiM → `ai_guesses`:** torch-free **`generate_ai_guess_fixture.py`**; local TerraTorch forward + **`ingest`** live under **`inference/terramind_tim_local/`** (`inference/terramind_tim_local/README.md`, [SPEC-generate-ai-guess-fixture.md](SPEC-generate-ai-guess-fixture.md)).

**Optional LLM scripts:** **`narrative_llm_batch.py`** and **`generate_useful_hints_llm.py`** default to **dry-run / stub** behavior until **`prompts/llm/`** and live backends are wired per their `SPEC-*.md` files.

**Heavy ML boundary:** `data/scripts/` stays **torch-free and TerraTorch-free** (fast CI, no GPU imports). **VLMs** (e.g. LFM-VL) and **TerraMind / TerraTorch** run only in **`inference/*`**, **`tools/`**, **`demos/terramind_space/`**, or **HF Jobs** — those processes **may** load models via:

1. **[vLLM](https://docs.vllm.ai/)** — OpenAI-compatible HTTP server (batch / game node call it as a URL), when the **model is supported** by vLLM; or  
2. **Hugging Face `transformers` + PyTorch** — in-process inside a FastAPI (or similar) worker behind the same HTTP contracts; or  
3. **TerraTorch directly** — normative for **TerraMind TiM / `terramind_v1_*_generate`** on EO stacks (`rules/12-python-gradio-terramind-server.md`), not mixed into the thin **`server/`** process.

`data/scripts` call those tiers over **HTTP** (or subprocess to local URLs); see [SPEC-generate-useful-hints-llm.md](SPEC-generate-useful-hints-llm.md) §1, [SPEC-batch-streetview-hints.md](SPEC-batch-streetview-hints.md), and `inference/README.md`.

---

*Index version: 2026-04-21 — Cross-link publishable UI plan + exit criteria (`content_version` / embedded manifest alignment).*
