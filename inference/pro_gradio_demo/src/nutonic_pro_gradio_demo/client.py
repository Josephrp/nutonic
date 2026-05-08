from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from nutonic_pro_gradio_demo.hmac_signing import nutonic_hmac_headers
from nutonic_pro_gradio_demo.models import ProJobCreateIn, ProJobCreateOut, ProJobStatusOut, ProVlmModelManifest, TokenResponse
from nutonic_pro_gradio_demo.settings import Settings


def _is_absolute_url(url: str) -> bool:
    try:
        return bool(urlparse(url).scheme)
    except Exception:
        return False


def _resolve_url(*, origin: str, url_or_path: str) -> str:
    if _is_absolute_url(url_or_path):
        return url_or_path
    if not origin:
        raise ValueError("NUTONIC_SERVER_ORIGIN is required to resolve relative URLs")
    return urljoin(origin.rstrip("/") + "/", url_or_path.lstrip("/"))


@dataclass(frozen=True)
class PollProgress:
    job_id: str
    status: str
    progress_pct: int | None
    status_reason: str | None


class NutonicServerClient:
    def __init__(self, settings: Settings) -> None:
        origin = settings.nutonic_server_origin.strip()
        if origin:
            origin = origin.rstrip("/")
        self._origin = origin
        self._hmac_secret = (settings.inference_hmac_secret or "").strip()
        self._timeout = httpx.Timeout(settings.http_timeout_seconds)
        self._client = httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "nutonic-pro-gradio-demo/0.1 (+https://huggingface.co/spaces/Tonic/nutonic-pro-demo)",
            },
        )
        self._session_token: str | None = None
        self._session_token_expires_at: float = 0.0
        self._maybe_canonicalize_origin()

    @property
    def origin(self) -> str:
        return self._origin

    @property
    def hmac_signing_enabled(self) -> bool:
        return bool(self._hmac_secret)

    def close(self) -> None:
        self._client.close()

    def _url(self, path: str) -> str:
        if not self._origin:
            raise ValueError("NUTONIC_SERVER_ORIGIN must be set")
        return self._origin + path

    def _maybe_canonicalize_origin(self) -> None:
        """
        Hugging Face sometimes serves the same Space under multiple hostnames
        (e.g. `nutonic-nutonic-game-server.hf.space` vs `NuTonic-nutonic-game-server.hf.space`)
        which can end up on different replicas/config states.

        If the origin responds with a `Link: <https://huggingface.co/spaces/ORG/SPACE>; rel="canonical"`,
        rewrite the origin to the canonical `https://ORG-SPACE.hf.space`.
        """
        if not self._origin:
            return
        try:
            r = self._client.get(self._origin + "/api/v1/health")
        except Exception:
            return
        link = r.headers.get("link") or r.headers.get("Link")
        if not link:
            return
        # Example: <https://huggingface.co/spaces/NuTonic/nutonic-game-server>;rel="canonical"
        if "huggingface.co/spaces/" not in link or "rel=\"canonical\"" not in link:
            return
        try:
            start = link.index("<") + 1
            end = link.index(">", start)
            url = link[start:end]
            # https://huggingface.co/spaces/ORG/SPACE
            parts = url.split("/")
            org = parts[-2]
            space = parts[-1]
            self._origin = f"https://{org}-{space}.hf.space"
        except Exception:
            return

    def post_pro_job(self, body: ProJobCreateIn) -> ProJobCreateOut:
        r = self._request_with_backoff(
            "POST",
            "/api/v1/pro/jobs",
            json_body=body.model_dump(mode="json"),
            require_bearer=True,
        )
        return ProJobCreateOut.model_validate(r.json())

    def get_pro_job(self, job_id: str) -> ProJobStatusOut:
        r = self._request_with_backoff("GET", f"/api/v1/pro/jobs/{job_id}", require_bearer=True)
        return ProJobStatusOut.model_validate(r.json())

    def get_artifact(self, *, job_id: str, artifact_id: str) -> bytes:
        r = self._request_with_backoff(
            "GET",
            f"/api/v1/pro/jobs/{job_id}/artifacts/{artifact_id}",
            require_bearer=True,
        )
        return r.content

    def get_bytes_by_url(self, url_or_path: str) -> bytes:
        url = _resolve_url(origin=self._origin, url_or_path=url_or_path)
        r = self._request_with_backoff("GET", url, absolute=True)
        return r.content

    def get_vlm_model_manifest(self) -> ProVlmModelManifest:
        r = self._request_with_backoff("GET", "/api/v1/pro/vlm/model-manifest", require_bearer=True)
        return ProVlmModelManifest.model_validate(r.json())

    def post_auth_token(self) -> TokenResponse:
        r = self._request_with_backoff("POST", "/api/v1/auth/token")
        return TokenResponse.model_validate(r.json())

    def _ensure_bearer(self) -> str:
        now = time.time()
        if self._session_token and now < self._session_token_expires_at:
            return self._session_token
        issued = self.post_auth_token()
        self._session_token = issued.access_token
        # Refresh a bit early to avoid edge-of-expiry 401s.
        self._session_token_expires_at = now + max(10, int(issued.expires_in) - 15)
        return self._session_token

    def _signed_headers(self, *, method: str, url: str, body: bytes) -> dict[str, str]:
        if not self._hmac_secret:
            return {}
        return nutonic_hmac_headers(method=method, url=url, secret=self._hmac_secret, body=body)

    def _request_with_backoff(
        self,
        method: str,
        path_or_url: str,
        *,
        absolute: bool = False,
        max_retries: int = 4,
        json_body: Any | None = None,
        require_bearer: bool = False,
    ) -> httpx.Response:
        """
        Hugging Face Spaces can return 429 under load. Handle 429 (and some transient 5xx)
        with a small Retry-After-aware backoff.

        When ``settings.inference_hmac_secret`` is set, every attempt is signed with the
        same canonical form used by ``tools/nutonic_hmac.py`` and the server's
        ``InferenceClient`` (timestamp + nonce per attempt, body sha256 over the exact
        bytes that go on the wire).
        """
        if json_body is not None:
            body_bytes = _json_bytes(json_body)
        else:
            body_bytes = b""

        attempt = 0
        while True:
            attempt += 1
            url = path_or_url if absolute else self._url(path_or_url)
            headers: dict[str, str] = self._signed_headers(method=method, url=url, body=body_bytes)
            if require_bearer:
                headers["Authorization"] = f"Bearer {self._ensure_bearer()}"
            request_kwargs: dict[str, Any] = {}
            if json_body is not None:
                # Send the same exact bytes we hashed; otherwise httpx may re-serialize
                # and break HMAC verification on the receiver.
                request_kwargs["content"] = body_bytes
                headers.setdefault("Content-Type", "application/json")
            r = self._client.request(method, url, headers=headers or None, **request_kwargs)
            if r.status_code not in {429, 502, 503, 504}:
                r.raise_for_status()
                return r
            if attempt > max_retries:
                r.raise_for_status()
                return r

            retry_after = r.headers.get("retry-after")
            sleep_s: float | None = None
            if retry_after:
                try:
                    sleep_s = float(retry_after)
                except Exception:
                    sleep_s = None

            if sleep_s is None:
                base = min(20.0, 0.8 * (2 ** (attempt - 1)))
                sleep_s = base + random.random() * 0.4
            time.sleep(max(0.2, sleep_s))

    def poll_until_terminal(
        self,
        *,
        job_id: str,
        poll_interval_seconds: float,
        poll_timeout_seconds: float,
        on_progress: callable | None = None,
    ) -> ProJobStatusOut:
        import time

        deadline = time.time() + poll_timeout_seconds
        last: ProJobStatusOut | None = None
        while True:
            if time.time() > deadline:
                raise TimeoutError(f"Timed out polling PRO job {job_id}")
            status = self.get_pro_job(job_id)
            last = status
            if on_progress is not None:
                try:
                    on_progress(
                        PollProgress(
                            job_id=status.job_id,
                            status=status.status,
                            progress_pct=status.progress_pct,
                            status_reason=status.status_reason,
                        )
                    )
                except Exception:
                    pass
            if status.status in {"completed", "failed", "cancelled"}:
                return status
            time.sleep(max(0.2, poll_interval_seconds))

    def probe_health_origin(self, origin: str) -> bool:
        """GET `{origin}/health` expecting `{'status':'ok'|'healthy'}`. Supports HMAC signing when configured."""
        url = _join_origin(origin, "/health")
        try:
            r = self._request_with_backoff("GET", url, absolute=True)
        except Exception:
            return False
        try:
            data = r.json()
        except Exception:
            return False
        status = str(data.get("status") or "").strip().lower()
        return status in {"ok", "healthy"}

    def post_json_to_origin(self, *, origin: str, path: str, json_body: Any) -> dict[str, Any]:
        url = _join_origin(origin, path)
        r = self._request_with_backoff("POST", url, absolute=True, json_body=json_body)
        return r.json()


def pretty_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def _json_bytes(json_body: Any) -> bytes:
    """
    Canonical JSON encoding used for HMAC signing. Keys are sorted and separators are
    compact so that the signing bytes are deterministic and match what's sent on the
    wire (mirrors `server.../inference_client._json_bytes`).
    """
    return json.dumps(json_body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _join_origin(origin: str, path: str) -> str:
    base = (origin or "").strip().rstrip("/")
    if not base:
        raise ValueError("origin is required")
    if not path.startswith("/"):
        path = "/" + path
    return base + path

