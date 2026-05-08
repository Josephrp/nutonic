from __future__ import annotations

from typing import Any

import gradio as gr

from nutonic_terramind_tim_local.space_api import health, tim_infer
from nutonic_terramind_tim_local.tim_defaults import DEFAULT_TIM_MODEL_ID


def _infer_from_json(req: dict[str, Any]) -> dict[str, Any]:
    return tim_infer(req)


def build_gradio_blocks() -> gr.Blocks:
    with gr.Blocks(title="NU:TONIC TerraMind TiM") as demo:
        gr.Markdown(
            "## TerraMind TiM worker\n"
            "This Gradio SDK app is the ZeroGPU host surface. The TiM export function is "
            "wrapped with `spaces.GPU` when the `spaces` package is installed."
        )
        health_json = gr.JSON(label="health", value=health())
        refresh = gr.Button("Refresh health")
        refresh.click(fn=health, outputs=health_json, api_name="health")
        req_json = gr.JSON(
            label="request",
            value={
                "analysis_profile": "brief_only",
                "config": {
                    "model_id": DEFAULT_TIM_MODEL_ID,
                    "pretrained": True,
                    "modalities": ["RGB"],
                    "tim_modalities": ["LULC", "location"],
                    "device": "cuda",
                    "inputs": {"mode": "random", "batch_size": 1},
                    "serialization": {"tensor_sample_limit": 0, "encoder_tensor_sample_limit": 0},
                    "export": {"map_id": "smoke_map", "location_id": "smoke_loc"},
                },
            },
        )
        out_json = gr.JSON(label="response")
        run = gr.Button("Run TiM")
        run.click(fn=_infer_from_json, inputs=req_json, outputs=out_json, api_name="tim_infer")
    return demo
