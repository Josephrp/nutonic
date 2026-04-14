"""HTTP surface for ``IMP-110`` — pano sampling stub + health."""

from __future__ import annotations

from fastapi import FastAPI

from streetview_pano_service.models import PanosSampleRequest, PanosSampleResponse
from streetview_pano_service.pano_config import get_pano_settings
from streetview_pano_service.sample_dispatch import sample_panos

app = FastAPI(title="NU:TONIC Street View pano service", version="0.3.0")


@app.get("/health")
def health() -> dict[str, str]:
    s = get_pano_settings()
    return {
        "status": "ok",
        "service": "streetview_pano_service",
        "version": "0.3.0",
        "streetview_provider": s.provider,
        "google_configured": "yes" if s.google_maps_api_key else "no",
    }


@app.get("/api/v1/pano/metadata")
def pano_metadata(lat: float, lon: float) -> dict[str, object]:
    """Echo + optional Google Street View metadata when ``STREETVIEW_PROVIDER=google``."""
    s = get_pano_settings()
    if s.provider == "google" and s.google_maps_api_key:
        from streetview_pano_service.google_static import fetch_metadata

        try:
            meta = fetch_metadata(lat, lon, api_key=s.google_maps_api_key)
            return dict(meta)
        except Exception as e:  # noqa: BLE001
            return {"lat": lat, "lon": lon, "status": "error", "error": str(e)}
    return {"lat": lat, "lon": lon, "status": "stub", "pano_id": None}


@app.post("/v1/panos/sample", response_model=PanosSampleResponse)
def panos_sample(req: PanosSampleRequest) -> PanosSampleResponse:
    """
    Returns JPEG ``frames[]``: **Google Street View Static** when ``STREETVIEW_PROVIDER=google``
    (or ``auto`` with ``GOOGLE_MAPS_API_KEY``), else **Pillow** synthetic stubs.
    """
    return sample_panos(req)
