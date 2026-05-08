from __future__ import annotations

import hashlib
import hmac
from unittest.mock import patch

from nutonic_hmac import nutonic_hmac_headers


def test_nutonic_hmac_headers_matches_server_canonical() -> None:
    secret = "s"
    url = "http://example.org/api/v1/panos/sample"
    with patch("nutonic_hmac.time.time", return_value=1_700_000_000.0):
        with patch("nutonic_hmac.secrets.token_hex", return_value="abcd1234ef567890"):
            h = nutonic_hmac_headers("POST", url, secret)
    body_hash = hashlib.sha256(b"").hexdigest()
    canonical = f"1700000000\nabcd1234ef567890\nPOST\n/api/v1/panos/sample\n{body_hash}\n"
    expect = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    assert h["X-Nutonic-Content-SHA256"] == body_hash
    assert h["X-Nutonic-Signature"] == expect
