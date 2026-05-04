# NU:TONIC — Hugging Face Jobs (hydration)

This folder documents **Hugging Face Jobs** for **GPU** cache hydration alongside **local** tooling (`tools/batch_streetview_hints.py`, `inference/terramind_tim_local`, `tools/run_geoguessr_hydration_local.py`). **Spaces** remain supported via `tools/hf_deploy/`; Jobs are for **one-shot / scheduled** heavy batches with **dataset volumes**.

## Prerequisites

- Repo root **``.dockerignore``** (excludes ``**/.venv/``, ``data/cache/``, ``.git/``, …) so ``docker build`` for **TiM** does not upload a multi‑gigabyte context (local ``inference/terramind_tim_local/.venv`` is the usual culprit). If you still see ``rpc error: code = Unavailable`` / EOF while **transferring context**, confirm the ignore file exists and retry ``docker build``.
- Hub account with **Jobs** enabled (see [Run and manage Jobs](https://huggingface.co/docs/huggingface_hub/guides/jobs)).
- `pip install -r tools/hf_jobs/requirements.txt`
- Hub tokens in `.env` (recommended):
  - **`HF_API_WRITE`** — submit Jobs and upload artifacts from the container (also used as `HF_TOKEN` secret when using `--secret-hf-token`).
  - **`HF_API_READ`** — `tools/pull_poidata_from_hub.py` and `tools/download_hydration_outputs.py` (falls back to the write token or `HF_TOKEN`).

## POI source: `NuTonic/poidata`

The dataset [NuTonic/poidata](https://huggingface.co/datasets/NuTonic/poidata) mirrors POI trees used under `data/downloads/`. The Hub **dataset viewer** may show generation errors for `Image`-typed tables; **file snapshots** still work.

**Jobs:** the volume should expose Layout-B folders `geoguessr_poi_12/` and `geoguessr_poi_120/` (with `poi_*/poi.json`). If the mount is empty or nested differently, **`entrypoint_hf_hydration.py`** tries shallow discovery, then **`snapshot_download`** for missing subtrees from **`NUTONIC_POIDATA_REPO`** (default `NuTonic/poidata`) using **`HF_TOKEN`** (your Job secret must allow **read** on that dataset). Set **`NUTONIC_NO_POIDATA_SNAPSHOT=1`** to disable Hub pull and fail fast.

**Local pull:**

```bash
python tools/pull_poidata_from_hub.py --local-dir data/downloads
```

This writes `data/downloads/geoguessr_poi_12/` and `data/downloads/geoguessr_poi_120/` when those paths exist in the repo snapshot. Adjust patterns:

```bash
python tools/pull_poidata_from_hub.py --local-dir data/downloads --allow-patterns "**"
```

## Full catalog: both POI roots + ranked / unranked

1. Pull POI bytes (above) or use an existing local `data/downloads/`.
2. Import **both** trees into **one** catalog (merge `maps.yaml`; add all `locations/*.yaml`). Run `catalog_import_poi.py` twice with `--force` on the second import, or import the larger tree first then the smaller with `--force` only on overlapping IDs (plan: run `geoguessr_poi_120` then `geoguessr_poi_12` if you need 120 as canonical for shared IDs).
3. Set **`--ranked-split half`** on the final import if you want ~50/50 `ranked_pool` flags for **ranked vs non-ranked** packaging (`assemble_ranked_clue_pack.py` reads `maps.yaml`).

Then run `build_poi_geo_context` → `compile_useful_hint_tiers` → `render_mapbox_still` → Street View batch → TiM ingest → `assemble_manifest` / `assemble_ranked_clue_pack` per `data/scripts/README.md`.

## Street View sampling env (sv-lfm Job)

The container entrypoint forwards optional **environment variables** to ``batch_streetview_hints.py`` (see ``tools/hf_jobs/pano_batch_env.py``):

| Variable | Effect |
|----------|--------|
| ``NUTONIC_SHUFFLE_SEED`` | ``--shuffle-seed`` — reproducible catalog order and per-POI ``jitter_seed`` derivation |
| ``NUTONIC_PANO_SAMPLING_MODE`` | ``--pano-sampling-mode`` (default in code: ``STOCHASTIC_S2_FOOTPRINT``) |
| ``NUTONIC_PANO_JITTER_SEED`` | ``--pano-jitter-seed`` (same seed every POI) |
| ``NUTONIC_PANO_AREA_RADIUS_M`` | ``--pano-area-radius-m`` |
| ``NUTONIC_PANO_MIN_ANCHOR_SEPARATION_M`` | ``--pano-min-anchor-separation-m`` |
| ``NUTONIC_PANO_LEGACY_RADIUS_M`` | ``--pano-legacy-radius-m`` (legacy mode only) |
| ``STREETVIEW_S2_GSD_M``, ``STREETVIEW_S2_CHIP_EDGE_PX`` | Passed into the pano **uvicorn** worker for default disk **R** |
| ``STREETVIEW_EXPOSE_SAMPLING_DEBUG`` | ``1`` / ``true`` — adds ``sampling_debug`` to pano responses (no secrets) |

**CLI (host):** ``python tools/run_full_hydration.py`` accepts ``--shuffle-seed``, ``--pano-sampling-mode``, ``--pano-jitter-seed``, ``--pano-area-radius-m``, ``--pano-min-anchor-separation-m``, ``--pano-legacy-radius-m`` and injects them into the **sv-lfm** Job env only.

## Street View + LFM-VL on a Job (VLM in the cloud)

1. Build and push a Docker image that contains:
   - This repo (or a slim copy): `data/scripts`, `tools`, `inference/streetview_pano_service`, `inference/lfm_vl_hint_service` with **`[model]`** extras.
   - An **entrypoint** script that:
     - Copies or symlinks `/mnt/poidata/geoguessr_poi_*` → `data/downloads/` if a volume is mounted.
     - Exports `STREETVIEW_PROVIDER=google`, `LFM_VL_BACKEND=transformers`, API keys from **Job secrets** (never bake keys into the image).
     - Starts `uvicorn` for pano + LFM on two ports, runs `python tools/batch_streetview_hints.py …`, uploads `data/cache/.../streetview/*.json` to a **private** dataset or artifact store.
2. Submit:

```bash
python tools/submit_nutonic_hydration_job.py streetview-lfm \
  --docker-image YOUR_DOCKERHUB/nutonic-hydration-sv-lfm:2026-04-16 \
  --flavor a10g-small \
  --secret-hf-token \
  --timeout 8h \
  --env CONTENT_VERSION=hf-job-sv-2026-04-16 \
  -- -- /app/entrypoint_sv_lfm.sh
```

`--secret-hf-token` forwards **`HF_API_WRITE`** (else **`HF_TOKEN`**) from your shell into the Job as **`HF_TOKEN`** so the container can `huggingface_hub` upload results.

### Build and push all Job images

From the **repo root**, with Docker logged in (`docker login`):

```bash
python tools/hf_jobs/build_and_push_images.py --namespace YOUR_DOCKERHUB_USER --tag 2026-04-18
```

The helper stages a **minimal temp build context per image** (`data/scripts`, relevant `inference/*`, `tools/*`, prompts when needed) before invoking Docker. This is the recommended path and avoids brittle root-context issues.

Builds and pushes three tags:

- `nutonic-hydration-sv-lfm` — `Dockerfile.hydration` (Street View + LFM-VL + `data/scripts` pipeline).
- `nutonic-hydration-tim` — `Dockerfile.hydration-tim` (TerraMind TiM STAC batch + Hub upload via `entrypoint_tim_hf.py`).
- `nutonic-hydration-llm` — `Dockerfile.hydration-llm` (**transformers** in-process by default when live; **vLLM** optional via **`NUTONIC_NARRATIVE_BACKEND=vllm`** + **`NUTONIC_VLLM_MODEL`**; GPU flavor; **`NUTONIC_NARRATIVE_LLM_LIVE=1`**).

Use `--dry-run` to print `docker build` / `docker push` commands only; `--no-push` to build locally.

### Full orchestration (three Jobs + local download)

1. Set `NUTONIC_HYDRATION_OUTPUT_DATASET` to your target dataset id (e.g. `NuTonic/nutonic-hydration-cache-test`). The **sv-lfm** and **TiM** entrypoints call `create_repo(..., repo_type="dataset", exist_ok=True)` before `upload_folder`, so the dataset is created on first run if your token can write under that namespace (**private** by default). Set `NUTONIC_HYDRATION_OUTPUT_PUBLIC=1` for a public dataset, or `NUTONIC_SKIP_CREATE_OUTPUT_DATASET=1` to require a pre-existing repo.
2. Build and push the three images (section above). Optionally set `NUTONIC_DOCKER_NAMESPACE` and reuse the printed `NUTONIC_HYDRATION_*_IMAGE` lines.
3. From repo root (with `.env` containing keys above):

```bash
python tools/run_full_hydration.py --content-version hf-2026-04-16 \
  --sv-image YOUR_DOCKERHUB/nutonic-hydration-sv-lfm:TAG \
  --tim-image YOUR_DOCKERHUB/nutonic-hydration-tim:TAG \
  --llm-image YOUR_DOCKERHUB/nutonic-hydration-llm:TAG
```

Jobs run in order: **sv-lfm** → **TiM** → **llm-sidecars**. Override the in-container TiM YAML with `--tim-config-in-container` or env `NUTONIC_TIM_HF_CONFIG`. Use `--skip-tim` to omit the TiM job.

For a **small slice** (e.g. first five ``geoguessr_poi_12`` POIs), pass ``--poi-limit 5`` on ``run_full_hydration.py`` / ``run_hf_hydration_full.py`` (Jobs set ``NUTONIC_POI_LIMIT``). **Geo context:** the sv-lfm entrypoint runs ``build_poi_geo_context.py`` with ``--allow-partial`` by default (skip bad coordinates / Shapely failures; still writes other POIs). Set ``NUTONIC_GEO_CONTEXT_ALLOW_PARTIAL=0`` on the Job to fail fast, or ``--skip-geo-hints`` to omit geo + useful_hints entirely. TiM uses ``config.hf_job_geoguessr_poi12_first5.yaml`` when the limit is 5 (unless you override ``--tim-config-in-container``).

**Without Mapbox (Sentinel-2 STAC reference stills):** pass ``--skip-mapbox-stills`` (or set ``NUTONIC_SKIP_MAPBOX_STILLS=1`` before submit). The sv-lfm Job runs ``render_mapbox_still.py --stac-reference-stills`` — Earth Search ``sentinel-2-l2a`` thumbnail/visual previews per POI (falls back to gray placeholder if STAC decode fails). No Mapbox token. Set ``NUTONIC_STAC_REFERENCE_STILLS=0`` for solid placeholders only. Optional tuning: ``NUTONIC_STAC_STILL_URL``, ``NUTONIC_STAC_STILL_BBOX_HALF_KM``, ``NUTONIC_STAC_STILL_MAX_CLOUD``, ``NUTONIC_STAC_STILL_DATETIME``. **TiM** bundled YAMLs (``config.hf_job_geoguessr_poi12_first*.yaml``, ``config.geoguessr_live_3row_*.yaml``) default to **``terramind_v1_large_tim``** (see ``nutonic_terramind_tim_local.tim_defaults``); override with ``TIM_HF_CONFIG`` / ``--tim-config-in-container`` when you need a smaller backbone for smoke tests.

Use `--dry-run-submit` to print resolved Job specs without calling the Hub. Use `--skip-download` if you only want Hub-side artifacts.

**Narrative LLM on the llm-sidecars Job:** default sidecar is **dry-run** unless **`NUTONIC_NARRATIVE_LLM_LIVE=1`**. Live inference (set via host **`--narrative-llm-live`** on `run_hf_hydration_full.py`):

If the llm-sidecars Job exits **137** (`SIGKILL`), the container was almost certainly **OOM-killed** while loading or running the text LM (large **`NUTONIC_NARRATIVE_TRANSFORMERS_MAX_NEW`**, many catalog rows, or a small GPU flavor). Lower max-new tokens, use a larger Job flavor, or shorten the catalog slice (`--poi-limit`).

| `NUTONIC_NARRATIVE_BACKEND` | Behavior |
|-----------------------------|----------|
| ``transformers`` (default when live, backend unset) | In-process HF causal LM on the Job GPU: **`NUTONIC_NARRATIVE_TRANSFORMERS_MODEL`** or default **Liquid LFM** text id from ``liquid_ai_defaults.py`` (+ optional **`NUTONIC_NARRATIVE_TRANSFORMERS_MAX_NEW`**). |
| ``vllm`` | Start **`python -m vllm.entrypoints.openai.api_server`** (unless ``NUTONIC_VLLM_SERVE_CMD`` / ``NUTONIC_VLLM_AUTOSTART=0``), wait on ``/v1/models``, then ``narrative_llm_batch.py --backend openai``. |
| ``openai`` | Same OpenAI HTTP path as ``vllm`` (external or autostarted server). |
| ``ollama`` | Legacy **`ollama serve`** if the binary exists on ``PATH``. |

Optional: **`NUTONIC_NARRATIVE_ENTRY_MAX`** (stored text cap after optional markdown strip), **`NUTONIC_NARRATIVE_OPENAI_MAX_TOKENS`**, **`NUTONIC_NARRATIVE_OPENAI_TEMPERATURE`**, **`NUTONIC_NARRATIVE_TRANSFORMERS_MAX_NEW`**, **`NUTONIC_NARRATIVE_TRANSFORMERS_TEMPERATURE`**, **`NUTONIC_NARRATIVE_TRANSFORMERS_TOP_P`**, **`NUTONIC_NARRATIVE_OLLAMA_NUM_PREDICT`**, **`NUTONIC_NARRATIVE_STRIP_MARKDOWN`** (`0` to disable), **`NUTONIC_VLLM_PORT`**, **`NUTONIC_VLLM_READY_SEC`**, **`OPENAI_API_KEY`** for remote OpenAI-compatible endpoints.

Narrative **clue composition** (before ``--clue-inject-max-chars``): **`NUTONIC_NARRATIVE_STREET_CLUE_CHARS`** (default ``1100``), **`NUTONIC_NARRATIVE_SAT_CLUE_CHARS`** (default ``750``) — sentence-aware excerpts from long VLM packs. **QA retry:** **`NUTONIC_NARRATIVE_QA_REGENERATE`** (default ``1``) runs one extra generation when heuristics flag brochure-style blurbs; set ``0`` to save GPU time.

**sv-lfm LFM-VL:** set **`LFM_VL_BACKEND=transformers`** (default in the entrypoint when unset) or **`LFM_VL_BACKEND=openai_compatible`** with **`LFM_OPENAI_BASE_URL`** / **`LFM_OPENAI_MODEL`** pointing at a vLLM (or compatible) server. Export these before `run_hf_hydration_full.py` so they are merged into the sv-lfm Job env (see ``inference_job_env.py``).

**Do not** use `tools/run_local_full_hydration.py` for production runs: it starts local `uvicorn` + LFM-VL and downloads model weights onto your laptop or workstation.

Use **`--dry-run`** to print the resolved spec without submitting.

### Liquid AI defaults and copy-paste test commands

Canonical Hub ids live in **`data/scripts/liquid_ai_defaults.py`** (text **LFM** for narrative / vLLM) and **`inference/lfm_vl_hint_service/.../liquid_hub_ids.py`** ( **LFM-VL** for Street View + satellite caption services). The **sv-lfm** entrypoint sets **`LFM_VL_MODEL_ID`** to the VL default when the Job env omits it.

**Build all three Job images** (from repo root, Docker logged in):

```bash
python tools/hf_jobs/build_and_push_images.py --namespace YOUR_DOCKERHUB_USER --tag 2026-04-18
```

Equivalent raw **Docker** invocations (repo-root context; use the helper above for safer staged contexts):

```bash
docker build -f tools/hf_jobs/Dockerfile.hydration -t YOUR_DOCKERHUB_USER/nutonic-hydration-sv-lfm:2026-04-18 .
docker build -f tools/hf_jobs/Dockerfile.hydration-llm -t YOUR_DOCKERHUB_USER/nutonic-hydration-llm:2026-04-18 .
docker build -f tools/hf_jobs/Dockerfile.hydration-tim -t YOUR_DOCKERHUB_USER/nutonic-hydration-tim:2026-04-18 .
docker push YOUR_DOCKERHUB_USER/nutonic-hydration-sv-lfm:2026-04-18
docker push YOUR_DOCKERHUB_USER/nutonic-hydration-llm:2026-04-18
docker push YOUR_DOCKERHUB_USER/nutonic-hydration-tim:2026-04-18
```

**Submit Jobs (or dry-run specs)** — load `.env` with `HF_API_WRITE`, `NUTONIC_HYDRATION_OUTPUT_DATASET`, map keys, then:

```bash
export NUTONIC_HYDRATION_SV_LFM_IMAGE=YOUR_DOCKERHUB_USER/nutonic-hydration-sv-lfm:2026-04-18
export NUTONIC_HYDRATION_LLM_IMAGE=YOUR_DOCKERHUB_USER/nutonic-hydration-llm:2026-04-18
export NUTONIC_HYDRATION_TIM_IMAGE=YOUR_DOCKERHUB_USER/nutonic-hydration-tim:2026-04-18
# Optional explicit pins (defaults match liquid_ai_defaults / liquid_hub_ids):
export NUTONIC_VLLM_MODEL=LiquidAI/LFM2.5-1.2B-Instruct
export LFM_VL_MODEL_ID=LiquidAI/LFM2.5-VL-450M

python tools/run_hf_hydration_full.py --content-version test-liquid-2026-04-18 \
  --poi-limit 5 --skip-geo-hints --narrative-llm-live \
  --dry-run-submit
```

Omit **`--dry-run-submit`** to actually submit and wait. For **LFM-VL via vLLM** on the sv-lfm Job instead of in-process transformers, export **`LFM_VL_BACKEND=openai_compatible`**, **`LFM_OPENAI_BASE_URL`**, and **`LFM_OPENAI_MODEL=LiquidAI/LFM2.5-VL-450M`** before the same command so **`inference_job_env`** forwards them.

## TerraTorch TiM on a Job

Local `uv run … nutonic_terramind_tim_local run` is unchanged. For **Hugging Face Jobs**, prefer **`Dockerfile.hydration-tim`** (batch + `huggingface_hub` upload) wired into `run_full_hydration.py` rather than the Space-oriented `inference/terramind_tim_local/Dockerfile`.

Default TiM job config in the image: `inference/terramind_tim_local/config.hf_job_geoguessr_poi12_first3.yaml` (`repo_root: /workspace`, STAC-only rows, **`terramind_v1_large_tim`**). Override with env `TIM_HF_CONFIG` or the orchestrator’s `--tim-config-in-container`.

Advanced: submit TiM alone with `submit_nutonic_hydration_job.py tim-s2` and a custom command if you outgrow the bundled YAML.

## Python API reference

- `huggingface_hub.run_job`: `image`, `command`, `env`, `secrets`, `flavor`, `timeout`, `labels`, `volumes`, `namespace`, `token`.
- `huggingface_hub.Volume`: `type="dataset"`, `source="NuTonic/poidata"`, `mount_path="/mnt/poidata"`, `revision`, `read_only=True`.

## Related

- `tools/hf_deploy/README.md` — **Spaces** (LFM, TiM, game server).
- `docs/scripts/SPEC-batch-streetview-hints.md` — batch contract.
- `inference/terramind_tim_local/README.md` — TiM local + Space.
