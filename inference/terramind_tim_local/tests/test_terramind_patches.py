"""TerraMind tokenizer hotfix: full-sequence coord decode + regex parse."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

_TERRA_SKIP = {"exc_type": ImportError, "reason": "requires a working terratorch stack (transformers/peft compatible)"}

torch = pytest.importorskip("torch")

from nutonic_terramind_tim_local.terramind_patches import (
    _coerce_discrete_token_ids,
    _parse_lat_lon_from_coord_text,
    apply_terramind_coord_decode_hotfix,
    apply_terramind_tim_runtime_hotfixes,
)


def test_coord_decode_hotfix_full_sequence_and_regex() -> None:
    pytest.importorskip("terratorch", **_TERRA_SKIP)
    apply_terramind_coord_decode_hotfix()
    from terratorch.models.backbones.terramind.tokenizer.text.text_tokenizer import CoordsTokenizer

    ct = CoordsTokenizer.__new__(CoordsTokenizer)
    mock_tok = MagicMock()
    mock_tok.decode = MagicMock(return_value="lat=10.25 lon=20.50 [EOS]")
    ct.text_tokenizer = mock_tok

    tensor = torch.tensor([[1, 2, 3, 4]], dtype=torch.long)
    mask = torch.zeros_like(tensor, dtype=torch.bool)
    mod: dict[str, dict[str, torch.Tensor]] = {"coords": {"tensor": tensor, "input_mask": mask}}

    out = CoordsTokenizer.decode_text(ct, mod)
    mock_tok.decode.assert_called_once_with([1, 2, 3, 4], skip_special_tokens=False)
    assert len(out) == 1
    lon, lat = out[0]
    assert lon == pytest.approx(20.5)
    assert lat == pytest.approx(10.25)


def test_coord_decode_hotfix_idempotent() -> None:
    pytest.importorskip("terratorch", **_TERRA_SKIP)
    apply_terramind_coord_decode_hotfix()
    apply_terramind_coord_decode_hotfix()


def test_coerce_discrete_token_ids_float_to_long() -> None:
    x = torch.tensor([[1.0, 2.4, 303.7]])
    y = _coerce_discrete_token_ids(x)
    assert y.dtype == torch.long
    assert y.tolist() == [[1, 2, 304]]


def test_tim_runtime_hotfixes_idempotent() -> None:
    pytest.importorskip("terratorch", **_TERRA_SKIP)
    apply_terramind_tim_runtime_hotfixes()
    apply_terramind_tim_runtime_hotfixes()


def test_parse_double_lon_prefix_mislabel() -> None:
    """Logs like ``lon=67.25 lon=-74.50``: training order is lat then lon; first ``lon=`` is lat."""
    lat, lon = _parse_lat_lon_from_coord_text("lon=67.25 lon=-74.50")
    assert lat == pytest.approx(67.25)
    assert lon == pytest.approx(-74.50)


def test_parse_double_lon_rejected_if_first_not_latitude_range() -> None:
    assert _parse_lat_lon_from_coord_text("lon=120 lon=30") is None


def test_parse_double_lat_missing_lon() -> None:
    lat, lon = _parse_lat_lon_from_coord_text("lat=-3.75 lat=-38.53")
    assert lat == pytest.approx(-3.75)
    assert lon == pytest.approx(-38.53)


def test_coord_decode_lon_before_lat_in_string() -> None:
    pytest.importorskip("terratorch", **_TERRA_SKIP)
    apply_terramind_coord_decode_hotfix()
    from terratorch.models.backbones.terramind.tokenizer.text.text_tokenizer import CoordsTokenizer

    ct = CoordsTokenizer.__new__(CoordsTokenizer)
    mock_tok = MagicMock()
    mock_tok.decode = MagicMock(return_value="lon=20.50 lat=10.25 [EOS]")
    ct.text_tokenizer = mock_tok

    tensor = torch.tensor([[9, 8, 7]], dtype=torch.long)
    mask = torch.zeros_like(tensor, dtype=torch.bool)
    mod: dict[str, dict[str, torch.Tensor]] = {"coords": {"tensor": tensor, "input_mask": mask}}

    out = CoordsTokenizer.decode_text(ct, mod)
    lon, lat = out[0]
    assert lon == pytest.approx(20.5)
    assert lat == pytest.approx(10.25)
