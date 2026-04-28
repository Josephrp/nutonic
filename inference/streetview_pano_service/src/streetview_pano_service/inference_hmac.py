"""
Inbound HMAC verification (IMP-092) — canonical string must match ``nutonic_server.inference_client``.

Enable on the worker with ``NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC=1`` and the same
``NUTONIC_INFERENCE_HMAC_SECRET`` / ``INFERENCE_HMAC_SECRET`` as the game server.
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import os
import threading
import time
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse

_NONCE_LOCK = threading.Lock()
_NONCE_CACHE: collections.OrderedDict[str, float] = collections.OrderedDict()
_DEFAULT_MAX_NONCE_CACHE = 10_000
_DEFAULT_MAX_SKEW_SECONDS = 300


def hmac_secret() -> str:
    return (
        os.environ.get("NUTONIC_INFERENCE_HMAC_SECRET") or os.environ.get("INFERENCE_HMAC_SECRET") or ""
    ).strip()


def require_inbound_hmac() -> bool:
    v = (os.environ.get("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def hmac_max_skew_seconds() -> int:
    return _env_int(
        "NUTONIC_INFERENCE_HMAC_MAX_SKEW_SECONDS",
        "INFERENCE_HMAC_MAX_SKEW_SECONDS",
        default=_DEFAULT_MAX_SKEW_SECONDS,
        minimum=1,
    )


def hmac_nonce_cache_max() -> int:
    return _env_int(
        "NUTONIC_INFERENCE_HMAC_NONCE_CACHE_MAX",
        "INFERENCE_HMAC_NONCE_CACHE_MAX",
        default=_DEFAULT_MAX_NONCE_CACHE,
        minimum=1,
    )


def verify_inbound_hmac(
    request: Request,
    *,
    body: bytes = b"",
    max_skew_s: int | None = None,
) -> str | None:
    """
    Return ``None`` if the request may proceed.

    When ``NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC`` is unset/false, always returns ``None``.
    When set, requires ``X-Nutonic-Timestamp``, ``X-Nutonic-Nonce``, ``X-Nutonic-Signature`` and a
    valid HMAC-SHA256 over ``{ts}\\n{nonce}\\n{METHOD}\\n{path}\\n{body_sha256}\\n``.
    """
    if not require_inbound_hmac():
        return None
    sec = hmac_secret()
    if not sec:
        return "NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC is enabled but HMAC secret is empty"
    skew_s = int(max_skew_s if max_skew_s is not None else hmac_max_skew_seconds())

    ts = request.headers.get("X-Nutonic-Timestamp") or request.headers.get("x-nutonic-timestamp")
    nonce = request.headers.get("X-Nutonic-Nonce") or request.headers.get("x-nutonic-nonce")
    body_hash = request.headers.get("X-Nutonic-Content-SHA256") or request.headers.get("x-nutonic-content-sha256")
    sig = request.headers.get("X-Nutonic-Signature") or request.headers.get("x-nutonic-signature")
    if not ts or not nonce or not body_hash or not sig:
        return "missing X-Nutonic-Timestamp, X-Nutonic-Nonce, X-Nutonic-Content-SHA256, or X-Nutonic-Signature"

    try:
        ts_i = int(str(ts).strip())
    except ValueError:
        return "invalid X-Nutonic-Timestamp"

    now = int(time.time())
    if abs(now - ts_i) > skew_s:
        return "X-Nutonic-Timestamp outside allowed skew"

    path = request.url.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    method = request.method.upper()
    expected_body_hash = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(expected_body_hash, str(body_hash).strip()):
        return "invalid X-Nutonic-Content-SHA256"
    canonical = f"{ts}\n{nonce}\n{method}\n{path}\n{expected_body_hash}\n"
    expected = hmac.new(sec.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(sig).strip()):
        return "invalid X-Nutonic-Signature"

    nonce_err = _check_and_record_nonce(str(nonce).strip(), float(ts_i), skew_s)
    if nonce_err is not None:
        return nonce_err

    return None


def _check_and_record_nonce(nonce: str, ts: float, max_skew_s: int) -> str | None:
    max_cache = hmac_nonce_cache_max()
    with _NONCE_LOCK:
        if nonce in _NONCE_CACHE:
            return "replayed X-Nutonic-Nonce"
        cutoff = time.time() - max_skew_s
        while _NONCE_CACHE:
            oldest_nonce, oldest_ts = next(iter(_NONCE_CACHE.items()))
            if oldest_ts < cutoff:
                _NONCE_CACHE.pop(oldest_nonce)
            else:
                break
        while len(_NONCE_CACHE) >= max_cache:
            _NONCE_CACHE.popitem(last=False)
        _NONCE_CACHE[nonce] = ts
    return None


def _env_int(*names: str, default: int, minimum: int) -> int:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            continue
        try:
            return max(minimum, int(raw.strip()))
        except ValueError:
            return default
    return default


def install_hmac_middleware(app: object) -> None:
    """Register Starlette HTTP middleware on a FastAPI ``app``."""

    @app.middleware("http")
    async def _hmac_middleware(request: Request, call_next: Callable):  # type: ignore[no-untyped-def]
        body = await request.body()
        err = verify_inbound_hmac(request, body=body)
        if err is not None:
            return JSONResponse({"detail": err}, status_code=401)
        return await call_next(request)
