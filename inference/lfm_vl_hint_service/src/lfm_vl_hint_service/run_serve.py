"""
Run FastAPI + optional Gradio on one port (``uvicorn``).

**Local / Hugging Face Docker Space (Gradio SDK + ZeroGPU):**

.. code-block:: bash

   export LFM_VL_MOUNT_GRADIO=1
   pip install -e ".[serve,model]"
   python -m lfm_vl_hint_service.run_serve

Uses ``PORT`` (default ``7860``) for Hugging Face Spaces.
"""

from __future__ import annotations

import os


def main() -> None:
    os.environ.setdefault("LFM_VL_MOUNT_GRADIO", "1")
    try:
        import gradio  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            'Gradio is required for this entrypoint. Install: pip install -e ".[serve]"'
        ) from e
    import uvicorn

    from lfm_vl_hint_service.main import app

    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
