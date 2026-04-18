from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from streetview_pano_service.google_static import fetch_metadata, fetch_static_jpeg


def test_fetch_metadata_ok() -> None:
    class FakeResp:
        status_code = 200
        text = json.dumps({"status": "OK", "pano_id": "p1"})

        def raise_for_status(self) -> None:
            return None

    with patch("streetview_pano_service.google_static.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = FakeResp()
        meta = fetch_metadata(10.0, 20.0, api_key="key")
    assert meta.pano_id == "p1"
    assert meta.status == "OK"


def test_fetch_static_jpeg_rejects_non_jpeg() -> None:
    class FakeResp:
        status_code = 200
        content = b"error not jpeg"

        def raise_for_status(self) -> None:
            return None

    with patch("streetview_pano_service.google_static.httpx.Client") as m:
        m.return_value.__enter__.return_value.get.return_value = FakeResp()
        with pytest.raises(RuntimeError, match="non-JPEG"):
            fetch_static_jpeg(lat=0.0, lon=0.0, api_key="k")


def test_fetch_static_jpeg_pano_query_has_pano_param() -> None:
    fake_jpeg = b"\xff\xd8" + b"\x00" * 2000

    class FakeResp:
        status_code = 200
        content = fake_jpeg

        def raise_for_status(self) -> None:
            return None

    with patch("streetview_pano_service.google_static.httpx.Client") as m:
        inst = m.return_value.__enter__.return_value
        inst.get.return_value = FakeResp()
        fetch_static_jpeg(pano_id="panorama_test_id", api_key="k", width=64, height=64)
        url = inst.get.call_args[0][0]
        assert "pano=panorama_test_id" in url
        assert "location=" not in url
