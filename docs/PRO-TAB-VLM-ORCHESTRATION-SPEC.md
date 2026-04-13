# NU:TONIC — PRO tab: coordinate intelligence dashboard (Sentinel + Mapbox materialization, TiM, multi-image on-device VLM)

**Status:** Normative product/engineering spec for the **PRO** shell tab (`rules/01-navigation-architecture.md`).  
**Date:** 2026-04-07 (product intent refined 2026-04-12)  
**Authority:** Binds to `rules/06-server-vlm-tim-and-on-device-ml.md`, `rules/12-python-gradio-terramind-server.md`, `rules/13-client-cache-and-data-plane.md`, `rules/05-networking-leaderboard.md`, `rules/04-maps-and-gameplay.md`, `rules/08-ux-and-performance-footguns.md`, `docs/RANKED-MODE.md`, `docs/SCREEN-MUSIC-SPEC.md` (PRO shell uses `music_pro` + header music toggle), `docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`, `plans/2026-04-07-complete-implementation-architecture.md`, `plans/2026-04-07-terramind-gradio-spaces-comprehensive-demo.md`, `plans/2026-04-07-game-server-thin-orchestrator.md`, **`plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md`** (fetch + downscale implementation). **SCAN** play uses **cached Mapbox stills** as the **primary** reference, with **optional bundled assists** (Street View text, useful-hint tiers)—see **`docs/GAME-ENGINE.md` §9** (PRO is a **separate** surface).

**Topology (normative):** The **Kotlin client** talks **only** to the **game server**. For PRO jobs the game server calls a **standalone PRO materialization service** (separate deployable—not `server/` process) that pulls **Sentinel-2** (STAC) and **Mapbox** imagery, then **downsamples / reprojects** to **contract sizes** for (a) **on-device VLM** multi-image ingest and (b) **TerraMind TiM** / optional **`terramind_v1_*_generate`** ingest per **`rules/12`**. The game server **orchestrates** the **same TerraMind TiM worker** contract used for **HF Jobs / `map_id` cache hydration**, **merges** **`tim_modality_outputs`** (every **`tim_modality`** the run configured — schema-capped per modality, including **`Coordinates`**) plus optional **`terra_mind_generate_summary`** into the **`ProVisionBundle`**, and returns it to the client **alongside** bytes the on-device VLM consumes. For **`AI_GUESS`**, **`Coordinates` → `ai_lat` / `ai_lon`** is the **normative source** when **`AiGuessStore`** / Dataset rows are produced for a **`map_id`** clue pipeline; **PRO** bundles **always** include **`tim_modality_outputs`** for the dashboard, while **cache writes** follow **`map_id`** / explicit registration rules in §1.1 step 3 and **§1.1.1** (`docs/GAME-ENGINE.md` §12.2, `rules/06`, `rules/10`).

**Reference implementations (behavioral, not shipped in KMP):**

| Path | Use in this spec |
|------|------------------|
| `refs/VLMExample/` | **Reference stack for on-device inference is possible here:** `ModelRunner`, **`ChatMessage` with multiple `Image` parts + text** (one forward over a **series** of server-prepared images from `vlm_image_set`), streaming collapsed to **one-shot** UX; **outputs** parsed to **caption + labeled bounding boxes** (JSON). **Model weights** are **not** “reference-only”—they must **ship through the product build/publish pipeline** (§6.0). Progress UI in the reference may mirror **unpack / warm-load** of shipped assets as well as any optional delta fetch. |
| `refs/satellite-vlm/` | **Caption + grounding** training/eval: **normalized [0,1] bboxes**, labels—canonical prompt blocks for **on-device** JSON decode and optional server QA. |
| `plans/2026-04-07-tim-standalone-gradio-poi-dataset.md` | **TiM** band completeness, tensor shapes, Mapbox + Sentinel pairing—inform **materialization → TiM** size contracts. |

---

## 1. Purpose and non-goals

### 1.1 Purpose

The **PRO** tab is a **non-game coordinate intelligence dashboard** (`rules/01`): the user supplies **WGS84** (typed, pasted, or map pick) and optionally a **short natural-language ask** (schema-capped). The client **POST**s to the **game server**, which forwards to a **standalone PRO materialization service** that:

1. **Acquires** **Mapbox** (or equivalent) **static** basemap tiles/stills and **Sentinel-2** assets via **STAC** (service keys **never** in `commonMain`, `rules/04`).  
2. **Downsamples / crops / reprojects** rasters to **two families of contracts** documented in OpenAPI:  
   - **`vlm_image_set`**: one or more fixed-size images (e.g. RGB + false-color + cloud-mask preview) sized for the **shipped on-device VLM** RAM/token and **multi-image** message layout.  
   - **`tim_input_contract`** (when `enable_tim`): patch dimensions and **band sets** that satisfy **TiM** `tim_modalities` and **no-subset** rules (`rules/12`)—materialization **fails closed** if bands are insufficient.  
3. Returns those artifacts to the **game server**, which **runs or proxies TerraMind TiM** (and optionally **`terramind_v1_*_generate`** on a **dedicated TerraMind worker**) and **merges** **`tim_modality_outputs`** — **one capped sub-object per imagined `tim_modality`** (e.g. **NDVI**, **LULC**, **`Coordinates`**, … per IBM’s allowed set) — plus optional **`terra_mind_generate_summary`** into the **`ProVisionBundle`** returned to the client. **`Coordinates` → `ai_lat` / `ai_lon`** is written to **`AiGuessStore`** / HF Dataset rows **only** in contexts keyed by **`map_id`** (clue materialization, Jobs prefetch, operator-approved pipelines)—**not** by default for every **ad-hoc PRO** user pin (unless OpenAPI adds an explicit **`register_ai_guess_row`** flag for product-defined flows).

#### 1.1.1 Persistence boundary — PRO TiM `Coordinates` vs **`AiGuessStore`**

**Two different questions:**

| Question | Where the answer lives | Default persistence |
|----------|------------------------|---------------------|
| “What does TiM infer at **this user-chosen PRO pin**?” | **`ProVisionBundle.tim_modality_outputs`** (and PRO job / bundle storage) | **Job-scoped** — serve the dashboard + on-device VLM; **do not** treat as SCAN round truth. |
| “What **fixed synthetic guess** does **this published `map_id` round** ship for **`AI_GUESS`**?” | **`AiGuessStore`** / Dataset / bundle slice keyed by **`map_id`** + **`content_version`** | **Catalog-scoped** — HF Jobs, clue materialization, or operator pipelines; **not** every PRO completion. |

**If implementers default to “every PRO job → write `ai_lat` / `ai_lon` into `AiGuessStore`”:**

- **Semantic corruption:** **`AiGuessStore`** stops meaning “precomputed AI marker for this **published** round” and mixes **ad-hoc analyst pins** with **curated map rows**—**AI vs golden** leaderboard tracks and results copy become **uninterpretable**.
- **Abuse and pool hygiene:** User-chosen coordinates could **poison** or **churn** rows tied to **`map_id`** surfaces (hints, selection, ranked round pools) **without** going through **`POST .../poi`** schema, moderation, or idempotency (`rules/05-networking-leaderboard.md`, `docs/RANKED-MODE.md`).
- **Privacy / retention:** Persisting every PRO **`Coordinates`** as durable catalog data resembles building a **shadow log of user-selected locations**; keep PRO outputs **ephemeral or job-keyed** unless a **documented** product path (e.g. explicit **`register_ai_guess_row`**) says otherwise.
- **Ops cost:** Blind writes amplify **Dataset sync**, **`content_version` bumps**, and **cache invalidation** for unrelated clients.

**Normative rule:** **`tim_modality_outputs.Coordinates`** in a **PRO** response is **always** valid for **PRO UI** (crosshair, strip, optional map pin). Copy into **`AiGuessStore` / `ai_lat` / `ai_lon`** **only** when OpenAPI context is **`map_id`**-bound (clue pipeline, Jobs row, operator registration) or when **`register_ai_guess_row`** (or successor) is **true** by explicit product contract.

**On the device**, the **VLM** consumes the **`vlm_image_set`** (series of images in **one** forward where the engine supports it, or a **documented** small number of forwards collapsed in UX) and produces:

- A **caption** (user-visible prose).  
- **Bounding boxes with labels** in **strict JSON** (normalized **[0,1]** coordinates relative to the **declared canonical surface**—typically the primary Mapbox still; document per bundle, `refs/satellite-vlm` alignment).

**On-screen result (normative):** a **layered composite**:

1. **Base layer** — Mapbox (or equivalent) still from bundle.  
2. **Server EO / Sentinel layers** — semi-transparent masks, SCL-derived hints, or simplified vectors from materialization (not full COG).  
3. **Server TiM / TerraMind dashboard strip** — **per-modality** cards fed from **`tim_modality_outputs`** (all **`tim_modalities`** configured for the run — logits, class names, **raster thumbs**, **`Coordinates`** point + confidence, etc., each **schema-capped**) plus **`terra_mind_generate_summary`** when used, so the user sees **what the server inferred** alongside local work.  
4. **On-device VLM overlay** — **stroke rectangles + labels** from parsed VLM JSON, drawn above base (dashed style when overlapping server-verified boxes per §7.4).  
5. **Caption + ask reply** — dedicated panel or card: **VLM caption** plus optional echo of **user ask**; **server dashboard** content is visually distinct (e.g. “UPLINK / TiM” cluster per **`docs/DESIGN.md`** tokens).

**Routing implication:** For some missions or flags, product may route heavy **`_generate`** work so the **TerraMind deployment returns the primary visual narrative**, and the on-device VLM only **refines boxes** or is skipped—OpenAPI must expose `pro_inference_route` (see §5). Default remains **on-device VLM primary** with **full `tim_modality_outputs`** from server for the PRO strip and for **Jobs/cache** parity.

### 1.2 Non-goals

- **PRO is not** the **SCAN** geo-guess loop; it does not replace **lock-in guess** or **ranked round tickets**.  
- **Raw** Sentinel COGs, full float **H×W×C** TerraTorch tensors, or **unbounded** `*_generate` rasters are **not** shipped to clients—only **downsampled** images and **schema-capped** JSON (`rules/06`, `rules/12`).  
- **Clients do not** call the **materialization** or **TerraMind** base URLs; only the **game server** does (`rules/13`).  
- **Streaming tokens** are **optional**; default is **one-shot** completion for predictability.

---

## 2. High-level architecture

The **game server** is the **only public orchestrator** clients call. It delegates **heavy IO + resampling + STAC/Mapbox** to a **standalone PRO materialization service** (`PRO_MATERIALIZATION_SERVICE_URL`), then calls **TerraMind workers** (`TERRAMIND_TIM_URL`, optional `TERRAMIND_GENERATE_URL`) with **payloads that already match** modality and size contracts. The game server **assembles** the **`ProVisionBundle`**, stores or signs download URLs, and never runs **torch** in-process (`plans/2026-04-07-game-server-thin-orchestrator.md`).

```mermaid
sequenceDiagram
  participant U as User (PRO tab)
  participant C as NU:TONIC client (KMP)
  participant G as Game server (thin)
  participant P as PRO materialization service (standalone)
  participant M as Mapbox CDN
  participant S as STAC / Sentinel
  participant T as TerraMind worker (TiM / optional generate)

  U->>C: Submit lat, lon (+ optional ask)
  C->>G: POST /api/v1/pro/jobs
  G->>G: Validate JWT, rate-limit, job_id
  G->>P: POST /internal/pro/materialize (coords, bbox, modes)
  P->>M: Mapbox static fetch
  P->>S: Sentinel L2A (policy-limited)
  P->>P: Downsample → vlm_image_set + tim_input_contract
  P-->>G: Artifact handles + numpy-safe sidecars / PNG series
  opt enable_tim or generate
    G->>T: TiM and/or _generate with sized tensors
    T-->>G: tim_modality_outputs (+ optional generate_summary; schema-capped)
  end
  G->>G: Merge ProVisionBundle + content_version
  loop Poll
    C->>G: GET /api/v1/pro/jobs/{job_id}
    G-->>C: status, bundle_url when READY
  end
  C->>G: GET bundle (If-None-Match)
  G-->>C: ProVisionBundle bytes
  C->>C: On-device VLM: multi-image → caption + bbox JSON
  U-->>C: Layered image + server dashboard + caption
```

**Alignment:** **Geospatial → resize → TiM / generate** follows `plans/2026-04-07-terramind-gradio-spaces-comprehensive-demo.md` and `plans/2026-04-07-tim-standalone-gradio-poi-dataset.md`; **split deployables** are documented in **`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`** §5.3.

**Internal HTTP path (disambiguation):** the game server’s call to the standalone materialization tier is **`POST /internal/pro/materialize`** (private network, HMAC/mTLS per thin orchestrator plan). It is **not** a client-visible URL; document the exact path in **`server/docs/TOPOLOGY.md`** if you rename routers.

---

## 3. Ranked play and PRO (UX boundaries)

| Concern | Rule / doc | Implication for PRO |
|--------|------------|----------------------|
| **Ranked rounds** | `docs/RANKED-MODE.md`, `rules/06` | **PRO** is a **separate** shell tab from **SCAN** ranked play; keep **navigation and job state** disjoint so operators do not conflate an **active ranked** session with a **PRO** materialize job. |
| **User POI proposal** | `rules/05`, `docs/RANKED-MODE.md` §4 | If PRO “send to server” is used to **propose a POI**, use **`POST /api/v1/maps/{map_id}/poi`** with the **OpenAPI** body (`rules/05`). |
| **Server payloads** | `rules/06` | Fields on **`POST`** paths follow **OpenAPI** DTOs. |

### 3.1 PRO entitlement (initial build)

- **Client:** **PRO** entry points are **gate-aware** (disabled UI, upsell copy, or hidden actions when `features.pro` is false)—product may still show the tab shell.
- **Game server:** For **valid registered clients**, **`GET /api/v1/pro/entitlement`** (or JWT claim `features.pro`) **always returns allowed** in the **initial build**, so engineering can ship **gated UX** before billing is wired. Tighten to real **SKU / receipt** checks in OpenAPI when product enables paywalls (`plans/2026-04-07-game-server-thin-orchestrator.md`).

---

## 4. Server responsibilities (orchestration)

### 4.1 Game server (thin)

- **Clamp** `latitude` ∈ [−90, 90], `longitude` ∈ [−180, 180]; **reject** NaN/Inf; **precision** ≤ 6 dp in logs (`rules/05`).  
- **Rate limits** per **IP / device id / JWT sub** on `POST .../pro/jobs`; **caps** on `bbox_half_km`, bytes, bundle size (e.g. **≤ 8–12 MiB** gzip mobile), max concurrent jobs.  
- **`POST .../pro/jobs`** → internal **`PRO_MATERIALIZATION_SERVICE_URL`** (HMAC/mTLS per **`plans/2026-04-07-game-server-thin-orchestrator.md`** §0.1); then optional **`TERRAMIND_TIM_URL`** / **`TERRAMIND_GENERATE_URL`** using **handles** (URLs, checksums) produced by materialization—**not** by re-hosting Sentinel COGs or large NPZ streams inside the game process. **Normative:** the game server is **control plane** (JWT, job ids, **poll JSON**, **signed `bundle_download_url`** or **HTTP redirect** to object storage for **`ProVisionBundle`** bytes per §5); **heavy raster IO** stays in **`inference/pro_materialization_service/`** and TerraMind workers. **No** `torch` in `server/`.

### 4.2 Standalone PRO materialization service

**Separate deployable.** Mapbox + Sentinel STAC fetch, **downsample** to **`vlm_image_set[]`** contract sizes and to **patch / band tensors** matching **`_*_tim`** modality rules for the TerraMind worker; **fail closed** on insufficient bands (`rules/12`). May colocate TiM only if ADR; default is **IO here, GPU on TerraMind worker** (`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §5.3).

### 4.3 TerraMind worker (GPU)

**TiM** → **`tim_modality_outputs`** (keys = requested **`tim_modalities`** subset; each value **OpenAPI-discriminated** — no raw H×W×C float tensors on the mobile bundle). **`Coordinates`** values **must** include **`latitude`**, **`longitude`** (WGS84), optional **`confidence`** — **always** for **PRO** bundle / dashboard display. **Hydration into `AiGuessStore` / `ai_lat` / `ai_lon`** uses the **same** payload shape but **only** under **`map_id`** / operator / **`register_ai_guess_row`** rules in **§1.1.1** — not for every ad-hoc PRO job (`docs/GAME-ENGINE.md` §12.2). Optional **`_generate`** → **`terra_mind_generate_summary`** when `pro_inference_route` requires server-primary narrative (`§1.1`).

### 4.4 Optional server VLM QA

**`lfm_vl_satellite_caption_service`** for ops/QA only—not default PRO path.

### 4.5 Downstream efficiency

**One** client **`GET`** after `READY`; **`ETag` / `content_version`** (`rules/13`). **No** full COGs or raw float tensors on device.

---

## 5. ProVisionBundle (normative client-visible contract)

Illustrative JSON header (bytes may be **CBOR** or **zip**; OpenAPI must fix one):

| Field | Type | Description |
|-------|------|-------------|
| `bundle_id` | UUID | Unique materialization id. |
| `content_version` | string | Monotonic or semver for cache invalidation. |
| `cache_key` | string | Server-computed hash of inputs (lat, lon, half_km, fetch modes, map zoom, policy ids, VLM model id). |
| `pro_inference_route` | enum | `ON_DEVICE_VLM_PRIMARY` \| `SERVER_TERRAMIND_GENERATE_PRIMARY` \| `HYBRID` — controls whether **`terra_mind_generate_summary`** is the dominant narrative vs on-device caption (`§1.1`). |
| `vlm_image_set` | array | Ordered list of `{ "role", "url" \| "inline_ref", "width", "height", "mime" }` — **all** sizes must match the **shipped** on-device VLM contract for this `model_bundle_id`. **Multi-image** single forward. |
| `canonical_surface_id` | string | Which **`vlm_image_set`** entry defines **[0,1]** bbox normalization (usually `mapbox_rgb`). |
| `image_width` / `image_height` | int | Dimensions of **`canonical_surface_id`** (redundant OK for fast path). |
| `mapbox_attribution` | string | Required legal text. |
| `sentinel_attribution` | string | Optional, if Sentinel used. |
| `overlays` | array | Server-drawable hints: SCL edges, cloud mask thumb, TiM-derived simplifications—see §7. |
| `tim_modality_outputs` | object? | Present when TiM ran. **Keys** = the **`tim_modalities`** list configured for that forward (subset of IBM-allowed modalities). **Values** = **discriminated** capped payloads, e.g. `{ "kind": "class_logits", "top_k": [...] }`, `{ "kind": "raster_thumb", "url" \| "inline_ref", "width", "height" }`, `{ "kind": "coordinates_wgs84", "latitude": number, "longitude": number, "confidence"?: number }` for **`Coordinates`**. **Normative:** the **`coordinates_wgs84`** payload is the **shape** the game server uses when persisting **`ai_lat` / `ai_lon`** to **`AiGuessStore`** / Dataset for **`map_id`** clue pipelines only (**§1.1.1**). **PRO-only** jobs return the same field for **dashboard** use **without** implying an **`AiGuessStore`** write. **No** full float patch tensors on device. |
| `tim_summary` | object? | **Legacy / optional:** aggregate cross-modality metrics if product still wants a single small object; prefer **`tim_modality_outputs`** for new OpenAPI. |
| `terra_mind_generate_summary` | object? | Present when **`_generate`** path used; schema-capped thumbs + text fields for **dashboard strip**. |
| `vlm_prompt_injection` | object? | Optional short strings merged into the on-device prompt template. |
| `on_device_model_hint` | string | e.g. `LFM2.5-VL-1.6B` + quant—client checks compatibility. |
| `materialization_revision` | string | Pin compatibility between client parser and materialization output shape. |

**Legacy:** A single `canonical_image` field may alias **`vlm_image_set[0]`** during migration—OpenAPI should prefer **`vlm_image_set`**.

---

## 6. On-device VLM (client)

### 6.0 Build, publish, and model artifacts (normative)

- **Ship with the product:** On-device VLM **checkpoint(s)**, tokenizer or runtime metadata, and any **LEAP / engine** files required at inference time are **part of the shipped app artifact**, produced by the same **KMP / Gradle build and store publish pipeline** as the rest of NU:TONIC (e.g. packaged under `composeResources`, Android `assets`, or an equivalent per-target bundle). **CI** must verify expected **files exist**, **size bounds**, and **`model_bundle_id` / revision** alignment with the **`on_device_model_hint`** and **`ProVisionBundle`** contract the materialization tier targets (`plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md` §4.1).
- **No mystery weights on device:** Production builds do **not** depend on the Hugging Face Hub, `hf` CLI, or arbitrary user-provided URLs for **core** PRO inference (`rules/13-client-cache-and-data-plane.md`). Optional **delta** updates (newer quant) require **OpenAPI-defined** URLs, **integrity hashes**, version gating, and explicit product sign-off—**default** remains **bundled-with-build**.
- **Inference is a port of `refs/VLMExample/`:** The **behavioral contract** for running the shipped model over **`vlm_image_set`**—session setup, multi-image message layout, forward, parse caption + JSON boxes—is **`refs/VLMExample/`**. KMP code uses **`expect`/`actual`** (or shared engine wrappers) to match that behavior per target (§6.2).

### 6.1 Behavioral port of `refs/VLMExample/` (multi-image)

- **Model acquisition (primary):** Load weights from **app-shipped** assets bundled in the **build/publish** output; revision must match **`model_bundle_id`** / `on_device_model_hint` agreed with materialization. **Optional UX:** reuse the **download / progress** patterns from **`refs/VLMExample/`** (`LeapModelDownloader`, `observeDownloadProgress`) for **first-run copy**, **decompress**, or **warm-load** into fast storage—not as a substitute for shipping weights through CI and store binaries. A **platform-neutral** wrapper is fine where LEAP is not used (`rules/06`).  
- **Inference:** Build **one** `ChatMessage` with `ChatMessageContent.Text` (system + user ask + **`vlm_prompt_injection`** + fixed instruction: *output caption + JSON array of `{label, bbox}` in [0,1] vs `canonical_surface_id`*) and **multiple** `ChatMessageContent.Image` parts in **`vlm_image_set` order**. If the SDK requires **single-image** calls, run a **documented** merge (e.g. grid collage) **only** if bbox normalization is updated to that collage—prefer **native multi-image** when available.  
- **Outputs:** Parse assistant text into **(a)** human-readable **caption** and **(b)** **bbox list**; validate JSON in **`commonMain`** before drawing.  
- **One-shot UX:** Aggregate streaming to **one** result state; then run **layer composer** (§7).

### 6.2 Multiplatform parity (`rules/06`, `rules/00`)

`refs/VLMExample` today is **Android-only** (LEAP SDK + Coil in `app/build.gradle.kts`). **On-device VLM is required only for targets that ship the PRO tab** (`rules/00-product-intent.md`).

| Target | Requirement |
|--------|-------------|
| **Android** | Reference path: **LEAP** as in `refs/VLMExample/`. |
| **iOS / Desktop / Web** | Ship **PRO** with **equivalent** on-device VLM behind **`expect`/`actual`**, or **hide / degrade PRO** on that target until parity lands—**no** requirement for SCAN gameplay. Optional **server-only caption** fallback remains **OpenAPI-defined** and **product-gated**. |

**ADR trigger:** Record interim parity in this document’s version table and in `rules/06` if PRO ships on a subset of targets first.

### 6.3 Prompting discipline

- **System prompt:** Fixed template in client resources; **no** user-controlled system strings.  
- **User ask:** Max length (e.g. 500 chars), stripped control chars.  
- **Image-grounding ask:** For **bbox JSON** output mode (satellite-vlm style), client may append a **fixed** instruction block mirroring `refs/satellite-vlm/README.md` (“normalized 0–1, valid JSON array”).  
- **Injected facts:** Only keys present in `vlm_prompt_injection`.

---

## 7. Overlays and rendering (all platforms)

### 7.1 Coordinate systems

- **Normalized bbox** — `[x1, y1, x2, y2]` in **0–1** relative to **`canonical_image`** width/height (same as satellite-vlm eval).  
- **Geo bbox** — Optional `west,south,east,north` for a **corner bracket** HUD; map still is **static** for PRO v1 (no full `MapViewport` engine required if product accepts **Compose Image + drawWithCache** overlays).

### 7.2 Drawing order (layered PRO canvas)

1. **Base:** Primary **`vlm_image_set`** still (typically Mapbox RGB) scaled to compositor size.  
2. **Server EO rasters:** Sentinel cloud / SCL / false-color from **`overlays`** at aligned resolution.  
3. **Server TiM / generate hints:** Simplified vectors, **coordinate crosshair** (from **`tim_modality_outputs.Coordinates`** when present), or heat pixels from **`tim_modality_outputs`** / **`terra_mind_generate_summary`** when product maps them to drawable primitives.  
4. **On-device VLM boxes:** Rectangles + **labels** from parsed JSON (**dashed** where §7.4 marks “model estimate”).  
5. **Caption + dashboard chrome:** **Caption** text block; adjacent **server summary** panel (**per-modality** rows from **`tim_modality_outputs`**) using **`docs/DESIGN.md`** semantic tokens—distinct from VLM caption so users can compare sources.  
6. **HUD chrome:** Scanlines / grid **off** when **reduced motion** (`rules/08`).

### 7.3 Client rendering parity

- **Android / iOS / Desktop:** `Canvas` or `graphicsLayer` with **device pixel ratio** scaling so 0–1 boxes align.  
- **Web (wasm/js):** Same math; test **one** reference bundle across targets in CI snapshot tests (`rules/11`).

### 7.4 Optional on-device bbox parse

If the VLM returns **JSON** in the assistant text, client may **parse** (strict schema) and **merge** with server overlays: **server wins** on conflict for **verified** layers; VLM-only boxes show as **dashed** “model estimate” per design tokens (`rules/02`).

---

## 8. UX: loading messages and state machine

**Job lifecycle** (`job_status`):

| Status | User-facing copy (themeable) | Client behavior |
|--------|------------------------------|-----------------|
| `QUEUED` | “UPLINK QUEUED…” | Show position in queue if server sends `queue_depth`. |
| `FETCHING_MAP` | “IMAGING STRIP ACQUIRED…” | Game server / materialization fetching Mapbox. |
| `FETCHING_SENTINEL` | “SPECTRAL CHANNELS OPEN…” | Materialization pulling STAC; **cancel** if product allows. |
| `RESIZING` | “NORMALIZING PATCH…” | Materialization downsampling for **VLM + TiM** contracts. |
| `TERRAMIND_PROCESSING` | “TERRAMIND DECODE…” | TiM / **`_generate`** on worker; **30–120s** cold GPU copy (`rules/06`). |
| `PACKAGING` | “COMPRESSING PACKET…” | Game server assembling **ProVisionBundle**. |
| `READY` | “DATA READY — RUNNING LOCAL VLM…” | Client download + **multi-image** infer + compose layers. |
| `DOWNLOADING_MODEL` | “NEURAL CORE LOAD…” | Mirror VLMExample percentages when using LEAP. |
| `INFERENCING` | “ANALYZING PATCH…” | Spinner + **cancel inference** only if engine supports safe cancel. |
| `DONE` | (final message shown) | Persist bundle ref in local cache for replay (`rules/13`). |
| `FAILED` | “UPLINK INTERRUPTED” | Map to structured `error_code` from server (`rules/05` errors footgun). |

**Footguns (`rules/08`):** First **~100ms** feedback on tap: optimistic **QUEUED** transition; **glow discipline** on primary send button (`rules/02`).

---

## 9. OpenAPI sketch (illustrative)

Implementers replace paths and wire **OpenAPI** components per product.

- **`POST /api/v1/pro/jobs`**  
  - Body: `{ "latitude": number, "longitude": number, "bbox_half_km"?: number, "user_ask"?: string, "sentinel_fetch_mode"?: "MINIMAL_RGB" | "TERRAMIND_SPECTRAL" | "FULL_STAC", "enable_tim"?: boolean, "tim_modalities"?: string[], "pro_inference_route"?: "ON_DEVICE_VLM_PRIMARY" | "SERVER_TERRAMIND_GENERATE_PRIMARY" | "HYBRID" }` — **`tim_modalities`** must be a **subset** of IBM-allowed imagined modalities when `enable_tim` is true; server may **override** route or modality list for policy / capacity. Include **`Coordinates`** when product wants **TiM-derived** map pin / **AI-guess** hydration.  
  - Response: `{ "job_id": "uuid", "poll_url": "...", "estimated_seconds": number }`

- **`GET /api/v1/pro/jobs/{job_id}`**  
  - Response: `{ "status": "...", "progress": 0.0-1.0, "message_key": "FETCHING_SENTINEL", "bundle_url"?: "...", "content_version"?: "...", "error"?: { "code": "...", "detail": "..." } }`

- **`GET /api/v1/pro/bundles/{bundle_id}`**  
  - Headers: `ETag`, `Cache-Control`  
  - Body: binary per §5

- **Optional:** **`DELETE /api/v1/pro/jobs/{job_id}`** — best-effort cancel.

**Auth:** **`POST /api/v1/pro/jobs`** (and poll **`GET`**) use the same **game-server session / JWT** model as other authenticated APIs (`rules/05-networking-leaderboard.md`) so the server can **rate-limit** and **cache** materialization. **Initial entitlement** behavior: **§3.1**.

---

## 10. Caching and offline (`rules/13`)

- **Disk cache** under stable key: `pro_bundle:{cache_key}` + `content_version`.  
- **Commit-after-download:** atomic write of manifest + binary.  
- **Offline:** If `GET` fails, offer **last successful bundle** for same `cache_key` with badge “CACHED SNAPSHOT”.  
- **No Hub tokens** on device; bundles only from **game server** or agreed CDN signed by server.

---

## 11. Performance and resource budgets

| Resource | Guidance |
|----------|----------|
| **Bundle size** | Target **≤ 4–8 MiB** gzip for mobile; desktop may allow larger **only** by explicit user setting. |
| **VLM RAM** | Document **minimum** RAM per model quant; refuse start with clear UI if below threshold. |
| **CPU/GPU time** | Cap on-device max tokens and **image max side** to preserve thermal budget (`rules/06`). |
| **Server GPU** | TiM / generate behind worker queues; **503 + Retry-After** when saturated (`rules/12`). |

---

## 12. Relation to `refs/satellite-vlm` (training reference)

That repo demonstrates **fine-tuning** LFM VLMs on **VRSBench** (VQA, grounding, captioning). For **PRO**:

- **Training** remains **offline** (Modal, leap-finetune)—not in the app.  
- **Inference prompt and eval format** inform how we ask for **JSON bboxes** and how server **validates** IoU-style overlays in **batch QA** of bundles—not necessarily at runtime on server.  
- **Grounding quality:** If on-device model is **general** LFM rather than satellite-finetuned, expect **weaker** literal grounding; **server-side** optional grounding remains the **quality bar** for box truthiness.

---

## 13. Implementation checklist

- [ ] OpenAPI for §9 + §5 schema published beside server.  
- [ ] KMP DTOs + `ProJobRepository` in `commonMain`; Ktor engines per target (`plans/2026-04-07-complete-implementation-architecture.md` §3.3).  
- [ ] `ProScreen` composable: chat transcript model, lat/lon inputs, map mini-picker optional, **state machine** §8.  
- [ ] `OnDeviceVlmPort` **expect/actual** with Android **LEAP** parity to **`refs/VLMExample/`**; **Gradle / CI** packages **pinned** on-device model artifacts with the release.  
- [ ] `ProOverlayRenderer` shared math for 0–1 bboxes.  
- [ ] **PRO materialization service**: Mapbox + Sentinel + resize contracts; contract tests vs VLM + TiM matrix.  
- [ ] Game server: **control-plane** orchestration **P → TiM → bundle** (JSON + **signed download URLs** / redirects per **§4.1**); **no** Sentinel/COG proxy through `server/`; persist **`tim_modality_outputs`** to **`AiGuessStore`** / Dataset **only** for **`map_id`** clue pipelines (incl. **`Coordinates` → ai_lat/ai_lon** per **§1.1.1**); **PRO** path returns full **`tim_modality_outputs`** **without** writing PRO-only jobs into **`AiGuessStore`**; integration tests with canned lat/lon.  
- [ ] Attribution strings visible in UI footer on image card.  
- [ ] **Ranked vs PRO:** integration test keeps **SCAN ranked** job IDs disjoint from **PRO** job IDs in the client shell.  
- [ ] **Reduced motion** and **high contrast** paths for animations (`rules/08`, `docs/CLIENT-SETTINGS-SPEC.md` if applicable).

---

## 14. Version history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-07 | Initial spec: PRO chatbot, server orchestration, downsampled bundles, on-device VLM, overlays, states, rules alignment |
| 0.2 | 2026-04-12 | **§3.1** initial entitlement (always-allow valid clients); **§6.2** PRO-only on-device scope; **§9** auth aligns with session JWT; SCAN hints = bundled (authority header) |
| 0.3 | 2026-04-12 | **Coordinate dashboard** intent; **standalone materialization** + **TiM/merge**; **multi-image** on-device VLM → caption + bboxes; **layered UI** + `pro_inference_route`; **`vlm_image_set`** bundle contract; **§4** split (**game server** vs **materialization** vs **TerraMind worker**) |
| 0.4 | 2026-04-12 | **`tim_modality_outputs`** replaces single **`tim_summary`** as normative; **all `tim_modalities`** schema-capped; **`Coordinates` → `ai_lat`/`ai_lon`** for **`AiGuessStore`** / **cached AI-guess** (`docs/GAME-ENGINE.md` §12.2); §9 **`tim_modalities`** request field |
| 0.5 | 2026-04-12 | **§6.0** — on-device VLM weights **ship with build/publish** + CI alignment to `model_bundle_id`; **`refs/VLMExample/`** as normative **inference** port; **§6.1** clarifies bundled weights vs optional warm-load/delta |
| 0.6 | 2026-04-12 | **§1.1.1** — explicit **PRO TiM `Coordinates` vs `AiGuessStore`** persistence boundary, implications, and checklist tightening; **§4.3** / **`tim_modality_outputs`** table clarify display vs catalog writes |
| 0.7 | 2026-04-12 | **§4.1** — game server **control plane** only (signed **`bundle_download_url`** / redirect); **no** Sentinel/COG re-host through `server/`; **§13** checklist aligned (`plans/2026-04-07-game-server-thin-orchestrator.md` §0.1) |

*End of document.*
