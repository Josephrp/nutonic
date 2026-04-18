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


def test_stochastic_stub_reproducible_with_seed() -> None:
    client = TestClient(app)
    body = {
        "request_id": "deterministic-stub-test",
        "center": {"lat": 40.7128, "lon": -74.0060},
        "count": 4,
        "sampling_mode": "STOCHASTIC_S2_FOOTPRINT",
        "jitter_seed": 424242,
        "area_radius_m": 500.0,
        "image_width": 64,
        "image_height": 64,
    }
    a = client.post("/api/v1/panos/sample", json=body)
    b = client.post("/api/v1/panos/sample", json=body)
    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    ja, jb = a.json(), b.json()
    assert ja["cache_key"] == jb["cache_key"]
    for fa, fb in zip(ja["frames"], jb["frames"]):
        assert fa["heading_deg"] == fb["heading_deg"]
        assert fa["image_base64"] == fb["image_base64"]


def test_min_anchor_separation_stub_returns_503() -> None:
    client = TestClient(app)
    r = client.post(
        "/api/v1/panos/sample",
        json={
            "request_id": "impossible-separation",
            "center": {"lat": 51.5, "lon": -0.12},
            "count": 4,
            "sampling_mode": "STOCHASTIC_S2_FOOTPRINT",
            "jitter_seed": 1,
            "area_radius_m": 80.0,
            "min_anchor_separation_m": 1.0e9,
            "image_width": 32,
            "image_height": 32,
        },
    )
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert "message" in detail
