"""OpenAI-compatible HTTP backend (vLLM / SGLang serving official LFM-VL weights)."""

from __future__ import annotations

from typing import Any

import httpx

from lfm_vl_hint_service.config import LfmVlSettings, get_settings
from lfm_vl_hint_service.models import (
    SuggestionItem,
    SuggestionsFromFramesRequest,
    SuggestionsFromFramesResponse,
)
from lfm_vl_hint_service.prompts import narrative_system_prompt, narrative_user_payload, streetview_user_prompt


def _chat_completion(
    client: httpx.Client,
    settings: LfmVlSettings,
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    url = f"{settings.openai_base_url}/chat/completions"
    body = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    r = client.post(url, json=body, headers={"Authorization": f"Bearer {settings.openai_api_key}"})
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices")
    if not choices or not isinstance(choices[0], dict):
        raise ValueError("OpenAI-compatible response missing choices[0]")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str):
        raise ValueError("OpenAI-compatible response missing message.content string")
    return content.strip()


def _image_part(b64: str) -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
    }


def infer_from_frames_openai(
    req: SuggestionsFromFramesRequest,
    *,
    client: httpx.Client | None = None,
) -> SuggestionsFromFramesResponse:
    settings = get_settings()
    own_client = client is None
    c = client or httpx.Client(timeout=httpx.Timeout(300.0))
    try:
        out: list[SuggestionItem] = []
        for i, fr in enumerate(req.frames):
            vid = fr.pano_id if fr.pano_id else f"decoy-{i}"
            user_text = streetview_user_prompt(viewpoint_label=vid, heading_deg=fr.heading_deg, req=req)
            messages: list[dict[str, Any]] = [
                {
                    "role": "user",
                    "content": [
                        _image_part(fr.image_base64),
                        {"type": "text", "text": user_text},
                    ],
                }
            ]
            text = _chat_completion(c, settings, messages=messages, max_tokens=settings.max_new_tokens)
            out.append(SuggestionItem(text=text, viewpoint_id=vid, rank=i + 1))
        return SuggestionsFromFramesResponse(suggestions=out)
    finally:
        if own_client:
            c.close()


def narrative_fuse_openai(
    captions: list[tuple[str, str]],
    *,
    client: httpx.Client | None = None,
    max_tokens: int = 512,
) -> str:
    settings = get_settings()
    own_client = client is None
    c = client or httpx.Client(timeout=httpx.Timeout(120.0))
    try:
        messages = [
            {"role": "system", "content": narrative_system_prompt()},
            {"role": "user", "content": narrative_user_payload(captions)},
        ]
        return _chat_completion(c, settings, messages=messages, max_tokens=max_tokens)
    finally:
        if own_client:
            c.close()
