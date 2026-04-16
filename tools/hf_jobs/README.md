# NU:TONIC — Hugging Face Jobs (hydration)

This folder documents **Hugging Face Jobs** for **GPU** cache hydration alongside **local** tooling (`tools/batch_streetview_hints.py`, `inference/terramind_tim_local`, `tools/run_geoguessr_hydration_local.py`). **Spaces** remain supported via `tools/hf_deploy/`; Jobs are for **one-shot / scheduled** heavy batches with **dataset volumes**.

## Prerequisites

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
python tools/hf_jobs/build_and_push_images.py --namespace YOUR_DOCKERHUB_USER --tag 2026-04-16
```

Builds and pushes three tags:

- `nutonic-hydration-sv-lfm` — `Dockerfile.hydration` (Street View + LFM-VL + `data/scripts` pipeline).
- `nutonic-hydration-tim` — `Dockerfile.hydration-tim` (TerraMind TiM STAC batch + Hub upload via `entrypoint_tim_hf.py`).
- `nutonic-hydration-llm` — `Dockerfile.hydration-llm` (CPU narrative sidecars).

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

For a **small slice** (e.g. first five ``geoguessr_poi_12`` POIs), pass ``--poi-limit 5`` and usually ``--skip-geo-hints`` on ``run_full_hydration.py`` / ``run_hf_hydration_full.py`` so Jobs set ``NUTONIC_POI_LIMIT`` and skip ``build_poi_geo_context`` when Natural Earth geometry fails on some rows. TiM automatically uses ``config.hf_job_geoguessr_poi12_first5.yaml`` when the limit is 5 (unless you override ``--tim-config-in-container``).

Use `--dry-run-submit` to print resolved Job specs without calling the Hub. Use `--skip-download` if you only want Hub-side artifacts.

**Do not** use `tools/run_local_full_hydration.py` for production runs: it starts local `uvicorn` + LFM-VL and downloads model weights onto your laptop or workstation.

Use **`--dry-run`** to print the resolved spec without submitting.

## TerraTorch TiM on a Job

Local `uv run … nutonic_terramind_tim_local run` is unchanged. For **Hugging Face Jobs**, prefer **`Dockerfile.hydration-tim`** (batch + `huggingface_hub` upload) wired into `run_full_hydration.py` rather than the Space-oriented `inference/terramind_tim_local/Dockerfile`.

Default TiM job config in the image: `inference/terramind_tim_local/config.hf_job_geoguessr_poi12_first3.yaml` (`repo_root: /workspace`, STAC-only rows). Override with env `TIM_HF_CONFIG` or the orchestrator’s `--tim-config-in-container`.

Advanced: submit TiM alone with `submit_nutonic_hydration_job.py tim-s2` and a custom command if you outgrow the bundled YAML.

## Python API reference

- `huggingface_hub.run_job`: `image`, `command`, `env`, `secrets`, `flavor`, `timeout`, `labels`, `volumes`, `namespace`, `token`.
- `huggingface_hub.Volume`: `type="dataset"`, `source="NuTonic/poidata"`, `mount_path="/mnt/poidata"`, `revision`, `read_only=True`.

## Related

- `tools/hf_deploy/README.md` — **Spaces** (LFM, TiM, game server).
- `docs/scripts/SPEC-batch-streetview-hints.md` — batch contract.
- `inference/terramind_tim_local/README.md` — TiM local + Space.
