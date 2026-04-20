"""
In-process **official** LFM-VL inference via Hugging Face ``transformers`` (Liquid docs).

**Weights:** loaded once via ``ensure_transformers_model_loaded()`` (module scope / eager startup),
not inside ``@spaces.GPU``. **GPU slice:** only ``model.generate(...)`` runs through
``apply_zero_gpu`` for Hugging Face ZeroGPU compatibility.

Install: ``pip install -e ".[model]"`` then set ``LFM_VL_BACKEND=transformers``.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from typing import Any

from PIL import Image

from lfm_vl_hint_service.config import get_settings
from lfm_vl_hint_service.models import SuggestionItem, SuggestionsFromFramesRequest, SuggestionsFromFramesResponse
from lfm_vl_hint_service.prompts import narrative_system_prompt, narrative_user_payload, streetview_user_prompt
from lfm_vl_hint_service.spaces_zero import apply_zero_gpu

_model: Any = None
_processor: Any = None


def _force_model_cuda() -> bool:
    """HF ZeroGPU / CUDA emulation: place weights on ``cuda`` even when no physical GPU yet."""
    return os.environ.get("LFM_VL_FORCE_MODEL_CUDA", "").lower() in ("1", "true", "yes")


def reset_transformers_model() -> None:
    """Test helper: unload HF weights."""
    global _model, _processor
    _model = None
    _processor = None


def _pil_from_b64(b64: str) -> Image.Image:
    raw = base64.b64decode(b64, validate=False)
    return Image.open(BytesIO(raw)).convert("RGB")


def ensure_transformers_model_loaded() -> tuple[Any, Any]:
    """
    Load processor + model **once** (outside ``@spaces.GPU``).

    Call from FastAPI ``lifespan`` when ``LFM_VL_EAGER_LOAD=1``, or lazily on first inference.
    For Hugging Face ZeroGPU Spaces, set ``LFM_VL_FORCE_MODEL_CUDA=1`` so weights sit on
    ``cuda`` during CUDA emulation before real GPU inside ``generate``.
    """
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
    resolved_dtype: Any = None
    if dt_name != "auto":
        import torch as T

        resolved_dtype = getattr(T, dt_name, None)
        if resolved_dtype is None:
            resolved_dtype = T.bfloat16

    _processor = AutoProcessor.from_pretrained(mid, trust_remote_code=True)
    base_kw: dict[str, Any] = {"trust_remote_code": True}
    if resolved_dtype is not None:
        base_kw["dtype"] = resolved_dtype
    try:
        _model = AutoModelForImageTextToText.from_pretrained(mid, device_map="auto", **base_kw)
    except TypeError:
        if resolved_dtype is None:
            raise
        base_kw.pop("dtype", None)
        base_kw["torch_dtype"] = resolved_dtype
        _model = AutoModelForImageTextToText.from_pretrained(mid, device_map="auto", **base_kw)
    except ValueError as e:
        if "accelerate" not in str(e).lower():
            raise
        kw2: dict[str, Any] = {"trust_remote_code": True}
        if resolved_dtype is not None:
            kw2["dtype"] = resolved_dtype
        try:
            _model = AutoModelForImageTextToText.from_pretrained(mid, **kw2)
        except TypeError:
            if resolved_dtype is None:
                raise
            kw2.pop("dtype", None)
            kw2["torch_dtype"] = resolved_dtype
            _model = AutoModelForImageTextToText.from_pretrained(mid, **kw2)
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
    """Only ``model.generate`` — wrapped by ``apply_zero_gpu`` for ZeroGPU."""
    global _model
    if _model is None:
        raise RuntimeError("transformers model not loaded; call ensure_transformers_model_loaded() first")
    try:
        return _model.generate(**gen_kwargs)
    except TypeError:
        gen2 = {k: v for k, v in gen_kwargs.items() if k != "min_p"}
        return _model.generate(**gen2)


_model_generate_gpu = apply_zero_gpu(_raw_model_generate)


def infer_from_frames_transformers(req: SuggestionsFromFramesRequest) -> SuggestionsFromFramesResponse:
    model, processor = ensure_transformers_model_loaded()
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
        output_ids = _model_generate_gpu(gen_kwargs)
        new_tokens = output_ids[:, in_len:]
        text = processor.batch_decode(new_tokens, skip_special_tokens=True)[0].strip()
        out.append(SuggestionItem(text=text, viewpoint_id=vid, rank=i + 1))

    return SuggestionsFromFramesResponse(suggestions=out)


def narrative_fuse_transformers(captions: list[tuple[str, str]]) -> str:
    model, processor = ensure_transformers_model_loaded()
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
    gen_kwargs = {
        **inputs,
        "max_new_tokens": min(512, settings.max_new_tokens),
        "do_sample": True,
        "temperature": 0.2,
    }
    output_ids = _model_generate_gpu(gen_kwargs)
    new_tokens = output_ids[:, in_len:]
    return processor.batch_decode(new_tokens, skip_special_tokens=True)[0].strip()
