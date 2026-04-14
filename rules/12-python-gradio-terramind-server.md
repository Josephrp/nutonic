# Python reference server: FastAPI, Gradio (ops UI), TerraMind **TiM** and **generation** (TerraTorch)

## Authority and scope

**Canonical production `server/`:** **`plans/2026-04-07-game-server-thin-orchestrator.md`** — public game API **without** `torch` / **`terratorch`** in that deployable; **`httpx`** to **multiple** **`inference/*`** Python services and to **TerraMind** worker URL(s) (`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` **§0**–**§0.2**). **Normative delivery** is: **(1)** **`data/scripts/`** + CI + **HF Jobs** hydrate caches and Datasets (**§0.1**), **(2)** discrete **`inference/*`** services implement the **same validated logic** over HTTP where needed (**`plans/2026-04-07-gradio-terramind-backend.md` §2**), **(3)** **one thin Python `server/`** serves OpenAPI and may mount **Gradio `/ops`** on the **same** process **without** TerraTorch—**never** fused game+TiM in `server/`. (**Non-Python** game API tiers remain **ADR-only**; see **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §3**.)

- **Game clients** (Kotlin Multiplatform, optional TypeScript web) talk to **documented HTTP (REST) APIs** for game features—never import TerraTorch or PyTorch in clients. (Internal server-to-server channels may use other transports; they are **not** the mobile contract, and **player-visible** gameplay stays **REST + local engine state** per **`docs/GAME-ENGINE.md` §14**.)
- **`refs/`** (including TerraMesh / TerraMind research trees) remains **behavioral reference**; **production server code** lives under a dedicated **`server/`** (or agreed) module in the monorepo.
- Detailed backend plan: **`plans/2026-04-07-gradio-terramind-backend.md`**.
- **Product stance:** Gameplay is **client-authoritative** for non-ranked; **non-ranked leaderboards default to device-local** with **no** score ingest required (`rules/05-networking-leaderboard.md`). The server may serve **optional** ML or static assets and may **optionally** expose community score **`POST`/`GET`** if product ships that path. **No required JWT or player auth** for opening the default shell on reference deployments (`rules/00-product-intent.md`, `rules/05-networking-leaderboard.md`).

---

## Topology: central game node vs inference workers (allowed)

**Layout:** the thin **`server/`** process hosts **FastAPI** + optional **Gradio `/ops`** only; **TerraTorch** runs in **`inference/*`**, TerraMind workers, **Jobs**, or **`demos/terramind_space/`** (see **Rule: FastAPI is the API root** below). **Production** splits responsibilities:

- **Central game / API node** — Owns the **public OpenAPI surface** clients use: optional community leaderboard, **ranked** round lifecycle and verification, JWT for gated writes, cache **manifest** URLs, and orchestration (**HTTP out** to many workers, each with timeouts). **This implementation plan:** **Python** thin **`server/`** (FastAPI). **Hypothetical:** a non-Python node could match the same contract (**ADR + parity strategy**; **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §3**).
- **Inference tier** — **Typically multiple** **Python** services under **`inference/*`** (Street View pano, LFM-VL hints, satellite caption, PRO materialization, …) **plus** **TerraMind TiM** / **`terramind_v1_*_generate`** on a **dedicated worker**: **separate processes**, **multiple Hugging Face Spaces**, or **HF Jobs → Dataset** with no live GPU on the hot path. Internal HTTP/gRPC between node and workers is **not** the mobile contract.
- **Worker runtimes (normative options):** **VLMs** may be served by **[vLLM](https://docs.vllm.ai/)** (OpenAI-compatible HTTP, when the model is supported) **or** by **Hugging Face `transformers` + PyTorch** inside the service container. **TerraMind / EO** paths use **TerraTorch** (and PyTorch) per TerraMind guides—**not** the thin `server/` process. Batch drivers (`tools/`, Jobs) call whichever URL backs the chosen stack.
- **Gradio** — Remains **operator-facing** (e.g. **`/ops`**) on whichever host serves admin UI. **Extra** Gradio or FastAPI-only inference replicas are fine **behind** the game node; **players** never rely on Gradio **`/queue`**, push/stream channels, or any non-REST path for **core** SCAN / ranked / INTEL flows (`rules/05`, TypeScript note below, **`docs/GAME-ENGINE.md` §14**).

**Hugging Face without one Gradio “god server”:** **Dataset** repos and **Jobs** are the cost-efficient artifact plane. **Spaces** may run **Docker** HTTP apps **without** Gradio. **ZeroGPU** is for **burst** GPU, not a promise of low cold-start latency—design fallbacks per **`rules/06-server-vlm-tim-and-on-device-ml.md`**.

**Database:** Use a **transactional store** (e.g. Postgres, or SQLite for reference-only) for **ranked** state and optional community rows; **HF Datasets** are for **versioned blobs / manifests**, not OLTP ranked adjudication alone. Rationale and ADR prompts: **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`**.

---

## Rule: FastAPI is the API root; Gradio is mounted on the thin `server/` (no TerraTorch there)

- Use **FastAPI** for **contract-first** **`/api/*`** routes on the **thin** **`server/`**: **optional** community **leaderboard ingest + query** (when shipped), **cache manifest / bundle** endpoints, optional **round / hint** hooks (solo-first semantics—**no** live-opponent room API), and **orchestration** that **`httpx`**-calls **`inference/*`** when live worker paths are enabled. **Do not** mount **in-process** TerraTorch TiM / **`_generate`** in this process—those belong in **`inference/*`**, **TerraMind workers**, or **Jobs** per **`plans/2026-04-07-gradio-terramind-backend.md` §2** and **`plans/2026-04-07-game-server-thin-orchestrator.md`**. **Hypothetical:** a **non-Python** central node would need the **same** public routes (or a documented versioned alternate) and could call Python inference services internally—**ADR-only** (**`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §3**).
- Mount **Gradio** with **`gr.mount_gradio_app(app, blocks, path="/ops")`** (path is an example) so **REST** and **Gradio** share one process without conflating routing.
- **JWT / auth** are **optional** and **off** by default. If added later for operator or account features, implement in **FastAPI** dependencies; **Gradio `/ops`** may use a separate ops secret.
- **Gradio** is allowed **only** for **operator-facing** surfaces (e.g. read-only leaderboard table). **Do not** require game players to use Gradio.

**TypeScript note:** TS clients consume **`/api/...` OpenAPI routes** via `fetch` or generated clients. Using **`@gradio/client`** for core game features is **discouraged**; reserve it for optional ops automation if ever needed.

Reference: [Gradio server mode](https://www.gradio.app/main/guides/server-mode/).

---

## Rule: TerraMind **TiM** and **`_generate`** (server-side, constrained)

- **TiM:** Use **`BACKBONE_REGISTRY`** with **`*_tim`** models, **`tim_modalities`**, and **full pre-trained band sets** per the [TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/) and [HF model card](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-large). **No** `bands` subset on raw inputs the model was not trained for; otherwise TiM must be **disabled** for that request.
- **Full generation:** Use **`FULL_MODEL_REGISTRY`** with **`terramind_v1_*_generate`**, explicit **`modalities`** and **`output_modalities`**, and **`standardize=True`** (or equivalent documented scaling) per the [same guide — Generation](https://terrastackai.github.io/terratorch/stable/guide/terramind/). Treat **`_generate`** as **heavier** than TiM forward—prefer **Jobs** or **async** for batch renders; do not block **guess submit** on generation.
- **Out of scope without ADR:** **backbone-only** TerraMind encoders (e.g. `terramind_v1_base` without `_tim` / `_generate`) and **parallel** generic EO vector pipelines—prefer explicit **`_*_tim`** or **`_*_generate`** contracts.
- **Default model size:** prefer **tiny/small/base** for development and reference servers; **large** only when GPU memory and latency budgets allow (TerraTorch sizing guidance in the same guide).
- Expose **timeouts**, **503** with structured errors, and **degraded** responses when inference fails (`06-server-vlm-tim-and-on-device-ml.md`). Clients still resolve rounds locally.

---

## Rule: Hugging Face Hub persistence for stable artifacts

- **Stable artifacts** (TiM run summaries, **generation** outputs or thumbnails per schema, manifests, anonymized eval shards) may be pushed to a **Dataset** repo using:
  - **`huggingface_hub.HfApi`** in Python, or
  - **`hf upload … --repo-type=dataset`** from the [Hub CLI](https://huggingface.co/docs/huggingface_hub/en/guides/cli).
- **Do not** store full patch-token tensors by default—**pool or compress** and define a **schema** (Parquet preferred). Persist **one column (or JSON sub-object) per imagined `tim_modality`** inside **`tim_modality_outputs`** so Jobs and the game server can hydrate **PRO** and **`AiGuessStore`** without a second inference pass. **`Coordinates`** entries **must** map cleanly to **`ai_lat` / `ai_lon`** when present. Document **`model_version`**, **`merge_method`**, **`tim_modalities`**, and **standardization** in each row or sidecar manifest.
- **Secrets:** `HF_TOKEN` via environment or secret manager; never in client apps or committed config.

---

## Rule: HF Jobs hydrate caches and Datasets; the reference server serves clients

- **HF Jobs** are the **preferred** place to run **GPU-heavy, known** work: **TiM** batch passes, **`_generate`** tile or clue renders, **precomputed AI-guess coordinates** for `location_id`s in the pool, and compaction of Parquet shards—then **`hf upload` / `HfApi`** push artifacts to a **Dataset** repo. See [Jobs documentation](https://huggingface.co/docs/huggingface_hub/en/guides/jobs) (authenticated; subject to Hub quotas).
- The **game server** **pulls or syncs** those artifacts into a **local store** (disk + optional DB index) and exposes **HTTP APIs** to clients; clients **never** call the Hub directly (`rules/13-client-cache-and-data-plane.md`).
- **Leaderboard store** (when community ingest exists) holds **optional self-reported** submissions and aggregates for display—not a validated competitive ledger for non-ranked rows unless product adds an ADR. **Ranked** rows are **verified** per `docs/RANKED-MODE.md`. Datasets hold **ML/cache** artifacts and manifests.
- **Real-time** round start on the client **must not** wait for a Job mid-flight; Jobs feed **optional** enhancement paths only.

## Rule: ZeroGPU (Hugging Face Spaces) for on-demand GPU

- For **hosted** demos or **burst** TiM / **generation** / VLM work on Hugging Face, use **[Spaces ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu)** with the **`@spaces.GPU`** decorator from the **`spaces`** library so GPU is allocated **per decorated call** (see Hub docs and [ZeroGPU blog](https://huggingface.co/blog/zerogpu-aoti)).
- **Constraint:** ZeroGPU is documented primarily for **Gradio**-style Spaces workloads; it is **not** a drop-in for a 24/7 dedicated GPU API. Other **containerized Spaces** or external GPU hosts may back inference instead—see **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`**. Production options: (1) **self-hosted GPU** with TerraTorch in-process, (2) **Jobs** for batch hydration, (3) **Space + HTTP API** that the **game node** calls for rare inference, or (4) **cache-only** hot path with no live GPU.

---

## Rule: alignment with game engine rule `10`

- **Street View / VLM progressive zoom** and **TerraMind TiM / generation / TerraMesh EO** paths are **different product surfaces**. APIs should **label** which pipeline serves a given optional clue bundle.
- **Haversine / scoring** for **non-ranked** player-visible results is **computed on the client** and stored **locally**; any **optional** community ingest **does not** claim anti-cheat validation. **Ranked** scores are **server-computed** (`10`, `05`).

---

## Related rules and docs

- **`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`** — **master**: **standard** LFM-VL Street View hints + **`inference/lfm_vl_satellite_caption_service`** (**specialist** satellite, `refs/satellite-vlm/` prompts, Gradio **demo** + FastAPI); HF Spaces + `hf` CLI.  
- **`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`** — Street View **A → B** drill-down.  
- **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`** — split topologies, HF cost patterns, DB vs Dataset, ADR checklist.  
- `05-networking-leaderboard.md` — **local** default, optional community contract, leaderboard dimensions, no default shell auth.  
- `06-server-vlm-tim-and-on-device-ml.md` — VLM, TerraMind **TiM** and **generation**, on-device ML, fallbacks.  
- `10-terramesh-vlm-progressive-zoom-game-engine.md` — client-authoritative loop.  
- `13-client-cache-and-data-plane.md` — no client Hub access; server-mediated optional assets.  
- **`plans/2026-04-07-terramind-gradio-spaces-comprehensive-demo.md`** — standalone TerraMind Gradio **server** demo, **ZeroGPU** (`@spaces.GPU`), HF Space layout, manual CI deploy (projects → line-level tasks).
