from __future__ import annotations

import os
from typing import Any

import gradio as gr
import uvicorn
from fastapi import FastAPI

from lfm_vl_satellite_caption_service.config import get_settings
from lfm_vl_satellite_caption_service.dispatch import effective_backend, infer
from lfm_vl_satellite_caption_service.gradio_panel import build_gradio_blocks
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest, SatelliteInferResponse


# Hugging Face ZeroGPU Spaces require at least one `@spaces.GPU` function to be
# defined at import time. Our actual transformer generation is wrapped lazily
# in the inference module, which can be too late for the startup detector.
try:
    import spaces

    @spaces.GPU  # type: ignore[misc]
    def _hf_zerogpu_probe(_: int = 0) -> int:
        return 0

except Exception:
    _hf_zerogpu_probe = None  # type: ignore[assignment]


demo = build_gradio_blocks()

# Hugging Face Gradio SDK Spaces run `python app.py` and expect an app listening on PORT (7860).
# Gradio's SSR (Node) layer can intercept unknown routes (causing 405/HTML for REST calls),
# so we run an explicit FastAPI parent app and mount Gradio onto it.
app = FastAPI()

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
    return infer(req)


# Mount UI at "/" so the Space homepage remains the Gradio app.
# Custom FastAPI routes above should take precedence over Gradio's catch-all.
app = gr.mount_gradio_app(app, demo, path="/", ssr_mode=False)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
