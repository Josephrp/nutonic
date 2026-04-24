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
    monkeypatch.setenv("NUTONIC_MAPBOX_ATTRIBUTION", "© Test attribution")
    monkeypatch.setenv("NUTONIC_MAPBOX_STATIC_STYLE", "mapbox/satellite-v9")

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
    assert r.status_code == 200, r.text
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
    assert data["run_manifest"]["mapbox_source"]["attribution"] == "© Test attribution"
    assert data["run_manifest"]["profile_policy"]["datetime_window_days"] == 120
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


@pytest.mark.parametrize("profile", ["wildfire", "oceanscout_ship_detection", "land_use_change", "flood_pulse"])
def test_profile_requires_tim_and_sentinel_stack(fake_mapbox_png, profile: str) -> None:
    client = TestClient(app)
    no_tim = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "analysis_profile": profile,
        },
    )
    assert no_tim.status_code == 422
    assert no_tim.json()["detail"]["code"] == "PROFILE_REQUIRES_TIM"

    minimal_rgb = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "analysis_profile": profile,
            "enable_tim": True,
        },
    )
    assert minimal_rgb.status_code == 422
    assert minimal_rgb.json()["detail"]["code"] == "PROFILE_REQUIRES_SENTINEL_STACK"


@pytest.mark.parametrize("profile", ["wildfire", "oceanscout_ship_detection", "land_use_change", "flood_pulse"])
def test_profile_requires_s2_tim_branch(fake_mapbox_png, profile: str) -> None:
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 1.0,
            "longitude": 1.0,
            "analysis_profile": profile,
            "sentinel_fetch_mode": "FULL_STAC",
            "enable_tim": True,
            "tim_branch": "RGB_mapbox",
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "PROFILE_REQUIRES_S2L2A_FULL"


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


def test_profile_materialization_records_temporal_scenes_and_profile_artifacts(
    fake_mapbox_png,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def _fake_load(**kwargs):  # noqa: ANN003
        calls.append(kwargs)
        stack = np.zeros((12, 224, 224), dtype=np.float32) + len(calls)
        meta = {
            "stac_item_id": f"S2_{len(calls)}",
            "stac_datetime": kwargs["datetime_range"].split("/")[-1],
            "eo_cloud_cover": 1.0,
            "band_asset_keys": ["coastal"] * 12,
            "scene_id_requested": kwargs.get("scene_id"),
        }
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
            "analysis_profile": "wildfire",
            "enable_tim": True,
            "tim_branch": "S2L2A_full",
            "scene_id_t0": "PINNED_T0",
            "datetime_interval": "2024-04-01/2024-04-30",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(calls) == 2
    assert calls[0]["scene_id"] == "PINNED_T0"
    assert data["run_manifest"]["temporal_slices"] == ["t0", "t1"]
    assert data["run_manifest"]["scene_provenance"]["t0"]["scene_id_requested"] == "PINNED_T0"
    roles = {artifact["role"] for artifact in data["vlm_artifacts"]}
    assert {
        "scene_provenance",
        "wildfire_aoi_overlay",
        "firewatch_burn_change_heatmap",
        "firewatch_metrics",
        "firewatch_hotspots",
        "firewatch_hotspots_geojson",
        "profile_artifact_index",
    } <= roles
    metrics = next(a for a in data["vlm_artifacts"] if a["role"] == "firewatch_metrics")
    assert metrics["mime"] == "application/json"
    heatmap = next(a for a in data["vlm_artifacts"] if a["role"] == "firewatch_burn_change_heatmap")
    assert heatmap["mime"] == "image/png"


def test_oceanscout_materialization_emits_candidate_and_coverage_artifacts(
    fake_mapbox_png,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_load(**kwargs):  # noqa: ANN003
        stack = np.zeros((12, 224, 224), dtype=np.float32)
        stack[2, 20:40, 20:40] = 0.8
        stack[7, 20:40, 20:40] = 0.1
        stack[11, 20:40, 20:40] = 0.9
        meta = {
            "stac_item_id": f"S2_{kwargs['datetime_range']}",
            "stac_datetime": kwargs["datetime_range"].split("/")[-1],
            "eo_cloud_cover": 10.0,
            "band_asset_keys": ["coastal"] * 12,
        }
        return stack, meta, None

    monkeypatch.setattr(
        "pro_materialization_service.geospatial.pipeline.load_s2l2a_patch_np",
        _fake_load,
    )
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 34.0522,
            "longitude": -118.2437,
            "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
            "analysis_profile": "oceanscout_ship_detection",
            "enable_tim": True,
            "tim_branch": "S2L2A_full",
            "datetime_interval": "2024-04-01/2024-04-30",
        },
    )

    assert r.status_code == 200, r.text
    roles = {artifact["role"] for artifact in r.json()["vlm_artifacts"]}
    assert {
        "observation_coverage",
        "vessel_candidates",
        "vessel_overlay",
        "lane_heatmap",
        "incursion_events",
    } <= roles


def test_landshift_materialization_emits_transition_artifacts(
    fake_mapbox_png,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def _fake_load(**kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        stack = np.zeros((12, 224, 224), dtype=np.float32)
        if calls == 1:
            stack[7, :, :] = 0.8
            stack[3, :, :] = 0.1
        else:
            stack[11, :, :] = 0.8
            stack[7, :, :] = 0.1
        meta = {
            "stac_item_id": f"S2_{calls}",
            "stac_datetime": kwargs["datetime_range"].split("/")[-1],
            "eo_cloud_cover": 2.0,
            "band_asset_keys": ["coastal"] * 12,
        }
        return stack, meta, None

    monkeypatch.setattr(
        "pro_materialization_service.geospatial.pipeline.load_s2l2a_patch_np",
        _fake_load,
    )
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 35.0,
            "longitude": -120.0,
            "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
            "analysis_profile": "land_use_change",
            "enable_tim": True,
            "tim_branch": "S2L2A_full",
            "datetime_interval": "2024-04-01/2024-04-30",
        },
    )

    assert r.status_code == 200, r.text
    roles = {artifact["role"] for artifact in r.json()["vlm_artifacts"]}
    assert {"land_transition_matrix", "land_top_transitions", "land_change_hotspots", "land_change_heatmap"} <= roles


def test_floodpulse_materialization_emits_water_change_artifacts(
    fake_mapbox_png,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def _fake_load(**kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        stack = np.zeros((12, 224, 224), dtype=np.float32)
        stack[2, :, :] = 0.1
        stack[7, :, :] = 0.8
        if calls == 2:
            stack[2, 20:80, 20:80] = 0.9
            stack[7, 20:80, 20:80] = 0.1
        meta = {
            "stac_item_id": f"S2_{calls}",
            "stac_datetime": kwargs["datetime_range"].split("/")[-1],
            "eo_cloud_cover": 2.0,
            "band_asset_keys": ["coastal"] * 12,
        }
        return stack, meta, None

    monkeypatch.setattr(
        "pro_materialization_service.geospatial.pipeline.load_s2l2a_patch_np",
        _fake_load,
    )
    client = TestClient(app)
    r = client.post(
        "/internal/v1/materialize",
        json={
            "latitude": 35.0,
            "longitude": -120.0,
            "sentinel_fetch_mode": "TERRAMIND_SPECTRAL",
            "analysis_profile": "flood_pulse",
            "enable_tim": True,
            "tim_branch": "S2L2A_full",
            "datetime_interval": "2024-04-01/2024-04-30",
        },
    )

    assert r.status_code == 200, r.text
    roles = {artifact["role"] for artifact in r.json()["vlm_artifacts"]}
    assert {
        "flood_water_change_metrics",
        "flood_inundation_polygons",
        "flood_before_water_extent",
        "flood_after_water_extent",
        "flood_expansion_heatmap",
    } <= roles
