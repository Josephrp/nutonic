from __future__ import annotations

import pytest

from streetview_pano_service.pano_config import reset_pano_settings_cache


@pytest.fixture(autouse=True)
def _reset_pano_env() -> None:
    reset_pano_settings_cache()
    yield
    reset_pano_settings_cache()
