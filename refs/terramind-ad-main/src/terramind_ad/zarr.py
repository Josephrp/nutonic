import logging
from pathlib import Path

import numpy as np
import xarray as xr
import zarr

log = logging.getLogger(__name__)


def save_timeseries(data: xr.DataArray, output_path: Path) -> None:
    """Save xarray time series to Zarr format with efficient chunking.

    Uses per-timestep chunking for efficient temporal access and spatial
    chunks for large images.
    """
    # ensure DataArray has a name
    if data.name is None:
        data = data.rename("data")

    # chunk: 1 timestep at a time, spatial chunks of 512x512
    # this allows efficient incremental writes and temporal slicing
    T, C, H, W = data.shape
    chunk_size = {"time": 1, "band": C, "y": min(512, H), "x": min(512, W)}

    # rechunk and write to zarr (xarray handles compression automatically)
    data = data.chunk(chunk_size)
    data.to_zarr(output_path, mode="w", consolidated=True)
    log.info("Saved Zarr time series: %s with shape %s", output_path, data.shape)


def load_timeseries(zarr_path: Path, time_slice: slice | None = None) -> xr.DataArray:
    """Load time series from Zarr format."""
    ds = xr.open_zarr(zarr_path, consolidated=True)
    data = ds[list(ds.data_vars)[0]]
    if time_slice is not None:
        data = data.isel(time=time_slice)
    return data


def save_features(
    features: np.ndarray, timestamps: list[str], output_path: Path, metadata: dict | None = None
) -> None:
    """Save feature time series to Zarr format.

    Args:
        features: array with shape (T, H, W, D)
        timestamps: list of timestamp strings
        output_path: path to save Zarr store
        metadata: optional metadata dict
    """
    root = zarr.open_group(str(output_path), mode="w")
    # chunk per timestep, full spatial and feature dimensions
    chunks = (1, features.shape[1], features.shape[2], features.shape[3])
    root.create_array("features", data=features, chunks=chunks)
    root.create_array("timestamps", data=np.array(timestamps, dtype="S10"))
    if metadata:
        root.attrs.update(metadata)
    log.info("Saved feature time series: %s with shape %s", output_path, features.shape)


def load_features(
    zarr_path: Path, time_indices: list[int] | slice | None = None
) -> tuple[np.ndarray, list[str], dict]:
    """Load features from Zarr format."""
    root = zarr.open(str(zarr_path), mode="r")
    features = root["features"][time_indices] if time_indices is not None else root["features"][:]  # type: ignore
    timestamps = root["timestamps"][time_indices] if time_indices is not None else root["timestamps"][:]  # type: ignore
    timestamps = [ts.decode("utf-8") for ts in timestamps]  # type: ignore
    return features, timestamps, dict(root.attrs)  # type: ignore


def save_cloud_masks(cloud_masks: np.ndarray, timestamps: list[str], spatial_coords: dict, output_path: Path) -> None:
    """Save cloud masks to Zarr format.

    Args:
        cloud_masks: array with shape (T, H, W) containing cloud masks
        timestamps: list of timestamp strings
        spatial_coords: dict with 'y' and 'x' coordinates
        output_path: path to save clouds.zarr
    """
    if cloud_masks.ndim != 3:
        raise ValueError(f"Expected 3D cloud mask array (T, H, W), got {cloud_masks.shape}")

    # create DataArray
    cloud_da = xr.DataArray(
        cloud_masks,
        coords={"time": timestamps, "y": spatial_coords["y"], "x": spatial_coords["x"]},
        dims=["time", "y", "x"],
        name="cloud_mask",
    )

    # save to zarr
    cloud_da.to_zarr(output_path, mode="w", consolidated=True)
    log.info("Saved cloud masks to %s with shape %s", output_path, cloud_masks.shape)
