from __future__ import annotations

from lfm_vl_satellite_caption_service.gradio_panel import build_gradio_blocks


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

# Keep the stable internal HTTP contract (`/health`, `/v1/infer`) even on Gradio SDK
# (ZeroGPU) deployments by mounting the Gradio UI onto the FastAPI app.
from lfm_vl_satellite_caption_service.main import app as app

try:
    import gradio as gr

    # IMPORTANT: do NOT mount at "/" or it will shadow FastAPI routes like `/v1/infer`.
    # Mount the UI under a subpath so the service contract remains reachable.
    gr.mount_gradio_app(app, demo, path="/ui")
except Exception:
    # If Gradio mounting fails for any reason, keep serving the FastAPI app so
    # callers (and CI smoke) still have `/health` and `/v1/infer`.
    pass

if __name__ == "__main__":
    demo.launch()
