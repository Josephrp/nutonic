# TerraMesh cache, VLM, and progressive-zoom game engine

## What the reference code under `refs/terramind-geogen-main/` is

The codebase under `refs/terramind-geogen-main/` is a **geospatial ML research pipeline** around **TerraMesh** (IBM, Hugging Face `ibm-esa-geospatial/TerraMesh`): WebDataset shards, multimodal inputs (e.g. `S2L2A`), optional coordinate metadata, transforms (`MultimodalTransforms`, Albumentations), and various **research** models for generation/evaluation. **Product server code** may use **TerraMind TiM** (`*_tim`) and **TerraMind full generation** (`terramind_v1_*_generate`) per `rules/06-server-vlm-tim-and-on-device-ml.md` and `rules/12-python-gradio-terramind-server.md`—not an in-app PyTorch runtime.

**Product use of TerraMesh (narrow):** batch/server jobs may emit **cached AI-guess lat/long (and metadata) per `map_id`**. Clients consume that cache over HTTP or bundled manifests—**not** full TerraMesh tensors at runtime. **TiM alignment:** **`AiGuessStore`** / manifest rows **must** accept **`ai_lat` / `ai_lon`** hydrated from **TerraMind TiM `Coordinates`** outputs ( **`tim_modality_outputs.Coordinates`** ) produced by the **same TiM worker** the game server uses for PRO (`rules/06-server-vlm-tim-and-on-device-ml.md`, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`). TerraMesh-only Jobs remain valid; when both exist, OpenAPI defines **precedence** (default: **TiM `Coordinates` wins** for the AI marker if present for that `map_id` revision). **Same JSON shape ≠ same store:** PRO tab responses include **`tim_modality_outputs`** for the **dashboard**; they **do not** imply an **`AiGuessStore`** write unless the request is **`map_id`**-bound or OpenAPI defines an explicit registration path (**`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §1.1.1**).

Authoritative pieces for **location semantics and scoring geometry** (batch / server):

| Artifact | Role |
|----------|------|
| `src/terramesh.py` | Dataset construction (`build_terramesh_dataset`), splits (`train` / `val`), modalities, metadata such as **center_lon / center_lat** when `return_metadata=True`. |
| `src/geo_utils.py` | **Haversine** distance in km between (lon, lat) pairs—implement the **same definition in `commonMain`** for player-visible scoring; server/batch code may mirror it for analytics. |
| `src/terramesh_statistics.yaml` | Normalization bounds for modalities; relevant if server-side models consume TerraMesh-style tensors. |
| `scripts/generate_and_evaluate.py` | Batch inference + per-modality metrics; **pattern** for how predictions are compared to ground truth (including coordinate error). |
| `scripts/plot_error_heatmap.py` | Geographic **binned error heatmaps** (lon/lat bins, aggregated haversine error)—inform **difficulty tuning** and analytics dashboards, not the mobile map widget. |
| `src/plotting_utils.py` | Visualization helpers for satellite-style tensors (e.g. RGB compositing). |
| `notebooks/*.ipynb` | Validate transforms, TerraMesh val workflows, and generation experiments—**behavioral reference** for data handling, not runtime code to embed in clients. |

**Rule:** Treat this tree as **research / server-batch reference**. Kotlin clients must not depend on PyTorch, WebDataset, or TerraMesh loaders. **Gameplay state** and **trust** for **non-ranked** play live on the client (`rules/00-product-intent.md`); **ranked** trust follows `docs/RANKED-MODE.md`. Optional HTTP APIs supply hints, **per-`map_id` AI lat/long cache rows**, or static bundles (`rules/05-networking-leaderboard.md`, `rules/06-server-vlm-tim-and-on-device-ml.md`).

---

## NU:TONIC game loop (client-authoritative engine for non-ranked)

**Default loop** (`docs/GAME-ENGINE.md` §2, §8–§9): **solo-first**—**no lobbies**, **no blocking on other players’ submits**. **World map** + **basemap**, **primary Mapbox reference still**, **collapsible** assist panels for **(a)** **pre-cached Street View description text** (batch LFM-VL over sampled panos per target—`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`), **(b)** **pre-cached useful hints** (default **six** coordinate-free tiers, script- or job-generated), **(c)** optional **peer marker** after **Reveal uplink** (hint only), **bottom-right guess modal**, **one primary human guess**, **narrative overlay** (authorial `prompts/` + **user text**—not a smuggled substitute for labeled assists), then **AI marker** from **cached** `ai_lat`/`ai_lon` (**TerraMesh** / **`AiGuessStore`** / TiM **`Coordinates`** when enabled). **On-device VLM** is **PRO tab only** (`rules/06-server-vlm-tim-and-on-device-ml.md`).

**Ranked:** expanding **Street View descriptions**, **any useful-hint tier**, or **peer reveal** before `submit` **forfeits** verified placement—server endpoints per **`docs/RANKED-MODE.md`**. **Non-ranked:** assists optional, **no** score consequence.

**Rounds, guesses, AI marker, and scores** are driven by **`commonMain`** for **non-ranked** missions. Bundled assists must not be the **only** way to obtain the Mapbox still or map; **primary still** always ships for SCAN.

### Rounds and data

1. **Dataset**: Rounds are drawn from a **location pool** with **ground-truth coordinates** bundled in-app, fetched as static manifest from the reference server, or both. **TerraMesh** supplies **cached lat/long guesses per `map_id`** for AI marker / analytics—not a drop-in Street View substitute.
2. **Challenge tuning**: Prefer **`assist_level` / `challenge_tone`** (and mission metadata) over a player-facing **Easy / Medium / Hard** menu (`docs/GAME-ENGINE.md` §7). Version **`ruleset_version`** in **local** leaderboard rows (and in any **optional** community **`POST`**) so rows stay comparable (`rules/05-networking-leaderboard.md`).

### VLM and human flow

3. **Assist UI** is **optional and collapsible**: **authorial** overlay (`prompts/` + user typing) is separate from **Street View description** and **useful-hint** panels (`rules/06-server-vlm-tim-and-on-device-ml.md`). **Street View / LFM-VL** runs in **batch** to fill bundles—not on-device during SCAN play.
4. **Human-facing map**: Initial camera may be **zoomed out** per mission; **progressive zoom is not required** for the player to submit a guess.
5. **Progressive zoom** (optional adjunct): **Client-owned** zoom state when enabled (tier index, bounds toward truth). If a **server-assisted** mode is added, the server may **suggest** bounds; the **playing client** still applies them through the shared `MapViewport` abstraction. Document which mode is active in API/flags.
6. **Overlay** must not block **map pan** or the **guess modal** (`rules/08-ux-and-performance-footguns.md`).

### Markers and async competition

7. **User markers**: Submitted through the shared map interface; **eligibility and timing** are enforced in **client** state—**not** by server score validation for **non-ranked** play. **Display:** **self** vs **optional peer hint** (after **Reveal uplink** only) vs **AI** (after human phase)—see **`docs/GAME-ENGINE.md` §10.1** and **`rules/04-maps-and-gameplay.md`**. Peer marker is **never** a lobby gate.
8. **Non-ranked outcomes:** Players resolve against **local round truth**, then **write** rows to the **device-local** per-**`map_id`** leaderboard. **Optional** **`POST .../guesses/record`** may mirror coords + client distance for **telemetry** only (`rules/05-networking-leaderboard.md`). **Server-visible** competition with other humans requires **ranked** and/or **optional** community APIs (`docs/SOCIAL-AND-COMPETITION.md`).
9. **AI marker phase**: After human phase, **one AI marker** is produced (local policy, **TerraMesh per-`map_id` cache**, bundled table, or optional server). Emit **`AI_GUESS_PLACED`** (or equivalent) for results UI. **Leaderboard** must expose **AI vs golden answer** metrics separately from human PvP rows (`rules/05-networking-leaderboard.md`). **Ranked:** peer reveal before `submit` **forfeits** verified score—**`docs/RANKED-MODE.md`**.

### Scoring

10. **Distance and local rows**: Compute **haversine km** (or product score) in **`commonMain`** aligned with `geo_utils.py` semantics. **Persist** **player role**, **matchup type**, and **AI-vs-truth** fields on **local** leaderboard rows. **Optional** community **`POST`** uses OpenAPI when product ships it.

---

## Implementation checklist (agents and humans)

- [ ] **Client (`commonMain`)** owns **round state machine**: mission/assist config, optional zoom step, narrative + **collapsible** assist panels + guesses, AI phase, resolution.
- [ ] **Server** supplies optional VLM strings, imagery handles, **per-`map_id` cached AI-guess** lat/long rows (**TerraMind TiM `Coordinates`** and/or **TerraMesh** batch), or static cache rows—**no mandatory** server for core single-device **non-ranked** play.
- [ ] Street View / Maps **API keys** isolated per platform; never embed secrets in `commonMain`.
- [ ] Notebooks/scripts under `refs/terramind-geogen-main` remain **reference**; production server code (if any) lives under **`server/`** with explicit API docs.

---

## Related rules

- `04-maps-and-gameplay.md` — map abstraction, tap-to-place, feedback latency.
- `05-networking-leaderboard.md` — **local** default, optional community API, leaderboard dimensions (PvP roles + AI vs golden), **auto-refetch off by default**.
- `06-server-vlm-tim-and-on-device-ml.md` — VLM overlay, `refs/VLMExample/` on-device ML, server ML, fallbacks.
- `02-design-system.md` — glass surfaces and typography for overlays.
- `00-product-intent.md` — client authority and parity.
