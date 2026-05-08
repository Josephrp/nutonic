from __future__ import annotations

from starlette.testclient import TestClient

from nutonic_terramind_tim_local import space_api
from nutonic_terramind_tim_local.space_api import app


def test_space_health() -> None:
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "terramind_tim_local"
    assert data["patch_diagnostics"]["diagnostics_version"] == "nutonic.terramind_patches.v1"


def test_tim_infer_alias_injects_profile(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(cfg: dict) -> dict:
        captured["cfg"] = cfg
        return {"ok": True, "analysis_profile": cfg.get("analysis_profile")}

    monkeypatch.setattr(space_api, "_run_tim_export_gpu", fake_run)
    client = TestClient(app)
    r = client.post(
        "/v1/tim/infer",
        json={
            "profile": "wildfire",
            "config": {
                "model_id": "demo",
                "inputs": {"mode": "random"},
            },
        },
    )

    assert r.status_code == 200
    assert r.json()["analysis_profile"] == "wildfire"
    assert captured["cfg"]["analysis_profile"] == "wildfire"


def test_tim_export_path_still_accepts_config(monkeypatch) -> None:
    def fake_run(cfg: dict) -> dict:
        return {"ok": True, "model_id": cfg.get("model_id")}

    monkeypatch.setattr(space_api, "_run_tim_export_gpu", fake_run)
    client = TestClient(app)
    r = client.post("/v1/tim/export", json={"config": {"model_id": "demo"}})

    assert r.status_code == 200
    assert r.json()["model_id"] == "demo"
