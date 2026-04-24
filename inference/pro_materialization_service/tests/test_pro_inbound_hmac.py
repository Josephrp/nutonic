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
    monkeypatch.delenv("NUTONIC_INFERENCE_HMAC_MAX_SKEW_SECONDS", raising=False)
    monkeypatch.delenv("NUTONIC_INFERENCE_HMAC_NONCE_CACHE_MAX", raising=False)
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


def test_pro_health_uses_configurable_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "p"
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", secret)
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_MAX_SKEW_SECONDS", "1")
    import pro_materialization_service.main as m

    importlib.reload(m)
    old_ts = str(int(time.time()) - 5)
    r = TestClient(m.app).get(
        "/health",
        headers=_sign(secret, "/health", "oldnonce0000001", ts=old_ts),
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "X-Nutonic-Timestamp outside allowed skew"


def test_pro_nonce_cache_size_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "p"
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", secret)
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_NONCE_CACHE_MAX", "1")
    import pro_materialization_service.inference_hmac as h
    import pro_materialization_service.main as m

    importlib.reload(m)
    c = TestClient(m.app)
    assert c.get("/health", headers=_sign(secret, "/health", "cachemax000001")).status_code == 200
    assert c.get("/health", headers=_sign(secret, "/health", "cachemax000002")).status_code == 200
    assert list(h._NONCE_CACHE.keys()) == ["cachemax000002"]


def test_pro_post_rejects_body_hash_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "p"
    monkeypatch.setenv("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC", "1")
    monkeypatch.setenv("NUTONIC_INFERENCE_HMAC_SECRET", secret)
    import pro_materialization_service.main as m

    importlib.reload(m)
    body = b'{"latitude":1.0,"longitude":2.0}'
    signed_other_body = b'{"latitude":9.0,"longitude":2.0}'
    r = TestClient(m.app).post(
        "/internal/v1/materialize",
        content=body,
        headers=_sign(
            secret,
            "/internal/v1/materialize",
            "bodyhash000001",
            method="POST",
            body=signed_other_body,
        ),
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid X-Nutonic-Content-SHA256"


def _sign(
    secret: str,
    path: str,
    nonce: str,
    *,
    method: str = "GET",
    body: bytes = b"",
    ts: str | None = None,
) -> dict[str, str]:
    ts = ts or str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{ts}\n{nonce}\n{method}\n{path}\n{body_hash}\n"
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Nutonic-Timestamp": ts,
        "X-Nutonic-Nonce": nonce,
        "X-Nutonic-Content-SHA256": body_hash,
        "X-Nutonic-Signature": sig,
    }
