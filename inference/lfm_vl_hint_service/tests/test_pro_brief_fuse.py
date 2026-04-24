from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import lfm_vl_hint_service.dispatch as dispatch
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
    assert "Observation coverage artifact is missing" in " ".join(body["key_findings"])


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


def test_pro_brief_fuse_uses_profile_artifact_context() -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/pro/brief/fuse",
        json={
            "profile": "wildfire",
            "tim_summary": {"has_npz": True, "branch": "S2L2A_full"},
            "artifact_refs": [
                {"artifact_id": "scene_provenance", "kind": "json"},
                {"artifact_id": "wildfire_aoi_overlay", "kind": "geojson"},
            ],
            "jobs": [{"job_id": "fire", "profile": "wildfire", "center_lat": 34.0, "center_lon": -119.0}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["confidence"] == "moderate"
    assert "Temporal scene provenance" in body["executive_summary"]
    assert "Prompt template: pro-brief-v1" in body["sections"][1]["body"]


def test_pro_brief_fuse_softens_generated_certainty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "effective_lfm_backend", lambda: "openai_compatible")

    def _fake_openai(**_kwargs):  # noqa: ANN003
        return "Confirmed vessel proves illegal activity detected near the AOI."

    monkeypatch.setattr(dispatch, "pro_brief_fuse_openai", _fake_openai)
    payload = dispatch.pro_brief_fuse_text(
        profile="oceanscout_ship_detection",
        tim_summary={"has_npz": True},
        artifact_refs=[{"artifact_id": "observation_coverage", "kind": "json"}],
        jobs=[{"job_id": "ocean", "center_lat": 1.0, "center_lon": 2.0}],
        force_compose=False,
        max_compose_distance_km=500.0,
    )
    combined = " ".join([payload["executive_summary"], *payload["key_findings"], *payload["warnings"]]).lower()
    assert "illegal activity detected" not in combined
    assert "confirmed vessel" not in combined
    assert "softened" in combined
