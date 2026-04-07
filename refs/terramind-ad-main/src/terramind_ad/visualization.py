from pathlib import Path

import numpy as np
from numpy.typing import NDArray


def read_raster(path: Path, dtype: type = np.float32) -> NDArray[np.floating]:
    """Load raster image.

    Returns array with shape (C, H, W).
    """
    import numpy as np
    import rasterio as rio

    with rio.open(path) as src:
        data = src.read().astype(dtype)
        assert np.sum(np.isnan(data)) == 0, f"{path} contains NaNs!"
    return data


def l2_normalize(embeddings: np.ndarray, axis: int = -1, eps: float = 1e-8) -> np.ndarray:
    """L2 normalize embeddings to unit length.

    Args:
        embeddings: array of embeddings (..., D)
        axis: dimension to normalize along
        eps: small constant to avoid division by zero

    Returns:
        normalized embeddings with same shape
    """
    norms = np.linalg.norm(embeddings, axis=axis, keepdims=True)
    return embeddings / (norms + eps)


def min_max_scale(values: np.ndarray) -> np.ndarray:
    """Scale values to [0, 1] using min-max normalization.

    Args:
        values: input array

    Returns:
        scaled array in [0, 1]
    """
    vmin = values.min()
    vmax = values.max()
    if vmax - vmin < 1e-8:
        return np.zeros_like(values)
    return (values - vmin) / (vmax - vmin)


def percentile_clip_scale(values: np.ndarray, lower: float = 2.0, upper: float = 98.0) -> np.ndarray:
    """Clip values to percentile range and scale to [0, 1].

    Args:
        values: input array
        lower: lower percentile (default 2nd percentile)
        upper: upper percentile (default 98th percentile)

    Returns:
        clipped and scaled array in [0, 1]
    """
    vmin, vmax = np.percentile(values, [lower, upper])
    clipped = np.clip(values, vmin, vmax)
    if vmax - vmin < 1e-8:
        return np.zeros_like(clipped)
    return (clipped - vmin) / (vmax - vmin)
