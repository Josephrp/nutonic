# Script specification: `render_mapbox_still.py`

**Path:** `data/scripts/render_mapbox_still.py`  
**Status:** Planned (**IMP-081**).  
**Plan:** [`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md`](../../plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md) Phase B.

---

## 1. Purpose

Produce **reference still** JPEG/PNG bytes for each catalog **`location_id`**:

1. **Prefer reuse:** if `still_source.bundled_relative` points to an existing Mapbox PNG from POI download, **copy + optional downscale** to product dimensions (width/height/zoom policy from `docs/GAME-ENGINE.md` §9).
2. **Else render:** call Mapbox Static Images API using **server/CI secret** token.

Emit files suitable for:

- **`nutonic/shared/src/commonMain/composeResources/files/maps/<bundle_id>.jpg`**, and
- **`server/`** bundle registry (`resolve_bundle_bytes`) via generated index.

**Downstream consumers (do not break contracts silently)**

| Consumer | Needs from this script |
|----------|-------------------------|
| **SCAN client** | JPEG/PNG bytes at policy width/height; `still_bundle_id` / `still_bundled_resource` in manifest (`docs/GAME-ENGINE.md` §9) |
| **`lfm_vl_satellite_caption_service`** (batch or server) | Same bytes (or lossless PNG) within **max edge** and **sRGB** per specialist Space README; optional caption lines may later merge into Intel / mission copy — **not** the same JSON field as `streetview_hint_pack` |
| **`assemble_manifest`** | Stable **`still_sha256`**, **`bundle_id`**, on-disk path under composeResources, dimensions **`width_px` / `height_px`** so OpenAPI and client decode match |
| **QA / TiM** | Optional sidecar **`center_lat` / `center_lon` / `zoom`** actually used for the static request — must stay consistent with catalog truth when the still is **truth-centered** (see §7) |

---

## 2. Inputs

- **`data/catalog/locations/*.yaml`** (via `--catalog-root`).
- **Environment:** `MAPBOX_ACCESS_TOKEN` or equivalent (never committed).
- **Policy file** (optional): `--still-policy still_policy.yaml` with `width_px`, `height_px`, `zoom`, `style_id`.

---

## 3. Outputs

| Output | Description |
|--------|-------------|
| **Image files** | Under `--compose-resources-maps-dir` and/or `--server-bundles-dir`. |
| **`still_sha256`** | Written back to sidecar **`data/cache/<version>/stills/<location_id>.meta.json`** or merged into manifest assembler input — exact merge TBD; must be **reproducible** from bytes. |
| **`bundle_id` → path index`** | JSON fragment consumed by **`assemble_manifest`** and **`sync_server_catalog`**. |
| **Recommended sidecar fields** | `width_px`, `height_px`, `style_id`, `zoom`, `center_lat`, `center_lon` (if differ from catalog truth, document why — e.g. snapped tile) |

---

## 4. Image contract

- **Format:** JPEG **baseline** (max compatibility for KMP `toImageBitmap`) or PNG if lossless required.
- **Max edge:** configurable; default ≤ **1536 px** long edge unless product ADR changes.
- **Color profile:** sRGB.

---

## 5. CLI

```text
python data/scripts/render_mapbox_still.py [--catalog-root data/catalog]
  [--compose-resources-maps-dir nutonic/shared/src/commonMain/composeResources/files/maps]
  [--reuse-only] [--dry-run]
```

- **`--reuse-only`:** never hit network; fail if no bundled PNG.

---

## 6. Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 4 | Missing token when render required |
| 5 | Upstream Mapbox HTTP error (retry policy: exponential backoff, max 3) |

---

## 7. Logical footguns

- **Center drift:** Re-rendering with a different zoom/center than the POI truth used for Street View sampling yields a **cognitively inconsistent** pack (still shows ridge A, SV captions describe valley B). Batch jobs must take **`center_lat` / `center_lon`** from the **same** catalog row used by `batch_streetview_hints` for that `content_version`.
- **Reuse vs policy:** `--reuse-only` copies an existing POI PNG; if its resolution or crop predates `still_policy.yaml`, assembly should record **`still_policy_mismatch: true`** in reports so CI can fail or force re-render.
- **WebP in reuse path:** KMP `toImageBitmap` may reject some WebP modes; prefer **JPEG baseline** for shipped `files/maps/*` even when reuse source is PNG.

---

## 8. Related

- [SPEC-catalog-import-poi.md](SPEC-catalog-import-poi.md)
- [SPEC-assemble-manifest.md](SPEC-assemble-manifest.md)
- `plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md` — satellite LFM consumes these stills

---

*Spec version: 2026-04-14 (2026-04-14b: downstream consumers + sidecar + footguns)*
