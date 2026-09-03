# ---
# jupyter:
#   jupytext:
#     formats: nhf_assist/notebooks//ipynb,src/workflow_templates/nhf//py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Create tmax_allsnow and tmax_allrain_offset Parameters
#
# ## Summary
# This notebook computes the `tmax_allsnow` and `tmax_allrain_offset` parameters
# for the OHM v2 domain. These parameters define the temperature thresholds at which
# precipitation falls as all-snow or all-rain, used by PRMS/pywatershed for
# precipitation partitioning.
#
# ## Original Method (NHM v1.1)
# Developed by Parker Norton (nhm_v1.1_workflows/tmax_allstar):
# - **Source data**: ERA5 reanalysis, hourly, 0.25° (~25km) resolution
# - **Period**: 2007–2019 (13 years)
# - **Method**: Mask 2m temperature by precipitation type (snow: ptype=5, rain: ptype=1),
#   clip to physical bounds, compute mean monthly values, area-weight to HRUs
# - **Grid-to-HRU weights**: Polygon intersection of ERA5 grid cells with GFv1.1 HRUs
# - **Processing tools**: Shell scripts (CDO/NCO) + Python
#
# ## Updated Method (OHM v2)
# This notebook adapts the workflow with two key improvements:
#
# | Aspect | Original (v1.1) | Updated (v2) |
# |--------|----------------|--------------|
# | Source data | ERA5 (25km) | **HRRR (3km)** |
# | Period | 2007–2019 | **2014-09 to 2025-09** (~11 water years) |
# | Temporal resolution | Hourly | Hourly |
# | Precip type field | ERA5 `ptype` (values 0-8) | HRRR `CSNOW`/`CRAIN` (binary flags) |
# | Grid-to-HRU weights | Polygon intersection | **Point-in-polygon** (3km grid fine enough) |
# | Processing | Shell + Python | **Pure Python (xarray + Herbie)** |
# | Geospatial fabric | GFv1.1 | **OHM v2 GeoPackage** |
#
# ## Rationale for HRRR
# - ERA5's 25km resolution produces visible grid-like artifacts in the parameters
# - HRRR's 3km resolution better resolves the physiography (elevation, aspect)
#   that drives snow/rain temperature thresholds
# - HRRR covers CONUS with hourly data from 2014-present
#
# ## Workflow Steps
# 1. Download ERA5 data (for comparison baseline)
# 2. Process ERA5: mask by ptype, monthly means, grid-to-HRU weights
# 3. Download HRRR data (via standalone script `run_hrrr_download_s3.py`)
# 4. Process HRRR: load cache, compute monthly means, grid-to-HRU weights
# 5. Compare ERA5 vs HRRR vs NHM v1.1 visually
# 6. Write final parameters using HRRR-derived values
#
# ## References
# - Norton, P.A., ERA5 tmax_allstar workflow, nhm_v1.1_workflows GitLab repository
# - Regan, R.S., et al., 2025, PRMS v6.0.0, USGS Software Release, https://doi.org/10.5066/P97032NH
# - HRRR archive: NOAA/AWS Open Data, https://noaa-hrrr-bdp-pds.s3.amazonaws.com

# %%
import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
import pathlib as pl
from shapely.geometry import Polygon

import sys
import os

# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhf_assist", 1)[0] + "nhf_assist")
sys.path.append(str(root_dir))

# %% [markdown]
# ## Configuration

# %%
# === PATHS ===
v2_gpkg_path = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\GIS\model_layers.gpkg")
land_sea_mask = pl.Path(r"D:\nhm-assist\data_dependencies\nhm_v1.1_workflows-master\tmax_allstar\land_sea_mask_upk.nc")
era5_data_dir = pl.Path(r"D:\ERA5_data")  # Where downloaded ERA5 files will be stored
output_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files")
output_dir.mkdir(parents=True, exist_ok=True)

# === PARAMETERS ===
start_year = 2007
end_year = 2019
grid_spacing = 0.25  # ERA5 grid spacing in degrees

# %% [markdown]
# ## Step 1: Download ERA5 data
# Requires `cdsapi` library and CDS API key configured.
# Each year downloads ~2GB of hourly data.

# %%
from assist.nhf.make_pws_params import fetch_era5_data
era5_valid = fetch_era5_data(v2_gpkg_path, era5_data_dir, start_year, end_year)

# %% [markdown]
# ## Step 2: Process ERA5 data — mask temperature by precipitation type
# Replaces the shell/NCO steps with pure Python/xarray.
# - `t2m_snow`: temperature when ptype == 5 (snow), clipped to [271.04, 274.4] K
# - `t2m_rain`: temperature when ptype == 1 (rain), clipped to [274.65, 276.48] K

# %%
from assist.nhf.make_pws_params import process_era5_ptype_masking

ymon_mean = process_era5_ptype_masking(era5_data_dir, start_year, end_year)

# %% [markdown]
# ## Step 3: Calculate ERA5 grid-to-HRU area weights
# Create polygons for each ERA5 grid cell, then compute intersection areas
# with each v2 HRU to produce weights.

# %%
from assist.nhf.make_pws_params import compute_era5_hru_weights

weights_df = compute_era5_hru_weights(
    v2_gpkg_path, era5_data_dir, start_year, grid_spacing, output_dir
)

# %% [markdown]
# ## Step 4: Apply weights — compute area-weighted tmax per HRU per month

# %%
from assist.nhf.make_pws_params import apply_era5_weights_to_hrus

hru_gdf = gpd.read_file(v2_gpkg_path, layer="nhru")
nhru = len(hru_gdf)

allsnow_f, allrain_f, allrain_offset = apply_era5_weights_to_hrus(
    ymon_mean, weights_df, nhru
)

# %% [markdown]
# ## Step 5: Write output parameter CSVs

# %%
def write_param_csv(filepath, param_name, data):
    """Write parameter in paramdb CSV format ($id, values by month)."""
    nhru, nmonths = data.shape
    rows = []
    # Flatten in Fortran order (column-major): all HRUs for month 1, then month 2, etc.
    flat = data.ravel(order="F")
    for i, val in enumerate(flat):
        rows.append({"$id": i + 1, param_name: val})
    pd.DataFrame(rows).to_csv(filepath, index=False)
    print(f"Wrote {filepath.name}: {len(rows)} rows")

# %% [markdown]
# ## Map: tmax_allsnow and tmax_allrain_offset by HRU

# %%
# import matplotlib.pyplot as plt
# from ipywidgets import interact, IntSlider
#
# hru_map_gdf = hru_gdf.to_crs(epsg=4326).copy()
#
# month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
#                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
#
# def plot_monthly_params(month=1):
#     idx = month - 1
#     hru_map_gdf["tmax_allsnow"] = allsnow_f[:, idx]
#     hru_map_gdf["tmax_allrain_offset"] = allrain_offset[:, idx]
#
#     fig, axes = plt.subplots(1, 2, figsize=(18, 8))
#
#     hru_map_gdf.plot(
#         ax=axes[0],
#         column="tmax_allsnow",
#         cmap="coolwarm",
#         edgecolor="none",
#         legend=True,
#         legend_kwds={"label": "tmax_allsnow (°F)", "shrink": 0.7},
#     )
#     axes[0].set_title(f"tmax_allsnow — {month_names[idx]}")
#     axes[0].set_axis_off()
#
#     hru_map_gdf.plot(
#         ax=axes[1],
#         column="tmax_allrain_offset",
#         cmap="coolwarm",
#         edgecolor="none",
#         legend=True,
#         legend_kwds={"label": "tmax_allrain_offset (°F)", "shrink": 0.7},
#     )
#     axes[1].set_title(f"tmax_allrain_offset — {month_names[idx]}")
#     axes[1].set_axis_off()
#
#     plt.tight_layout()
#     plt.show()
#
# interact(plot_monthly_params, month=IntSlider(min=1, max=12, step=1, value=1, description="Month:"))

# %%

# %% [markdown]
# ## Download HRRR data
# HRRR offers a higher-resolution dataset to match the higher spatial resolution of the Hydrofabric version 2. HRRR hourly data will be downloaded for the same domain, the grid-to-HRU area weights and tmax_allsnow/tmax_allrain_offset are computed.
#
# HRRR uses `CSNOW:surface` (1=snow) and `CRAIN:surface` (1=rain) flags with `TMP:2 m above ground` (in K).
#
# Requires: `pip install herbie-data cfgrib eccodes`
# HRRR available: 2014-present (hourly, 3km CONUS)
#
#

# %%
from herbie import Herbie
from datetime import datetime
from datetime import datetime as dt

# Configuration
hrrr_start_date = "2014-10-01"
hrrr_end_date = "2025-06-30"


# %% [markdown]
# ### Step H1: Download and process HRRR hourly data for all days
# Process each day's 24 hours, mask t2m by snow/rain flags,
# accumulate monthly means across the full period.

# %%
# This cell should be uncommented if you need to download the HRRR data; note the download took ~60 hours using HERBIE
# This downloads the full CONUS HRRR grid (~1799 x 1059 at 3km) for every hour.
# from assist.nhf.make_pws_params import fetch_hrrr_ptype_data
#
# hrrr_cache_file = era5_data_dir / "hrrr_processed_cache.npz"
# hrrr_result = fetch_hrrr_ptype_data(hrrr_start_date, hrrr_end_date, hrrr_cache_file)

# %% [markdown]
# ### Steps H2–H3: Compute HRRR monthly climatology and grid-to-HRU weights
# Physical constraints used in this step were set by Parker Norton based on the PRMS literature and experience with PRMS precipitation partitioning. The gap between 274.4 and 274.65 K (0.25 K) ensures the snow and rain temperature ranges don't overlap.
#
# 271.04 K = -2.11°C (28.1°F) — coldest reasonable "all-snow" threshold
# 274.4 K = 1.25°C (34.3°F) — warmest "all-snow" threshold (just above freezing)
# 274.65 K = 1.5°C (34.7°F) — coldest "all-rain" threshold (just above the snow max)
# 276.48 K = 3.33°C (38.0°F) — warmest "all-rain" threshold

# %%
from assist.nhf.make_pws_params import process_hrrr_climatology_and_weights

hrrr_cache_file = era5_data_dir / "hrrr_processed_cache.npz"
hrrr_ymon_snow, hrrr_ymon_rain, hrrr_weights = process_hrrr_climatology_and_weights(
    hrrr_cache_file, v2_gpkg_path
)

# %% [markdown]
# ### Step H4: Apply weights — compute HRRR area-weighted tmax per HRU per month

# %%
nhru_hrrr = len(hru_gdf)

# Default fill values for HRUs with no valid observations for a given month.
# From the original v1.1 workflow (process_era5_tmax_allstar.py, nan= argument).
# - snow_nan_default: 273.15 K (0°C, 32°F) — freezing point; a physically
#   intuitive midpoint within the snow clip range [271.04, 274.4 K].
# - rain_nan_default: 274.65 K (1.5°C, 34.7°F) — the lower bound of the rain
#   clip range [274.65, 276.48 K]; most conservative "all-rain" assumption.
snow_nan_default = 273.15  # K
rain_nan_default = 274.65  # K

hrrr_allsnow = np.full((nhru_hrrr, 12), snow_nan_default)
hrrr_allrain = np.full((nhru_hrrr, 12), rain_nan_default)

hrrr_hru_groups = hrrr_weights.groupby("model_hru_idx")

for month_idx in range(12):
    snow_flat = hrrr_ymon_snow[month_idx].flatten()
    rain_flat = hrrr_ymon_rain[month_idx].flatten()

    for hru_id, group in hrrr_hru_groups:
        grid_ids = group["grid_id"].values
        wgts = group["weight"].values

        # Snow
        vals = snow_flat[grid_ids]
        valid = (vals > 0) & ~np.isnan(vals)
        if valid.sum() > 0:
            hrrr_allsnow[int(hru_id) - 1, month_idx] = np.average(vals[valid], weights=wgts[valid])

        # Rain
        vals = rain_flat[grid_ids]
        valid = (vals > 0) & ~np.isnan(vals)
        if valid.sum() > 0:
            hrrr_allrain[int(hru_id) - 1, month_idx] = np.average(vals[valid], weights=wgts[valid])

# Convert to Fahrenheit
hrrr_allsnow_f = (hrrr_allsnow - 273.15) * 1.8 + 32.0
hrrr_allrain_f = (hrrr_allrain - 273.15) * 1.8 + 32.0
hrrr_allrain_offset = hrrr_allrain_f - hrrr_allsnow_f

# Report proportion of HRUs that retained default values (no valid observations)
snow_default_frac = (hrrr_allsnow == snow_nan_default).sum() / hrrr_allsnow.size
rain_default_frac = (hrrr_allrain == rain_nan_default).sum() / hrrr_allrain.size
print(f"HRU-months using default (no obs): snow={snow_default_frac:.2%}, rain={rain_default_frac:.2%}")

print(f"HRRR tmax_allsnow range: {np.nanmin(hrrr_allsnow_f):.2f} - {np.nanmax(hrrr_allsnow_f):.2f} °F")
print(f"HRRR tmax_allrain_offset range: {np.nanmin(hrrr_allrain_offset):.2f} - {np.nanmax(hrrr_allrain_offset):.2f} °F")

# %%
# # Daignostic block
# date = datetime(2019, 1, 15, 12)
# H = Herbie(date, model="hrrr", product="sfc", fxx=0)
# ds_csnow = H.xarray(":CSNOW:surface")
# csnow_var = [v for v in ds_csnow.data_vars if v not in ["gribfile_projection"]][0]
# csnow_vals = ds_csnow[csnow_var].values

# print(f"Variable name: {csnow_var}")
# print(f"dtype: {csnow_vals.dtype}")
# print(f"Shape: {csnow_vals.shape}")
# print(f"Unique values: {np.unique(csnow_vals)}")
# print(f"Min/Max: {csnow_vals.min()} / {csnow_vals.max()}")
# print(f"Count == 1: {(csnow_vals == 1).sum()}")
# print(f"Count == 1.0: {(csnow_vals == 1.0).sum()}")
# print(f"Count > 0: {(csnow_vals > 0).sum()}")


# %% [markdown]
# ### Step H5: Compare ERA5 vs HRRR side-by-side maps
# `tmax_allsnow` is the maximum daily temperature (°F) at which all precipitation
# is assumed to fall as snow. It is a monthly climatological value derived by
# masking 2m temperature by the categorical snow flag (CSNOW=1 in HRRR, ptype=5
# in ERA5), then computing the long-term mean for each calendar month at each
# grid cell, and finally area-weighting to each HRU.

# %%
import matplotlib.pyplot as plt

hru_map_gdf = hru_gdf.to_crs(epsg=4326).copy()

month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# January comparison (month index 0)
compare_month = 0
month_name = month_names[compare_month]

hru_map_gdf["era5_snow"] = allsnow_f[:, compare_month]
hru_map_gdf["hrrr_snow"] = hrrr_allsnow_f[:, compare_month]
hru_map_gdf["diff_snow"] = hrrr_allsnow_f[:, compare_month] - allsnow_f[:, compare_month]

fig, axes = plt.subplots(1, 3, figsize=(22, 7))

# ERA5
hru_map_gdf.plot(ax=axes[0], column="era5_snow", cmap="coolwarm", edgecolor="none",
                 legend=True, legend_kwds={"label": "°F", "shrink": 0.7})
axes[0].set_title(f"ERA5 tmax_allsnow — {month_name}")
axes[0].set_axis_off()

# HRRR
hru_map_gdf.plot(ax=axes[1], column="hrrr_snow", cmap="coolwarm", edgecolor="none",
                 legend=True, legend_kwds={"label": "°F", "shrink": 0.7})
axes[1].set_title(f"HRRR tmax_allsnow — {month_name}")
axes[1].set_axis_off()

# Difference (HRRR - ERA5)
hru_map_gdf.plot(ax=axes[2], column="diff_snow", cmap="RdBu_r", edgecolor="none",
                 legend=True, legend_kwds={"label": "°F difference", "shrink": 0.7})
axes[2].set_title(f"Difference (HRRR - ERA5) — {month_name}")
axes[2].set_axis_off()

plt.suptitle("tmax_allsnow: ERA5 (25km) vs HRRR (3km)", fontsize=14)
plt.tight_layout()
plt.show()

# %%
# Summary statistics
print(f"\n{'Month':<6} {'ERA5 mean':<12} {'HRRR mean':<12} {'Diff mean':<12} {'Diff std'}")
print("-" * 55)
for i in range(12):
    era5_mean = np.nanmean(allsnow_f[:, i])
    hrrr_mean = np.nanmean(hrrr_allsnow_f[:, i])
    diff = hrrr_allsnow_f[:, i] - allsnow_f[:, i]
    print(f"{month_names[i]:<6} {era5_mean:<12.2f} {hrrr_mean:<12.2f} {np.nanmean(diff):<12.2f} {np.nanstd(diff):.2f}")

# %%


# %% [markdown]
# ### Compare v1.1 vs v2 ERA5 tmax_allsnow (single month)

# %%
# Load v1.1 tmax_allsnow from subdomain param file and GIS
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData

v1_model_dir = pl.Path(r"D:\nhm-assist\data_dependencies\20240524_v1.1_gm_precal_williamette_river")
v1_param_file = v1_model_dir / "myparam.param"
v1_gis_file = v1_model_dir / "GIS" / "model_nhru.shp"

# Read param file with pyPRMS
prms_meta = MetaData().metadata
pdb = ParameterFile(v1_param_file, metadata=prms_meta, verbose=False)
v1_nhm_ids = pdb.get("nhm_id").data  # ordering of HRUs in the param file
v1_allsnow_vals = pdb.get("tmax_allsnow").data  # shape: (nhru, 12)

print(f"v1.1 subdomain: {len(v1_nhm_ids)} HRUs, tmax_allsnow shape: {v1_allsnow_vals.shape}")

# Load v1.1 subdomain geometry
v1_hru_gdf = gpd.read_file(v1_gis_file).to_crs(epsg=4326)

# Map nhm_id to param array index
nhm_id_to_idx = {nhm_id: idx for idx, nhm_id in enumerate(v1_nhm_ids)}
v1_hru_gdf["param_idx"] = v1_hru_gdf["nhm_id"].map(nhm_id_to_idx)

# Assign January values
compare_month = 0  # January
v1_hru_gdf["tmax_allsnow"] = v1_allsnow_vals[v1_hru_gdf["param_idx"].values, compare_month]

# v2 January values
hru_v2_map = hru_gdf.to_crs(epsg=4326).copy()
hru_v2_map["tmax_allsnow"] = allsnow_f[:, compare_month]

# Side-by-side comparison (3 panels: v1.1, v2 ERA5, v2 HRRR)
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 3, figsize=(24, 8))

month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# v2 HRRR January values
hru_v2_hrrr = hru_gdf.to_crs(epsg=4326).copy()
hru_v2_hrrr["tmax_allsnow"] = hrrr_allsnow_f[:, compare_month]

# Shared color range across all three
vmin = min(v1_hru_gdf["tmax_allsnow"].min(), hru_v2_map["tmax_allsnow"].min(), hru_v2_hrrr["tmax_allsnow"].min())
vmax = max(v1_hru_gdf["tmax_allsnow"].max(), hru_v2_map["tmax_allsnow"].max(), hru_v2_hrrr["tmax_allsnow"].max())

# Panel 1: v1.1
v1_hru_gdf.plot(ax=axes[0], column="tmax_allsnow", cmap="coolwarm", edgecolor="none",
                vmin=vmin, vmax=vmax, legend=True,
                legend_kwds={"label": "°F", "shrink": 0.7})
axes[0].set_title(f"v1.1 tmax_allsnow — {month_names[compare_month]}")
axes[0].set_axis_off()

# Panel 2: v2 ERA5
hru_v2_map.plot(ax=axes[1], column="tmax_allsnow", cmap="coolwarm", edgecolor="none",
                vmin=vmin, vmax=vmax, legend=True,
                legend_kwds={"label": "°F", "shrink": 0.7})
v1_hru_gdf.dissolve().boundary.plot(ax=axes[1], color="black", linewidth=1.5)
v1_bounds = v1_hru_gdf.total_bounds
axes[1].set_xlim(v1_bounds[0] - 0.1, v1_bounds[2] + 0.1)
axes[1].set_ylim(v1_bounds[1] - 0.1, v1_bounds[3] + 0.1)
axes[1].set_title(f"v2 (ERA5) tmax_allsnow — {month_names[compare_month]}")
axes[1].set_axis_off()

# Panel 3: v2 HRRR
hru_v2_hrrr.plot(ax=axes[2], column="tmax_allsnow", cmap="coolwarm", edgecolor="none",
                 vmin=vmin, vmax=vmax, legend=True,
                 legend_kwds={"label": "°F", "shrink": 0.7})
v1_hru_gdf.dissolve().boundary.plot(ax=axes[2], color="black", linewidth=1.5)
axes[2].set_xlim(v1_bounds[0] - 0.1, v1_bounds[2] + 0.1)
axes[2].set_ylim(v1_bounds[1] - 0.1, v1_bounds[3] + 0.1)
axes[2].set_title(f"v2 (HRRR) tmax_allsnow — {month_names[compare_month]}")
axes[2].set_axis_off()

plt.suptitle("tmax_allsnow: NHM v1.1 vs OHM v2 (ERA5) vs OHM v2 (HRRR)", fontsize=14)
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Compare v1.1 vs v2 ERA5 tmax_allrain_offset (single month)

# %% jupyter={"source_hidden": true}
# v1.1 tmax_allrain_offset from param file
v1_allrain_offset_vals = pdb.get("tmax_allrain_offset").data  # shape: (nhru, 12)
v1_hru_gdf["tmax_allrain_offset"] = v1_allrain_offset_vals[v1_hru_gdf["param_idx"].values, compare_month]

# v2 ERA5
hru_v2_map["tmax_allrain_offset"] = allrain_offset[:, compare_month]

# v2 HRRR
hru_v2_hrrr["tmax_allrain_offset"] = hrrr_allrain_offset[:, compare_month]

# Shared color range
vmin_off = min(v1_hru_gdf["tmax_allrain_offset"].min(), hru_v2_map["tmax_allrain_offset"].min(), hru_v2_hrrr["tmax_allrain_offset"].min())
vmax_off = max(v1_hru_gdf["tmax_allrain_offset"].max(), hru_v2_map["tmax_allrain_offset"].max(), hru_v2_hrrr["tmax_allrain_offset"].max())

fig, axes = plt.subplots(1, 3, figsize=(24, 8))

# Panel 1: v1.1
v1_hru_gdf.plot(ax=axes[0], column="tmax_allrain_offset", cmap="coolwarm", edgecolor="none",
                vmin=vmin_off, vmax=vmax_off, legend=True,
                legend_kwds={"label": "°F", "shrink": 0.7})
axes[0].set_title(f"v1.1 tmax_allrain_offset — {month_names[compare_month]}")
axes[0].set_axis_off()

# Panel 2: v2 ERA5
hru_v2_map.plot(ax=axes[1], column="tmax_allrain_offset", cmap="coolwarm", edgecolor="none",
                vmin=vmin_off, vmax=vmax_off, legend=True,
                legend_kwds={"label": "°F", "shrink": 0.7})
v1_hru_gdf.dissolve().boundary.plot(ax=axes[1], color="black", linewidth=1.5)
axes[1].set_xlim(v1_bounds[0] - 0.1, v1_bounds[2] + 0.1)
axes[1].set_ylim(v1_bounds[1] - 0.1, v1_bounds[3] + 0.1)
axes[1].set_title(f"v2 (ERA5) tmax_allrain_offset — {month_names[compare_month]}")
axes[1].set_axis_off()

# Panel 3: v2 HRRR
hru_v2_hrrr.plot(ax=axes[2], column="tmax_allrain_offset", cmap="coolwarm", edgecolor="none",
                 vmin=vmin_off, vmax=vmax_off, legend=True,
                 legend_kwds={"label": "°F", "shrink": 0.7})
v1_hru_gdf.dissolve().boundary.plot(ax=axes[2], color="black", linewidth=1.5)
axes[2].set_xlim(v1_bounds[0] - 0.1, v1_bounds[2] + 0.1)
axes[2].set_ylim(v1_bounds[1] - 0.1, v1_bounds[3] + 0.1)
axes[2].set_title(f"v2 (HRRR) tmax_allrain_offset — {month_names[compare_month]}")
axes[2].set_axis_off()

plt.suptitle("tmax_allrain_offset: NHM v1.1 vs OHM v2 (ERA5) vs OHM v2 (HRRR)", fontsize=14)
plt.tight_layout()
plt.show()

# %%

# %% [markdown]
# ### Interactive comparison: v1.1 vs v2 ERA5 vs v2 HRRR (folium)

# %% jupyter={"source_hidden": true}
import folium
from branca.colormap import LinearColormap

# Shared colormap
cmap_allsnow = LinearColormap(
    colors=["blue", "cyan", "yellow", "orange", "red"],
    vmin=vmin,
    vmax=vmax,
    caption=f"tmax_allsnow (°F) — {month_names[compare_month]}",
)

# Center on v1.1 domain
center_lat = (v1_bounds[1] + v1_bounds[3]) / 2
center_lon = (v1_bounds[0] + v1_bounds[2]) / 2

m = folium.Map(location=[center_lat, center_lon], zoom_start=8, tiles="CartoDB positron")

folium.TileLayer(
    tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attr="OpenTopoMap",
    name="OpenTopoMap",
    show=False,
).add_to(m)

# Layer: v1.1
folium.GeoJson(
    v1_hru_gdf[["nhm_id", "tmax_allsnow", "geometry"]].to_json(),
    name=f"v1.1 tmax_allsnow ({month_names[compare_month]})",
    style_function=lambda f: {
        "fillColor": cmap_allsnow(f["properties"]["tmax_allsnow"]) if f["properties"]["tmax_allsnow"] is not None else "gray",
        "color": "black",
        "weight": 0.2,
        "fillOpacity": 0.7,
    },
    tooltip=folium.GeoJsonTooltip(fields=["nhm_id", "tmax_allsnow"]),
    show=True,
).add_to(m)

# Clip v2 data to v1.1 domain extent for faster rendering
v1_envelope = v1_hru_gdf.dissolve().geometry.values[0].envelope
hru_v2_map_clipped = hru_v2_map[hru_v2_map.intersects(v1_envelope)].copy()
hru_v2_hrrr_clipped = hru_v2_hrrr[hru_v2_hrrr.intersects(v1_envelope)].copy()

# Layer: v2 ERA5
folium.GeoJson(
    hru_v2_map_clipped[["model_hru_idx", "tmax_allsnow", "geometry"]].to_json(),
    name=f"v2 ERA5 tmax_allsnow ({month_names[compare_month]})",
    style_function=lambda f: {
        "fillColor": cmap_allsnow(f["properties"]["tmax_allsnow"]) if f["properties"]["tmax_allsnow"] is not None else "gray",
        "color": "black",
        "weight": 0.2,
        "fillOpacity": 0.7,
    },
    tooltip=folium.GeoJsonTooltip(fields=["model_hru_idx", "tmax_allsnow"]),
    show=False,
).add_to(m)

# Layer: v2 HRRR
folium.GeoJson(
    hru_v2_hrrr_clipped[["model_hru_idx", "tmax_allsnow", "geometry"]].to_json(),
    name=f"v2 HRRR tmax_allsnow ({month_names[compare_month]})",
    style_function=lambda f: {
        "fillColor": cmap_allsnow(f["properties"]["tmax_allsnow"]) if f["properties"]["tmax_allsnow"] is not None else "gray",
        "color": "black",
        "weight": 0.2,
        "fillOpacity": 0.7,
    },
    tooltip=folium.GeoJsonTooltip(fields=["model_hru_idx", "tmax_allsnow"]),
    show=False,
).add_to(m)

cmap_allsnow.add_to(m)
folium.LayerControl().add_to(m)
m

# %%

# %% [markdown]
# ### Write final parameters using HRRR-derived values
# The HRRR-derived values better represent the physiography of the landscape
# compared to ERA5, which shows grid-like artifacts from the coarser resolution.
# Overwriting the ERA5 output files with HRRR results.

# %%
# Compute HRRR allrain_offset
hrrr_allrain_offset_final = hrrr_allrain_f - hrrr_allsnow_f

print("Writing HRRR-derived parameters (replacing ERA5 output):")
print(f"  tmax_allsnow range: {np.nanmin(hrrr_allsnow_f):.2f} - {np.nanmax(hrrr_allsnow_f):.2f} °F")
print(f"  tmax_allrain_offset range: {np.nanmin(hrrr_allrain_offset_final):.2f} - {np.nanmax(hrrr_allrain_offset_final):.2f} °F")

write_param_csv(output_dir / "tmax_allsnow.csv", "tmax_allsnow", hrrr_allsnow_f)
write_param_csv(output_dir / "tmax_allrain_offset.csv", "tmax_allrain_offset", hrrr_allrain_offset_final)

print(f"\nFinal parameters written to {output_dir}")
print("Source: HRRR 3km (2014-09 to 2026-09)")

# %%
