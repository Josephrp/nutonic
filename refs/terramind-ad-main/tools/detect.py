import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from argdantic import ArgField, ArgParser
from numpy.typing import NDArray
from PIL import Image
from sklearn.preprocessing import minmax_scale

from terramind_ad.data import SitesConfig
from terramind_ad.detect import detect_changes
from terramind_ad.zarr import load_features, load_timeseries

log = logging.getLogger("detect")
cli = ArgParser(description="Element84 change detection")


def load_pc_features(features_dir: Path, component: int = 1) -> tuple[NDArray, list[str]]:
    """
    Load pre-computed PC features from zarr.

    Args:
        features_dir: Directory containing PC files (e.g., data/site_id/features/s2/)
        component: Number of PC components (1 or 3)

    Returns:
        features: (T, H, W, component) PC values
        timestamps: List of ISO date strings
    """
    pc_path = features_dir / f"features_pc{component}.zarr"
    if not pc_path.exists():
        raise FileNotFoundError(
            f"PC file not found: {pc_path}\n"
            f"Run PCA preprocessing first: uv run python tools/infer.py pca --site-id <site> --n-components {component}"
        )

    features, timestamps, metadata = load_features(pc_path)
    log.info("Loaded PC%d: %s from %d timestamps", component, features.shape, len(timestamps))
    return features, timestamps


def save_image(array: NDArray, output_path: Path, upscale: int = 10, mode: str = "L") -> None:
    """Save array as upscaled PNG."""
    if mode == "L":  # grayscale
        norm = minmax_scale(array.flatten(), feature_range=(0, 255)).reshape(array.shape)
        uint8 = norm.astype(np.uint8)
    else:  # RGB
        h, w, c = array.shape
        norm = minmax_scale(array.reshape(-1, c), feature_range=(0, 255)).reshape(h, w, c)
        uint8 = norm.astype(np.uint8)

    img = Image.fromarray(uint8, mode=mode)
    img = img.resize((img.width * upscale, img.height * upscale), resample=Image.Resampling.NEAREST)
    img.save(output_path)


def compute_persistence_score(
    detections: NDArray,
    frequency_weight: float = 0.6,
    continuity_weight: float = 0.4,
) -> float:
    """
    Compute temporal persistence score for a pixel's anomaly detections.

    Args:
        detections: (T,) binary array where 1 = anomaly detected at time t
        frequency_weight: Weight for frequency component (default: 0.6)
        continuity_weight: Weight for continuity component (default: 0.4)

    Returns:
        Score in [0, 1] where higher = more persistent anomaly
    """
    if detections.sum() == 0:
        return 0.0

    # frequency component: what fraction of observations are anomalies
    frequency = detections.mean()

    # continuity component: penalize gaps in detection
    # find first and last detection
    detected_indices = np.where(detections)[0]
    if len(detected_indices) == 1:
        # single detection = low continuity
        continuity = 0.0
    else:
        span = detected_indices[-1] - detected_indices[0] + 1
        continuity = detections.sum() / span  # ratio of detections within span

    # combined score
    score = frequency_weight * frequency + continuity_weight * continuity
    return score


@cli.command()
def run(
    site_id: str = ArgField(description="Site ID to process"),
    data_dir: Path = ArgField(default=Path("data"), description="Data directory"),
    sensor_dir: str = ArgField(default="s2", description="Sensor subdirectory (e.g., 's2', 's2_median_3m')"),
    pc_component: int = ArgField(default=1, description="Number of PC components (1 for detection)"),
    output_dir: Path = ArgField(default=Path("outputs"), description="Output directory"),
    period: float = ArgField(default=1.0, description="Period in years for harmonic regression (1.0 = annual)"),
) -> None:
    """
    Detect spatial changes using RANSAC fitted on pre-event clear observations.

    Pipeline:
        1. Load pre-computed PC features and cloud masks
        2. Fit RANSAC harmonic model on pre-event clear data only
        3. Compute residuals for all clear observations
        4. Use per-pixel thresholds for anomaly detection

    Prerequisites:
        - Run PCA preprocessing: uv run python tools/infer.py pca --site-id <site> --n-components 1
        - Ensure cloud masks exist at: data/<site>/features/s2/features_cm.zarr

    Examples:
        uv run python tools/detect.py run --site-id libya_floods_2023
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

    # load PC features
    features_dir = data_dir / site_id / "features" / sensor_dir
    features, timestamps = load_pc_features(features_dir, pc_component)

    # load cloud masks
    cloud_mask_path = features_dir / "features_cm.zarr"
    if not cloud_mask_path.exists():
        raise FileNotFoundError(
            f"Cloud mask not found: {cloud_mask_path}\nEnsure cloud masks are generated during preprocessing"
        )
    cloud_mask = load_timeseries(cloud_mask_path).values  # (T, H, W)
    log.info("Loaded cloud mask: %s", cloud_mask.shape)

    # find event index in FULL timeseries
    event_dt = datetime.strptime(site.event_date, "%Y-%m-%d")
    timestamp_dts = [datetime.strptime(ts, "%Y-%m-%d") for ts in timestamps]
    event_idx = next((i for i, ts in enumerate(timestamp_dts) if ts >= event_dt), None)
    if event_idx is None:
        raise ValueError(f"No timestamps after {site.event_date}")

    log.info("Event: %s -> index %d/%d (%s)", site.event_date, event_idx, len(timestamps), timestamps[event_idx])

    # run detection
    result = detect_changes(
        features=features,
        cloud_mask=cloud_mask,
        timestamps=timestamps,
        event_idx_full=event_idx,
        period=period,
    )

    # save to data directory (anomalies subdirectory)
    anomalies_dir = data_dir / site_id / "anomalies" / sensor_dir
    anomalies_dir.mkdir(parents=True, exist_ok=True)

    # save detection results
    np.savez_compressed(
        anomalies_dir / "detection.npz",
        residuals=result.residuals,
        fitted_values=result.fitted_values,
        threshold=result.threshold,
        valid_mask=result.valid_mask,
        timestamps=result.timestamps,
        event_idx=result.event_idx,
    )
    log.info("Saved detection results: %s", anomalies_dir / "detection.npz")

    # compute accumulated post-event anomalies
    post_event_residuals = result.residuals[result.event_idx :]  # (T_post, H, W)
    post_event_valid = result.valid_mask[result.event_idx :]  # (T_post, H, W)

    # binary anomaly mask: residual > threshold (per-pixel)
    anomaly_mask = post_event_residuals > result.threshold[None, :, :]  # (T_post, H, W)
    anomaly_mask = anomaly_mask & post_event_valid  # only count clear observations

    # accumulate anomalies over time
    accumulated_anomalies = anomaly_mask.sum(axis=0).astype(float)  # (H, W)

    # normalize by max for visualization
    accumulated_norm = accumulated_anomalies / (accumulated_anomalies.max() + 1e-10)

    # save visualizations
    output_path = output_dir / site_id / sensor_dir
    output_path.mkdir(parents=True, exist_ok=True)

    h, w = result.threshold.shape
    # 1. accumulated anomaly count (normalized)
    save_image(accumulated_norm, output_path / "accumulated_anomalies.png", mode="L")
    save_image(result.threshold, output_path / "threshold_map.png", mode="L")
    log.info("Saved visualizations: %s", output_path)
    # log summary stats
    post_event_residuals = result.residuals[result.event_idx :]
    post_event_anomalies = (post_event_residuals > result.threshold[None, :, :]).sum()
    log.info(
        "Post-event anomalies: %d / %d (%.1f%%)",
        post_event_anomalies,
        post_event_residuals.size,
        100 * post_event_anomalies / post_event_residuals.size,
    )


@cli.command()
def filter(
    site_id: str = ArgField(description="Site ID to process"),
    data_dir: Path = ArgField(default=Path("data"), description="Data directory"),
    sensor_dir: str = ArgField(default="s2", description="Sensor subdirectory (e.g., 's2', 's2_median_3m')"),
    output_dir: Path = ArgField(default=Path("outputs"), description="Output directory"),
    min_score: float = ArgField(default=0.3, description="Minimum persistence score (0-1)"),
    min_appearances: int = ArgField(default=2, description="Minimum number of appearances"),
    frequency_weight: float = ArgField(default=0.6, description="Weight for frequency component"),
    continuity_weight: float = ArgField(default=0.4, description="Weight for continuity component"),
) -> None:
    """
    Filter detected anomalies by temporal persistence.

    Pipeline:
        1. Load detection results from previous run
        2. Compute persistence score for each pixel
        3. Filter out non-persistent anomalies
        4. Save filtered results and visualizations

    Prerequisites:
        - Run detection first: uv run python tools/detect.py run --site-id <site>

    Examples:
        uv run python tools/detect.py filter --site-id libya_floods_2023 --min-score 0.3 --min-appearances 2
    """
    log.setLevel(logging.INFO)

    # load detection results
    anomalies_dir = data_dir / site_id / "anomalies" / sensor_dir
    detection_file = anomalies_dir / "detection.npz"
    if not detection_file.exists():
        raise FileNotFoundError(
            f"Detection results not found: {detection_file}\n"
            f"Run detection first: uv run python tools/detect.py run --site-id {site_id}"
        )
    data = np.load(detection_file)
    residuals = data["residuals"]  # (T, H, W)
    threshold = data["threshold"]  # (H, W)
    valid_mask = data["valid_mask"]  # (T, H, W)
    timestamps = data["timestamps"]
    event_idx = int(data["event_idx"])

    log.info("Loaded detection results: %s", residuals.shape)
    log.info("Event index: %d / %d", event_idx, len(timestamps))

    # extract post-event data
    post_residuals = residuals[event_idx:]  # (T_post, H, W)
    post_valid = valid_mask[event_idx:]  # (T_post, H, W)
    # compute binary anomaly mask
    anomaly_mask = post_residuals > threshold[None, :, :]  # (T_post, H, W)
    anomaly_mask = anomaly_mask & post_valid  # only clear observations
    t_post, h, w = anomaly_mask.shape
    log.info("Post-event shape: (%d, %d, %d)", t_post, h, w)

    # compute persistence score for each pixel
    log.info("Computing persistence scores...")
    persistence_scores = np.zeros((h, w))
    for i in range(h):
        for j in range(w):
            detections = anomaly_mask[:, i, j]  # (T_post,)
            persistence_scores[i, j] = compute_persistence_score(
                detections,
                frequency_weight=frequency_weight,
                continuity_weight=continuity_weight,
            )
    # filter by persistence criteria
    appearance_count = anomaly_mask.sum(axis=0)  # (H, W)
    persistent_mask = (persistence_scores >= min_score) & (appearance_count >= min_appearances)
    # compute filtered accumulated anomalies
    filtered_anomalies = anomaly_mask.copy()
    filtered_anomalies[:, ~persistent_mask] = 0  # zero out non-persistent pixels
    accumulated_filtered = filtered_anomalies.sum(axis=0).astype(float)  # (H, W)
    accumulated_orig = anomaly_mask.sum(axis=0).astype(float)  # (H, W)
    # normalize for visualization
    accumulated_filtered = accumulated_filtered**2  # highlight frequent
    accumulated_filtered_norm = accumulated_filtered / (accumulated_filtered.max() + 1e-10)

    # save results
    np.savez_compressed(
        anomalies_dir / "detection_filtered.npz",
        persistence_scores=persistence_scores,
        persistent_mask=persistent_mask,
        accumulated_filtered=accumulated_filtered,
        accumulated_orig=accumulated_orig,
        timestamps=timestamps[event_idx:],
    )
    log.info("Saved filtered results: %s", anomalies_dir / "detection_filtered.npz")

    # save visualizations
    output_path = output_dir / site_id / sensor_dir
    output_path.mkdir(parents=True, exist_ok=True)

    save_image(persistence_scores, output_path / "persistence_scores.png", mode="L")
    save_image(accumulated_filtered_norm, output_path / "accumulated_filtered.png", mode="L")
    log.info("Saved visualizations: %s", output_path)

    # log summary stats
    n_persistent = persistent_mask.sum()
    n_total = (accumulated_orig > 0).sum()
    total_anomalies_orig = accumulated_orig.sum()
    total_anomalies_filtered = accumulated_filtered.sum()

    log.info("Pixels with anomalies (original): %d", n_total)
    log.info("Pixels with persistent anomalies: %d (%.1f%%)", n_persistent, 100 * n_persistent / (n_total + 1e-10))
    log.info("Total anomaly detections (original): %d", total_anomalies_orig)
    log.info(
        "Total anomaly detections (filtered): %d (%.1f%%)",
        total_anomalies_filtered,
        100 * total_anomalies_filtered / (total_anomalies_orig + 1e-10),
    )
    log.info("Persistence score range: [%.3f, %.3f]", persistence_scores.min(), persistence_scores.max())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
    cli()
