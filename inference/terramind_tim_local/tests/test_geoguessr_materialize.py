"""Token grid reshape for TiM materialization (torch only)."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from nutonic_terramind_tim_local.geoguessr_materialize import (
    _codebook_upper,
    _ids_bhw_from_block,
    _safe_stem,
    _tensor_bchw_to_rgb_u8,
)


def test_safe_stem_replaces_at() -> None:
    assert _safe_stem("tok_lulc@224") == "tok_lulc_at_224"


def test_tensor_bchw_s2_rgb_order_uses_b321() -> None:
    # 12 bands: make RED high on band 3, others low → red-ish pixel
    t = torch.zeros(1, 12, 2, 2)
    t[0, 3, 0, 0] = 8000.0
    t[0, 2, 0, 0] = 500.0
    t[0, 1, 0, 0] = 500.0
    rgb = _tensor_bchw_to_rgb_u8(t)
    assert rgb.shape == (2, 2, 3)
    assert rgb[0, 0, 0] > rgb[0, 0, 2]


def test_codebook_upper_fsq_hyphen_string_uses_level_product() -> None:
    class _Q:
        _levels = __import__("torch").tensor([7, 5, 5, 5, 5], dtype=torch.int32)

    class _T:
        codebook_size = "7-5-5-5-5"
        quantize = _Q()

    assert _codebook_upper(_T()) == 7 * 5 * 5 * 5 * 5


def test_ids_bhw_from_block_196_tokens() -> None:
    t = torch.arange(196, dtype=torch.float32).view(1, 196)
    ids = _ids_bhw_from_block({"tensor": t}, torch.device("cpu"))
    assert ids.shape == (1, 14, 14)
    assert ids.dtype == torch.int64
