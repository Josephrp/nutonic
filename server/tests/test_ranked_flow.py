"""IMP-090 ranked start/submit (reloads ``nutonic_server.main`` for env isolation)."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def ranked_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FEATURE_RANKED", "true")
    monkeypatch.setenv("FEATURE_COMMUNITY_LB_POST", "false")
    monkeypatch.setenv("NUTONIC_RANKED_DATABASE_URL", f"sqlite:///{tmp_path}/ranked.db")
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    import nutonic_server.main as main

    importlib.reload(main)
    return TestClient(main.app)


def test_ranked_forfeit_blocks_submit(ranked_client: TestClient) -> None:
    tok = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    start = ranked_client.post("/api/v1/ranked/rounds/start", headers=headers, json={"map_id": "demo"})
    assert start.status_code == 200, start.text
    rid = start.json()["round_id"]
    ticket = start.json()["round_ticket"]

    ff = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/forfeit-ranked-integrity",
        headers=headers,
        json={"reason": "assists"},
    )
    assert ff.status_code == 200, ff.text
    assert ff.json()["status"] == "forfeited"

    submit = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={**headers, "Idempotency-Key": "rk-forfeit"},
        json={"guess_lat": 48.2082, "guess_lon": 16.3738, "round_ticket": ticket},
    )
    assert submit.status_code == 409


def test_ranked_start_submit_verifies_distance(ranked_client: TestClient) -> None:
    tok = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    start = ranked_client.post("/api/v1/ranked/rounds/start", headers=headers, json={"map_id": "demo"})
    assert start.status_code == 200, start.text
    body = start.json()
    rid = body["round_id"]
    ticket = body["round_ticket"]
    assert body["clue"]["map_id"] == "demo"
    assert "truth_lat" not in body["clue"]
    pack = body["clue"].get("streetview_hint_pack")
    assert isinstance(pack, list) and len(pack) >= 1
    assert pack[0].get("text")

    submit = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={**headers, "Idempotency-Key": "rk-1"},
        json={"guess_lat": 48.2082, "guess_lon": 16.3738, "round_ticket": ticket},
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["distance_km"] < 1.0
    assert submit.json()["score_points"] > 0

    dup = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={**headers, "Idempotency-Key": "rk-1"},
        json={"guess_lat": 0.0, "guess_lon": 0.0, "round_ticket": ticket},
    )
    assert dup.status_code == 200
    assert dup.json()["distance_km"] < 1.0

    conflict = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={**headers, "Idempotency-Key": "rk-2"},
        json={"guess_lat": 10.0, "guess_lon": 10.0, "round_ticket": ticket},
    )
    assert conflict.status_code == 409


def test_bundle_demo_still_bytes() -> None:
    from fastapi.testclient import TestClient

    from nutonic_server.main import app

    r = TestClient(app).get("/api/v1/bundles/nutonic.bundle.v1.demo_still")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert len(r.content) > 100


def test_guess_record_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_GUESSES_RECORD", "true")
    monkeypatch.setenv("NUTONIC_GUESS_TELEMETRY_DATABASE_URL", f"sqlite:///{tmp_path}/g.db")
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    import nutonic_server.main as main

    importlib.reload(main)
    c = TestClient(main.app)
    tok = c.post("/api/v1/auth/token").json()["access_token"]
    r = c.post(
        "/api/v1/maps/demo/guesses/record",
        headers={"Authorization": f"Bearer {tok}", "Idempotency-Key": "g-1"},
        json={
            "round_instance_id": "demo|loc|1",
            "location_id": "demo-vienna-001",
            "guess_lat": 48.0,
            "guess_lon": 16.0,
            "client_distance_km": 12.3,
            "ruleset_version": "v1",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] >= 1


def test_pro_job_stub_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_PRO_JOBS", "true")
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    import nutonic_server.main as main

    importlib.reload(main)
    c = TestClient(main.app)
    tok = c.post("/api/v1/auth/token").json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    j = c.post("/api/v1/pro/jobs", headers=h, json={"center_lat": 1.0, "center_lon": 2.0})
    assert j.status_code == 200
    jid = j.json()["job_id"]
    s1 = c.get(f"/api/v1/pro/jobs/{jid}", headers=h)
    assert s1.status_code == 200
    assert s1.json()["status"] == "queued"
    s2 = c.get(f"/api/v1/pro/jobs/{jid}", headers=h)
    assert s2.json()["status"] == "completed"
