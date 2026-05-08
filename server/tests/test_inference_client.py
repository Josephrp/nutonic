"""IMP-092: InferenceClient timeouts + optional HMAC signing on outbound GETs."""

from __future__ import annotations

import hashlib
import hmac
import httpx

from nutonic_server.inference_client import InferenceClient, InferenceClientConfig


def _parse_sig_headers(request: httpx.Request) -> tuple[str, str, str]:
    ts = request.headers.get("x-nutonic-timestamp", "")
    nonce = request.headers.get("x-nutonic-nonce", "")
    sig = request.headers.get("x-nutonic-signature", "")
    return ts, nonce, sig


def _body_hash(request: httpx.Request) -> str:
    return request.headers.get("x-nutonic-content-sha256", "")


def test_inference_client_probe_without_hmac_uses_plain_get() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Nutonic-Signature") is None
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as raw:
        with InferenceClient(client=raw) as ic:
            assert ic.probe_health_origin("http://example.test:9999") is True


def test_inference_client_probe_rejects_degraded_health_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "degraded"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as raw:
        with InferenceClient(client=raw) as ic:
            assert ic.probe_health_origin("http://example.test:9999") is False


def test_inference_client_probe_rejects_invalid_health_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as raw:
        with InferenceClient(client=raw) as ic:
            assert ic.probe_health_origin("http://example.test:9999") is False


def test_inference_client_get_json_adds_hmac_when_secret_set() -> None:
    secret = "unit-test-secret"
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as raw:
        cfg = InferenceClientConfig(hmac_secret=secret)
        with InferenceClient(config=cfg, client=raw) as ic:
            ic.get_json("http://worker.test/api/v1/health")

    req = captured["req"]
    ts, nonce, sig = _parse_sig_headers(req)
    assert ts.isdigit()
    assert len(nonce) == 16
    path = "/api/v1/health"
    body_hash = hashlib.sha256(b"").hexdigest()
    assert _body_hash(req) == body_hash
    canonical = f"{ts}\n{nonce}\nGET\n{path}\n{body_hash}\n"
    expect = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    assert sig == expect


def test_inference_client_post_json_hmac_uses_post_and_path() -> None:
    secret = "unit-test-secret"
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as raw:
        cfg = InferenceClientConfig(hmac_secret=secret)
        with InferenceClient(config=cfg, client=raw) as ic:
            ic.post_json("http://worker.test/internal/v1/materialize", json_body={"latitude": 1.0})

    req = captured["req"]
    assert req.method == "POST"
    ts, nonce, sig = _parse_sig_headers(req)
    path = "/internal/v1/materialize"
    assert req.headers["content-type"] == "application/json"
    body_hash = hashlib.sha256(req.content).hexdigest()
    assert _body_hash(req) == body_hash
    canonical = f"{ts}\n{nonce}\nPOST\n{path}\n{body_hash}\n"
    expect = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    assert sig == expect
