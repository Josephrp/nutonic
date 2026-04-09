# Server embedding and AI-driven play

## Rule: embeddings run on the server

- **Text or multimodal embedding models** are **not** bundled in the mobile/desktop client for production parity unless explicitly approved for on-device inference.
- Clients send **allowed inputs** (e.g. clue text, round id, role) to server endpoints; server returns **vectors, scores, or decisions** as defined by the API.

## Alien / AI role

- “Unpredictable AI playstyle” or embedding-driven behavior is implemented as **server policy** (retrieval, sampling, difficulty). UI shows **outcomes** (hints, opponent moves, narrative) from API—**do not** reimplement game AI only on one platform.

## Latency and resilience

- **Timeout and fallback**: If **live** embed or VLM calls fail, degrade with **cached** clues, **static** copy, or **pre-hydrated** model outputs—**never** hang the map UI.
- **AI guess is not optional** for a normal round: the engine **always** reaches **`AI_GUESS_PLACED`** with coordinates unless the round **aborts** under a documented fault path. Prefer **Jobs + Dataset + server cache** so the hot path rarely depends on live GPU (`rules/GAME-ENGINE.md` §12.2, `rules/13-client-cache-and-data-plane.md`, `rules/12-python-gradio-terramind-server.md`).

## Privacy

- Only send data the server contract allows; document fields in the API spec. No logging of secrets or raw tokens.

## Relation to reference code under `refs/`

- Use **`refs/`** Python or other reference **as behavioral reference** for the server. Clients consume **HTTP/WebSocket** only; do not copy Python dependencies into KMP.

## TerraMind / TerraTorch (Earth-observation backbone)

- When the product uses **satellite / multimodal EO** clues or server-side embedding from TerraMind, run **TerraTorch** (`BACKBONE_REGISTRY`, optional **TiM** `*_tim` models) **only on the reference Python server**—see **`12-python-gradio-terramind-server.md`** and **`plans/2026-04-07-gradio-terramind-backend.md`**.
- **TiM is not a generic “fill missing JSON fields” tool:** it operates under documented **modality**, **band completeness**, and **`tim_modalities`** constraints from the [TerraTorch TerraMind guide](https://terrastackai.github.io/terratorch/stable/guide/terramind/).
- Persist **pooled or compressed** representations to a **Hugging Face Dataset** repo via **`huggingface_hub` or `hf upload`** when stable artifacts are required; avoid dumping full patch sequences without a retention and schema plan.
