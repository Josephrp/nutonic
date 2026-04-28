"""
Outbound HMAC headers for calling inference workers (same contract as ``nutonic_server.inference_client``).

Used by ``tools/batch_streetview_hints.py`` when ``NUTONIC_INFERENCE_HMAC_SECRET`` / ``INFERENCE_HMAC_SECRET``
is set in the environment (aligns with workers that enable ``NUTONIC_INFERENCE_REQUIRE_INBOUND_HMAC``).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlparse


def nutonic_hmac_headers(method: str, url: str, secret: str, *, body: bytes = b"") -> dict[str, str]:
    """Return ``X-Nutonic-*`` headers for one request (method is ``GET`` or ``POST``, etc.)."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{ts}\n{nonce}\n{method.upper()}\n{path}\n{body_hash}\n"
    sig = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Nutonic-Timestamp": ts,
        "X-Nutonic-Nonce": nonce,
        "X-Nutonic-Content-SHA256": body_hash,
        "X-Nutonic-Signature": sig,
    }


def nutonic_hmac_headers_from_env(method: str, url: str, *, body: bytes = b"") -> dict[str, str]:
    """If env secret is set, return signing headers; else empty dict."""
    sec = (os.environ.get("NUTONIC_INFERENCE_HMAC_SECRET") or os.environ.get("INFERENCE_HMAC_SECRET") or "").strip()
    if not sec:
        return {}
    return nutonic_hmac_headers(method, url, sec, body=body)
