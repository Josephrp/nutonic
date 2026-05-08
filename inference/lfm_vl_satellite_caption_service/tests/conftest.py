from __future__ import annotations

import pytest

from lfm_vl_satellite_caption_service.config import reset_settings_cache
from lfm_vl_satellite_caption_service.infer_transformers import reset_model


@pytest.fixture(autouse=True)
def _reset_satellite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LFM_SATELLITE_BACKEND", "stub")
    reset_settings_cache()
    reset_model()
    yield
    reset_settings_cache()
    reset_model()
