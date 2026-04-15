"""HTTP client for ``inference/*`` workers (IMP-092) — timeouts + optional HMAC outbound signing."""

from __future__ import annotations

import hashlib
import hmac
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

    def _sign_headers(self, method: str, url: str) -> dict[str, str]:
        sec = (self._config.hmac_secret or "").strip()
        if not sec:
            return {}
        parsed = urlparse(url)
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        ts = str(int(time.time()))
        nonce = secrets.token_hex(8)
        canonical = f"{ts}\n{nonce}\n{method.upper()}\n{path}\n"
        sig = hmac.new(sec.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "X-Nutonic-Timestamp": ts,
            "X-Nutonic-Nonce": nonce,
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
        headers: dict[str, str] = dict(self._sign_headers("POST", url))
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
        r = self._client.post(url, json=json_body, headers=headers or None, **timeout_kw)
        r.raise_for_status()
        return r.json()

    def probe_health_origin(self, origin: str) -> bool:
        """GET ``{origin}/health`` — ``True`` on 2xx JSON, ``False`` on any failure (IMP-092)."""
        base = origin.strip().rstrip("/")
        if not base:
            return False
        try:
            self.get_json(f"{base}/health")
        except Exception:
            return False
        return True

    def __enter__(self) -> InferenceClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
