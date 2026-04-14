"""Light tests for modality I/O wiring (torch required; no HF weights)."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from nutonic_terramind_tim_local.run import _build_inputs
from nutonic_terramind_tim_local.serialize import build_tim_modality_outputs


def test_build_inputs_s2l2a_random_shape() -> None:
    cfg = {
        "modalities": ["S2L2A"],
        "inputs": {"batch_size": 1, "s2_mode": "random"},
    }
    d, aux = _build_inputs(cfg, torch.device("cpu"))
    assert list(d.keys()) == ["S2L2A"]
    assert d["S2L2A"].shape == (1, 12, 224, 224)
    assert aux == {}


def test_build_inputs_rgb_plus_s2() -> None:
    cfg = {
        "modalities": ["RGB", "S2L2A"],
        "inputs": {"batch_size": 1, "mode": "zeros", "s2_mode": "zeros"},
    }
    d, _aux = _build_inputs(cfg, torch.device("cpu"))
    assert d["RGB"].shape == (1, 3, 224, 224)
    assert d["S2L2A"].shape == (1, 12, 224, 224)


def test_tim_outputs_full_retains_keys() -> None:
    class _Tok:
        def decode_text(self, _d):  # noqa: ANN001
            return None

    class _M:
        tokenizer = {"coords": _Tok()}

    tim_dict = {
        "coords": {"lat": torch.zeros(1)},
        "tok_lulc@224": {"ids": torch.zeros(1, 8, 8, dtype=torch.long)},
        "custom_extra": {"x": torch.ones(2, 3)},
    }
    full = build_tim_modality_outputs(_M(), tim_dict, tensor_sample_limit=0, policy="full")
    assert "coords" in full
    assert "tok_lulc@224" in full
    assert "custom_extra" in full

    prod = build_tim_modality_outputs(_M(), tim_dict, tensor_sample_limit=0, policy="product")
    assert "custom_extra" not in prod
