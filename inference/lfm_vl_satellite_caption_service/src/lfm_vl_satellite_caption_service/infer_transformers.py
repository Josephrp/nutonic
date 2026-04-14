from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

from PIL import Image

from lfm_vl_satellite_caption_service.config import get_settings
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest, SatelliteInferResponse

_model: Any = None
_processor: Any = None


def reset_model() -> None:
    global _model, _processor
    _model = None
    _processor = None


def _load():
    global _model, _processor
    if _model is not None:
        return _model, _processor
    try:
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
    kw: dict[str, Any] = {"device_map": "auto", "trust_remote_code": True}
    if torch_dtype is not None:
        kw["torch_dtype"] = torch_dtype
    _model = AutoModelForImageTextToText.from_pretrained(mid, **kw)
    return _model, _processor


def infer_transformers(req: SatelliteInferRequest) -> SatelliteInferResponse:
    model, processor = _load()
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
    gen_kw = {**inputs, "max_new_tokens": s.max_new_tokens, "do_sample": True, "temperature": 0.1, "repetition_penalty": 1.05}
    try:
        gen_kw["min_p"] = 0.15
        out = model.generate(**gen_kw)
    except TypeError:
        gen_kw.pop("min_p", None)
        out = model.generate(**gen_kw)
    new_tok = out[:, in_len:]
    text = processor.batch_decode(new_tok, skip_special_tokens=True)[0].strip()
    return SatelliteInferResponse(caption=text, model_id=s.model_id)
