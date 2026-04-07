import numpy as np
import streamlit as st
import xarray as xr
from matplotlib import patches
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from numpy.typing import NDArray

from terramind_ad.visualization import min_max_scale, percentile_clip_scale

# display configuration
SPATIAL_MAP_SIZE = (2.5, 2.5)  # figure size for RGB, PCA, anomaly maps
TEMPORAL_PLOT_SIZE = (12, 2.2)  # figure size for temporal series
SPATIAL_DPI = 96  # DPI for spatial maps
TEMPORAL_DPI = 250  # DPI for temporal plots (higher for clarity)

# set matplotlib style for professional web plots
plt.style.use("seaborn-v0_8-darkgrid")
plt.rcParams.update(
    {
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "figure.dpi": SPATIAL_DPI,
        "savefig.dpi": SPATIAL_DPI,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linewidth": 0.5,
    }
)


def draw_crosshair(
    ax: Axes,
    cx: int,
    cy: int,
    size: int = 32,
    color: str = "red",
    draw_lines: bool = True,
):
    half_size = size // 2
    square = patches.Rectangle(
        (cx - half_size, cy - half_size),
        width=size,
        height=size,
        fill=False,
        edgecolor=color,
        linewidth=1,
    )
    ax.add_patch(square)
    if draw_lines:
        ax.hlines(y=cy, xmin=0, xmax=(cx - half_size), linestyle=":", color=color, linewidth=1)
        ax.vlines(x=cx, ymin=0, ymax=(cy - half_size), linestyle=":", color=color, linewidth=1)


def render_rgb_image(
    rgb_data: xr.DataArray,
    time_idx: int,
    selected_patch: tuple[int, int] | None = None,
    downsample: int = 16,
) -> None:
    """Render RGB satellite image with optional patch marker.

    Loads only the requested timestep from zarr (lazy loading).
    """
    # lazy load only this timestep
    rgb = rgb_data.isel(time=time_idx, band=[3, 2, 1]).values  # B4, B3, B2
    rgb = np.clip(rgb / 5000 * 255, 0, 255).astype(np.uint8)
    rgb = rgb.transpose(1, 2, 0)

    fig, ax = plt.subplots(figsize=SPATIAL_MAP_SIZE, facecolor="white")
    ax.imshow(rgb)
    ax.axis("off")

    if selected_patch is not None:
        px, py = selected_patch
        cx = px * downsample + downsample // 2
        cy = py * downsample + downsample // 2
        draw_crosshair(ax, cx, cy)

    plt.tight_layout(pad=0.1)
    st.pyplot(fig, width="stretch")
    plt.close()


def render_pca_features(
    pca_data: xr.DataArray,
    time_idx: int,
    selected_patch: tuple[int, int] | None = None,
) -> None:
    """Render PCA feature visualization with z-score normalization.

    Loads only the requested timestep from zarr (lazy loading).
    """
    # lazy load only this timestep (handle both xarray and zarr arrays)
    if hasattr(pca_data, "isel"):
        pca_t = pca_data.isel(time=time_idx).values  # xarray DataArray
    else:
        pca_t = pca_data[time_idx]  # zarr Array  # (H, W, 3)

    # apply normalization
    pca_flat = pca_t.reshape(-1, 3)
    pca_norm = percentile_clip_scale(pca_flat)
    pca_scaled = min_max_scale(pca_norm)
    pca_rgb = pca_scaled.reshape(pca_t.shape)

    fig, ax = plt.subplots(figsize=SPATIAL_MAP_SIZE, facecolor="white")
    ax.imshow(pca_rgb, interpolation="nearest")
    ax.axis("off")

    if selected_patch is not None:
        px, py = selected_patch
        draw_crosshair(ax, px, py, size=4, color="yellow")

    plt.tight_layout(pad=0.1)
    st.pyplot(fig, width="stretch")
    plt.close()


def render_anomaly_map(
    accumulated_anomalies: NDArray,
    selected_patch: tuple[int, int] | None = None,
) -> None:
    """Render accumulated post-event anomaly heatmap.

    Args:
        accumulated_anomalies: (H, W) count of anomalies per pixel after event
        selected_patch: (x, y) coordinates of selected patch
    """
    fig, ax = plt.subplots(figsize=SPATIAL_MAP_SIZE, facecolor="white")

    # normalize for visualization
    max_count = accumulated_anomalies.max()
    if max_count > 0:
        normalized = accumulated_anomalies / max_count
    else:
        normalized = accumulated_anomalies

    ax.imshow(normalized, cmap="magma", vmin=0, vmax=1, interpolation="nearest")
    ax.axis("off")

    if selected_patch is not None:
        px, py = selected_patch
        draw_crosshair(ax, px, py, size=3, draw_lines=False)

    plt.tight_layout(pad=0.1)
    st.pyplot(fig, width="stretch")
    plt.close()


def render_temporal_series(
    residuals: NDArray,
    anomaly_mask: NDArray,
    timestamps: list[str],
    patch_coord: tuple[int, int],
    time_idx: int,
    event_idx: int,
) -> None:
    """Render temporal evolution at selected patch."""
    px, py = patch_coord
    residuals_patch = residuals[:, py, px]
    anomaly_patch = anomaly_mask[:, py, px]

    fig, ax = plt.subplots(figsize=TEMPORAL_PLOT_SIZE, facecolor="white", dpi=TEMPORAL_DPI)
    time_indices = np.arange(len(timestamps))
    # plot residuals with professional styling
    ax.plot(
        time_indices,
        residuals_patch,
        "o-",
        color="#2E86AB",
        alpha=0.7,
        markersize=3.5,
        linewidth=1.3,
        label="Residual",
    )

    # mark anomalies with red X (only post-event)
    anom_indices = np.where(anomaly_patch)[0]
    post_event_anom_indices = anom_indices[anom_indices >= event_idx]
    if len(post_event_anom_indices) > 0:
        ax.scatter(
            post_event_anom_indices,
            residuals_patch[post_event_anom_indices],
            marker="x",
            s=60,
            c="#C73E1D",
            linewidths=2.2,
            zorder=5,
            label="Anomaly",
        )
    # mark current time and event
    ax.axvline(time_idx, color="#F18F01", linestyle="--", linewidth=1.8, alpha=0.7, label="Current")
    if event_idx is not None:
        ax.axvline(event_idx, color="#6A4C93", linestyle=":", linewidth=1.8, alpha=0.7, label="Event")

    ax.set_xlabel("Date", fontweight="semibold")
    ax.set_ylabel("PC1 Value", fontweight="semibold")
    ax.set_title(f"Temporal Profile at Patch ({px}, {py})", fontweight="bold", pad=10)

    # show dates on x-axis with smart ticking
    n_ticks = min(10, len(timestamps))
    tick_indices = np.linspace(0, len(timestamps) - 1, n_ticks, dtype=int)
    ax.set_xticks(tick_indices)
    ax.set_xticklabels([timestamps[i] for i in tick_indices], rotation=45, ha="right")
    ax.tick_params(labelsize=7)
    ax.legend(loc="upper left", fontsize=6, framealpha=0.95, ncol=3, edgecolor="gray", fancybox=True)

    plt.tight_layout()
    st.pyplot(fig, width="content")
    plt.close()


def render_anomaly_timeline(
    anomaly_mask: NDArray,
    timestamps: list[str],
    time_idx: int,
    event_idx: int,
) -> None:
    """Render timeline of anomaly counts over time."""
    T, H, W = anomaly_mask.shape
    anomaly_counts = anomaly_mask.sum(axis=(1, 2))

    fig, ax = plt.subplots(figsize=TEMPORAL_PLOT_SIZE, facecolor="white", dpi=TEMPORAL_DPI)

    time_indices = np.arange(len(timestamps))
    colors = ["#F18F01" if i == time_idx else "#2E86AB" for i in range(len(timestamps))]

    ax.bar(time_indices, anomaly_counts, color=colors, alpha=0.75, width=0.85, edgecolor="white", linewidth=0.5)

    # mark event
    if event_idx is not None:
        ax.axvline(event_idx, color="#6A4C93", linestyle=":", linewidth=2, alpha=0.8, label="Event")
        ax.legend(loc="upper right", fontsize=8, framealpha=0.95, edgecolor="gray")

    ax.set_xlabel("Date", fontweight="semibold")
    ax.set_ylabel("Anomalous Patches", fontweight="semibold")
    ax.set_title(f"Spatial Anomaly Count Over Time (Total: {H * W} patches)", fontweight="bold", pad=10)

    # show dates on x-axis with smart ticking
    n_ticks = min(10, len(timestamps))
    tick_indices = np.linspace(0, len(timestamps) - 1, n_ticks, dtype=int)
    ax.set_xticks(tick_indices)
    ax.set_xticklabels([timestamps[i] for i in tick_indices], rotation=45, ha="right")
    ax.tick_params(labelsize=7)

    plt.tight_layout()
    st.pyplot(fig, width="content")
    plt.close()
