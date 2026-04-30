"""HTTP client for ``inference/*`` workers (IMP-092) — timeouts + optional HMAC outbound signing."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class InferenceClientConfig:
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 60.0
    write_timeout_s: float = 30.0
    """When set, ``GET`` requests include ``X-Nutonic-*`` signing headers (thin orchestrator §1 / §5)."""

    hmac_secret: str | None = None


class InferenceClient:
    """Thin ``httpx`` wrapper for orchestrator → worker calls."""

    def __init__(
        self,
        *,
        config: InferenceClientConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config or InferenceClientConfig()
        self._owns_client = client is None
        # httpx 0.28+ requires all four timeout fields when using keyword form.
        cto = self._config.connect_timeout_s
        timeout = httpx.Timeout(
            connect=cto,
            read=self._config.read_timeout_s,
            write=self._config.write_timeout_s,
            pool=cto,
        )
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _sign_headers(self, method: str, url: str, *, body: bytes = b"") -> dict[str, str]:
        sec = (self._config.hmac_secret or "").strip()
        if not sec:
            return {}
        parsed = urlparse(url)
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        ts = str(int(time.time()))
        nonce = secrets.token_hex(8)
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = f"{ts}\n{nonce}\n{method.upper()}\n{path}\n{body_hash}\n"
        sig = hmac.new(sec.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "X-Nutonic-Timestamp": ts,
            "X-Nutonic-Nonce": nonce,
            "X-Nutonic-Content-SHA256": body_hash,
            "X-Nutonic-Signature": sig,
        }

    def get_json(self, url: str, *, extra_headers: dict[str, str] | None = None) -> dict:
        headers: dict[str, str] = dict(self._sign_headers("GET", url))
        if extra_headers:
            headers.update(extra_headers)
        r = self._client.get(url, headers=headers or None)
        r.raise_for_status()
        return r.json()

    def post_json(
        self,
        url: str,
        *,
        json_body: dict | None = None,
        read_timeout_s: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        """POST JSON with the same HMAC signing rules as ``GET`` (path from URL, IMP-092)."""
        body = _json_bytes(json_body) if json_body is not None else b""
        headers: dict[str, str] = dict(self._sign_headers("POST", url, body=body))
        if json_body is not None:
            headers.setdefault("Content-Type", "application/json")
        if extra_headers:
            headers.update(extra_headers)
        timeout_kw: dict = {}
        if read_timeout_s is not None:
            cto = self._config.connect_timeout_s
            wto = self._config.write_timeout_s
            timeout_kw["timeout"] = httpx.Timeout(
                connect=cto,
                read=read_timeout_s,
                write=wto,
                pool=cto,
            )
        r = self._client.post(
            url,
            content=body if json_body is not None else None,
            headers=headers or None,
            **timeout_kw,
        )
        r.raise_for_status()
        return r.json()

    def post_gradio_json(
        self,
        origin: str,
        *,
        api_name: str,
        json_body: dict,
        read_timeout_s: float | None = None,
    ) -> dict:
        base = origin.strip().rstrip("/")
        submit = self.post_json(
            f"{base}/gradio_api/call/v2/{api_name}",
            json_body={"req": json_body},
            read_timeout_s=read_timeout_s,
        )
        event_id = str(submit.get("event_id") or submit.get("id") or "").strip()
        if not event_id:
            raise ValueError("gradio_missing_event_id")
        timeout_kw: dict = {}
        if read_timeout_s is not None:
            cto = self._config.connect_timeout_s
            wto = self._config.write_timeout_s
            timeout_kw["timeout"] = httpx.Timeout(connect=cto, read=read_timeout_s, write=wto, pool=cto)
        r = self._client.get(f"{base}/gradio_api/call/{api_name}/{event_id}", **timeout_kw)
        r.raise_for_status()
        return _parse_gradio_sse_json(r.text)

    def probe_health_origin(self, origin: str) -> bool:
        """GET ``{origin}/health`` and require an explicitly healthy JSON body."""
        base = origin.strip().rstrip("/")
        if not base:
            return False
        try:
            data = self.get_json(f"{base}/health")
        except Exception:
            return False
        status = str(data.get("status") or "").strip().lower()
        return status in {"ok", "healthy"}

    def probe_gradio_origin(self, origin: str) -> bool:
        """ZeroGPU Gradio Spaces expose readiness through ``/gradio_api/info`` instead of ``/health``."""
        base = origin.strip().rstrip("/")
        if not base:
            return False
        try:
            data = self.get_json(f"{base}/gradio_api/info")
        except Exception:
            return False
        return isinstance(data.get("named_endpoints"), dict) or isinstance(data.get("dependencies"), list)

    def __enter__(self) -> InferenceClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _json_bytes(json_body: dict) -> bytes:
    return json.dumps(json_body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _parse_gradio_sse_json(body: str) -> dict:
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line.split("data:", 1)[1].strip()
        if not raw:
            continue
        payload = json.loads(raw)
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                return data[0]
            return payload
    raise ValueError("gradio_missing_data")
