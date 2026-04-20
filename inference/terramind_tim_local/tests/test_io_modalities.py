"""Light tests for modality I/O wiring (torch required; no HF weights)."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from nutonic_terramind_tim_local.inputs_build import _build_inputs, _rgb_from_s12_reflectance
from nutonic_terramind_tim_local.serialize import build_tim_modality_outputs, mean_arithmetic_latlon


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


def test_rgb_s2_rgb_matches_s2_channels() -> None:
    s12 = torch.arange(12 * 4, dtype=torch.float32).reshape(1, 12, 2, 2)
    rgb = _rgb_from_s12_reflectance(s12)
    assert rgb.shape == (1, 3, 2, 2)
    # channels 3,2,1 = RED, GREEN, BLUE
    assert torch.equal(rgb[0, 0], s12[0, 3])
    assert torch.equal(rgb[0, 1], s12[0, 2])
    assert torch.equal(rgb[0, 2], s12[0, 1])


def test_build_inputs_rgb_s2_rgb_shared_zeros_not_stac() -> None:
    """Shared STAC path is skipped when neither branch uses stac/s2_rgb."""
    cfg = {
        "modalities": ["RGB", "S2L2A"],
        "inputs": {"batch_size": 1, "rgb_mode": "zeros", "s2_mode": "zeros"},
    }
    d, aux = _build_inputs(cfg, torch.device("cpu"))
    assert d["RGB"].shape == (1, 3, 224, 224)
    assert d["S2L2A"].shape == (1, 12, 224, 224)
    assert aux == {}


def test_mean_arithmetic_latlon_skips_missing_and_nan() -> None:
    pairs: list[tuple[float | None, float | None]] = [
        (1.0, 10.0),
        (None, None),
        (3.0, 30.0),
        (float("nan"), 0.0),
    ]
    la, lo = mean_arithmetic_latlon(pairs)
    assert la == pytest.approx(2.0)
    assert lo == pytest.approx(20.0)


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
