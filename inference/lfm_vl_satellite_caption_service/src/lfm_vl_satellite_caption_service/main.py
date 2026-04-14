from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from lfm_vl_satellite_caption_service.config import get_settings
from lfm_vl_satellite_caption_service.dispatch import effective_backend, infer
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest, SatelliteInferResponse

app = FastAPI(title="NU:TONIC LFM-VL satellite caption service", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "status": "ok",
        "service": "lfm_vl_satellite_caption_service",
        "version": "0.1.0",
        "lfm_satellite_backend_config": s.backend,
        "lfm_satellite_backend": effective_backend(),
        "model_id": s.model_id,
    }


@app.post("/v1/infer", response_model=SatelliteInferResponse)
def infer_route(req: SatelliteInferRequest) -> SatelliteInferResponse:
    """Mapbox / ortho still → caption (``task=caption``)."""
    return infer(req)
