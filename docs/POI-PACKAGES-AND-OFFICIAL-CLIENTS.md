# POI packages, lightweight clients, and official-app submissions

This document captures the **current product/engineering intent** for:

- **Lightweight clients** that rely on **cached POI payloads** and **server-held static assets** (downsampled imagery + metadata), with **optional on-device inference** only where the product explicitly allows it (e.g. **new POI** flows).
- A **canonical on-disk layout** for GeoGuessr-style POIs (example tree: `data/downloads/geoguessr_poi_120/`), used as the **authoring reference** for what the **server packages** and what **apps may bundle or download**.
- **Store / marketplace builds** use **OpenAPI**-defined **`POST`** bodies for **scores** and **POIs** when those paths ship (`rules/05-networking-leaderboard.md`).

Normative rules are updated in **`rules/05-networking-leaderboard.md`**, **`rules/06-server-vlm-tim-and-on-device-ml.md`**, **`rules/13-client-cache-and-data-plane.md`**, and **`rules/00-product-intent.md`**. Networking details remain in **`docs/LEADERBOARD-MAP-POI-SCORES.md`**.

---

## 1. Canonical POI directory layout (authoring reference)

Each POI is a folder named `poi_<zero-padded id>` (e.g. `poi_0011`) under a **dataset root** such as `geoguessr_poi_120`:

```text
<dataset_root>/
  poi_0011/
    poi.json                 # metadata: ids, titles, WGS84 ground truth, provenance, content_version, …
    mapbox/                  # one or more Mapbox (or equivalent) static raster clues — full-res authoring assets
      *.png
    sentinel-2-l2a/          # optional EO tiles / composites for Terra-style or hybrid rounds
      …
```

### 1.1 `poi.json` (required semantics)

- Must include stable identifiers (**`poi_id`**, and linkage to **`map_id` / `round_id`** as defined in OpenAPI).
- Must include **WGS84** ground truth the **engine** needs for scoring when this POI is the round object (**`lat`**, **`lon`**, optional elevation, CRS = EPSG:4326 unless documented otherwise).
- Should include **`content_version`** (or semver) so clients and servers agree on which asset revision is in play.

The **reference tree** may live under `data/downloads/…` in the monorepo for **ML and packaging jobs**; **production devices** must not depend on that path existing—they consume **bundles** or **HTTP** artifacts produced from it.

---

## 2. Server role: canonical store and shippable bundles

- The **reference server** (or build pipeline) is the **canonical holder** of:
  - **Full-resolution** internal assets (if policy allows storage on server),
  - **Downsampled** / **WebP** / **JPEG** variants for mobile bandwidth,
  - **Normalized `poi.json`** slices merged into **`map_id`** manifests,
  - **ETag** / **`content_version`** headers for cache correctness.
- Clients **fetch or ship** only what the contract lists: e.g. a **single downsampled `mapbox` still** + **redacted `poi.json`** for clue rounds that **hide** exact truth until resolve, **or** full metadata for offline practice—**product per `round_type`**.
- **No Hugging Face write tokens on device**; Hub remains **Job / server** side (`rules/13-client-cache-and-data-plane.md`).

---

## 3. Lightweight client: cache-first, optional local inference

### 3.1 Default path (casual / reference)

- **Play** from **pre-generated POI objects**: imagery + allowed fields from manifest; **scoring** uses ground truth available to the **local engine** per round policy (`docs/GAME-ENGINE.md` §0).
- **Leaderboard rows** for non-ranked play are **device-local by default** (`rules/05-networking-leaderboard.md`); **optional** community **`POST`/`GET`** (Modes A–B) is separate from ranked (**Mode C**).

### 3.1b Ranked (Mode C)

- **Clue manifest** for an active ranked round **omits** server ground truth (`lat`/`lon` of the target) from anything the client can read before **submit**; stills and metadata match **`rules/13`** bundle rules.
- **After** server **`submit`**, the client may cache **server-returned** `distance_km` / points for UX—**not** recomputed locally for ranked display authority.
- Full policy: **`docs/RANKED-MODE.md`**.

### 3.2 Optional local inference (“new POI” or enrichment)

- **Allowed only** for flows explicitly named in product + OpenAPI (e.g. **“propose new POI”**).
- **Constraints** (`rules/06-server-vlm-tim-and-on-device-ml.md`): **timeouts**, **CPU/GPU caps**, **no blocking** map submit path; **outputs** on **`POST`** paths follow **OpenAPI** schemas.

---

## 4. Store builds and **`POST`** contracts

When product ships **server-mutating** paths, **`rules/05-networking-leaderboard.md`** defines **JWT**, **official-client registration** (where used), **JSON Schema**, and **idempotency** for **`POST`** scores and **`POST`** POIs.

### 4.1 Reference builds

**Reference / sideload** builds may omit gated writes—see **`rules/05-networking-leaderboard.md`** Mode A.

### 4.2 Server validation

- **Validate** schema, ranges, and that **`poi_id` / `map_id`** exist on published manifests when those **`POST`** paths are enabled.
- **Parameterized** storage for all dynamic fields.

---

## 5. Static asset shipping strategy

| Channel | Use |
|--------|-----|
| **On-disk in APK/IPA/desktop** | Curated **downsampled** stills + minimal `poi.json` for offline / first-run. |
| **On-demand download** | Larger Sentinel stacks, extra POIs—**versioned** URLs from server/CDN. |
| **Delta updates** | Manifest lists **`content_version`** per POI; client skips unchanged blobs. |

---

## 6. Related documents

| Document | Role |
|----------|------|
| `rules/05-networking-leaderboard.md` | JWT, official client, schema-strict POSTs |
| `rules/13-client-cache-and-data-plane.md` | POI bundles, cache keys, no Hub on client |
| `rules/06-server-vlm-tim-and-on-device-ml.md` | Optional local inference bounds |
| `docs/LEADERBOARD-MAP-POI-SCORES.md` | Per-map API, POI POST, score POST |
| `docs/SOCIAL-AND-COMPETITION.md` | Async `map_id` competition |
| `docs/GAME-ENGINE.md` | Client authority vs Mode C |
| `docs/RANKED-MODE.md` | Server-held POIs, verified scores, tickets |

---

| Version | Date | Notes |
|---------|------|-------|
| 0.3 | 2026-04-12 | Trim standalone threat / license prose; pointer to **`rules/05`** for **`POST`** contracts |
| 0.2 | 2026-04-07 | Ranked (§3.1b), Mode C integrity pointer |
| 0.1 | 2026-04-07 | POI tree, server bundles, lightweight client, official-app + JWT framing |

*End of document.*
