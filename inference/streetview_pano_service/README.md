# Street View pano service (IMP-110 scaffold)

Discrete **`inference/*`** worker for CPU pano / static URL building per `plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`.

- `GET /health` — process liveness
- `GET /api/v1/pano/metadata?lat=&lon=` — stub response until provider wiring ships

Build: `docker build -f inference/streetview_pano_service/Dockerfile -t nutonic-streetview-pano inference/streetview_pano_service`
