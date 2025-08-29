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
# ### This notebook subsets the NHM CONUS baseline data used for calibration targets to create observation files (.nc) for each model extraction in the root folder. These created files will be read by the subsequent Notebook to make files used (read during) in PEST++ calibration.
# #### This notebook also preprocesses the SCA baseline data to emulate the filtering that is done in NHM calibration with Fortran.
# #### This only needs to be run once.

# %% [markdown]
# ### Make a pest_ies folder in the model directory to hold all pest_ies related files

# %%
if not (config["model_dir"] / "pestpp_ies").exists():
    (config["model_dir"] / "pestpp_ies").mkdir()
pestpp_model_dir = config["model_dir"] / "pestpp_ies"
pestpp_dir = root_dir / "pestpp_ies_calibration"

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
conus_baselines_dir = pestpp_dir / "data_dependencies/NHM_v1_1/CONUS_baselines"
[i for i in conus_baselines_dir.glob("*.nc")]

# %% [markdown]
# ### Slice output to calibration periods for each variable
# #### These are as follows from table 2 (Hay and others, 2023):
#

# %%
aet_start = "2000-01-01"
aet_end = "2010-12-31"
recharge_start = "2000-01-01"
recharge_end = "2009-12-31"
runoff_start = "1982-01-01"
runoff_end = "2010-12-31"
soil_rechr_start = "1982-01-01"
soil_rechr_end = "2010-12-31"
sca_start = "2000-01-01"
sca_end = "2010-12-31"

# %% [markdown]
# ### Subset AET NHM baseline data

# %%
# Use larger, manual chunks for efficiency
AET_all = xr.open_dataset(
    conus_baselines_dir / "baseline_AET_v11.nc", chunks={"time": 12, "nhru": 500}
)

c_da = AET_all.sel(nhru=nhm_ids)
# Always pre-load before writing for speed
c_da[["aet_max", "aet_min"]].load().to_netcdf(obsdir / f"AET_monthly.nc")

# Compute mean in memory, then write
c_da.groupby("time.month").mean().load().to_netcdf(obsdir / f"AET_mean_monthly.nc")

AET_all.close()

# %%
# AET_all = xr.open_dataset(conus_baselines_dir / "baseline_AET_v11.nc", chunks="auto")
# # AET_all

# %%
# c_da = AET_all.sel(nhru=nhm_ids)
# c_da[["aet_max", "aet_min"]].to_netcdf(obsdir / f"AET_monthly.nc")
# c_da.groupby("time.month").mean().to_netcdf(obsdir / f"AET_mean_monthly.nc")
# AET_all.close()

# %% [markdown]
# ###  Subset HRU Streamflow (RUNOFF NHM) baseline data--The MWBM term, "runoff" is total contribution to streamflow from each HRU. We are re-terming this in the subset file to "hru_streamflow" to clearly describe HRU contributions to streamflow.

# %%
RUN_all = xr.open_dataset(conus_baselines_dir / "baseline_RUN_v11.nc", chunks="auto")
# RUN_all

# %%
c_da = RUN_all.sel(nhru=nhm_ids, time=slice(runoff_start, runoff_end))
c_da[["runoff_mwbm", "runoff_min", "runoff_max"]].to_netcdf(
    obsdir / f"hru_streamflow_monthly.nc"
)
RUN_all.close()

# %% [markdown]
# ### Subset Annual Recharge
# ### These annual values are actually the average daily rate; and, match the units of the output.

# %%
RCH_all = xr.open_dataset(conus_baselines_dir / "baseline_RCH_v11.nc", chunks="auto")
RCH_all

# %%
c_da = RCH_all.sel(nhru=nhm_ids)
c_da[["recharge_min_norm", "recharge_max_norm"]].to_netcdf(obsdir / f"RCH_annual.nc")
RCH_all.close()

# %%
c_da.recharge_min_norm.values

# %% [markdown]
# ### Subset Annual Soil Moisture

# %%
SOM_ann_all = xr.open_dataset(
    conus_baselines_dir / "baseline_SOMann_v11.nc", chunks="auto"
)
SOM_ann_all

# %%
c_da = SOM_ann_all.sel(nhru=nhm_ids)
c_da[["soil_moist_min_norm", "soil_moist_max_norm"]].to_netcdf(
    obsdir / f"Soil_Moisture_annual.nc"
)
SOM_ann_all.close()

# %% [markdown]
# ### Subset Monthly Soil Moisture

# %%
SOM_mon_all = xr.open_dataset(
    conus_baselines_dir / "baseline_SOMmth_v11.nc", chunks="auto"
)
SOM_mon_all

# %%
c_da = SOM_mon_all.sel(nhru=nhm_ids)
c_da[["soil_moist_min_norm", "soil_moist_max_norm"]].to_netcdf(
    obsdir / "Soil_Moisture_monthly.nc"
)
SOM_mon_all.close()

# %% [markdown]
# ### Subset and pre-process Daily Snow Covered Area

# %%
# Read the raw data set. Lauren Hay developed fortran code embedded in the NHM that pre-processed the raw data,
# applying several filters.
SCA = xr.open_dataset(conus_baselines_dir / "baseline_SCA_v11.nc", chunks="auto")
# SCA

# %%
# populating variables used in Parker Norton's function.
baseline_file = conus_baselines_dir / "baseline_SCA_v11.nc"
sca_var = "snow_cover_extent"
ci_var = "sca_clear_index"
# st_date = '2000-01-01' #per publication
# en_date = '2010-12-31' #per publication
remove_ja = True  # This is technically the first filter for removing July and August from the dataset


# %%
def get_dataset(filename, f_vars, start_date, end_date):
    # This routine assumes dimension nhru exists and variable nhm_id exists
    df = xr.open_dataset(filename)
    # NOTE: Next line needed if nhm_id variable exists in netcdf file
    df = df.assign_coords(nhru=df.nhm_id)
    if isinstance(f_vars, list):
        df = df[f_vars].sel(time=slice(start_date, end_date))
    else:
        df = df[[f_vars]].sel(time=slice(start_date, end_date))
    return df


baseline_df = get_dataset(baseline_file, [sca_var, ci_var, "nhru"], sca_start, sca_end)

# Applying first filter to remove selected months, July and August, from the dataset, selects months to keep.
if remove_ja:
    #
    baseline_restr = baseline_df.sel(
        time=baseline_df.time.dt.month.isin([1, 2, 3, 4, 5, 6, 9, 10, 11, 12])
    )
else:
    baseline_restr = baseline_df
baseline_df.close()

# %%
# Create the SCAmask to remove other data meeting criteria below.

# Compute lower and upper SCA values based on confidence interval(used to be called the clear index). Comes from MODIS,
# "fraction of the cell observed in cloud free conditions," here, if cloud cover is less than 30%, then,
# the SCA values is used;
threshold = 70.0
ci_pct = baseline_restr[ci_var].where(baseline_restr[ci_var] >= threshold)
ci_pct /= 100.0

# Mask SCA values where CI is masked; this included daily targets for HRUs when the clear index was greater than 70%
sca_obs = baseline_restr[sca_var].where(~np.isnan(ci_pct))

# Maximum SCA value of those within the threshold...so really "sca_obs_max"
msk_SCAmax = sca_obs.max(axis=0)

# Now count the data sca_obs:
# Number of daily values > 0.0 by HRU
msk_num_obs = (sca_obs > 0.0).sum(axis=0)

# Excluding HRUs that do not have enough values
# Number of years of values by HRU: How many years of annula values that are greater than 0?
msk_num_ann = sca_obs.resample(
    time="1AS"
).mean()  # resamples the df and finds the average value for each year
msk_num_ann = (msk_num_ann > 0).sum(
    axis=0
)  # takes a count of all average annual values greater than 0.

# Create SCA mask based on:
# 1 - Keeps HRUs targets where at least 2 years of data that were the annual average values are greater than 0 (see above),
# 2 - and, where sca_max is greater than 50%,
# 3 - and, where there are least 9 days of values in the total selected period.
SCAmask = (msk_num_ann > 1) & (msk_SCAmax > 0.5) & (msk_num_obs > 9)

# %%
# Lower bound of SCA by HRU
baseline_SCAmin = (ci_pct * sca_obs).where(
    SCAmask
)  # Computes min based upon %SCA of the %area visible.

# %%
# Upper bound of SCA by HRU
baseline_SCAmax = (baseline_SCAmin + (1.0 - ci_pct)).where(
    SCAmask
)  # Computes max based upon % SCA + %area not visible

# %%
SCA_daily = xr.combine_by_coords(
    [
        baseline_SCAmin.to_dataset(name="SCA_min"),
        baseline_SCAmax.to_dataset(name="SCA_max"),
    ]
)
SCA_daily

# %%
c_da = SCA_daily.sel(nhru=nhm_ids)
c_da.to_netcdf(obsdir / f"SCA_daily.nc")

# %%
SCA.close()
SCA_daily.close()

# %% [markdown]
# ### Lets peak at SCA

# %%
# SCA_daily.SCA_max.sel(nhru=99860, time=slice("2002-11-01", "2003-01-30")).plot()
# SCA_daily.SCA_min.sel(nhru=99860, time=slice("2002-11-01", "2003-01-30")).plot()
hru_sel = nhm_ids[3]
c_da.SCA_max.sel(nhru=hru_sel, time=slice("2002-11-01", "2003-01-30")).plot()
c_da.SCA_min.sel(nhru=hru_sel, time=slice("2002-11-01", "2003-01-30")).plot()

# %%
