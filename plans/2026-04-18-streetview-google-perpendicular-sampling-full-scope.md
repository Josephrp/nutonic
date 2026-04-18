# Street View: real Google imagery, stochastic sampling in a Sentinel-2–scaled footprint

**Status:** Normative implementation breakdown (WBS).  
**Authority:** Product intent (2026-04-18, revised): diversify Street View by **seeded random** sample anchors in a **local disk** around the round’s center; disk radius defaults from a **Sentinel-2–style ground extent** (10 m GSD × reference chip edge — **local** context, not a full L2A granule). **No** required road bearing, graph navigation, or external map APIs for “where to look.” Aligns with `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` (§2.2), `plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md` §5 Phase **D**, IMP-110, `docs/scripts/SPEC-batch-streetview-hints.md`, `rules/06-server-vlm-tim-and-on-device-ml.md`, `inference/README.md`.

**Scope:** Real Google Static + Metadata; **STOCHASTIC_S2_FOOTPRINT** default; **`pano=`** Static when metadata returns a pano; **random headings** per frame; reproducibility via **`jitter_seed`**; optional **`min_anchor_separation_m`** for “fair” spread; **`LEGACY_RADIAL_OFFSET`** preserved; optional pitch/FOV, URL signing, batch/HF wiring, health/`model_pins`, CI, docs. **Deferred (not DoD):** OSM / Mapbox / Google Roads / Tile API for bearing or walking; multi-pano graph walks.

**Non-goals:** Kotlin clients calling Google; golden coordinates in ranked packs; LFM policy via `validate_hint_strings.py` + prompts unchanged in principle.

---

## 0. Executive summary

| Gap today | Target |
|-----------|--------|
| `heading_mode` is a string with **no real implementation** in stub/Google. | **`sampling_mode`** (or constrained `heading_mode`) with **STOCHASTIC_S2_FOOTPRINT** default + legacy + optional omni single-pano. |
| Google path: **deterministic** offsets + **`i·360/n`** headings (`google_sample.py` ~L30–L55). | **Seeded random** anchors in disk radius **R** + **metadata per anchor** + **random heading** per successful snap; optional **min separation** between anchors. |
| Batch hardcodes **`radius_m: 120`** (`batch_streetview_hints.py` ~L135–L142). | Send **`area_radius_m`** (optional), **`jitter_seed`**, **`sampling_mode`**; **`radius_m`** = **legacy-only** when `LEGACY_RADIAL_OFFSET`. |

### 0.1 Sentinel-2 default radius (normative)

Sentinel-2 MSI **10 m** bands define a natural **GSD**. Use a **reference chip edge** `W_px` at that GSD; sampling uses a **disk** around catalog truth:

**`R_default = (W_px × g_m) / 2`**

| Env / constant | Default | Role |
|----------------|---------|------|
| `STREETVIEW_S2_GSD_M` (`g_m`) | **10** | S2 10 m GSD (convention). |
| `STREETVIEW_S2_CHIP_EDGE_PX` (`W_px`) | **512** | Reference chip → **5120 m** width → **`R_default = 2560 m`**. |

**Overrides:** request **`area_radius_m`** (server **max cap**, e.g. 15000 m); batch **`--pano-area-radius-m`**. Optional future (**PR-J**): derive **R** from **`still_index.json`** per-location ground footprint when present.

---

## 1. Work breakdown structure (projects)

| ID | Project | Outcome |
|----|---------|---------|
| **PR-A** | **API contract & DTOs** | `sampling_mode`, `jitter_seed`, `area_radius_m`, optional `min_anchor_separation_m`, `fov_deg`, optional `pitch_jitter_deg`, gated `sampling_debug`. |
| **PR-B** | **Google HTTP layer** | `pano=` vs `location=` Static; typed metadata + domain errors; optional URL signing. |
| **PR-C** | **Sampling core** | Stochastic default + legacy + optional `OMNI_SINGLE_PANO`; `cache_key` includes mode, **R**, seed, policy version. |
| **PR-D** | **Extent & PRNG** | `sampling_extent.py`: default **R**, uniform disk draw (reuse `offset_lat_lon`), haversine min-separation, attempt caps. |
| **PR-E** | **Stub parity** | Stub mirrors modes + seed in `cache_key` / synthetic headings. |
| **PR-F** | **Batch & Jobs** | JSON body + CLI; **`model_pins`**; renumber LFM ranks after chunk merge (`batch_streetview_hints.py` ~L377–388). |
| **PR-G** | **Observability** | Backoff, logs (`ZERO_RESULTS` drops, attempts, accepted count). |
| **PR-H** | **Testing** | Seeded determinism; min-separation; `pano=` URL assertions (mocks). |
| **PR-I** | **Documentation** | SPEC §S1, streetview plan §2.2, package README. |
| **PR-J** | **Optional** | Pitch/FOV jitter; manifest provenance; nightly Google; **R** from still metadata. |

**Dependencies:** PR-A → PR-B, PR-C; PR-D consumed by PR-C; PR-F after PR-C stable.

---

## 2. PR-A — `models.py` (approx. L13–L35)

| Task | Detail |
|------|--------|
| **A1** | Add **`sampling_mode`**: `STOCHASTIC_S2_FOOTPRINT` (default), `LEGACY_RADIAL_OFFSET`, `OMNI_SINGLE_PANO`. Map legacy string **`RADIAL_OR_RANDOM` → `LEGACY_RADIAL_OFFSET`**. |
| **A2** | **`jitter_seed: int | None`**: if `None`, derive stable seed from `request_id` (document algorithm, e.g. first 8 hex of SHA-256). |
| **A3** | **`area_radius_m: float | None`**: if `None`, use §0.1 server default; enforce max. |
| **A4** | **`min_anchor_separation_m: float | None`**. |
| **A5** | Optional **`fov_deg`**, **`pitch_jitter_deg`**. |
| **A6** | **`sampling_debug`** in response when `STREETVIEW_EXPOSE_SAMPLING_DEBUG=1`: mode, **R** used, seed, attempts, drops — **no secrets**. |
| **A7** | Optional **`PanoFrame`**: debug-only `anchor_lat`/`anchor_lon` (strip from ranked client paths if ever forwarded; default omit). |

**Line-level:** extend `PanosSampleRequest` Field descriptions; tighten types (Literal / Enum).

---

## 3. PR-B — `google_static.py`

| Task | Lines (guide) | Detail |
|------|----------------|--------|
| **B1** | ~L33–L39 | Wrap metadata JSON in **`MetadataResult`**; classify non-OK `status`. |
| **B2** | ~L42–L73 | Refactor **`fetch_static_jpeg`**: exactly one of **`pano_id`** or **`(lat,lon)`**; build query accordingly. |
| **B3** | — | Optional static URL **signing** when required by key type. |

---

## 4. PR-C — `google_sample.py`, `sample_dispatch.py`, `sample_frames.py`

### 4.1 Stochastic default (`sample_panos_google_stochastic`)

**Replace** current default loop (~L26–L55) with:

1. **`R`** = `req.area_radius_m` or `default_area_radius_m()` (PR-D).  
2. **RNG** from resolved `jitter_seed`.  
3. **Attempts** loop (cap `K * count`, e.g. `K=8`): draw **uniform in disk**: random distance in `[0, R]`, random bearing; convert with existing **`offset_lat_lon`**.  
4. **`fetch_metadata(anchor)`**; on non-OK, continue.  
5. If **`min_anchor_separation_m`**: reject if **haversine** to any accepted anchor `<` threshold.  
6. **`fetch_static_jpeg(..., pano_id=..., heading=rng.uniform(0, 360), ...)`**.  
7. Append **`PanoFrame`**; unique **logical** `pano_id` for LFM if needed (`base#idx` / heading bucket).  
8. If cannot reach **`count`** by cap → **`StreetViewInsufficientCoverageError`** (HTTP mapping + batch `--allow-partial` policy).

**Line-level:** move old body verbatim into **`sample_panos_google_legacy_radial`**; router selects implementation.

### 4.2 `OMNI_SINGLE_PANO`

One metadata at **center**; **N** Static calls, **same** `pano_id`, headings **`i·360/N`**, pitch 0.

### 4.3 `sample_dispatch.py` (~L12–L22)

Branch on **`sampling_mode`** to stochastic / legacy / omni.

### 4.4 `sample_frames.py` (~L27–L56)

Mirror **RNG headings** and **seed in `cache_key`** for stochastic; legacy hue simulation for radial.

---

## 5. PR-D — new `sampling_extent.py`

| Function | Role |
|----------|------|
| `default_area_radius_m()` | Reads §0.1 envs, returns float + validates cap. |
| `uniform_disk_offset(rng, center_lat, center_lon, radius_m)` | Returns `(lat, lon)` using `offset_lat_lon`. |
| `haversine_m(a, b)` | Min-separation filter. |
| Constants | `MAX_AREA_RADIUS_M`, `MAX_METADATA_ATTEMPTS_FACTOR`. |

---

## 6. PR-E — `main.py`

| Task | Detail |
|------|--------|
| **E1** | **`health`**: `default_area_radius_m`, `s2_gsd_m`, `s2_chip_edge_px`, supported modes — **remove** any “road_bearing_provider” from earlier drafts. |
| **E2** | Map insufficient coverage / metadata errors to **HTTP** codes per SPEC. |

---

## 7. PR-F — `tools/batch_streetview_hints.py`

| Task | Lines (guide) | Detail |
|------|----------------|--------|
| **F1** | ~L135–L142 | JSON: `sampling_mode`, `jitter_seed` (from **`--pano-jitter-seed`** or derive from **`--shuffle-seed`** / run id), `area_radius_m`, optional `min_anchor_separation_m`. |
| **F2** | — | **`radius_m`**: only when legacy mode; document to avoid conflating with **R**. |
| **F3** | **`_pano_model_pin`** | `sampling_mode`, `s2_area_policy_version` (e.g. `2026-04-18.v1`). |
| **F4** | ~L377–L388 | **Renumber `rank` 1..N** after merging LFM chunks. |

**HF Jobs:** pass `STREETVIEW_S2_*` and jitter envs; **do not** wire road-provider secrets.

---

## 8. PR-G — observability

Backoff on Static **429**/5xx; structured logs: attempts, **`ZERO_RESULTS`** rate, accepted frames.

---

## 9. PR-H — testing

| Test | Detail |
|------|--------|
| **H1** | Fixed seed + mocked metadata → deterministic anchors/headings. |
| **H2** | Min-separation rejects near-duplicate anchors. |
| **H3** | Mocked Static URL contains `pano=` when `pano_id` present. |
| **H4** | Batch forwards new JSON keys. |

---

## 10. PR-I — documentation

Update **`docs/scripts/SPEC-batch-streetview-hints.md`** §1.1 S1, **`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`** §2.2 JSON, **`inference/streetview_pano_service/README.md`**, **`inference/README.md`** row; **`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`** Phase D bullet (stochastic S2 footprint, not road providers).

---

## 11. PR-J — optional

| ID | Task |
|----|------|
| **J1** | Pitch / FOV jitter (ranked policy review). |
| **J2** | LFM `streetview_user_prompt`: neutral “multi-sample around map context” wording (**no** “facade orthogonal” requirement). |
| **J3** | Manifest / `model_pins`: `streetview_sampling_version`. |
| **J4** | Static URL signing. |
| **J5** | Nightly real Google smoke CI. |
| **J6** | Default **R** from **`still_index`** ground meters when available. |

---

## 12. Risks

| Risk | Mitigation |
|------|------------|
| High **`ZERO_RESULTS`** rate inside disk | Attempt cap; optional adaptive **shrink R**; log in `sampling_debug` + batch failures. |
| **R** too large | Server max; sensible §0.1 default. |
| Random headings collide | Optional **stratified** set: shuffle N headings in `k·360/N` buckets with jitter inside bucket. |
| **`radius_m` vs `area_radius_m` confusion | SPEC + API docs: legacy-only vs stochastic. |

---

## 13. Definition of done

1. **Default** path: **STOCHASTIC_S2_FOOTPRINT**, real Static when keyed, **stub** parity.  
2. **Seeded** anchors + **random** headings; **`pano=`** when metadata OK.  
3. **Legacy** path bit-identical to old radial-offset behavior (modulo intentional bugfixes).  
4. **Batch** + **tests** + **docs** updated; **LFM rank** merge fixed.  
5. **No** road-bearing providers required to ship.

---

## 14. Checkbox tracker

- [ ] **J1** Pitch / FOV jitter  
- [ ] **J2** LFM neutral multi-sample prompt  
- [ ] **J3** Manifest sampling version  
- [ ] **J4** URL signing  
- [ ] **J5** Nightly Google  
- [ ] **J6** R from still_index  
- [ ] **H+** Stratified heading buckets  

---

## 15. References

- [Street View Static API](https://developers.google.com/maps/documentation/streetview/overview)  
- [Street View Image Metadata](https://developers.google.com/maps/documentation/streetview/metadata)  
- Copernicus / ESA Sentinel-2 MSI resolutions (10 / 20 / 60 m).

---

**Document history**

| Ver | Date | Notes |
|-----|------|-------|
| 0.1–0.2 | 2026-04-18 | Prior WBS (road-perpendicular + bearing providers). |
| **0.3** | **2026-04-18** | **Pivot:** stochastic S2-scaled disk, random headings; road/navigation stack deferred; PR-D = extent + PRNG. |