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
import shutil

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
# # Introduction
# This notebook will make files for the pest-ies setup: 
# `allobs.dat`
# This file is observations that pest will match with model output in the model calibration.
#
# The pest instruction  file is a file that connects the pywatershed model output after each model run to the calibration targets listed in the pest observation file. For clarity, each line in the `allobs.dat` file corresponds to the same indexed line in the `modelobs.dat.ins` file, and aslo the model output file, `modelobs.dat`. 
#
# This notebook will first consolidate the hru observation files that were written with notebook `Subset_NHM_baselines`for the model, assign observation names for each observation, and write observations names and observations into a single file with 2 columns for PEST++ to read.
#
# Then, the instruction file is made from the observations file with
#
# Lastly, this notebook will run the model and postprocess the model output to mirror the observations listed in the instruction file and perform checks to ensure that the lines in the model output file, instruction file, and observation file coorelate to the same observation name. If and error is found, some tips are offered for the corrective approach.
#
#

# %% [markdown]
# # Workspace Setup
# Create `pestpp_ies` folder in the model directory
# All pestpp-ies files needed to run the model usng pestpp-ies will be placed here.

# %%
if not (config["model_dir"] / "pestpp_ies").exists():
    (config["model_dir"] / "pestpp_ies").mkdir()
pestpp_model_dir = config["model_dir"] / "pestpp_ies"
pestpp_dir = root_dir / "pestpp_ies_calibration"

if not (pestpp_model_dir / "observation_data").exists():
    (pestpp_model_dir / "observation_data").mkdir()
obsdir = pestpp_model_dir / "observation_data"

if not (pestpp_model_dir / "ancillary").exists():
    (pestpp_model_dir / "ancillary").mkdir()
ancillary_dir = pestpp_model_dir / "ancillary"

if not (pestpp_model_dir / "output").exists():
    (pestpp_model_dir / "output").mkdir()
output_dir = pestpp_model_dir / "output"

# %%
pws_prcp_input_file = config["model_dir"] / "prcp.nc"
pws_tmin_input_file = config["model_dir"] / "tmin.nc"
pws_tmax_input_file = config["model_dir"] / "tmax.nc"
nhmx_input_file = config["model_dir"] / "cbh.nc"
input_file_path_list = [pws_prcp_input_file, pws_tmin_input_file, pws_tmax_input_file]

for input_file_path in input_file_path_list:
    if not input_file_path.exists():
        con.print(
            "One or more of the pywatershed input files does not exist. All input file will be rewritten from the cbh.nc file."
        )
        with xr.open_dataset(
            nhmx_input_file
        ) as input:  # This is the input file given with NHMx
            model_input = input.swap_dims({"nhru": "nhm_id"}).drop("nhru")
            prcp = getattr(model_input, "prcp")
            tmin = getattr(model_input, "tmin")
            tmax = getattr(model_input, "tmax")
        prcp.to_netcdf(pws_prcp_input_file)
        tmin.to_netcdf(pws_tmin_input_file)
        tmax.to_netcdf(pws_tmax_input_file)
        con.print(
            f"The pywatershed input file [bold]{pl.Path(input_file_path).stem}[/bold] was missing. All pywatershed input files were created in {config['model_dir']} from the cbh.nc file."
        )
    else:
        pass
con.print(
    f"[bold][green]Optional:[/bold][/green] To recreate pywatershed input files in {config['model_dir']}, delete [bold]prcp.nc[/bold], [bold]tmin.nc[/bold], and [bold]tmax.nc[/bold] files and re-run this notebook."
)

# %%
# Copy template to subdomain model folder for editing
file_list = [
    "localization_groups.csv",
    "Observation_standard_deviation.csv",
    "par_cal_bounds_use.csv",
    "target_and_output_vars_table.csv",
    "zero_weighting.csv",
]
for file in file_list:
    source = pestpp_dir / f"data_dependencies/ancillary_template/{file}"
    destination = ancillary_dir / f"{file}"
    shutil.copy2(source, destination)


# These file need to be moved over to run pest remotely.
model_file_list = [
    "control.default.bandit",
    "tmin.nc",
    "tmax.nc",
    "prcp.nc",
]

for file in model_file_list:
    source = config["model_dir"] / file
    destination = pestpp_model_dir / file
    shutil.copy2(source, destination)

# %%
all_nc_files = sorted([i for i in (obsdir).glob("*.nc")])  # Read in the files to check
# all_nc_files #Checks all the subset observation files from the CONUS NHM outputs

# %%
# from netCDF4 import Dataset

# all_nc_files = sorted(obsdir.glob("*.nc"))

# for path in all_nc_files:
#     print(f"\nFile: {path.name}")
#     with Dataset(path) as nc:
#         for vname, var in nc.variables.items():
#             dims = var.dimensions  # tuple of dimension names
#             shape = var.shape  # tuple of sizes along dims
#             print(f"  {vname}: dims={dims}, shape={shape}")

# %%
for path in all_nc_files:
    ds = xr.open_dataset(path)
    if path.name == "AET_mean_monthly.nc":
        months = ds["month"].values

    else:
        # adjust 'time' to your actual coordinate name if different
        time = ds["time"]
        # If time is already decoded as datetimes
        t_start = pd.to_datetime(time.min().values)
        t_end = pd.to_datetime(time.max().values)

    if path.name == "AET_mean_monthly.nc":
        print(f"{path.name}: months = {months}")
    else:
        print(
            f"{path.name}: {t_start.strftime('%Y/%m/%d')}  ->  {t_end.strftime('%Y/%m/%d')}"
        )

    ds.close()

# %%
# Make a file to hold the consolidated results used for the pest++ .ins file
ofp = open(
    pestpp_model_dir / "allobs.dat", "w"
)  # the 'w' will delete any existing file here and recreate; 'a' appends

# Make a file to hold the consolidated results used for the pest++ range bounds
# in the pest observation file (notebook 3)
ofp = open(pestpp_model_dir / "allobs_bounds.dat", "w")

# %% [markdown]
# # Format Observations

# %%
##  AET  monthly (Note that these values are in inches/day, and a daily average rate for the month--Jacob verified)
cdat = xr.open_dataset(obsdir / "AET_monthly.nc")
# set up the indices in sequence
inds = [
    f"actet_mon:{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]

# Write the observations to the observations.dat file for use in creating the instruction file
actet_mon = (cdat.aet_max + cdat.aet_min) / 2
varvals = np.ravel(actet_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    ofp.write("obsname    obsval\n")  # writing a header for the file
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]


obsvals_max = np.ravel(cdat.aet_max, order="C")  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(cdat.aet_min, order="C")  # flattens the 2D array to a 1D array
obs_bounds_df = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

# %%
##  AET mean monthly
cdat = xr.open_dataset(obsdir / "AET_mean_monthly.nc")
# set up the indices in sequence
inds = [
    f"actet_mean_mon:{i}:{j}"
    for i in cdat.indexes["month"]
    for j in cdat.indexes["nhru"]
]

actet_mean_mon = (cdat.aet_max + cdat.aet_min) / 2
varvals = np.ravel(actet_mean_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]


obsvals_max = np.ravel(cdat.aet_max, order="C")  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(cdat.aet_min, order="C")  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %%
# aet_mean_obs.sel(month= 1)

# %%
##  RCH  annual
cdat = xr.open_dataset(obsdir / "RCH_annual.nc")
# set up the indices in sequence
inds = [
    f"recharge_ann:{i.year}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]

recharge_ann = (cdat.recharge_max_norm + cdat.recharge_min_norm) / 2
varvals = np.ravel(recharge_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

obsvals_max = np.ravel(
    cdat.recharge_max_norm, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.recharge_min_norm, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %%
##  Soil Moisture  monthly
cdat = xr.open_dataset(obsdir / "Soil_Moisture_monthly.nc")
# set up the indices in sequence
inds = [
    f"soil_moist_mon:{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]

soil_moist_mon = (cdat.soil_moist_max_norm + cdat.soil_moist_min_norm) / 2
varvals = np.ravel(soil_moist_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]


obsvals_max = np.ravel(
    cdat.soil_moist_max_norm, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.soil_moist_min_norm, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %%
##  Soil_Moisture annual
cdat = xr.open_dataset(obsdir / "Soil_Moisture_annual.nc")
# set up the indices in sequence
inds = [
    f"soil_moist_ann:{i.year}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]

soil_moist_ann = (cdat.soil_moist_max_norm + cdat.soil_moist_min_norm) / 2
varvals = np.ravel(soil_moist_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

obsvals_max = np.ravel(
    cdat.soil_moist_max_norm, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.soil_moist_min_norm, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)
obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %%
##  RUN  monthly (This is an average daily rate in cfs for the month)
cdat = xr.open_dataset(obsdir / "hru_streamflow_monthly.nc")
# set up the indices in sequence
inds = [
    f"runoff_mon:{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]
runoff_mon = (cdat.runoff_max + cdat.runoff_min) / 2
varvals = np.ravel(runoff_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

obsvals_max = np.ravel(
    cdat.runoff_max, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.runoff_min, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)
obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %% [markdown]
# ## the following has NaNs for SCA daily that got rejected by the filter. Need to decide if totally drop, or give a dummary value (-999) or whatnot

# %%
##  Snow_covered_area daily
cdat = xr.open_dataset(obsdir / "SCA_daily.nc")
cdat = cdat.fillna(-9999)
# set up the indices in sequence
inds = [
    f"sca_daily:{i.year}_{i.month}_{i.day}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhru"]
]
sca_daily = (cdat.SCA_max + cdat.SCA_min) / 2
varvals = np.ravel(sca_daily, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

obsvals_max = np.ravel(cdat.SCA_max, order="C")  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(cdat.SCA_min, order="C")  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %%
# Write the bounds_df
obs_bounds_df.to_csv(pestpp_model_dir / "allobs_bounds.dat", index=False)

# %% [markdown]
# ##  Streamflow daily
# Warning: You must run the EFC notebook prior to this block to create the new sf file with EFC codes "EFC_netcdf"

# %%
seg_outflow_start = "1999-10-01"
seg_outflow_end = "2010-09-30"

# seg_outflow_start = "2011-01-01"  # Note: For ease, the start and end dates must be same as those designated in
# seg_outflow_end = "2022-12-31"  #    "the Create_pest_model_observation_file."

## Set up validation years
start_water_year = pd.to_datetime(seg_outflow_start).year + 1
end_water_year = pd.to_datetime(seg_outflow_end).year
streamflow_water_years = np.array(range(start_water_year, end_water_year + 1))

## We will choose even years as validation
val_water_years = [i for i in streamflow_water_years if i % 2 == 0]
cal_water_years = [i for i in streamflow_water_years if i % 2 != 0]

# read in param file
param_file = config["model_dir"] / "myparam.param"
# parameters_json_file = pestpp_model_dir / "parameters.json"
pardat = pws.parameters.PrmsParameters.load(param_file)
paramfile_poi_gage_id_list = pardat.parameters.get("poi_gage_id").tolist()


cdat = xr.open_dataset(config["nc_files_dir"] / "sf_efc.nc").sel(
    time=slice(seg_outflow_start, seg_outflow_end),
)
cdat = cdat.sel(poi_id=cdat.poi_id.isin(paramfile_poi_gage_id_list))
cdat = cdat.reindex(poi_id=paramfile_poi_gage_id_list)

cdat = cdat[["discharge", "efc", "high_low"]]

# %%
cdat

# %%
moo = cdat.discharge.to_dataframe()
# moo.loc[moo['discharge'] <0]
obs_poi_list = moo.index.get_level_values(0).unique().tolist()

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

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
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

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
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

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
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

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_mean_mon_val:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]
