from __future__ import annotations

from fastapi.testclient import TestClient

from lfm_vl_hint_service.main import app


def test_pro_brief_fuse_oceanscout_claim_safe() -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/pro/brief/fuse",
        json={
            "profile": "oceanscout_ship_detection",
            "tim_summary": {"vessel_candidates": []},
            "artifact_refs": [{"artifact_id": "vessel_candidates", "kind": "json"}],
            "jobs": [{"job_id": "a", "profile": "oceanscout_ship_detection", "center_lat": 34.0, "center_lon": -119.0}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["confidence"] == "limited"
    assert "corroboration" in body["executive_summary"].lower()
    assert "legal certainty" in " ".join(body["limitations"]).lower()


def test_pro_brief_fuse_rejects_cross_aoi_without_override() -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/pro/brief/fuse",
        json={
            "profile": "brief_only",
            "jobs": [
                {"job_id": "california", "center_lat": 34.0, "center_lon": -119.0},
                {"job_id": "bangladesh", "center_lat": 23.8, "center_lon": 90.4},
            ],
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "aoi_mismatch"
