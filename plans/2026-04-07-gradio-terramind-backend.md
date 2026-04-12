# Plan: Python backend with FastAPI + Gradio, TerraMind (TiM + **generation**), leaderboard APIs, and Hugging Face persistence

**Date:** 2026-04-07  
**Scope:** Monorepo layout, reference server architecture, verification of technical claims, integration with existing rules (`05`, `06`, `10`).

**Multi-service and hosting options:** For a **central game API node** (**this plan: Python** thin **`server/`**) separate from **Python inference workers**, **HF Spaces without Gradio**, **Datasets + Jobs** as the cheap artifact plane, and **database** vs Dataset responsibilities, read **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`** and the **Topology** section in **`rules/12-python-gradio-terramind-server.md`**. (Hypothetical **non-Python** game API tier: **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §3**, ADR-only.)

**Canonical thin game server (auth, ranked, leaderboards, orchestration HTTP only):** **`plans/2026-04-07-game-server-thin-orchestrator.md`** — **`server/`** excludes **torch / terratorch / transformers**; Street View viewpoint math, LFM-VL, and TerraMind **TiM** / **`_generate`** run on **`inference/*`**, **`demos/terramind_space/`**, or **HF Jobs**.

**Normative production topology:** the thin **Python** **`server/`** calls **multiple separate Python services**—for example **`inference/streetview_pano_service/`**, **`inference/lfm_vl_hint_service/`**, **`inference/lfm_vl_satellite_caption_service/`**, **`inference/pro_materialization_service/`**, and **TerraMind** worker URL(s)—each as its **own** deployable (own container / Space / pool). That is the **default** NU:TONIC backend shape; see **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §0.1–§0.2**.

This document (**gradio-terramind-backend**) remains the **ML + Jobs + Dataset artifact** plan: **how** TerraTorch/TiM/`_generate` behave, **how** Hub artifacts are produced, and **how** work moves from **`data/scripts/`** validation into **discrete `inference/*`** services. It does **not** describe loading TerraTorch inside the public **`server/`** game API process.

**Standalone TiM + generation demo + POI tensor wiring (`poi_####`, Mapbox PNG, Sentinel COGs, Gradio.server):** Read **`plans/2026-04-07-tim-standalone-gradio-poi-dataset.md`** (IBM TiM + **`FULL_MODEL_REGISTRY`** input constraints vs 3-band shortcuts, dataset layout from `data/scripts/`, HF artifact schema).

---

## 1. Executive assessment

### 1.1 What is feasible

| Claim | Verdict | Notes |
|--------|---------|--------|
| Host **TerraMind TiM** inference in a **Python** process | **Yes** | Use **TerraTorch** **`BACKBONE_REGISTRY`** with **`*_tim`** models, per the [TerraMind model card](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-large) and [TerraTorch TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/). |
| Host **TerraMind full generation** (`*_generate`) in a **Python** process | **Yes** | Use **`FULL_MODEL_REGISTRY.build("terramind_v1_*_generate", …)`** with **`modalities`**, **`output_modalities`**, **`standardize=True`** per the [same guide — Generation](https://terrastackai.github.io/terratorch/stable/guide/terramind/). Heavier than TiM—prefer **Jobs** or **async** for large tiles. |
| Run **Thinking-in-Modalities (TiM)** on the server | **Yes, with strict preconditions** | TiM requires **`\_tim` model names**, **full pre-trained band sets** (no `bands` subset), and a **frozen** intermediate generator; see TiM section in the same TerraTorch guide. Violating any of these invalidates the pipeline. |
| Mount **Gradio `/ops`** beside **FastAPI** on the **thin `server/`** | **Yes** | **FastAPI** as the ASGI root; **`gr.mount_gradio_app(app, blocks, path="…")`** mounts operator UI on a subpath—**without** TerraTorch in that process. **NU:TONIC game clients** use **OpenAPI / REST** on FastAPI only; any framework-internal transports Gradio uses are **not** part of the player contract (`docs/GAME-ENGINE.md` §14). See [Gradio server mode / FastAPI mounting](https://www.gradio.app/main/guides/server-mode/). |
| **Gradio UI shows only the leaderboard** | **Yes** | Implement a minimal Blocks app (e.g. `gr.Dataframe` or HTML) fed from the **same read model** as `GET /api/v1/leaderboard`. No requirement to expose TiM or auth flows in Gradio. |
| **TypeScript** consumes leaderboard + auth via HTTP | **Yes** | TS uses **`fetch`/OpenAPI client** against FastAPI—not Gradio’s `/queue` API—unless you explicitly add a Gradio-based ops flow. |
| Persist **stable artifacts** on a **Hugging Face Dataset** repo | **Yes** | Use **`huggingface_hub`** (`HfApi.upload_file`, `upload_folder`) or the [**`hf` CLI**](https://huggingface.co/docs/huggingface_hub/en/guides/cli) (`hf upload … --repo-type=dataset`) as documented in the Hub CLI guide. |
| Use **Hugging Face Jobs** for batch artifact generation | **Conditional** | Jobs are appropriate for **offline, scheduled, GPU-on-Hub** workloads. Treat them as **optional**: product-critical paths should not depend on Jobs until you confirm quota, stability, and auth for your org. Official docs: [Hugging Face Jobs](https://huggingface.co/docs/huggingface_hub/en/guides/jobs) (requires login/token; rate limits may apply to unauthenticated doc/API access). |

### 1.2 What is *not* automatic or misleading

1. **“Gradio.server hosts everything”** — Misleading if read literally. **Gradio is not a substitute for a versioned REST contract.** The durable pattern is **FastAPI owns `/api/*`**, Gradio owns **`/ops` or `/admin`** (leaderboard view only).  
2. **`TerraMind-1.0-large`** — Correct for maximum quality; **wrong default for a reference server**. TerraTorch recommends **tiny/small for dev/edge**, **base** for most downstream tasks, **large** when compute allows ([model size guidance](https://terrastackai.github.io/terratorch/stable/guide/terramind/)).  
3. **TiM ≠ arbitrary “fill any missing modality”** — TiM imagines **tokenized modalities** (e.g. LULC) under documented constraints; it is not a generic “any hole in the JSON” filler. Product copy and APIs must align with **actual** `tim_modalities` and input specs.  
4. **TiM artifact storage on Hub** — TiM produces **high-dimensional internal tensors**; naïvely storing every forward pass will **explode** repo size and commit frequency. Persist only **schema-defined, downsized summaries** (metadata + optional fixed-size fields per OpenAPI), **partition** (e.g. Parquet by date/`map_id`), and enforce a **retention policy**.  
5. **HF Jobs “stability”** — Depend on Hub product limits, token, and org billing. **Primary persistence** should work with **`hf upload` / `HfApi`** from your long-running server or CI; Jobs are a **scale-out** path for heavy batch generation.

---

## 2. Script-first hydration, then thin `server/` + discrete `inference/*` services

### 2.1 Script-first cache and Dataset materialization (normative)

**Initially**, **specialized `data/scripts/`**, CI, and **HF Jobs** hydrate **versioned caches** (Mapbox stills, Street View hint packs, useful-hint tiers, POI imagery, TiM/`_generate` job outputs, Parquet shards) into **Datasets** and bundles the thin **`server/`** serves or syncs (`rules/13`, `docs/GAME-ENGINE.md` §9). That path is the **source of truth** for what the game ships offline and what **contracts** (tensor shapes, STAC windows, VLM frame layouts) are correct **before** any long-lived inference microservice exists.

### 2.2 Building `inference/*` from validated scripts (normative)

Each package under **`inference/*`** (and the **TerraMind** worker) should be **cut from the same logic** already proven in **`data/scripts/`** / Jobs drivers: same STAC queries, same Mapbox static URL policy, same band-stacking rules for TiM, same LFM-VL prompt boundaries—now exposed as **HTTP** with timeouts, auth, and deployable images. **Do not** add **`routes_inference.py`** with **in-process** TerraTorch inside **`server/`**; the game API process stays **`httpx`-only** toward workers (`plans/2026-04-07-game-server-thin-orchestrator.md`).

### 2.3 Repository layout (illustrative)

```text
server/                         # thin orchestrator — NO torch
inference/
  streetview_pano_service/      # Python — CPU; logic proven in scripts first
  lfm_vl_hint_service/          # Python — GPU Space
  lfm_vl_satellite_caption_service/
  pro_materialization_service/  # Python — CPU/IO
# TerraMind TiM / _generate: dedicated Python worker Space or demos/terramind_space — not inside server/
```

**Process model:** **`server/`** **FastAPI** awaits **`httpx`** responses from workers with **per-upstream budgets** so ranked **submit** never blocks on optional hint Spaces (**`rules/06`**, thin orchestrator plan). Each worker loads **only** its stack (LFM-VL, pano fetch, materialization, or TerraTorch on the TerraMind tier).

---

## 3. TerraMind TiM and **generation** service design

### 3.1 Model selection — **TiM** (`*_tim`)

- **Dev / CI:** `terramind_v1_tiny_tim` or `terramind_v1_small_tim`.  
- **Staging:** `terramind_v1_base_tim`.  
- **Prod (if justified):** `terramind_v1_large_tim` — weights from [Hugging Face `ibm-esa-geospatial/TerraMind-1.0-large`](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-large), Apache-2.0.

### 3.1b Model selection — **full generation** (`*_generate`)

- **Dev / CI:** `terramind_v1_small_generate` or `terramind_v1_tiny_generate` for smoke tests.  
- **IBM sizing note:** decoder cost dominates across sizes—**do not** assume `tiny` cuts wall time like a CNN; size is mainly **quality** ([guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/)).  
- **Prod:** gate **`_generate`** behind **feature flags**, **semaphores**, and **timeouts**; never block **ranked guess submit** on completion.

### 3.2 TiM pipeline (server-side)

1. **Build model:** `BACKBONE_REGISTRY.build("terramind_v1_*_tim", pretrained=True, modalities=[…], tim_modalities=[…])` per TerraTorch.  
2. **Inputs:** Dict of tensors per modality (e.g. `S2L2A`, `S1GRD`) with **correct shapes** (e.g. `B, 12, 224, 224` for S2L2A in model card examples).  
3. **Standardization:** Use **`standardize=True`** or documented pre-training stats where required (generation and TiM docs stress this).  
4. **Output:** Apply TerraTorch **`merge_method`** (`mean`, `max`, `concat`, `dict`, `None`) to TiM outputs and serialize **every imagined `tim_modality`** into **`tim_modality_outputs`** (OpenAPI-discriminated JSON per `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`). **`Coordinates`** → **`ai_lat` / `ai_lon`** for **`AiGuessStore`** / Dataset hydration (`docs/GAME-ENGINE.md` §12.2). Document the **contract** for downstream game logic (rule `06`).  
5. **Failure modes:** Timeouts, CUDA OOM, missing modality → HTTP 503 + structured error; client degrades per rule `06`.

### 3.2b Generation pipeline (server-side)

1. **Build model:** `FULL_MODEL_REGISTRY.build("terramind_v1_*_generate", pretrained=True, modalities=[…], output_modalities=[…], standardize=True, …)` per TerraTorch [Generation](https://terrastackai.github.io/terratorch/stable/guide/terramind/).  
2. **Inputs:** Same modality dict discipline as TiM—**full pre-trained bands** for each **raw** input modality declared.  
3. **Outputs:** Decoded rasters or thumbnails per **`output_modalities`**; persist **schema-bound** URIs + **`pipeline": "terramind_generate"`** in manifests (`rules/06`).  
4. **Failure modes:** Same as TiM; add **job queue** or **202 Accepted** for long tile jobs.

### 3.3 Relation to NU:TONIC game loop

Rule **`10-terramesh-vlm-progressive-zoom-game-engine.md`** separates **batch Street View + LFM-VL** assist text (bundle `streetview_hint_pack`, optional SCAN UI) from **TerraMesh/TerraMind** satellite pipelines. **TerraMind TiM** (on a **TerraMind worker**, **HF Job**, or **`demos/terramind_space/`**—never the thin **`server/`** game API process) should power:

- **Satellite / EO clue generation or distortion** via **TiM** and/or **`_generate`** decoded outputs (if product uses that path), and/or  
- **Server-side “Alien” flavor** using **TiM / generation outputs** and **retrieval only over allowed, disclosed features**; **cached AI-guess** lat/lon may come from **TiM `Coordinates`** in **`tim_modality_outputs`** (not free-text inference),

—not silent replacement of the entire geo game unless product explicitly merges flows.

---

## 4. Gradio: leaderboard-only UI + APIs for TS/KMP

### 4.1 Division of responsibility

| Surface | Technology | Consumer |
|---------|------------|----------|
| **Auth** (login, refresh, guest) | FastAPI + JWT or session | Kotlin `commonMain`, TS |
| **Leaderboard CRUD/read** | FastAPI + DB | Kotlin, TS |
| **TiM inference** | **Dedicated worker** Space / Job / `demos/terramind_space/` — **not** the thin `server/` process (`plans/2026-04-07-game-server-thin-orchestrator.md`) | Game server calls worker over **HTTP** only |
| **Operator leaderboard dashboard** | Gradio at e.g. `/ops` | Humans / ops only |

### 4.2 TypeScript integration

- **Do not** rely on Gradio for TS leaderboard unless you explicitly use **`@gradio/client`**—that couples you to Gradio’s queue and versioning.  
- **Do** publish **`openapi.yaml`** and generate a TS client (or hand-write `fetch` types).  
- Enable **CORS** for known web origins; keep **Gradio path** separate to avoid accidental CORS exposure of ops UI.

### 4.3 Gradio implementation sketch

- Load leaderboard rows from **`LeaderboardStore`** (same function as REST handler).  
- Optional: password or **shared secret** middleware on `/ops` (FastAPI `Depends` before mount, or Gradio `auth=`).  
- **No** game authentication UI in Gradio if product wants “leaderboard display only.”

---

## 5. Hugging Face dataset persistence

### 5.1 What to store (stable artifacts)

Examples aligned with rules **`06`** and **`10`**:

- **TiM artifact manifest (example fields):** `round_id`, `role`, `model_version`, `merge_method`, `tim_modalities`, **`tim_modality_outputs` JSON** (all modalities, capped), denormalized **`ai_lat` / `ai_lon`** when **`Coordinates`** ran, `created_at` (no raw patch grids in Hub by default).  
- **TiM run metadata:** input modality hash, `tim_modalities`, standardization version.  
- **Leaderboard snapshots** (optional): periodic Parquet for analytics—not source of truth if DB is primary.  
- **Eval / calibration** shards (research parity with `refs`): binned error summaries.

### 5.2 How to upload

- **From Python:** `huggingface_hub.HfApi` (preferred in app code).  
- **From shell / CI:** `hf auth login` then `hf upload <repo> <path> <path_in_repo> --repo-type=dataset` per [CLI upload docs](https://huggingface.co/docs/huggingface_hub/en/guides/cli).  
- **Large trees:** `hf upload-large-folder` for TB-scale; reference server likely uses **small Parquet append** strategy instead.

### 5.3 Versioning and concurrency

- Use **deterministic paths** e.g. `data/year=2026/month=04/part-000.parquet` or Hive-style.  
- **Avoid** one giant mutable file without merge strategy; prefer **append + compaction job** (optional HF Job).

---

## 6. Hugging Face Jobs — primary cache hydration path

**Jobs are the right place to “know what to generate” ahead of time:** enumerate `location_id`s (from the location pool / GeoGuessr-style HF datasets), run **TiM** to produce **schema-stable cache rows** and **precomputed `ai_guess_latlon`** (plus `ruleset_version`, `model_version`), then commit **Parquet shards** to a **private Dataset** via `hf upload` or `HfApi` inside the Job. See [Hugging Face Jobs](https://huggingface.co/docs/huggingface_hub/en/guides/jobs).

**The thin game API node** **then:**

1. **Syncs** Dataset revisions to local disk (startup, cron, or lazy with ETag).  
2. Serves **`GET /api/v1/cache/manifest`** and **`GET /api/v1/bundles/...`** (or equivalent) so **clients never touch the Hub** (`rules/13-client-cache-and-data-plane.md`).  
3. Resolves **`AI_GUESS`** from the **local row** on the hot path; optional **on-demand TiM** / ZeroGPU only when cache miss and policy allows.

**Do not depend on Jobs for:**

- **Blocking** a round that already started—only for **filling** the cache before locations go live.  
- **Authoritative leaderboard writes** (use DB + REST).

**Assessment:** Jobs + Dataset are **normative** for ML artifact hydration; **`hf` CLI / `HfApi`** remain the **portable** upload API inside Jobs and CI.

---

## 6b. ZeroGPU (Hugging Face Spaces) vs self-hosted GPU

- **[Spaces ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu)** uses **`@spaces.GPU`** (from the **`spaces`** package) to allocate GPU **per decorated function** in a **Gradio Space**—suitable for **demos**, **burst** TiM, or **offline** tools—not a full-time substitute for a **dedicated game-API or inference worker** GPU. See also [ZeroGPU AoT blog](https://huggingface.co/blog/zerogpu-aoti).  
- **Reference architecture:** **FastAPI game server** (CPU or light GPU) + **Jobs** for bulk hydration; optionally a **separate Space** with ZeroGPU for **on-demand** backfill when a cache key is missing.  
- Do **not** assume `@spaces.GPU` runs inside a vanilla `uvicorn` VPS unless you deploy on **Spaces**.

---

## 6c. Authentication (light default; JWT when required)

- **FastAPI** issues **JWT** access tokens (and optional refresh) when auth is enabled; validate with dependencies on protected routes. **Gradio `/ops`** uses the same app middleware or a separate ops token—Gradio is **not** the source of truth for JWT logic.  
- Default reference stack may use **anonymous `player_id`** until product enables auth (`rules/05`).

---

## 7. Python dependency and runtime requirements

- **Python 3.10+** (match TerraTorch).  
- **PyTorch** with **CUDA** matching your GPU; CPU-only for smoke tests.  
- **`terratorch`** (version supporting TiM and coordinate modalities if needed—see TerraTorch **1.1+** note for coordinates in docs).  
- **`fastapi`, `uvicorn[standard]`, `gradio`, `pydantic`** (v2).  
- **`huggingface_hub`, `datasets`** (if loading Hub datasets locally).  
- **DB:** `sqlite` for reference impl; `postgres` for multi-instance.  
- **Secrets:** `HF_TOKEN` for uploads; never commit; inject via env / secret store.

---

## 8. OpenAPI and ops alignment

- **`05-networking-leaderboard.md`:** OpenAPI co-located; versioned paths; role filters as query params.  
- **`06-server-vlm-tim-and-on-device-ml.md`:** timeouts and fallbacks for inference.  
- **Ops Gradio:** restrict **`/ops`** per deploy policy (`12`).

---

## 9. Phased delivery plan

| Phase | Deliverable | Exit criteria |
|-------|-------------|----------------|
| **P0** | FastAPI skeleton + OpenAPI + in-memory leaderboard + `GET` filters | TS/KMP can hydrate leaderboard from mock DB |
| **P1** | Optional **JWT** + persistent DB + Gradio read-only mount at `/ops` | Gradio shows same data as REST; auth matches `rules/05` |
| **P1b** | **`AiGuessStore`** + manifest: load Parquet shards from synced Dataset; `GET` cache manifest for clients | Round resolve reads AI coords from store; no Hub in client |
| **P2** | **TiM** (`*_tim`) on **worker Space or HF Job** — full-band validation + standardization | Integration test on one canned sample; thin **`server/`** skips this phase and uses **`TERRAMIND_WORKER_URL`** only |
| **P2b** | **`_generate`** on same worker + raster/thumbnail export path | Integration test; response labeled `terramind_generate` |
| **P3** | `hf_artifacts` upload of **TiM + generation** summary rows + manifest to Dataset repo | Artifact visible on Hub; reproducible from commit |
| **P4** (opt) | HF Job notebook/script for batch TiM / generation → Parquet | Runbook + cost estimate |

---

## 10. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| GPU OOM on large model | Default to base/small; request queue length 1; batch size 1 |
| TiM misuse (subset bands) | Server validates shape/bands; reject with 400 + doc link |
| Generation OOM / multi-minute runs | Default **small** weights; **single-flight** GPU lock; **async Jobs** for large tiles |
| Hub upload rate / size | Summarize TiM outputs in Parquet; batch commits; optional LFS; **compress** generation rasters |
| Gradio vs API drift | Single `LeaderboardStore` module; both call same function |
| Product confusion (TerraMind vs Street View) | Rule `10` + API docs state which rounds use EO vs VLM |
| **Cache miss** for `location_id` | Block location from live pool until Job row exists; or heuristic + audit flag; never hang resolve |

---

## 11. References (external)

- [ibm-esa-geospatial/TerraMind-1.0-large](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-large) — model card, backbone usage, outputs.  
- [TerraTorch TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/) — registry names, TiM, generation, merge methods.  
- [Hugging Face Hub CLI (`hf`)](https://huggingface.co/docs/huggingface_hub/en/guides/cli) — upload, auth, datasets.  
- [Gradio server mode / FastAPI](https://www.gradio.app/main/guides/server-mode/) — mounting and shared ASGI app.  
- [Hugging Face Jobs](https://huggingface.co/docs/huggingface_hub/en/guides/jobs) — batch hydration on Hub.  
- [Spaces ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu) — `@spaces.GPU` for Spaces deployments.

---

## 12. Next actions for implementers

1. Add `server/` with `pyproject.toml` and **OpenAPI-first** FastAPI app.  
2. Implement **`LeaderboardStore`** and mount **Gradio leaderboard-only** UI.  
3. Land **TerraMind TiM** and optional **`_generate`** on a **GPU worker** or **HF Job** path—**not** inside the thin **`server/`** process; see **`plans/2026-04-07-game-server-thin-orchestrator.md`**.  
4. Define **Parquet schema** for Hub artifacts and a **single** upload code path (`HfApi`).  
5. Update Kotlin **`commonMain`** DTOs to match OpenAPI (rule `05`).  
6. Implement **Dataset sync + `AiGuessStore`** and document **Parquet schema** for precomputed AI rows (`rules/GAME-ENGINE.md` §12.2, `rules/13`).
