"""IMP-090 ranked start/submit (reloads ``nutonic_server.main`` for env isolation)."""

from __future__ import annotations

import importlib
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from catalog_samples import manifest_location_for_sample_map, sample_map_id, truth_coordinates_for_map


def test_ranked_start_returns_403_when_feature_disabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_RANKED", "false")
    monkeypatch.setenv("NUTONIC_RANKED_DATABASE_URL", f"sqlite:///{tmp_path}/ranked_off.db")
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    import nutonic_server.main as main

    importlib.reload(main)
    c = TestClient(main.app)
    tok = c.post("/api/v1/auth/token").json()["access_token"]
    r = c.post(
        "/api/v1/ranked/rounds/start",
        headers={"Authorization": f"Bearer {tok}"},
        json={"map_id": sample_map_id()},
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body.get("error") == "feature_disabled"
    assert body.get("feature") == "ranked"


def test_ranked_submit_requires_idempotency_key(ranked_client: TestClient) -> None:
    mid = sample_map_id()
    tok = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    start = ranked_client.post("/api/v1/ranked/rounds/start", headers=headers, json={"map_id": mid})
    assert start.status_code == 200, start.text
    rid = start.json()["round_id"]
    ticket = start.json()["round_ticket"]
    submit = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers=headers,
        json={"guess_lat": 1.0, "guess_lon": 2.0, "round_ticket": ticket},
    )
    assert submit.status_code == 400, submit.text


def test_ranked_submit_rejects_round_ticket_for_other_session(ranked_client: TestClient) -> None:
    mid = sample_map_id()
    tlat, tlon = truth_coordinates_for_map(mid)
    tok_a = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    start = ranked_client.post(
        "/api/v1/ranked/rounds/start",
        headers={"Authorization": f"Bearer {tok_a}"},
        json={"map_id": mid},
    )
    assert start.status_code == 200, start.text
    rid = start.json()["round_id"]
    ticket = start.json()["round_ticket"]
    tok_b = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    submit = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={"Authorization": f"Bearer {tok_b}", "Idempotency-Key": "rk-other-session"},
        json={"guess_lat": tlat, "guess_lon": tlon, "round_ticket": ticket},
    )
    assert submit.status_code == 403, submit.text


def test_ranked_verified_leaderboard_after_submit(ranked_client: TestClient) -> None:
    mid = sample_map_id()
    tlat, tlon = truth_coordinates_for_map(mid)
    lb0 = ranked_client.get(f"/api/v1/maps/{mid}/leaderboard/ranked")
    assert lb0.status_code == 200
    assert lb0.json() == []

    tok = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    start = ranked_client.post("/api/v1/ranked/rounds/start", headers=headers, json={"map_id": mid})
    assert start.status_code == 200, start.text
    rid = start.json()["round_id"]
    ticket = start.json()["round_ticket"]
    sub = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={**headers, "Idempotency-Key": "rk-lb-test"},
        json={"guess_lat": tlat, "guess_lon": tlon, "round_ticket": ticket},
    )
    assert sub.status_code == 200, sub.text

    lb1 = ranked_client.get(f"/api/v1/maps/{mid}/leaderboard/ranked")
    assert lb1.status_code == 200
    rows = lb1.json()
    assert len(rows) == 1
    assert rows[0]["player_role"] == "RANKED"
    assert rows[0]["display_handle"].startswith("RNK-")
    assert rows[0]["score_points"] == sub.json()["score_points"]


def test_ranked_leaderboard_get_403_when_feature_disabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_RANKED", "false")
    monkeypatch.setenv("NUTONIC_RANKED_DATABASE_URL", f"sqlite:///{tmp_path}/r2.db")
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    import nutonic_server.main as main

    importlib.reload(main)
    c = TestClient(main.app)
    r = c.get(f"/api/v1/maps/{sample_map_id()}/leaderboard/ranked")
    assert r.status_code == 403
    assert r.json().get("feature") == "ranked"


def test_get_leaderboard_tier_ranked_matches_dedicated_path(ranked_client: TestClient) -> None:
    mid = sample_map_id()
    tlat, tlon = truth_coordinates_for_map(mid)
    tok = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    start = ranked_client.post("/api/v1/ranked/rounds/start", headers=headers, json={"map_id": mid})
    rid = start.json()["round_id"]
    ticket = start.json()["round_ticket"]
    ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={**headers, "Idempotency-Key": "rk-tier-alias"},
        json={"guess_lat": tlat, "guess_lon": tlon, "round_ticket": ticket},
    )
    via_tier = ranked_client.get(f"/api/v1/maps/{mid}/leaderboard?tier=ranked")
    dedicated = ranked_client.get(f"/api/v1/maps/{mid}/leaderboard/ranked")
    assert via_tier.status_code == 200 and dedicated.status_code == 200
    assert via_tier.json() == dedicated.json()


def test_prune_removes_stale_open_round_on_next_start(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "prune.db"
    monkeypatch.setenv("FEATURE_RANKED", "true")
    monkeypatch.setenv("NUTONIC_RANKED_DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    monkeypatch.setenv("NUTONIC_RANKED_STALE_OPEN_ROUND_MAX_AGE_SECONDS", "120")
    import nutonic_server.main as main

    importlib.reload(main)
    c = TestClient(main.app)
    mid = sample_map_id()
    tlat, tlon = truth_coordinates_for_map(mid)
    tok = c.post("/api/v1/auth/token").json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    start1 = c.post("/api/v1/ranked/rounds/start", headers=h, json={"map_id": mid})
    rid1 = start1.json()["round_id"]
    ticket1 = start1.json()["round_ticket"]

    import sqlite3

    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE ranked_rounds SET opened_at_epoch = 1 WHERE round_id = ?", (rid1,))
    conn.commit()
    conn.close()

    c.post("/api/v1/ranked/rounds/start", headers=h, json={"map_id": mid})

    gone = c.post(
        f"/api/v1/ranked/rounds/{rid1}/submit",
        headers={**h, "Idempotency-Key": "rk-after-prune"},
        json={"guess_lat": tlat, "guess_lon": tlon, "round_ticket": ticket1},
    )
    assert gone.status_code == 404, gone.text


def test_ranked_submit_rejects_expired_round_ticket(ranked_client: TestClient) -> None:
    from nutonic_server.settings import load_settings

    mid = sample_map_id()
    tlat, tlon = truth_coordinates_for_map(mid)
    s = load_settings()
    tok = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    sess = jwt.decode(tok, s.jwt_secret, algorithms=["HS256"])["session_id"]
    headers = {"Authorization": f"Bearer {tok}"}
    start = ranked_client.post("/api/v1/ranked/rounds/start", headers=headers, json={"map_id": mid})
    rid = start.json()["round_id"]
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    expired_ticket = jwt.encode(
        {
            "typ": "nutonic_ranked_round",
            "round_id": rid,
            "session_id": str(sess),
            "jti": "jti-expired",
            "iat": int(past.timestamp()),
            "exp": int(past.timestamp()),
        },
        s.jwt_secret,
        algorithm="HS256",
    )
    sub = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={**headers, "Idempotency-Key": "rk-expired-ticket"},
        json={"guess_lat": tlat, "guess_lon": tlon, "round_ticket": expired_ticket},
    )
    assert sub.status_code == 401, sub.text


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
    mid = sample_map_id()
    tlat, tlon = truth_coordinates_for_map(mid)
    tok = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    start = ranked_client.post("/api/v1/ranked/rounds/start", headers=headers, json={"map_id": mid})
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
        json={"guess_lat": tlat, "guess_lon": tlon, "round_ticket": ticket},
    )
    assert submit.status_code == 409


def test_ranked_start_submit_verifies_distance(ranked_client: TestClient) -> None:
    mid = sample_map_id()
    tlat, tlon = truth_coordinates_for_map(mid)
    tok = ranked_client.post("/api/v1/auth/token").json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}
    start = ranked_client.post("/api/v1/ranked/rounds/start", headers=headers, json={"map_id": mid})
    assert start.status_code == 200, start.text
    body = start.json()
    rid = body["round_id"]
    ticket = body["round_ticket"]
    assert body["clue"]["map_id"] == mid
    assert "truth_lat" not in body["clue"]
    pack = body["clue"].get("streetview_hint_pack")
    assert isinstance(pack, list) and len(pack) >= 1
    assert pack[0].get("text")
    sat = body["clue"].get("satellite_caption_sidecar")
    if sat is not None:
        assert isinstance(sat, dict)
        assert sat.get("caption")

    submit = ranked_client.post(
        f"/api/v1/ranked/rounds/{rid}/submit",
        headers={**headers, "Idempotency-Key": "rk-1"},
        json={"guess_lat": tlat, "guess_lon": tlon, "round_ticket": ticket},
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


def test_bundle_idempo_nyc_still_bytes() -> None:
    from fastapi.testclient import TestClient

    from nutonic_server.main import app

    r = TestClient(app).get("/api/v1/bundles/nutonic.still.v1.idempo_nyc")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert len(r.content) > 100


def test_bundle_unknown_returns_404() -> None:
    from fastapi.testclient import TestClient

    from nutonic_server.main import app

    r = TestClient(app).get("/api/v1/bundles/nutonic.bundle.v99.missing")
    assert r.status_code == 404


def test_bundle_registry_contains_shipped_ids() -> None:
    from nutonic_server.bundles import list_registered_bundle_ids

    ids = list_registered_bundle_ids()
    assert "nutonic.bundle.v1.demo_still" in ids
    assert "nutonic.still.v1.idempo_nyc" in ids


def test_guess_record_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_GUESSES_RECORD", "true")
    monkeypatch.setenv("NUTONIC_GUESS_TELEMETRY_DATABASE_URL", f"sqlite:///{tmp_path}/g.db")
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    import nutonic_server.main as main

    importlib.reload(main)
    c = TestClient(main.app)
    loc = manifest_location_for_sample_map()
    mid, lid = loc.map_id, loc.location_id
    tok = c.post("/api/v1/auth/token").json()["access_token"]
    r = c.post(
        f"/api/v1/maps/{mid}/guesses/record",
        headers={"Authorization": f"Bearer {tok}", "Idempotency-Key": "g-1"},
        json={
            "round_instance_id": f"{mid}|{lid}|1",
            "location_id": lid,
            "guess_lat": float(loc.truth_lat) - 0.01,
            "guess_lon": float(loc.truth_lon) + 0.01,
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
    body = j.json()
    jid = body["job_id"]
    assert body.get("inference_upstream_ok") is None
    status = None
    for _ in range(50):
        s1 = c.get(f"/api/v1/pro/jobs/{jid}", headers=h)
        assert s1.status_code == 200
        status = s1.json()
        if status["status"] == "completed":
            break
        time.sleep(0.02)
    assert status is not None
    assert status["status"] == "completed"
    assert status["materialization_summary"]["mode"] == "no_worker_configured"


def test_pro_job_required_origin_failure_surfaces_on_status(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_PRO_JOBS", "true")
    monkeypatch.setenv("NUTONIC_LEADERBOARD_DATABASE_URL", "memory")
    monkeypatch.setenv("NUTONIC_INFERENCE_WORKER_BASE_URL", "http://127.0.0.1:59998")
    monkeypatch.setenv("NUTONIC_PRO_REQUIRED_ORIGINS", "inference_worker")
    monkeypatch.setenv("NUTONIC_PRO_OPTIONAL_ORIGINS", "")
    import nutonic_server.main as main
    import nutonic_server.pro_jobs_runner as pro_jobs_runner

    importlib.reload(main)

    class FakeIC:
        def __init__(self, *, config=None, client=None) -> None:
            pass

        def probe_health_origin(self, origin: str) -> bool:
            return False

        def post_json(self, *a, **k):
            raise AssertionError("should not POST when required probe fails")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def close(self) -> None:
            pass

    monkeypatch.setattr(pro_jobs_runner, "InferenceClient", FakeIC)

    c = TestClient(main.app)
    tok = c.post("/api/v1/auth/token").json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    j = c.post("/api/v1/pro/jobs", headers=h, json={"center_lat": 1.0, "center_lon": 2.0})
    assert j.status_code == 200
    assert j.json().get("inference_upstream_ok") is None
    failed = None
    for _ in range(50):
        s = c.get(f"/api/v1/pro/jobs/{j.json()['job_id']}", headers=h)
        assert s.status_code == 200
        failed = s.json()
        if failed["status"] == "failed":
            break
        time.sleep(0.02)
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error_class"] == "worker_unreachable"
