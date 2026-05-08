from __future__ import annotations

from fastapi.testclient import TestClient

from lfm_vl_hint_service.main import app


def test_narrative_fuse_stub() -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/narrative/fuse",
        json={
            "captions": [
                {"viewpoint_id": "a", "text": "First scene without coords."},
                {"viewpoint_id": "b", "text": "Second scene without coords."},
            ],
            "mission_flavor": "neutral",
        },
    )
    assert r.status_code == 200
    assert "narrative" in r.json()
    assert "a:" in r.json()["narrative"]
