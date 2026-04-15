"""IMP-114: PRO job create calls materialization worker when URL is configured."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nutonic_server import main


@pytest.fixture
def pro_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FEATURE_PRO_JOBS", "true")
    monkeypatch.setenv("NUTONIC_PRO_MATERIALIZATION_SERVICE_URL", "http://pro.worker.test")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", "test-hmac-secret")
    return TestClient(main.app)


def _auth_header(c: TestClient) -> dict[str, str]:
    tok = c.post("/api/v1/auth/token").json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_pro_job_calls_materialize_when_health_ok(
    pro_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[tuple[str, dict | None]] = []

    class FakeIC:
        def __init__(self, *, config=None, client=None) -> None:
            self.config = config

        def probe_health_origin(self, origin: str) -> bool:
            return "pro.worker.test" in origin

        def post_json(self, url: str, *, json_body=None, read_timeout_s=None, extra_headers=None):
            posts.append((url, json_body))
            return {
                "materialization_id": "mid-test",
                "cache_key": "ck-test",
                "vlm_artifacts": [
                    {
                        "role": "mapbox_rgb",
                        "sha256": "abc",
                        "mime": "image/png",
                        "width": 512,
                        "height": 512,
                        "inline_base64": "VERYLONG",
                    },
                ],
                "tim_payload": None,
                "run_manifest": {"mapbox_center_mode": "user_pin"},
                "errors": [],
                "warnings": [],
            }

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def close(self) -> None:
            pass

    monkeypatch.setattr(main, "InferenceClient", FakeIC)

    r = pro_client.post(
        "/api/v1/pro/jobs",
        headers=_auth_header(pro_client),
        json={"center_lat": 48.86, "center_lon": 2.35},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["inference_upstream_ok"] is True
    assert body["materialization_ok"] is True
    assert body["materialization_id"] == "mid-test"
    assert body["cache_key"] == "ck-test"
    assert len(posts) == 1
    assert posts[0][0] == "http://pro.worker.test/internal/v1/materialize"
    assert posts[0][1]["latitude"] == 48.86
    assert posts[0][1]["sentinel_fetch_mode"] == "MINIMAL_RGB"

    job_id = body["job_id"]
    st = pro_client.get(f"/api/v1/pro/jobs/{job_id}", headers=_auth_header(pro_client))
    assert st.status_code == 200
    sj = st.json()
    assert sj["materialization_id"] == "mid-test"
    assert sj["materialization_summary"]["vlm_artifacts"][0]["role"] == "mapbox_rgb"
    assert "inline_base64" not in sj["materialization_summary"]["vlm_artifacts"][0]


def test_pro_job_skips_materialize_when_probe_fails(
    pro_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeIC:
        def __init__(self, *, config=None, client=None) -> None:
            pass

        def probe_health_origin(self, origin: str) -> bool:
            return False

        def post_json(self, *a, **k):
            raise AssertionError("should not POST when health fails")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def close(self) -> None:
            pass

    monkeypatch.setattr(main, "InferenceClient", FakeIC)

    r = pro_client.post(
        "/api/v1/pro/jobs",
        headers=_auth_header(pro_client),
        json={"center_lat": 1.0, "center_lon": 1.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["inference_upstream_ok"] is False
    assert body["materialization_ok"] is False
    assert body["materialization_error"] == "inference_health_probe_failed"
