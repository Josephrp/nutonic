# NU:TONIC — Cached data → POI hydration (ranked + non-ranked): gaps, implications, and implementation plan

**Date:** 2026-04-16  
**Status:** Engineering plan (normative for sequencing; product signs off on catalog size, spoiler policy, and store binary caps).  
**Authority:** `rules/13-client-cache-and-data-plane.md`, `docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`, `docs/GAME-ENGINE.md` §9–§13, `docs/RANKED-MODE.md`, `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`, `plans/2026-04-13-repo-state-gap-analysis.md`, backlog **IMP-080–084**, **IMP-081**, **IMP-082**, **IMP-090**, **IMP-120**.

---

## 1. Problem statement

**POI** in this plan means a **published playable location**: stable **`location_id`** under a **`map_id`**, plus **hydratable SCAN assets** (reference still, useful hints, optional Street View pack, satellite sidecar, narrative slots) and, for non-ranked only, **golden WGS84 truth**. **Ranked** adds **server-held truth** until `submit`, while the client must still render clues and, after human lock-in, the **AI marker** from **precomputed** coordinates without leaking golden truth to disk pre-submit (`rules/13`, `docs/RANKED-MODE.md`).

**Cached data** means: **embedded compose resources**, **persisted manifest envelope** (`GET /api/v1/cache/manifest` + ETag), **`GET /api/v1/bundles/{bundle_id}`** bytes, optional **`still_http_url`** fetches, and **`ranked_clue_pack.json`** — not live HF or game-server inference on the hot path.

This document lists **what is missing or incomplete** for POIs to **hydrate correctly** in both modes, then **implications** of closing those gaps, then a **phased plan**.

---

## 2. Current implementation map (brief)

| Layer | Non-ranked | Ranked |
|--------|------------|--------|
| **Catalog / map list** | `ContentCacheRepository.cachedDocument()` → `maps[]`; SCAN refresh merges **shipped** `manifest.full.json` when server redacts **and** `content_version` matches (`mergeShippedRoundTruth`) | Same catalog for `map_id`; **start** uses server `game_catalog.manifest_location_for_map` |
| **Round row resolution** | `CacheManifestDocument.locationForMap(mapId)` → **first** `locations[]` row for that `map_id` | `RankedClue` from `POST .../ranked/rounds/start` merged with **shipped** `mergeRankedClueWithPack` |
| **Reference still** | `still_bundle_id` / `still_http_url` via API, else `still_bundled_resource` compose path | Same priority in `WorldMapGameplayScreen` |
| **AI marker** | `AiGuessStore(manifestSnapshot)` → `ai_guesses` | **Same** `AiGuessStore` from **manifest only** — **does not** read `RankedCluePackDocument.ai_guesses` |

**Normative pipeline docs** already describe ranked clue packs including **`ai_guesses`** (`data/scripts/assemble_ranked_clue_pack.py` copies AI rows for ranked pool keys). The **Kotlin UI does not consume pack AI rows** today.

---

## 3. Unimplemented or incomplete features (required for full POI hydration)

### 3.1 Ranked — **`ai_guesses` from ranked clue pack (client)**

**Gap:** `WorldMapGameplayScreen` builds `AiGuessStore` only from `manifestSnapshot`. Shipped **`ranked_clue_pack.json`** may contain **`ai_guesses`** (generator supports it), but **no code** merges pack AI into lookup for ranked rounds.

**Symptom:** Ranked rounds with `ai_marker_phase_enabled == true` can show **no AI marker** after lock-in when the public manifest has **empty** `ai_guesses` (redacted wire) and the embedded full manifest also omits ranked-pool AI rows, even though the **ranked pack** carries them.

**Required work:**

1. Introduce a small resolver, e.g. `EffectiveAiGuessStore(manifest, rankedPack?, isRanked, mapId, locationId)` or merge lists: **manifest `ai_guesses` ∪ pack `ai_guesses`** with documented precedence (typically manifest wins for dev; pack wins for store ranked-only slices — **pick one** and document in OpenAPI/KDoc).
2. Wire `readShippedRankedCluePack()` into that resolver **when `rankedSession != null`** (suspend/read once per session or memoize).
3. Add **unit tests** in `commonTest` or `desktopTest`: ranked session + pack row with `ai_guesses` only in pack → marker coordinates resolve.

**Refs:** `nutonic/shared/.../WorldMapGameplayScreen.kt` (`aiGuessStore`), `ShippedRankedCluePack.kt`, `assemble_ranked_clue_pack.py`.

---

### 3.2 Non-ranked — **`mergeShippedRoundTruth` version gate**

**Gap:** Overlay of shipped `locations` / `aiGuesses` runs only when `networkOrPersisted.contentVersion == shippedFull.contentVersion`. If the server bumps **`content_version`** before the app ships a new embedded manifest, **redacted wire + old ship** → **no overlay** → empty locations → **gameplay blocked** (`nonRankedContentBlocked`).

**Required work (choose one policy and implement consistently):**

- **Policy A (strict):** Treat mismatch as “update required” UX: explicit banner, link to store / forced refresh — **no silent merge**.
- **Policy B (lenient offline):** Merge **by `map_id` union`**: for each shipped location row whose `map_id` exists in server `maps[]`, overlay truth/assists when wire row is missing, keyed by **`(map_id, location_id)`** even when top-level `content_version` differs — **only if product accepts** possible schema skew (needs validation step).
- **Policy C (channel split):** Compare **`engine_version`** + semver of **`ruleset_version`** per row instead of single global `content_version`.

Document the chosen policy in `rules/13` and `docs/GAME-ENGINE.md` §9 footnotes.

**Refs:** `ShippedManifestMerge.kt`.

---

### 3.3 Multi-POI per **`map_id`** (selection + resolution)

**Gap:** `locationForMap(mapId)` returns **`locations.firstOrNull { it.mapId == mapId }`**. Authoring (`data/catalog/`, POI trees) and docs (`docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md`) assume **many** `poi_*` / **`location_id`** under a dataset; a **map** may represent a **mission** with **multiple rounds** or pick-one POIs.

**Required work:**

1. **Data model:** Either enforce **one location per `map_id` for v1** in catalog lint, **or** extend SCAN → gameplay navigation to pass **`location_id`** (and server manifest to list **all** locations per map).
2. **UI:** Map hub row → “Play” must pass **`location_id`** when multiple exist.
3. **Server:** `manifest_location_for_map` today returns **one** row; ranked **start** uses that — needs **`POST` body `location_id` optional** or explicit **`round_pool`** draw if multiple ranked-eligible rows per map.

**Refs:** `ManifestPlayResolution.kt`, `server/.../catalog.py`, `ranked_round_start`.

---

### 3.4 **Bundle bytes disk cache** (client)

**Gap:** `getBundleStill` / `getHttpBytes` always hit the network. **`rules/13`** expects atomic commit of fetched blobs + version metadata for offline replay and bandwidth.

**Required work:**

1. **`BundleBlobStore`** `expect`/`actual` (parallel to `ManifestBlobStore`): key = **`bundle_id`** (+ optional `content_version` / sha256 from manifest).
2. After successful fetch, **write bytes** + small sidecar JSON (ETag, fetched-at); still load path: **disk → network → compose resource**.
3. Eviction policy (LRU / max MB) — product cap for mobile/desktop.
4. **Ranked:** Do **not** persist golden truth; caching **JPEG still** and clue JSON is allowed.

---

### 3.5 **Server catalog beyond static Python** (**IMP-120**)

**Gap:** Published maps/locations for hydration ultimately come from **`catalog_generated.py`** / optional `NUTONIC_MANIFEST_FULL_PATH`. There is **no** live **`POST .../poi`**, Dataset sync, or SQL-backed **LocationPoolService** as described in `plans/2026-04-07-complete-implementation-architecture.md` §4.

**Implications for POIs:** New POIs cannot enter player-visible cache until **CI/regenerate script** runs — **no** dynamic “community POI → next manifest” loop.

**Required work:** Track **`sync_server_catalog --mode sql`** + minimal CRUD or import job from `data/catalog/` → DB → manifest builder (see existing backlog).

---

### 3.6 **POI write path and official-client program**

**Gap:** `docs/LEADERBOARD-MAP-POI-SCORES.md` / `rules/05` describe **`POST`** POI for store builds; **no** matching FastAPI route was found in `server/src/nutonic_server` at plan time.

**Required for “hydrate from server after user submit”:** OpenAPI + server persistence + manifest inclusion pipeline + client “propose POI” flow — **large** cross-cutting surface (JWT, idempotency, sanitization).

---

### 3.7 **Ranked round ↔ catalog binding when server rotates `location_id`**

**Gap:** Client merges ranked pack by **`(map_id, location_id)` from `start` clue**. If server ever returns a **`location_id`** not present in the **shipped** pack (new server row, old app), assists and **pack AI** may be incomplete.

**Required work:** Contract tests + app behavior: **force update** or **degrade** (hide assist panels, disable AI phase) with telemetry — document in `docs/RANKED-MODE.md`.

---

### 3.8 **Narrative / prompt bundle hydration** (parallel to POI still)

**Gap:** `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md` L4–L5 (PromptBundle, LLM chrome) are **not** fully wired into `WorldMapGameplayScreen` narrative overlay beyond placeholders.

**POI impact:** Missions feel empty without **per-`map_id` / `location_id`** strings from shipped **`prompt_bundle.json`**.

**Required work:** Gradle embed + `NarrativeRepository` keyed like catalog (can share **`content_version`** policy with §3.2).

---

## 4. Implications of fully implementing the above

### 4.1 Security and spoiler hygiene

- **Ranked:** Any widening of merged manifest or pack data on disk must **re-run golden leak checks** (`assemble_ranked_clue_pack.py` already has `_assert_no_golden_leak`). Client-side caches must **never** write **`truth_lat` / `truth_lon`** for ranked pre-submit.
- **Community manifest exposure:** If **`NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH`** is mis-set in production, **full POI truth** leaks world-readable — ops risk. Mitigation: separate **internal** vs **public** manifest URLs or signed **player** manifests (future).

### 4.2 Binary size, CI time, and release coupling

- Full **`geoguessr_poi_120`**-style embeds increase **APK/IPA/DMG/MSI** size; **`:shared:validateCatalog`** must gate broken paths.
- **Version policy (§3.2)** couples **app store review** cadence to **server `content_version`** bumps — product must own release ordering.

### 4.3 Engineering complexity

- **Bundle disk cache** touches **every platform** `actual` + quota APIs (Web: IndexedDB vs localStorage limits for bytes — **may need** separate strategy from `Utf8BlobStore` JSON).
- **Multi-POI** touches navigation (`rules/01`), SCAN hub, OpenAPI, ranked **start** contract, and **idempotency** keys that may include **`location_id`**.

### 4.4 Testing

- Need **fixture** rounds: redacted manifest + shipped overlay + ranked pack **without** network; **E2E** for non-ranked row persist (**IMP-083** exit).
- **Contract tests:** OpenAPI ↔ FastAPI ↔ Kotlin for new fields (`location_id` on start, POI POST).

---

## 5. Phased implementation plan

Phases are **sequential** unless marked **∥**.

| Phase | ID | Scope | Exit criteria |
|-------|-----|--------|----------------|
| **P0** | HYDRATE-001 | **Ranked AI from clue pack** — merge `RankedCluePackDocument.ai_guesses` into effective `AiGuessStore` for ranked sessions; tests | Ranked UI test or unit test: AI marker appears when manifest `ai_guesses` empty but pack has row |
| **P1** | HYDRATE-002 | **Document + implement `content_version` merge policy** (choose A/B/C in §3.2); update `ShippedManifestMerge.kt` + tests | Decision recorded in `rules/13` + plan cross-link; SCAN blocked vs lenient behavior matches spec |
| **P2** | HYDRATE-003 ∥ | **Bundle disk cache** (`BundleBlobStore` + integrate into still `LaunchedEffect`) | Airplane-mode: second launch renders still from disk for `still_bundle_id` present in last manifest |
| **P3** | HYDRATE-004 | **Single vs multi-POI per map** — either lint “one row per map” **or** pass `location_id` end-to-end (client + OpenAPI + server `manifest_location`) | No silent wrong POI; catalog lint or UI tests |
| **P4** | HYDRATE-005 | **Server dynamic catalog** — `IMP-120` / SQL or import API feeding manifest + `sync_server_catalog` | New row appears in `GET /api/v1/maps` + manifest without editing `catalog_generated.py` manually |
| **P5** | HYDRATE-006 | **`POST .../poi`** (optional, gated) + pipeline into next manifest revision | OpenAPI + pytest + client stub flow per `rules/05` |
| **P6** | HYDRATE-007 ∥ | **Narrative PromptBundle** hydration in SCAN / gameplay (`shipped-cache` L4–L5) | Mission/map copy reads from embedded bundle keyed by `map_id` |

**Recommended order for “playable POI parity” before dynamic server POI:**

`P0 → P1 → P2 → P3`, then **`P4` → `P5`** as product enables community/catalog growth; **`P6`** in parallel once P0–P2 stabilize stills.

---

## 6. Traceability

| This plan § | Backlog / other plans |
|-------------|------------------------|
| §3.1 | **IMP-082** extension (ranked AI from pack); aligns `shipped-cache` §1 |
| §3.2 | **IMP-083** acceptance / redaction footgun (gap analysis v0.8+) |
| §3.3–3.5 | **IMP-081**, **IMP-120**, architecture **S1b/S3/S6** |
| §3.4 | **rules/13** “commit after hydration” |
| §3.6 | **IMP-061** official client + `docs/POI-PACKAGES-AND-OFFICIAL-CLIENTS.md` |
| §3.8 | `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md` §5 |
| §7 | Cross-check **IMP-110** / **IMP-111** / **IMP-113** / data-script SPECs vs stub inventory below |

---

## 7. Data-generation stubs and partial paths (inventory)

This section lists **remaining stubs** and **non-production defaults** on the **artifact → manifest → clue-pack** path (not general UI placeholders). Items are **verified against the repo** as of the plan date.

**Detailed replacement / implementation sequencing:** [`plans/2026-04-16-stub-replacement-implementation-plan.md`](2026-04-16-stub-replacement-implementation-plan.md) (workstreams **STUB-A** through **STUB-I**, CI dual lane, PR slices).

### 7.1 Inference workers (batch inputs → JSON / JPEG)

| Component | Stub / default behavior | What “real” generation requires |
|-----------|-------------------------|--------------------------------|
| **`inference/streetview_pano_service`** | Docstring: **“pano sampling stub + health”**. Without **`GOOGLE_MAPS_API_KEY`**, **`STREETVIEW_PROVIDER`** resolves to **stub** → **Pillow synthetic JPEGs** (`sample_frames.py`); **`/api/v1/pano/metadata`** returns **`status: "stub", pano_id: null`**. | **IMP-110**: normative file/line WBS — [`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](2026-04-18-streetview-google-perpendicular-sampling-full-scope.md) (**real Static `pano=`**, **`heading_mode`**, road providers, batch, tests); gap analysis **v1.4** **inference** row. |
| **`inference/lfm_vl_hint_service`** | Default **`LFM_VL_BACKEND=stub`**: `stub_infer.py` emits **deterministic coordinate-free captions**; **`narrative_fuse_text`** in stub path is **concatenation** (`dispatch.py` L50–52), not a fused model. CI and **`tools/batch_streetview_hints.py`** explicitly pin **stub** health. | **`transformers`** (Liquid weights) or **`openai_compatible`** upstream; optional Gradio **`/gradio`** for Spaces. |
| **`inference/lfm_vl_satellite_caption_service`** | **`LFM_SATELLITE_BACKEND=stub`**: stub caption string in tests and default dispatch. | Wire **transformers** / **openai_compatible** for Mapbox-still captions used in batch still pipeline (`shipped-cache` L1/L2). |
| **`inference/pro_materialization_service`** | **`POST /api/v1/materialize/stub`** remains a **backward-compatible** thin contract; P1 internal materialize is the “real” path; **STAC / full TiM** branches optional via **`[s2]`**. | **IMP-113** full PRO materialization + server **`InferenceClient`** timeouts (**IMP-092**). |
| **`inference/terramind_tim_local`** | **`inputs_build.py`** raises **`NotImplementedError`** for **unsupported `tim_modalities`** in auto-inputs — not all modality paths are built for batch TiM generation. | Extend **`inputs_build.py`** per modality matrix in **`rules/06`** / PRO spec; or restrict catalog to supported modalities until extended. |

### 7.2 `data/scripts` — LLM and narrative (optional tiers)

| Script | Stub / partial | Notes |
|--------|----------------|-------|
| **`narrative_llm_batch.py`** | **`--no-dry-run` explicitly “not implemented in this stub”** — exits with error; dry-run writes **empty `llm_sidecar.json`**. | Live batch must call Ollama/OpenAI (or HF Job) per **`docs/scripts/SPEC-narrative-llm-batch.md`**. |
| **`generate_useful_hints_llm.py`** | **`--enable-llm-polish` + `--no-dry-run`** prints that **backend wiring is out of scope for this repository stub** and exits **`EXIT_POLICY`**. | Polish either moves to **external inference** + HTTP client in script, or stays a **Job-only** step (`shipped-cache` §5). |
| **`generate_placeholder_bgm_wav.py`** | **Silent WAV placeholders** for BGM spec — unrelated to POI geometry but part of **shipped asset** pipeline. | Replace with real loops when audio pipeline ships (**IMP-051**). |

**Non-stub (real logic, but heuristic):** **`generate_ai_guess_fixture.py`** implements **`decoy_offset`**, **`random_seeded`**, **`tim_only`**, CSV, etc. — these are **valid offline producers** for `ai_guesses[]`, not service stubs. **TiM truth** still requires **external TiM exports** (`tim_dir` / JSONL).

### 7.3 `tools/batch_streetview_hints.py`

- **End-to-end** against **stub** pano + LFM services is **supported and tested** (`tools/tests/test_batch_streetview_hints.py` mocks stub health).
- **Pins** in batch output record **`stub_jpeg`** / **`lfm_backend: stub`** for provenance — downstream manifest assembly should treat these as **QA / dev-grade**, not production caption quality.

### 7.4 Server and OpenAPI (control plane vs hydration bytes)

| Surface | Stub language | Reality |
|---------|---------------|---------|
| **`docs/openapi.yaml`** | PRO **`POST /api/v1/pro/jobs`** / poll described as **stub control plane** in summaries. | **`server/main.py`** implements **in-memory job ids** + optional **HTTP forward** to **`pro_materialization_service_url`** when set — **partial real**, not pure no-op. |
| **`server/README.md`** | Lists **`STREETVIEW_PANO_SERVICE_URL`**, **`LFM_VL_*`**, **`TERRAMIND_WORKER_URL`** as **future placeholders** (not read in thin slice). | **IMP-092** **`InferenceClient`** must wire these for orchestrated batch / ranked-adjacent calls. |

### 7.5 Kotlin client (not data generators, but block “full” UX)

| Item | Role |
|------|------|
| **`WorldMapGameplayScreen`** **`worldMapShareScoreStub`** | **IMP-084** share hook not implemented. |
| **SCAN / PRO `NavStubButton` placeholders** | Checklist navigation only — do not produce POI bytes; listed to avoid confusing with **inference** stubs. |

### 7.6 Implications for §3 / §5 of this plan

- **Hydration correctness** (manifest + ranked pack + stills) can be **validated in CI** using **stub inference** outputs — **separate** from **production-quality** Street View + LFM-VL captions.
- Replacing stubs with **real backends** increases: **GPU/ZeroGPU cost**, **determinism** variance (caption drift → **manifest `content_version`** churn → **§3.2 merge policy** stress), and **secret management** (Google, HF, OpenAI) across **Jobs, Spaces, and local scripts**.
- **Recommended sequencing:** keep **stub inference** for **catalog lint + assemble_manifest + ranked clue pack** CI gates; add a **nightly** or **manual** “full quality” profile that runs **`batch_streetview_hints`** with **`transformers` / google** and fails on **hint policy** violations (`validate_hint_strings`), then bumps **`content_version`** intentionally.

---

## 8. Document history

| Version | Date | Notes |
|---------|------|-------|
| 0.1 | 2026-04-16 | Initial plan from repo audit of manifest, merge, gameplay, ranked pack, server ranked start, `rules/13`. |
| 0.2 | 2026-04-16 | Added **§7** inventory: inference stubs, partial LLM scripts, batch tool pins, server/OpenAPI notes, client share stub; **§6** trace row for §7. |
| 0.3 | 2026-04-16 | **§7** intro: cross-link **stub-replacement implementation plan** (`2026-04-16-stub-replacement-implementation-plan.md`). |
| 0.4 | 2026-04-16 | **Repo alignment:** parent **`plans/*`** + **`server/*`** + **`docs/openapi.yaml`** updated for **IMP-090**/**IMP-092**/**IMP-114** partial land and **CI** desktop **MSI/DMG** (see **`rules/11`**, gap analysis **v1.2**). |
| 0.5 | 2026-04-18 | **§7** **`streetview_pano_service`** row: **IMP-110** normative WBS — [`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](2026-04-18-streetview-google-perpendicular-sampling-full-scope.md); gap analysis **v1.4**. |
