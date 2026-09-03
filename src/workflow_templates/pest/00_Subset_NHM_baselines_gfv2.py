# ---
# jupyter:
#   jupytext:
#     formats: pestpp_ies_calibration/notebooks//ipynb,src/workflow_templates/pest//py:percent
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

# %% jupyter={"source_hidden": true}
import sys
import os
import pathlib as pl
import warnings

warnings.filterwarnings("ignore")
from rich.console import Console

con = Console()
from rich import pretty

pretty.install()
import jupyter_black

jupyter_black.load()
# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"


from assist.nhf.nhm_hydrofabric_v2 import (
    make_hf_map_elements,
    evaluate_and_fix_nhru_geometry,
)
from assist.nhf.map_template_v2 import make_hf_map, make_geo_map, make_geo_legend

from assist.nhf.nhm_assist_utilities_v2 import (
    load_subdomain_config,
    find_missing_gage_info,
    fetch_non_ref_npoigages_info,
    fetch_ref_npoigages_info,
)

from assist.nhf import efc

# import topojson


config = load_subdomain_config(root_dir)
# con.print(config)


import pandas as pd
import xarray as xr
import numpy as np
import datetime

from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.


# from assist.workspace.bridge import resolve_project_notebook_context
# from assist.workspace.service import get_active_model_root

# project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
# if project_context:
#     active_model_root = get_active_model_root(
#         project_context["workspace_root"], project_context["project_root"].name
#     )
#     config_root = active_model_root / "config"
# else:
#     config_root = root_dir

from dotenv import load_dotenv

# Use home directory for Nebari, otherwise use repo root_dir
if "NEBARI_CONDA_STORE_SERVER_SERVICE_HOST" in os.environ:
    dotenv_path = pl.Path.home() / ".env"
else:
    dotenv_path = root_dir / ".env"

load_dotenv(dotenv_path=dotenv_path)

############################################


# from assist.nhm.nhm_assist_utilities import load_subdomain_config
# from assist.nhm import efc

config = load_subdomain_config(root_dir)

# %%
from assist.nhf.nhm_hydrofabric_v2 import (
    make_hf_map_elements,
    evaluate_and_fix_nhru_geometry,
)
from assist.nhf.map_template_v2 import make_hf_map, make_geo_map, make_geo_legend

from assist.nhf.nhm_assist_utilities_v2 import (
    load_subdomain_config,
    find_missing_gage_info,
    fetch_non_ref_npoigages_info,
    fetch_ref_npoigages_info,
)

# %% jupyter={"source_hidden": true}
(
    hru_gdf,
    hru_txt,
    hru_cal_level_txt,
    seg_gdf,
    seg_txt,
    waterdata_gages_aoi,
    poi_df,
    gages_df,
    gages_txt,
    gages_txt_nb2,
    HW_basins_gdf,
    HW_basins,
) = make_hf_map_elements(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    control_file_name=config["control_file_name"],
    waterdata_gages_file=config["waterdata_gages_file"],
    gages_file=config["gages_file"],
    resource_gages_file=config["resource_gages_file"],
    default_gages_file=config["default_gages_file"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
)

# %% [markdown]
# ### This notebook subsets the NHM CONUS baseline data used for calibration targets to create observation files (.nc) for each model extraction in the root folder. These created files will be read by the subsequent Notebook to make files used (read during) in PEST++ calibration.
# #### This notebook also preprocesses the SCA baseline data to emulate the filtering that is done in NHM calibration with Fortran.
# #### This only needs to be run once.

# %% [markdown]
# ### Make a pest_ies folder in the model directory to hold all pest_ies related files

# %%
config["model_dir"]

# %%
if not (config["model_dir"] / "pestpp_ies").exists():
    (config["model_dir"] / "pestpp_ies").mkdir()
pestpp_model_dir = config["model_dir"] / "pestpp_ies"
pestpp_dir = pl.Path("../").resolve()

# %% [markdown]
# ### Make observation_data folder in the subbasin model directory

# %%
if not (pestpp_model_dir / "observation_data").exists():
    (pestpp_model_dir / "observation_data").mkdir()
obsdir = pestpp_model_dir / "observation_data"

# %%
if not (pestpp_model_dir / "ancillary").exists():
    (pestpp_model_dir / "ancillary").mkdir()
ancillary_dir = pestpp_model_dir / "ancillary"

# %% [markdown]
# ### now grab all the `nhm_ids` from the `myparam.param` file

# %%
nhm_ids = pws.parameters.PrmsParameters.load(
    config["model_dir"] / config["param_file"]
).parameters["nhm_id"]

# %% [markdown]
# ### assign `wkdir` to indicate where the raw CONUS netCDF files live

# %%
import shutil

# Copy template to subdomain model folder for editing
source = (
    pestpp_dir / "data_dependencies/ancillary_template/target_and_output_vars_table.csv"
)
destination = ancillary_dir / "target_and_output_vars_table.csv"
shutil.copy2(source, destination)

# %%
lu = pd.read_csv(ancillary_dir / "target_and_output_vars_table.csv", index_col=0)
lu

# %%
baselines_dir = pestpp_dir / "data_dependencies/OHM_targets"
[i for i in baselines_dir.glob("*.nc")]

# %% [markdown]
# ### Slice output to calibration periods for each variable
# Approach as of 08-25-26, take the most recent 12 years of data from each HRU target. 
# #### These are as follows from table 2 (Hay and others, 2023):
#

# %%
aet_start = "2009-01-01"
aet_end = "2020-12-31"
_years = np.array(range(aet_start, aet_end))
aet_val_years = [i for i in _years if i % 2 == 0]
aet_cal_years = [i for i in _years if i % 2 != 0]

recharge_start = "2002-01-01"
recharge_end = "2013-12-31"
_years = np.array(range(recharge_start, recharge_end))
recharge_val_years = [i for i in _years if i % 2 == 0]
recharge_cal_years = [i for i in _years if i % 2 != 0]

runoff_start = "2009-01-01"
runoff_end = "2020-12-31"
_years = np.array(range(runoff_start, runoff_end))
runoff_val_years = [i for i in _years if i % 2 == 0]
runoff_cal_years = [i for i in _years if i % 2 != 0]

soil_rechr_start = "2014-01-01"
soil_rechr_end = "2025-12-31"
_years = np.array(range(soil_rechr_start, soil_rechr_end))
soil_rechr_val_years = [i for i in _years if i % 2 == 0]
soil_rechr_cal_years = [i for i in _years if i % 2 != 0]

sca_start = "2003-01-01"
sca_end = "2021-12-31"
_years = np.array(range(sca_start, sca_end))
sca_val_years = [i for i in _years if i % 2 == 0]
sca_cal_years = [i for i in _years if i % 2 != 0]

swe_start = "2010-01-01"
swe_end = "2021-12-31"
_years = np.array(range(swe_start, swe_end))
swe_val_years = [i for i in _years if i % 2 == 0]
swe_cal_years = [i for i in _years if i % 2 != 0]

# %%
## We will choose even years as validation
val_years = [i for i in streamflow_years if i % 2 == 0]
cal_years = [i for i in streamflow_years if i % 2 != 0]

# %% [markdown]
# ### Subset AET NHM baseline data

# %%
# Use larger, manual chunks for efficiency
AET_all = xr.open_dataset(
    baselines_dir / "aet_targets.nc", chunks={"time": 12, "nhru": 500}
)

# %% [markdown]
# #### Quick spatial check of the target data as referrenced by nhm_id to the model HRUs by nhm_id

# %%
# Step 1: Load parent geopackage and create cross-walk table for nhm_id for the child model.
import geopandas as gpd
import folium

# Load the nhru layer from the parent model geopackage
parent_gpkg = root_dir / "hydrofabric_domain_data/OHM_2026_02_21/GIS/model_layers.gpkg"
parent_hru_gdf = gpd.read_file(parent_gpkg, layer="nhru")

# %% [markdown]
# #### Crosswalk: child model `nhm_id` to parent model `nhm_id`
#
# The child model's `nhm_id` parameter (from the param file) is actually the **parent model's `hru_id`** (local index), not the national HRU identifier. To select the correct HRUs from the CONUS baseline datasets (which use the parent's `nhm_id`), we need a crosswalk:
#
# - **Parent gpkg** has: `nhm_id` (national ID) and `hru_id` (parent-local index)
# - **Child model** has: `nhm_id` (= parent's `hru_id`) and `hru_id` (child-local index)
#
# Join: `child nhm_id` == `parent hru_id` → retrieve `parent nhm_id`

# %%
# Crosswalk: child model nhm_id (= parent hru_id) -> parent nhm_id
# The child's "nhm_id" param is actually the parent's local hru_id.
# Look up each child nhm_id in the parent gpkg's hru_id column to get the parent nhm_id.

crosswalk = parent_hru_gdf[["nhm_id", "hru_id"]].copy()
crosswalk = crosswalk.rename(
    columns={"nhm_id": "parent_nhm_id", "hru_id": "parent_hru_id"}
)

# nhm_ids from child param file = parent's hru_id
child_df = pd.DataFrame({"child_nhm_id": nhm_ids})
child_df["child_hru_id"] = range(1, len(nhm_ids) + 1)  # child local index (1-based)

# Join: child_nhm_id == parent_hru_id to get the parent_nhm_id
xwalk = child_df.merge(
    crosswalk, left_on="child_nhm_id", right_on="parent_hru_id", how="left"
)

print(f"Child HRUs: {len(child_df)}")
print(f"Matched to parent nhm_id: {xwalk['parent_nhm_id'].notna().sum()}")
print(f"Unmatched: {xwalk['parent_nhm_id'].isna().sum()}")

nhm_ids = list(xwalk["parent_nhm_id"])

# %% jupyter={"source_hidden": true}
# Interactive map: compare parent gpkg centroids vs AET_all centroids (plotly)
import plotly.graph_objects as go

# Parent gpkg centroids (reproject to WGS84)
parent_hru_gdf_wgs = parent_hru_gdf.to_crs(epsg=4326)
parent_hru_gdf_wgs["centroid_lat"] = parent_hru_gdf_wgs.geometry.centroid.y
parent_hru_gdf_wgs["centroid_lon"] = parent_hru_gdf_wgs.geometry.centroid.x

# AET centroids clipped to parent gpkg bounding box
lat_min = parent_hru_gdf_wgs["centroid_lat"].min() - 0.5
lat_max = parent_hru_gdf_wgs["centroid_lat"].max() + 0.5
lon_min = parent_hru_gdf_wgs["centroid_lon"].min() - 0.5
lon_max = parent_hru_gdf_wgs["centroid_lon"].max() + 0.5

aet_all_lats = AET_all["centroid_lat"].values
aet_all_lons = AET_all["centroid_lon"].values
aet_all_ids = AET_all["nhm_id"].values

bbox_mask = (
    (aet_all_lats >= lat_min)
    & (aet_all_lats <= lat_max)
    & (aet_all_lons >= lon_min)
    & (aet_all_lons <= lon_max)
)

fig = go.Figure()

# Parent gpkg centroids — toggleable trace
fig.add_trace(
    go.Scattermapbox(
        lat=parent_hru_gdf_wgs["centroid_lat"],
        lon=parent_hru_gdf_wgs["centroid_lon"],
        mode="markers",
        marker=dict(size=6, color="blue", opacity=0.6),
        text=[f"nhm_id: {i}" for i in parent_hru_gdf_wgs["nhm_id"]],
        name="Parent gpkg (nhm_id)",
    )
)

# AET centroids — toggleable trace
fig.add_trace(
    go.Scattermapbox(
        lat=aet_all_lats[bbox_mask],
        lon=aet_all_lons[bbox_mask],
        mode="markers",
        marker=dict(size=4, color="red", opacity=0.7),
        text=[f"nhm_id: {i}" for i in aet_all_ids[bbox_mask]],
        name="AET_all (centroid_lat/lon)",
    )
)

# Lines connecting matched crosswalk pairs (gpkg centroid -> AET centroid)
# Use the xwalk to draw connection lines for matched HRUs
xwalk_matched = xwalk[xwalk["parent_nhm_id"].notna()].copy()
gpkg_lookup = parent_hru_gdf_wgs.set_index("nhm_id")[["centroid_lat", "centroid_lon"]]
aet_lookup = pd.DataFrame(
    {
        "nhm_id": aet_all_ids,
        "aet_lat": aet_all_lats,
        "aet_lon": aet_all_lons,
    }
).set_index("nhm_id")

line_lats = []
line_lons = []
for _, row in xwalk_matched.iterrows():
    pid = int(row["parent_nhm_id"])
    if pid in gpkg_lookup.index and pid in aet_lookup.index:
        g = gpkg_lookup.loc[pid]
        a = aet_lookup.loc[pid]
        line_lats.extend([g["centroid_lat"], a["aet_lat"], None])
        line_lons.extend([g["centroid_lon"], a["aet_lon"], None])

fig.add_trace(
    go.Scattermapbox(
        lat=line_lats,
        lon=line_lons,
        mode="lines",
        line=dict(width=1, color="green"),
        name="Crosswalk links",
        opacity=0.5,
    )
)

fig.update_layout(
    mapbox=dict(
        style="open-street-map",
        center=dict(
            lat=parent_hru_gdf_wgs["centroid_lat"].mean(),
            lon=parent_hru_gdf_wgs["centroid_lon"].mean(),
        ),
        zoom=6,
    ),
    margin=dict(l=0, r=0, t=30, b=0),
    title="Centroid Comparison: Parent gpkg vs AET_all",
    height=600,
)

fig.show()

# %% [markdown]
# ### Write Subset AET NHM baseline data

# %%
c_da = AET_all.sel(nhm_id=nhm_ids, time=slice(aet_start, aet_end))
# Always pre-load before writing for speed
c_da[["upper_bound", "lower_bound"]].load().to_netcdf(obsdir / f"AET_monthly.nc")

# Compute mean in memory, then write
c_da.groupby("time.month").mean().load().to_netcdf(obsdir / f"AET_mean_monthly.nc")

AET_all.close()

# %%
# AET_all = xr.open_dataset(baselines_dir / "baseline_AET_v11.nc", chunks="auto")
# # AET_all

# %%
# c_da = AET_all.sel(nhm_id=nhm_ids)
# c_da[["aet_max", "aet_min"]].to_netcdf(obsdir / f"AET_monthly.nc")
# c_da.groupby("time.month").mean().to_netcdf(obsdir / f"AET_mean_monthly.nc")
# AET_all.close()

# %% [markdown]
# ###  Subset HRU Streamflow (RUNOFF NHM) baseline data--The MWBM term, "runoff" is total contribution to streamflow from each HRU. We are re-terming this in the subset file to "hru_streamflow" to clearly describe HRU contributions to streamflow.

# %%
RUN_all = xr.open_dataset(baselines_dir / "runoff_targets.nc", chunks="auto")
# RUN_all

# %%
c_da = RUN_all.sel(nhm_id=nhm_ids, time=slice(runoff_start, runoff_end))
c_da[["lower_bound", "upper_bound"]].to_netcdf(obsdir / f"hru_streamflow_monthly.nc")
RUN_all.close()

# %% [markdown]
# ### Subset Annual Recharge
# ### These annual values are actually the average daily rate; and, match the units of the output.

# %%
RCH_all = xr.open_dataset(baselines_dir / "recharge_targets.nc", chunks="auto")
# RCH_all

# %%
c_da = RCH_all.sel(nhm_id=nhm_ids)
c_da[["lower_bound", "upper_bound"]].to_netcdf(obsdir / f"RCH_annual.nc")
RCH_all.close()

# %% [markdown]
# ### Subset Annual Soil Moisture

# %%
SOM_ann_all = xr.open_dataset(
    baselines_dir / "soil_moisture_targets_annual.nc", chunks="auto"
)
# SOM_ann_all

# %%
c_da = SOM_ann_all.sel(nhm_id=nhm_ids, time=slice(soil_rechr_start, soil_rechr_end))
c_da[["lower_bound", "upper_bound"]].to_netcdf(obsdir / f"Soil_Moisture_annual.nc")
SOM_ann_all.close()

# %% [markdown]
# ### Subset Monthly Soil Moisture

# %%
SOM_mon_all = xr.open_dataset(
    baselines_dir / "soil_moisture_targets_monthly.nc", chunks="auto"
)
# SOM_mon_all

# %%
c_da = SOM_mon_all.sel(nhm_id=nhm_ids, time=slice(soil_rechr_start, soil_rechr_end))
c_da[["lower_bound", "upper_bound"]].to_netcdf(obsdir / "Soil_Moisture_monthly.nc")
SOM_mon_all.close()

# %% [markdown]
# ### Subset and pre-process Daily Snow Covered Area

# %%
# Read the raw data set. Lauren Hay developed fortran code embedded in the NHM that pre-processed the raw data,
# applying several filters.
SCA = xr.open_dataset(baselines_dir / "sca_targets.nc", chunks="auto")
SCA


# %%
# # populating variables used in Parker Norton's function.
# sca_lower_var = "lower_bound"
# sca_upper_var = "upper_bound"
# remove_ja = True  # This is technically the first filter for removing July and August from the dataset

# %%
def get_dataset(df, f_vars, start_date, end_date):
    # This routine assumes dimension nhru exists and variable nhm_id exists
    # NOTE: Next line needed if nhm_id variable exists in netcdf file
    # df = df.assign_coords(nhru=df.nhm_id)
    if isinstance(f_vars, list):
        df = df[f_vars].sel(time=slice(start_date, end_date))
    else:
        df = df[[f_vars]].sel(time=slice(start_date, end_date))
    return df


baseline_df = get_dataset(
    SCA, ["lower_bound", "upper_bound", "nhm_id"], sca_start, sca_end
)

# # Applying first filter to remove selected months, July and August, from the dataset, selects months to keep.
# if remove_ja:
#     #
#     baseline_restr = baseline_df.sel(
#         time=baseline_df.time.dt.month.isin([1, 2, 3, 4, 5, 6, 9, 10, 11, 12])
#     )
# else:
#     baseline_restr = baseline_df
# baseline_df.close()

# %%
SCA.close()
del SCA

# %%
# Lower bound of SCA by HRU
baseline_SCAmin = baseline_df["lower_bound"]

# %%
# Upper bound of SCA by HRU
baseline_SCAmax = baseline_df["upper_bound"]

# %%
# Lower bound of SCA by HRU
baseline_SCAmin = baseline_df["lower_bound"]
# Upper bound of SCA by HRU
baseline_SCAmax = baseline_df["upper_bound"]


SCA_daily = xr.combine_by_coords(
    [
        baseline_SCAmin.to_dataset(name="SCA_min"),
        baseline_SCAmax.to_dataset(name="SCA_max"),
    ]
)
SCA_daily

# %%
c_da = SCA_daily.sel(nhm_id=nhm_ids)
c_da.to_netcdf(obsdir / f"SCA_daily.nc")

# %%
# 5-day averaged SCA dataset
# Calculation: centered rolling mean with a window of 5 days applied along the time
# dimension. For each timestep, the value is the average of the 2 days before, the day
# itself, and the 2 days after (window=5, center=True). The first and last 2 days of
# the time series will contain NaN where the full window is not available (min_periods
# not relaxed). This smooths short-term noise while preserving the seasonal signal.
c_da_5day = c_da.rolling(time=5, center=True).mean()
c_da_5day = c_da_5day.dropna(dim="time", how="any")
c_da_5day.attrs["averaging_method"] = (
    "5-day centered rolling mean (window=5, center=True) applied along the time dimension"
)
c_da_5day.to_netcdf(obsdir / "SCA_5day_avg.nc")

# %% [markdown]
# ### Lets peak at SCA

# %%
# SCA_daily.SCA_max.sel(nhru=99860, time=slice("2002-11-01", "2003-01-30")).plot()
# SCA_daily.SCA_min.sel(nhru=99860, time=slice("2002-11-01", "2003-01-30")).plot()
import plotly.graph_objects as go
import plotly.colors as pc

hru_sel = [29154, 29073, 29058]  # [nhm_ids[0], nhm_ids[1], nhm_ids[2]]
colors = pc.qualitative.Set1[: len(hru_sel)]  # distinct colors per HRU
time_slice = slice("2002-11-01", "2008-01-30")

# --- Daily SCA bounds ---
fig = go.Figure()
for hru, color in zip(hru_sel, colors):
    sca_max = c_da.SCA_max.sel(nhm_id=hru, time=time_slice)
    sca_min = c_da.SCA_min.sel(nhm_id=hru, time=time_slice)
    fig.add_trace(
        go.Scatter(
            x=sca_max.time.values,
            y=sca_max.values,
            mode="lines",
            name=f"{hru} SCA_max (line)",
            line=dict(color=color),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=sca_max.time.values,
            y=sca_max.values,
            mode="markers",
            name=f"{hru} SCA_max (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=sca_min.time.values,
            y=sca_min.values,
            mode="lines",
            name=f"{hru} SCA_min (line)",
            line=dict(color=color, dash="dash"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=sca_min.time.values,
            y=sca_min.values,
            mode="markers",
            name=f"{hru} SCA_min (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig.update_layout(
    title="SCA bounds (daily)",
    xaxis_title="Time",
    yaxis_title="Snow Covered Area (fraction)",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig.show()

# %% jupyter={"source_hidden": true}
# --- Weekly mean SCA bounds ---
fig_w = go.Figure()
for hru, color in zip(hru_sel, colors):
    sca_max_w = c_da.SCA_max.sel(nhm_id=hru, time=time_slice).resample(time="1W").mean()
    sca_min_w = c_da.SCA_min.sel(nhm_id=hru, time=time_slice).resample(time="1W").mean()
    fig_w.add_trace(
        go.Scatter(
            x=sca_max_w.time.values,
            y=sca_max_w.values,
            mode="lines",
            name=f"{hru} SCA_max (line)",
            line=dict(color=color),
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=sca_max_w.time.values,
            y=sca_max_w.values,
            mode="markers",
            name=f"{hru} SCA_max (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=sca_min_w.time.values,
            y=sca_min_w.values,
            mode="lines",
            name=f"{hru} SCA_min (line)",
            line=dict(color=color, dash="dash"),
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=sca_min_w.time.values,
            y=sca_min_w.values,
            mode="markers",
            name=f"{hru} SCA_min (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_w.update_layout(
    title="SCA bounds (weekly mean)",
    xaxis_title="Time",
    yaxis_title="Snow Covered Area (fraction)",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_w.show()

# %% jupyter={"source_hidden": true}
# --- 5-day rolling average SCA bounds ---
fig_5d = go.Figure()
for hru, color in zip(hru_sel, colors):
    sca_max_5d = (
        c_da.SCA_max.sel(nhm_id=hru, time=time_slice)
        .rolling(time=5, center=True)
        .mean()
    )
    sca_min_5d = (
        c_da.SCA_min.sel(nhm_id=hru, time=time_slice)
        .rolling(time=5, center=True)
        .mean()
    )
    fig_5d.add_trace(
        go.Scatter(
            x=sca_max_5d.time.values,
            y=sca_max_5d.values,
            mode="lines",
            name=f"{hru} SCA_max (line)",
            line=dict(color=color),
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=sca_max_5d.time.values,
            y=sca_max_5d.values,
            mode="markers",
            name=f"{hru} SCA_max (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=sca_min_5d.time.values,
            y=sca_min_5d.values,
            mode="lines",
            name=f"{hru} SCA_min (line)",
            line=dict(color=color, dash="dash"),
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=sca_min_5d.time.values,
            y=sca_min_5d.values,
            mode="markers",
            name=f"{hru} SCA_min (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_5d.update_layout(
    title="SCA bounds (5-day rolling average)",
    xaxis_title="Time",
    yaxis_title="Snow Covered Area (fraction)",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_5d.show()

# %% jupyter={"source_hidden": true}
# --- Monthly mean SCA bounds ---
fig_m = go.Figure()
for hru, color in zip(hru_sel, colors):
    sca_max_m = (
        c_da.SCA_max.sel(nhm_id=hru, time=time_slice).resample(time="1ME").mean()
    )
    sca_min_m = (
        c_da.SCA_min.sel(nhm_id=hru, time=time_slice).resample(time="1ME").mean()
    )
    fig_m.add_trace(
        go.Scatter(
            x=sca_max_m.time.values,
            y=sca_max_m.values,
            mode="lines",
            name=f"{hru} SCA_max (line)",
            line=dict(color=color),
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=sca_max_m.time.values,
            y=sca_max_m.values,
            mode="markers",
            name=f"{hru} SCA_max (points)",
            marker=dict(size=5, color=color),
            visible="legendonly",
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=sca_min_m.time.values,
            y=sca_min_m.values,
            mode="lines",
            name=f"{hru} SCA_min (line)",
            line=dict(color=color, dash="dash"),
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=sca_min_m.time.values,
            y=sca_min_m.values,
            mode="markers",
            name=f"{hru} SCA_min (points)",
            marker=dict(size=5, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_m.update_layout(
    title="SCA bounds (monthly mean)",
    xaxis_title="Time",
    yaxis_title="Snow Covered Area (fraction)",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_m.show()

# %% [markdown]
# ## Subset and pre-process Daily Snow Water Equivalent (SWE)

# %%
# Read the raw data set.
SWE_daily = xr.open_dataset(baselines_dir / "swe_targets.nc", chunks="auto")
c_da_swe = SWE_daily.sel(nhm_id=nhm_ids, time=slice(swe_start, swe_end))
c_da_swe[["lower_bound", "upper_bound"]].to_netcdf(obsdir / "SWE.nc")

# %%
# 5-day averaged SWE dataset
# Calculation: resample to non-overlapping 5-day windows and compute the mean
# of each window. This produces one value per 5-day period (not a smoothed daily
# series). The first 2 days and last 2 days are dropped so that every retained
# timestamp sits at the center of a complete 5-day window.
c_da_swe_5day = c_da_swe[["lower_bound", "upper_bound"]].resample(time="5D").mean()
c_da_swe_5day = c_da_swe_5day.dropna(dim="time", how="any")
c_da_swe_5day.attrs["averaging_method"] = (
    "5-day resample mean (non-overlapping 5-day windows)"
)
c_da_swe_5day.to_netcdf(obsdir / "SWE_5day_avg.nc")

SWE_daily.close()

# %% [markdown]
# ### Peek at SWE

# %%
# Reload for plotting (subset already saved)
SWE_plot = xr.open_dataset(obsdir / "SWE.nc")
time_slice_swe = slice("2005-01-01", "2020-12-30")

# --- Daily SWE bounds ---
fig = go.Figure()
for hru, color in zip(hru_sel, colors):
    swe_max = SWE_plot["upper_bound"].sel(nhm_id=hru, time=time_slice_swe)
    swe_min = SWE_plot["lower_bound"].sel(nhm_id=hru, time=time_slice_swe)
    fig.add_trace(
        go.Scatter(
            x=swe_max.time.values,
            y=swe_max.values,
            mode="lines",
            name=f"{hru} upper (line)",
            line=dict(color=color),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=swe_max.time.values,
            y=swe_max.values,
            mode="markers",
            name=f"{hru} upper (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=swe_min.time.values,
            y=swe_min.values,
            mode="lines",
            name=f"{hru} lower (line)",
            line=dict(color=color, dash="dash"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=swe_min.time.values,
            y=swe_min.values,
            mode="markers",
            name=f"{hru} lower (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig.update_layout(
    title="SWE bounds (daily)",
    xaxis_title="Time",
    yaxis_title="SWE",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig.show()

# %% jupyter={"source_hidden": true}
# --- Weekly mean SWE bounds ---
fig_w = go.Figure()
for hru, color in zip(hru_sel, colors):
    swe_max_w = (
        SWE_plot["upper_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1W")
        .mean()
    )
    swe_min_w = (
        SWE_plot["lower_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1W")
        .mean()
    )
    fig_w.add_trace(
        go.Scatter(
            x=swe_max_w.time.values,
            y=swe_max_w.values,
            mode="lines",
            name=f"{hru} upper (line)",
            line=dict(color=color),
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=swe_max_w.time.values,
            y=swe_max_w.values,
            mode="markers",
            name=f"{hru} upper (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=swe_min_w.time.values,
            y=swe_min_w.values,
            mode="lines",
            name=f"{hru} lower (line)",
            line=dict(color=color, dash="dash"),
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=swe_min_w.time.values,
            y=swe_min_w.values,
            mode="markers",
            name=f"{hru} lower (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_w.update_layout(
    title="SWE bounds (weekly mean)",
    xaxis_title="Time",
    yaxis_title="SWE",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_w.show()

# %%
# --- 5-day rolling average SWE bounds ---
fig_5d = go.Figure()
for hru, color in zip(hru_sel, colors):
    swe_max_5d = (
        SWE_plot["upper_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .rolling(time=5, center=True)
        .mean()
    )
    swe_min_5d = (
        SWE_plot["lower_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .rolling(time=5, center=True)
        .mean()
    )
    fig_5d.add_trace(
        go.Scatter(
            x=swe_max_5d.time.values,
            y=swe_max_5d.values,
            mode="lines",
            name=f"{hru} upper (line)",
            line=dict(color=color),
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=swe_max_5d.time.values,
            y=swe_max_5d.values,
            mode="markers",
            name=f"{hru} upper (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=swe_min_5d.time.values,
            y=swe_min_5d.values,
            mode="lines",
            name=f"{hru} lower (line)",
            line=dict(color=color, dash="dash"),
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=swe_min_5d.time.values,
            y=swe_min_5d.values,
            mode="markers",
            name=f"{hru} lower (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_5d.update_layout(
    title="SWE bounds (5-day rolling average)",
    xaxis_title="Time",
    yaxis_title="SWE",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_5d.show()

# %% jupyter={"source_hidden": true}
# --- Monthly mean SWE bounds ---
fig_m = go.Figure()
for hru, color in zip(hru_sel, colors):
    swe_max_m = (
        SWE_plot["upper_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1ME")
        .mean()
    )
    swe_min_m = (
        SWE_plot["lower_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1ME")
        .mean()
    )
    fig_m.add_trace(
        go.Scatter(
            x=swe_max_m.time.values,
            y=swe_max_m.values,
            mode="lines",
            name=f"{hru} upper (line)",
            line=dict(color=color),
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=swe_max_m.time.values,
            y=swe_max_m.values,
            mode="markers",
            name=f"{hru} upper (points)",
            marker=dict(size=5, color=color),
            visible="legendonly",
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=swe_min_m.time.values,
            y=swe_min_m.values,
            mode="lines",
            name=f"{hru} lower (line)",
            line=dict(color=color, dash="dash"),
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=swe_min_m.time.values,
            y=swe_min_m.values,
            mode="markers",
            name=f"{hru} lower (points)",
            marker=dict(size=5, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_m.update_layout(
    title="SWE bounds (monthly mean)",
    xaxis_title="Time",
    yaxis_title="SWE",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_m.show()

# %% [markdown]
# ### Compound plots: SCA and SWE stacked (daily, 5-day average, monthly)

# %%
from plotly.subplots import make_subplots

# --- Compound: Daily SCA (top) and SWE (bottom) ---
fig_comp_d = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    subplot_titles=("SCA bounds (daily)", "SWE bounds (daily)"),
)

for hru, color in zip(hru_sel, colors):
    # SCA daily
    sca_max_d = c_da.SCA_max.sel(nhm_id=hru, time=time_slice)
    sca_min_d = c_da.SCA_min.sel(nhm_id=hru, time=time_slice)
    fig_comp_d.add_trace(
        go.Scatter(
            x=sca_max_d.time.values,
            y=sca_max_d.values,
            mode="lines",
            name=f"{hru} SCA_max",
            line=dict(color=color),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=1,
        col=1,
    )
    fig_comp_d.add_trace(
        go.Scatter(
            x=sca_min_d.time.values,
            y=sca_min_d.values,
            mode="lines",
            name=f"{hru} SCA_min",
            line=dict(color=color, dash="dash"),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=1,
        col=1,
    )
    # SWE daily
    swe_max_d = SWE_plot["upper_bound"].sel(nhm_id=hru, time=time_slice_swe)
    swe_min_d = SWE_plot["lower_bound"].sel(nhm_id=hru, time=time_slice_swe)
    fig_comp_d.add_trace(
        go.Scatter(
            x=swe_max_d.time.values,
            y=swe_max_d.values,
            mode="lines",
            name=f"{hru} SWE upper",
            line=dict(color=color),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=2,
        col=1,
    )
    fig_comp_d.add_trace(
        go.Scatter(
            x=swe_min_d.time.values,
            y=swe_min_d.values,
            mode="lines",
            name=f"{hru} SWE lower",
            line=dict(color=color, dash="dash"),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=2,
        col=1,
    )

fig_comp_d.update_yaxes(title_text="SCA (fraction)", row=1, col=1)
fig_comp_d.update_yaxes(title_text="SWE", row=2, col=1)
fig_comp_d.update_xaxes(title_text="Time", row=2, col=1)
fig_comp_d.update_layout(height=700, title_text="Daily: SCA and SWE")
fig_comp_d.show()

# %%
# --- Compound: 5-day rolling average SCA (top) and SWE (bottom) ---
fig_comp_5d = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    subplot_titles=("SCA bounds (5-day avg)", "SWE bounds (5-day avg)"),
)

for hru, color in zip(hru_sel, colors):
    # SCA 5-day
    sca_max_5d = (
        c_da.SCA_max.sel(nhm_id=hru, time=time_slice)
        .rolling(time=5, center=True)
        .mean()
    )
    sca_min_5d = (
        c_da.SCA_min.sel(nhm_id=hru, time=time_slice)
        .rolling(time=5, center=True)
        .mean()
    )
    fig_comp_5d.add_trace(
        go.Scatter(
            x=sca_max_5d.time.values,
            y=sca_max_5d.values,
            mode="lines",
            name=f"{hru} SCA_max",
            line=dict(color=color),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=1,
        col=1,
    )
    fig_comp_5d.add_trace(
        go.Scatter(
            x=sca_min_5d.time.values,
            y=sca_min_5d.values,
            mode="lines",
            name=f"{hru} SCA_min",
            line=dict(color=color, dash="dash"),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=1,
        col=1,
    )
    # SWE 5-day
    swe_max_5d = (
        SWE_plot["upper_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .rolling(time=5, center=True)
        .mean()
    )
    swe_min_5d = (
        SWE_plot["lower_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .rolling(time=5, center=True)
        .mean()
    )
    fig_comp_5d.add_trace(
        go.Scatter(
            x=swe_max_5d.time.values,
            y=swe_max_5d.values,
            mode="lines",
            name=f"{hru} SWE upper",
            line=dict(color=color),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=2,
        col=1,
    )
    fig_comp_5d.add_trace(
        go.Scatter(
            x=swe_min_5d.time.values,
            y=swe_min_5d.values,
            mode="lines",
            name=f"{hru} SWE lower",
            line=dict(color=color, dash="dash"),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=2,
        col=1,
    )

fig_comp_5d.update_yaxes(title_text="SCA (fraction)", row=1, col=1)
fig_comp_5d.update_yaxes(title_text="SWE", row=2, col=1)
fig_comp_5d.update_xaxes(title_text="Time", row=2, col=1)
fig_comp_5d.update_layout(height=700, title_text="5-day Average: SCA and SWE")
fig_comp_5d.show()

# %%
# --- Compound: Monthly mean SCA (top) and SWE (bottom) ---
fig_comp_m = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    subplot_titles=("SCA bounds (monthly mean)", "SWE bounds (monthly mean)"),
)

for hru, color in zip(hru_sel, colors):
    # SCA monthly
    sca_max_m = (
        c_da.SCA_max.sel(nhm_id=hru, time=time_slice).resample(time="1ME").mean()
    )
    sca_min_m = (
        c_da.SCA_min.sel(nhm_id=hru, time=time_slice).resample(time="1ME").mean()
    )
    fig_comp_m.add_trace(
        go.Scatter(
            x=sca_max_m.time.values,
            y=sca_max_m.values,
            mode="lines+markers",
            name=f"{hru} SCA_max",
            line=dict(color=color),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=1,
        col=1,
    )
    fig_comp_m.add_trace(
        go.Scatter(
            x=sca_min_m.time.values,
            y=sca_min_m.values,
            mode="lines+markers",
            name=f"{hru} SCA_min",
            line=dict(color=color, dash="dash"),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=1,
        col=1,
    )
    # SWE monthly
    swe_max_m = (
        SWE_plot["upper_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1ME")
        .mean()
    )
    swe_min_m = (
        SWE_plot["lower_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1ME")
        .mean()
    )
    fig_comp_m.add_trace(
        go.Scatter(
            x=swe_max_m.time.values,
            y=swe_max_m.values,
            mode="lines+markers",
            name=f"{hru} SWE upper",
            line=dict(color=color),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=2,
        col=1,
    )
    fig_comp_m.add_trace(
        go.Scatter(
            x=swe_min_m.time.values,
            y=swe_min_m.values,
            mode="lines+markers",
            name=f"{hru} SWE lower",
            line=dict(color=color, dash="dash"),
            legendgroup=f"{hru}",
            showlegend=True,
        ),
        row=2,
        col=1,
    )

fig_comp_m.update_yaxes(title_text="SCA (fraction)", row=1, col=1)
fig_comp_m.update_yaxes(title_text="SWE", row=2, col=1)
fig_comp_m.update_xaxes(title_text="Time", row=2, col=1)
fig_comp_m.update_layout(height=700, title_text="Monthly Mean: SCA and SWE")
fig_comp_m.show()

# %%
