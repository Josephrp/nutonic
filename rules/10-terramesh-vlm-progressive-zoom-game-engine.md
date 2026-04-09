# TerraMind / TerraMesh reference and VLM progressive-zoom game engine

## What the reference code actually is

The codebase under `refs/terramind-geogen-main/` is a **geospatial ML research pipeline** around **TerraMesh** (IBM, Hugging Face `ibm-esa-geospatial/TerraMesh`): WebDataset shards, multimodal inputs (e.g. `S2L2A`), optional coordinate metadata, transforms (`MultimodalTransforms`, Albumentations), and **Terramind** models for generation/evaluation.

Authoritative pieces for **location semantics and scoring geometry**:

| Artifact | Role |
|----------|------|
| `src/terramesh.py` | Dataset construction (`build_terramesh_dataset`), splits (`train` / `val`), modalities, metadata such as **center_lon / center_lat** when `return_metadata=True`. |
| `src/geo_utils.py` | **Haversine** distance in km between (lon, lat) pairs—use the same definition server-side for guess-vs-ground-truth scoring to stay consistent with research metrics. |
| `src/terramesh_statistics.yaml` | Normalization bounds for modalities; relevant if server-side models consume TerraMesh-style tensors. |
| `scripts/generate_and_evaluate.py` | Batch inference + per-modality metrics; **pattern** for how predictions are compared to ground truth (including coordinate error). |
| `scripts/plot_error_heatmap.py` | Geographic **binned error heatmaps** (lon/lat bins, aggregated haversine error)—inform **difficulty tuning** (where the world is inherently harder) and analytics dashboards, not the mobile map widget. |
| `src/plotting_utils.py` | Visualization helpers for satellite-style tensors (e.g. RGB compositing). |
| `notebooks/*.ipynb` | Validate transforms, TerraMesh val workflows, and generation experiments—**behavioral reference** for data handling, not runtime code to embed in clients. |

**Rule:** Treat this tree as **server/research reference**. Kotlin clients must not depend on PyTorch, WebDataset, or TerraMesh loaders. Expose game behavior through **HTTP/WebSocket APIs** (see `05-networking-leaderboard.md`, `06-server-embedding-and-ai.md`).

---

## NU:TONIC game loop (product engine, server-authoritative)

This loop extends the generic map flow in `04-maps-and-gameplay.md`.

### Rounds and data

1. **Dataset**: Rounds are drawn from a **preloaded GeoGuessr-style (or equivalent) location pool** with **ground-truth coordinates** and **Street View–sourced imagery** (or API handles) for the VLM path. TerraMesh is **not** a drop-in substitute for Street View; use TerraMesh only where product explicitly uses satellite/modality generation—otherwise keep datasets separate but use the same **haversine** and metadata discipline as TerraMesh eval.
2. **Difficulty**: **Easy / medium / hard** are **server-defined profiles** that adjust tunables such as:
   - **Initial map viewport** radius (larger = easier),
   - **Maximum zoom-in steps** (`max_zooms`) and **per-step shrink factor** toward ground truth,
   - **VLM hint strength** (specificity vs vague narrative),
   - **Time or turn limits**,
   - Optional **starting blur / distortion** on clues.
   Profiles must be **versioned** in API responses so clients render the correct UX copy (“Hard mode: 4 zoom steps”).

### VLM and human flow

3. **VLM input**: The VLM receives **Google Maps Street View–style images** (and any allowed metadata) and produces a **natural-language description / plan** for humans—not raw coordinates exposed to the client before round end.
4. **Human-facing map**: The **main UI shows a zoomed-out map** at round start; it **does not** start at street level unless difficulty says so.
5. **Progressive zoom**: On each **qualified turn** (e.g. user message, hint request, or server-paced tick—pick one contract and stick to it), the server advances **zoom state** (camera bounds toward truth) until **max_zooms** is reached. **Rule:** Zoom level and center are **authoritative on the server**; the client applies the viewport the server sends. Prevents map hacks from learning extra precision early.
6. **Chat UI**: VLM hints and chat live in a **glass-like, semi-transparent overlay** on top of the map (`refs/DESIGN.md` glass rules, scanline/glow discipline in `02-design-system.md`). Chat must not obscure the **primary tap-to-place** affordance; follow `08-ux-and-performance-footguns.md` for hit targets and responsiveness.

### Markers and multiplayer

7. **User markers**: Each participant submits **guess coordinates** through the same abstract map interface as in `04-maps-and-gameplay.md`; server records **who guessed when** and validates against match rules.
8. **Join ongoing games**: Matches expose a **joinable state** (lobby vs in-progress) over the realtime channel; late joiners receive **current zoom tier + chat history slice + VLM summary** per API contract. Do not fork divergent game state per client.
9. **AI marker phase**: After **all human players** in the match have submitted (or forfeited per rules), the **AI places a single marker**—**required** for normal resolution. Coordinates are **always** produced for clients; in production they should come **primarily from precomputed cache** (HF Jobs → Dataset → server sync) with **live** TerraMind/VLM as an enhancement when available. One broadcast **`AI_GUESS_PLACED`** event; same coordinate schema as human guesses for scoring UI (`rules/13-client-cache-and-data-plane.md`).

### Scoring

10. **Distance and leaderboard**: Compute **haversine km** (or product-defined score derived from it) from each guess to ground truth using the **same formula** as `geo_utils.haversine` conceptually; persist results for leaderboard hydration (`05-networking-leaderboard.md`).

---

## Implementation checklist (agents and humans)

- [ ] Server owns **round state machine**: difficulty profile, zoom step index, VLM transcript, participant list, guess status, AI phase.
- [ ] Client owns **presentation**: map viewport from server, glass chat overlay, markers, optimistic UI within reconciliation rules.
- [ ] Street View / Maps **API keys and ToS** isolated per platform; never embed secrets in `commonMain`.
- [ ] Notebooks/scripts under `refs/terramind-geogen-main` remain **reference**; production server code lives under the project’s service module with explicit API docs.

---

## Related rules

- `04-maps-and-gameplay.md` — map abstraction, tap-to-place, feedback latency.
- `05-networking-leaderboard.md` — APIs for matches and leaderboard.
- `06-server-embedding-and-ai.md` — VLM/embeddings on server, fallbacks.
- `02-design-system.md` — glass surfaces and typography for the chat overlay.
- `00-product-intent.md` — multi-user parity and server authority.
