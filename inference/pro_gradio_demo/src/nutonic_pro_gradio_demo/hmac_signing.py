"""
Outbound HMAC headers for calling NU:TONIC services.

Mirrors `tools/nutonic_hmac.py` and `server/src/nutonic_server/inference_client.py`
so that this Space participates in the same `X-Nutonic-*` request signing contract
when `NUTONIC_INFERENCE_HMAC_SECRET` (or `INFERENCE_HMAC_SECRET`) is configured.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import urlparse


def nutonic_hmac_headers(
    *,
    method: str,
    url: str,
    secret: str,
    body: bytes = b"",
) -> dict[str, str]:
    """Return ``X-Nutonic-*`` headers for one request (same canonical form as the rest of the repo)."""
    sec = (secret or "").strip()
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
