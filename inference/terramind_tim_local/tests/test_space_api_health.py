from __future__ import annotations

from starlette.testclient import TestClient

from nutonic_terramind_tim_local.space_api import app


def test_space_health() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "terramind_tim_local"
