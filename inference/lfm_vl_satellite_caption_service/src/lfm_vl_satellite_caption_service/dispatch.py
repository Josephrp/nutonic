from __future__ import annotations

from lfm_vl_satellite_caption_service.config import get_settings
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest, SatelliteInferResponse


def effective_backend() -> str:
    raw = get_settings().backend
    if raw != "auto":
        return raw
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForImageTextToText  # noqa: F401

        return "transformers"
    except ImportError:
        return "stub"


def infer(req: SatelliteInferRequest) -> SatelliteInferResponse:
    b = effective_backend()
    if b == "transformers":
        from lfm_vl_satellite_caption_service.infer_transformers import infer_transformers

        return infer_transformers(req)
    if b in ("openai_compatible", "openai", "vllm", "sglang"):
        from lfm_vl_satellite_caption_service.infer_openai import infer_openai

        return infer_openai(req)
    from lfm_vl_satellite_caption_service.stub_infer import infer_stub

    return infer_stub(req)
