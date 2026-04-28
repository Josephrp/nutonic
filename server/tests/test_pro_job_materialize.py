"""IMP-114: PRO job create calls materialization worker when URL is configured."""

from __future__ import annotations

import time
from threading import Event

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
    monkeypatch.setenv("NUTONIC_PRO_ARTIFACT_ROOT", str(tmp_path / "pro_artifacts"))
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


def _session_id(c: TestClient, headers: dict[str, str]) -> str:
    r = c.get("/api/v1/debug/session", headers=headers)
    assert r.status_code == 200
    return str(r.json()["session_id"])


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
                        "inline_base64": "aGVsbG8=",
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
    assert posts[0][1]["sentinel_fetch_mode"] == "TERRAMIND_SPECTRAL"
    assert posts[0][1]["enable_tim"] is True
    assert posts[0][1]["tim_branch"] == "S2L2A_full"
    assert posts[0][1]["analysis_profile"] == "wildfire"
    assert sj["materialization_id"] == "mid-test"
    assert sj["cache_key"] == "ck-test"
    assert sj["progress_pct"] == 100
    assert sj["analysis_profile"] == "wildfire"
    assert sj["materialization_summary"]["vlm_artifacts"][0]["role"] == "mapbox_rgb"
    assert "inline_base64" not in sj["materialization_summary"]["vlm_artifacts"][0]
    assert sj["artifacts"][0]["artifact_id"] == "mapbox_rgb"
    assert sj["artifacts"][0]["contract_id"] == "pro.vlm_image.mapbox_rgb.v1"
    assert sj["artifacts"][0]["role"] == "mapbox_rgb"
    assert sj["artifacts"][0]["category"] == "vlm_image"
    assert sj["artifacts"][0]["required_for_profile"] is True
    assert sj["artifacts"][0]["size_bytes"] == 5

    artifact = pro_client.get(
        f"/api/v1/pro/jobs/{job_id}/artifacts/mapbox_rgb",
        headers=headers,
    )
    assert artifact.status_code == 200
    assert artifact.content == b"hello"


def test_pro_vlm_model_manifest_uses_configured_contract_ids(
    pro_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NUTONIC_PRO_VLM_MODEL_BUNDLE_ID", "nutonic.pro.vlm.test")
    monkeypatch.setenv("NUTONIC_PRO_VLM_MODEL_REVISION", "2026-04-26")
    monkeypatch.setenv("NUTONIC_PRO_VLM_MODEL_DOWNLOAD_URL", "https://cdn.example.test/pro-vlm.bin")
    monkeypatch.setenv("NUTONIC_PRO_VLM_MODEL_SHA256", "A" * 64)
    monkeypatch.setenv("NUTONIC_PRO_VLM_MODEL_SIZE_BYTES", "42")
    monkeypatch.setenv("NUTONIC_PRO_VLM_MODEL_RUNTIME", "leap")
    monkeypatch.setenv("NUTONIC_PRO_VLM_MODEL_CONTRACT_IDS", "nutonic.pro.vlm.v1_512, nutonic.pro.vlm.v1_512_fc_scl")

    headers = _auth_header(pro_client)
    r = pro_client.get("/api/v1/pro/vlm/model-manifest", headers=headers)

    assert r.status_code == 200
    body = r.json()
    assert body["model_bundle_id"] == "nutonic.pro.vlm.test"
    assert body["sha256"] == "a" * 64
    assert body["contract_ids"] == ["nutonic.pro.vlm.v1_512", "nutonic.pro.vlm.v1_512_fc_scl"]


def test_pro_job_calls_brief_stage_when_lfm_url_configured(
    pro_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NUTONIC_LFM_VL_HINT_SERVICE_URL", "http://lfm.worker.test")
    posts: list[tuple[str, dict | None]] = []

    class FakeIC:
        def __init__(self, *, config=None, client=None) -> None:
            pass

        def probe_health_origin(self, origin: str) -> bool:
            return "pro.worker.test" in origin or "lfm.worker.test" in origin

        def post_json(self, url: str, *, json_body=None, read_timeout_s=None, extra_headers=None):
            posts.append((url, json_body))
            if url.endswith("/internal/v1/materialize"):
                return {
                    "materialization_id": "mid-brief",
                    "cache_key": "ck-brief",
                    "vlm_artifacts": [],
                    "tim_payload": {"branch": "S2L2A_full", "modalities_keys": ["LULC"], "npz_base64": "abc"},
                    "run_manifest": {"mapbox_center_mode": "user_pin"},
                }
            if url.endswith("/v1/pro/brief/fuse"):
                assert json_body["profile"] == "wildfire"
                assert json_body["tim_summary"]["branch"] == "S2L2A_full"
                return {
                    "executive_summary": "Brief summary",
                    "key_findings": ["Finding"],
                    "confidence": "medium",
                    "recommended_actions": ["Review source artifacts"],
                    "sections": [{"title": "Summary", "body": "Brief summary", "confidence": "medium"}],
                    "warnings": [],
                    "limitations": ["demo"],
                }
            raise AssertionError(f"unexpected URL {url}")

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
        json={
            "center_lat": 48.86,
            "center_lon": 2.35,
            "analysis_profile": "wildfire",
            "enable_tim": True,
            "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
            "tim_branch": "S2L2A_full",
        },
    )
    assert r.status_code == 200
    completed = _wait_for_status(pro_client, r.json()["job_id"], headers, "completed")
    assert [url for url, _ in posts] == [
        "http://pro.worker.test/internal/v1/materialize",
        "http://lfm.worker.test/v1/pro/brief/fuse",
    ]
    assert completed["materialization_summary"]["brief_summary"]["executive_summary"] == "Brief summary"
    assert completed["brief_artifacts"][0]["artifact_id"] == "brief_summary"
    assert completed["brief_artifacts"][0]["contract_id"] == "pro.brief.summary.v1"
    assert completed["brief_artifacts"][0]["category"] == "brief"
    assert completed["on_device_payload"]["confidence_summary"] == "medium"
    assert completed["on_device_payload"]["brief_sections"][0]["title"] == "Executive summary"
    assert completed["on_device_payload"]["brief_sections"][0]["body"] == "Brief summary"

    brief = pro_client.get(
        f"/api/v1/pro/jobs/{r.json()['job_id']}/artifacts/brief_summary",
        headers=headers,
    )
    assert brief.status_code == 200
    assert b"Brief summary" in brief.content


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


def test_pro_job_allows_optional_origin_probe_failure(
    pro_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NUTONIC_INFERENCE_WORKER_BASE_URL", "http://optional.worker.test")
    monkeypatch.setenv("NUTONIC_PRO_REQUIRED_ORIGINS", "pro_materialization")
    monkeypatch.setenv("NUTONIC_PRO_OPTIONAL_ORIGINS", "inference_worker")
    probes: list[str] = []

    class FakeIC:
        def __init__(self, *, config=None, client=None) -> None:
            pass

        def probe_health_origin(self, origin: str) -> bool:
            probes.append(origin)
            return "pro.worker.test" in origin

        def post_json(self, url: str, *, json_body=None, read_timeout_s=None, extra_headers=None):
            return {
                "materialization_id": "mid-optional-origin",
                "cache_key": "ck-optional-origin",
                "vlm_artifacts": [],
                "tim_payload": None,
                "run_manifest": {"mapbox_center_mode": "user_pin"},
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
        json={"center_lat": 1.0, "center_lon": 1.0},
    )
    assert r.status_code == 200
    completed = _wait_for_status(pro_client, r.json()["job_id"], headers, "completed")
    assert completed["materialization_id"] == "mid-optional-origin"
    assert probes == ["http://optional.worker.test", "http://pro.worker.test"]


def test_pro_job_sweeper_recovers_preexisting_queued_job(
    pro_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[str] = []

    class FakeIC:
        def __init__(self, *, config=None, client=None) -> None:
            pass

        def probe_health_origin(self, origin: str) -> bool:
            return "pro.worker.test" in origin

        def post_json(self, url: str, *, json_body=None, read_timeout_s=None, extra_headers=None):
            posts.append(url)
            return {
                "materialization_id": "mid-recovered",
                "cache_key": "ck-recovered",
                "vlm_artifacts": [],
                "tim_payload": None,
                "run_manifest": {"mapbox_center_mode": "user_pin"},
            }

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def close(self) -> None:
            pass

    monkeypatch.setattr(pro_jobs_runner, "InferenceClient", FakeIC)
    settings = deps.get_settings()
    store = deps.get_pro_job_store_for_settings(settings)
    runner = deps.get_pro_job_runner_for_settings(settings, store)
    record = store.create_job(
        session_id="session-recovery-test",
        analysis_profile="brief_only",
        request_params={"center_lat": 12.0, "center_lon": 13.0},
    )

    assert runner.sweep_once() == 1
    last = None
    for _ in range(50):
        last = store.get_job(record.job_id)
        if last is not None and last.status == "completed":
            break
        time.sleep(0.02)

    runner.shutdown(grace_seconds=1.0)
    assert last is not None
    assert last.status == "completed"
    assert last.materialization_id == "mid-recovered"
    assert posts == ["http://pro.worker.test/internal/v1/materialize"]


def test_pro_job_status_poll_does_not_mutate_queued_job(pro_client: TestClient) -> None:
    headers = _auth_header(pro_client)
    settings = deps.get_settings()
    store = deps.get_pro_job_store_for_settings(settings)
    record = store.create_job(
        session_id=_session_id(pro_client, headers),
        analysis_profile="brief_only",
        request_params={"center_lat": 12.0, "center_lon": 13.0},
    )

    first = pro_client.get(f"/api/v1/pro/jobs/{record.job_id}", headers=headers)
    second = pro_client.get(f"/api/v1/pro/jobs/{record.job_id}", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "queued"
    assert store.get_job(record.job_id).status == "queued"


def test_pro_job_cancel_queued_job(pro_client: TestClient) -> None:
    headers = _auth_header(pro_client)
    settings = deps.get_settings()
    store = deps.get_pro_job_store_for_settings(settings)
    record = store.create_job(
        session_id=_session_id(pro_client, headers),
        analysis_profile="brief_only",
        request_params={"center_lat": 12.0, "center_lon": 13.0},
    )

    cancelled = pro_client.post(f"/api/v1/pro/jobs/{record.job_id}/cancel", headers=headers)
    status = pro_client.get(f"/api/v1/pro/jobs/{record.job_id}", headers=headers)

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert status.status_code == 200
    assert status.json()["status"] == "cancelled"
    assert status.json()["error_class"] == "cancelled"


def test_pro_job_cancel_running_job_after_worker_call_returns(
    pro_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_started = Event()
    release_post = Event()

    class FakeIC:
        def __init__(self, *, config=None, client=None) -> None:
            pass

        def probe_health_origin(self, origin: str) -> bool:
            return "pro.worker.test" in origin

        def post_json(self, url: str, *, json_body=None, read_timeout_s=None, extra_headers=None):
            post_started.set()
            assert release_post.wait(timeout=2.0), "test did not release blocked worker call"
            return {
                "materialization_id": "mid-cancelled",
                "cache_key": "ck-cancelled",
                "vlm_artifacts": [],
                "tim_payload": None,
                "run_manifest": {"mapbox_center_mode": "user_pin"},
            }

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def close(self) -> None:
            pass

    monkeypatch.setattr(pro_jobs_runner, "InferenceClient", FakeIC)

    headers = _auth_header(pro_client)
    created = pro_client.post(
        "/api/v1/pro/jobs",
        headers=headers,
        json={"center_lat": 1.0, "center_lon": 1.0},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    assert post_started.wait(timeout=2.0)

    cancelling = pro_client.post(f"/api/v1/pro/jobs/{job_id}/cancel", headers=headers)
    assert cancelling.status_code == 200
    assert cancelling.json()["status"] == "cancelling"
    release_post.set()

    final = _wait_for_status(pro_client, job_id, headers, "cancelled")
    assert final["status"] == "cancelled"
    assert final["materialization_id"] is None
