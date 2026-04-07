import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import planetary_computer
import pystac_client
import xarray as xr
from scipy.ndimage import convolve
from shapely.geometry import shape
from tqdm import tqdm

from terramind_ad.data import DisasterSite

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
log = logging.getLogger(__name__)


def create_client() -> pystac_client.Client:
    """Create authenticated STAC client for Planetary Computer."""
    return pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)


def get_bbox(site: DisasterSite) -> np.ndarray:
    """Extract WGS84 bounding box from site geometry.

    Args:
        site: disaster site configuration

    Returns:
        bounding box as [minx, miny, maxx, maxy]
    """
    geometries = [shape(f.geometry.model_dump()) for f in site.observed_event.features]
    gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")
    return gdf.total_bounds


def fill_nans(data: np.ndarray) -> np.ndarray:
    """Fill scattered NaN values with average of valid neighbors, per band.

    Args:
        data: array with shape (bands, height, width)

    Returns:
        array with NaNs filled, same shape as input
    """
    filled = data.copy()
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.float32)

    for band_idx in tqdm(range(data.shape[0]), desc="Filling NaNs"):
        band = filled[band_idx]
        nan_mask = np.isnan(band)
        if not nan_mask.any():
            continue
        # replace NaNs with 0 for convolution
        valid = ~nan_mask
        band_no_nan = np.where(valid, band, 0)
        # sum of valid neighbors
        neighbor_sum = convolve(band_no_nan.astype(np.float32), kernel, mode="constant", cval=0.0)
        # count of valid neighbors
        neighbor_count = convolve(valid.astype(np.float32), kernel, mode="constant", cval=0.0)
        # avoid division by zero
        neighbor_mean = np.divide(
            neighbor_sum, neighbor_count, where=neighbor_count > 0, out=np.zeros_like(neighbor_sum)
        )
        filled[band_idx] = np.where(nan_mask, neighbor_mean, band)
    return filled


def save_cog(data: xr.DataArray, filename: Path, fill_gaps: bool = True) -> None:
    """Save xarray DataArray to COG file with optional NaN filling.

    Args:
        data: xarray DataArray to save
        filename: output file path
        fill_gaps: whether to fill NaN values before saving

    Raises:
        ValueError: if NaN values remain after gap filling is disabled
    """
    values = data.values
    nan_count = int(np.isnan(values).sum())

    if nan_count > 0:
        if fill_gaps:
            nan_ratio = nan_count / values.size
            log.warning(
                "%s contains %d NaN values (%.2f%% of %d pixels). Filling gaps.",
                filename.name,
                nan_count,
                nan_ratio * 100,
                values.size,
            )
            data.values = fill_nans(values)
        else:
            raise ValueError(f"Cannot save {filename}: contains {nan_count} NaN values")

    data.rio.to_raster(filename, driver="COG", dtype="float32", compress="lzw")
    log.info("Saved %s", filename.name)
