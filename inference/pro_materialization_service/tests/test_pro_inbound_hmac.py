"""Inbound HMAC gate mirrors ``streetview_pano_service`` (IMP-092)."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _restore_pro_app(monkeypatch: pytest.MonkeyPatch):
    import pro_materialization_service.inference_hmac as h

    h._NONCE_CACHE.clear()
    yield
    monkeypatch.delenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", raising=False)
    monkeypatch.delenv("NUTONIC_INFERENCE_HMAC_SECRET", raising=False)
    import pro_materialization_service.main as m

    importlib.reload(m)


def test_pro_health_401_when_hmac_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", "p")
    import pro_materialization_service.main as m

    importlib.reload(m)
    r = TestClient(m.app).get("/health")
    assert r.status_code == 401


def test_pro_health_200_with_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "p"
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", secret)
    import pro_materialization_service.main as m

    importlib.reload(m)
    r = TestClient(m.app).get(
        "/health",
        headers=_sign(secret, "/health", "0123456789abcdef"),
    )
    assert r.status_code == 200


def test_pro_health_rejects_replayed_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "p"
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", secret)
    import pro_materialization_service.main as m

    importlib.reload(m)
    headers = _sign(secret, "/health", "replaynonce0001")
    c = TestClient(m.app)
    assert c.get("/health", headers=headers).status_code == 200
    replay = c.get("/health", headers=headers)
    assert replay.status_code == 401
    assert replay.json()["detail"] == "replayed X-Nutonic-Nonce"


def _sign(secret: str, path: str, nonce: str) -> dict[str, str]:
    ts = str(int(time.time()))
    canonical = f"{ts}\n{nonce}\nGET\n{path}\n"
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"X-Nutonic-Timestamp": ts, "X-Nutonic-Nonce": nonce, "X-Nutonic-Signature": sig}
