# Street View pano service (IMP-110)

Discrete **`inference/*`** worker for CPU pano / static URL building per `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`.

- `GET /health` — process liveness
- `GET /api/v1/pano/metadata?lat=&lon=` — legacy stub metadata
- **`POST /v1/panos/sample`** — **local batch**: returns **`count`** synthetic JPEG **`frames[]`** (no network; **Pillow**). Request/response shape matches plan §2.2.

Run locally (port **7861** matches `tools/batch_streetview_hints.py` defaults):

```bash
cd inference/streetview_pano_service
pip install -e ".[dev]"
uvicorn streetview_pano_service.main:app --host 127.0.0.1 --port 7861
```

Build: `docker build -f inference/streetview_pano_service/Dockerfile -t nutonic-streetview-pano inference/streetview_pano_service`
