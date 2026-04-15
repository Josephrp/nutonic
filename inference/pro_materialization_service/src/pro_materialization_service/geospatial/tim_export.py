"""TerraMind tensor handoff — ``RGB`` / ``S2L2A`` NPZ (``numpy`` only, no torch)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def rgb_mapbox_npz_from_png(
    png_bytes: bytes,
    *,
    tim_height: int = 224,
    tim_width: int = 224,
) -> bytes:
    """
    Build NPZ with key ``RGB``: shape ``[1, 3, H, W]``, ``float32``, channel order **B, G, R**
    with values ``0..255`` (plan §4.2 branch B).
    """
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    im = im.resize((tim_width, tim_height), Image.Resampling.BILINEAR)
    arr = np.asarray(im, dtype=np.float32)  # H, W, RGB
    bgr = arr[:, :, ::-1]  # H, W, BGR
    chw = np.transpose(bgr, (2, 0, 1))  # 3, H, W
    stacked = np.expand_dims(chw, axis=0)  # 1, 3, H, W
    bio = io.BytesIO()
    np.savez_compressed(bio, RGB=stacked)
    return bio.getvalue()


def s2l2a_npz_from_stack(stack_12_hw: np.ndarray) -> bytes:
    """
    NPZ key ``S2L2A``: shape ``[1, 12, H, W]``, ``float32`` (TerraMind / ``terramind_tim_local`` order).
    ``stack_12_hw`` must be ``(12, H, W)``.
    """
    if stack_12_hw.ndim != 3 or stack_12_hw.shape[0] != 12:
        raise ValueError(f"expected (12, H, W), got {stack_12_hw.shape}")
    chw = stack_12_hw.astype(np.float32, copy=False)
    stacked = np.expand_dims(chw, axis=0)
    bio = io.BytesIO()
    np.savez_compressed(bio, S2L2A=stacked)
    return bio.getvalue()
