# Server and inference architecture — implications and decision points

This document captures **real implications** of splitting the **game API plane** from **ML inference**, hosting on **Hugging Face** without assuming **one Python process** hosts both the public game API and heavy ML, and **database** placement. **Re-implementing the thin game API in a non-Python runtime** remains a **hypothetical / ADR-level** option (see §3); it is **not** part of this repository’s **current** delivery plan.

It complements **`rules/12-python-gradio-terramind-server.md`** (thin **`server/`** + **`httpx`** to workers, Gradio **`/ops`** on the game tier) and **`plans/2026-04-07-gradio-terramind-backend.md`** (TerraMind / Jobs / Dataset behavior, **§2** production layout: **script-first hydration** → discrete **`inference/*`** services).

**Implementation plan (this repo — disambiguated):** The production **`server/`** thin orchestrator is **Python** (FastAPI + **`httpx`** to **`inference/*`**, OpenAPI/Pydantic validation, ranked + JWT + idempotency in one codebase per **`plans/2026-04-07-game-server-thin-orchestrator.md`**). **Inference workers** under **`inference/*`** are also **Python** in this plan. That avoids **dual-runtime drift** (duplicate clamp / ticket / forfeit logic in two languages) on the default path.

**Client invariant (unchanged):** Kotlin (and any TS shell) speak only to **documented HTTP APIs** (OpenAPI). They do not import PyTorch, call Gradio `/queue` for core gameplay, use a **player-facing** push/stream transport for core loops, or hold Hub tokens (`rules/13-client-cache-and-data-plane.md`, `docs/GAME-ENGINE.md` §14).

**Standalone TerraMind demo (optional):** The planned **`demos/terramind_space/`** package (see **`plans/2026-04-07-terramind-gradio-spaces-comprehensive-demo.md`**) is an **independent** Gradio **[server-mode](https://www.gradio.app/main/guides/server-mode/)** + Hugging Face **Spaces / ZeroGPU** showcase. It is **not** the game API tier and does not change the client invariants above; it documents inference-hosting patterns (GPU decorators, manual Hub sync from GitHub Actions) for operators and ML engineers.

**Default SCAN data path:** **Unranked** maps, **Mapbox downscaled clue stills**, and other **read-mostly** game payloads are produced by **scripts / HF Jobs → Datasets** and shipped as **bundles** or synced to **CDN / object storage**—**not** generated on the player hot path (`docs/GAME-ENGINE.md` §9, `rules/13-client-cache-and-data-plane.md`). **Live `server/` work** is **primarily** **`POST` POIs** (user-submitted map proposals when shipped), **ranked** round lifecycle (**server-held secrets + `guess_lat`/`guess_lon` submit**), **JWT/session**, and **thin PRO job orchestration** (status + **signed URLs**)—**not** hosting Sentinel downloads or other **heavy data-plane** pipelines (those stay in **`inference/*`** and TerraMind workers per **`plans/2026-04-07-game-server-thin-orchestrator.md`** §0.1).

**Optional inference plane (labs / PRO / EO tooling):** **`inference/streetview_pano_service/`**, **`inference/lfm_vl_hint_service/`**, **`inference/lfm_vl_satellite_caption_service/`**, and **`inference/pro_materialization_service/`** stay **separate** from **`server/`** when used; see **`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`**, **`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`**, and **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`**.

**Current CI deployment reality (2026-04):** **`.github/workflows/huggingface-deploy.yml`** deploys the required long-lived Docker Spaces after targeted pytest:

| Target | Source | Space repo | Notes |
|--------|--------|------------|-------|
| Game server | `server/` | `NuTonic/nutonic-game-server` | CPU Space, feature flags default off through `tools/hf_deploy/profiles/game_server.yaml`. |
| PRO materialization | `inference/pro_materialization_service/` | `NuTonic/nutonic-pro-materialization` | CPU Space, inbound HMAC required by `tools/hf_deploy/profiles/pro_materialization.yaml`. |
| Street View pano | `inference/streetview_pano_service/` | `Tonic/nutonic-streetview-pano` | CPU Space, stub provider by default; optional Google key for real imagery. |
| LFM-VL hints / PRO brief fusion | `inference/lfm_vl_hint_service/` | `Tonic/nutonic-lfm-vl-streetview` | ZeroGPU profile with `LFM_VL_BACKEND=transformers` and Gradio mounted. |
| LFM-VL satellite captions | `inference/lfm_vl_satellite_caption_service/` | `Tonic/nutonic-lfm-vl-satellite` | ZeroGPU profile with `LFM_SATELLITE_BACKEND=transformers`. |
| TerraMind TiM | `inference/terramind_tim_local/` | `Tonic/nutonic-terramind-tim` | ZeroGPU profile for the Space API. |

**0. Vocabulary — thin game `server/` + workers (no TerraTorch in `server/`).** **Shipped public game API** `server/` is the **thin orchestrator** in **`plans/2026-04-07-game-server-thin-orchestrator.md`**: **no** `torch` / **`terratorch`** in that deployable’s dependencies; **`httpx`** (or equivalent) to **`inference/*`**, **`PRO_MATERIALIZATION_SERVICE_URL`**, and **`TERRAMIND_*`** workers. **`rules/12-python-gradio-terramind-server.md`** describes how **FastAPI** owns **`/api/*`** and how **Gradio** may mount at **`/ops`** on **that same thin process** for operators—**without** loading TerraTorch in `server/`. Heavy ML lives only in **`inference/*`**, **TerraMind workers**, **HF Jobs**, or **`demos/terramind_space/`**.

**0.1 Normative shape — scripts first, then discrete Python services.** Cached SCAN data, PRO materialization inputs, and other **read-mostly** payloads are **hydrated first** with **specialized `data/scripts/`**, CI, and **HF Jobs → Datasets** (`docs/GAME-ENGINE.md` §9, **`plans/2026-04-07-gradio-terramind-backend.md` §2**). Each **`inference/*`** HTTP service (and the **TerraMind** worker) is **introduced only where validated script logic** must become a **long-lived, addressable deployable** (batch refresh, PRO on-demand paths, ops)—never by loading TerraTorch inside the **`server/`** game API process.

**0.2 Runtime topology — one thin Python game `server/`, many Python workers.** The **running** system is:

- **One thin Python game `server/`** (public OpenAPI, auth, ranked tickets, DB, manifests, rate limits)—**no** TerraTorch in its dependency closure.
- **Several separate Python services** (each its own process, image, or Hugging Face Space), called **only** from the thin Python server over **HTTP** (or internal gRPC), for example: **`inference/streetview_pano_service/`**, **`inference/lfm_vl_hint_service/`**, **`inference/lfm_vl_satellite_caption_service/`**, **`inference/pro_materialization_service/`**, and one or more **TerraMind** worker URLs (**`TERRAMIND_TIM_URL`**, **`TERRAMIND_GENERATE_URL`**, or a collapsed **`TERRAMIND_WORKER_URL`**). Workers **do not** need to co-locate with each other; each scales and fails independently.

**Footgun this section removes:** loading **TerraTorch / TiM / `_generate`** inside the **`server/`** process that also serves **ranked** and **JWT**—which couples **GPU OOM** and CUDA hangs to **game API uptime**.

---

## 1. Why separate the game server from inference

| Concern | Single process (FastAPI + TerraTorch in one container) | Split: **game orchestrator** + **inference worker(s)** |
|--------|--------------------------------------------------------|--------------------------------------------------------|
| **Scaling** | GPU memory and Python GIL contention couple unrelated traffic | Scale **stateless inference** horizontally; keep **ranked secrets, JWT, DB transactions** on a small, optimizable game tier |
| **Language / runtime** | Everything is Python | **This plan:** thin game **`server/`** + **`inference/*`** workers are **Python**; split reduces GIL/GPU coupling vs one fused process, not language diversity on the API tier. **Other** game-node languages are **ADR-only** (§3). |
| **Failure isolation** | TiM / **`_generate`** OOM or CUDA hang can take down leaderboard + auth | Inference timeouts return **503**; game tier continues serving reads, ranked ticket validation, static manifests |
| **Cost on HF** | One fat Space with GPU is expensive idle | **CPU-only** game Space + **ZeroGPU** or **ephemeral** inference Spaces, or **Jobs-only** cache with no live GPU hot path |
| **Deploy cadence** | Model updates force game redeploy | Bump **inference image** independently; game tier changes only when API or policy changes |

**Implication:** **FastAPI** + **`mount_gradio_app`(`/ops`)** on the **thin** `server/` is **one Python process for the game API + operator UI only**—still **no** TerraTorch there. Heavy ML stays in **`inference/*`** and TerraMind workers.

---

## 2. Topology — thin orchestrator + inference workers

### 2.1 Default production

- **Game / API node (“central node”)** — **Python** thin **`server/`** in this plan. Owns: OpenAPI routes clients call, **optional** community leaderboard ingest, **ranked** `round_ticket` lifecycle, JWT validation for gated writes, **manifest URLs** for clients, **orchestration** (call workers with timeouts). Does **not** need to load TerraTorch if workers handle all GPU paths.
- **Inference workers** — **Typically multiple** **Python** deployables (each optional per feature flag): FastAPI microservices under **`inference/*`**, Celery workers, **HF Spaces** exposing `POST /v1/...`, and/or a **dedicated TerraMind GPU worker**. They are **peers of each other**, not submodules inside `server/`; the thin server **fans out** with per-upstream timeouts. May use **Gradio** internally for debugging only; **players** still use the game node’s REST contract. The current CI deploy path covers the Space-backed workers listed above; new long-lived workers should follow the same profile/template/smoke pattern.
- **Internal transport** — HTTP/gRPC from game node → workers; or **queue** (Redis, SQS) for async batch—**not** part of the mobile OpenAPI doc unless product exposes the same to clients (usually **no**).

**Implication:** Document **two** OpenAPI surfaces if needed: **public** (`/api/v1/...` for clients) and **internal** (`/internal/v1/infer` between your own services), or keep internal undocumented but versioned in repo.

---

## 3. Game server language — **Python** for this implementation plan

**Normative (this repo):** The thin **`server/`** is **Python** (same family as **`inference/*`** and the **`rules/12`** reference stack). **Ranked** ticket lifecycle, **forfeit** transitions, **idempotency**, coordinate **clamps**, JWT gates, and OpenAPI request validation are implemented **once** on that tier. Kotlin **`commonMain`** DTOs stay **aligned with OpenAPI**; they do **not** re-implement server trust rules.

**Requirement (any game node, including this Python one):** Behavior matches **`rules/05-networking-leaderboard.md`**, **`docs/RANKED-MODE.md`**, and the published contract.

**Hypothetical alternative (ADR only, not this plan):** A **non-Python** game node could still match the same REST paths and schemas, add **timeouts** / **circuit breakers** toward Python workers, and keep **strong consistency** for ranked state—but it reintroduces **dual-runtime validation** risk (two hand-written implementations of clamps, idempotency keys, and forfeit state unless everything is **generated** from one OpenAPI source or a **single-language BFF** owns mutations).

**Decision for NU:TONIC here:** Ship and evolve the **Python** thin orchestrator in **`server/`**; revisit another language only with an explicit **ADR** and a **contract parity** strategy (tests/codegen), not as a silent parallel rewrite.

---

## 4. Hugging Face without “one Gradio app”

HF is a **hosting and artifact** platform, not “Gradio only.”

| Pattern | Cost profile (rough) | Fits |
|---------|----------------------|------|
| **Dataset repos** | Storage + bandwidth; no always-on compute | Versioned **Parquet manifests**, TerraMesh cache rows, **TiM** / **`_generate`** job outputs (schema-defined), **static POI bundles** |
| **HF Jobs** | Pay per job / GPU minute | **Batch** work—feeds Datasets; see `rules/12` |
| **Space — Docker / custom** | Free tier sleep; paid for always-on | **Game API** (CPU) or **inference** (GPU) **without** Gradio |
| **Space — Gradio** | Same | **Ops** UI or demos; ZeroGPU decorator model |
| **ZeroGPU** | GPU only while request runs | **Burst** inference; **not** a substitute for 24/7 low-latency ranked adjudication unless you design for cold starts |

**Implication:** **Datasets** = heavy artifacts; **Jobs** = hydration; **small CPU** game node reads snapshots; **optional** GPU Space for burst inference; otherwise **cache-only** hot path per `rules/06-server-vlm-tim-and-on-device-ml.md`.

---

## 5. Multiple Gradio (or Python) servers behind the central node

### 5.1 Cached bundle sync (default game reads)

The **game server** (or static CDN in front of it) serves **`GET` manifests / bundle bytes** produced offline. **No** inference call is required to play **SCAN** rounds: the client loads the **Mapbox still** and catalog slice from the bundle (`docs/GAME-ENGINE.md` §9).

### 5.2 Optional inference workers (PRO, TerraMind, lab)

| Env (illustrative) | Service | Notes |
|--------------------|---------|--------|
| `LFM_VL_SATELLITE_CAPTION_SERVICE_URL` | `inference/lfm_vl_satellite_caption_service` | Optional **GPU** service for **Intel** / EO lab copy |
| `STREETVIEW_PANO_SERVICE_URL` / `LFM_VL_HINT_SERVICE_URL` | `inference/*` | Optional **batch / ops** tooling—not the default SCAN player clue path |

**Implications:** **Per-dependency timeouts** and **bulkheads**; **consistent error shape** (503 + JSON); **no client-visible fan-out** (one `baseUrl`).

**Decision point:** Keep **heavy** work in **Jobs → Dataset → bundle**; use live workers for **PRO** and **TerraMind** only when OpenAPI defines those routes.

### 5.3 PRO coordinate materialization (Mapbox + Sentinel-2; not the game server process)

| Env (illustrative) | Service | Notes |
|--------------------|---------|--------|
| `PRO_MATERIALIZATION_SERVICE_URL` | **`inference/pro_materialization_service/`** (or equivalent repo path) | **CPU / IO**: STAC + Mapbox static fetch, **reproject / downsample** to **`vlm_image_set`** sizes for on-device VLM **and** to TerraMind **TiM** / **`_generate`** input contracts; **no** ranked secrets |
| `TERRAMIND_TIM_URL` / `TERRAMIND_GENERATE_URL` (or `TERRAMIND_WORKER_URL`) | TerraMind worker Space / process | **GPU**: consumes **materialization-produced** handles (NPZ URLs, paths)—**not** raw game-server buffers; returns **`tim_modality_outputs`** (all configured **`tim_modalities`**, schema-capped — incl. **`Coordinates` → WGS84**). **`ProVisionBundle`** **heavy bytes** (images/archives) are **authored and stored** by the materialization tier and/or object storage; the **game server** attaches **metadata + signed download URLs** (or **redirects**) for the Kotlin client. **`AiGuessStore` / `ai_lat` / `ai_lon`** updates use the **same** `Coordinates` shape **only** when persisting **`map_id`** clue or Job rows — **not** for every ad-hoc PRO job (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §1.1.1, `docs/GAME-ENGINE.md` §12.2) |

**Persistence reminder:** **`PRO_MATERIALIZATION_SERVICE_URL`** and the TerraMind worker are on the **analyst / materialization** path. **`AiGuessStore`** is on the **published-round / SCAN `AI_GUESS`** path. Treating every PRO **`Coordinates`** as a catalog row is an **implementation error** with trust, moderation, and cost implications — **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §1.1.1**.

The **thin game server** validates JWT, rate-limits **`POST .../pro/jobs`**, and runs **control-plane** orchestration only: **small JSON** to materialization and TerraMind workers, **job status** in its DB, and **client-visible** responses that carry **`bundle_download_url`** / **redirects**—it **does not** download Sentinel assets, **does not** re-stream COGs or NPZ intermediates through its process, and **does not** run Sentinel COG math or TerraTorch. See **`plans/2026-04-07-game-server-thin-orchestrator.md`** §0.1 and §1.6.

---

## 6. Database in context

| Data | Typical store | Notes |
|------|---------------|--------|
| **Optional community leaderboard** | Postgres / SQLite | **`rules/05`**, idempotency keys |
| **Ranked rounds** | Postgres + transactions | Verified scores |
| **Artifact index** | DB row or Dataset manifest | `content_version` |

**HF Dataset is not OLTP** for ranked submits—use it for **blobs/manifests**; keep **ranked state** in a real DB behind the game node.

---

## 7. Trust and architecture (short reminder)

- **Non-ranked:** Client truth; local leaderboards default; **SCAN** clues from **cached Mapbox stills** (`docs/GAME-ENGINE.md` §9).  
- **Ranked:** Game node holds secrets until submit (`docs/RANKED-MODE.md`).

---

## 8. Architecture decision checklist (for ADRs)

1. Fused game+ML process vs thin orchestrator + workers? **(This plan: thin + workers; no ML in `server/`.)** 2. Game node language? **(Python `server/`.)** 3. Live GPU vs cache-only? 4. Artifacts: Dataset vs DB? 5. Ranked store? 6. How many inference URLs? 7. Client `baseUrl`? 8. Internal auth (mTLS, shared secret)?

---

## 9. Related documents

- **`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`** — master: **standard** hint LFM-VL + **specialist** satellite Space + Gradio demo + CI  
- **`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`** — Street View **A → B** detail  
- **`docs/NARRATIVE-AND-PROMPTS.md`** — narrative bundles, cache keys  
- **`rules/12-python-gradio-terramind-server.md`** — thin **`server/`** (FastAPI + optional Gradio **`/ops`**) + HF Jobs/Datasets + **`inference/*`** (see **§0**–**§0.2** above)  
- **`docs/RANKED-MODE.md`** — ranked verification (**not** the **PRO** tab); former `docs/RANKED-AND-PRO-MODE.md`  
- **`rules/13-client-cache-and-data-plane.md`** — no Hub on device  
- **`rules/05-networking-leaderboard.md`** — public API trust  
- **`plans/2026-04-07-gradio-terramind-backend.md`** — TerraMind Jobs, Datasets; **§2** script-first hydration and **`inference/*`** layout  
- **`plans/2026-04-07-game-server-thin-orchestrator.md`** — **canonical** thin `server/`: auth, ranked, POI, leaderboards, **control-plane** `httpx` to `inference/*` (**§0.1** — no Sentinel/COG custody; **no** `torch`)  
- **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`** — PRO jobs: materialization service + TerraMind merge + on-device VLM (`§5.3` above)

When you adopt a split topology, add **`server/docs/TOPOLOGY.md`** with **URLs, env vars, sequence diagrams**.
