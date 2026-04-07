import logging
from pathlib import Path

import numpy as np
import xarray as xr
from argdantic import ArgField, ArgParser
from PIL import Image
from tqdm import tqdm

log = logging.getLogger("generate")
cli = ArgParser(description="TerraMind generation tools")

# Impact Observatory LULC color palette (0-9 class indices)
LULC_PALETTE = np.array(
    [
        [0, 0, 0],  # no data
        [65, 155, 223],  # Water
        [57, 125, 73],  # Trees
        [122, 135, 198],  # Flooded Vegetation
        [228, 150, 53],  # Crops
        [196, 40, 27],  # Built Area
        [165, 155, 143],  # Bare Ground
        [168, 235, 255],  # Snow/Ice
        [97, 97, 97],  # Clouds
        [227, 226, 195],  # Rangeland
    ],
    dtype=np.uint8,
)


def _lulc_to_rgb(lulc_map: np.ndarray) -> np.ndarray:
    """Convert LULC class indices to RGB image using Impact Observatory palette."""
    h, w = lulc_map.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for class_id in range(len(LULC_PALETTE)):
        mask = lulc_map == class_id
        rgb[mask] = LULC_PALETTE[class_id]
    return rgb


@cli.command()
def lulc(
    site_id: str = ArgField(description="site ID to process"),
    data_dir: Path = ArgField(default=Path("data"), description="data directory"),
    sensor_dir: str = ArgField(default="s2", description="sensor subdirectory (default: 's2')"),
    tile_size: int = ArgField(default=224, description="tile size for tiled inference"),
    overlap: int = ArgField(default=112, description="overlap in pixels for tiled inference"),
    batch_size: int = ArgField(default=8, description="batch size for inference"),
    device: str = ArgField(default="cuda", description="device for inference"),
) -> None:
    """Generate LULC maps from Zarr time series using TerraMind.

    Examples:
        # generate LULC for all S2 images
        uv run python tools/generate.py lulc --site-id libya_floods_2023

        # use median composites
        uv run python tools/generate.py lulc --site-id libya_floods_2023 --sensor-dir s2_median_3m
    """
    import torch
    from terratorch import FULL_MODEL_REGISTRY
    from torch.nn import functional as fn

    from terramind_ad.tiling import TiledPredictor

    log.setLevel(logging.INFO)

    # load Zarr time series
    zarr_path = data_dir / site_id / "images" / sensor_dir / "timeseries.zarr"
    if not zarr_path.exists():
        raise FileNotFoundError(f"Zarr not found: {zarr_path}")

    log.info("Loading time series from %s", zarr_path)
    ds = xr.open_zarr(zarr_path, consolidated=True)
    data = ds[list(ds.data_vars)[0]]
    timestamps = [str(t) for t in data.time.values]
    log.info("Found %d timesteps", len(timestamps))

    # setup output directory
    output_dir = data_dir / site_id / "generated" / sensor_dir / "lulc"
    output_dir.mkdir(exist_ok=True, parents=True)
    log.info("Outputs will be saved to: %s", output_dir)

    # load generation model
    log.info("Loading terramind generation model...")
    model = FULL_MODEL_REGISTRY.build(
        "terramind_v1_base_generate",
        modalities=["S2L2A"],
        output_modalities=["LULC"],
        pretrained=True,
        standardize=True,
    )
    model = model.to(device)  # type: ignore
    model.eval()

    # create tiled predictor
    predictor = TiledPredictor(
        tile_size=tile_size,
        overlap=overlap,
        batch_size=batch_size,
        downsample_factor=16,
        device=device,
    )
    log.info("Using tiled predictor: tile_size=%d, overlap=%d, batch_size=%d", tile_size, overlap, batch_size)

    # collect all LULC logits
    all_lulc_logits = []

    # process each timestep
    for t_idx in tqdm(range(len(timestamps)), desc="Generating LULC"):
        # load image for this timestep
        img = data.isel(time=t_idx).values  # (C, H, W)
        inputs = {"S2L2A": torch.from_numpy(img).float().to(device)}

        # define prediction function for tiled inference
        def predict_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
            with torch.no_grad():
                generated = model(batch["S2L2A"])
            # return LULC logits (B, num_classes, patch_h, patch_w)
            return fn.interpolate(
                generated["LULC"],
                size=(tile_size // 16, tile_size // 16),
                mode="bilinear",
            )

        # run tiled inference
        lulc_logits = predictor(inputs, predict_fn)  # type: ignore (num_classes, H, W)
        all_lulc_logits.append(lulc_logits.detach().cpu().numpy())

    # stack all logits along time dimension
    lulc_timeseries = np.stack(all_lulc_logits, axis=0)  # (T, C, H, W)
    log.info("LULC time series shape: %s", lulc_timeseries.shape)

    # save as NPZ (compressed)
    output_path = output_dir / "lulc_logits.npz"
    np.savez_compressed(
        output_path,
        logits=lulc_timeseries,
        timestamps=np.array(timestamps, dtype="S10"),
    )
    log.info("Saved LULC logits to %s", output_path)


@cli.command()
def visualize(
    site_id: str = ArgField(description="site ID to process"),
    data_dir: Path = ArgField(default=Path("data"), description="data directory"),
    sensor_dir: str = ArgField(default="s2", description="sensor subdirectory (default: 's2')"),
) -> None:
    """Generate RGB PCA visualizations from LULC logits.

    Examples:
        # visualize LULC logits
        uv run python tools/generate.py visualize --site-id libya_floods_2023

        # visualize median composite LULC
        uv run python tools/generate.py visualize --site-id libya_floods_2023 --sensor-dir s2_median_3m
    """
    from sklearn.decomposition import PCA

    from terramind_ad.visualization import l2_normalize, percentile_clip_scale

    log.setLevel(logging.INFO)

    # locate npz file
    lulc_dir = data_dir / site_id / "generated" / sensor_dir / "lulc"
    npz_path = lulc_dir / "lulc_logits.npz"

    if not npz_path.exists():
        raise FileNotFoundError(f"LULC logits not found: {npz_path}")

    log.info("Loading LULC logits from %s", npz_path)
    data = np.load(npz_path)
    logits = data["logits"]  # (T, C, H, W)
    timestamps = data["timestamps"]
    timestamps = [ts.decode("utf-8") for ts in timestamps]

    T, C, H, W = logits.shape
    log.info("Loaded logits: %s, timesteps: %d", logits.shape, T)

    # collect all samples for PCA fitting
    log.info("Preparing samples for PCA fitting...")
    all_samples = logits.transpose(0, 2, 3, 1).reshape(-1, C)  # (T*H*W, C)

    # l2 normalize to prevent magnitude outliers
    log.info("L2 normalizing logits...")
    all_samples = l2_normalize(all_samples, axis=-1)

    # fit PCA
    log.info("Fitting PCA...")
    pca = PCA(n_components=3)
    pca.fit(all_samples)
    log.info("PCA explained variance: %s", pca.explained_variance_ratio_)

    # transform each timestep to RGB
    log.info("Creating RGB visualizations...")
    for t in tqdm(range(T), desc="Generating PNGs"):
        timestamp = timestamps[t]
        logits_t = logits[t]  # (C, H, W)

        # reshape and transform
        logits_flat = logits_t.transpose(1, 2, 0).reshape(-1, C)  # (H*W, C)
        logits_flat = l2_normalize(logits_flat, axis=-1)
        rgb_flat = pca.transform(logits_flat)  # (H*W, 3)
        rgb_flat = percentile_clip_scale(rgb_flat, lower=2.0, upper=98.0)

        # reshape and save
        rgb = rgb_flat.reshape(H, W, 3)
        rgb_uint8 = (rgb * 255).astype(np.uint8)

        png_path = lulc_dir / f"{timestamp}_lulc_pca.png"
        img = Image.fromarray(rgb_uint8)
        img.resize(size=(H * 5, W * 5), resample=Image.Resampling.NEAREST).save(png_path)

    log.info("Saved %d PCA visualizations to %s", T, lulc_dir)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
    )
    cli()
