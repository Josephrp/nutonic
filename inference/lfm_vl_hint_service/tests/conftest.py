from __future__ import annotations

import pytest

from lfm_vl_hint_service.config import reset_settings_cache
from lfm_vl_hint_service.infer_transformers import reset_transformers_model


@pytest.fixture(autouse=True)
def _reset_lfm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LFM_VL_BACKEND", "stub")
    reset_settings_cache()
    reset_transformers_model()
    yield
    reset_settings_cache()
    reset_transformers_model()
