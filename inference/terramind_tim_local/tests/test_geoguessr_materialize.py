"""Token grid reshape for TiM materialization (torch only)."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from nutonic_terramind_tim_local.geoguessr_materialize import _codebook_upper, _ids_bhw_from_block


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
