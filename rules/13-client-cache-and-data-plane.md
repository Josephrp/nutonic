# Client cache, optional server hydration, and Hugging Face (no client Hub access)

## Rule: clients never use the Hugging Face CLI or Hub tokens

- **Kotlin / Compose clients** (and any TS web shell) **do not** bundle `hf`, `huggingface_hub`, or Hub **write** tokens.
- **Dataset artifacts**, **precomputed AI guesses**, **TiM job outputs** (schema-defined), and **location-pool shards** are produced **server-side or by HF Jobs**, stored on the Hub (or built in CI), then **consumed by the reference server** (if used), which exposes **versioned HTTP APIs** or **static bundle URLs** to clients.
- Clients **may** download **opaque blobs** (JSON, protobuf, small Parquet, and PRO model artifacts) **from the NU:TONIC reference server** (or signed CDN fronting it)—never directly from `huggingface.co` in production unless product explicitly documents an exception (e.g. read-only public asset URLs with no secrets). Large PRO model artifacts must be described by an OpenAPI manifest with size/hash/revision and cached in the app sandbox, not committed to the app repo.

## Rule: local-first persistence on clients

- Clients **persist** locally: **round/match summaries**, **per-`map_id` non-ranked leaderboard** (authoritative **device-local** rows for default play—see `rules/05-networking-leaderboard.md`), **optional** last-known **server** aggregates for community/`GET` features, theme/static assets, **build-serialized narrative bundles** from `prompts/` (shipped as resources—no refetch unless product adds remote overrides), **hydration manifests** (e.g. `content_version`, `shard_id`, ETag) for any optional `GET`s, **golden / AI reference blobs** received from the server for a map, **server-cached AI suggestion** payloads keyed by mission/map, and **game progress** (levels, settings).
- Use **platform-appropriate storage** (DataStore, preferences, files in app sandbox, desktop user data dir). **Encrypted / secure storage** is for optional future tokens only—not required for default play (`rules/03-kotlin-multiplatform-structure.md`, `rules/05-networking-leaderboard.md`).
- **Offline UX**: show **last-known per-map** leaderboard and **cached** round assets; full play remains possible when rounds are **bundled** in-app. Do not assume Hub availability.

## Rule: commit after hydration (golden, AI, aggregates)

- After each **non-ranked** round, **commit** updated **local** leaderboard state for that **`map_id`** atomically (no partial writes for visible lists).
- After a successful **optional** **`GET`** of **community** leaderboard and/or **reference** payload for a **`map_id`**, clients **atomically persist** the body + **`ETag` / `content_version`** under a stable key (e.g. `leaderboard:community:{map_id}`, `reference:{map_id}`). Treat as **commit**—**do not** partially write visible UI without matching stored version metadata.
- On **optional** **`POST` self-report** success, either **invalidate** the per-map **community** cache entry or **merge** server-returned aggregate fragment per OpenAPI—then **commit** so “Update” and next launch stay coherent. **Local** rows are unaffected unless the response explicitly merges.

## Rule: HF Jobs hydrate server-side and Hub datasets—not the player’s trust path

- **Jobs** run **known** generation work ahead of time (**TiM** passes, **TerraMind `*_generate`** renders when used, AI-guess rows keyed by `round_id` / `location_id`, static map metadata) and **push** results to a **private or gated Dataset** repo (`hf upload` / `HfApi` inside the job).
- The **reference server** **pulls** or **syncs** those artifacts into a **local store** and may expose **`CacheService` / `AiGuessStore`**-style APIs for **optional** client enrichment.
- **Active round** resolution **must not** block on a Job finishing mid-round; if a precomputed row is missing, the **client** uses a **documented fallback** (heuristic AI guess, **per-`map_id` TerraMesh cache** lat/long, static clue, or round abort)—see **`06-server-vlm-tim-and-on-device-ml.md`** and **`docs/GAME-ENGINE.md`**.

## Rule: location pool and golden truth

- **Ground truth** for a round may be **shipped inside the app** (bundled pool), **downloaded** as an opaque manifest from the reference server, or both. Curation from **GeoGuessr-style** or TerraMesh-related datasets may happen in **server or Job code** before packaging.
- **Casual / local-truth rounds:** Clients hold **`location_id` / `poi_id` → golden coordinates** (or equivalent) for **local scoring**; **local** leaderboard rows carry `ruleset_version` / round ids for sorting and filters. **Optional** community **`POST`** uses the same ids when product ships that API (`rules/05-networking-leaderboard.md`).
- **Ranked missions:** Clients **must not** persist server **pre-submit** ground truth to disk; cache only **clue manifests** and, after **`submit`**, the **server-returned** verified score payload (`docs/RANKED-MODE.md`).

## Rule: POI directory shape → server bundles → client cache

- **Authoring layout** (example: `data/downloads/geoguessr_poi_120/poi_0011/`) contains **`poi.json`** plus **`mapbox/`** PNGs and optional **`sentinel-2-l2a/`** assets. The **server or CI pipeline** normalizes this tree into **versioned bundles** (downsampled rasters + trimmed JSON) exposed at **`GET /api/.../manifest`** or static URLs—clients **never** assume the raw monorepo path exists on device.
- **Cache keys** should include **`poi_id`**, **`content_version`**, and **`asset_variant`** (e.g. `mapbox_512`, `s2_thumb`).
- **Bundled vs download:** ship **minimal** assets in the app for cold start; **lazy-fetch** heavy Sentinel stacks when the round type requires them.
- **Writes:** **`POST` POI** and **`POST` scores** follow **`rules/05-networking-leaderboard.md`** (non-ranked vs ranked + store rules); payloads remain **schema-strict**.

Full product implications: **`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`**.

## Related rules

- **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`** — central game node vs inference workers; HF Datasets/Jobs/Spaces; DB vs artifact store (still: clients use **one** public API, no Hub tokens).  
- `05-networking-leaderboard.md` — per-map scope, **local** default, optional community API, ranked missions, POI, sanitization, leaderboard dimensions.  
- `docs/RANKED-MODE.md` — ranked clue vs cache rules  
- `docs/LEADERBOARD-MAP-POI-SCORES.md` — assessment and illustrative API table.  
- `06-server-vlm-tim-and-on-device-ml.md` — SCAN **bundled** hint overlay, TerraMind **TiM**, **PRO** on-device ML (`refs/VLMExample/`), client-owned resolution.  
- `12-python-gradio-terramind-server.md` — Jobs, ZeroGPU lane, Hub persistence.  
- `docs/GAME-ENGINE.md` — engine phases and events (aligned with client authority §0).  
- `plans/2026-04-07-complete-implementation-architecture.md` — end-to-end data plane.
