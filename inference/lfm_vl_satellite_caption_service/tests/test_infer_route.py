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
