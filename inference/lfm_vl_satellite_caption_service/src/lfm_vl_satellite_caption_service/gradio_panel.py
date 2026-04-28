from __future__ import annotations

from typing import Any

import gradio as gr

from lfm_vl_satellite_caption_service.dispatch import effective_backend, infer
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest


def _infer_from_json(req: dict[str, Any]) -> dict[str, Any]:
    parsed = SatelliteInferRequest.model_validate(req)
    return infer(parsed).model_dump()


def build_gradio_blocks() -> gr.Blocks:
    with gr.Blocks(title="NU:TONIC LFM-VL satellite captions") as demo:
        gr.Markdown(
            "## LFM-VL satellite caption service\n"
            "This Gradio SDK app is the ZeroGPU host surface. The underlying transformers "
            "generation call is wrapped with `spaces.GPU` when the `spaces` package is installed.\n\n"
            f"**Effective backend:** `{effective_backend()}`"
        )
        req_json = gr.JSON(
            label="request",
            value={
                "image_base64": "",
                "task": "caption",
                "analysis_profile": "brief_only",
                "contract_id": "nutonic.pro.caption.v1",
            },
        )
        out_json = gr.JSON(label="response")
        run = gr.Button("Run caption")
        run.click(fn=_infer_from_json, inputs=req_json, outputs=out_json, api_name="infer")
    return demo
