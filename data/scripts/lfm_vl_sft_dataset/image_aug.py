"""Fixed geometric views on square RGB + mask (flip, 90° rotations) — no resampling."""

from __future__ import annotations

from typing import Iterator

import numpy as np


def iter_square_augmentations(
    rgb_hw3: np.ndarray,
    mask_hw: np.ndarray,
    *,
    hflip: bool,
    rot90: bool,
) -> Iterator[tuple[str, np.ndarray, np.ndarray]]:
    """
    Yield ``(suffix, rgb, mask)`` for extra training views (not including identity).

    ``rot90`` emits three views: 90°, 180°, 270° counter-clockwise (``numpy.rot90``).
    """
    assert rgb_hw3.shape[:2] == mask_hw.shape[:2], "RGB and mask must align spatially"
    if hflip:
        yield (
            "flip",
            np.ascontiguousarray(rgb_hw3[:, ::-1, :]),
            np.ascontiguousarray(mask_hw[:, ::-1]),
        )
    if rot90:
        for k, name in ((1, "r90"), (2, "r180"), (3, "r270")):
            yield (
                name,
                np.ascontiguousarray(np.rot90(rgb_hw3, k=k, axes=(0, 1))),
                np.ascontiguousarray(np.rot90(mask_hw, k=k, axes=(0, 1))),
            )
