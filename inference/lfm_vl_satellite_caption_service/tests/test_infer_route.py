from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from lfm_vl_satellite_caption_service.config import reset_settings_cache
from lfm_vl_satellite_caption_service.infer_openai import infer_openai
from lfm_vl_satellite_caption_service.main import app
from lfm_vl_satellite_caption_service.models import SatelliteInferRequest
from lfm_vl_satellite_caption_service.prompts import satellite_openai_user_prompt, satellite_transformers_user_prompt


def test_health_and_infer_stub() -> None:
    client = TestClient(app)
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["lfm_satellite_backend"] == "stub"
    r = client.post(
        "/v1/infer",
        json={"task": "caption", "image_base64": "Zm9v", "ranked_clue_safe": True},
    )
    assert r.status_code == 200
    assert "stub" in r.json()["caption"].lower()
    assert r.json()["pipeline"] == "satellite_lfm_vl_specialist"


def test_pro_caption_alias_preserves_profile_context() -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/pro/caption",
        json={
            "task": "caption",
            "image_base64": "Zm9v",
            "analysis_profile": "wildfire",
            "contract_id": "nutonic.pro.caption.v1",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["analysis_profile"] == "wildfire"
    assert body["contract_id"] == "nutonic.pro.caption.v1"


def test_satellite_prompts_include_profile_context() -> None:
    transformers_prompt = satellite_transformers_user_prompt(
        ranked_clue_safe=True,
        analysis_profile="flood_pulse",
        contract_id="nutonic.pro.caption.v1",
    )
    openai_prompt = satellite_openai_user_prompt(
        ranked_clue_safe=True,
        analysis_profile="flood_pulse",
        contract_id="nutonic.pro.caption.v1",
    )

    assert "PRO analysis profile: flood_pulse" in transformers_prompt
    assert "Output contract: nutonic.pro.caption.v1" in transformers_prompt
    assert "PRO analysis profile: flood_pulse" in openai_prompt
    assert "Output contract: nutonic.pro.caption.v1" in openai_prompt


def test_openai_backend_preserves_profile_context(monkeypatch) -> None:
    monkeypatch.setenv("LFM_SATELLITE_OPENAI_MODEL", "test-model")
    reset_settings_cache()
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(200, json={"choices": [{"message": {"content": "caption"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    req = SatelliteInferRequest(
        image_base64="Zm9v",
        analysis_profile="oceanscout_ship_detection",
        contract_id="nutonic.pro.caption.v1",
    )

    try:
        out = infer_openai(req, client=client)
    finally:
        reset_settings_cache()
        client.close()

    assert out.caption == "caption"
    assert out.model_id == "test-model"
    assert out.analysis_profile == "oceanscout_ship_detection"
    assert out.contract_id == "nutonic.pro.caption.v1"
    assert "oceanscout_ship_detection" in str(captured["body"])
