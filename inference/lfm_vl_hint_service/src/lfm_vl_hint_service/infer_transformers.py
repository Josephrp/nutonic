"""
In-process **official** LFM-VL inference via Hugging Face ``transformers`` (Liquid docs).

Install: ``pip install -e ".[model]"`` then set ``LFM_VL_BACKEND=transformers``.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

from PIL import Image

from lfm_vl_hint_service.config import get_settings
from lfm_vl_hint_service.models import SuggestionItem, SuggestionsFromFramesRequest, SuggestionsFromFramesResponse
from lfm_vl_hint_service.prompts import narrative_system_prompt, narrative_user_payload, streetview_user_prompt

_model: Any = None
_processor: Any = None


def reset_transformers_model() -> None:
    """Test helper: unload HF weights."""
    global _model, _processor
    _model = None
    _processor = None


def _pil_from_b64(b64: str) -> Image.Image:
    raw = base64.b64decode(b64, validate=False)
    return Image.open(BytesIO(raw)).convert("RGB")


def _load_hf():
    global _model, _processor
    if _model is not None and _processor is not None:
        return _model, _processor
    try:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except ImportError as e:
        raise RuntimeError(
            'LFM_VL_BACKEND=transformers requires optional deps: pip install -e ".[model]" '
            "(torch, transformers, pillow; accelerate recommended for device_map=\"auto\")."
        ) from e

    settings = get_settings()
    mid = settings.model_id
    dt_name = settings.torch_dtype
    torch_dtype: Any = None
    if dt_name != "auto":
        import torch as T

        torch_dtype = getattr(T, dt_name, None)
        if torch_dtype is None:
            torch_dtype = T.bfloat16

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
    return _model, _processor


def infer_from_frames_transformers(req: SuggestionsFromFramesRequest) -> SuggestionsFromFramesResponse:
    model, processor = _load_hf()
    device = model.device
    out: list[SuggestionItem] = []
    settings = get_settings()

    for i, fr in enumerate(req.frames):
        vid = fr.pano_id if fr.pano_id else f"decoy-{i}"
        pil = _pil_from_b64(fr.image_base64)
        user_text = streetview_user_prompt(viewpoint_label=vid, heading_deg=fr.heading_deg, req=req)
        conversation: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil},
                    {"type": "text", "text": user_text},
                ],
            }
        ]
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

        input_ids = inputs["input_ids"]
        in_len = int(input_ids.shape[1])

        gen_kwargs: dict[str, Any] = {
            **inputs,
            "max_new_tokens": settings.max_new_tokens,
            "do_sample": True,
            "temperature": 0.1,
            "repetition_penalty": 1.05,
            "min_p": 0.15,
        }
        try:
            output_ids = model.generate(**gen_kwargs)
        except TypeError:
            gen_kwargs.pop("min_p", None)
            output_ids = model.generate(**gen_kwargs)
        new_tokens = output_ids[:, in_len:]
        text = processor.batch_decode(new_tokens, skip_special_tokens=True)[0].strip()
        out.append(SuggestionItem(text=text, viewpoint_id=vid, rank=i + 1))

    return SuggestionsFromFramesResponse(suggestions=out)


def narrative_fuse_transformers(captions: list[tuple[str, str]]) -> str:
    model, processor = _load_hf()
    device = model.device
    settings = get_settings()
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": narrative_system_prompt()},
        {
            "role": "user",
            "content": [{"type": "text", "text": narrative_user_payload(captions)}],
        },
    ]
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
    output_ids = model.generate(
        **inputs,
        max_new_tokens=min(512, settings.max_new_tokens),
        do_sample=True,
        temperature=0.2,
    )
    new_tokens = output_ids[:, in_len:]
    return processor.batch_decode(new_tokens, skip_special_tokens=True)[0].strip()
