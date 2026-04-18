# Street View pano service (IMP-110)

Discrete **`inference/*`** worker for CPU pano / static URL building per `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md` and **[`plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md`](../../plans/2026-04-18-streetview-google-perpendicular-sampling-full-scope.md)**.

- **`GET /health`** — liveness plus **`default_area_radius_m`**, **`s2_gsd_m`**, **`s2_chip_edge_px`**, supported **`sampling_mode`** list
- **`GET /api/v1/pano/metadata?lat=&lon=`** — Google metadata when **`STREETVIEW_PROVIDER=google`** + key, else stub echo
- **`POST /api/v1/panos/sample`** (legacy **`POST /v1/panos/sample`**) — **`count`** JPEG **`frames[]`**: **stub** (Pillow) or **Google** Static + Metadata per **`STREETVIEW_PROVIDER`**

**Sampling:** **`sampling_mode`** defaults to **`STOCHASTIC_S2_FOOTPRINT`** (seeded anchors in disk **R**, optional **`min_anchor_separation_m`**, **`pano=`** when Google returns **`pano_id`**). **`LEGACY_RADIAL_OFFSET`** matches pre-2026 radial policy (**`radius_m`**). Deprecated **`heading_mode": "RADIAL_OR_RANDOM"`** maps to legacy when **`sampling_mode`** is omitted. Optional **`STREETVIEW_EXPOSE_SAMPLING_DEBUG=1`** adds **`sampling_debug`** (no secrets).

Run locally (port **7861** matches `tools/batch_streetview_hints.py` defaults):

```bash
cd inference/streetview_pano_service
pip install -e ".[dev]"
uvicorn streetview_pano_service.main:app --host 127.0.0.1 --port 7861
```

Build: `docker build -f inference/streetview_pano_service/Dockerfile -t nutonic-streetview-pano inference/streetview_pano_service`
