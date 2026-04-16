from __future__ import annotations

import base64
import os
from io import BytesIO
from typing import Any

from PIL import Image

from lfm_vl_satellite_caption_service.config import get_settings
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest, SatelliteInferResponse
from lfm_vl_satellite_caption_service.spaces_zero import apply_zero_gpu

_model: Any = None
_processor: Any = None


def _force_model_cuda() -> bool:
    return os.environ.get("LFM_SATELLITE_FORCE_MODEL_CUDA", "").lower() in ("1", "true", "yes")


def reset_model() -> None:
    global _model, _processor
    _model = None
    _processor = None


def ensure_satellite_model_loaded() -> tuple[Any, Any]:
    """
    Load weights once (outside ``@spaces.GPU``).

    Set ``LFM_SATELLITE_FORCE_MODEL_CUDA=1`` on Hugging Face ZeroGPU Spaces so weights
    register on ``cuda`` during emulation. Use ``LFM_SATELLITE_EAGER_LOAD=1`` + lifespan
    to warm before first request.
    """
    global _model, _processor
    if _model is not None and _processor is not None:
        return _model, _processor
    try:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except ImportError as e:
        raise RuntimeError('Install optional deps: pip install -e ".[model]"') from e

    s = get_settings()
    mid = s.model_id
    torch_dtype: Any = None
    if s.torch_dtype != "auto":
        import torch as T

        torch_dtype = getattr(T, s.torch_dtype, None) or T.bfloat16
    _processor = AutoProcessor.from_pretrained(mid, trust_remote_code=True)
    base_kw: dict[str, Any] = {"trust_remote_code": True}
    if torch_dtype is not None:
        base_kw["torch_dtype"] = torch_dtype
    try:
        _model = AutoModelForImageTextToText.from_pretrained(mid, device_map="auto", **base_kw)
    except ValueError as e:
        if "accelerate" not in str(e).lower():
            raise
        _model = AutoModelForImageTextToText.from_pretrained(mid, **base_kw)
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _model = _model.to(dev)

    if _force_model_cuda():
        try:
            dm = getattr(_model, "hf_device_map", None) or {}
            if not dm:
                _model = _model.to("cuda")
        except Exception:
            pass
    elif torch.cuda.is_available():
        try:
            dm = getattr(_model, "hf_device_map", None) or {}
            if not dm and str(next(_model.parameters()).device) == "cpu":
                _model = _model.to("cuda")
        except Exception:
            pass

    return _model, _processor


def _raw_model_generate(gen_kwargs: dict[str, Any]) -> Any:
    global _model
    if _model is None:
        raise RuntimeError("model not loaded; call ensure_satellite_model_loaded() first")
    try:
        return _model.generate(**gen_kwargs)
    except TypeError:
        gen2 = {k: v for k, v in gen_kwargs.items() if k != "min_p"}
        return _model.generate(**gen2)


_model_generate_gpu = apply_zero_gpu(_raw_model_generate)


def infer_transformers(req: SatelliteInferRequest) -> SatelliteInferResponse:
    model, processor = ensure_satellite_model_loaded()
    device = model.device
    raw = base64.b64decode(req.image_base64, validate=False)
    pil = Image.open(BytesIO(raw)).convert("RGB")
    safe = (
        "Do not output latitude/longitude or place names. Describe land cover, water, roads, and shadows only."
        if req.ranked_clue_safe
        else "Avoid raw coordinate numbers."
    )
    user = f"Describe this satellite or aerial image in two short sentences for a geography game. {safe}"
    conversation = [{"role": "user", "content": [{"type": "image", "image": pil}, {"type": "text", "text": user}]}]
    inputs = processor.apply_chat_template(
        conversation,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
        tokenize=True,
    )
    if hasattr(inputs, "to"):
        inputs = inputs.to(device)
    else:
        inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}
    in_len = int(inputs["input_ids"].shape[1])
    s = get_settings()
    gen_kw = {
        **inputs,
        "max_new_tokens": s.max_new_tokens,
        "do_sample": True,
        "temperature": 0.1,
        "repetition_penalty": 1.05,
        "min_p": 0.15,
    }
    out = _model_generate_gpu(gen_kw)
    new_tok = out[:, in_len:]
    text = processor.batch_decode(new_tok, skip_special_tokens=True)[0].strip()
    return SatelliteInferResponse(caption=text, model_id=s.model_id)
