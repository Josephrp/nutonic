"""
Gradio UI + JSON API for ``lfm_vl_hint_service`` (Hugging Face ZeroGPU + Gradio SDK).

Mount at ``/gradio`` on the FastAPI app when ``LFM_VL_MOUNT_GRADIO=1`` and ``gradio`` is installed.
"""

from __future__ import annotations

from typing import Any

import gradio as gr

from lfm_vl_hint_service.dispatch import effective_lfm_backend, infer_suggestions, narrative_fuse_text, pro_brief_fuse_text
from lfm_vl_hint_service.models import SuggestionsFromFramesRequest


def _suggestions_from_json(req: dict[str, Any]) -> dict[str, Any]:
    parsed = SuggestionsFromFramesRequest.model_validate(req)
    return infer_suggestions(parsed).model_dump()


def _narrative_fuse_from_json(req: dict[str, Any]) -> dict[str, Any]:
    caps = req.get("captions") or []
    pairs: list[tuple[str, str]] = []
    for c in caps:
        if isinstance(c, dict):
            pairs.append((str(c.get("viewpoint_id", "")), str(c.get("text", ""))))
    mission = req.get("mission_flavor")
    text = narrative_fuse_text(pairs)
    return {"narrative": text, "mission_flavor": mission}


def _pro_brief_fuse_from_json(req: dict[str, Any]) -> dict[str, Any]:
    return pro_brief_fuse_text(
        profile=str(req.get("profile") or "brief_only"),
        tim_summary=req.get("tim_summary") if isinstance(req.get("tim_summary"), dict) else None,
        artifact_refs=[a for a in req.get("artifact_refs") or [] if isinstance(a, dict)],
        jobs=[j for j in req.get("jobs") or [] if isinstance(j, dict)],
        force_compose=bool(req.get("force_compose")),
        max_compose_distance_km=float(req.get("max_compose_distance_km") or 500.0),
    )


def build_gradio_blocks() -> gr.Blocks:
    """Gradio Blocks suitable for ``gr.mount_gradio_app(..., path='/gradio')``."""
    with gr.Blocks(title="NU:TONIC LFM-VL hints") as demo:
        gr.Markdown(
            "## LFM-VL Street View hint service\n"
            "JSON **POST** APIs remain on the same host under **`/v1/...`** (FastAPI). "
            "This panel is for **manual checks** and matches **Hugging Face ZeroGPU + Gradio SDK** hosting.\n\n"
            f"**Effective backend:** `{effective_lfm_backend()}`"
        )
        with gr.Tab("suggestions_from_frames"):
            gr.Markdown("Body matches **`POST /v1/suggestions/from_frames`** (Pydantic JSON).")
            req_json = gr.JSON(label="request", value={"frames": []})
            out_json = gr.JSON(label="response")
            go = gr.Button("Run inference")
            go.click(fn=_suggestions_from_json, inputs=req_json, outputs=out_json, api_name="suggestions_from_frames")
        with gr.Tab("narrative_fuse"):
            gr.Markdown("Body matches **`POST /v1/narrative/fuse`** (`captions[]`, optional `mission_flavor`).")
            fuse_in = gr.JSON(
                label="request",
                value={"captions": [{"viewpoint_id": "a", "text": "one"}], "mission_flavor": "neutral"},
            )
            fuse_out = gr.JSON(label="response")
            go2 = gr.Button("Fuse captions")
            go2.click(fn=_narrative_fuse_from_json, inputs=fuse_in, outputs=fuse_out, api_name="narrative_fuse")
        with gr.Tab("pro_brief_fuse"):
            gr.Markdown("Body matches **`POST /v1/pro/brief/fuse`** for PRO mini-app brief handoff.")
            pro_in = gr.JSON(
                label="request",
                value={"profile": "brief_only", "tim_summary": {"mode": "not_requested"}, "artifact_refs": [], "jobs": []},
            )
            pro_out = gr.JSON(label="response")
            go3 = gr.Button("Compose PRO brief")
            go3.click(fn=_pro_brief_fuse_from_json, inputs=pro_in, outputs=pro_out, api_name="pro_brief_fuse")
    return demo
