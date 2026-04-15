"""Upstream TerraTorch / TerraMind hotfixes applied at import time."""

from __future__ import annotations

import re
import warnings
from typing import Any

# Match training-style ``lat=…`` / ``lon=…`` independently so ``lon=… lat=…`` order works.
_COORD_LAT_RE = re.compile(r"lat\s*=\s*([-+]?\d*(?:\.\d+)?(?:[eE][-+]?\d+)?)")
_COORD_LON_RE = re.compile(r"lon\s*=\s*([-+]?\d*(?:\.\d+)?(?:[eE][-+]?\d+)?)")

_PATCHED = False


def _parse_lat_lon_from_coord_text(text: str) -> tuple[float, float] | None:
    """
    Best-effort (decode-string only) WGS84 pair ``(latitude, longitude)``.

    Training encodes ``lat=<lat> lon=<lon>`` (see TerraTorch ``CoordsTokenizer.encode``).
    Generation sometimes mis-labels the first field (e.g. ``lon=67.25 lon=-74.50``):
    numeric order still matches ``(lat, lon)``, so two ``lon=`` captures are interpreted
    as latitude then longitude when values fit WGS84 ranges. Symmetric for duplicated
    ``lat=`` when ``lon=`` is missing.
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
