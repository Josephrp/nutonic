from __future__ import annotations

from typing import Any

import gradio as gr

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

# Hugging Face Gradio SDK Spaces serve the Gradio app's underlying FastAPI instance.
# Expose stable internal routes (`/health`, `/v1/infer`) on that ASGI app so other
# services (and CI smoke) can call it without going through Gradio's event protocol.
app = demo.app  # FastAPI under the hood

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

if __name__ == "__main__":
    demo.launch()
