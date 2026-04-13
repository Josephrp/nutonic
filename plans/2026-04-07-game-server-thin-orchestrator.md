# Plan: NU:TONIC game server — thin orchestrator (auth, signatures, leaderboards; no generative math)

**Date:** 2026-04-07  
**Status:** Normative **product/engineering** plan for the **`server/`** deployable that **Kotlin clients** call via **OpenAPI**. It implements the **thin** game API only: **`server/`** **does not** host TerraTorch, LFM-VL, Street View sampling geometry, or other **heavy / numeric content pipelines**. Those run on **separate** **`inference/*`** Python services (each grounded in **`data/scripts/`**-validated logic per **`plans/2026-04-07-gradio-terramind-backend.md` §2**), **`demos/terramind_space/`**, or **HF Jobs** (`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` **§0.1–§0.2**, `inference/README.md`).

**Implementation language:** The thin **`server/`** is **Python** (FastAPI + **`httpx`**, Pydantic/OpenAPI validation)—see **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §0** and **§3**. That keeps ranked tickets, forfeits, clamps, and idempotency in **one** runtime with **`inference/*`**, avoiding a parallel non-Python API core that could drift from the contract.

**Authority:** `rules/05-networking-leaderboard.md`, `rules/12-python-gradio-terramind-server.md`, `rules/13-client-cache-and-data-plane.md`, `rules/06-server-vlm-tim-and-on-device-ml.md`, `docs/RANKED-MODE.md`, `docs/LEADERBOARD-MAP-POI-SCORES.md`, `docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`, `docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`, `docs/GAME-ENGINE.md` §0.

**Related plans (do not duplicate — cross-link only):**

| Plan | Role |
|------|------|
| **`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`** | Service A+B: pano sampling + LFM-VL hints (**all viewpoint / pano math here**). |
| **`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`** | Master for LFM-VL Spaces + satellite specialist. |
| **`plans/2026-04-07-gradio-terramind-backend.md`** | TerraMind **TiM** / **`_generate`**, Jobs → Dataset, **`inference/*`** services — not inside the thin game server. |
| **`plans/2026-04-07-tim-standalone-gradio-poi-dataset.md`** | TiM + POI tensor demos and dataset hygiene. |
| **`plans/2026-04-07-complete-implementation-architecture.md`** | End-to-end monorepo; **§2 / §4** align with **this** document for `server/`. |

---

## 0. Executive summary

| Goal | Approach |
|------|----------|
| **One public `baseUrl`** for clients | FastAPI (or equivalent ASGI) on **HF Docker Space** port **7860** ([Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker)), or same container elsewhere. |
| **No generative / vision / EO math in-process** | `server/` **dependencies exclude** `torch`, `transformers`, `terratorch`, Google Street View client libraries. Use **`httpx`** (async) to call **`STREETVIEW_PANO_SERVICE_URL`**, **`LFM_VL_HINT_SERVICE_URL`**, **`LFM_VL_SATELLITE_CAPTION_SERVICE_URL`**, **`PRO_MATERIALIZATION_SERVICE_URL`** (Mapbox + Sentinel-2 resize for PRO), and **`TERRAMIND_TIM_URL`** / **`TERRAMIND_GENERATE_URL`** (or a single **`TERRAMIND_WORKER_URL`**) for TerraMind workers. |
| **Auth and internal wiring** | JWT issuance and validation (**ranked**, store-gated **`POST`**, optional accounts), **official-client** registration when product enables it (`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`), **HMAC** or mTLS for **server→inference** calls. |
| **Leaderboards + ranked lifecycle** | Transactional store (SQLite on `/data` for reference, Postgres for prod) for **optional community** rows, **ranked** `round_id` / **`round_ticket`**, verified submits; **same read model** for optional Gradio **`/ops`**. |
| **Non-ranked default** | No required score ingest; manifests and **GET** reference payloads only if product enables (`rules/05`, `rules/13`). |
| **PRO / paywall-ready** | Reserve JWT claims (`features`, `tier`, `exp`) and route stubs per **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`** §3.1; game server **orchestrates** `POST .../pro/jobs` + poll as **control plane only** (small JSON, job ids, errors)—**heavy bytes** (Mapbox/Sentinel rasters, NPZ, final **`ProVisionBundle`** archives) stay on **`PRO_MATERIALIZATION_SERVICE_URL`**, **TerraMind** workers, or **object storage** behind **short-lived signed URLs** returned to the client (see **§0.1**). **Initial build:** entitlement endpoint **returns allowed** for **valid registered clients** (gate-aware client UX only). |

### 0.1 Control plane vs heavy data plane (normative)

**Intent:** The **`server/`** deployable is the **public game API**: auth, **rate limits**, **transactional** state (ranked tickets, optional POI rows, optional community aggregates), and **small JSON** coordination with workers. It is **not** a geospatial data warehouse, **not** a raster pipeline, and **not** a place to **download, hold, or re-stream** Sentinel COGs, Street View imagery, LFM-VL tensors, or other **large intermediate** EO/ML artifacts.

| Responsibility | **Belongs on `server/`** (typical) | **Belongs off `server/`** (mandatory) |
|------------------|-------------------------------------|----------------------------------------|
| **User-submitted map proposals** | **`POST .../poi`** (schema-strict), validation, rounding, persistence, moderation hooks when product ships (`rules/05`, POI docs). | POI **package build** (Mapbox/Sentinel fetch for accepted POIs) — **HF Jobs** + **`inference/*`** or batch workers. |
| **Guess / WGS84 writes** | **Ranked** `start` / `submit` / **`forfeit-*`** — store server-secret truth, accept **`guess_lat` / `guess_lon`**, verify with **small** haversine module (`§1.3`). Optional **`POST .../guesses/record`** (telemetry). | Any **hint** or **clue** generation (Street View pano math, LFM-VL, TiM forwards). |
| **PRO jobs** | Issue **`job_id`**, call workers with **HMAC/mTLS**, persist **status + metadata** (`content_version`, `bundle_id`, **signed `bundle_download_url`** TTL, caps-only **`tim_modality_outputs`** if needed for polling). | **STAC** queries, Sentinel **download**, **reproject/downsample**, Mapbox **fetch**, NPZ/tensor **assembly** — **`inference/pro_materialization_service/`**; **TiM / `_generate`** — **TerraMind worker**. |
| **SCAN play reads** | **`GET` manifests** and **indexes**; **HTTP 302 / 307** or JSON **`asset_url`** fields pointing at **CDN**, Dataset-backed static host, or worker-signed URLs (`rules/13`). | Re-fetching or **proxying** multi‑MiB clue bytes through Python RAM **when avoidable**; never **rehydrate** STAC on the hot path inside `server/`. |

**Heavy intermediate rule:** `server/` **must not** implement STAC clients, Sentinel COG readers, Street View Static API clients, or **downsample/reproject** pipelines for production paths. If **`httpx`** is used toward **`inference/*`**, request/response bodies should be **handles + JSON** (paths, presigned URLs, checksums, dimensions)—not **opaque gigabyte streams** buffered through the game process. **Exception (ADR only):** a constrained **development** stub that proxies a tiny canned bundle for CI; production must follow **signed URL** or **redirect** patterns.

**Client `baseUrl` unchanged:** Kotlin still calls **only** the game server for **session** semantics; **signed bundle URLs** are **minted by workers or storage** but **returned inside** game-server responses so clients never hold Hub tokens (`rules/13`).

---

## 1. Responsibilities the game server **owns**

### 1.1 Authentication and identity

- **Issue / refresh / revoke** short-lived **JWTs** for: ranked **start** / **submit** (`docs/RANKED-MODE.md`), optional **community** score `POST`, **`POST .../poi`**, future **PRO tab** materialization (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`), future **entitlements** (`rules/05`).
- **Validate** `Authorization: Bearer`, **`app_id`**, **`platform`**, **`build`**, optional **`sub`**, optional **`features`** / SKU claims (populate later from store receipts without changing route shape).
- **Anonymous device sessions:** Issue **JWTs without a user `sub`** for **session-only** clients so **GET** manifest / leaderboard / maps still require a token for **rate limit + cache** keys (`rules/05`, `rules/00`).

### 1.2 Official client and request integrity

- **Register** Android signing cert hash, iOS Team ID + bundle, desktop API key policy — store in DB or config; **reject** unregistered clients on gated **`POST`** paths when enabled (`rules/05` §Official client).
- **Service-to-service:** sign outbound calls to inference (`INFERENCE_HMAC_SECRET`, timestamps, nonce) or mTLS; **rotate** secrets via HF Space variables.

### 1.3 Ranked missions (trust boundary)

- **`POST /api/.../ranked/rounds/start`**: create `round_id`, issue **`round_ticket`**, persist **server-secret** ground truth, return **clue manifest** without truth—**do not** attach **`play_budget_ms`**, **`submit_deadline`**, or any server-enforced play timer (`docs/RANKED-MODE.md` §4).
- **`POST /api/.../ranked/rounds/{id}/submit`**: validate **`round_ticket`** + idempotency (**no** server play-time / deadline checks); optional **`client_reported_ms`**—**accept and persist** if present, **no** verification, **never** used for accept/reject or score; load secret truth; **compute verified `distance_km` / points**; persist **verified** row; return final payload.
- **Note on “calculations”:** The **only** numeric geometry that **must** remain co-located with the **ranked secret store** is **haversine (or product score) vs server-held WGS84** — it is **anti-cheat policy**, not Street View / VLM / TerraMind work. Implement with a **small, audited, pure-Python or Rust extension** module inside `server/` (no ML stack). If product ever mandates **isolation**, split to a **1-function “verify” microservice** behind localhost — optional ADR; default stays in-process for simplicity.

### 1.4 Leaderboards (server-backed surfaces)

- **Optional** **`GET` / `POST`** community per-`map_id` aggregates when shipped — sanitize, rate-limit, idempotency (`rules/05`, `docs/LEADERBOARD-MAP-POI-SCORES.md`).
- **Ranked-only** leaderboard segments read from **verified** rows.
- **Ops / Gradio** at **`/ops`**: read-only views over **same** store (`rules/12`).

### 1.5 Manifests, bundles, cache index

- **`GET /api/v1/maps`**, **`GET .../manifest`**, **`GET .../bundles/...`** with **`ETag` / `content_version`** — prefer **signed redirect URLs** or **JSON manifest entries** that point at **object storage / CDN** for large bytes; where the game server **does** attach bytes, keep them **prebuilt SCAN artifacts** (small clue stills) synced from **HF Jobs → Dataset**, not live EO pulls (`rules/13`). **Sync** from Hub to disk may run in a **sidecar cron** using **`huggingface_hub`** on infrastructure **associated with** the deploy, but **normative product stance** is: **do not** route Sentinel or pano **through** the game process—only **indexes + redirects + auth**. **No** TiM forward in the request path.

### 1.6 Orchestration (control plane only; no heavy data custody)

- **SCAN bundles:** Same as **§1.5**—manifests and **references** to clue assets built offline (`docs/GAME-ENGINE.md` §9). **Optional** live **`inference/*`** calls are **ops / batch** only (operators refresh caches)—not player-hot-path downloads inside `server/`.
- **Satellite / Intel copy:** optional **`httpx`** to **`lfm_vl_satellite_caption_service`** for **short JSON** captions only; **no** pulling COGs through the game tier.
- **PRO jobs:** **`POST /api/v1/pro/jobs`** validates JWT + rate-limit → **`POST`** small **`MaterializeRequest`** / job envelope to **`PRO_MATERIALIZATION_SERVICE_URL`** → that service performs **all** Mapbox/Sentinel **fetch + resample** and (per product) emits **presigned read URLs** or **external object keys** for **`vlm_image_set`** blobs and TiM handoffs → optional **`TERRAMIND_*`** calls with **handles** (NPZ URL + checksum), not inline float tensors → game server persists **`job_id`**, **`status`**, **`content_version`**, and returns to the client either **`bundle_download_url`** (+ metadata) or **`GET .../pro/bundles/{id}`** as **302** to storage. **Normative:** game server **does not** download Sentinel, **does not** buffer materialization intermediates for re-upload, and **does not** “reassemble” rasters in memory—only **merge JSON caps** (`tim_modality_outputs` summaries) into the **polling** payload when the product needs inline progress. **`GET .../pro/jobs/{id}`** returns **status + URLs**, not multi‑MiB bodies. Game server **never** runs on-device VLM or TerraTorch (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §4–§5, `docs/GAME-ENGINE.md` §12.2).
  - **`AiGuessStore` / `ai_lat` / `ai_lon`:** **Do not** persist PRO-job **`Coordinates`** here by default. Writes are **only** for **`map_id`**-keyed clue materialization, HF Jobs / Dataset ingest, or operator-approved pipelines — or when OpenAPI defines an explicit flag (e.g. **`register_ai_guess_row`**). **Why:** PRO pins are **user-chosen**; **`AiGuessStore`** is **catalog-scoped** synthetic truth for **`AI_GUESS`**. Blurring them **corrupts** the **AI vs golden** semantics, **circumvents** POI / moderation gates, and **inflates** artifact churn (**`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §1.1.1**).

### 1.7 POI ingest (optional)

- **`POST /api/maps/{map_id}/poi`**: schema-strict body; validation, rounding, storage (`rules/05`, POI doc).

### 1.8 Optional guess telemetry + ranked integrity forfeits

- **`POST /api/maps/{map_id}/guesses/record`** (when shipped): persist **non-ranked** guess coords + **client-reported** distance for **ops / analytics** only—**no** trust as score authority (`docs/GAME-ENGINE.md` §12.3, `rules/05`).
- **`POST /api/ranked/rounds/{round_id}/forfeit-reveal`** (when shipped): invalidate **`round_ticket`**, record **DNF/forfeit** when ranked UI offers **Reveal uplink** and the player accepts (`docs/RANKED-MODE.md` §4).
- **`POST /api/ranked/rounds/{round_id}/forfeit-assists`** (when shipped): same state transition when the player accepts **Street View description** and/or **useful-hint** tiers before `submit` (`docs/GAME-ENGINE.md` §9, **`docs/RANKED-MODE.md` §4**). OpenAPI may merge both into **`.../forfeit-ranked-integrity`** with a **`reason`** field. **`routes_ranked.py`** owns **submit** and all **forfeit-*** transitions.

---

## 2. Responsibilities the game server **does not** own

| Offloaded to | Examples |
|--------------|----------|
| **`inference/streetview_pano_service`** | WGS84 → pano availability, **heading/pitch policies**, radial sampling, **Static API URL build**, multi-frame selection, quota-aware retries (`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` §2). |
| **`inference/lfm_vl_hint_service`** | Model load, tokenization, image tensors, **`suggestions[]`** generation (`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`). |
| **`inference/lfm_vl_satellite_caption_service`** | Satellite VQA / caption / grounding JSON (`refs/satellite-vlm` prompts). |
| **`inference/pro_materialization_service/`** (name illustrative) | PRO **lat/lon** → Mapbox still + optional Sentinel-2 STAC fetch + **downsample** for on-device VLM + TiM contracts (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`, `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §5.3). |
| **TerraMind TiM / `terramind_v1_*_generate`** | **`demos/terramind_space/`**, dedicated worker Space, or **HF Jobs** → Dataset (`plans/2026-04-07-gradio-terramind-backend.md`, `plans/2026-04-07-tim-standalone-gradio-poi-dataset.md`). |
| **Non-ranked scoring** | **Client** `commonMain` (`docs/GAME-ENGINE.md` §0); server **does not** recompute casual round distance unless optional analytics endpoint is explicitly added. |
| **Hub uploads from clients** | Forbidden (`rules/13`). |
| **Sentinel / STAC / large raster custody** | **Never** in `server/` — all fetch, COG read, resample, and **default** bundle binary packaging on **`inference/pro_materialization_service/`** (or Jobs → object storage). |

---

## 3. Target `server/` layout (thin)

```text
server/
  pyproject.toml                    # fastapi, uvicorn, httpx, pydantic, python-jose, sqlalchemy + aiosqlite OR asyncpg,
                                    # huggingface_hub (sync only), structlog — NO torch / terratorch / transformers
  Dockerfile                        # HF Docker Space: USER 1000, EXPOSE 7860, CMD uvicorn
  README.md                         # env vars table, TOPOLOGY link
  docs/
    TOPOLOGY.md                     # sequence diagrams, all URLs, timeouts — mandatory when split deploys land
  src/nutonic_server/
    main.py                         # FastAPI app; mount_gradio_app(..., "/ops") optional
    api/
      routes_health.py
      routes_auth.py                # token, refresh, jwks or introspect stub
      routes_ranked.py              # start, submit, optional forfeit-reveal — uses scoring/haversine.py + ticket store
      routes_leaderboard.py         # optional community GET/POST
      routes_maps.py                # map list, manifests, bundle redirects
      routes_poi.py
      routes_proxy_hints.py         # optional: POST /internal/hints/refresh — or fold into routes_hints.py
      routes_pro.py                 # PRO job create/status — httpx → materialization + TerraMind; bundle GET
    services/
      jwt_service.py
      official_client_registry.py
      inference_client.py           # httpx AsyncClient + timeouts + retries + HMAC headers
      ranked_store.py               # SQLAlchemy models: rounds, tickets, secrets
      leaderboard_store.py
      poi_store.py
      manifest_sync.py              # optional: pull Dataset shards to disk
    scoring/
      haversine.py                  # ranked verification only; mirror geo_utils semantics (lon, lat order)
    gradio_app/
      leaderboard_ops.py
  tests/
    test_haversine.py
    test_ranked_flow.py             # mocked inference URLs
```

---

## 4. Environment variables (illustrative)

| Variable | Purpose |
|----------|---------|
| `STREETVIEW_PANO_SERVICE_URL` | Base URL for pano sampling (**internal**). |
| `LFM_VL_HINT_SERVICE_URL` | Standard LFM-VL hints. |
| `LFM_VL_SATELLITE_CAPTION_SERVICE_URL` | Satellite specialist. |
| `PRO_MATERIALIZATION_SERVICE_URL` | PRO Mapbox + Sentinel-2 fetch and **resize**; **internal** from game server. |
| `TERRAMIND_TIM_URL` / `TERRAMIND_GENERATE_URL` | Optional; PRO or EO clues need **on-demand** TiM / **`_generate`** — **worker** only (HTTP from game server; **not** a player push channel). |
| `TERRAMIND_WORKER_URL` | Optional single base if product collapses TiM + generate behind one router. |
| `INFERENCE_HMAC_SECRET` | Shared secret for server→inference requests. |
| `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` or symmetric secret | Per product policy; never in client. |
| `DATABASE_URL` | `sqlite+aiosqlite:///...` or Postgres. |
| `HF_TOKEN` | Server-only Dataset sync. |
| `CORS_ORIGINS` | Explicit list for web clients. |

---

## 5. HTTP client discipline (orchestration)

- **Per-upstream `httpx.Timeout`** (connect, read, write, pool) — e.g. pano service 30s, LFM 120s with **smaller** client-facing deadline + **asyncio.wait_for** guard.
- **Response size:** Prefer **JSON + URL handles** from workers; set **max read bytes** guards so a buggy upstream cannot **OOM** the game API process with a COG stream.
- **Circuit breaker** (optional `tenacity` or custom): after N failures, return **503** + `retry_after` for hint routes; **never** block ranked **submit** on hint Spaces (`rules/06`).
- **No raw inference base URLs** in client config — clients receive **time-limited signed URLs** or **paths** only **inside** authenticated game responses (`rules/13`, `inference/README.md`).

---

## 6. Hugging Face deployment

- **SDK:** `docker` in Space README YAML; **`app_port: 7860`** ([Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker)).
- **Persistence:** Ranked + JWT refresh rows need a **transactional** store — **Postgres** (Neon, Supabase) recommended for production; **SQLite** on attached **`/data`** acceptable for demos ([Storage](https://huggingface.co/docs/hub/storage-buckets)).
- **Cold start:** document for clients; **health** `GET /api/v1/health`; optional paid hardware to reduce sleep.
- **Secrets:** Google / Mapbox keys **only** if the game server ever proxies a **non-pano** map call — prefer **all** Street View keys **only** on `streetview_pano_service` (`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` §2).

---

## 7. OpenAPI and Kotlin parity

- **Health (normative):** **`GET /api/v1/health`** for liveness — same path in §6 (HF) and §8 **P0** (no separate “root” health unless OpenAPI documents an optional **`GET /health`** redirect for legacy probes).
- Single **`docs/openapi.yaml`** (or generated from FastAPI with export) — version **`/api/v1/...`**.
- **`kotlinx.serialization`** DTOs in **`nutonic/shared`** match field names and enums (`rules/05`, `rules/03`).
- **Ranked** DTOs: **no** client-supplied `distance_km` as authority (`rules/05`).

---

## 8. Phased delivery

| Phase | Deliverable | Exit criteria |
|-------|-------------|----------------|
| **P0** | FastAPI skeleton, **`GET /api/v1/health`**, OpenAPI stub, Dockerfile Space | Space boots on HF; port 7860 |
| **P1** | JWT issue/validate + **official client** registry (in-memory → DB) | Integration test: gated `POST` 401 without token |
| **P2** | **Ranked** start/submit + **`scoring/haversine.py`** + SQLite | E2E test: ticket + verified row |
| **P3** | **Optional** community leaderboard `GET`/`POST` + idempotency | Matches `rules/05` sanitization |
| **P4** | **`InferenceClient`** (optional): call **`inference/*`** for ops/batch refresh; or stub if **cache-only** SCAN | Mocked upstreams in CI |
| **P5** | Manifest / map list **GET** + optional Dataset sync job | Client hydrates without Hub token |
| **P6** | **`/ops` Gradio** read-only leaderboard | Same queries as REST |
| **P7** | **PRO** route forward to worker + poll (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md`) | Feature-flagged |
| **P8** | **Entitlements** claims in JWT + `require_feature` deps (stubs) | Ready for billing integration without API churn |

---

## 9. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Inference Space cold/slow | Cache last-good **`content_version`** row; return **503** with copy; client degrades per `rules/06` |
| Splitting ranked haversine to remote | Keep in-process unless ADR; **tiny** audited module |
| Gradio drift | Single `LeaderboardStore` query layer |
| SQLite on ephemeral disk | Use HF **`/data`** attachment or external Postgres |

---

## 10. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-07 | Initial thin game server plan; defers all generative / pano math to inference tier |
| 0.2 | 2026-04-12 | **PRO**: explicit **`PRO_MATERIALIZATION_SERVICE_URL`** chain + optional **`TERRAMIND_TIM_URL`** / **`TERRAMIND_GENERATE_URL`**; offload table row (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §4) |
| 0.3 | 2026-04-12 | **PRO / TiM**: merge **`tim_modality_outputs`**; persist **`Coordinates` → ai_lat/ai_lon** for **`AiGuessStore`** (`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §5, `docs/GAME-ENGINE.md` §12.2) |
| 0.4 | 2026-04-12 | **§1.8** optional **`guesses/record`** + ranked **`forfeit-reveal`**; **`routes_ranked`** owns ticket invalidation |
| 0.5 | 2026-04-12 | **§1.6 PRO jobs** — split **`AiGuessStore`** rules into sub-bullets; default **no** PRO → **`AiGuessStore`** write; link **`docs/PRO-TAB-VLM-ORCHESTRATION-SPEC.md` §1.1.1** |
| 0.6 | 2026-04-12 | **§0.1** control plane vs data plane: **`POST` POI** + **ranked lat/lon** as primary live mutations; **no** Sentinel/COG custody or heavy **retransmit** through `server/`; PRO **signed URLs** / **302**; **§1.5–§1.6**, **§5** aligned |
| 0.7 | 2026-04-13 | **§7–§8 P0:** normative liveness **`GET /api/v1/health`** (aligns §6 HF with §8 **P0**; optional documented **`GET /health`** redirect only) |

*End of plan.*
