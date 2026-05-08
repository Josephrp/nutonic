from __future__ import annotations

from fastapi.testclient import TestClient

from lfm_vl_hint_service.main import app


def test_from_frames_stub() -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/suggestions/from_frames",
        json={
            "frames": [
                {"image_base64": "QUJD", "pano_id": "p-0", "heading_deg": 10.0},
                {"image_base64": "REVGRg==", "pano_id": "p-1", "heading_deg": 70.0},
            ],
            "ranked_clue_safe": True,
            "prompt_template_version": "stub-v1",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["suggestions"]) == 2
    assert data["suggestions"][0]["viewpoint_id"] == "p-0"
    assert "degree bearing" in data["suggestions"][0]["text"]


def test_health_reports_stub_backend() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["lfm_backend"] == "stub"
    assert body["lfm_backend_config"] in ("stub", "auto")
    assert body["model_id"]
    assert "openai_base_url" not in body
