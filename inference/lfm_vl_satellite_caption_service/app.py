from __future__ import annotations

import gradio as gr
from lfm_vl_satellite_caption_service.gradio_panel import build_gradio_blocks


# Hugging Face ZeroGPU Spaces require at least one `@spaces.GPU` function to be
# defined at import time in the Space entry file (`app.py`). Keep this at module
# scope with a real `spaces` import so the platform detector can register it.
try:
    import spaces  # type: ignore

    @spaces.GPU  # type: ignore[misc]
    def hf_zerogpu_probe(_: int = 0) -> int:
        return 0

except ImportError:
    # Local/dev environments without the optional `spaces` package.
    hf_zerogpu_probe = None  # type: ignore[assignment]


demo = build_gradio_blocks()

if __name__ == "__main__":
    demo.launch(ssr_mode=False)
