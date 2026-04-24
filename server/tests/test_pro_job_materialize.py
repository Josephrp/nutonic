"""IMP-114: PRO job create calls materialization worker when URL is configured."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from nutonic_server import deps
from nutonic_server import main
from nutonic_server import pro_jobs_runner


@pytest.fixture
def pro_client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    monkeypatch.setenv("FEATURE_PRO_JOBS", "true")
    monkeypatch.setenv("NUTONIC_PRO_MATERIALIZATION_SERVICE_URL", "http://pro.worker.test")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", "test-hmac-secret")
    monkeypatch.setenv("NUTONIC_PRO_JOB_DATABASE_URL", f"sqlite:///{tmp_path / 'pro_jobs.db'}")
    deps._pro_job_stores.clear()
    deps._pro_job_runners.clear()
    return TestClient(main.app)


def _auth_header(c: TestClient) -> dict[str, str]:
    tok = c.post("/api/v1/auth/token").json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _wait_for_status(c: TestClient, job_id: str, headers: dict[str, str], expected: str) -> dict:
    last: dict = {}
    for _ in range(50):
        r = c.get(f"/api/v1/pro/jobs/{job_id}", headers=headers)
        assert r.status_code == 200
        last = r.json()
        if last["status"] == expected:
            return last
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {expected}; last={last}")


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

    monkeypatch.setattr(pro_jobs_runner, "InferenceClient", FakeIC)

    headers = _auth_header(pro_client)
    r = pro_client.post(
        "/api/v1/pro/jobs",
        headers=headers,
        json={"center_lat": 48.86, "center_lon": 2.35, "analysis_profile": "wildfire"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["inference_upstream_ok"] is None

    job_id = body["job_id"]
    sj = _wait_for_status(pro_client, job_id, headers, "completed")
    assert len(posts) == 1
    assert posts[0][0] == "http://pro.worker.test/internal/v1/materialize"
    assert posts[0][1]["latitude"] == 48.86
    assert posts[0][1]["sentinel_fetch_mode"] == "MINIMAL_RGB"
    assert posts[0][1]["analysis_profile"] == "wildfire"
    assert sj["materialization_id"] == "mid-test"
    assert sj["cache_key"] == "ck-test"
    assert sj["progress_pct"] == 100
    assert sj["analysis_profile"] == "wildfire"
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

    monkeypatch.setattr(pro_jobs_runner, "InferenceClient", FakeIC)

    headers = _auth_header(pro_client)
    r = pro_client.post(
        "/api/v1/pro/jobs",
        headers=headers,
        json={"center_lat": 1.0, "center_lon": 1.0},
    )
    assert r.status_code == 200
    body = r.json()
    failed = _wait_for_status(pro_client, body["job_id"], headers, "failed")
    assert failed["error_class"] == "worker_unreachable"
    assert "pro_materialization health probe failed" in failed["error_detail"]
