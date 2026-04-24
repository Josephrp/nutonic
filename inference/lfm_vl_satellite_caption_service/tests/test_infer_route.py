from __future__ import annotations

from fastapi.testclient import TestClient

from lfm_vl_satellite_caption_service.main import app


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
