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

if __name__ == "__main__":
    demo.launch()
