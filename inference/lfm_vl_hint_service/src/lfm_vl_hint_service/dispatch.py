"""Route inference to stub, in-process Hugging Face (official LFM-VL weights), or OpenAI-compatible servers."""

from __future__ import annotations

from lfm_vl_hint_service.config import get_settings
from lfm_vl_hint_service.models import SuggestionsFromFramesRequest, SuggestionsFromFramesResponse


def effective_lfm_backend() -> str:
    """
    Resolve ``LFM_VL_BACKEND=auto`` to ``transformers`` when ``torch`` + ``transformers`` are importable, else ``stub``.
    """
    raw = get_settings().backend
    if raw != "auto":
        return raw
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForImageTextToText  # noqa: F401

        return "transformers"
    except ImportError:
        return "stub"


def infer_suggestions(req: SuggestionsFromFramesRequest) -> SuggestionsFromFramesResponse:
    backend = effective_lfm_backend()
    if backend == "transformers":
        from lfm_vl_hint_service.infer_transformers import infer_from_frames_transformers

        return infer_from_frames_transformers(req)
    if backend in ("openai", "openai_compatible", "vllm", "sglang"):
        from lfm_vl_hint_service.infer_openai import infer_from_frames_openai

        return infer_from_frames_openai(req)
    from lfm_vl_hint_service.stub_infer import infer_from_frames_stub

    return infer_from_frames_stub(req)


def narrative_fuse_text(captions: list[tuple[str, str]]) -> str:
    backend = effective_lfm_backend()
    if backend == "transformers":
        from lfm_vl_hint_service.infer_transformers import narrative_fuse_transformers

        return narrative_fuse_transformers(captions)
    if backend in ("openai", "openai_compatible", "vllm", "sglang"):
        from lfm_vl_hint_service.infer_openai import narrative_fuse_openai

        return narrative_fuse_openai(captions)
    parts = [f"{vid}: {txt}" for vid, txt in captions]
    fused = " · ".join(parts)[:890]
    return fused
