"""Tests for batch Street View HTTP retry helpers."""

from __future__ import annotations

import httpx

from tools.batch_streetview_hints import _parse_retry_after_sec


def test_parse_retry_after_numeric() -> None:
    r = httpx.Response(503, headers={"retry-after": "12"})
    assert _parse_retry_after_sec(r) == 12.0


def test_parse_retry_after_caps_huge_value() -> None:
    r = httpx.Response(503, headers={"retry-after": "99999"})
    assert _parse_retry_after_sec(r) == 300.0


def test_parse_retry_after_missing() -> None:
    r = httpx.Response(503, headers={})
    assert _parse_retry_after_sec(r) is None
