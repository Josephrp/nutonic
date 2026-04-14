from __future__ import annotations

from typing import Any

import httpx

from lfm_vl_satellite_caption_service.config import get_settings
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest, SatelliteInferResponse


def _caption(client: httpx.Client, b64: str, *, ranked_safe: bool) -> str:
    s = get_settings()
    safe = (
        "Do not output latitude/longitude or place names. Describe land cover, water, and structure footprints only."
        if ranked_safe
        else "Avoid raw coordinate numbers."
    )
    url = f"{s.openai_base_url}/chat/completions"
    body = {
        "model": s.openai_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": f"Two short sentences about this satellite image. {safe}"},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": s.max_new_tokens,
    }
    r = client.post(url, json=body, headers={"Authorization": f"Bearer {s.openai_api_key}"})
    r.raise_for_status()
    data = r.json()
    ch = data.get("choices", [{}])[0]
    msg = ch.get("message") or {}
    c = msg.get("content")
    if not isinstance(c, str):
        raise ValueError("OpenAI-compatible: missing choices[0].message.content")
    return c.strip()


def infer_openai(req: SatelliteInferRequest, *, client: httpx.Client | None = None) -> SatelliteInferResponse:
    own = client is None
    c = client or httpx.Client(timeout=httpx.Timeout(300.0))
    try:
        text = _caption(c, req.image_base64, ranked_safe=req.ranked_clue_safe)
        return SatelliteInferResponse(caption=text, model_id=get_settings().openai_model)
    finally:
        if own:
            c.close()
