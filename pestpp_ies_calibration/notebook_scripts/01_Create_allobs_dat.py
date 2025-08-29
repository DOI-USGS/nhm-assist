# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.17.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import sys
import os
import pathlib as pl
import warnings

import pywatershed as pws
import xarray as xr
import numpy as np
import pandas as pd
import datetime

warnings.filterwarnings("ignore")
from rich.console import Console

con = Console()
from rich import pretty

pretty.install()
import jupyter_black

jupyter_black.load()
# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))
print(root_dir)
from nhm_helpers.nhm_assist_utilities import load_subdomain_config
from nhm_helpers import efc

config = load_subdomain_config(root_dir)

# %% [markdown]
# ## Load in NHM-Assist paths and model configuration set in Notebook 0_workspace_setup.ipynb

# %%
if not (config["model_dir"] / "pestpp_ies").exists():
    (config["model_dir"] / "pestpp_ies").mkdir()
pestpp_dir = config["model_dir"] / "pestpp_ies"

# %% [markdown]
# ### This notebook will read in the consolidated NC files that were written with notebook  `Subset_NHM_baselines`for each subbasin extraction, assign names for each obs, and write names and observations into a single file with 2 columns for PEST++ to read.

# %% [markdown]
# ### Designate the list on subabsin extraction and the root directory that contains it.

# %%
# cm = all_models[2] # sets cutout from list
# cm = snakemake.params['basin']
obsdir = (
    pestpp_dir / "observation_data"
)  # This is where the observation files for each extraction were written.

# %%
all_nc_files = sorted([i for i in (obsdir).glob("*.nc")])  # Read in the files to check

# %%
# all_nc_files #Checks all the subset observation files from the CONUS NHM outputs

# %%
# make a file to hold the consolidated results
ofp = open(
    pestpp_dir / "allobs.dat", "w"
)  # the 'w' will delete any existing file here and recreate; 'a' appends

# make allobs "old" verison of file that has l_ and g_ -- we will use this later to set the range bounds in the pest parameter data
ofp = open(pestpp_dir / "allobs_bounds.dat", "w")

# %%
##  AET  monthly (Note that these values are in inches/day, and a daily average rate for the month--Jacob verified)
cdat = xr.open_dataset(obsdir / "AET_monthly.nc")
# set up the indices in sequence
inds = [
    f"{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]

actet_mon = (cdat.aet_max + cdat.aet_min) / 2
varvals = np.ravel(actet_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    ofp.write("obsname    obsval\n")  # writing a header for the file
    [
        ofp.write(f"actet_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# sets the non-penalized condition to less than the max value
l_max_actet_mon = cdat.aet_max
varvals = np.ravel(l_max_actet_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    ofp.write("obsname    obsval\n")  # writing a header for the file
    [
        ofp.write(f"l_max_actet_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# sets the non-penalized condition to greater than the min value
g_min_actet_mon = cdat.aet_min
varvals = np.ravel(g_min_actet_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"g_min_actet_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# aet_mean_obs
# aet_monthly_obs.sel(time= '2000-01-01') # look at a slice of the netcdf and compare to pest write

# %%

# %%
##  AET mean monthly
cdat = xr.open_dataset(obsdir / "AET_mean_monthly.nc")
# set up the indices in sequence
inds = [f"{i}:{j}" for i in cdat.indexes["month"] for j in cdat.indexes["nhru"]]

actet_mean_mon = (cdat.aet_max + cdat.aet_min) / 2
varvals = np.ravel(actet_mean_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"actet_mean_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

l_max_actet_mean_mon = cdat.aet_max
varvals = np.ravel(
    l_max_actet_mean_mon, order="C"
)  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"l_max_actet_mean_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]


# sets the non-penalized condition to greater than the min value
g_min_actet_mean_mon = cdat.aet_min
varvals = np.ravel(
    g_min_actet_mean_mon, order="C"
)  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"g_min_actet_mean_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# aet_mean_obs.sel(month= 1)

# %%
##  RCH  annual
cdat = xr.open_dataset(obsdir / "RCH_annual.nc")
# set up the indices in sequence
inds = [f"{i.year}:{j}" for i in cdat.indexes["time"] for j in cdat.indexes["nhru"]]

recharge_ann = (cdat.recharge_max_norm + cdat.recharge_min_norm) / 2
varvals = np.ravel(recharge_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"recharge_ann:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

l_max_recharge_ann = cdat.recharge_max_norm
varvals = np.ravel(l_max_recharge_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"l_max_recharge_ann:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

g_min_recharge_ann = cdat.recharge_min_norm
varvals = np.ravel(g_min_recharge_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"g_min_recharge_ann:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# recharge_mean_obs.sel(time='2000-01-01')

# %%
##  Soil Moisture  monthly
cdat = xr.open_dataset(obsdir / "Soil_Moisture_monthly.nc")
# set up the indices in sequence
inds = [
    f"{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]

soil_moist_mon = (cdat.soil_moist_max_norm + cdat.soil_moist_min_norm) / 2
varvals = np.ravel(soil_moist_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"soil_moist_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

l_max_soil_moist_mon = cdat.soil_moist_max_norm
varvals = np.ravel(
    l_max_soil_moist_mon, order="C"
)  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"l_max_soil_moist_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

g_min_soil_moist_mon = cdat.soil_moist_min_norm
varvals = np.ravel(
    g_min_soil_moist_mon, order="C"
)  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"g_min_soil_moist_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# soil_moist_mean_obs.sel(time='1982-01-01')

# %%
##  Soil_Moisture annual
cdat = xr.open_dataset(obsdir / "Soil_Moisture_annual.nc")
# set up the indices in sequence
inds = [f"{i.year}:{j}" for i in cdat.indexes["time"] for j in cdat.indexes["nhru"]]

soil_moist_ann = (cdat.soil_moist_max_norm + cdat.soil_moist_min_norm) / 2
varvals = np.ravel(soil_moist_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"soil_moist_ann:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

l_max_soil_moist_ann = cdat.soil_moist_max_norm
varvals = np.ravel(
    l_max_soil_moist_ann, order="C"
)  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"l_max_soil_moist_ann:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]


g_min_soil_moist_ann = cdat.soil_moist_min_norm
varvals = np.ravel(
    g_min_soil_moist_ann, order="C"
)  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"g_min_soil_moist_ann:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# soil_moist_mean_obs.sel(time='1982-01-01')

# %%
cdat

# %%
##  RUN  monthly (This is an average daily rate in cfs for the month)
cdat = xr.open_dataset(obsdir / "hru_streamflow_monthly.nc")
# set up the indices in sequence
inds = [
    f"{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]

runoff_mon = (cdat.runoff_max + cdat.runoff_min) / 2
varvals = np.ravel(runoff_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"runoff_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

l_max_runoff_mon = cdat.runoff_max
varvals = np.ravel(l_max_runoff_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"l_max_runoff_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

g_min_runoff_mon = cdat.runoff_min
varvals = np.ravel(g_min_runoff_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"g_min_runoff_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# cdat.runoff_mwbm.sel(time='1982-01-01')

# %% [markdown]
# ## the following has NaNs for SCA daily that got rejected by the filter. Need to decide if totally drop, or give a dummary value (-999) or whatnot

# %%
##  Snow_covered_area daily
cdat = xr.open_dataset(obsdir / "SCA_daily.nc")
cdat = cdat.fillna(-9999)
# set up the indices in sequence
inds = [
    f"{i.year}_{i.month}_{i.day}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]

sca_daily = (cdat.SCA_max + cdat.SCA_min) / 2
varvals = np.ravel(sca_daily, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"sca_daily:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

l_max_sca_daily = cdat.SCA_max
varvals = np.ravel(l_max_sca_daily, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"l_max_sca_daily:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

g_min_sca_daily = cdat.SCA_min
varvals = np.ravel(g_min_sca_daily, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_dir / "allobs_bounds.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"g_min_sca_daily:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# SCA_mean_obs.sel(time='2000-02-28')

# %%
##  Streamflow daily
###### Warning: You must run the EFC notebook prior to this block to create the new sf file with EFC codes "EFC_netcdf"
seg_outflow_start = "2011-01-01"  # Note: For ease, the start and end dates must be same as those designated in
seg_outflow_end = "2022-12-31"  #    "the Create_pest_model_observation_file."

## Set up validation years
start_water_year = pd.to_datetime(seg_outflow_start).year + 1
end_water_year = pd.to_datetime(seg_outflow_end).year
streamflow_water_years = np.array(range(start_water_year, end_water_year + 1))

## We will choose even years as validation
val_water_years = [i for i in streamflow_water_years if i % 2 == 0]
cal_water_years = [i for i in streamflow_water_years if i % 2 != 0]


cdat = xr.open_dataset(config["nc_files_dir"] / "sf_efc.nc").sel(
    time=slice(seg_outflow_start, seg_outflow_end),
)

cdat = cdat[["discharge", "efc", "high_low"]]

# %%
cdat

# %%
moo = cdat.discharge.to_dataframe()
# moo.loc[moo['discharge'] <0]
moo.index.get_level_values(0).unique()

# %%
# Creates a dataframe time series of monthly values (average daily rate for the month)
cdat_monthly = cdat.resample(time="ME").mean(skipna=True)
cdat_monthly["wateryear"] = [
    (i + pd.DateOffset(30 + 31 + 31)).year for i in cdat_monthly.time.values
]

# %%
# Creates dataframe time series of mean monthly (mean of all jan, feb, mar....) for calibration and validation
# years separately
# cdat_mean_monthly = cdat_monthly.groupby('time.month').mean(skipna=True)

# pro-tip - gotta use sel with two conditions, but .values breaks the connection to the index using
#           a boolean based on one condition to subset another
cdat_monthly_val = cdat_monthly.sel(
    time=cdat_monthly.wateryear.isin(val_water_years).values,
    wateryear=cdat_monthly.wateryear.isin(val_water_years),
)
cdat_monthly_cal = cdat_monthly.sel(
    time=cdat_monthly.wateryear.isin(cal_water_years).values,
    wateryear=cdat_monthly.wateryear.isin(cal_water_years),
)

cdat_mean_monthly_cal = cdat_monthly_cal.groupby("time.month").mean(skipna=True)
cdat_mean_monthly_val = cdat_monthly_val.groupby("time.month").mean(skipna=True)

# %%
cdat_mean_monthly_cal = cdat_mean_monthly_cal.fillna(-9999)
cdat_mean_monthly_val = cdat_mean_monthly_val.fillna(-9999)
cdat_monthly = cdat_monthly.fillna(-9999)
cdat = cdat.fillna(-9999)

# %%
# streamflow_daily is followed by a suffix: "efc"_"high_low" integers
# efc [1, 2, 3, 4, 5] are ['Large flood', 'Small flood', 'High flow pulse', 'Low flow', 'Extreme low flow']
# high_low [1, 2, 3] are ['Low flow', 'Ascending limb', 'Descending limb']

# set up the indices in sequence
inds = [
    f'_{int(cdat["efc"].sel(poi_id=j, time=i).item())}_{int(cdat["high_low"].sel(poi_id=j, time=i).item())}:{i.year}_{i.month}_{i.day}:{j}'
    for j in cdat.indexes["poi_id"]
    for i in cdat.indexes["time"]
]

# get the variable names
# dvs = list(cdat.keys())

varvals = np.ravel(cdat["discharge"], order="C")  # flattens the 2D array to a 1D array

with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_daily{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# Now write to the pest obs file
inds = [
    f"{i.year}_{i.month}:{j}"
    for j in cdat_monthly.indexes["poi_id"]
    for i in cdat_monthly.indexes["time"]
]  # set up the indices in sequence
varvals = np.ravel(
    cdat_monthly["discharge"], order="F"
)  # flattens the 2D array to a 1D array--just playing

with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
inds = [
    f"{i}:{j}"
    for j in cdat_mean_monthly_cal.indexes["poi_id"]
    for i in cdat_mean_monthly_cal.indexes["month"]
]
varvals = np.ravel(
    cdat_mean_monthly_cal["discharge"], order="F"
)  # flattens the 2D array to a 1D array

with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_mean_mon_cal:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
inds = [
    f"{i}:{j}"
    for j in cdat_mean_monthly_val.indexes["poi_id"]
    for i in cdat_mean_monthly_val.indexes["month"]
]
varvals = np.ravel(
    cdat_mean_monthly_val["discharge"], order="F"
)  # flattens the 2D array to a 1D array

with open(pestpp_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_mean_mon_val:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
