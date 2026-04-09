# Client cache, server-mediated hydration, and Hugging Face (no client Hub access)

## Rule: clients never use the Hugging Face CLI or Hub tokens

- **Kotlin / Compose clients** (and any TS web shell) **do not** bundle `hf`, `huggingface_hub`, or Hub **write** tokens.
- All **Dataset artifacts**, **precomputed AI guesses**, **TiM / embedding outputs**, and **location-pool shards** are produced **server-side or by HF Jobs**, stored on the Hub (or built in CI), then **consumed by the reference server**, which exposes **versioned HTTP APIs** (and optional **static bundle URLs**) for clients.
- Clients **may** download **opaque blobs** (JSON, Parquet-as-zip, protobuf) **only from the NU:TONIC server** (or CDN fronting it)—never directly from `huggingface.co` in production unless product explicitly documents an exception (e.g. read-only public asset URLs with no secrets).

## Rule: local-first persistence on clients

- Clients **persist** received payloads **locally**: match/round summaries, leaderboard cache, theme/static assets, and **hydration manifests** (e.g. `content_version`, `shard_id`, ETag).
- Use **platform-appropriate storage** (DataStore, encrypted preferences, files in app sandbox, desktop user data dir—`rules/03`, `rules/05` secure storage for tokens only when auth is enabled).
- **Offline UX**: where product allows, show **last-known** leaderboard and **cached** round assets; on reconnect, **refresh** from server. Do not assume Hub availability.

## Rule: HF Jobs hydrate server-side and Hub datasets—not the live player path

- **Jobs** run **known** generation work ahead of time (TiM passes, pooled embeddings, AI-guess rows keyed by `round_id` / `location_id`, static map metadata) and **push** results to a **private or gated Dataset** repo (`hf upload` / `HfApi` inside the job).
- The **game server** **pulls** or **syncs** those artifacts (scheduled job, startup sync, or lazy fetch with local disk cache), then serves them through **`CacheService` / `AiGuessStore`** APIs.
- **Live** match resolution **must not block** on a Job finishing mid-round; if a precomputed row is missing, use a **documented fallback** (e.g. heuristic guess, stale cache tier, or round **abort** flag)—see **`06-server-embedding-and-ai.md`** and **`GAME-ENGINE.md` §12.2**.

## Rule: alignment with location pool (`refs/terramind-geogen-main`)

- **Location pool** entries (ground truth, imagery handles) may be **curated** from **GeoGuessr-style public datasets** on Hugging Face (e.g. street-view pano metadata) **only inside server or Job code**; clients receive **opaque** `location_id` and **server-issued** imagery references per contract.
- Keep **compliance** (licenses, attribution, no redistribution of raw third-party imagery in violation of dataset terms) in **`docs/`** or server README.

## Related rules

- `05-networking-leaderboard.md` — auth tiers, JWT when required, API contract.  
- `06-server-embedding-and-ai.md` — AI guess mandatory / cache-first inference policy.  
- `12-python-gradio-terramind-server.md` — Jobs, ZeroGPU lane, Hub persistence.  
- `GAME-ENGINE.md` — `AI_GUESS` phase and events.  
- `plans/2026-04-07-complete-implementation-architecture.md` — end-to-end data plane.
