"""
Lock the outbound HMAC contract for the PRO Gradio demo.

The demo MUST sign requests with the same canonical form as
`tools/nutonic_hmac.py` and `server/.../inference_client.py`, so that workers
configured with `NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC=1` accept them when the
same `NUTONIC_INFERENCE_HMAC_SECRET` is shared at deploy time.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from nutonic_pro_gradio_demo.client import NutonicServerClient
from nutonic_pro_gradio_demo.models import ProJobCreateIn
from nutonic_pro_gradio_demo.settings import Settings


SECRET = "shared-test-secret-do-not-use-in-prod"
ORIGIN = "https://example.test"


def _settings(*, secret: str = "") -> Settings:
    return Settings(
        nutonic_server_origin=ORIGIN,
        require_server_origin=False,
        inference_hmac_secret=secret,
    )


def _make_client(*, settings: Settings, transport: httpx.MockTransport) -> NutonicServerClient:
    client = NutonicServerClient(settings)
    client._client.close()
    client._client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(10.0),
        follow_redirects=True,
        headers={"User-Agent": "test"},
    )
    return client


def _expected_signature(*, ts: str, nonce: str, method: str, path: str, body: bytes, secret: str) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{ts}\n{nonce}\n{method.upper()}\n{path}\n{body_hash}\n"
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def test_get_is_signed_when_secret_set() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        if request.url.path == "/api/v1/auth/token":
            return httpx.Response(200, json={"access_token": "test-token", "token_type": "bearer", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "model_bundle_id": "NuTonic/lspace",
                "revision": "abc",
                "download_url": "https://huggingface.co/NuTonic/lspace/resolve/abc/model.safetensors",
                "size_bytes": 1,
                "sha256": "0" * 64,
                "runtime": "transformers",
            },
        )

    settings = _settings(secret=SECRET)
    client = _make_client(settings=settings, transport=httpx.MockTransport(handler))
    client.get_vlm_model_manifest()
    client.close()

    req = captured["req"]
    assert req.headers.get("X-Nutonic-Timestamp")
    assert req.headers.get("X-Nutonic-Nonce")
    assert req.headers.get("X-Nutonic-Content-SHA256") == hashlib.sha256(b"").hexdigest()

    expected = _expected_signature(
        ts=req.headers["X-Nutonic-Timestamp"],
        nonce=req.headers["X-Nutonic-Nonce"],
        method="GET",
        path="/api/v1/pro/vlm/model-manifest",
        body=b"",
        secret=SECRET,
    )
    assert req.headers["X-Nutonic-Signature"] == expected


def test_post_signs_exact_body_bytes_when_secret_set() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        captured["body"] = request.content
        if request.url.path == "/api/v1/auth/token":
            return httpx.Response(200, json={"access_token": "test-token", "token_type": "bearer", "expires_in": 3600})
        return httpx.Response(200, json={"job_id": "job-1"})

    settings = _settings(secret=SECRET)
    client = _make_client(settings=settings, transport=httpx.MockTransport(handler))
    body = ProJobCreateIn(
        center_lat=47.6062,
        center_lon=-122.3321,
        bbox_half_km=5.0,
        mapbox_zoom=12,
        analysis_profile="brief_only",
    )
    client.post_pro_job(body)
    client.close()

    req: httpx.Request = captured["req"]  # type: ignore[assignment]
    sent_bytes: bytes = captured["body"]  # type: ignore[assignment]

    expected_bytes = json.dumps(body.model_dump(mode="json"), separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert sent_bytes == expected_bytes, "POST must sign and send the exact same canonical bytes"

    assert req.headers.get("Content-Type") == "application/json"
    assert req.headers.get("X-Nutonic-Content-SHA256") == hashlib.sha256(expected_bytes).hexdigest()

    expected_sig = _expected_signature(
        ts=req.headers["X-Nutonic-Timestamp"],
        nonce=req.headers["X-Nutonic-Nonce"],
        method="POST",
        path="/api/v1/pro/jobs",
        body=expected_bytes,
        secret=SECRET,
    )
    assert req.headers["X-Nutonic-Signature"] == expected_sig


def test_no_signing_headers_when_secret_unset() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["req"] = request
        if request.url.path == "/api/v1/auth/token":
            return httpx.Response(200, json={"access_token": "test-token", "token_type": "bearer", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "model_bundle_id": "x",
                "revision": "y",
                "download_url": "https://example.test/m",
                "size_bytes": 1,
                "sha256": "0" * 64,
                "runtime": "transformers",
            },
        )

    settings = _settings(secret="")
    client = _make_client(settings=settings, transport=httpx.MockTransport(handler))
    client.get_vlm_model_manifest()
    client.close()

    req = captured["req"]
    assert "X-Nutonic-Signature" not in req.headers
    assert "X-Nutonic-Timestamp" not in req.headers
    assert "X-Nutonic-Nonce" not in req.headers


@pytest.mark.parametrize(
    "env_name",
    ["NUTONIC_INFERENCE_HMAC_SECRET", "INFERENCE_HMAC_SECRET"],
)
def test_secret_loads_from_canonical_env_aliases(monkeypatch: pytest.MonkeyPatch, env_name: str) -> None:
    """Match the env var fallbacks documented in `tools/nutonic_hmac.py`."""
    monkeypatch.delenv("NUTONIC_INFERENCE_HMAC_SECRET", raising=False)
    monkeypatch.delenv("INFERENCE_HMAC_SECRET", raising=False)
    monkeypatch.setenv(env_name, "from-env-" + env_name)
    s = Settings()
    assert s.inference_hmac_secret == "from-env-" + env_name
