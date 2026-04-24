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
_MAX_NONCE_CACHE = 10_000


def hmac_secret() -> str:
    return (
        os.environ.get("NUTONIC_INFERENCE_HMAC_SECRET") or os.environ.get("INFERENCE_HMAC_SECRET") or ""
    ).strip()


def require_inbound_hmac() -> bool:
    v = (os.environ.get("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def verify_inbound_hmac(request: Request, *, max_skew_s: int = 300) -> str | None:
    """
    Return ``None`` if the request may proceed.

    When ``NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC`` is unset/false, always returns ``None``.
    When set, requires ``X-Nutonic-Timestamp``, ``X-Nutonic-Nonce``, ``X-Nutonic-Signature`` and a
    valid HMAC-SHA256 over ``{ts}\\n{nonce}\\n{METHOD}\\n{path}\\n`` (path from URL, leading ``/``).
    """
    if not require_inbound_hmac():
        return None
    sec = hmac_secret()
    if not sec:
        return "NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC is enabled but HMAC secret is empty"

    ts = request.headers.get("X-Nutonic-Timestamp") or request.headers.get("x-nutonic-timestamp")
    nonce = request.headers.get("X-Nutonic-Nonce") or request.headers.get("x-nutonic-nonce")
    sig = request.headers.get("X-Nutonic-Signature") or request.headers.get("x-nutonic-signature")
    if not ts or not nonce or not sig:
        return "missing X-Nutonic-Timestamp, X-Nutonic-Nonce, or X-Nutonic-Signature"

    try:
        ts_i = int(str(ts).strip())
    except ValueError:
        return "invalid X-Nutonic-Timestamp"

    now = int(time.time())
    if abs(now - ts_i) > max_skew_s:
        return "X-Nutonic-Timestamp outside allowed skew"

    path = request.url.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    method = request.method.upper()
    canonical = f"{ts}\n{nonce}\n{method}\n{path}\n"
    expected = hmac.new(sec.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(sig).strip()):
        return "invalid X-Nutonic-Signature"

    nonce_err = _check_and_record_nonce(str(nonce).strip(), float(ts_i), max_skew_s)
    if nonce_err is not None:
        return nonce_err

    return None


def _check_and_record_nonce(nonce: str, ts: float, max_skew_s: int) -> str | None:
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
        while len(_NONCE_CACHE) >= _MAX_NONCE_CACHE:
            _NONCE_CACHE.popitem(last=False)
        _NONCE_CACHE[nonce] = ts
    return None


def install_hmac_middleware(app: object) -> None:
    """Register Starlette HTTP middleware on a FastAPI ``app``."""

    @app.middleware("http")
    async def _hmac_middleware(request: Request, call_next: Callable):  # type: ignore[no-untyped-def]
        err = verify_inbound_hmac(request)
        if err is not None:
            return JSONResponse({"detail": err}, status_code=401)
        return await call_next(request)
