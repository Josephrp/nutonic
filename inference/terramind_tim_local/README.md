# NU:TONIC — local TerraMind **TiM** (TerraTorch) runner

Optional **GPU/CPU** batch tool under `inference/*` (not the thin game `server/`, not `data/scripts/`). Builds **`terramind_v1_*_tim`** via **`BACKBONE_REGISTRY`**, captures **TiM `GenerationSampler` outputs** (per imagined modality), serializes **schema-capped JSON**, and can emit **NDJSON** compatible with:

- `data/scripts/generate_ai_guess_fixture.py --mode terramind_tim_jsonl`

**Authority:** `rules/06-server-vlm-tim-and-on-device-ml.md`, `rules/12-python-gradio-terramind-server.md`, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` (Coordinates → `ai_lat` / `ai_lon` for catalog pipelines).

## Install (separate venv recommended)

```bash
cd inference/terramind_tim_local
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
```

### Install with **uv** (locked env, recommended for TerraTorch)

The package ships a **`uv.lock`** so TerraTorch, **peft**, **transformers**, and **urllib3** resolve together (avoids broken global stacks such as `HybridCache` / `BaseSSLError` mismatches).

From the **monorepo root** `nutonic/`:

```bash
uv sync --project inference/terramind_tim_local --extra dev --extra s2
```

The **`s2`** extra includes **`boto3`** so **rasterio** can build a real **AWS session** for Earth Search / `amazonaws.com` COG URLs instead of logging **DummySession** fallback INFO on every band open.

Run the CLI with the project venv (cwd becomes `inference/terramind_tim_local`):

```bash
uv run --directory inference/terramind_tim_local python -m nutonic_terramind_tim_local run ^
  --config config.example.yaml --output-dir ./out
```

**S2-compatible GeoGuessr E2E** (STAC + `rgb_mode: s2_rgb`; writes under `data/downloads/…`):

```bash
uv run --directory inference/terramind_tim_local python -m nutonic_terramind_tim_local run ^
  --config config.geoguessr_live_3row_s2_compatible.yaml ^
  --output-dir ../../data/downloads/tim_geoguessr_uv_e2e
```

**GeoGuessr E2E + full TiM materialization** (same three POIs, **`terramind_v1_large_tim`**, **`pretrained: true`**): runs STAC batch, writes `tim_export.jsonl` / `tim_run.json`, and under each **`<output-dir>/<map_id>/materialized/`** writes **every TiM sampler key** — `tim_shapes.json`, **`coords_*_decoded.json`**, each **`untok_*`** as **`{key}_tensor_preview.png`** (12-band S2 uses RGB = bands 3,2,1), each **`tok_*`** as **`{key}_decoded.png`** plus LULC/NDVI extras when those names appear. First run downloads large weights from Hugging Face.

```bash
uv run --directory inference/terramind_tim_local python -m nutonic_terramind_tim_local.geoguessr_materialize ^
  --config config.geoguessr_live_3row_s2_compatible_large.yaml ^
  --output-dir ../../data/downloads/tim_geoguessr_large_materialized
```

Equivalent console script: **`nutonic-tim-geoguessr-materialize`** (same module).

Tests:

```bash
uv run --directory inference/terramind_tim_local pytest tests -q
```

Weights download from Hugging Face on first `pretrained: true` run (`HF_TOKEN` optional for higher rate limits).

### Hugging Face Space (Docker + optional ZeroGPU)

Optional **`[space]`** extra adds **FastAPI** on port **`PORT`** (default **7860**): **`GET /health`**, **`POST /v1/tim/export`** (JSON `config` or `config_yaml`). Run locally:

```bash
pip install -e ".[space]"
python -m nutonic_terramind_tim_local.run_space_serve
```

The repo **`Dockerfile`** targets **CUDA** images; pick **ZeroGPU** or GPU hardware on Hugging Face. CI deploy: **`tools/hf_deploy/README.md`**.

## Quick run (random RGB smoke)

On Windows, if the console script is not on `PATH`, use the module form:

```bash
cd inference/terramind_tim_local
python -m nutonic_terramind_tim_local run --config config.example.yaml --output-dir ./out
```

Artifacts:

- `tim_run.json` — full capped export (TiM dict + encoder trace).
- `tim_export.jsonl` — one JSON object per `--line` (default single smoke line); includes `tim_modality_outputs` for downstream tools.

## Ingest → `ai_guesses.json`

Delegates to the torch-free repo script:

```bash
python -m nutonic_terramind_tim_local ingest --tim-jsonl ./out/tim_export.jsonl --catalog-root ../../data/catalog --content-version dev
```

This runs `python ../../data/scripts/generate_ai_guess_fixture.py --mode terramind_tim_jsonl ...`.

## Batch mode (`config.batch`)

Add a YAML list of `{map_id, location_id, rgb_mode?, rgb_jpeg?}` rows. Each row runs **one** forward pass on a shared loaded model (amortizes weight download / init). Example:

```yaml
batch:
  - { map_id: poi_0001, location_id: poi_0001, rgb_mode: random }
  - { map_id: poi_0002, location_id: poi_0002, rgb_mode: jpeg, rgb_jpeg: data/downloads/.../mapbox/foo.png }
```

Then `python -m nutonic_terramind_tim_local run ...` writes **multiple** JSONL lines (one per batch row) plus `tim_run.json` as `{ "runs": [ ... ] }`.

## TiM modality names (TerraTorch)

Use **IBM/TerraTorch spellings** in YAML, for example `LULC`, `NDVI`, **`location`** (maps internally to **`coords`**; exported as OpenAPI-style **`Coordinates`** / `coordinates_wgs84`). Do **not** pass the string `Coordinates` to `BACKBONE_REGISTRY.build` — it is not a valid `tim_modality` key in TerraTorch 1.2.x.

## Input and output modalities (this runner)

- **`config.modalities`** — encoder inputs you pass as tensors in the forward dict (`RGB`, `S2L2A`, …). The export row includes `engine.input_modalities` (same list) for traceability.
- **`config.tim_modalities`** — TiM heads / sampler outputs (e.g. `LULC`, `NDVI`, `location`). Listed under `engine.output_modalities_tim` and `engine.tim_modalities`.
- **`serialization.tim_outputs`** — `product` (default): compact PRO-style grouping (`Coordinates`, `LULC`, `_inputs` for untokenized stacks). `full`: every key returned by the TiM sampler is serialized at the top level of `tim_modality_outputs` (no silent drops), still adding `Coordinates` when `coords` decode succeeds.
- **`serialization.include_tim_raw_keys: true`** — adds `engine.tim_raw_keys` (sorted internal dict keys from the last sampler return).

## Sentinel-2 L2A (`S2L2A`)

TerraMind expects **12 channels** in the same order as TerraTorch `PRETRAINED_BANDS["untok_sen2l2a@224"]` (B01, B02, …, B8A, B09, B11, B12), at **224×224**, with values on the **~0–10000** surface-reflectance scale used by the pretrained tokenizer.

- **Synthetic / smoke:** set `modalities: [S2L2A]` and `inputs.s2_mode: random` or `zeros` (see `config.example.s2l2a.yaml`).
- **STAC pull (Earth Search–style catalogs):** set `inputs.s2_mode: stac` (or per-batch `s2_mode: stac`) and install extras: `pip install -e ".[s2]"`. Provide `inputs.s2.lat`, `inputs.s2.lon`, `inputs.s2.datetime` (or the same keys on each `batch` row / top-level `inputs.datetime`). Default band assets match **Element84 Earth Search** ``sentinel-2-l2a`` ids: ``coastal``, ``blue``, …, ``nir``, ``nir08``, ``wvp``, ``swir16``, ``swir22``. Override with ``inputs.s2.asset_keys`` (12 strings) for other catalogs (e.g. ``B01``…``B12``).
- **End-to-end GeoGuessr POI batch (RGB on disk + S2 STAC):** see ``config.geoguessr_live_3row_full_output.yaml`` (run from repo root; set ``paths.repo_root: .``).
- After a STAC run, the export includes `inputs_meta.s2_stac` (item id, datetime, cloud cover, resolved asset keys).

For **RGB + S2** together, set `inputs.mode` for RGB (e.g. `jpeg`) and **`inputs.s2_mode`** for S2 (defaults to `random` if unset — it does **not** reuse `inputs.mode`).

**TerraMind `RGB` is not generic JPEG.** The backbone maps the string `RGB` to **`untok_sen2rgb@224`** (Sentinel-2 RED / GREEN / BLUE reflectance, same numeric range as S2L2A). Feeding Mapbox or other 8-bit RGB PNGs (e.g. `rgb_mode: jpeg`) will **not** match pre-training and TiM outputs can look arbitrary. For POI batches, use **`rgb_mode: s2_rgb`** so RGB is sliced from the same STAC stack as `S2L2A` (see `config.geoguessr_live_3row_s2_compatible.yaml`), or use **`modalities: [S2L2A]`** only.

## CI

Default GitHub Actions **do not** install TerraTorch. Opt-in smoke:

```bash
set RUN_TERRATORCH_TIM=1
pytest inference/terramind_tim_local/tests -q
```
