from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from nutonic_server.main import app

client = TestClient(app)


def test_health_ok() -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_config_features_shape() -> None:
    r = client.get("/api/v1/config")
    assert r.status_code == 200
    body = r.json()
    assert "features" in body
    f = body["features"]
    for k in ("ranked", "community_lb_get", "community_lb_post", "pro_jobs", "guesses_record"):
        assert k in f
        assert isinstance(f[k], bool)


@pytest.mark.skipif(
    not Path(__file__).resolve().parents[2].joinpath("docs", "openapi.yaml").is_file(),
    reason="openapi.yaml not at repo root",
)
def test_openapi_yaml_parseable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    spec_path = repo_root / "docs" / "openapi.yaml"
    text = spec_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["openapi"].startswith("3.")
    servers = data["servers"]
    assert servers, "must declare servers"
    base = servers[0]["url"].rstrip("/")
    assert not base.endswith("/api/v1"), "server URL must be origin-only (RFC 3986 join safety)"
    paths = data["paths"]
    for key in (
        "/api/v1/health",
        "/api/v1/config",
        "/api/v1/auth/token",
        "/api/v1/debug/session",
        "/api/v1/maps",
        "/api/v1/cache/manifest",
        "/api/v1/maps/{map_id}/leaderboard",
        "/api/v1/bundles/{bundle_id}",
        "/api/v1/maps/{map_id}/guesses/record",
        "/api/v1/ranked/rounds/start",
        "/api/v1/ranked/rounds/{round_id}/forfeit-ranked-integrity",
        "/api/v1/ranked/rounds/{round_id}/submit",
        "/api/v1/pro/jobs",
        "/api/v1/pro/jobs/{job_id}",
    ):
        assert key in paths, f"missing path {key}"


@pytest.mark.skipif(
    not Path(__file__).resolve().parents[2].joinpath("docs", "openapi.yaml").is_file(),
    reason="openapi.yaml not at repo root",
)
def test_openapi_operations_match_fastapi_routes() -> None:
    """Hand-maintained YAML must list the same /api/v1 methods as the ASGI app."""
    repo_root = Path(__file__).resolve().parents[2]
    data = yaml.safe_load((repo_root / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
    from_yaml: set[tuple[str, str]] = set()
    for path, path_item in data["paths"].items():
        for method, op in path_item.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            from_yaml.add((method.upper(), path))

    from_app: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api/v1"):
            continue
        for m in route.methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            from_app.add((m, route.path))

    assert from_yaml == from_app, (
        f"OpenAPI vs app mismatch.\nOnly in YAML: {sorted(from_yaml - from_app)}\n"
        f"Only in app: {sorted(from_app - from_yaml)}"
    )


def test_auth_token_and_gated_debug() -> None:
    r = client.post("/api/v1/auth/token")
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert isinstance(token, str) and len(token) > 10

    no_auth = client.get("/api/v1/debug/session")
    assert no_auth.status_code == 401

    ok = client.get(
        "/api/v1/debug/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert "session_id" in body


def test_leaderboard_demo_get_and_post(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_COMMUNITY_LB_POST", "true")
    rows = client.get("/api/v1/maps/demo/leaderboard")
    assert rows.status_code == 200
    assert isinstance(rows.json(), list)
    assert len(rows.json()) >= 1

    tok = client.post("/api/v1/auth/token").json()["access_token"]
    post = client.post(
        "/api/v1/maps/demo/leaderboard",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "display_handle": "TEST",
            "player_role": "ASTRONAUT",
            "score_points": 1234,
            "distance_km": 9.5,
        },
    )
    assert post.status_code == 200
    assert post.json()["display_handle"] == "TEST"

    denied = client.post(
        "/api/v1/maps/demo/leaderboard",
        json={"display_handle": "X", "player_role": "HUMAN", "score_points": 1},
    )
    assert denied.status_code == 401


def test_maps_list_returns_catalog() -> None:
    r = client.get("/api/v1/maps")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) >= 1
    first = data[0]
    assert "map_id" in first and "title" in first
    ids = {row["map_id"] for row in data}
    assert "demo" in ids


def test_cache_manifest_etag_and_not_modified() -> None:
    r1 = client.get("/api/v1/cache/manifest")
    assert r1.status_code == 200
    body = r1.json()
    assert body["content_version"]
    assert isinstance(body["maps"], list) and len(body["maps"]) >= 1
    etag = r1.headers.get("etag")
    assert etag and etag.startswith("W/")

    r304 = client.get("/api/v1/cache/manifest", headers={"If-None-Match": etag})
    assert r304.status_code == 304
    assert r304.headers.get("etag") == etag


def test_cache_manifest_matches_maps_list_ids() -> None:
    maps = client.get("/api/v1/maps").json()
    man = client.get("/api/v1/cache/manifest").json()
    assert {m["map_id"] for m in maps} == {m["map_id"] for m in man["maps"]}


def test_cache_manifest_includes_round_fixtures_and_ai_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH", "true")
    man = client.get("/api/v1/cache/manifest").json()
    assert man["content_version"] == "nutonic.manifest.v2"
    locs = man["locations"]
    assert isinstance(locs, list) and len(locs) >= 2
    demo_loc = next(x for x in locs if x["map_id"] == "demo")
    assert demo_loc["location_id"] == "demo-vienna-001"
    assert demo_loc["truth_lat"] == 48.2082
    assert demo_loc["still_bundled_resource"] == "files/3.jpg"
    guesses = man["ai_guesses"]
    assert isinstance(guesses, list) and len(guesses) >= 2
    g0 = next(x for x in guesses if x["map_id"] == "demo")
    assert g0["ai_lat"] == 41.9028


def test_cache_manifest_redacts_round_fixtures_by_default() -> None:
    man = client.get("/api/v1/cache/manifest").json()
    assert man.get("locations") == []
    assert man.get("ai_guesses") == []


def test_cache_manifest_if_none_match_accepts_comma_separated_list() -> None:
    r1 = client.get("/api/v1/cache/manifest")
    etag = r1.headers.get("etag")
    assert etag
    r304 = client.get(
        "/api/v1/cache/manifest",
        headers={"If-None-Match": f'W/"other", {etag}'},
    )
    assert r304.status_code == 304


def test_community_lb_get_disabled_returns_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_COMMUNITY_LB_GET", "false")
    r = client.get("/api/v1/maps/demo/leaderboard")
    assert r.status_code == 403
    assert r.json()["error"] == "feature_disabled"
    assert r.json()["feature"] == "community_lb_get"


def test_community_lb_post_disabled_returns_403_before_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_COMMUNITY_LB_POST", "false")
    r = client.post(
        "/api/v1/maps/demo/leaderboard",
        json={"display_handle": "X", "player_role": "HUMAN", "score_points": 1},
    )
    assert r.status_code == 403
    assert r.json()["feature"] == "community_lb_post"


def test_leaderboard_post_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same Idempotency-Key + map_id returns first row (rules/05 dedupe)."""
    monkeypatch.setenv("FEATURE_COMMUNITY_LB_POST", "true")
    tok = client.post("/api/v1/auth/token").json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}", "Idempotency-Key": "idem-test-1"}
    body_a = {
        "display_handle": "FIRST",
        "player_role": "HUMAN",
        "score_points": 100,
    }
    body_b = {
        "display_handle": "SECOND",
        "player_role": "ALIEN",
        "score_points": 200,
    }
    r1 = client.post("/api/v1/maps/idempotency-map/leaderboard", headers=headers, json=body_a)
    r2 = client.post("/api/v1/maps/idempotency-map/leaderboard", headers=headers, json=body_b)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["display_handle"] == "FIRST"
    assert r2.json()["display_handle"] == "FIRST"
