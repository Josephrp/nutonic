"""Tests for ``hf_hub_tokens`` env mapping."""

from __future__ import annotations

import os

import pytest

import hf_hub_tokens as mod


@pytest.fixture(autouse=True)
def clear_hf_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "HUGGING_FACE_HUB_TOKEN",
        "HF_TOKEN",
        "HF_API_READ",
        "HF_API_WRITE",
    ):
        monkeypatch.delenv(k, raising=False)


def test_apply_hf_read_token_sets_hub_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_API_READ", "readtok")
    mod.apply_hf_read_token()
    assert os.environ.get("HUGGING_FACE_HUB_TOKEN") == "readtok"


def test_apply_hf_write_token_prefers_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_API_WRITE", "writetok")
    mod.apply_hf_write_token()
    assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "writetok"
    assert os.environ["HF_TOKEN"] == "writetok"


def test_apply_hf_tokens_for_hub_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_API_READ", "r")
    mod.apply_hf_tokens_for_hub(write=False)
    assert os.environ.get("HUGGING_FACE_HUB_TOKEN") == "r"


def test_apply_hf_tokens_for_hub_write_fallback_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_API_READ", "ronly")
    mod.apply_hf_tokens_for_hub(write=True)
    assert os.environ.get("HUGGING_FACE_HUB_TOKEN") == "ronly"
