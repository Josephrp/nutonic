import logging
from pathlib import Path

import numpy as np
import xarray as xr
from argdantic import ArgField, ArgParser

log = logging.getLogger("infer")
cli = ArgParser(description="TerraMind inference tools")

variants = {
    "base": 768,
    "base_tim": 768,
    "large": 1024,
    "large_tim": 1024,
}


@cli.command()
def features(
    site_id: str = ArgField(description="Site ID to process"),
    data_dir: Path = ArgField(default=Path("data"), description="Data directory"),
    sensor_dirs: list[str] = ArgField(description="Sensor subdirectories (e.g., 's2' or 's2 s1' for fusion)"),
    model_name: str = ArgField(default="terramind_v1_base", description="TerraMind model name"),
    tile_size: int = ArgField(default=224, description="Tile size for tiled inference"),
    overlap: int = ArgField(default=112, description="Overlap in pixels for tiled inference"),
    tim_modalities: list[str] = ArgField(default=None, description="Additional modalities to generate via TiM"),
    batch_size: int = ArgField(default=32, description="Batch size for inference"),
    device: str = ArgField(default="cuda", description="Device for inference"),
) -> None:
    """Extract TerraMind embeddings from Zarr time series.

    Uses overlapping tiled inference for memory-efficient processing of large images.

    Examples:
        # S2 only
        uv run python tools/infer.py features --site-id libya_floods_2023 --sensor-dirs s2

        # S2 + S1 fusion
        uv run python tools/infer.py features --site-id libya_floods_2023 --sensor-dirs s2 s1

        # median composites with fusion
        uv run python tools/infer.py features --site-id libya_floods_2023 --sensor-dirs s2_median_3m s1_median_3m
    """
    import torch
    from terratorch.registry import BACKBONE_REGISTRY
    from tqdm import tqdm

    from terramind_ad.tiling import TiledPredictor
    from terramind_ad.zarr import save_features

    log.setLevel(logging.INFO)

    model_variant = model_name.replace("terramind_v1_", "")
    assert model_variant in variants, f"Unknown model variant: {model_variant}"
    feat_dims = variants[model_variant]
    uses_tim = "tim" in model_name

    # detect modalities and map to TerraMind keys
    sensor_modalities = {}
    for sensor_dir in sensor_dirs:
        # extract base modality (s2 or s1) from sensor_dir
        if "s2" in sensor_dir:
            sensor_modalities[sensor_dir] = "S2L2A"
        elif "s1" in sensor_dir:
            sensor_modalities[sensor_dir] = "S1GRD"
        else:
            raise ValueError(f"Unknown modality in {sensor_dir}, must contain 's2' or 's1'")

    log.info("Processing %d modalities: %s", len(sensor_dirs), list(sensor_modalities.values()))

    # load Zarr time series for each modality
    modality_data = {}
    timestamps = None

    for sensor_dir in sensor_dirs:
        zarr_path = data_dir / site_id / "images" / sensor_dir / "timeseries.zarr"
        if not zarr_path.exists():
            raise FileNotFoundError(f"Zarr not found: {zarr_path}")

        log.info("Loading %s from %s", sensor_dir, zarr_path)
        ds = xr.open_zarr(zarr_path, consolidated=True)
        data = ds[list(ds.data_vars)[0]]
        modality_data[sensor_dir] = data
        # extract timestamps from first modality
        if timestamps is None:
            timestamps = [str(t) for t in data.time.values]

    # verify all modalities have same timestamps
    for sensor_dir, data in modality_data.items():
        ts = [str(t) for t in data.time.values]
        if ts != timestamps:
            raise ValueError(f"{sensor_dir} has different timestamps")
    log.info("Found %d common timesteps", len(timestamps))  # type: ignore

    # setup output directory
    if uses_tim and tim_modalities:
        sensor_dirs += [f"{m}_tim" for m in tim_modalities]
    sensor_combo = "+".join(sensor_dirs)
    features_dir = data_dir / site_id / "features" / sensor_combo
    features_dir.mkdir(exist_ok=True, parents=True)
    log.info("Features will be saved to: %s", features_dir)

    # load model with required modalities
    required_modalities = list(set(sensor_modalities.values()))
    log.info("Loading model %s with modalities: %s...", model_name, required_modalities)
    model_params = dict(pretrained=True, modalities=required_modalities)
    if uses_tim:
        log.info("Adding TiM modalities: %s", tim_modalities)
        model_params.update(tim_modalities=[t.upper() for t in tim_modalities])
    model = BACKBONE_REGISTRY.build(model_name, **model_params)
    model = model.to(device)  # type: ignore
    model.eval()

    # TerraMind uses patch_size=16, so downsample_factor=16
    predictor = TiledPredictor(
        tile_size=tile_size,
        overlap=overlap,
        batch_size=batch_size,
        downsample_factor=16,
        device=device,
    )
    log.info("Using tiled predictor: tile_size=%d, overlap=%d, batch_size=%d", tile_size, overlap, batch_size)

    # process each timestamp
    all_features = []

    for t_idx, timestamp in enumerate(tqdm(timestamps, desc="Processing timestamps")):
        # load all modalities for this timestamp
        inputs = {}
        for sensor_dir, data in modality_data.items():
            # extract (band, y, x) array for this timestep
            img = data.isel(time=t_idx).values  # (band, y, x)
            inputs[sensor_modalities[sensor_dir]] = torch.from_numpy(img).float().to(device)

        # get reference shape from first modality
        ref_array = next(iter(inputs.values()))
        h_in, w_in = ref_array.shape[-2:]
        h_feat, w_feat = h_in // 16, w_in // 16

        def predict_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
            outputs = model(batch)
            out = outputs[-1].reshape(-1, tile_size // 16, tile_size // 16, feat_dims)
            # requires (B, C, H, W)
            return out.permute(0, 3, 1, 2)

        with torch.no_grad():
            embeddings = predictor(inputs, predict_fn)

        # convert to (H, W, D) format
        features_grid = embeddings.permute(1, 2, 0).cpu().numpy()

        # validation
        assert np.sum(np.isnan(features_grid)) == 0, f"{timestamp} features contain NaNs!"
        assert features_grid.shape[-1] == feat_dims, f"Expected {feat_dims} dims, got {features_grid.shape[-1]}"
        assert features_grid.shape[:2] == (
            h_feat,
            w_feat,
        ), f"Expected shape ({h_feat}, {w_feat}), got {features_grid.shape[:2]}"

        all_features.append(features_grid)

    # stack all features into (T, H, W, D) array
    features_array = np.stack(all_features, axis=0)
    log.info("Stacked features: %s", features_array.shape)

    # save as Zarr
    output_path = features_dir / "features.zarr"
    metadata = {
        "tile_size": tile_size,
        "overlap": overlap,
        "modalities": list(sensor_modalities.values()),
        "sensor_dirs": sensor_dirs,
        "model_name": model_name,
    }
    save_features(features_array, timestamps, output_path, metadata=metadata)  # type: ignore


@cli.command()
def visualize(
    site_id: str = ArgField(description="Site ID to process"),
    features_subdir: str = ArgField(description="Features subdirectory name (e.g., 's2', 's2+s1', 's2_median_3m')"),
    data_dir: Path = ArgField(default=Path("data"), description="Data directory"),
) -> None:
    """Generate RGB PCA visualizations from pre-computed PC3 features.

    Prerequisites:
        Run PCA preprocessing first to generate PC3 file:
        uv run python tools/infer.py pca --site-id <site> --features-subdir s2 --n-components 3

    Examples:
        # visualize S2 unimodal features
        uv run python tools/infer.py visualize --site-id libya_floods_2023 --features-subdir s2

        # visualize S2+S1 multimodal features
        uv run python tools/infer.py visualize --site-id libya_floods_2023 --features-subdir s2+s1
    """
    import numpy as np
    from PIL import Image
    from tqdm import tqdm

    from terramind_ad.visualization import percentile_clip_scale
    from terramind_ad.zarr import load_features

    log.setLevel(logging.INFO)

    # load PC3 features
    features_path = data_dir / site_id / "features" / features_subdir / "features_pc3.zarr"
    if not features_path.exists():
        raise FileNotFoundError(
            f"PC3 file not found: {features_path}\n"
            f"Run PCA preprocessing first: uv run python tools/infer.py pca --site-id {site_id} --features-subdir {features_subdir} --n-components 3"
        )

    log.info("Loading PC3 features from %s", features_path)
    features, timestamps, metadata = load_features(features_path)
    log.info("Loaded PC3 features: %s, timesteps: %d", features.shape, len(timestamps))

    # verify shape
    T, H, W, D = features.shape
    assert D == 3, f"Expected 3 PC components for RGB visualization, got {D}"

    # setup output directory
    vis_dir = data_dir / site_id / "visualizations" / features_subdir
    vis_dir.mkdir(exist_ok=True, parents=True)
    log.info("Visualizations will be saved to: %s", vis_dir)

    # transform each timestep to RGB
    log.info("Creating RGB visualizations...")
    for t in tqdm(range(T), desc="Creating visualizations"):
        timestamp = timestamps[t]
        output_path = vis_dir / f"{timestamp}_pca.png"

        rgb = features[t]  # (H, W, 3)
        # percentile-based clipping and scaling
        rgb_flat = rgb.reshape(-1, 3)
        rgb_flat = percentile_clip_scale(rgb_flat, lower=2.0, upper=98.0)
        rgb = rgb_flat.reshape(H, W, 3)
        rgb_norm = (rgb * 255).astype(np.uint8)

        # save as PNG
        img = Image.fromarray(rgb_norm)
        img = img.resize(size=(img.width * 5, img.height * 5), resample=Image.Resampling.NEAREST)
        img.save(output_path)

    log.info("Saved %d visualizations to %s", T, vis_dir)


@cli.command()
def pca(
    site_id: str = ArgField(description="Site ID to process"),
    features_subdir: str = ArgField(description="Features subdirectory name (e.g., 's2', 's2+s1', 's2_median_3m')"),
    n_components: int = ArgField(default=1, description="Number of PCA components to extract"),
    data_dir: Path = ArgField(default=Path("data"), description="Data directory"),
    subsample: int = ArgField(default=None, description="Max samples for PCA fitting"),
    normalize: bool = ArgField(default=False, description="Apply z-score normalization to the samples"),
    skip_existing: bool = ArgField(default=True, description="Skip if output already exists"),
) -> None:
    """Apply PCA to TerraMind features and save reduced features.

    Output is saved as features_pcN.zarr where N is n_components.

    Examples:
        # create PC1 for detection
        uv run python tools/infer.py pca --site-id libya_floods_2023 --features-subdir s2 --n-components 1

        # create PC3 for visualization
        uv run python tools/infer.py pca --site-id libya_floods_2023 --features-subdir s2 --n-components 3
    """
    import numpy as np
    from sklearn.decomposition import PCA

    from terramind_ad.zarr import load_features, save_features

    log.setLevel(logging.INFO)

    # load features from Zarr
    features_path = data_dir / site_id / "features" / features_subdir / "features.zarr"
    assert features_path.exists(), f"Features not found: {features_path}"

    # setup output path
    suffix = "-n" if normalize else ""
    output_path = data_dir / site_id / "features" / features_subdir / f"features_pc{n_components}{suffix}.zarr"
    if skip_existing and output_path.exists():
        log.info("Output already exists, skipping: %s", output_path)
        return

    log.info("Loading features from %s", features_path)
    features, timestamps, metadata = load_features(features_path)
    log.info("Loaded features: %s, timesteps: %d", features.shape, len(timestamps))

    # collect samples for PCA fitting
    log.info("Preparing samples for PCA fitting...")
    T, H, W, D = features.shape
    all_samples = features.reshape(-1, D)

    # subsample if needed
    if subsample and len(all_samples) > subsample:
        log.info("Subsampling %d -> %d for PCA", len(all_samples), subsample)
        indices = np.random.choice(len(all_samples), subsample, replace=False)
        all_samples = all_samples[indices]

    # z-score normalize embeddings (mean=0, std=1)
    mean = std = None
    if normalize:
        log.info("Z-score normalizing embeddings...")
        mean = all_samples.mean(axis=0)
        std = all_samples.std(axis=0)
        all_samples = (all_samples - mean) / (std + 1e-8)

    # fit PCA
    log.info("Fitting PCA with %d components...", n_components)
    pca = PCA(n_components=n_components)
    pca.fit(all_samples)
    log.info("PCA explained variance ratio: %s", pca.explained_variance_ratio_)
    log.info("PCA cumulative explained variance: %.4f", pca.explained_variance_ratio_.sum())

    # transform each timestep
    log.info("Transforming features...")
    feats_flat = features.reshape(-1, D)
    if normalize:
        feats_flat = (feats_flat - mean) / (std + 1e-8)  # type: ignore
    pca_flat = pca.transform(feats_flat)
    pca_grid = pca_flat.reshape(T, H, W, n_components)
    log.info("PCA features shape: %s", pca_grid.shape)

    # save as Zarr
    pca_metadata = {
        **metadata,
        "pca_components": n_components,
        "pca_explained_variance": pca.explained_variance_ratio_.tolist(),
    }
    save_features(pca_grid, timestamps, output_path, metadata=pca_metadata)
    log.info("Saved PCA features to %s", output_path)


@cli.command()
def clouds(
    site_id: str = ArgField(description="Site ID to process"),
    data_dir: Path = ArgField(default=Path("data"), description="Data directory"),
    sensor_dirs: list[str] = ArgField(
        default=["s2"], description="Sensor subdirectories to process (must include 's2')"
    ),
    patch_size: int = ArgField(default=512, description="Patch size for OmniCloudMask"),
    patch_overlap: int = ArgField(default=256, description="Patch overlap for OmniCloudMask"),
    batch_size: int = ArgField(default=1, description="Batch size for inference"),
    device: str = ArgField(default="cuda", description="Device for inference"),
    inference_dtype: str = ArgField(default="bf16", description="Inference dtype (bf16, fp32, fp16)"),
    dilation_size: int = ArgField(default=8, description="Dilation size for feature-level cloud mask"),
    downsample_factor: int = ArgField(default=16, description="Downsample factor for feature-level cloud mask"),
    skip_existing: bool = ArgField(default=True, description="Skip if cloud mask already exists"),
) -> None:
    """Generate cloud masks using OmniCloudMask and save to separate zarr files.

    Generates two outputs:
    1. Full-resolution cloud masks: data/{site_id}/images/s2/clouds.zarr
    2. Feature-resolution cloud masks: data/{site_id}/features/{sensor_combo}/features_cm.zarr
       (dilated and downsampled to match TerraMind feature resolution)

    Cloud mask values:
        0 = Clear
        1 = Thick Cloud / Cloudy (after dilation and downsampling)

    Examples:
        # generate cloud masks for S2 only
        uv run python tools/infer.py clouds --site-id libya_floods_2023

        # generate for S2+S1 fusion features
        uv run python tools/infer.py clouds --site-id libya_floods_2023 --sensor-dirs s2 s1

        # use larger batch size for faster processing on GPU
        uv run python tools/infer.py clouds --site-id libya_floods_2023 --batch-size 4 --device cuda
    """
    import numpy as np
    import xarray as xr
    from tqdm import tqdm

    from terramind_ad.cloudmask import generate_cloud_mask, prepare_feature_cloud_mask
    from terramind_ad.zarr import load_timeseries, save_cloud_masks

    log.setLevel(logging.INFO)

    # ensure s2 is in sensor_dirs
    if "s2" not in [s.split("_")[0] for s in sensor_dirs]:
        raise ValueError("sensor_dirs must include 's2' for cloud mask generation")

    # load S2 timeseries
    zarr_path = data_dir / site_id / "images" / "s2" / "timeseries.zarr"
    if not zarr_path.exists():
        raise FileNotFoundError(f"S2 timeseries not found: {zarr_path}")

    # check if clouds already exist
    clouds_path = data_dir / site_id / "images" / "s2" / "clouds.zarr"
    if skip_existing and clouds_path.exists():
        log.info("Cloud masks already exist at %s, skipping", clouds_path)
        return

    log.info("Loading S2 timeseries from %s", zarr_path)
    data = load_timeseries(zarr_path)

    log.info("Timeseries shape: %s", data.shape)
    T = data.sizes["time"]
    timestamps = [str(t) for t in data.time.values]

    log.info("Extracting RGB+NIR bands")
    cloud_masks = []
    for t in tqdm(range(T), desc="Generating cloud masks"):
        # extract RGB+NIR as (3, H, W): Red=B04, Green=B03, NIR=B08
        rgb_nir = data.isel(time=t).values[[3, 2, 7], :, :]
        # generate cloud mask
        mask = generate_cloud_mask(
            rgb_nir=rgb_nir,
            patch_size=patch_size,
            patch_overlap=patch_overlap,
            batch_size=batch_size,
            device=device,
            inference_dtype=inference_dtype,
        )
        cloud_masks.append(mask)

    # stack into (T, H, W) array
    cloud_masks_array = np.stack(cloud_masks, axis=0)
    log.info("Generated cloud masks with shape: %s", cloud_masks_array.shape)
    # save full-resolution cloud masks
    spatial_coords = {"y": data.y.values, "x": data.x.values}
    save_cloud_masks(cloud_masks_array, timestamps, spatial_coords, clouds_path)
    # prepare feature-level cloud masks (dilated + downsampled)
    log.info("Preparing feature-level cloud masks...")
    feature_masks = prepare_feature_cloud_mask(
        cloud_masks_array,
        dilation_size=dilation_size,
        downsample_factor=downsample_factor,
    )
    # save to features directory
    sensor_combo = "+".join(sensor_dirs)
    features_dir = data_dir / site_id / "features" / sensor_combo
    features_dir.mkdir(exist_ok=True, parents=True)
    features_cm_path = features_dir / "features_cm.zarr"
    # create downsampled spatial coordinates
    H_feat, W_feat = feature_masks.shape[1], feature_masks.shape[2]
    y_feat = data.y.values[::downsample_factor][:H_feat]
    x_feat = data.x.values[::downsample_factor][:W_feat]
    # save feature-level cloud masks with metadata
    feature_cloud_da = xr.DataArray(
        feature_masks,
        coords={"time": timestamps, "y": y_feat, "x": x_feat},
        dims=["time", "y", "x"],
        name="cloud_mask",
        attrs={
            "dilation_size": dilation_size,
            "downsample_factor": downsample_factor,
            "source": "OmniCloudMask",
        },
    )
    feature_cloud_da.to_zarr(features_cm_path, mode="w", consolidated=True)
    log.info("Saved feature-level cloud masks to %s with shape %s", features_cm_path, feature_masks.shape)
    log.info("Cloud mask generation complete!")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
    )
    cli()
