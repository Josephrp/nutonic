from __future__ import annotations

from nutonic_pro_gradio_demo.gradio_app import build_demo
from nutonic_pro_gradio_demo.gradio_app import LEAFLET_JS

# Hugging Face ZeroGPU Spaces require at least one `@spaces.GPU` function to be
# defined at import time in the Space entry file (`app.py`).
try:
    import spaces  # type: ignore

    @spaces.GPU  # type: ignore[misc]
    def hf_zerogpu_probe(_: int = 0) -> int:
        return 0

except ImportError:
    hf_zerogpu_probe = None  # type: ignore[assignment]


demo = build_demo()

if __name__ == "__main__":
    demo.launch(ssr_mode=False, js=LEAFLET_JS)

