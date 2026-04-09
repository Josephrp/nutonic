# Python reference server: FastAPI, Gradio (ops UI), TerraMind / TerraTorch

## Authority and scope

- **Game clients** (Kotlin Multiplatform, optional TypeScript web) talk to **HTTP/WebSocket APIs** only—never import TerraTorch or PyTorch in clients.
- **`refs/`** (including TerraMesh / TerraMind research trees) remains **behavioral reference**; **production server code** lives under a dedicated **`server/`** (or agreed) module in the monorepo.
- Detailed backend plan: **`plans/2026-04-07-gradio-terramind-backend.md`**.

---

## Rule: FastAPI is the API root; Gradio is mounted

- Use **FastAPI** (or equivalent ASGI app) for **contract-first** routes: auth (including **JWT** when enabled), leaderboard, match hooks, **cache manifest / bundle** endpoints for clients, and inference hooks used by the game.
- Mount **Gradio** with **`gr.mount_gradio_app(app, blocks, path="/ops")`** (path is an example) so **REST** and **Gradio** share one process without conflating routing.
- **JWT** is issued and validated in **FastAPI** (dependencies / middleware). **Gradio** does not replace auth; it may sit behind the same ASGI stack or separate ops auth.
- **Gradio** is allowed **only** for **operator-facing** surfaces (e.g. read-only leaderboard table). **Do not** require game players to use Gradio.

**TypeScript note:** TS clients consume **`/api/...` OpenAPI routes** via `fetch` or generated clients. Using **`@gradio/client`** for core game features is **discouraged**; reserve it for optional ops automation if ever needed.

Reference: [Gradio server mode](https://www.gradio.app/main/guides/server-mode/).

---

## Rule: TerraMind inference (including TiM) is server-side and constrained

- Use **TerraTorch** registries (`BACKBONE_REGISTRY`, `FULL_MODEL_REGISTRY`) per the [TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/) and [HF model card](https://huggingface.co/ibm-esa-geospatial/TerraMind-1.0-large).
- **Thinking-in-Modalities (TiM):** use **`*_tim`** model names and **`tim_modalities`** as documented. TiM requires **full pre-trained band sets**—**no** `bands` subset on inputs the generator was not trained for; otherwise TiM must be **disabled** for that request.
- **Default model size:** prefer **tiny/small/base** for development and reference servers; **large** only when GPU memory and latency budgets allow (TerraTorch sizing guidance in the same guide).
- Expose **timeouts**, **503** with structured errors, and **degraded gameplay** when inference fails (`06-server-embedding-and-ai.md`).

---

## Rule: Hugging Face Hub persistence for stable artifacts

- **Stable artifacts** (pooled embeddings, manifests, anonymized eval shards) may be pushed to a **Dataset** repo using:
  - **`huggingface_hub.HfApi`** in Python, or
  - **`hf upload … --repo-type=dataset`** from the [Hub CLI](https://huggingface.co/docs/huggingface_hub/en/guides/cli).
- **Do not** store full patch-token tensors by default—**pool or compress** and define a **schema** (Parquet preferred). Document **`model_version`**, **`merge_method`**, and **standardization** in each row or sidecar manifest.
- **Secrets:** `HF_TOKEN` via environment or secret manager; never in client apps or committed config.

---

## Rule: HF Jobs hydrate caches and Datasets; the match server serves clients

- **HF Jobs** are the **preferred** place to run **GPU-heavy, known** work: TiM passes, pooled embeddings, **precomputed AI-guess coordinates** for `location_id`s in the pool, and compaction of Parquet shards—then **`hf upload` / `HfApi`** push artifacts to a **Dataset** repo. See [Jobs documentation](https://huggingface.co/docs/huggingface_hub/en/guides/jobs) (authenticated; subject to Hub quotas).
- The **game server** **pulls or syncs** those artifacts into a **local store** (disk + optional DB index) and exposes **only HTTP APIs** to clients; clients **never** call the Hub directly (`rules/13-client-cache-and-data-plane.md`).
- **Leaderboard source of truth** remains the server **DB** (or agreed store), not the Dataset; Datasets hold **ML/cache** artifacts and manifests.
- **Real-time** round start must **not** wait for a Job mid-flight; use **already-committed** shards or **fallback** policy (`rules/06`, `GAME-ENGINE.md` §12.2).

## Rule: ZeroGPU (Hugging Face Spaces) for on-demand GPU

- For **hosted** demos or **burst** TiM/VLM work on Hugging Face, use **[Spaces ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu)** with the **`@spaces.GPU`** decorator from the **`spaces`** library so GPU is allocated **per decorated call** (see Hub docs and [ZeroGPU blog](https://huggingface.co/blog/zerogpu-aoti)).
- **Constraint:** ZeroGPU targets **Gradio Spaces** workloads; it is **not** a drop-in for a 24/7 dedicated FastAPI GPU server. Production options: (1) **self-hosted GPU** with TerraTorch in-process, (2) **Jobs** for batch hydration, (3) **Space + API** that the match server calls for rare inference, or (4) **cache-only** hot path with no live GPU.

---

## Rule: alignment with game engine rule `10`

- **Street View / VLM progressive zoom** and **TerraMind / TerraMesh EO** paths are **different product surfaces**. Server APIs must **label** which pipeline serves a given round or clue so clients do not mix semantics.
- **Haversine / scoring** remains consistent with server authority (`10`, `05`).

---

## Related rules

- `05-networking-leaderboard.md` — OpenAPI, leaderboard hydration, optional JWT.  
- `06-server-embedding-and-ai.md` — embeddings, AI guess cache-first policy.  
- `10-terramesh-vlm-progressive-zoom-game-engine.md` — TerraMesh reference, game loop, scoring.  
- `13-client-cache-and-data-plane.md` — no client Hub access; server-mediated hydration.
