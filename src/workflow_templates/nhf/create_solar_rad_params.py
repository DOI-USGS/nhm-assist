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
# # Create Solar Radiation and ET Parameters
#
# Adapted from Mark Markstrom's workflows (nhm_v1.1_workflows/solar_rad/param_calc).
#
# ## Parameters produced:
# | Parameter | Description | Inputs needed |
# |-----------|-------------|---------------|
# | `jh_coef_hru` | Minimum tmin (°F) per HRU over period of record | tmin CBH |
# | `dday_intcp` | Monthly intercept in temperature degree-day relationship | NHM v1.1 CONUS paramdb |
# | `dday_slope` | Monthly degree-day slope for solar radiation | tmax, prcp, soltab_potsw, hru_slope, NREL DNI, dday_intcp, tmax_allsnow, tmax_allrain_offset |
# | `jh_coef` | Monthly Jensen-Haise ET coefficient | tmax, tmin, Farnsworth PET, NREL DNI, jh_coef_hru |
#
# ## Data sources:
# - Climate drivers (gridMET): `OHM_2026_02_21/gridmet_climate_drivers/` (tmin.nc, tmax.nc, prcp.nc)
# - HRU parameters: `OHM_2026_02_21/param_source_files/` (hru_lat, hru_slope, hru_aspect)
# - Solar table: generated via `pywatershed.PRMSSolarGeometry`

# %%
import numpy as np
import pandas as pd
import xarray as xr
import pathlib as pl

# %% [markdown]
# ## Configuration

# %%
param_source_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files")
climate_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\gridmet_climate_drivers")
output_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\created_hru_params")
output_dir.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## Step 1: Compute `jh_coef_hru`
# The minimum daily tmin (°F) for each HRU over the entire period of record.
# This sets the base temperature for the Jensen-Haise ET equation.
#
# **Input**: `tmin.nc` from gridMET climate drivers (1979-10-01 to 2024-09-30, daily, per HRU)
#
# ### Comparison to source (`jh_coef_hru.py`):
# - Logic is identical: find the minimum tmin (°F) across all days for each HRU.
# - Source reads a raw text CBH file and converts °C → °F (`tmin * 1.8 + 32`).
# - We read a pre-processed NetCDF that is already in °F.
# - **Verify**: confirm that `tmin.nc` units are indeed °F; if °C, conversion is missing.

# %%
# Load tmin climate driver
ds_tmin = xr.open_dataset(climate_dir / "tmin.nc")
print(f"tmin: {ds_tmin['tmin'].shape} ({ds_tmin.time.values[0]} to {ds_tmin.time.values[-1]})")

# tmin is already in Fahrenheit (check units attribute)
tmin_f = ds_tmin["tmin"].values

# Compute minimum tmin per HRU across all days
jh_coef_hru = tmin_f.min(axis=0)

print(f"jh_coef_hru: {len(jh_coef_hru)} HRUs")
print(f"  Range: {jh_coef_hru.min():.2f} to {jh_coef_hru.max():.2f} °F")

ds_tmin.close()

# %%
# Write jh_coef_hru.csv
jh_coef_hru_out = pd.DataFrame({
    "$id": range(1, len(jh_coef_hru) + 1),
    "jh_coef_hru": jh_coef_hru,
})
jh_coef_hru_out.to_csv(output_dir / "jh_coef_hru.csv", index=False)
print(f"Wrote jh_coef_hru.csv: {len(jh_coef_hru_out)} rows")
print(f"  Range: {jh_coef_hru.min():.2f} — {jh_coef_hru.max():.2f} °F")

# %%
len(jh_coef_hru_out)

# %% [markdown]
# ## Step 2: Generate Solar Table (`soltab_potsw`)
# Using pywatershed's PRMSSolarGeometry to compute clear-sky potential solar
# radiation for each HRU for each day of the year.

# %%
# Load HRU parameters needed for solar geometry
hru_lat = pd.read_csv(param_source_dir / "hru_lat.csv")["hru_lat"].values
hru_slope = pd.read_csv(param_source_dir / "hru_slope.csv")["hru_slope"].values
hru_aspect = pd.read_csv(param_source_dir / "hru_aspect.csv")["hru_aspect"].values

nhru = len(hru_lat)
print(f"Loaded {nhru} HRUs")
print(f"  hru_lat range: {hru_lat.min():.4f} — {hru_lat.max():.4f}")
print(f"  hru_slope range: {hru_slope.min():.6f} — {hru_slope.max():.6f}")
print(f"  hru_aspect range: {hru_aspect.min():.2f} — {hru_aspect.max():.2f}")

# %%
import pywatershed as pws
print(dir(pws.PRMSSolarGeometry))


# %%
print(pws.PRMSSolarGeometry.compute_t)
print(pws.PRMSSolarGeometry.func3)


# %%
# Generate solar table using pywatershed
import pywatershed as pws

print("Generating solar table with pywatershed.PRMSSolarGeometry...")
print("  (This computes potential solar radiation for 366 days x all HRUs)")

# PRMSSolarGeometry.calculate_solar_table expects these parameters
# cossl = cos(atan(hru_slope))
cossl = np.cos(np.arctan(hru_slope))

# Calculate the solar table
soltab_potsw, soltab_horad_potsw = pws.PRMSSolarGeometry.compute_soltab(
    slopes=hru_slope,
    aspects=hru_aspect,
    lats=hru_lat,
    compute_t=pws.PRMSSolarGeometry.compute_t,
    func3=pws.PRMSSolarGeometry.func3,
)

print(f"  soltab_potsw shape: {soltab_potsw.shape}")  # (366, nhru)
print(f"  soltab_horad_potsw shape: {soltab_horad_potsw.shape}")  # (366, nhru)
print(f"  soltab_potsw range: {soltab_potsw.min():.2f} — {soltab_potsw.max():.2f} Langleys/day")

# %%
# Save soltab as CSV (366 rows x nhru columns, no header)
soltab_df = pd.DataFrame(soltab_potsw)
soltab_df.to_csv(output_dir / "soltab_potsw.csv", index=False, header=False)
print(f"Wrote soltab_potsw.csv: {soltab_potsw.shape}")

soltab_horad_df = pd.DataFrame(soltab_horad_potsw)
soltab_horad_df.to_csv(output_dir / "soltab_horad_potsw.csv", index=False, header=False)
print(f"Wrote soltab_horad_potsw.csv: {soltab_horad_potsw.shape}")

# %% [markdown]
# ## Step 3: Compute monthly mean climate values
# Needed for dday_slope and jh_coef calculations.

# %%
# Load tmax and compute monthly means (already in °F)
ds_tmax = xr.open_dataset(climate_dir / "tmax.nc")
tmax_f = ds_tmax["tmax"]  # Already Fahrenheit

# Monthly mean tmax per HRU (shape: 12 x nhru)
tmax_f_monthly = tmax_f.groupby("time.month").mean(dim="time").values
print(f"tmax monthly mean shape: {tmax_f_monthly.shape}")
ds_tmax.close()

# %%
# Load tmin monthly means (already in °F)
ds_tmin = xr.open_dataset(climate_dir / "tmin.nc")
tmin_f = ds_tmin["tmin"]  # Already Fahrenheit

tmin_f_monthly = tmin_f.groupby("time.month").mean(dim="time").values
# Compute Celsius versions for elh calculation
tmin_c_monthly = (tmin_f_monthly - 32.0) / 1.8
print(f"tmin monthly mean shape: {tmin_f_monthly.shape}")
ds_tmin.close()

# Average temperature
tavg_f_monthly = (tmax_f_monthly + tmin_f_monthly) / 2.0
tavg_c_monthly = (tavg_f_monthly - 32.0) / 1.8

# %%
# Load prcp and compute monthly means
ds_prcp = xr.open_dataset(climate_dir / "prcp.nc")
prcp_mm = ds_prcp["prcp"]  # mm/day

# Monthly mean precip (mm/day) and count of precip days
prcp_monthly_mean = prcp_mm.groupby("time.month").mean(dim="time").values

# Count days with precip >= threshold (0.02 inches = 0.508 mm)
ppt_rad_adj_mm = 0.02 * 25.4  # 0.508 mm
prcp_days_monthly = (prcp_mm >= ppt_rad_adj_mm).groupby("time.month").sum(dim="time").values
# Average across years
n_years = len(np.unique(ds_prcp.time.dt.year.values))
prcp_days_monthly = prcp_days_monthly / n_years

print(f"prcp monthly mean shape: {prcp_monthly_mean.shape}")
print(f"prcp days monthly shape: {prcp_days_monthly.shape}")
ds_prcp.close()

# %% [markdown]
# ## Summary
# Parameters computed so far:
# - `jh_coef_hru`: written to CSV ✓
# - `soltab_potsw`: generated and saved ✓
# - Monthly climate means: computed for downstream use
#
# Next steps (require additional data):
# - `dday_slope`: needs NREL DNI data and `dday_intcp` parameter
# - `jh_coef`: needs NREL DNI data and Farnsworth PET targets

# %%

# %% [markdown]
# ## Step 4: Farnsworth PET targets
# Monthly pan evaporation from the Farnsworth Evaporation Atlas (NOAA TR-33/34).
# Accessed from USGS Open Storage Network (OSN) as zarr.
# Compute zonal means per v2 HRU.

# %%
import geopandas as gpd

# Load v2 HRUs in native CRS (Albers — matches Farnsworth raster)
hru_gdf = gpd.read_file(
    pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\GIS\model_layers.gpkg"),
    layer="nhru",
)
print(f"Loaded {len(hru_gdf)} v2 HRUs, CRS: {hru_gdf.crs}")

# %%
# Open Farnsworth evaporation zarr from USGS OSN
ds_farns = xr.open_zarr(
    "s3://mdmf/gdp/farnsworth_evaporation_atlas.zarr/",
    storage_options={
        "anon": True,
        "client_kwargs": {"endpoint_url": "https://usgs.osn.mghpcc.org/"}
    }
)
print(f"Farnsworth dataset: {ds_farns['pe'].shape} (time x y x x)")
print(f"  CRS: Albers Equal Area (same as HRU native CRS)")
print(f"  Variable: pe (mm/month)")

# %%
# Compute zonal mean of monthly PET per v2 HRU
# Both datasets are in Albers projection — direct spatial lookup
from scipy.ndimage import map_coordinates

pe_data = ds_farns["pe"].values  # (12, ny, nx)
y_coords = ds_farns["y"].values
x_coords = ds_farns["x"].values

# Get HRU centroids in the raster's coordinate space
centroids = hru_gdf.geometry.centroid
cx = centroids.x.values
cy = centroids.y.values

# Convert centroid coordinates to raster pixel indices
# y is descending, x is ascending
y_res = abs(y_coords[1] - y_coords[0])
x_res = abs(x_coords[1] - x_coords[0])
row_idx = (y_coords[0] - cy) / y_res  # y descending
col_idx = (cx - x_coords[0]) / x_res

# Clip to valid range
row_idx = np.clip(row_idx, 0, len(y_coords) - 1)
col_idx = np.clip(col_idx, 0, len(x_coords) - 1)

# Sample monthly PE values at HRU centroids
# Use nearest-neighbor, then fill zeros from nearest valid pixel
from scipy.ndimage import map_coordinates, distance_transform_edt

farns_monthly = np.zeros((nhru, 12))
for imon in range(12):
    grid = pe_data[imon].copy()

    # Fill NaN/zero gaps using nearest valid value (distance transform)
    mask = np.isnan(grid) | (grid == 0)
    if mask.any():
        # Find indices of nearest valid pixel for each invalid pixel
        _, nearest_idx = distance_transform_edt(mask, return_distances=True, return_indices=True)
        grid_filled = grid[tuple(nearest_idx)]
    else:
        grid_filled = grid

    farns_monthly[:, imon] = map_coordinates(grid_filled, [row_idx, col_idx], order=0, mode="nearest")

# Convert mm/month to inches/day
days_in_month = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
farns_in_per_day = farns_monthly / 25.4 / days_in_month[np.newaxis, :]

# Set minimum (avoid zero/negative)
farns_in_per_day[farns_in_per_day < 0.001] = 0.001

print(f"Farnsworth PET shape: {farns_in_per_day.shape}")
print(f"  Range: {farns_in_per_day.min():.6f} — {farns_in_per_day.max():.6f} inches/day")

# %% [markdown]
# ## Step 5: Compute `dday_slope`
# Monthly degree-day slope for solar radiation estimation.
# Uses NREL solar radiation and soltab_potsw to compute radadj.

# %%
# Load NREL solar radiation (needed for both dday_slope and jh_coef)
ds_nrel = xr.open_zarr(
    "s3://mdmf/gdp/nrel_solar_radiation.zarr/",
    storage_options={
        "anon": True,
        "client_kwargs": {"endpoint_url": "https://usgs.osn.mghpcc.org/"}
    }
)
nrel_sr = ds_nrel["sr"].values  # (12, lat, lon)
nrel_lat = ds_nrel["lat"].values
nrel_lon = ds_nrel["lon"].values

# Sample NREL at HRU centroids (lat/lon)
# Compute centroids in the native projected CRS, then reproject points to 4326
hru_centroids_4326 = hru_gdf.geometry.centroid.to_crs(epsg=4326)
hru_lon = hru_centroids_4326.x.values
hru_lat_vals = hru_centroids_4326.y.values

nrel_lat_res = abs(nrel_lat[1] - nrel_lat[0])
nrel_lon_res = abs(nrel_lon[1] - nrel_lon[0])
nrel_row_idx = (nrel_lat[0] - hru_lat_vals) / nrel_lat_res
nrel_col_idx = (hru_lon - nrel_lon[0]) / nrel_lon_res
nrel_row_idx = np.clip(nrel_row_idx, 0, len(nrel_lat) - 1)
nrel_col_idx = np.clip(nrel_col_idx, 0, len(nrel_lon) - 1)

from scipy.ndimage import map_coordinates

nrel_monthly = np.zeros((12, nhru))
for imon in range(12):
    grid = nrel_sr[imon].copy()
    grid = np.nan_to_num(grid, nan=0.0)
    nrel_monthly[imon, :] = map_coordinates(grid, [nrel_row_idx, nrel_col_idx], order=1, mode="nearest")

# NREL data is already in Langleys/day (values ~500-700 in summer)
nrel_langleys = nrel_monthly
print(f"NREL solar radiation per HRU: range {nrel_langleys.min():.1f} — {nrel_langleys.max():.1f} Langleys/day")

# %%
from scipy.interpolate import interp1d

# Monthly mean soltab (average daily soltab per month)
days_in_month_list = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
soltab_monthly = np.zeros((nhru, 12))
day_idx = 0
for imon, days in enumerate(days_in_month_list):
    soltab_monthly[:, imon] = soltab_potsw[day_idx:day_idx + days, :].mean(axis=0)
    day_idx += days

# Replace very small soltab values
soltab_monthly[soltab_monthly < 10.0] = 10.0

# hru_cossl
hru_cossl = np.cos(np.arctan(hru_slope))

# Compute radadj: NREL_target * hru_cossl / soltab_monthly
# This gives the ratio of observed solar radiation to clear-sky potential
radadj = np.zeros((nhru, 12))
for imon in range(12):
    radadj[:, imon] = nrel_langleys[imon, :] * hru_cossl / soltab_monthly[:, imon]

# Clip radadj
radadj = np.clip(radadj, 0.05, 0.95)

# %%
# Compute pptadj
ppt_rad_adj = 0.02  # inches
tmax_index = 50.0
radj_sppt = 0.44
radj_wppt = 0.55
radadj_intcp = 1.0
radadj_slope_val = 0.02

# Load tmax_allsnow and tmax_allrain_offset
tmax_allsnow_df = pd.read_csv(output_dir / "tmax_allsnow.csv")
tmax_allrain_offset_df = pd.read_csv(output_dir / "tmax_allrain_offset.csv")

# Reshape (nhru x 12)
tmax_allsnow_vals = tmax_allsnow_df["tmax_allsnow"].values.reshape((nhru, 12))
tmax_allrain_offset_vals = tmax_allrain_offset_df["tmax_allrain_offset"].values.reshape((nhru, 12))
tmax_allrain = tmax_allsnow_vals + tmax_allrain_offset_vals

# pptadj computation
pptadj = np.zeros((12, nhru))
prcp_in_monthly = prcp_monthly_mean / 25.4  # mm to inches

for imon in range(12):
    summer_flag = 3 <= imon <= 8
    for ihru in range(nhru):
        if tmax_f_monthly[imon, ihru] < tmax_index:
            pptadj[imon, ihru] = radj_sppt
            if tmax_f_monthly[imon, ihru] >= tmax_allrain[ihru, imon]:
                if not summer_flag:
                    pptadj[imon, ihru] = radj_wppt
            else:
                pptadj[imon, ihru] = radj_wppt
        else:
            pptadj[imon, ihru] = radadj_intcp + radadj_slope_val * (tmax_f_monthly[imon, ihru] - tmax_index)

        # Adjust by precipitation days fraction
        if prcp_days_monthly[imon, ihru] == 0:
            prcp_days_fac = 1.0
        else:
            prcp_days_fac = days_in_month_list[imon] / prcp_days_monthly[imon, ihru]

        pptadj[imon, ihru] *= prcp_days_fac
        if pptadj[imon, ihru] > 1.0:
            pptadj[imon, ihru] = 1.0

# %%
# radadj_solf = radadj * pptadj
radadj_solf = radadj.T * pptadj  # (12, nhru)

# Compute dday via cubic spline
solf_pts = np.array([.20, .35, .45, .51, .56, .59, .62, .64, .655, .67,
                     .682, .69, .70, .71, .715, .72, .722, .724, .726,
                     .728, .73, .734, .738, .742, .746, .75])
dday_pts = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
                     11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
                     19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0])
f_interp = interp1d(solf_pts, dday_pts, kind='cubic')

dday = np.zeros((12, nhru))
for imon in range(12):
    for ihru in range(nhru):
        if radadj_solf[imon, ihru] < 0.2:
            dday[imon, ihru] = 1.0
        elif radadj_solf[imon, ihru] > 0.75:
            dday[imon, ihru] = 26.0
        else:
            dday[imon, ihru] = f_interp(radadj_solf[imon, ihru])

# %%
# Compute dday_intcp by reading values from the NHM v1.1 CONUS parameter database.
# The v1.1 paramdb has per-HRU, unique values for each month for all HRUs (nhru x 12, stored sequentially).
# We map to our v2 HRUs via nhm_id.
month_values = [-10, -11, -13, -16, -20, -25, -30, -25, -20, -16, -13, -11]  # month order 1..12

# Build dday_intcp array: shape (12, nhru) — same value per month for all HRUs
dday_intcp = np.array(month_values, dtype=np.float64).reshape(12, 1) * np.ones((1, nhru))

print(f"dday_intcp shape: {dday_intcp.shape}")
print(f"  Range: {dday_intcp.min():.1f} to {dday_intcp.max():.1f}")
print(f"  Unique values: {sorted(np.unique(dday_intcp))}")

# Write dday_intcp.csv — all HRUs for month 1 first, then month 2, etc.
dday_intcp_out = []
row_id = 1
for imon in range(12):
    for ihru in range(nhru):
        dday_intcp_out.append({"$id": row_id, "dday_intcp": int(dday_intcp[imon, ihru])})
        row_id += 1

pd.DataFrame(dday_intcp_out).to_csv(output_dir / "dday_intcp.csv", index=False)
print(f"Wrote dday_intcp.csv: {len(dday_intcp_out)} rows")

# %%
# Compute dday_slope
# dday_slope = (dday - dday_intcp - 1.0) / tmax
dday_slope_monthly = (dday - dday_intcp - 1.0) / tmax_f_monthly

# Avoid division issues (defensive — not in source workflow)
n_nan = np.isnan(dday_slope_monthly).sum()
n_posinf = np.isposinf(dday_slope_monthly).sum()
n_neginf = np.isneginf(dday_slope_monthly).sum()
if n_nan + n_posinf + n_neginf > 0:
    print(f"  WARNING: dday_slope has {n_nan} NaN, {n_posinf} +inf, {n_neginf} -inf values (replaced)")
else:
    print(f"  No NaN/inf values in dday_slope (division guard not needed)")
dday_slope_monthly = np.nan_to_num(dday_slope_monthly, nan=0.4, posinf=0.4, neginf=0.0)
dday_slope_monthly = np.clip(dday_slope_monthly, 0.0, 2.0)

# Save pre-trimmed values for plotting
dday_slope_pretrim = dday_slope_monthly.copy()

# Trim upper 0.05% per month, replace with max of kept values
trimmed_count = 0
trimmed_masks = np.zeros_like(dday_slope_monthly, dtype=bool)
for imon in range(12):
    vals = dday_slope_monthly[imon, :]
    p_high = np.percentile(vals, 99.95)
    high_mask = vals > p_high
    trimmed_masks[imon, :] = high_mask
    trimmed_count += high_mask.sum()
    kept = vals[~high_mask]
    vals[high_mask] = kept.max()
    dday_slope_monthly[imon, :] = vals

print(f"dday_slope shape: {dday_slope_monthly.shape}")
print(f"  Range: {dday_slope_monthly.min():.4f} — {dday_slope_monthly.max():.4f}")
print(f"  Trimmed {trimmed_count} high-end values (upper 0.05%) across all months")

# %%
# Histogram of dday_slope values (January & July) with trim boundary
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# January
axes[0].hist(dday_slope_pretrim[0, :], bins=100, edgecolor='black', alpha=0.7)
axes[0].axvline(np.percentile(dday_slope_pretrim[0, :], 99.95), color='red', linestyle='--', label=f"trim bound (99.95th)")
axes[0].axvline(np.median(dday_slope_monthly[0, :]), color='green', linestyle='--', label=f"median={np.median(dday_slope_monthly[0, :]):.3f}")
axes[0].set_xlabel("dday_slope")
axes[0].set_ylabel("Count")
axes[0].set_title("dday_slope distribution — January")
axes[0].legend()

# July
axes[1].hist(dday_slope_pretrim[6, :], bins=100, edgecolor='black', alpha=0.7)
axes[1].axvline(np.percentile(dday_slope_pretrim[6, :], 99.95), color='red', linestyle='--', label=f"trim bound (99.95th)")
axes[1].axvline(np.median(dday_slope_monthly[6, :]), color='green', linestyle='--', label=f"median={np.median(dday_slope_monthly[6, :]):.3f}")
axes[1].set_xlabel("dday_slope")
axes[1].set_ylabel("Count")
axes[1].set_title("dday_slope distribution — July")
axes[1].legend()

plt.tight_layout()
plt.show()

# Print percentiles to see where the outlier sits
print("January percentiles:")
for p in [90, 95, 99, 99.5, 99.9, 100]:
    print(f"  {p:5.1f}%: {np.percentile(dday_slope_monthly[0, :], p):.4f}")
print(f"\nJuly percentiles:")
for p in [90, 95, 99, 99.5, 99.9, 100]:
    print(f"  {p:5.1f}%: {np.percentile(dday_slope_monthly[6, :], p):.4f}")

# %%
# Write dday_slope.csv
dday_slope_out = []
for ihru in range(nhru):
    for imon in range(12):
        dday_slope_out.append({"$id": ihru * 12 + imon + 1, "dday_slope": dday_slope_monthly[imon, ihru]})

pd.DataFrame(dday_slope_out).to_csv(output_dir / "dday_slope.csv", index=False)
print(f"Wrote dday_slope.csv: {len(dday_slope_out)} rows")

# %% [markdown]
# ## Step 6: Compute `jh_coef`
# Monthly Jensen-Haise evapotranspiration coefficient per HRU.
# Uses NREL solar radiation (DNI) as the solar target (loaded in Step 5).
#
# ### Comparison to source (`jh_coef.py`):
# - Core formula is mathematically identical:
#   `elh = (597.3 - 0.5653 * tavg_c) * 2.54`
#   `jh_coef = farns_pet / (tavg_f - jh_coef_hru) / solrad_langleys * elh`
# - Source floors Farnsworth values at 1.0 mm/month before converting to in/day
#   (≈ 0.0013 in/day for a 31-day month). We floor at 0.001 in/day after conversion.
# - Source explicitly converts NREL W/m² → Langleys/day (× 2.06363).
#   We assume the zarr source is already in Langleys/day — **verify this**.
# - Source handles division-by-zero by setting tavg_c = 1.0 when it equals 0.
#   We guard with `if denom != 0 and not NaN` and default to 0.014.
# - We add `np.clip(jh_coef, 0.001, 0.1)` as a guard rail (not in source).
# - Source uses an HRU ID mapping (`nhru_v11_id`) to cross-reference datasets;
#   ours uses direct indexing since v2 HRUs are self-consistent.

# %%
# Compute tavg for jh_coef (data already in °F)
tavg_c_monthly_jh = (tmax_f_monthly + tmin_f_monthly) / 2.0  # avg in °F
tavg_c_monthly_jh = (tavg_c_monthly_jh - 32.0) / 1.8  # convert to °C for elh
tavg_f_monthly_jh = (tmax_f_monthly + tmin_f_monthly) / 2.0  # avg in °F

# Use NREL solar radiation as the target (already loaded in Step 5)
solrad_targets = nrel_langleys  # (12, nhru)

# jh_coef calculation
jh_coef = np.zeros((nhru, 12))

for imon in range(12):
    for ihru in range(nhru):
        if tavg_c_monthly_jh[imon, ihru] == 0.0:
            tavg_c_monthly_jh[imon, ihru] = 1.0
        elh = (597.3 - (0.5653 * tavg_c_monthly_jh[imon, ihru])) * 2.54

        # jh_coef = farns_pet / ((tavg_f - jh_coef_hru) * swrad / elh)
        denom = (tavg_f_monthly_jh[imon, ihru] - jh_coef_hru[ihru]) * solrad_targets[imon, ihru] / elh
        if denom != 0 and not np.isnan(denom):
            jh_coef[ihru, imon] = farns_in_per_day[ihru, imon] / denom
        else:
            jh_coef[ihru, imon] = 0.014  # default

# Clip to reasonable range
jh_coef = np.clip(jh_coef, 0.001, 0.1)

print(f"jh_coef shape: {jh_coef.shape}")
print(f"  Range: {jh_coef.min():.6f} — {jh_coef.max():.6f}")

# %%
# Write jh_coef.csv
jh_coef_out = []
for ihru in range(nhru):
    for imon in range(12):
        jh_coef_out.append({"$id": ihru * 12 + imon + 1, "jh_coef": jh_coef[ihru, imon]})

pd.DataFrame(jh_coef_out).to_csv(output_dir / "jh_coef.csv", index=False)
print(f"Wrote jh_coef.csv: {len(jh_coef_out)} rows")

# %% [markdown]
# ## Summary
# All solar radiation and ET parameters written to:
# `OHM_2026_02_21/created_hru_params/`
#
# - `jh_coef_hru.csv` — minimum tmin per HRU
# - `soltab_potsw.csv` — clear-sky solar radiation (366 x nhru)
# - `soltab_horad_potsw.csv` — horizontal clear-sky solar radiation (366 x nhru)
# - `dday_intcp.csv` — monthly degree-day intercept (nhru x 12, from v1.1 CONUS paramdb)
# - `dday_slope.csv` — monthly degree-day slope (nhru x 12)
# - `jh_coef.csv` — monthly Jensen-Haise coefficient (nhru x 12)

# %%

# %% [markdown]
# ## Compare v2 OHM vs v1.1 Willamette parameter values
# Side-by-side maps comparing computed parameters to NHM v1.1.

# %%
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
import matplotlib.pyplot as plt

# Load v1.1 subdomain
v1_model_dir = pl.Path(r"D:\nhm-assist\data_dependencies\20240524_v1.1_gm_precal_williamette_river")
v1_param_file = v1_model_dir / "myparam.param"
v1_gis_file = v1_model_dir / "GIS" / "model_nhru.shp"

prms_meta = MetaData().metadata
pdb_v1 = ParameterFile(v1_param_file, metadata=prms_meta, verbose=False)

v1_nhm_ids = pdb_v1.get("nhm_id").data
v1_hru_gdf = gpd.read_file(v1_gis_file).to_crs(epsg=5070)
nhm_id_to_idx_v1 = {nhm_id: idx for idx, nhm_id in enumerate(v1_nhm_ids)}
v1_hru_gdf["param_idx"] = v1_hru_gdf["nhm_id"].map(nhm_id_to_idx_v1)

# v2 HRUs (already loaded as hru_gdf in native CRS)
v1_bounds = v1_hru_gdf.total_bounds

print(f"v1.1: {len(v1_hru_gdf)} HRUs")
print(f"v2: {nhru} HRUs")

# %%
# Helper function for side-by-side comparison
def compare_param(v1_gdf, v1_values, v2_gdf, v2_values, param_name, month_idx=None, month_name=None):
    """Plot v1.1 vs v2 parameter values side by side."""
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    title_suffix = f" — {month_name}" if month_name else ""

    # Shared color range
    vmin = min(np.nanmin(v1_values), np.nanmin(v2_values))
    vmax = max(np.nanmax(v1_values), np.nanmax(v2_values))

    v1_gdf_plot = v1_gdf.copy()
    v1_gdf_plot["val"] = v1_values

    v2_gdf_plot = v2_gdf.copy()
    v2_gdf_plot["val"] = v2_values

    v1_gdf_plot.plot(ax=axes[0], column="val", cmap="viridis", edgecolor="none",
                     vmin=vmin, vmax=vmax, legend=True,
                     legend_kwds={"label": param_name, "shrink": 0.7})
    axes[0].set_title(f"v1.1 {param_name}{title_suffix}")
    axes[0].set_axis_off()

    v2_gdf_plot.plot(ax=axes[1], column="val", cmap="viridis", edgecolor="none",
                     vmin=vmin, vmax=vmax, legend=True,
                     legend_kwds={"label": param_name, "shrink": 0.7})
    v1_gdf.dissolve().boundary.plot(ax=axes[1], color="black", linewidth=1.5)
    axes[1].set_xlim(v1_bounds[0] - 5000, v1_bounds[2] + 5000)
    axes[1].set_ylim(v1_bounds[1] - 5000, v1_bounds[3] + 5000)
    axes[1].set_title(f"v2 {param_name}{title_suffix}")
    axes[1].set_axis_off()

    plt.suptitle(f"{param_name}: v1.1 vs v2{title_suffix}", fontsize=13)
    plt.tight_layout()
    plt.show()

# %% [markdown]
# ### jh_coef_hru comparison

# %% jupyter={"source_hidden": true}
# v1_jh_coef_hru = pdb_v1.get("jh_coef_hru").data
# v1_vals = v1_jh_coef_hru[v1_hru_gdf["param_idx"].values]

# # v2 values (clip to v1 domain for comparison)
# v2_vals = jh_coef_hru  # all v2 HRUs

# # compare_param(v1_hru_gdf, v1_vals, hru_gdf, v2_vals, "jh_coef_hru")

# print(f"v1.1 range: {v1_vals.min():.2f} — {v1_vals.max():.2f}")
# print(f"v2 range: {v2_vals.min():.2f} — {v2_vals.max():.2f}")

# %% [markdown]
# ### jh_coef comparison (July)

# %%
# compare_month = 6  # July (index 6)
# month_name = "Jul"

# v1_jh_coef = pdb_v1.get("jh_coef").data  # shape: (nhru, 12)
# v1_vals = v1_jh_coef[v1_hru_gdf["param_idx"].values, compare_month]
# v2_vals = jh_coef[:, compare_month]

# # compare_param(v1_hru_gdf, v1_vals, hru_gdf, v2_vals, "jh_coef", compare_month, month_name)

# print(f"v1.1 range: {v1_vals.min():.6f} — {v1_vals.max():.6f}")
# print(f"v2 range: {v2_vals.min():.6f} — {v2_vals.max():.6f}")

# %%
# # Check before clipping
# jh_coef_raw = np.zeros((nhru, 12))
# ihru, imon = 100, 6
# elh = (597.3 - (0.5653 * tavg_c_monthly_jh[imon, ihru])) * 2.54
# denom = (tavg_f_monthly_jh[imon, ihru] - jh_coef_hru[ihru]) * solrad_targets[imon, ihru] / elh

# print(f"tavg_f = {tavg_f_monthly_jh[imon, ihru]:.1f} °F")
# print(f"tavg_c = {tavg_c_monthly_jh[imon, ihru]:.1f} °C")
# print(f"jh_coef_hru = {jh_coef_hru[ihru]:.1f} °F")
# print(f"solrad = {solrad_targets[imon, ihru]:.1f} Langleys/day")
# print(f"farns = {farns_in_per_day[ihru, imon]:.6f} in/day")
# print(f"elh = {elh:.1f}")
# print(f"denom = {denom:.4f}")
# print(f"jh_coef = {farns_in_per_day[ihru, imon] / denom:.6f}")


# %% [markdown]
# ### dday_slope comparison (January)

# %%
# compare_month = 0  # January
# month_name = "Jan"

# v1_dday_slope = pdb_v1.get("dday_slope").data  # shape: (nhru, 12)
# v1_vals = v1_dday_slope[v1_hru_gdf["param_idx"].values, compare_month]
# v2_vals = dday_slope_monthly[compare_month, :]  # (12, nhru) -> select month

# # compare_param(v1_hru_gdf, v1_vals, hru_gdf, v2_vals, "dday_slope", compare_month, month_name)

# print(f"v1.1 range: {v1_vals.min():.4f} — {v1_vals.max():.4f}")
# print(f"v2 range: {v2_vals.min():.4f} — {v2_vals.max():.4f}")

# %% [markdown]
# ### dday_intcp comparison (January)

# %%
# v1_dday_intcp = pdb_v1.get("dday_intcp").data  # shape: (nhru, 12)
# v1_vals = v1_dday_intcp[v1_hru_gdf["param_idx"].values, compare_month]

# # v2 dday_intcp (from v1.1 CONUS paramdb via nhm_id mapping)
# v2_dday_intcp = dday_intcp[compare_month, :]  # (12, nhru) -> select month

# compare_param(v1_hru_gdf, v1_vals, hru_gdf, v2_dday_intcp, "dday_intcp", compare_month, month_name)

# print(f"v1.1 range: {v1_vals.min():.4f} — {v1_vals.max():.4f}")
# print(f"v2 range: {v2_dday_intcp.min():.4f} — {v2_dday_intcp.max():.4f}")

# %%
# What solar radiation values does v1.1 use internally?
# The radadj in v1.1 should be ~0.3-0.7 typically
# radadj = nrel_target * hru_cossl / soltab
# So: nrel_target = radadj * soltab / hru_cossl

# Check v1.1 soltab for July (month 6)
v1_soltab = pdb_v1.get("soltab_potsw").data if "soltab_potsw" in [p for p in dir(pdb_v1)] else None
print(f"Checking v1.1...")
print(f"Our soltab July mean: {soltab_monthly[:, 6].mean():.1f} Langleys/day")
print(f"Our NREL July mean: {nrel_langleys[6, :].mean():.1f}")
print(f"Ratio (NREL/soltab): {(nrel_langleys[6, :] / soltab_monthly[:, 6]).mean():.3f}")
print(f"Our radadj July mean: {radadj[:, 6].mean():.3f}")


# %%
print(f"Our dday_slope January: mean={dday_slope_monthly[0, :].mean():.4f}, range={dday_slope_monthly[0, :].min():.4f} — {dday_slope_monthly[0, :].max():.4f}")
print(f"v1.1 dday_slope January: mean={v1_dday_slope[:, 0].mean():.4f}, range={v1_dday_slope[:, 0].min():.4f} — {v1_dday_slope[:, 0].max():.4f}")
print()
print(f"Our dday January mean: {dday[0, :].mean():.2f}")
print(f"Our dday_intcp January mean: {dday_intcp[0, :].mean():.2f}")
print(f"Our tmax_f January mean: {tmax_f_monthly[0, :].mean():.2f}")


# %%

# %% [markdown]
# ## Interactive Map: All Parameters by HRU
# Folium choropleth with each parameter as a selectable layer (July values for monthly params).

# %%
import folium
from branca.colormap import LinearColormap
from shapely.validation import make_valid

# Prepare HRU GeoDataFrame in EPSG:4326 for folium
hru_map_gdf = hru_gdf.copy()
hru_map_gdf["geometry"] = hru_map_gdf.geometry.apply(
    lambda g: make_valid(g).buffer(0) if g is not None and not g.is_empty else g
)
hru_map_gdf = hru_map_gdf.to_crs(epsg=4326)

# Attach parameter values (use July=index 6 for monthly params)
display_month = 6  # July
month_label = "Jul"

hru_map_gdf["jh_coef_hru"] = jh_coef_hru
hru_map_gdf[f"jh_coef_{month_label}"] = jh_coef[:, display_month]
hru_map_gdf[f"dday_slope_{month_label}"] = dday_slope_monthly[display_month, :]
hru_map_gdf[f"dday_intcp_{month_label}"] = dday_intcp[display_month, :]
hru_map_gdf[f"soltab_potsw_{month_label}"] = soltab_monthly[:, display_month]
hru_map_gdf[f"radadj_{month_label}"] = radadj[:, display_month]
hru_map_gdf[f"nrel_solrad_{month_label}"] = nrel_langleys[display_month, :]
hru_map_gdf[f"farns_pet_{month_label}"] = farns_in_per_day[:, display_month]

# Simplify geometry for faster rendering
hru_map_gdf["geometry"] = hru_map_gdf.geometry.simplify(0.001)

# Center map
bounds = hru_map_gdf.total_bounds
center_lat = (bounds[1] + bounds[3]) / 2
center_lon = (bounds[0] + bounds[2]) / 2

m = folium.Map(location=[center_lat, center_lon], zoom_start=8, tiles="CartoDB positron")

folium.TileLayer(
    tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attr="OpenTopoMap",
    name="OpenTopoMap",
    show=False,
).add_to(m)

# Define layers with colormaps
param_layers = [
    ("jh_coef_hru", "jh_coef_hru", "°F"),
    (f"jh_coef_{month_label}", f"jh_coef ({month_label})", ""),
    (f"dday_slope_{month_label}", f"dday_slope ({month_label})", ""),
    (f"dday_intcp_{month_label}", f"dday_intcp ({month_label})", ""),
    (f"soltab_potsw_{month_label}", f"soltab_potsw ({month_label})", "Langleys/day"),
    (f"radadj_{month_label}", f"radadj ({month_label})", ""),
    (f"nrel_solrad_{month_label}", f"NREL solrad ({month_label})", "Langleys/day"),
    (f"farns_pet_{month_label}", f"Farnsworth PET ({month_label})", "in/day"),
]

cmaps = {}
for col, label, units in param_layers:
    vals = hru_map_gdf[col].dropna()
    vmin, vmax = vals.quantile(0.02), vals.quantile(0.98)
    if vmin == vmax:
        vmin, vmax = vals.min(), vals.max()
    cmap = LinearColormap(
        colors=["blue", "cyan", "yellow", "orange", "red"],
        vmin=vmin,
        vmax=vmax,
        caption=f"{label} {units}".strip(),
    )
    cmaps[col] = cmap

    show_layer = (col == "jh_coef_hru")  # only show first layer by default

    folium.GeoJson(
        hru_map_gdf[["geometry", col]].to_json(),
        name=label,
        style_function=lambda f, c=col, cm=cmap: {
            "fillColor": cm(f["properties"][c]) if f["properties"][c] is not None else "gray",
            "color": "none",
            "fillOpacity": 0.7,
        },
        tooltip=folium.GeoJsonTooltip(fields=[col], aliases=[label]),
        show=show_layer,
    ).add_to(m)

# Add colormaps to map
for cmap in cmaps.values():
    cmap.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
m

# %% [markdown]
# ## Compare v2 OHM vs v1.1 CONUS Parameter Values
# Side-by-side maps: v1.1 HRUs (clipped to OHM extent) on the left,
# v2 HRUs on the right. Uses spatial clipping (bounding box) since
# nhm_id is not shared between versions.

# %%
import geopandas as gpd
import matplotlib.pyplot as plt

# --- Load v1.1 HRU geometry from GFv1.1.gdb ---
v11_gdb = pl.Path(r"D:\nhm-assist\data_dependencies\NHM_v1_1\version1_1_params\GFv1.1.gdb")
v11_paramdb = pl.Path(r"D:\nhm-assist\data_dependencies\NHM_v1_1\version1_1_params\paramdb_v1.1_gridmet_CONUS-master")

print("Loading v1.1 HRU geometry...")
v11_hru_gdf = gpd.read_file(v11_gdb, layer="nhru_v1_1")
print(f"  v1.1 CONUS: {len(v11_hru_gdf)} HRUs, CRS: {v11_hru_gdf.crs}")

# --- Load v2 HRU geometry ---
v2_gpkg = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\GIS\model_layers.gpkg")
v2_hru_gdf = gpd.read_file(v2_gpkg, layer="nhru")
print(f"  v2 OHM: {len(v2_hru_gdf)} HRUs, CRS: {v2_hru_gdf.crs}")

# Reproject v2 to match v1.1 CRS for spatial operations
v2_hru_gdf_proj = v2_hru_gdf.to_crs(v11_hru_gdf.crs)

# %%
# --- Clip v1.1 to v2 OHM bounding box (with buffer) ---
v2_bounds = v2_hru_gdf_proj.total_bounds  # [minx, miny, maxx, maxy]
buffer_m = 10000  # 10 km buffer around the v2 extent
from shapely.geometry import box

clip_box = box(
    v2_bounds[0] - buffer_m, v2_bounds[1] - buffer_m,
    v2_bounds[2] + buffer_m, v2_bounds[3] + buffer_m,
)

v11_clipped = v11_hru_gdf[v11_hru_gdf.intersects(clip_box)].copy()
print(f"  v1.1 clipped to OHM extent: {len(v11_clipped)} HRUs")

# %%
# --- Load v1.1 parameters for clipped HRUs ---
# The row order in nhm_id.csv defines the HRU ordering for all param CSVs.
# To look up a param value for a GDB HRU, find its nhm_id position in nhm_id.csv.
nhru_v11 = 114958  # total CONUS HRUs

df_nhm_id = pd.read_csv(v11_paramdb / "nhm_id.csv")
nhm_id_order = df_nhm_id["nhm_id"].values  # row position -> nhm_id
nhm_id_to_row = {nid: idx for idx, nid in enumerate(nhm_id_order)}

# Map GDB nhru_v1_1 to row indices in the param arrays
v11_hru_ids = v11_clipped["nhru_v1_1"].values

# Filter to only HRUs that exist in the paramdb (GDB may have extra HRUs)
valid_mask = np.isin(v11_hru_ids, nhm_id_order)
print(f"  {valid_mask.sum()} of {len(v11_hru_ids)} clipped HRUs found in paramdb")
v11_clipped = v11_clipped[valid_mask].copy()
v11_hru_ids = v11_clipped["nhru_v1_1"].values
v11_row_indices = np.array([nhm_id_to_row[nid] for nid in v11_hru_ids])

# jh_coef_hru: one value per HRU
df_jh_coef_hru_v11 = pd.read_csv(v11_paramdb / "jh_coef_hru.csv")
v11_clipped["jh_coef_hru"] = df_jh_coef_hru_v11["jh_coef_hru"].values[v11_row_indices]

# dday_intcp: 12 months x nhru (stored sequentially: all HRUs for month 1, then month 2, etc.)
df_dday_intcp_v11 = pd.read_csv(v11_paramdb / "dday_intcp.csv")
dday_intcp_all = df_dday_intcp_v11["dday_intcp"].values.reshape(12, nhru_v11)
v11_clipped["dday_intcp_Jan"] = dday_intcp_all[0, v11_row_indices]

# dday_slope: 12 months x nhru
df_dday_slope_v11 = pd.read_csv(v11_paramdb / "dday_slope.csv")
dday_slope_all = df_dday_slope_v11["dday_slope"].values.reshape(12, nhru_v11)
v11_clipped["dday_slope_Jan"] = dday_slope_all[0, v11_row_indices]

# jh_coef: 12 months x nhru
df_jh_coef_v11 = pd.read_csv(v11_paramdb / "jh_coef.csv")
jh_coef_all = df_jh_coef_v11["jh_coef"].values.reshape(12, nhru_v11)
v11_clipped["jh_coef_Jul"] = jh_coef_all[6, v11_row_indices]

print("v1.1 parameter ranges (clipped extent):")
print(f"  jh_coef_hru: {v11_clipped['jh_coef_hru'].min():.2f} — {v11_clipped['jh_coef_hru'].max():.2f}")
print(f"  dday_intcp (Jan): {v11_clipped['dday_intcp_Jan'].min():.1f} — {v11_clipped['dday_intcp_Jan'].max():.1f}")
print(f"  dday_slope (Jan): {v11_clipped['dday_slope_Jan'].min():.4f} — {v11_clipped['dday_slope_Jan'].max():.4f}")
print(f"  jh_coef (Jul): {v11_clipped['jh_coef_Jul'].min():.6f} — {v11_clipped['jh_coef_Jul'].max():.6f}")

# %%
# --- Attach v2 computed parameter values ---
v2_hru_gdf_proj["jh_coef_hru"] = jh_coef_hru

# --- Load Willamette outline for domain reference ---
v1_wil_dir = pl.Path(r"D:\nhm-assist\data_dependencies\20240524_v1.1_gm_precal_williamette_river")
v1_wil_gis = v1_wil_dir / "GIS" / "model_nhru.shp"
wil_hru_gdf = gpd.read_file(v1_wil_gis).to_crs(v11_hru_gdf.crs)
wil_outline = wil_hru_gdf.dissolve().boundary
v2_outline = v2_hru_gdf_proj.dissolve().boundary

print(f"  Willamette outline: {len(wil_hru_gdf)} HRUs")

# %%
# --- Two-panel comparison maps ---
def compare_v11_v2(v11_gdf, v2_gdf, column, param_label, cmap="viridis"):
    """Plot v1.1 (left) vs v2 (right) with shared color scale and domain outlines."""
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    v11_vals = v11_gdf[column].values
    v2_vals = v2_gdf[column].values

    # Shared color range across both datasets
    vmin = min(np.nanmin(v11_vals), np.nanmin(v2_vals))
    vmax = max(np.nanmax(v11_vals), np.nanmax(v2_vals))

    # Left panel: v1.1 with Willamette and v2 outlines
    v11_gdf.plot(ax=axes[0], column=column, cmap=cmap, edgecolor="none",
                 vmin=vmin, vmax=vmax, legend=True,
                 legend_kwds={"label": param_label, "shrink": 0.7})
    wil_outline.plot(ax=axes[0], color="red", linewidth=1.5, label="Willamette")
    v2_outline.plot(ax=axes[0], color="blue", linewidth=1.5, linestyle="--", label="v2 OHM")
    axes[0].legend(loc="lower left", fontsize=9)
    axes[0].set_title(f"v1.1 — {param_label}", fontsize=12)
    axes[0].set_axis_off()

    # Right panel: v2 OHM with Willamette outline
    v2_gdf.plot(ax=axes[1], column=column, cmap=cmap, edgecolor="none",
                vmin=vmin, vmax=vmax, legend=True,
                legend_kwds={"label": param_label, "shrink": 0.7})
    wil_outline.plot(ax=axes[1], color="red", linewidth=1.5, label="Willamette")
    axes[1].legend(loc="lower left", fontsize=9)
    axes[1].set_title(f"v2 OHM — {param_label}", fontsize=12)
    axes[1].set_axis_off()

    # Match extents
    xlim = [min(v11_gdf.total_bounds[0], v2_gdf.total_bounds[0]) - 5000,
            max(v11_gdf.total_bounds[2], v2_gdf.total_bounds[2]) + 5000]
    ylim = [min(v11_gdf.total_bounds[1], v2_gdf.total_bounds[1]) - 5000,
            max(v11_gdf.total_bounds[3], v2_gdf.total_bounds[3]) + 5000]
    for ax in axes:
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)

    plt.suptitle(f"{param_label}: v1.1 vs v2 OHM", fontsize=14)
    plt.tight_layout()
    plt.show()

    # Print summary statistics
    print(f"  {'':20s} {'v1.1 (clipped)':>16s}   {'v2 OHM':>16s}")
    print(f"  {'Range':20s} {np.nanmin(v11_vals):8.4f} — {np.nanmax(v11_vals):<8.4f}  {np.nanmin(v2_vals):8.4f} — {np.nanmax(v2_vals):<8.4f}")
    print(f"  {'Mean':20s} {np.nanmean(v11_vals):>16.4f}   {np.nanmean(v2_vals):>16.4f}")

# %%
compare_v11_v2(v11_clipped, v2_hru_gdf_proj, "jh_coef_hru", "jh_coef_hru (°F)")

# %%
# --- Interactive monthly comparison with slider ---
import ipywidgets as widgets
from IPython.display import display

month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def plot_monthly_param(month_idx, param_name, v11_all_months, v2_all_months):
    """Plot a monthly parameter for a given month index (0-based)."""
    month_label = month_names[month_idx]

    # Set values for the selected month
    v11_clipped[f"{param_name}_plot"] = v11_all_months[month_idx, v11_row_indices]
    v2_hru_gdf_proj[f"{param_name}_plot"] = v2_all_months[month_idx]

    compare_v11_v2(v11_clipped, v2_hru_gdf_proj, f"{param_name}_plot",
                   f"{param_name} ({month_label})")


# %%
# dday_intcp interactive slider
def show_dday_intcp(month=0):
    v2_monthly = dday_intcp  # (12, nhru)
    plot_monthly_param(month, "dday_intcp", dday_intcp_all, v2_monthly)

widgets.interact(show_dday_intcp,
                 month=widgets.IntSlider(min=0, max=11, step=1, value=0,
                                         description="Month:",
                                         continuous_update=False,
                                         readout_format="d"))

# %%
# dday_slope interactive slider
def show_dday_slope(month=0):
    v2_monthly = dday_slope_monthly  # (12, nhru)
    plot_monthly_param(month, "dday_slope", dday_slope_all, v2_monthly)

widgets.interact(show_dday_slope,
                 month=widgets.IntSlider(min=0, max=11, step=1, value=0,
                                         description="Month:",
                                         continuous_update=False,
                                         readout_format="d"))

# %%
# jh_coef interactive slider
def show_jh_coef(month=6):
    v2_monthly = jh_coef.T  # jh_coef is (nhru, 12), transpose to (12, nhru)
    plot_monthly_param(month, "jh_coef", jh_coef_all, v2_monthly)

widgets.interact(show_jh_coef,
                 month=widgets.IntSlider(min=0, max=11, step=1, value=6,
                                         description="Month:",
                                         continuous_update=False,
                                         readout_format="d"))

# %%
