from __future__ import annotations

import base64
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pro_materialization_service.main import app


def _tiny_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (128, 128), color=(12, 34, 56)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def fake_mapbox_png(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "test-token-not-for-production")

    def _fake_fetch(client, **kwargs):  # noqa: ANN001, ARG001
        return (_tiny_png(), "© Test attribution")

    monkeypatch.setattr(
        "pro_materialization_service.geospatial.pipeline.fetch_mapbox_static_png",
        _fake_fetch,
    )


def test_health_and_internal_healthz() -> None:
    client = TestClient(app)
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["service"] == "pro_materialization_service"

    z = client.get("/internal/v1/healthz")
    assert z.status_code == 200
    body = z.json()
    assert body["ok"] is True
    assert "version" in body
    assert body.get("s2_asset_mapping_version")


def test_materialize_stub(fake_mapbox_png) -> None:
    client = TestClient(app)
    r = client.post(
        "/api/v1/materialize/stub",
        json={"latitude": 48.8566, "longitude": 2.3522},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["vlm_roles"] == ["mapbox_rgb"]


def test_internal_materialize_with_tim_npz(fake_mapbox_png) -> None:
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 40.7128,
            "longitude": -74.006,
            "enable_tim": True,
            "tim_branch": "RGB_mapbox",
            "mapbox_size": 256,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["vlm_artifacts"][0]["width"] == 512
    assert data["tim_payload"]["modalities_keys"] == ["RGB"]
    raw = base64.standard_b64decode(data["tim_payload"]["npz_base64"])
    z = np.load(io.BytesIO(raw))
    assert z["RGB"].shape == (1, 3, 224, 224)


def test_minimal_rgb_tim_wrong_branch(fake_mapbox_png) -> None:
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "enable_tim": True,
            "tim_branch": "S2L2A_full",
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "TIM_BRANCH_REQUIRES_RGB_MAPBOX"


def test_profile_requires_tim_and_sentinel_stack(fake_mapbox_png) -> None:
    client = TestClient(app)
    no_tim = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "analysis_profile": "wildfire",
        },
    )
    assert no_tim.status_code == 422
    assert no_tim.json()["detail"]["code"] == "PROFILE_REQUIRES_TIM"

    minimal_rgb = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "analysis_profile": "wildfire",
            "enable_tim": True,
        },
    )
    assert minimal_rgb.status_code == 422
    assert minimal_rgb.json()["detail"]["code"] == "PROFILE_REQUIRES_SENTINEL_STACK"


def test_terramind_spectral_requires_s2_tim_when_rgb_tim(fake_mapbox_png) -> None:
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
            "enable_tim": True,
            "tim_branch": "RGB_mapbox",
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "TIM_BRANCH_REQUIRES_S2L2A_FULL"


def test_terramind_spectral_s2_npz_mocked(fake_mapbox_png, monkeypatch: pytest.MonkeyPatch) -> None:
    stack = np.zeros((12, 224, 224), dtype=np.float32) + 100.0
    meta = {"stac_item_id": "S2A_TEST", "stac_datetime": "2024-01-01T00:00:00Z", "eo_cloud_cover": 1.0}

    def _fake_load(**kwargs):  # noqa: ANN003
        return stack, meta, None

    monkeypatch.setattr(
        "pro_materialization_service.geospatial.pipeline.load_s2l2a_patch_np",
        _fake_load,
    )
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 48.8566,
            "longitude": 2.3522,
            "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
            "enable_tim": True,
            "tim_branch": "S2L2A_full",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["run_manifest"]["stac"]["item_id"] == "S2A_TEST"
    assert data["tim_payload"]["modalities_keys"] == ["S2L2A"]
    raw = base64.standard_b64decode(data["tim_payload"]["npz_base64"])
    z = np.load(io.BytesIO(raw))
    assert z["S2L2A"].shape == (1, 12, 224, 224)


def test_s2_dependencies_missing_returns_503(fake_mapbox_png, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**kwargs):  # noqa: ANN003
        raise ImportError("no rasterio")

    monkeypatch.setattr(
        "pro_materialization_service.geospatial.pipeline.load_s2l2a_patch_np",
        _boom,
    )
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "sentinel_fetch_mode": "FULL_STAC",
        },
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "S2_DEPENDENCIES_MISSING"


def test_missing_mapbox_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAPBOX_ACCESS_TOKEN", raising=False)
    client = TestClient(app)
    r = client.post("/internal/v1/materialize", json={"latitude": 1.0, "longitude": 1.0})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "MAPBOX_TOKEN_MISSING"


def test_unknown_vlm_contract(fake_mapbox_png) -> None:
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={"latitude": 1.0, "longitude": 1.0, "vlm_contract_id": "unknown.contract"},
    )
    assert r.status_code == 422


def test_vlm_fc_scl_contract_requires_spectral_mode(fake_mapbox_png) -> None:
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "vlm_contract_id": "nutonic.pro.vlm.v1_512_fc_scl",
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "VLM_CONTRACT_REQUIRES_SENTINEL_STACK"


def test_terramind_spectral_fc_scl_contract_three_artifacts(fake_mapbox_png, monkeypatch: pytest.MonkeyPatch) -> None:
    stack = np.zeros((12, 224, 224), dtype=np.float32) + 100.0
    stack[7] += 2000.0
    stack[11] += 1500.0
    meta = {
        "stac_item_id": "S2A_TEST",
        "stac_datetime": "2024-01-01T00:00:00Z",
        "eo_cloud_cover": 1.0,
        "band_asset_keys": [],
        "scl_asset_key": "scl",
    }
    scl = np.zeros((224, 224), dtype=np.float32)
    scl[60:100, 60:100] = 9.0

    def _fake_load(**kwargs):  # noqa: ANN003
        assert kwargs.get("include_scl") is True
        return stack, meta, scl

    monkeypatch.setattr(
        "pro_materialization_service.geospatial.pipeline.load_s2l2a_patch_np",
        _fake_load,
    )
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 48.8566,
            "longitude": 2.3522,
            "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
            "vlm_contract_id": "nutonic.pro.vlm.v1_512_fc_scl",
        },
    )
    assert r.status_code == 200
    data = r.json()
    roles = [a["role"] for a in data["vlm_artifacts"]]
    assert roles == ["mapbox_rgb", "sentinel_fc", "cloud_mask_thumb"]
    assert data["run_manifest"]["vlm_roles"] == roles
    assert data["run_manifest"].get("vlm_false_color", {}).get("stretch") == "per_band_percentile_2_98"
    assert data["run_manifest"].get("vlm_cloud_mask", {}).get("scl_asset_key") == "scl"
