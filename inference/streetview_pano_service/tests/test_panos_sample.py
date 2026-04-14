from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from streetview_pano_service.main import app


def test_panos_sample_returns_frames() -> None:
    client = TestClient(app)
    rid = str(uuid.uuid4())
    r = client.post(
        "/v1/panos/sample",
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
    assert r.status_code == 200
    data = r.json()
    assert data["request_id"] == rid
    assert len(data["frames"]) == 3
    for i, fr in enumerate(data["frames"]):
        assert fr["pano_id"]
        assert "image_base64" in fr
        assert len(fr["image_base64"]) > 50
        assert fr["heading_deg"] is not None
