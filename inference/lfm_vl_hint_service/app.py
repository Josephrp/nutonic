from __future__ import annotations

import gradio as gr

from lfm_vl_hint_service.gradio_panel import build_gradio_blocks


demo = build_gradio_blocks()

if __name__ == "__main__":
    demo.launch()
