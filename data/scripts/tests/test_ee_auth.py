"""Tests for Earth Engine auth helpers (service account path mocked)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_resolve_project_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EE_PROJECT", raising=False)
    from lfm_vl_sft_dataset import ee_auth

    assert ee_auth._resolve_project("myproj") == "myproj"


def test_resolve_project_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EE_PROJECT", "fromenv")
    from lfm_vl_sft_dataset import ee_auth

    assert ee_auth._resolve_project(None) == "fromenv"


def test_service_account_key_paths_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EE_SERVICE_ACCOUNT_KEY_PATH", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    from lfm_vl_sft_dataset import ee_auth

    a = tmp_path / "a.json"
    a.write_text("{}", encoding="utf-8")
    out = ee_auth._service_account_key_paths(a)
    assert out == [a]


def test_initialize_service_account_branch(tmp_path: Path) -> None:
    pytest.importorskip("ee")
    key = tmp_path / "sa.json"
    key.write_text(
        json.dumps(
            {
                "type": "service_account",
                "client_email": "svc@test.iam.gserviceaccount.com",
                "private_key_id": "dummy",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----\n",
                "project_id": "radioshaq",
            }
        ),
        encoding="utf-8",
    )

    from lfm_vl_sft_dataset.ee_auth import initialize_earth_engine

    with patch("ee.Number") as num, patch("ee.ServiceAccountCredentials") as sac, patch("ee.Initialize") as init:
        num.return_value.getInfo.side_effect = RuntimeError("not initialized yet")
        meta = initialize_earth_engine(project="radioshaq", service_account_key=key)
        sac.assert_called_once()
        init.assert_called_once()
        assert meta["mode"] == "service_account"
        assert meta["project"] == "radioshaq"
