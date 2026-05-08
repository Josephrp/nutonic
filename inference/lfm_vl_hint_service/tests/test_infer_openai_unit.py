from __future__ import annotations

import json

import httpx

from lfm_vl_hint_service.config import get_settings, reset_settings_cache
from lfm_vl_hint_service.infer_openai import infer_from_frames_openai, narrative_fuse_openai
from lfm_vl_hint_service.models import HintFrame, SuggestionsFromFramesRequest


def _chat_completion_handler(request: httpx.Request) -> httpx.Response:
    if not str(request.url).rstrip("/").endswith("chat/completions"):
        return httpx.Response(404)
    body = json.loads(request.content.decode())
    assert "messages" in body
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "Tree-lined curb with low-rise masonry facades."}}]},
    )


def test_infer_from_frames_openai_mocked(monkeypatch) -> None:
    monkeypatch.setenv("LFM_VL_BACKEND", "openai_compatible")
    monkeypatch.setenv("LFM_OPENAI_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LFM_OPENAI_MODEL", "LiquidAI/LFM2.5-VL-450M")
    reset_settings_cache()
    assert get_settings().backend == "openai_compatible"

    transport = httpx.MockTransport(_chat_completion_handler)
    req = SuggestionsFromFramesRequest(
        frames=[HintFrame(image_base64="Zm9v", pano_id="pv-1", heading_deg=12.0)],
        ranked_clue_safe=True,
    )
    with httpx.Client(transport=transport, base_url="http://llm.test/v1") as client:
        out = infer_from_frames_openai(req, client=client)
    assert len(out.suggestions) == 1
    assert out.suggestions[0].viewpoint_id == "pv-1"
    assert "masonry" in out.suggestions[0].text.lower()


def test_narrative_fuse_openai_mocked(monkeypatch) -> None:
    monkeypatch.setenv("LFM_VL_BACKEND", "openai_compatible")
    monkeypatch.setenv("LFM_OPENAI_BASE_URL", "http://llm.test/v1")
    reset_settings_cache()

    transport = httpx.MockTransport(_chat_completion_handler)
    with httpx.Client(transport=transport, base_url="http://llm.test/v1") as client:
        text = narrative_fuse_openai([("a", "one"), ("b", "two")], client=client)
    assert "masonry" in text.lower() or "tree" in text.lower()
