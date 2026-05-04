# PRO materialization service

HTTP worker for **`PRO_MATERIALIZATION_SERVICE_URL`** / **`NUTONIC_PRO_MATERIALIZATION_SERVICE_URL`** (`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md` §5.3, `plans/2026-04-12-pro-materialization-fetch-and-downscale-service.md`). **Kotlin clients do not call this URL** (`rules/13-client-cache-and-data-plane.md`); the thin **`server/`** may orchestrate **`POST /api/v1/pro/jobs`** → **`POST …/internal/v1/materialize`**.

## Implemented

### P0–P1

- **`GET /health`**, **`GET /internal/v1/healthz`** (`s2_asset_mapping_version` from packaged YAML).
- **`POST /internal/v1/materialize`** with **`sentinel_fetch_mode": "MINIMAL_RGB"`** (default): Mapbox pin → **`vlm_contract_id`** PNG (`mapbox_rgb` inline base64) + optional **`RGB_mapbox`** TiM NPZ (`[1,3,224,224]` BGR **0–255**).
- **`vlm_contract_id`**: **`nutonic.pro.vlm.v1_512`** → roles **`mapbox_rgb`** only. **`nutonic.pro.vlm.v1_512_fc_scl`** (plan §6.4) adds **`sentinel_fc`** (SWIR2/NIR/red false-color PNG) + **`cloud_mask_thumb`** (SCL → semi-transparent RGBA PNG); requires **`TERRAMIND_SPECTRAL`** or **`FULL_STAC`** and optional **`[s2]`** deps. **`nutonic.pro.vlm.v1_512_s2_only`** ships the same Sentinel-derived PNGs **without** **`mapbox_rgb`**; spectral modes do **not** require a Mapbox token for this contract.
- **`POST /api/v1/materialize/stub`** — backward-compatible wrapper.

### P2 (Sentinel-2 + TerraMind spectral path)

- **`sentinel_fetch_mode`**: **`TERRAMIND_SPECTRAL`** or **`FULL_STAC`** runs **STAC** (Earth Search default) + **12-band** patch at **224×224** (same asset key order as `terramind_tim_local.s2_stac`), reflectance scaled like TerraMind, merged into **`run_manifest.stac`**.
- **`enable_tim` + `tim_branch": "S2L2A_full"`** → NPZ key **`S2L2A`** `[1,12,224,224]` float32.
- **`FULL_STAC`** + **`RGB_mapbox`** TiM still uses Mapbox-derived RGB NPZ while STAC stack is fetched for manifest/audit.
- **`TERRAMIND_SPECTRAL`** + **`enable_tim`** requires **`S2L2A_full`** (422 `TIM_BRANCH_REQUIRES_S2L2A_FULL` if **`RGB_mapbox`**).
- **`data/s2_asset_allowlist.yaml`**: **`version`** + ordered **`assets`** (12 keys); drives cache key + STAC reads.
- **Sentinel/STAC** (`pystac-client`, **`rasterio`**) are **core dependencies** (since **0.3.1**). Spectral modes still return **503** `S2_DEPENDENCIES_MISSING` only if imports fail at runtime (e.g. missing GDAL system libs — the service **Dockerfile** installs **`gdal-bin`** / **`libgdal-dev`**).

## Constraints

- **No `torch`** / **no `terratorch`** in this package (plan §3.2).
- **`MAPBOX_ACCESS_TOKEN`** required when the resolved VLM contract includes **`mapbox_rgb`** (including **`MINIMAL_RGB`** and **`nutonic.pro.vlm.v1_512_fc_scl`** on spectral modes). Sentinel-only contracts (**`nutonic.pro.vlm.v1_512_s2_only`**) skip Mapbox entirely.

## Environment

| Variable | Purpose |
|----------|---------|
| **`MAPBOX_ACCESS_TOKEN`** | Mapbox Static Images token (omit only for Sentinel-only VLM contracts on **`TERRAMIND_SPECTRAL`** / **`FULL_STAC`**). |
| **`NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC`** | When `1`, require signed requests. |
| **`NUTONIC_INFERENCE_HMAC_SECRET`** | Shared HMAC secret. |

## Run locally

```bash
pip install -e "./inference/pro_materialization_service[dev]"
set MAPBOX_ACCESS_TOKEN=your_token
uvicorn pro_materialization_service.main:app --host 127.0.0.1 --port 7865
```

From the monorepo root, tests should pick up this package’s `src` first (or use an editable install). If imports resolve to an older site-packages copy, set `PYTHONPATH` to `inference/pro_materialization_service/src` before running `pytest`.

## Docker

```bash
docker build -t nutonic-pro-materialization inference/pro_materialization_service
```

The packaged **Dockerfile** installs **`gdal-bin`** and **`libgdal-dev`** (rasterio needs GDAL/PROJ/GEOS at runtime on Debian slim), then **`pip install .`**, and fails the build if **`import rasterio`** / **`pystac_client`** do not work.
