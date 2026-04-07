import datetime
import logging
from collections import defaultdict
from pathlib import Path

import numpy as np
import xarray as xr
from argdantic import ArgField, ArgParser
from dask.distributed import Client, LocalCluster
from pystac import ItemCollection

from terramind_ad.data import DisasterSite, SitesConfig
from terramind_ad.processing import create_stack, process_timeseries, write_median_composite
from terramind_ad.stac import create_client, get_bbox

log = logging.getLogger("download")
cli = ArgParser(description="Download Sentinel time series for disaster change detection")

# sensor configurations
S2_BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]
S1_BANDS = ["vv", "vh"]

# sentinel-2 baseline change cutoff
S2_BASELINE_CUTOFF = datetime.datetime(2022, 1, 25, tzinfo=datetime.timezone.utc)
S2_BASELINE_OFFSET = 1000


def harmonize_s2_baseline(stack: xr.DataArray) -> xr.DataArray:
    """Apply Sentinel-2 baseline harmonization for post-2022 data.

    Data after 2022-01-25 has a +1000 offset that needs to be removed.
    See: https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a#Baseline-Change
    """
    # find timestamps after the cutoff
    post_cutoff_mask = stack.time >= np.datetime64(S2_BASELINE_CUTOFF)

    if not post_cutoff_mask.any():
        log.info("No data after baseline cutoff, skipping harmonization")
        return stack

    n_affected = post_cutoff_mask.sum().item()
    log.info("Harmonizing %d timesteps after %s", n_affected, S2_BASELINE_CUTOFF.date())

    # apply offset correction: clip to offset minimum, then subtract offset
    stack_harmonized = stack.where(~post_cutoff_mask, stack.clip(min=S2_BASELINE_OFFSET) - S2_BASELINE_OFFSET)

    return stack_harmonized


def load_sites(config: Path, site_id: str | None = None) -> list[DisasterSite]:
    """Load disaster sites from config, optionally filtering by ID."""
    if not config.exists():
        raise FileNotFoundError(f"Config file not found: {config}")

    sites_config = SitesConfig.model_validate_json(config.read_text())
    sites = sites_config.sites

    if site_id:
        sites = [s for s in sites if s.id == site_id]
        if not sites:
            raise ValueError(f"Site '{site_id}' not found in config")

    return sites


def print_dry_run_stats(
    site: DisasterSite,
    items: ItemCollection,
    individual: bool,
    has_cloud_info: bool = False,
) -> None:
    """Print statistics for dry run mode."""
    log.info("\n%s", "=" * 60)
    log.info("Site: %s (%s)", site.name, site.id)
    log.info("  Event: %s on %s", site.event_type, site.event_date)
    log.info("  Period: %s to %s", site.historical_start, site.historical_end)
    log.info("  EPSG: %s", site.epsg)
    log.info("  Bbox (WGS84): %s", get_bbox(site).tolist())

    by_date: dict[str, list] = defaultdict(list)
    by_month: dict[tuple[int, int], list] = defaultdict(list)
    cloud_covers: list[float] = []

    for item in items:
        dt = item.datetime
        assert dt is not None, f"item {item} has no datetime"
        cc = item.properties.get("eo:cloud_cover") if has_cloud_info else None
        if cc is not None:
            cloud_covers.append(cc)
        by_date[str(dt.date())].append(cc)
        by_month[(dt.year, dt.month)].append(cc)

    log.info("\n  Total images: %d", len(items))
    log.info("  Unique dates: %d", len(by_date))
    log.info("  Unique months: %d", len(by_month))

    if cloud_covers:
        avg_cc = sum(cloud_covers) / len(cloud_covers)
        log.info("  Cloud cover: min=%.1f%%, max=%.1f%%, avg=%.1f%%", min(cloud_covers), max(cloud_covers), avg_cc)

    log.info("\n  Monthly distribution:")
    for (year, month), ccs in sorted(by_month.items()):
        if has_cloud_info:
            valid_ccs = [c for c in ccs if c is not None]
            avg = sum(valid_ccs) / len(valid_ccs) if valid_ccs else 0
            log.info("    %d-%02d: %d images (avg cloud: %.1f%%)", year, month, len(ccs), avg)
        else:
            log.info("    %d-%02d: %d images", year, month, len(ccs))

    output_type = "--individual" if individual else "monthly composite"
    output_count = len(by_date) if individual else len(by_month)
    log.info("\n  Output (%s): %d files", output_type, output_count)


@cli.command()
def sentinel2(
    config: Path = ArgField(default=Path("resources/events.json"), description="Path to disaster sites config"),
    output_dir: Path = ArgField("-o", default=Path("data"), description="Output directory"),
    site_id: str | None = ArgField("-s", default=None, description="Process only this site ID"),
    bands: list[str] | None = ArgField("-b", default=None, description="Bands to download"),
    cloud_cover: int = ArgField("-c", default=25, description="Maximum cloud cover percentage"),
    resolution: int = ArgField("-r", default=10, description="Output resolution in meters"),
    temporal_agg: str = ArgField("-t", default="daily", description="Temporal aggregation: daily, monthly, or none"),
    skip_existing: bool = ArgField(default=True, description="Skip existing files"),
    n_workers: int = ArgField(default=8, description="Number of Dask workers"),
    test: bool = ArgField(default=False, description="Test mode: limit to first 10 timesteps"),
    dry_run: bool = ArgField(default=False, description="Only show image counts, don't download"),
) -> None:
    """Download Sentinel-2 L2A images for disaster sites as Zarr time series."""
    log.setLevel(logging.INFO)
    bands = bands or S2_BANDS

    if temporal_agg not in ("daily", "monthly", "none"):
        raise ValueError(f"Invalid temporal_agg: {temporal_agg}, must be 'daily', 'monthly', or 'none'")

    sites = load_sites(config, site_id)
    log.info("Processing %d site(s) with Sentinel-2 L2A", len(sites))
    log.info("Bands: %s, Cloud cover < %d%%, Temporal agg: %s", bands, cloud_cover, temporal_agg)

    stac = create_client()

    if dry_run:
        for site in sites:
            bbox_wgs = get_bbox(site)
            search = stac.search(
                bbox=bbox_wgs.tolist(),
                datetime=f"{site.historical_start}/{site.historical_end}",
                collections=["sentinel-2-l2a"],
                query={"eo:cloud_cover": {"lt": cloud_cover}},
            )
            print_dry_run_stats(site, search.item_collection(), temporal_agg == "daily", has_cloud_info=True)
        log.info("\n%s", "=" * 60)
        return

    with LocalCluster(n_workers=n_workers) as cluster, Client(cluster):
        for site in sites:
            log.info("Processing %s (%s)", site.name, site.id)
            site_dir = output_dir / site.id / "images" / "s2"
            site_dir.mkdir(exist_ok=True, parents=True)

            output_path = site_dir / "timeseries.zarr"
            if skip_existing and output_path.exists():
                log.info("Output already exists, skipping: %s", output_path)
                continue

            bbox_wgs = get_bbox(site)

            search = stac.search(
                bbox=bbox_wgs.tolist(),
                datetime=f"{site.historical_start}/{site.historical_end}",
                collections=["sentinel-2-l2a"],
                query={"eo:cloud_cover": {"lt": cloud_cover}},
            )
            items = search.item_collection()
            log.info("Found %d items for %s", len(items), site.id)

            if not items:
                log.warning("No items found for %s, skipping", site.id)
                continue

            stack = create_stack(items, bands, bbox_wgs, site.epsg, resolution)

            # apply baseline harmonization for post-2022 data
            stack = harmonize_s2_baseline(stack)

            # S2 uses 0 as nodata
            stack = stack.where(lambda x: x > 0, other=np.nan)
            # band dimension already uses common_name from stackstac when band_coords=True

            # limit timesteps in test mode
            if test:
                max_timesteps = 10
                stack = stack.isel(time=slice(0, min(max_timesteps, len(stack.time))))
                log.info("Test mode: limited to %d timesteps", len(stack.time))

            process_timeseries(stack, output_path, temporal_agg=temporal_agg, sort_by_cloud=True, fill_gaps=True)


@cli.command()
def sentinel1(
    config: Path = ArgField(default=Path("resources/events.json"), description="Path to disaster sites config"),
    output_dir: Path = ArgField("-o", default=Path("data"), description="Output directory"),
    site_id: str | None = ArgField("-s", default=None, description="Process only this site ID"),
    bands: list[str] | None = ArgField("-b", default=None, description="Bands to download"),
    resolution: int = ArgField("-r", default=10, description="Output resolution in meters"),
    temporal_agg: str = ArgField("-t", default="monthly", description="Temporal aggregation: daily, monthly, or none"),
    skip_existing: bool = ArgField(default=True, description="Skip existing files"),
    n_workers: int = ArgField(default=8, description="Number of Dask workers"),
    test: bool = ArgField(default=False, description="Test mode: limit to first 10 timesteps"),
    dry_run: bool = ArgField(default=False, description="Only show image counts, don't download"),
) -> None:
    """Download Sentinel-1 RTC images for disaster sites as Zarr time series."""
    log.setLevel(logging.INFO)
    bands = bands or S1_BANDS

    if temporal_agg not in ("daily", "monthly", "none"):
        raise ValueError(f"Invalid temporal_agg: {temporal_agg}, must be 'daily', 'monthly', or 'none'")

    sites = load_sites(config, site_id)
    log.info("Processing %d site(s) with Sentinel-1 RTC", len(sites))
    log.info("Bands: %s, Temporal agg: %s", bands, temporal_agg)

    stac = create_client()

    if dry_run:
        for site in sites:
            bbox_wgs = get_bbox(site)
            search = stac.search(
                bbox=bbox_wgs.tolist(),
                datetime=f"{site.historical_start}/{site.historical_end}",
                collections=["sentinel-1-rtc"],
            )
            print_dry_run_stats(site, search.item_collection(), temporal_agg == "daily", has_cloud_info=False)
        log.info("\n%s", "=" * 60)
        return

    with LocalCluster(n_workers=n_workers) as cluster, Client(cluster):
        for site in sites:
            log.info("Processing %s (%s)", site.name, site.id)
            site_dir = output_dir / site.id / "images" / "s1"
            site_dir.mkdir(exist_ok=True, parents=True)

            output_path = site_dir / "timeseries.zarr"
            if skip_existing and output_path.exists():
                log.info("Output already exists, skipping: %s", output_path)
                continue

            bbox_wgs = get_bbox(site)

            search = stac.search(
                bbox=bbox_wgs.tolist(),
                datetime=f"{site.historical_start}/{site.historical_end}",
                collections=["sentinel-1-rtc"],
            )
            items = search.item_collection()
            log.info("Found %d items for %s", len(items), site.id)

            if not items:
                log.warning("No items found for %s, skipping", site.id)
                continue

            stack = create_stack(items, bands, bbox_wgs, site.epsg, resolution)
            # limit timesteps in test mode
            if test:
                max_timesteps = 10
                stack = stack.isel(time=slice(0, min(max_timesteps, len(stack.time))))
                log.info("Test mode: limited to %d timesteps", len(stack.time))
            process_timeseries(stack, output_path, temporal_agg=temporal_agg, sort_by_cloud=False, fill_gaps=True)


@cli.command()
def composite(
    config: Path = ArgField(default=Path("resources/events.json"), description="Path to disaster sites config"),
    data_dir: Path = ArgField(default=Path("data"), description="Data directory"),
    site_id: str | None = ArgField("-s", default=None, description="Process only this site ID"),
    sensor: str = ArgField(default="s2", description="Sensor type: s2 or s1"),
    interval: int = ArgField("-i", default=3, description="Temporal window in months for median composite"),
    skip_existing: bool = ArgField(default=True, description="Skip existing files"),
) -> None:
    """Create temporal median composites from existing Zarr time series.

    Reads from: data/{site_id}/images/{sensor}/timeseries.zarr
    Writes to: data/{site_id}/images/{sensor}_median_{interval}m/timeseries.zarr

    Example:
        uv run python tools/download.py composite --site-id libya_floods_2023 --interval 3
    """
    log.setLevel(logging.INFO)

    sites = load_sites(config, site_id)
    log.info("Creating temporal median composites for %d site(s)", len(sites))
    log.info("Sensor: %s, Interval: %d months", sensor, interval)

    for site in sites:
        log.info("Processing %s (%s)", site.name, site.id)

        input_path = data_dir / site.id / "images" / sensor / "timeseries.zarr"
        output_dir = data_dir / site.id / "images" / f"{sensor}_median_{interval}m"
        output_dir.mkdir(exist_ok=True, parents=True)
        output_path = output_dir / "timeseries.zarr"

        if not input_path.exists():
            log.warning("Input Zarr not found: %s, skipping", input_path)
            continue

        if skip_existing and output_path.exists():
            log.info("Output already exists, skipping: %s", output_path)
            continue

        write_median_composite(input_path, output_path, interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="[%(asctime)s] %(levelname)s: %(message)s")
    cli()
