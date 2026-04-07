"""Convert time series of GeoTIFF files to Zarr format."""

import json
import logging
from pathlib import Path

import rioxarray as rxr
import xarray as xr
from argdantic import ArgField, ArgParser

from terramind_ad.data import SitesConfig
from terramind_ad.zarr import save_timeseries

log = logging.getLogger("convert")
cli = ArgParser(description="Convert GeoTIFF time series to Zarr")


@cli.command()
def tif_to_zarr(
    site_id: str = ArgField(description="Site ID to process"),
    data_dir: Path = ArgField(default=Path("data"), description="Data directory"),
    sensor: str = ArgField(default="s2", description="Sensor type (s2 or s1)"),
) -> None:
    """
    Convert a time series of GeoTIFF files to a single Zarr dataset.

    Reads all *.tif files from the images directory and consolidates them
    into a single Zarr store with proper xarray dimensions and coordinates.

    Examples:
        # convert S2 images to Zarr
        uv run python tools/convert.py tif-to-zarr --site-id libya_floods_2023

        # convert S1 data
        uv run python tools/convert.py tif-to-zarr --site-id libya_floods_2023 --sensor s1
    """
    log.setLevel(logging.INFO)

    # load site config
    config_path = Path("resources/events.json")
    with config_path.open() as f:
        config = SitesConfig(**json.load(f))
    site = next((s for s in config.sites if s.id == site_id), None)
    if not site:
        raise ValueError(f"Site {site_id} not found")

    log.info("Site: %s, Event: %s", site.name, site.event_date)

    # find all TIF files
    tif_dir = data_dir / site_id / "images" / sensor
    tif_files = sorted(tif_dir.glob("*.tif"))
    if not tif_files:
        raise FileNotFoundError(f"No *.tif files in {tif_dir}")

    log.info("Found %d TIF files", len(tif_files))

    # load all files as xarray DataArrays
    data_arrays = []
    timestamps = []
    for tif_path in tif_files:
        # extract timestamp from filename: "2023-01-05.tif" -> "2023-01-05"
        timestamp_str = tif_path.stem
        timestamps.append(timestamp_str)

        # load with rioxarray (preserves CRS and spatial metadata)
        da = rxr.open_rasterio(tif_path, chunks={"x": 512, "y": 512})
        data_arrays.append(da)

    # concatenate along time dimension
    timeseries = xr.concat(data_arrays, dim="time")
    timeseries = timeseries.assign_coords(time=("time", timestamps))

    log.info("Timeseries shape: %s", timeseries.shape)
    log.info("Dimensions: %s", timeseries.dims)

    # save as Zarr using the standard save_timeseries function
    output_path = tif_dir / "timeseries.zarr"
    save_timeseries(timeseries, output_path)

    log.info("Conversion complete: %s", output_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    cli()
