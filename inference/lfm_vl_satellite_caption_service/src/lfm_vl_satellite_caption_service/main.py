from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from lfm_vl_satellite_caption_service.config import get_settings
from lfm_vl_satellite_caption_service.dispatch import effective_backend, infer
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest, SatelliteInferResponse


@asynccontextmanager
async def _lifespan(_: FastAPI):
    if os.environ.get("LFM_SATELLITE_EAGER_LOAD", "").lower() in ("1", "true", "yes"):
        if effective_backend() == "transformers":
            from lfm_vl_satellite_caption_service.infer_transformers import ensure_satellite_model_loaded

            ensure_satellite_model_loaded()
    yield


app = FastAPI(title="NU:TONIC LFM-VL satellite caption service", version="0.1.0", lifespan=_lifespan)


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


@app.post("/v1/pro/caption", response_model=SatelliteInferResponse)
def pro_caption_route(req: SatelliteInferRequest) -> SatelliteInferResponse:
    """PRO alias carrying profile and contract context for composable map captions."""
    return infer(req)
