"""
Inbound HMAC verification (IMP-092) — canonical string must match ``nutonic_server.inference_client``.

Keep in sync with ``streetview_pano_service/inference_hmac.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse


def hmac_secret() -> str:
    return (
        os.environ.get("NUTONIC_INFERENCE_HMAC_SECRET") or os.environ.get("INFERENCE_HMAC_SECRET") or ""
    ).strip()


def require_inbound_hmac() -> bool:
    v = (os.environ.get("NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def verify_inbound_hmac(request: Request, *, max_skew_s: int = 300) -> str | None:
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

    return None


def install_hmac_middleware(app: object) -> None:
    @app.middleware("http")
    async def _hmac_middleware(request: Request, call_next: Callable):  # type: ignore[no-untyped-def]
        err = verify_inbound_hmac(request)
        if err is not None:
            return JSONResponse({"detail": err}, status_code=401)
        return await call_next(request)
