"""Spectral index utilities for Sentinel-2-based profile datasets."""

from __future__ import annotations

import numpy as np


def _safe_ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """Return float32 ratio with NaN where denominator is near zero or non-finite."""
    num_f = num.astype(np.float32, copy=False)
    den_f = den.astype(np.float32, copy=False)
    out = np.full_like(num_f, np.nan, dtype=np.float32)
    valid = np.isfinite(num_f) & np.isfinite(den_f) & (np.abs(den_f) > 1e-6)
    out[valid] = num_f[valid] / den_f[valid]
    return out


def compute_nbr(nir: np.ndarray, swir2: np.ndarray) -> np.ndarray:
    """Normalized Burn Ratio: (NIR - SWIR2) / (NIR + SWIR2)."""
    return _safe_ratio(nir - swir2, nir + swir2)


def compute_ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Normalized Difference Water Index: (Green - NIR) / (Green + NIR)."""
    return _safe_ratio(green - nir, green + nir)


def compute_mndwi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """Modified NDWI: (Green - SWIR1) / (Green + SWIR1)."""
    return _safe_ratio(green - swir1, green + swir1)


def compute_dnbr(nbr_pre: np.ndarray, nbr_post: np.ndarray) -> np.ndarray:
    """Differenced NBR: pre - post."""
    pre = nbr_pre.astype(np.float32, copy=False)
    post = nbr_post.astype(np.float32, copy=False)
    out = pre - post
    out[~np.isfinite(pre) | ~np.isfinite(post)] = np.nan
    return out

