from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from streetview_pano_service.google_static import fetch_metadata, fetch_static_jpeg


def test_fetch_metadata_ok() -> None:
    class FakeResp:
        text = json.dumps({"status": "OK", "pano_id": "p1"})

        def raise_for_status(self) -> None:
            return None

    with patch("streetview_pano_service.google_static.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = FakeResp()
        meta = fetch_metadata(10.0, 20.0, api_key="key")
    assert meta["pano_id"] == "p1"


def test_fetch_static_jpeg_rejects_non_jpeg() -> None:
    class FakeResp:
        content = b"error not jpeg"

        def raise_for_status(self) -> None:
            return None

    with patch("streetview_pano_service.google_static.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = FakeResp()
        with pytest.raises(RuntimeError, match="non-JPEG"):
            fetch_static_jpeg(0.0, 0.0, api_key="k")
