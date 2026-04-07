import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import RANSACRegressor

log = logging.getLogger(__name__)


@dataclass
class CDResult:
    """Results from change detection analysis."""

    # temporal outputs (full timeline with holes for cloudy observations)
    residuals: NDArray  # (T, H, W) - absolute residuals (zeros where cloudy)
    fitted_values: NDArray  # (T, H, W) - predicted values from RANSAC (zeros where cloudy)
    threshold: NDArray  # (H, W) - per-pixel RANSAC threshold
    valid_mask: NDArray  # (T, H, W) - True where clear, False where cloudy

    # metadata
    timestamps: list[str]  # full timeline timestamps
    event_idx: int  # event index in full timeline


def to_decimal_year(timestamps: list[str]) -> NDArray:
    """
    Convert ISO date strings to decimal year format.

    Args:
        timestamps: List of date strings in 'YYYY-MM-DD' format

    Returns:
        Array of decimal years (e.g., 2023.5 for July 2023)
    """
    decimal_years = []
    for ts in timestamps:
        dt = datetime.strptime(ts, "%Y-%m-%d")
        year = dt.year
        # days since year start / days in year
        year_start = datetime(year, 1, 1)
        year_end = datetime(year + 1, 1, 1)
        days_in_year = (year_end - year_start).days
        days_elapsed = (dt - year_start).days
        decimal_years.append(year + days_elapsed / days_in_year)

    return np.array(decimal_years)


def create_harmonic_features(timestamps_decimal: NDArray, period: float = 1.0) -> NDArray:
    """
    Create harmonic regression features: [1, t, sin(2πt/T), cos(2πt/T)].

    This captures:
    - Constant offset (intercept)
    - Linear trend (slow drift over years)
    - Annual seasonality (sin/cos with 1-year period)

    Args:
        timestamps_decimal: (T,) decimal year values
        period: Period in years (default: 1.0 for annual cycle)

    Returns:
        Feature matrix: (T, 4) with columns [1, t, sin(2πt/T), cos(2πt/T)]
    """
    t = timestamps_decimal
    T = period
    # create feature matrix
    X = np.column_stack(
        [
            np.ones_like(t),  # intercept
            t,  # linear trend
            np.sin(2 * np.pi * t / T),  # seasonal component
            np.cos(2 * np.pi * t / T),  # seasonal component
        ]
    )
    return X


def fit_pre_event_ransac(
    pc1_clear: NDArray,
    x_features_clear: NDArray,
    event_idx: int,
    percentile: int = 98,
) -> tuple[NDArray, NDArray, float]:
    """
    Fit RANSAC on pre-event clear observations only.

    Args:
        pc1_clear: (T_clear,) time series of PC1 values (clear obs only)
        x_features_clear: (T_clear, 4) harmonic features for clear obs
        event_idx: index in clear timeseries where event occurs

    Returns:
        fitted_values: (T_clear,) predicted values for all clear obs
        residuals: (T_clear,) absolute errors for all clear obs
        threshold: 95th percentile of pre-event residuals
    """
    # extract pre-event data
    pc1_pre = pc1_clear[:event_idx]
    x_pre = x_features_clear[:event_idx]

    # fit RANSAC on pre-event only (use default auto threshold for fitting)
    ransac_thresh = (pc1_pre.max() - pc1_pre.min()) * 0.25
    ransac = RANSACRegressor(residual_threshold=ransac_thresh, random_state=42)
    ransac.fit(x_pre, pc1_pre)

    # predict on ALL clear observations
    fitted = ransac.predict(x_features_clear)
    residuals = np.abs(pc1_clear - fitted)

    # compute threshold from pre-event residuals (nth percentile)
    pre_event_residuals = residuals[:event_idx]
    anomaly_thresh = np.percentile(pre_event_residuals, percentile)
    return fitted, residuals, float(anomaly_thresh)


def detect_changes(
    features: NDArray,
    cloud_mask: NDArray,
    timestamps: list[str],
    event_idx_full: int,
    period: float = 1.0,
    percentile: int = 98,
) -> CDResult:
    """
    RANSAC-based change detection fitted on pre-event clear observations.

    Approach:
        1. Filter cloudy observations using cloud_mask
        2. Fit RANSAC harmonic model on pre-event clear data only
        3. Predict on all clear observations
        4. Compute residuals for anomaly detection

    Args:
        features: (T, H, W, 1) PC-reduced embeddings
        cloud_mask: (T, H, W) boolean mask (True = cloudy)
        timestamps: List of date strings for ALL timesteps
        event_idx_full: Index of event in FULL timeseries
        period: Period in years for seasonality (default: 1.0)

    Returns:
        CDResult with residuals, fitted values, and per-pixel thresholds
    """
    t, h, w, d = features.shape
    assert d == 1, f"Expected PC-reduced features with D=1, got D={d}. Run PCA preprocessing first."
    assert cloud_mask.shape == (t, h, w), f"Cloud mask shape {cloud_mask.shape} != features shape {(t, h, w)}"

    # squeeze features to (T, H, W)
    pc_all = features.squeeze(-1)

    # initialize outputs
    residuals_all = []
    fitted_all = []
    threshold_map = np.zeros((h, w))
    valid_mask_all = []

    # process each pixel
    log.info("Fitting RANSAC for %d pixels...", h * w)
    for i in range(h):
        for j in range(w):
            # get time series for this pixel
            pc_series = pc_all[:, i, j]  # (T,)
            valid_pixel = cloud_mask[:, i, j] < 1  # clear observations

            # filter to clear observations only
            pc_clear = pc_series[valid_pixel]
            timestamps_clear = [ts for ts, v in zip(timestamps, valid_pixel) if v]

            # find event index in clear timeseries
            event_date = timestamps[event_idx_full]
            event_idx_clear = next(
                (idx for idx, ts in enumerate(timestamps_clear) if ts >= event_date),
                len(timestamps_clear),
            )
            # skip if not enough pre-event data
            if event_idx_clear < 4:  # need at least 4 points for harmonic fit
                # fill with zeros
                residuals_all.append(np.zeros(len(pc_clear)))
                fitted_all.append(np.zeros(len(pc_clear)))
                threshold_map[i, j] = 0.0
                valid_mask_all.append(valid_pixel)
                continue

            # convert to decimal years and create harmonic features
            timestamps_dec_clear = to_decimal_year(timestamps_clear)
            x_features_clear = create_harmonic_features(timestamps_dec_clear, period=period)
            # fit RANSAC on pre-event clear data
            fitted, residuals, thresh = fit_pre_event_ransac(
                pc_clear,
                x_features_clear,
                event_idx_clear,
                percentile=percentile,
            )
            residuals_all.append(residuals)
            fitted_all.append(fitted)
            threshold_map[i, j] = thresh
            valid_mask_all.append(valid_pixel)
    # create arrays with full timeline (T, H, W)
    # use indexing to place clear observations at their temporal positions
    residuals_full = np.zeros((t, h, w))
    fitted_full = np.zeros((t, h, w))
    valid_mask_full = np.zeros((t, h, w), dtype=bool)

    for idx, (i, j) in enumerate([(i, j) for i in range(h) for j in range(w)]):
        res = residuals_all[idx]
        fit = fitted_all[idx]
        valid = valid_mask_all[idx]

        # place results at their temporal positions using the valid mask
        residuals_full[valid, i, j] = res
        fitted_full[valid, i, j] = fit
        valid_mask_full[:, i, j] = valid

    # count clear observations
    n_clear = valid_mask_full.sum(axis=(1, 2)).max()
    log.info("Clear observations: up to %d / %d", n_clear, t)
    log.info("Event index in full timeseries: %d / %d", event_idx_full, t)
    log.info("Residual range: [%.3f, %.3f]", residuals_full.min(), residuals_full.max())
    log.info("Threshold range: [%.3f, %.3f]", threshold_map.min(), threshold_map.max())

    return CDResult(
        residuals=residuals_full,
        fitted_values=fitted_full,
        threshold=threshold_map,
        valid_mask=valid_mask_full,
        timestamps=timestamps,  # full timeline
        event_idx=event_idx_full,  # event index in full timeline
    )
