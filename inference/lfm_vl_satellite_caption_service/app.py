from __future__ import annotations

from lfm_vl_satellite_caption_service.gradio_panel import build_gradio_blocks


demo = build_gradio_blocks()

if __name__ == "__main__":
    demo.launch()
