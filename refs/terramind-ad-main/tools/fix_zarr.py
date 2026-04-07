"""Fix existing Zarr files to add dimension_names metadata for xarray compatibility."""

import json
import logging
from pathlib import Path

import zarr
from argdantic import ArgField, ArgParser

log = logging.getLogger("fix_zarr")
cli = ArgParser(description="Fix Zarr files with missing dimension_names metadata")


def add_dimension_names_to_zarr_json(zarr_json_path: Path, dims: list[str]) -> bool:
    """Add dimension_names field to Zarr v3 JSON metadata file.

    Returns True if the file was modified, False if already had dimension_names.
    """
    with open(zarr_json_path) as f:
        metadata = json.load(f)
    if "dimension_names" in metadata:
        return False
    metadata["dimension_names"] = dims
    with open(zarr_json_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return True


@cli.command()
def fix(
    zarr_path: Path = ArgField("-z", description="Path to Zarr store to fix"),
    dry_run: bool = ArgField(default=False, description="Show what would be changed without modifying"),
    rename_to_data: bool = ArgField(default=False, description="Rename main variable to 'data'"),
    dims: str | None = ArgField(default=None, description="Comma-separated dimension names (auto-infer if not provided)"),
) -> None:
    """Add _ARRAY_DIMENSIONS metadata to Zarr stores for xarray compatibility.

    This fixes the error: 'Zarr object is missing the dimension_names metadata'
    """
    log.setLevel(logging.INFO)

    if not zarr_path.exists():
        raise FileNotFoundError(f"Zarr path not found: {zarr_path}")

    # open zarr group
    root = zarr.open_group(str(zarr_path), mode="r+" if not dry_run else "r")
    # find data variable (first array that's not a coordinate or timestamps)
    data_var_name = None
    for name in root.array_keys():
        if name not in ("time", "band", "x", "y", "timestamps"):
            data_var_name = name
            break

    if not data_var_name:
        log.error("No data variable found in Zarr store")
        return

    data_array = root[data_var_name]
    log.info("Found data variable: %s with shape %s", data_var_name, data_array.shape)

    # check if dimension names already exist on data variable
    dims_exist = "_ARRAY_DIMENSIONS" in data_array.attrs
    needs_rename = rename_to_data and data_var_name != "data"

    # check if coordinates have dimension metadata
    coord_names = ["time", "band", "x", "y"]
    coords_need_fix = []
    for coord_name in coord_names:
        if coord_name in root and "_ARRAY_DIMENSIONS" not in root[coord_name].attrs:
            coords_need_fix.append(coord_name)

    # for Zarr v3, check if JSON files have dimension_names
    json_needs_fix = False
    data_json = zarr_path / data_var_name / "zarr.json"
    if data_json.exists():
        with open(data_json) as f:
            if "dimension_names" not in json.load(f):
                json_needs_fix = True

    if dims_exist and not needs_rename and not coords_need_fix and not json_needs_fix:
        log.info(
            "Zarr store is already fixed (dims=%s, name=%s)", data_array.attrs["_ARRAY_DIMENSIONS"], data_var_name
        )
        return

    # parse or infer dimensions from shape
    if dims:
        # use user-provided dimensions
        dim_list = [d.strip() for d in dims.split(",")]
    else:
        # infer dimensions from shape
        # for image timeseries: (T, C, H, W) -> ["time", "band", "y", "x"]
        # for feature timeseries: (T, H, W, C) -> ["time", "y", "x", "features"]
        ndim = len(data_array.shape)
        if ndim == 4:
            # check if this looks like features (has "band" coordinate = not feature store)
            if "band" in root:
                dim_list = ["time", "band", "y", "x"]
            else:
                dim_list = ["time", "y", "x", "features"]
        elif ndim == 3:
            dim_list = ["time", "y", "x"]
        else:
            log.error("Unexpected number of dimensions: %d. Use --dims to specify manually.", ndim)
            return

    if dry_run:
        actions = []
        if not dims_exist:
            actions.append(f"add _ARRAY_DIMENSIONS={dim_list}")
        if needs_rename:
            actions.append(f"rename '{data_var_name}' -> 'data'")
        if coords_need_fix:
            actions.append(f"fix coordinates: {coords_need_fix}")
        log.info("[DRY RUN] Would: %s", ", ".join(actions))
    else:
        if not dims_exist:
            log.info("Adding dimension names: %s", dim_list)
            data_array.attrs["_ARRAY_DIMENSIONS"] = dim_list

        if needs_rename:
            log.info("Renaming variable '%s' -> 'data'", data_var_name)
            # copy array with new name (let zarr use default compression)
            old_array = root[data_var_name]
            fill_value = getattr(old_array.metadata, "fill_value", 0)

            new_array = root.create_array(
                "data",
                shape=old_array.shape,
                chunks=old_array.chunks,
                dtype=old_array.dtype,
                fill_value=fill_value,
            )
            new_array[:] = old_array[:]
            new_array.attrs.update(old_array.attrs)
            new_array.attrs["_ARRAY_DIMENSIONS"] = dim_list
            del root[data_var_name]

        # fix coordinate arrays - each coordinate is a 1D array with dimension = its own name
        for coord_name in coords_need_fix:
            log.info("Adding _ARRAY_DIMENSIONS to coordinate: %s", coord_name)
            root[coord_name].attrs["_ARRAY_DIMENSIONS"] = [coord_name]

        # for Zarr v3, also add dimension_names to the JSON metadata files
        # use the final name (after potential rename)
        final_data_name = "data" if needs_rename else data_var_name
        data_json = zarr_path / final_data_name / "zarr.json"
        if data_json.exists():
            log.info("Detected Zarr v3 format, updating JSON metadata files")
            if add_dimension_names_to_zarr_json(data_json, dim_list):
                log.info("Added dimension_names to %s/zarr.json", final_data_name)

            for coord_name in coord_names:
                coord_json = zarr_path / coord_name / "zarr.json"
                if coord_json.exists():
                    if add_dimension_names_to_zarr_json(coord_json, [coord_name]):
                        log.info("Added dimension_names to %s/zarr.json", coord_name)

        zarr.consolidate_metadata(zarr_path)
        log.info("Fixed %s and consolidated metadata", zarr_path)


@cli.command()
def fix_bands(
    zarr_path: Path = ArgField("-z", description="Path to Zarr store to fix"),
    dry_run: bool = ArgField(default=False, description="Show what would be changed without modifying"),
) -> None:
    """Fix duplicate/invalid band names by replacing with original Sentinel-2 band IDs.

    Replaces stackstac's common_name mapping with the original asset keys (B01-B12).
    """
    log.setLevel(logging.INFO)

    if not zarr_path.exists():
        raise FileNotFoundError(f"Zarr path not found: {zarr_path}")

    # sentinel-2 band mapping (order matters - must match the 12 bands in timeseries)
    s2_bands = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"]

    root = zarr.open_group(str(zarr_path), mode="r+" if not dry_run else "r")

    if "band" not in root:
        log.error("No 'band' coordinate found in Zarr store")
        return

    band_arr = root["band"]
    current_bands = [str(b) for b in band_arr[:]]
    log.info("Current band names: %s", current_bands)

    if len(current_bands) != len(s2_bands):
        log.error(
            "Expected %d bands for Sentinel-2, found %d. Cannot auto-fix.", len(s2_bands), len(current_bands)
        )
        return

    if dry_run:
        log.info("[DRY RUN] Would replace band names with: %s", s2_bands)
    else:
        log.info("Replacing band names with: %s", s2_bands)
        band_arr[:] = s2_bands

        zarr.consolidate_metadata(zarr_path)
        log.info("Fixed band names in %s", zarr_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="[%(asctime)s] %(levelname)s: %(message)s")
    cli()
