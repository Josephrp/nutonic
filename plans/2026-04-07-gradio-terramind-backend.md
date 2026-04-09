# Plan: Python backend with FastAPI + Gradio, TerraMind (TiM), leaderboard APIs, and Hugging Face persistence

**Date:** 2026-04-07  
**Scope:** Monorepo layout, reference server architecture, verification of technical claims, integration with existing rules (`05`, `06`, `10`).

---

## 1. Executive assessment

### 1.1 What is feasible

| Claim | Verdict | Notes |
|--------|---------|--------|
| Host **TerraMind** inference in a **Python** process | **Yes** | Use **TerraTorch** `BACKBONE_REGISTRY` / `FULL_MODEL_REGISTRY` as in the [TerraMind model card](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-large) and [TerraTorch TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/). |
| Run **Thinking-in-Modalities (TiM)** on the server | **Yes, with strict preconditions** | TiM requires **`\_tim` model names**, **full pre-trained band sets** (no `bands` subset), and a **frozen** intermediate generator; see TiM section in the same TerraTorch guide. Violating any of these invalidates the pipeline. |
| Use **Gradio** in the same process as game/admin APIs | **Yes** | **FastAPI** as the ASGI root; **`gr.mount_gradio_app(app, blocks, path="…")`** mounts the Gradio UI on a subpath. Custom REST/WebSocket routes remain on FastAPI for **TypeScript** and **Kotlin** clients. See [Gradio server mode / FastAPI mounting](https://www.gradio.app/main/guides/server-mode/). |
| **Gradio UI shows only the leaderboard** | **Yes** | Implement a minimal Blocks app (e.g. `gr.Dataframe` or HTML) fed from the **same read model** as `GET /api/v1/leaderboard`. No requirement to expose TiM or auth flows in Gradio. |
| **TypeScript** consumes leaderboard + auth via HTTP | **Yes** | TS uses **`fetch`/OpenAPI client** against FastAPI—not Gradio’s `/queue` API—unless you explicitly add a Gradio-based ops flow. |
| Persist **stable artifacts** on a **Hugging Face Dataset** repo | **Yes** | Use **`huggingface_hub`** (`HfApi.upload_file`, `upload_folder`) or the [**`hf` CLI**](https://huggingface.co/docs/huggingface_hub/en/guides/cli) (`hf upload … --repo-type=dataset`) as documented in the Hub CLI guide. |
| Use **Hugging Face Jobs** for batch artifact generation | **Conditional** | Jobs are appropriate for **offline, scheduled, GPU-on-Hub** workloads. Treat them as **optional**: product-critical paths should not depend on Jobs until you confirm quota, stability, and auth for your org. Official docs: [Hugging Face Jobs](https://huggingface.co/docs/huggingface_hub/en/guides/jobs) (requires login/token; rate limits may apply to unauthenticated doc/API access). |

### 1.2 What is *not* automatic or misleading

1. **“Gradio.server hosts everything”** — Misleading if read literally. **Gradio is not a substitute for a versioned REST contract.** The durable pattern is **FastAPI owns `/api/*`**, Gradio owns **`/ops` or `/admin`** (leaderboard view only).  
2. **`TerraMind-1.0-large`** — Correct for maximum quality; **wrong default for a reference server**. TerraTorch recommends **tiny/small for dev/edge**, **base** for most downstream tasks, **large** when compute allows ([model size guidance](https://terrastackai.github.io/terratorch/stable/guide/terramind/)).  
3. **TiM ≠ arbitrary “fill any missing modality”** — TiM imagines **tokenized modalities** (e.g. LULC) under documented constraints; it is not a generic “any hole in the JSON” filler. Product copy and APIs must align with **actual** `tim_modalities` and input specs.  
4. **Embedding storage on Hub** — Backbone outputs are **high-dimensional patch sequences**; naïvely storing every inference will **explode** repo size and commit frequency. You need a **schema**, **downsampling** (e.g. pooled vector + metadata), **partitioning** (Parquet by date/match), and **retention policy**.  
5. **HF Jobs “stability”** — Depend on Hub product limits, token, and org billing. **Primary persistence** should work with **`hf upload` / `HfApi`** from your long-running server or CI; Jobs are a **scale-out** path for heavy batch generation.

---

## 2. Target architecture (monorepo slice)

Recommended layout under repo root (names illustrative):

```text
nutonic/                    # existing KMP app
server/
  pyproject.toml            # uv/poetry; pins torch, terratorch, gradio, fastapi, …
  src/nutonic_server/
    main.py                 # FastAPI app + mount_gradio_app
    api/
      routes_auth.py
      routes_leaderboard.py
      routes_inference.py   # TiM / embed (internal or token-gated)
    services/
      terramind_service.py  # lazy load, device, merge_method, TiM forward
      leaderboard_store.py  # DB or file-backed + Hub sync
      hf_artifacts.py       # upload pooled embeddings, manifests, eval shards
    gradio_app/
      leaderboard_only.py   # read-only UI
    models/                 # Pydantic / dataclass DTOs matching OpenAPI
  tests/
docs/
  openapi.yaml              # contract-first (rule 05)
plans/                      # this file
rules/
```

**Process model:** one **GPU worker** (or CPU with tiny model for CI) loads TerraTorch once; **FastAPI** handles concurrency with a **single-flight or small semaphore** around GPU forward to avoid OOM.

---

## 3. TerraMind + TiM service design

### 3.1 Model selection

- **Dev / CI:** `terramind_v1_tiny` or `terramind_v1_small` (+ `_tim` if testing TiM).  
- **Staging:** `terramind_v1_base` / `terramind_v1_base_tim`.  
- **Prod (if justified):** `terramind_v1_large` — weights from [Hugging Face `ibm-esa-geospatial/TerraMind-1.0-large`](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-large), Apache-2.0.

### 3.2 TiM pipeline (server-side)

1. **Build model:** `BACKBONE_REGISTRY.build("terramind_v1_*_tim", pretrained=True, modalities=[…], tim_modalities=[…])` per TerraTorch.  
2. **Inputs:** Dict of tensors per modality (e.g. `S2L2A`, `S1GRD`) with **correct shapes** (e.g. `B, 12, 224, 224` for S2L2A in model card examples).  
3. **Standardization:** Use **`standardize=True`** or documented pre-training stats where required (generation and TiM docs stress this).  
4. **Output:** Patch/token embeddings; apply **`merge_method`** (`mean`, `max`, `concat`, `dict`, `None`) consistently and document the **contract** for downstream game logic (rule `06`).  
5. **Failure modes:** Timeouts, CUDA OOM, missing modality → HTTP 503 + structured error; client degrades per rule `06`.

### 3.3 Relation to NU:TONIC game loop

Rule **`10-terramesh-vlm-progressive-zoom-game-engine.md`** separates **Street View / VLM** gameplay from **TerraMesh/TerraMind** satellite pipelines. **TerraMind on this server** should power:

- **Satellite / EO clue generation or distortion** (if product uses that path), and/or  
- **Server-side “Alien” policy** using embeddings similarity over **allowed** features,

—not silent replacement of the entire geo game unless product explicitly merges flows.

---

## 4. Gradio: leaderboard-only UI + APIs for TS/KMP

### 4.1 Division of responsibility

| Surface | Technology | Consumer |
|---------|------------|----------|
| **Auth** (login, refresh, guest) | FastAPI + JWT or session | Kotlin `commonMain`, TS |
| **Leaderboard CRUD/read** | FastAPI + DB | Kotlin, TS |
| **TiM / embed inference** | FastAPI (internal routes or API key) | Server-driven game loop; not mobile |
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

- **Pooled embedding manifest:** `round_id`, `role`, `model_version`, `merge_method`, `vector` (fixed dim), `created_at` (no raw patch grids unless needed).  
- **TiM run metadata:** input modality hash, `tim_modalities`, standardization version.  
- **Leaderboard snapshots** (optional): periodic Parquet for analytics—not source of truth if DB is primary.  
- **Eval / calibration** shards (research parity with `refs`): binned error summaries, not PII.

### 5.2 How to upload

- **From Python:** `huggingface_hub.HfApi` (preferred in app code).  
- **From shell / CI:** `hf auth login` then `hf upload <repo> <path> <path_in_repo> --repo-type=dataset` per [CLI upload docs](https://huggingface.co/docs/huggingface_hub/en/guides/cli).  
- **Large trees:** `hf upload-large-folder` for TB-scale; reference server likely uses **small Parquet append** strategy instead.

### 5.3 Versioning and concurrency

- Use **deterministic paths** e.g. `data/year=2026/month=04/part-000.parquet` or Hive-style.  
- **Avoid** one giant mutable file without merge strategy; prefer **append + compaction job** (optional HF Job).

---

## 6. Hugging Face Jobs — primary cache hydration path

**Jobs are the right place to “know what to generate” ahead of time:** enumerate `location_id`s (from the location pool / GeoGuessr-style HF datasets), run **TiM / backbone / policy** to produce **pooled embeddings** and **precomputed `ai_guess_latlon`** (plus `ruleset_version`, `model_version`), then commit **Parquet shards** to a **private Dataset** via `hf upload` or `HfApi` inside the Job. See [Hugging Face Jobs](https://huggingface.co/docs/huggingface_hub/en/guides/jobs).

**The match server then:**

1. **Syncs** Dataset revisions to local disk (startup, cron, or lazy with ETag).  
2. Serves **`GET /api/v1/cache/manifest`** and **`GET /api/v1/bundles/...`** (or equivalent) so **clients never touch the Hub** (`rules/13-client-cache-and-data-plane.md`).  
3. Resolves **`AI_GUESS`** from the **local row** on the hot path; optional **live** TerraTorch/ZeroGPU only when cache miss and policy allows.

**Do not depend on Jobs for:**

- **Blocking** a round that already started—only for **filling** the cache before locations go live.  
- **Authoritative leaderboard writes** (use DB + REST).

**Assessment:** Jobs + Dataset are **normative** for ML artifact hydration; **`hf` CLI / `HfApi`** remain the **portable** upload API inside Jobs and CI.

---

## 6b. ZeroGPU (Hugging Face Spaces) vs self-hosted GPU

- **[Spaces ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu)** uses **`@spaces.GPU`** (from the **`spaces`** package) to allocate GPU **per decorated function** in a **Gradio Space**—suitable for **demos**, **burst** TiM, or **offline** tools—not a full-time substitute for a dedicated match-server GPU. See also [ZeroGPU AoT blog](https://huggingface.co/blog/zerogpu-aoti).  
- **Reference architecture:** **FastAPI match server** (CPU or light GPU) + **Jobs** for bulk hydration; optionally a **separate Space** with ZeroGPU for **on-demand** backfill when a cache key is missing.  
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

## 8. Security and contract (rules alignment)

- **`05-networking-leaderboard.md`:** OpenAPI co-located; versioned paths; role filters as query params.  
- **`06-server-embedding-and-ai.md`:** No secrets in clients; timeouts and fallbacks for inference.  
- **Ops Gradio:** Not a public admin surface without **auth**; prefer VPN or SSO proxy in production.

---

## 9. Phased delivery plan

| Phase | Deliverable | Exit criteria |
|-------|-------------|----------------|
| **P0** | FastAPI skeleton + OpenAPI + in-memory leaderboard + `GET` filters | TS/KMP can hydrate leaderboard from mock DB |
| **P1** | Optional **JWT** + persistent DB + Gradio read-only mount at `/ops` | Gradio shows same data as REST; auth matches `rules/05` |
| **P1b** | **`AiGuessStore`** + manifest: load Parquet shards from synced Dataset; `GET` cache manifest for clients | Round resolve reads AI coords from store; no Hub in client |
| **P2** | TerraTorch backbone **without** TiM (tiny model) + `POST /internal/embed` | Returns fixed-dim vector; contract documented |
| **P3** | **TiM** path (`*_tim`) + validation of full-band inputs + standardization | Integration test on one canned TerraMesh-style sample |
| **P4** | `hf_artifacts` upload of pooled vectors + manifest to Dataset repo | Artifact visible on Hub; reproducible from commit |
| **P5** (opt) | HF Job notebook/script for batch TiM → Parquet | Runbook + cost estimate |

---

## 10. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| GPU OOM on large model | Default to base/small; request queue length 1; batch size 1 |
| TiM misuse (subset bands) | Server validates shape/bands; reject with 400 + doc link |
| Hub upload rate / size | Pool embeddings; batch Parquet; optional LFS |
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
3. Land **TerraTorch** inference behind a **feature flag** and **model config** (YAML or env).  
4. Define **Parquet schema** for Hub artifacts and a **single** upload code path (`HfApi`).  
5. Update Kotlin **`commonMain`** DTOs to match OpenAPI (rule `05`).  
6. Implement **Dataset sync + `AiGuessStore`** and document **Parquet schema** for precomputed AI rows (`rules/GAME-ENGINE.md` §12.2, `rules/13`).
