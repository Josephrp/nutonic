# NU:TONIC — Data and cache pipeline script specifications

**Purpose:** Normative **per-script** specifications for the shipped-cache / catalog / hint production pipeline. **Orchestration plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md).  
**Implementation plans:** [`plans/2026-04-14-data-scripts-implementation-track.md`](../../plans/2026-04-14-data-scripts-implementation-track.md) (ordered tracks + PR boundaries), [`plans/2026-04-14-data-scripts-testing-and-ci.md`](../../plans/2026-04-14-data-scripts-testing-and-ci.md) (fixtures, pytest, CI).

**Authority:** Complements `docs/GAME-ENGINE.md` §9, `docs/NARRATIVE-AND-PROMPTS.md`, `rules/13-client-cache-and-data-plane.md`, `docs/openapi.yaml`.

**Convention:** Each `SPEC-*.md` file matches one **planned or existing** script path. Implementations must satisfy the spec; when code diverges, update the spec in the same PR.

| Spec | Script path | Phase |
|------|-------------|--------|
| [SPEC-download-geoguessr-poi-imagery.md](SPEC-download-geoguessr-poi-imagery.md) | `data/scripts/download_geoguessr_poi_imagery.py` | **Existing** ingest |
| [SPEC-geo-nutonic.md](SPEC-geo-nutonic.md) | `data/scripts/geo_nutonic.py` (planned shared module) | Shared |
| [SPEC-fetch-geo-baselines.md](SPEC-fetch-geo-baselines.md) | `data/scripts/fetch_geo_baselines.py` | **A — implemented** |
| [SPEC-catalog-import-poi.md](SPEC-catalog-import-poi.md) | `data/scripts/catalog_import_poi.py` | **A — implemented** |
| [SPEC-catalog-lint.md](SPEC-catalog-lint.md) | `data/scripts/catalog_lint.py` | **A — implemented** |
| [SPEC-render-mapbox-still.md](SPEC-render-mapbox-still.md) | `data/scripts/render_mapbox_still.py` | **B — implemented** |
| [SPEC-build-poi-geo-context.md](SPEC-build-poi-geo-context.md) | `data/scripts/build_poi_geo_context.py` | **C0 — implemented** |
| [SPEC-compile-useful-hint-tiers.md](SPEC-compile-useful-hint-tiers.md) | `data/scripts/compile_useful_hint_tiers.py` | **C1 — implemented** |
| [SPEC-validate-hint-strings.md](SPEC-validate-hint-strings.md) | `data/scripts/validate_hint_strings.py` | **C2 — implemented** |
| [SPEC-generate-useful-hints-llm.md](SPEC-generate-useful-hints-llm.md) | `data/scripts/generate_useful_hints_llm.py` | C3 (optional) |
| [SPEC-batch-streetview-hints.md](SPEC-batch-streetview-hints.md) | `tools/batch_streetview_hints.py` | D |
| [SPEC-generate-ai-guess-fixture.md](SPEC-generate-ai-guess-fixture.md) | `data/scripts/generate_ai_guess_fixture.py` | **E — implemented** |
| [SPEC-assemble-manifest.md](SPEC-assemble-manifest.md) | `data/scripts/assemble_manifest.py` | **F — implemented** |
| [SPEC-assemble-ranked-clue-pack.md](SPEC-assemble-ranked-clue-pack.md) | `data/scripts/assemble_ranked_clue_pack.py` | **F — implemented** |
| [SPEC-sync-server-catalog.md](SPEC-sync-server-catalog.md) | `data/scripts/sync_server_catalog.py` | F |
| [SPEC-narrative-llm-batch.md](SPEC-narrative-llm-batch.md) | `data/scripts/narrative_llm_batch.py` | G (optional) |

**Gradle (non-Python):** `:shared:validateCatalog` — see note in [SPEC-catalog-lint.md](SPEC-catalog-lint.md) §Related.

**Heavy ML boundary:** `data/scripts/` stays **torch-free and TerraTorch-free** (fast CI, no GPU imports). **VLMs** (e.g. LFM-VL) and **TerraMind / TerraTorch** run only in **`inference/*`**, **`tools/`**, **`demos/terramind_space/`**, or **HF Jobs** — those processes **may** load models via:

1. **[vLLM](https://docs.vllm.ai/)** — OpenAI-compatible HTTP server (batch / game node call it as a URL), when the **model is supported** by vLLM; or  
2. **Hugging Face `transformers` + PyTorch** — in-process inside a FastAPI (or similar) worker behind the same HTTP contracts; or  
3. **TerraTorch directly** — normative for **TerraMind TiM / `terramind_v1_*_generate`** on EO stacks (`rules/12-python-gradio-terramind-server.md`), not mixed into the thin **`server/`** process.

`data/scripts` call those tiers over **HTTP** (or subprocess to local URLs); see [SPEC-generate-useful-hints-llm.md](SPEC-generate-useful-hints-llm.md) §1, [SPEC-batch-streetview-hints.md](SPEC-batch-streetview-hints.md), and `inference/README.md`.

---

*Index version: 2026-04-14d — `generate_ai_guess_fixture` landed*
