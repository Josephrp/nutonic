import logging
from collections import defaultdict
from pathlib import Path

import numpy as np
import stackstac
import xarray as xr
import zarr
from pystac import ItemCollection
from tqdm import tqdm

from terramind_ad.stac import fill_nans

log = logging.getLogger(__name__)


def create_stack(
    items: ItemCollection,
    bands: list[str],
    bbox_wgs: np.ndarray,
    epsg: int,
    resolution: int = 10,
    chunksize: int = 512,
) -> xr.DataArray:
    """Create stacked xarray from STAC items."""
    return stackstac.stack(
        items,
        assets=bands,
        resolution=resolution,
        bounds_latlon=bbox_wgs,  # type: ignore
        epsg=epsg,
        chunksize=chunksize,
        xy_coords="center",  # use center of pixel for coordinates
        properties=False,  # don't include item properties as coordinates
        band_coords=True,  # enable common_name mapping for readable band labels
    )


def _write_timestep_to_zarr(
    mosaic: xr.DataArray,
    timestamp: str,
    output_path: Path,
    fill_gaps: bool,
    mode: str = "a",
) -> None:
    """Write a single timestep to Zarr store incrementally."""
    if fill_gaps and np.isnan(mosaic.values).any():
        log.debug("Filling NaNs in timestep %s", timestamp)
        mosaic.values[:] = fill_nans(mosaic.values)

    mosaic = mosaic.expand_dims(time=[timestamp])

    coords_to_keep = {"time", "band", "x", "y"}
    coords_to_drop = [c for c in mosaic.coords if c not in coords_to_keep]
    if coords_to_drop:
        mosaic = mosaic.drop_vars(coords_to_drop)
    mosaic.attrs = {}

    # always rename to "data" for consistency (stackstac generates hash-based names)
    mosaic = mosaic.rename("data")

    # convert to dataset to ensure proper encoding
    ds = mosaic.to_dataset()

    if mode == "w":
        _, C, H, W = mosaic.shape
        chunk_size = {"time": 1, "band": C, "y": min(512, H), "x": min(512, W)}
        ds = ds.chunk(chunk_size)
        # use zarr_version=2 for better xarray compatibility
        ds.to_zarr(output_path, mode="w", consolidated=False, zarr_version=2)
    else:
        ds.to_zarr(output_path, mode="a", append_dim="time", consolidated=False)


def process_timeseries(
    stack: xr.DataArray,
    output_path: Path,
    temporal_agg: str = "daily",
    sort_by_cloud: bool = False,
    fill_gaps: bool = True,
) -> None:
    """Process stack into Zarr time series with incremental writes to avoid memory issues."""
    log.info("Processing time series with temporal aggregation: %s", temporal_agg)

    if temporal_agg not in ("none", "daily", "monthly"):
        raise ValueError(f"Unknown temporal aggregation: {temporal_agg}")

    group_by = "time.date" if temporal_agg in ("daily", "none") else "time.month"

    first_write = True
    for key, group_data in tqdm(stack.groupby(group_by), desc=f"Processing {temporal_agg}"):
        try:
            if sort_by_cloud and "eo:cloud_cover" in group_data.coords:
                group_data = group_data.sortby("eo:cloud_cover", ascending=False)

            mosaic = stackstac.mosaic(group_data, dim="time").compute()
            if group_by == "time.date":
                timestamp = str(key)
            else:
                year = int(group_data.time.values[0].astype("datetime64[Y]").astype(int) + 1970)
                timestamp = f"{year}-{int(key):02d}-15"

            mode = "w" if first_write else "a"
            _write_timestep_to_zarr(mosaic, timestamp, output_path, fill_gaps, mode)
            first_write = False

        except Exception as e:
            log.warning("Failed to process %s: %s", key, e)

    zarr.consolidate_metadata(output_path)
    log.info("Saved Zarr time series: %s", output_path)


def write_median_composite(input_zarr: Path, output_zarr: Path, interval_months: int = 3) -> None:
    """Create rolling temporal median composites from Zarr time series with incremental writes."""
    timeseries = xr.open_zarr(input_zarr, consolidated=True)
    data = timeseries[list(timeseries.data_vars)[0]]

    log.info("Loaded time series with %d timesteps", len(data.time))

    monthly_groups: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(data.time.values):
        year_month = "-".join(str(ts).split("-")[:2])
        monthly_groups[year_month].append(i)

    sorted_months = sorted(monthly_groups.keys())
    log.info("Grouped into %d months", len(sorted_months))

    first_write = True
    n_written = 0

    for i in tqdm(range(len(sorted_months)), desc="Creating median composites"):
        window_indices = []
        for j in range(max(0, i - interval_months // 2), min(len(sorted_months), i + interval_months // 2 + 1)):
            window_indices.extend(monthly_groups[sorted_months[j]])

        if len(window_indices) < interval_months // 2:
            log.warning("Not enough data for %s, skipping", sorted_months[i])
            continue

        try:
            median = data.isel(time=window_indices).median(dim="time").compute()
            timestamp = f"{sorted_months[i]}-15"

            mode = "w" if first_write else "a"
            _write_timestep_to_zarr(median, timestamp, output_zarr, fill_gaps=False, mode=mode)
            first_write = False
            n_written += 1

        except Exception as e:
            log.warning("Failed to create median for %s: %s", sorted_months[i], e)

    zarr.consolidate_metadata(output_zarr)
    log.info("Created temporal median composites with %d timesteps", n_written)
