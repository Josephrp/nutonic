from __future__ import annotations

from nutonic_terramind_tim_local.gradio_panel import build_gradio_blocks


demo = build_gradio_blocks()

if __name__ == "__main__":
    demo.launch()
