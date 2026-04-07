import json
from pathlib import Path

import numpy as np
import streamlit as st
import xarray as xr

from terramind_ad.dashboard.components import (
    render_anomaly_map,
    render_anomaly_timeline,
    render_pca_features,
    render_rgb_image,
    render_temporal_series,
)
from terramind_ad.data import SitesConfig

# configuration constants
DATA_DIR = Path("data")
SENSOR_DIR = "s2"
EVENTS_CONFIG_PATH = Path("resources/events.json")


@st.cache_resource
def load_site_data(site_id: str) -> dict:
    """Load lazy references to zarr data (no eager loading into memory).

    Returns xarray DataArrays that load data on-demand when sliced.
    """
    features_path = DATA_DIR / site_id / "features" / SENSOR_DIR / "features.zarr"
    if not features_path.exists():
        raise FileNotFoundError(f"Features not found: {features_path}")

    # load as zarr group for metadata
    import zarr

    features_group = zarr.open(str(features_path), mode="r")
    timestamps = [ts.decode("utf-8") for ts in features_group["timestamps"][:]]  # type: ignore
    metadata = dict(features_group.attrs)

    # load PC3 features for visualization (stored as zarr arrays, not xarray)
    pc3_path = DATA_DIR / site_id / "features" / SENSOR_DIR / "features_pc3.zarr"
    pca_data = None
    if pc3_path.exists():
        pca_group = zarr.open(str(pc3_path), mode="r")
        pca_data = pca_group["features"]  # type: ignore lazy array (T, H, W, 3)

    # lazy load RGB imagery
    sat_zarr_path = DATA_DIR / site_id / "images" / SENSOR_DIR / "timeseries.zarr"

    sat_data = None
    if sat_zarr_path.exists():
        ds = xr.open_zarr(sat_zarr_path, consolidated=True)
        sat_data = ds[list(ds.data_vars)[0]]  # lazy DataArray

    return {
        "timestamps": timestamps,
        "rgb_data": sat_data,
        "metadata": metadata,
        "pca_data": pca_data,
        "T": len(timestamps),
        "H": pca_data.shape[1] if pca_data is not None else 0,  # type: ignore
        "W": pca_data.shape[2] if pca_data is not None else 0,  # type: ignore
    }


@st.cache_data
def load_anomaly_data(site_id: str) -> dict | None:
    """Load pre-computed anomaly detection results."""
    detection_path = DATA_DIR / site_id / "anomalies" / SENSOR_DIR / "detection.npz"

    if not detection_path.exists():
        return None

    data = np.load(detection_path)

    # compute anomaly mask: residuals > threshold (per-pixel)
    residuals = data["residuals"]  # (T, H, W)
    threshold = data["threshold"]  # (H, W)
    valid_mask = data["valid_mask"]  # (T, H, W)
    event_idx = int(data["event_idx"])

    # binary anomaly: where residual exceeds threshold AND observation is clear
    anomaly_mask = (residuals > threshold[None, :, :]) & valid_mask  # (T, H, W)

    # compute accumulated post-event anomalies for visualization
    post_event_mask = anomaly_mask[event_idx:]  # (T_post, H, W)
    accumulated_anomalies = post_event_mask.sum(axis=0).astype(float)  # (H, W)

    # try to load filtered results if available
    filtered_path = DATA_DIR / site_id / "anomalies" / SENSOR_DIR / "detection_filtered.npz"
    if filtered_path.exists():
        filtered_data = np.load(filtered_path)
        accumulated_anomalies = filtered_data["accumulated_filtered"]  # use filtered version

    return {
        "residuals_timeseries": residuals,
        "anomaly_mask_timeseries": anomaly_mask,
        "fitted_timeseries": data["fitted_values"],
        "valid_mask": valid_mask,
        "threshold": threshold,
        "event_idx": event_idx,
        "accumulated_anomalies": accumulated_anomalies,  # (H, W) accumulated post-event
    }


@st.cache_resource
def load_sites_config() -> SitesConfig:
    """Load site configurations from events.json."""
    with EVENTS_CONFIG_PATH.open() as f:
        return SitesConfig(**json.load(f))


def run():
    st.set_page_config(page_title="TerraMind Anomaly Detection", page_icon="🌍", layout="wide")
    st.sidebar.title("TerraMind \nChange Detection")

    # load available sites
    config = load_sites_config()
    site_options = {site.id: site.name for site in config.sites}

    # site selection dropdown
    site_id = st.sidebar.selectbox(
        "Site",
        options=list(site_options.keys()),
        format_func=lambda x: site_options[x],
    )

    # get current site config
    current_site = next(site for site in config.sites if site.id == site_id)

    # load data
    try:
        with st.spinner("Loading data..."):
            data = load_site_data(site_id)
            anomaly_data = load_anomaly_data(site_id)
    except FileNotFoundError as e:
        st.error(f"❌ {e}")
        st.info(f"Expected structure:\n- `{DATA_DIR}/<site_id>/features/{SENSOR_DIR}/features.zarr`")
        return

    timestamps = data["timestamps"]
    rgb_data = data["rgb_data"]
    pca_data = data["pca_data"]
    T = data["T"]
    H = data["H"]
    W = data["W"]

    # sidebar: show errors only
    if anomaly_data is None:
        st.sidebar.error("⚠️  No anomaly data")
        st.sidebar.info("Run: `uv run python tools/detect.py run --site-id <site_id>`")
        return
    if pca_data is None:
        st.sidebar.error("⚠️  No PC3 features")
        st.sidebar.info("Run: `uv run python tools/infer.py pca --site-id <site_id> --n-components 3`")
        return
    event_idx = anomaly_data["event_idx"]

    # controls
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎛️ Controls")

    # reset state when site changes
    if "current_site_id" not in st.session_state or st.session_state.current_site_id != site_id:
        st.session_state.current_site_id = site_id
        st.session_state.time_idx = event_idx if event_idx is not None else 0
        st.session_state.patch_x = current_site.default_patch_x or W // 2
        st.session_state.patch_y = current_site.default_patch_y or H // 2

    # time control with +/- buttons
    st.sidebar.markdown("**⏱️ Time Selection**")

    # clamp time_idx to valid range (in case data size changed)
    st.session_state.time_idx = min(max(0, st.session_state.time_idx), T - 1)

    col_minus, col_slider, col_plus = st.sidebar.columns([1, 8, 1])
    with col_minus:
        if st.button(
            "",
            key="time_minus",
            type="tertiary",
            help="Previous timestep",
            icon=":material/do_not_disturb_on:",
        ):
            st.session_state.time_idx = max(0, st.session_state.time_idx - 1)
    with col_slider:
        time_idx = st.slider(
            "Date",
            0,
            T - 1,
            st.session_state.time_idx,
            format=f"{timestamps[st.session_state.time_idx]}",
            label_visibility="collapsed",
        )
        st.session_state.time_idx = time_idx
    with col_plus:
        if st.button(
            "",
            key="time_plus",
            type="tertiary",
            help="Next timestep",
            icon=":material/add_circle:",
        ):
            st.session_state.time_idx = min(T - 1, st.session_state.time_idx + 1)
    time_idx = st.session_state.time_idx

    st.sidebar.markdown("**📍 Patch Selection**")
    # clamp patch coordinates to valid range
    st.session_state.patch_x = min(max(0, st.session_state.patch_x), W - 1)
    st.session_state.patch_y = min(max(0, st.session_state.patch_y), H - 1)

    col1, col2 = st.sidebar.columns(2)
    patch_x = col1.number_input("X", 0, W - 1, st.session_state.patch_x, key="px")
    patch_y = col2.number_input("Y", 0, H - 1, st.session_state.patch_y, key="py")

    # update session state with any manual changes
    st.session_state.patch_x = patch_x
    st.session_state.patch_y = patch_y

    # main content: temporal analysis view (always shown)
    st.title(site_options[site_id])

    # spatial context (small maps)
    st.markdown(f"### 🗺️ Spatial Context — `{timestamps[time_idx]}`")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**RGB**")
        if rgb_data is not None:
            render_rgb_image(
                rgb_data,
                time_idx,
                (int(patch_x), int(patch_y)),
            )
        else:
            st.warning("RGB data not available")

    with col2:
        st.markdown("**PCA**")
        render_pca_features(
            pca_data,
            time_idx,
            (int(patch_x), int(patch_y)),
        )

    with col3:
        st.markdown("**Anomaly Heatmap**")
        render_anomaly_map(
            anomaly_data["accumulated_anomalies"],
            (int(patch_x), int(patch_y)),
        )

    st.markdown(f"### 📈 Temporal Analysis — Patch `({patch_x}, {patch_y})`")

    # temporal series and anomaly timeline
    render_temporal_series(
        residuals=anomaly_data["residuals_timeseries"],
        anomaly_mask=anomaly_data["anomaly_mask_timeseries"],
        timestamps=timestamps,
        patch_coord=(int(patch_x), int(patch_y)),
        time_idx=time_idx,
        event_idx=event_idx,
    )

    render_anomaly_timeline(
        anomaly_mask=anomaly_data["anomaly_mask_timeseries"],
        timestamps=timestamps,
        time_idx=time_idx,
        event_idx=event_idx,
    )


if __name__ == "__main__":
    run()
