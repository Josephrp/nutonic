"""Optional inbound HMAC gate (IMP-092 follow-up)."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _restore_streetview_app(monkeypatch: pytest.MonkeyPatch):
    import streetview_pano_service.inference_hmac as h

    h._NONCE_CACHE.clear()
    yield
    monkeypatch.delenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", raising=False)
    monkeypatch.delenv("NUTONIC_INFERENCE_HMAC_SECRET", raising=False)
    monkeypatch.delenv("INFERENCE_HMAC_SECRET", raising=False)
    import streetview_pano_service.main as m

    importlib.reload(m)


def _sign_get(secret: str, path: str, nonce: str = "a1b2c3d4e5f67890") -> dict[str, str]:
    ts = str(int(time.time()))
    canonical = f"{ts}\n{nonce}\nGET\n{path}\n"
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Nutonic-Timestamp": ts,
        "X-Nutonic-Nonce": nonce,
        "X-Nutonic-Signature": sig,
    }


def test_health_rejects_unsigned_when_hmac_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", "unit-test-secret")
    import streetview_pano_service.main as m

    importlib.reload(m)
    c = TestClient(m.app)
    r = c.get("/health")
    assert r.status_code == 401
    assert "detail" in r.json()


def test_health_accepts_valid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "unit-test-secret"
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", secret)
    import streetview_pano_service.main as m

    importlib.reload(m)
    c = TestClient(m.app)
    hdr = _sign_get(secret, "/health")
    r = c.get("/health", headers=hdr)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_rejects_replayed_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "unit-test-secret"
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", secret)
    import streetview_pano_service.main as m

    importlib.reload(m)
    c = TestClient(m.app)
    hdr = _sign_get(secret, "/health", nonce="replaynonce0001")
    assert c.get("/health", headers=hdr).status_code == 200
    replay = c.get("/health", headers=hdr)
    assert replay.status_code == 401
    assert replay.json()["detail"] == "replayed X-Nutonic-Nonce"


def test_startup_fails_when_require_hmac_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.delenv("NUTONIC_INFERENCE_HMAC_SECRET", raising=False)
    monkeypatch.delenv("INFERENCE_HMAC_SECRET", raising=False)
    import streetview_pano_service.main as m

    importlib.reload(m)
    with pytest.raises(RuntimeError, match="HMAC_SECRET"):
        with TestClient(m.app):
            pass
