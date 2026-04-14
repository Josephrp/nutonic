from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from streetview_pano_service.main import app


def _post_sample(client: TestClient, path: str) -> object:
    rid = str(uuid.uuid4())
    r = client.post(
        path,
        json={
            "request_id": rid,
            "center": {"lat": -33.86, "lon": 151.2},
            "count": 3,
            "radius_m": 80,
            "heading_mode": "RADIAL_OR_RANDOM",
            "image_width": 128,
            "image_height": 128,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["request_id"] == rid
    assert len(data["frames"]) == 3
    for fr in data["frames"]:
        assert fr["pano_id"]
        assert "image_base64" in fr
        assert len(fr["image_base64"]) > 50
        assert fr["heading_deg"] is not None
    return data


def test_panos_sample_returns_frames_legacy_path() -> None:
    _post_sample(TestClient(app), "/v1/panos/sample")


def test_panos_sample_returns_frames_api_v1_path() -> None:
    _post_sample(TestClient(app), "/api/v1/panos/sample")
