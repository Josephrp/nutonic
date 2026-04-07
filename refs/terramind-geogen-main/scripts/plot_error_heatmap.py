import pathlib

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from scipy.stats import binned_statistic_2d
from matplotlib.colors import LogNorm 


# Configuration Variables
IN_MODALITY = "S2L2A"
MODEL_VERSION = "terramind_v1_base_generate"
CSV_PATH = f"generation_errors_{IN_MODALITY}_{MODEL_VERSION}_20k_Coordinates_10averaged_haversine.csv"
OUTPUT_FIG = pathlib.Path("Haversine_distance_km_Coordinates_10averaged.png")
BIN_SIZE_DEG = 2.0


df = pd.read_csv(CSV_PATH)
lats = df["Latitude"].values
lons = df["Longitude"].values
values = df["Haversine_distance_km_Coordinates"].values

non_nan_mask = ~np.isnan(values)

# Apply the mask to all three arrays
lats = lats[non_nan_mask]
lons = lons[non_nan_mask]
values = values[non_nan_mask]

non_nan_count = np.count_nonzero(~np.isnan(values))
print(non_nan_count)

# Set up map
proj = ccrs.PlateCarree()
fig = plt.figure(figsize=(9, 4.5))
ax = plt.axes(projection=proj)

ax.add_feature(cfeature.COASTLINE)
gridlines = ax.gridlines(draw_labels=False, linewidth=0.5, color='gray',
                         alpha=0.5, linestyle='--')
gridlines.top_labels = False
gridlines.right_labels = False
gridlines.x_inline = False
gridlines.y_inline = False

# Define bin edges restricted to the data range
lat_min, lat_max = -60, 83
lon_min, lon_max = -180, 180

lat_edges = np.arange(lat_min, lat_max + BIN_SIZE_DEG, BIN_SIZE_DEG)
lon_edges = np.arange(lon_min, lon_max + BIN_SIZE_DEG, BIN_SIZE_DEG)

# Compute the mean MAE inside each rectangle
stat, _, _, _ = binned_statistic_2d(
    x=lons,
    y=lats,
    values=values,
    statistic="mean",  # mean per bin
    bins=[lon_edges, lat_edges],
)

non_nan_count = np.count_nonzero(~np.isnan(stat))

# Mask empty bins (nan)
stat = np.ma.masked_invalid(stat)

# Plot the rectangular heat‑map.
mesh = ax.pcolormesh(
    lon_edges,
    lat_edges,
    stat.T,
    cmap='plasma',
    shading="auto",
    transform=proj,
    norm=LogNorm(
        vmin=np.nanmin(stat[stat > 0]) if np.any(stat > 0) else 0.01,
    ),
)

cb = fig.colorbar(mesh, ax=ax, shrink=0.7, pad=0.02)

# formatter: turn scientific notation into plain integers
cb.formatter = mtick.FuncFormatter(lambda x, _: f'{int(x):,}' if x >= 1 else f'{x:.2f}')
cb.update_ticks()

plt.tight_layout()
plt.savefig(OUTPUT_FIG, dpi=300, bbox_inches="tight")
