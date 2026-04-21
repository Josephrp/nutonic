"""Tile native rasters, downsample RGB + mask for model input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np


@dataclass(frozen=True)
class TileSpec:
    row_off: int
    col_off: int
    height: int
    width: int


def iter_tiles(h: int, w: int, tile: int, stride: int) -> Iterator[TileSpec]:
    """Yield **full** ``tile×tile`` windows; caller pads when ``h`` or ``w`` < ``tile``."""
    if tile <= 0 or stride <= 0:
        raise ValueError("tile and stride must be positive")
    if h < tile or w < tile:
        return
    for r in range(0, h - tile + 1, stride):
        for c in range(0, w - tile + 1, stride):
            yield TileSpec(r, c, tile, tile)


def clip_spatial_copy_to_tile(th: int, tw: int, native_tile: int) -> tuple[int, int]:
    """
    Height and width to copy from ``rgb``/``label`` into a ``native_tile``×``native_tile`` pad.

    When the grid is smaller than ``native_tile`` on one axis but **larger** on the other, the
    destination slice ``pad[:, :th, :tw]`` is silently capped at ``native_tile`` on each axis,
    while the source slice used full ``th``×``tw`` and no longer matched (broadcast error).
    """
    nt = int(native_tile)
    return min(int(th), nt), min(int(tw), nt)


def reflectance_stack_to_uint8(
    rgb: np.ndarray,
    *,
    p_lo: float = 2.0,
    p_hi: float = 98.0,
) -> np.ndarray:
    """
    ``rgb`` is ``(3, H, W)`` float. Returns ``(H, W, 3)`` uint8 with per-band percentile stretch.
    """
    _, h, w = rgb.shape
    out = np.zeros((h, w, 3), dtype=np.uint8)
    for i in range(3):
        band = rgb[i].astype(np.float32)
        valid = np.isfinite(band) & (band > 0)
        if not np.any(valid):
            continue
        lo, hi = np.percentile(band[valid], (p_lo, p_hi))
        if hi <= lo:
            hi = lo + 1e-6
        scaled = (band - lo) / (hi - lo)
        scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)
        out[..., i] = (np.clip(scaled, 0.0, 1.0) * 255.0).astype(np.uint8)
    return out


def downsample_tile(
    rgb_uint8_hw3: np.ndarray,
    mask_hw: np.ndarray,
    *,
    output_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Bilinear RGB and **nearest** mask to ``(output_size, output_size)``.

    Uses **Pillow** only (no ``scikit-image``) so ``pip install -r data/scripts/requirements.txt``
    is enough when Pillow is present.
    """
    from PIL import Image

    h, w, _ = rgb_uint8_hw3.shape
    if h != mask_hw.shape[0] or w != mask_hw.shape[1]:
        raise ValueError("RGB and mask spatial shapes must match")
    size = (output_size, output_size)
    rgb_small = np.asarray(
        Image.fromarray(rgb_uint8_hw3).resize(size, Image.Resampling.BILINEAR),
        dtype=np.uint8,
    )
    mask_small = np.asarray(
        Image.fromarray(mask_hw).resize(size, Image.Resampling.NEAREST),
        dtype=np.uint8,
    )
    return rgb_small, mask_small


def tile_valid_fraction(mask_tile: np.ndarray, ignore: int = 255) -> float:
    flat = mask_tile.ravel()
    ok = flat != ignore
    if not np.any(ok):
        return 0.0
    return float(np.mean(ok))
