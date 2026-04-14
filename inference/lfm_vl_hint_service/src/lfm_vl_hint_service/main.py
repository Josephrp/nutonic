"""FastAPI entry for LFM-VL Street View hint batch (stub | transformers | OpenAI-compatible)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from lfm_vl_hint_service.config import get_settings
from lfm_vl_hint_service.dispatch import effective_lfm_backend, infer_suggestions, narrative_fuse_text
from lfm_vl_hint_service.models import SuggestionsFromFramesRequest, SuggestionsFromFramesResponse

app = FastAPI(title="NU:TONIC LFM-VL hint service", version="0.2.0")


class NarrativeCaption(BaseModel):
    viewpoint_id: str
    text: str


class NarrativeFuseRequest(BaseModel):
    captions: list[NarrativeCaption] = Field(..., min_length=1)
    mission_flavor: str | None = "neutral"


class NarrativeFuseResponse(BaseModel):
    narrative: str


@app.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    eff = effective_lfm_backend()
    out: dict[str, Any] = {
        "status": "ok",
        "service": "lfm_vl_hint_service",
        "version": "0.2.0",
        "lfm_backend_config": s.backend,
        "lfm_backend": eff,
        "model_id": s.model_id,
    }
    if eff in ("openai_compatible", "openai", "vllm", "sglang") or s.backend in (
        "openai_compatible",
        "openai",
        "vllm",
        "sglang",
    ):
        out["openai_base_url"] = s.openai_base_url
    return out


@app.post("/v1/suggestions/from_frames", response_model=SuggestionsFromFramesResponse)
def suggestions_from_frames(req: SuggestionsFromFramesRequest) -> SuggestionsFromFramesResponse:
    """
    Multi-image JSON → ``suggestions[]`` (``docs/scripts/SPEC-batch-streetview-hints.md`` §3.1).

    **Backends** (``LFM_VL_BACKEND``):

    - ``stub`` — no ``torch`` (default for CI).
    - ``transformers`` — in-process **Liquid** Hugging Face weights (``LFM_VL_MODEL_ID``, default
      ``LiquidAI/LFM2.5-VL-450M``) per https://docs.liquid.ai/lfm/models/lfm25-vl-450m
    - ``openai_compatible`` — ``POST {LFM_OPENAI_BASE_URL}/chat/completions`` for vLLM/SGLang
      serving the same model id.
    """
    return infer_suggestions(req)


@app.post("/v1/narrative/fuse", response_model=NarrativeFuseResponse)
def narrative_fuse(req: NarrativeFuseRequest) -> NarrativeFuseResponse:
    """Fuse caption lines (text-only); uses same backend as frames when not ``stub``."""
    caps = [(c.viewpoint_id, c.text) for c in req.captions]
    text = narrative_fuse_text(caps)
    return NarrativeFuseResponse(narrative=text)
