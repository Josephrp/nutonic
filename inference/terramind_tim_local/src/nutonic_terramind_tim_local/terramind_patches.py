"""Upstream TerraTorch / TerraMind hotfixes applied at import time."""

from __future__ import annotations

import functools
import re
import warnings
from typing import Any

import torch

# Match training-style ``lat=…`` / ``lon=…`` independently so ``lon=… lat=…`` order works.
_COORD_LAT_RE = re.compile(r"lat\s*=\s*([-+]?\d*(?:\.\d+)?(?:[eE][-+]?\d+)?)")
_COORD_LON_RE = re.compile(r"lon\s*=\s*([-+]?\d*(?:\.\d+)?(?:[eE][-+]?\d+)?)")

_PATCHED = False
_MERGE_SEQ_LONG_PATCHED = False
_TOKEN_EMB_INDICES_PATCHED = False


def _parse_lat_lon_from_coord_text(text: str) -> tuple[float, float] | None:
    """
    Best-effort (decode-string only) WGS84 pair ``(latitude, longitude)``.

    Training encodes ``lat=<lat> lon=<lon>`` (see TerraTorch ``CoordsTokenizer.encode``).
    Generation sometimes mis-labels the first field (e.g. ``lon=67.25 lon=-74.50``):
    numeric order still matches ``(lat, lon)``, so two ``lon=`` captures are interpreted
    as latitude then longitude when values fit WGS84 ranges. Symmetric for duplicated
    ``lat=`` when ``lon=`` is missing. Duplicate ``lat=`` before a single ``lon=`` uses
    the **last** latitude (model stutter) with that longitude.
    """
    try:
        lat_vals = [float(m.group(1)) for m in _COORD_LAT_RE.finditer(text)]
        lon_vals = [float(m.group(1)) for m in _COORD_LON_RE.finditer(text)]
    except ValueError:
        return None

    if len(lat_vals) == 1 and len(lon_vals) == 1:
        return lat_vals[0], lon_vals[0]

    if len(lat_vals) == 0 and len(lon_vals) >= 2:
        a, b = lon_vals[0], lon_vals[1]
        if abs(a) <= 90.0 and abs(b) <= 180.0:
            return a, b
        return None

    if len(lat_vals) >= 2 and len(lon_vals) == 0:
        a, b = lat_vals[0], lat_vals[1]
        if abs(a) <= 90.0 and abs(b) <= 180.0:
            return a, b
        return None

    # Model stutter: ``lat=… lat=… lon=…`` (duplicate lat prefix); pair last lat with lon.
    if len(lat_vals) >= 2 and len(lon_vals) == 1:
        la, lo = lat_vals[-1], lon_vals[0]
        if abs(la) <= 90.0 and abs(lo) <= 180.0:
            return la, lo
        return None

    # Symmetric: ``lon=… lon=… lat=…``
    if len(lon_vals) >= 2 and len(lat_vals) == 1:
        la, lo = lat_vals[0], lon_vals[-1]
        if abs(la) <= 90.0 and abs(lo) <= 180.0:
            return la, lo
        return None

    return None


def _coords_decode_text_patched(self: Any, mod_dict: dict[str, Any], key: str = "coords") -> list[list[float]]:
    """Decode full coord token rows (like ``CaptionTokenizer``), then parse WGS84 best-effort."""
    coords: list[list[float]] = []
    entry = mod_dict[key]
    tensor = entry["tensor"]
    b = int(tensor.shape[0])
    mask = entry.get("input_mask")
    for i in range(b):
        seq = tensor[i]
        if mask is not None:
            seq = seq[mask[i] == 0]
        ids = seq.tolist()
        text = self.text_tokenizer.decode(ids, skip_special_tokens=False)
        text = text.replace(" [EOS]", "").strip()
        parsed = _parse_lat_lon_from_coord_text(text)
        if parsed is None:
            warnings.warn(
                f"Coordinate generation did not work correctly, generated text: {text!r}. Returning NaN.",
                stacklevel=2,
            )
            coords.append([float("nan"), float("nan")])
            continue
        lat, lon = parsed
        coords.append([lon, lat])
    return coords


def apply_terramind_coord_decode_hotfix() -> None:
    """Monkey-patch TerraTorch ``CoordsTokenizer.decode_text`` (full sequence + robust parse)."""
    global _PATCHED
    if _PATCHED:
        return
    from terratorch.models.backbones.terramind.tokenizer.text import text_tokenizer as tt

    tt.CoordsTokenizer.decode_text = _coords_decode_text_patched  # type: ignore[method-assign]
    _PATCHED = True


def _coerce_discrete_token_ids(t: torch.Tensor) -> torch.Tensor:
    """``nn.Embedding`` requires integer indices; some TiM paths yield float tensors (e.g. merge_sequences)."""
    if not isinstance(t, torch.Tensor) or not t.is_floating_point():
        return t
    return t.round().clamp(min=0).to(dtype=torch.long)


def apply_terramind_tim_merge_sequences_long_hotfix() -> None:
    """
    Ensure sequence merge outputs are ``long`` token rows.

    TerraTorch ``GenerationSampler.merge_sequences`` uses ``torch.tensor(merged_ids)`` without an
    explicit integer dtype. If ``pred_ids`` is a floating tensor (mixed precision / dtype promotion),
    merged coordinate tokens stay float and ``TerraMindTiM.forward`` fails on the second encoder pass
    with: embedding indices must be Long/Int.
    """
    global _MERGE_SEQ_LONG_PATCHED
    if _MERGE_SEQ_LONG_PATCHED:
        return
    from terratorch.models.backbones.terramind.model.generate import GenerationSampler

    _orig_ms = GenerationSampler.merge_sequences
    _orig_msb = GenerationSampler.merge_sequences_batched

    @functools.wraps(_orig_ms)
    def merge_sequences(  # noqa: ANN001
        self,
        mod_dict,
        pred_ids,
        target_mod,
        text_tokenizer,
        default_sentinel="[S_1]",
    ):
        _orig_ms(self, mod_dict, pred_ids, target_mod, text_tokenizer, default_sentinel)
        blk = mod_dict[target_mod]
        if isinstance(blk, dict) and isinstance(blk.get("tensor"), torch.Tensor):
            blk["tensor"] = _coerce_discrete_token_ids(blk["tensor"])
        return mod_dict

    @functools.wraps(_orig_msb)
    def merge_sequences_batched(  # noqa: ANN001
        self,
        mod_dict,
        pred_ids,
        target_mod,
        text_tokenizer,
        default_sentinel="[S_1]",
    ):
        _orig_msb(self, mod_dict, pred_ids, target_mod, text_tokenizer, default_sentinel)
        blk = mod_dict[target_mod]
        if isinstance(blk, dict) and isinstance(blk.get("tensor"), torch.Tensor):
            blk["tensor"] = _coerce_discrete_token_ids(blk["tensor"])
        return mod_dict

    GenerationSampler.merge_sequences = merge_sequences  # type: ignore[method-assign]
    GenerationSampler.merge_sequences_batched = merge_sequences_batched  # type: ignore[method-assign]
    _MERGE_SEQ_LONG_PATCHED = True


def apply_terramind_token_embedding_indices_hotfix() -> None:
    """
    Coerce float token maps to ``long`` before ``nn.Embedding`` in TerraMind token/sequence encoders.

    Defense in depth for TiM outputs (e.g. LULC/NDVI token grids or coords) that should be discrete IDs.
    """
    global _TOKEN_EMB_INDICES_PATCHED
    if _TOKEN_EMB_INDICES_PATCHED:
        return
    from terratorch.models.backbones.terramind.model.encoder_embeddings import (
        ImageTokenEncoderEmbedding,
        SequenceEncoderEmbedding,
    )

    def _wrap_forward(orig):  # noqa: ANN001
        @functools.wraps(orig)
        def forward(self, d):  # noqa: ANN001
            if isinstance(d, dict):
                t = d.get("tensor")
                if isinstance(t, torch.Tensor) and t.is_floating_point():
                    d = {**d, "tensor": _coerce_discrete_token_ids(t)}
            elif isinstance(d, torch.Tensor) and d.is_floating_point():
                d = _coerce_discrete_token_ids(d)
            return orig(self, d)

        return forward

    SequenceEncoderEmbedding.forward = _wrap_forward(SequenceEncoderEmbedding.forward)  # type: ignore[method-assign]
    ImageTokenEncoderEmbedding.forward = _wrap_forward(ImageTokenEncoderEmbedding.forward)  # type: ignore[method-assign]
    _TOKEN_EMB_INDICES_PATCHED = True


def apply_terramind_tim_runtime_hotfixes() -> None:
    """Apply all TerraMind TiM runtime patches used by this package (safe to call multiple times)."""
    apply_terramind_coord_decode_hotfix()
    apply_terramind_tim_merge_sequences_long_hotfix()
    apply_terramind_token_embedding_indices_hotfix()
