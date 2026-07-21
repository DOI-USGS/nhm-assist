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

# %%
import sys
import os
import shutil

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
from pestpp_ies_calibration.helpers.pest_utils import (
    pars_to_tpl_entries,
    pars_to_tpl_entries_2,
    write_to_json_tpl,
    check_par_bounds,
)

config = load_subdomain_config(root_dir)

import pyemu
import platform

if "Windows" in platform.system():
    exe_name = "pestpp-ies.exe"
else:
    exe_name = "pestpp-ies"

# %% [markdown]
# # Workspace Setup
# ## Create `pestpp_ies` folder in the model directory
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

# %% [markdown]
# <!-- ## Create PEST instruction file `.ins`
# Map observation name from allobs.dat (created in notebook 01_Create_allobs_dat) to the instruction file `modelobs.dat.ins` -->

# %% [markdown]
# # Create PEST control file object with `pyemu`

# %%
pst = pyemu.Pst.from_io_files(
    tpl_files=[os.path.join(pestpp_model_dir, "parameters.json.tpl")],
    in_files=[
        os.path.join(pestpp_model_dir, "parameters.json")
    ],  # Values for parval1 and bnds will be populated with default values
    ins_files=[os.path.join(pestpp_model_dir, "modelobs.dat.ins")],
    out_files=[
        os.path.join(pestpp_model_dir, "modelobs.dat")
    ],  # names the model output file in the control file (prior_mc.pst)--Chk with Mike
    pst_path=".",
)

# %%

# %% [markdown]
# # Direct editing PEST++ files using pyemu

# %% [markdown]
# ### Set obsval value and ranges
# In PEST++ `pst.observation_data`, the values for obsval are inherited from `modelobs.dat` and are not the "observation" values from allobs.dat, so the values in `pst.observation_data` need to be overwritten with the observation values.

# %% [markdown]
# #### Read in the observation file, `allobs.dat`

# %%
obsvals = pd.read_csv(pestpp_model_dir / "allobs.dat", delim_whitespace=True)
obsvals.set_index("obsname", inplace=True, drop=False)
# obsvals.sample(5)
# print(obsvals)
print(f'The {len(obsvals)} values for "obsval" are the true observation values.')

# %% [markdown]
# Create an observation_data dataframe from the PEST++ control object

# %%
obs = (
    pst.observation_data
)  # This pulls the "observation data" from the pst dataframe and sets it to the "obs" object (dataframe)

# %% [markdown]
# Overwrite 'obsval' with values from observation values from allobs.dat

# %%
obs.loc[obsvals.obsname, "obsval"] = (
    obsvals.obsval.values
)  # Observation value is copied over to obs

# pst_obj.parameter_data = self._update_parameter_data(pst_obj.parameter_data, par_df)
# pst_obj.observation_data = self._update_observation_data(pst_obj.observation_data, obs_df)

# %% [markdown]
# #### Set obsval ranges (not single value) for observations
# PEST++ now allows for ranges to be set for observations. This best replicates the approach in Hay and others (2023).

# %% [markdown]
# Read `allobs_bounds.dat`

# %%
obs_bounds = pd.read_csv(os.path.join(pestpp_model_dir, "allobs_bounds.dat"))
# obs_bounds.rename(columns={"obsname": "obsnme"}, inplace=True)

# %% [markdown]
# Write observation bounds to the observation_data dataframe

# %%
greater_than_dict = dict(
    zip(
        obs_bounds["obsname"],
        obs_bounds["greater_than"],
    )
)
less_than_dict = dict(
    zip(
        obs_bounds["obsname"],
        obs_bounds["less_than"],
    )
)

obs.loc[:, "less_than"] = np.nan
obs.loc[:, "greater_than"] = np.nan

obs.loc[:, "less_than"] = obs.loc[:, "obsnme"].map(less_than_dict)
obs.loc[:, "greater_than"] = obs.loc[:, "obsnme"].map(greater_than_dict)

# %% [markdown]
# ## Create PEST++ **obs**ervation** g**roup **n**a**me**s (**obsgnme**)
# Obervation criteria noted in the obsnme were used to create observation group names.

# %%
obs.obgnme = "obgnme"
print(f"The default value of obgnme is set to {list(set(obs['obgnme']))}.")

# %% [markdown]
# #### Create observation groups for hru observations. No validation groups were made for these targets.

# %%
obs.loc[obs.obsnme.str.startswith("actet_mon"), "obgnme"] = "actet_mon"

obs.loc[obs.obsnme.str.startswith("actet_mean_mon"), "obgnme"] = "actet_mean_mon"

obs.loc[obs.obsnme.str.startswith("recharge_ann"), "obgnme"] = "recharge_ann"

obs.loc[obs.obsnme.str.startswith("soil_moist_mon"), "obgnme"] = "soil_moist_mon"

obs.loc[obs.obsnme.str.startswith("soil_moist_ann"), "obgnme"] = "soil_moist_ann"

obs.loc[obs.obsnme.str.startswith("runoff_mon"), "obgnme"] = "runoff_mon"

obs.loc[obs.obsnme.str.startswith("sca_daily"), "obgnme"] = "sca_daily"

# %% [markdown]
# #### Create observation groups for streamflow observations.

# %%
obs.loc[obs.obsnme.str.startswith("streamflow_daily_1_2"), "obgnme"] = (
    "streamflow_daily_large_ascnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_daily_1_3"), "obgnme"] = (
    "streamflow_daily_large_dscnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_daily_2_2"), "obgnme"] = (
    "streamflow_daily_small_ascnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_daily_2_3"), "obgnme"] = (
    "streamflow_daily_small_dscnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_daily_3_2"), "obgnme"] = (
    "streamflow_daily_pulse_ascnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_daily_3_3"), "obgnme"] = (
    "streamflow_daily_pulse_dscnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_daily_4_1"), "obgnme"] = (
    "streamflow_daily_low"
)
obs.loc[obs.obsnme.str.startswith("streamflow_daily_5_1"), "obgnme"] = (
    "streamflow_daily_ex_low"
)
obs.loc[obs.obsnme.str.startswith("streamflow_mon"), "obgnme"] = "streamflow_mon"

obs.loc[obs.obsnme.str.startswith("streamflow_mean_mon_cal"), "obgnme"] = (
    "streamflow_mean_mon_cal"
)
obs.loc[obs.obsnme.str.startswith("streamflow_mean_mon_val"), "obgnme"] = (
    "streamflow_mean_mon_val"
)

# %% [markdown]
# No streamflow observation group "streamflow_nodata"
#

# %%
obs_group = "streamflow_nodata"
mask_no_flow = (obs["obsnme"].str.startswith("streamflow_")) & (obs["obsval"] == -9999)

print(
    f"{len(obs.loc[mask_no_flow])} observations in {list(set(obs.loc[mask_no_flow, 'obgnme']))} have streamflow values of -9999."
)
obs.loc[mask_no_flow, "obgnme"] = obs_group
print(
    f"{len(obs.loc[obs['obgnme'] == obs_group])} observations were assigned to {obs_group}."
)

# %% [markdown]
# Special group for daily streamflow with missing EFC code/code component

# %%
obs_group = "streamflow_nodata"
mask_efc_error = (
    (obs.obsnme.str.startswith("streamflow_daily"))
    & (obs.obsnme.str.contains("-1"))
    & (obs["obsval"] != -9999)
)

if not obs.loc[mask_efc_error].empty:
    print(
        f"[WARNING]: {len(obs.loc[mask_efc_error])} observations have streamflow values and no EFC classification.",
        f"These observations will be moved to {obs_group} group.",
    )
    obs.loc[mask_efc_error, "obgnme"] = obs_group
else:
    print(
        f"[PASS]: All observations with streamflow values have EFC classification.",
    )

# %% [markdown]
# Correct default EFC for first day of flow
# A small bug is present in the EFC code, where if the first few days of observations are "0" flow, the EFC vale for the first day is "3_2".
# This code block checks for "0" flow values that are not assiged to group "streamflow_daily_ex_low" and reassigns them to that group.

# %%
obs_group = "streamflow_daily_ex_low"
mask = (obs.obsnme.str.startswith("streamflow_daily")) & (obs.obsval == 0)

obgnme_list = list(set(obs.loc[mask, "obgnme"]))

if (len(obgnme_list) == 1) & (obgnme_list[0] == "streamflow_daily_ex_low"):
    print(f"[PASS]: All '0' streamflow observations are in {obs_group}.")
else:
    change_list = [x for x in obgnme_list if x != obs_group]
    chang_mask = (mask) & (obs["obgnme"].isin(change_list))

    print(
        f"[WARNING]: '0' value streamflows were found in {len(chang_mask)} observations in groups {change_list}.",
        f"The obgnme for these observations will be changes to {obs_group}.",
    )

# %% [markdown]
# #### Create validation observation groups for streamflow observations.
# Hay and others (2023) used streamflow observation data during odd water years from 1980 to 2010 to calibrate the model and observations during even water years to validate the model. This section calculates the water year for streamflow_daily and streamflow_monthly observations using the observation name. The streamflow_ann (annual) observations are already in water years if water years were selected in notebook 0_workspace_setup.ipynb.
#
# Note: **streamflow_mean_mon_val** and **streamflow_mean_mon_cal** validation/calibration observations were created in notebook 02_.ipynb.*

# %% [markdown]
# Determine "wateryear" for validation groups

# %%
# "Annual" Annual is in WY or calyear already depending on setting in notebook 0_workspace_setup.ipynb.
# It cannot be changed here. If you want something other than was was set, it must be reset in 0 and rerun all ns.
if config["water_years"] == True:
    print("[PASS]: Streamflow annual observations are water years.")
else:
    print(
        "[FAIL]: Streamflow annual observations are calendar years.",
        "Return to notebook 0_workspace_setup.ipynb, correct the configuration, and rerun notebook 1_create_streamflow_observations.ipynb.",
    )

# Create water year default value for all groups
obs["wateryear"] = -9999

# --- Streamflow Monthly ---
mask_mon = obs.obgnme.str.contains("streamflow_mon") & ~obs.obgnme.str.contains(
    "streamflow_mean"
)

# Convert index strings to datetime
dates_mon = pd.to_datetime(
    obs.loc[mask_mon].index.str.split(":").str[1].str.replace("_", "-", regex=False)
    + "-01",
    errors="coerce",
)
# Apply Water Year logic: Year + 1 if Month >= 10
obs.loc[mask_mon, "wateryear"] = dates_mon.year + (dates_mon.month >= 10).astype(int)

# --- Streamflow Annual ---
mask_ann = obs.obgnme.str.contains("ann")
obs_index_series = pd.Series(obs.loc[mask_ann].index)
obs_index_split = obs_index_series.str.split(":").str[1]
obs.loc[mask_ann, "wateryear"] = obs_index_split.astype(int).values

# --- Streamflow Daily ---
mask_daily = obs.obgnme.str.contains("streamflow_daily")

# Convert index strings to datetime
dates_daily = pd.to_datetime(
    obs.loc[mask_daily].index.str.split(":").str[1].str.replace("_", "-", regex=False),
    errors="coerce",
)
# Apply Water Year logic: Year + 1 if Month >= 10
obs.loc[mask_daily, "wateryear"] = dates_daily.year + (dates_daily.month >= 10).astype(
    int
)

# %%
# # "Annual" Annual is in WY or calyear already depending on setting in notebook 0_workspace_setup.ipynb.
# # It cannot be changed here. If you want something other than was was set, it must be reset in 0 and rerun all ns.
# if config["water_years"] == True:
#     print("[PASS]: Streamflow annual observations are water years.")
# else:
#     print(
#         "[FAIL]: Streamflow annual observations are calendar years.",
#         "Return to notebook 0_workspace_setup.ipynb, correct the configuration, and rerun notebook 1_create_streamflow_observations.ipynb.",
#     )

# # Create water year defualt value for all groups
# obs["wateryear"] = -9999

# # Determine water year value for streamflow_mon observations
# mask_mon = obs.obgnme.str.contains("streamflow_mon") & ~obs.obgnme.str.contains(
#     "streamflow_mean"
# )

# # df['water_year'] = df['date'].dt.year.where(df['date'].dt.month < 10, df['date'].dt.year + 1) (Make this change soon for better accuracy)

# obs.loc[mask_mon, "wateryear"] = (
#     pd.to_datetime(
#         obs.loc[mask_mon].index.str.split(":").str[1].str.replace("_", "-", regex=False)
#         + "-01",
#         errors="coerce",
#     )
#     + pd.DateOffset(30 + 31 + 31)
# ).year

# # Determine water year value for streamflow_ann observations
# mask_ann = obs.obgnme.str.contains("ann")
# obs_index_series = pd.Series(obs.loc[mask_ann].index)  # Convert Index to Series
# obs_index_split = obs_index_series.str.split(":").str[1]  # Extract substring part
# obs.loc[mask_ann, "wateryear"] = obs_index_split.astype(
#     int
# ).values  # Assign as numpy array to avoid index alignment issues

# # Determine water year value for streamflow_daily observations
# mask_daily = obs.obgnme.str.contains("streamflow_daily")
# obs.loc[mask_daily, "wateryear"] = (
#     pd.to_datetime(
#         obs.loc[mask_daily]
#         .index.str.split(":")
#         .str[1]
#         .str.replace("_", "-", regex=False),
#         errors="coerce",
#     )
#     + pd.DateOffset(30 + 31 + 31)
# ).year

# %% [markdown]
# Set time period for model calibration
# The model calibration period for Fienen and others (2025) was truncated to 1999 through 2010. 
# The calibration period can be edited below.

# %%
cal_ts_start = "1999-10-01"  # (Eddie) We should check these dates against the control file dates with at least one year for spin up,
cal_ts_end = "2010-09-30"

# %%
start_water_year = (
    pd.to_datetime(cal_ts_start).year + 1
)  # These are really messy, we need to script this better
end_water_year = pd.to_datetime(cal_ts_end).year
streamflow_water_years = np.array(range(start_water_year, end_water_year + 1))

## We will choose even years as validation
val_water_years = [i for i in streamflow_water_years if i % 2 == 0]
val_water_years

# %% [markdown]
# Append "_val" to observations in validation years data and assign groups to indicate "validation" for these

# %%
val_mask = obs.wateryear.isin(val_water_years) & obs.obsnme.str.startswith("streamflow")
obs.loc[val_mask, "obgnme"] = [f"{i}_val" for i in obs.loc[val_mask].obgnme]

# %%
set(obs.obgnme)

# %%
# obs.loc[obs['obgnme'].str.startswith('streamflow_mean_mon')=='streamflow_nodata']

# %%
# obs.loc[obs.obsnme.str.startswith('streamflow_mean_mon') &
#       (obs.obsnme.str.endswith(exclude_gages[c_model][0]))]

# %%
obs.loc[obs["obgnme"] == "obgnme"]

# %%
obs.loc[(obs.obsval <= 1) & (obs.obgnme.str.startswith("stream"))]

# %%
# obs.loc[obs.obgnme.str.startswith('streamflow')

# %% [markdown]
# ## now we flip these weights back to standard deviation for the noise ensemble and then do not revisit STD, although we will adjust weights to rebalance PHI--Retooled

# %%
# obs.loc[:,'standard_deviation'] = [1/w if w!=0 else 1e-6 for w in obs.weight]

# %% [markdown]
# ## Set SD and bounds for obs from file "Observation_standard_deviation.csv" in Supporting Information folder; if you want to change bounds and SD, change values in the .csv file. Primarily to make sure values during the prior don't go negative.

# %%
obs_sdbnds_path = pestpp_model_dir / "ancillary/Observation_standard_deviation.csv"
obs_sdbnds = pd.read_csv(
    obs_sdbnds_path
)  # Creates a data frame of the bounds for par catagories

# %%
obs_sdbnds.set_index("obsgroup", inplace=True, drop=False)
obs_sdbnds.rename(columns={"obsgroup": "obgnme"}, inplace=True)
obs_sdbnds

# %%
# cleaning up: strip removes the extra spaces and /n etc
obs_sdbnds.index = [i.strip() for i in obs_sdbnds.index]

# %%
obs_sdbnds

# %%
print(obs_sdbnds.index.unique())
print(len(obs_sdbnds.index.unique()))

# %%
obgnme_list = obs_sdbnds["obgnme"]
obgnme_list

# %%
# obs['lower_bound'] = 0
# obs['upper_bound'] = np.nan
obs["standard_deviation"] = np.nan
# obs['weight'] = np.nan
# obs["less_than"] = np.nan
# obs["greater_than"] = np.nan

# %%
obs_sdbnds.columns

# %%
obs.loc[obs.obgnme == "obgnme"]

# %%
for cn, _ in obs.groupby("obgnme"):
    if "streamflow" in cn:
        obs.loc[obs.obgnme == cn, "upper_bound"] = obs_sdbnds.loc[cn, "obsubnd"]
        obs.loc[obs.obgnme == cn, "lower_bound"] = obs_sdbnds.loc[cn, "obslbnd"]
    # print(cn)

# %%
obs.loc[obs.obgnme.str.startswith("streamflow_daily_low")]

# %% [markdown]
# #### Set SD for observations using group noise percent and observation value

# %%
# tt = obs.groupby("obgnme")
for cn, _ in obs.groupby("obgnme"):
    print(cn)

# %%
for cn, _ in obs.groupby("obgnme"):
    print(cn)
    obs_group_percent = obs_sdbnds.loc[cn, "noise_percent"]
    obs.loc[obs.obgnme == cn, "standard_deviation"] = obs_group_percent * (
        obs.loc[obs.obgnme == cn, "obsval"]
    )
# print(cn)

# Replace std value with 9999 where obsval values with "9999"
obs.loc[obs.obsval == -9999, "standard_deviation"] = 9999

# %%
# check for nans: obs.loc[obs.standard_deviation.isnull()]
obs.loc[obs.standard_deviation == np.nan]


# %%
# obs.loc[(obs.obsval == 0) & (obs.obgnme == "streamflow_daily_low")]
# obs.loc[(obs.obsval == 0) & (obs.obgnme == "streamflow_daily_low")]
# obs.loc[obs.obgnme.str.startswith("streamflow_daily_low"), "weight"].max()

# %%
# But, to read in the "other" SD, the SD for the value, not the noise.

# %% [markdown]
# ## Set weight for observations for streamflow using group wt_percent and observation value; for all others using group wt percent

# %%
obs["poi_group"] = obs["obsnme"].str.rsplit(":", n=1).str[-1]

for cn, _ in obs.groupby("obgnme"):

    if cn.startswith("streamflow_"):

        """
        Assign weight value for observatons in the obsevation group name "streamflow_no_data".
        """
        if cn == "streamflow_nodata" or "_val" in cn:
            mask_cn = obs.obgnme == cn
            obs.loc[mask_cn, "weight"] = 0
            obs_remaining = obs.loc[~mask_cn]

            min_val = obs.loc[obs["obgnme"] == cn, "weight"].min()
            max_val = obs.loc[obs["obgnme"] == cn, "weight"].max()
            print(
                f"Observation weights {cn} range {min_val} to {max_val} for n={len(obs.loc[mask_cn])}"
            )

        else:

            """
            Observations in groups (daily, monthly, mean monthly) will have flow values of zero, or non-zero.
            Generally, the weighting is distributed to the observation as:
            1 / ([obs_group_percent--from the .csv lookup] * [observation value])

            However, as seen in the TSJ model, many observations groups have flow values that are very, very small
            given the local hydrology. In this situation, it may be nessessary to strongly govern the weight assignment.
            The "low_bound" variable represents a flow threshold. If flows in any observation group fall below this
            threashold, they will be assigned a weight of the threashold flow value.

            The default value will be the maximum value in the extreemly low flow catagory.

            Give relative wt of each flow obs based on normalized flow magnitude for each gage separately, so that the wts are
            balanced and relative to the frame of each gages flow. Just like how EFC works

            """
            mask_cn = obs.obgnme == cn
            poi_groups = list(set(obs.loc[mask_cn, "poi_group"]))

            for poi_group in poi_groups:
                mask_poi_group = obs.poi_group == poi_group
                mask_cn_and_poi_group = (mask_cn) & (mask_poi_group)
                # (Eddie need to update below to run with new mask for poi_group)

                #### For non-zero flows:
                mask_cn_and_notzero = mask_cn_and_poi_group & (obs["obsval"] != 0)
                obs_group_percent = obs_sdbnds.loc[
                    cn, "wt_percent"
                ]  # "wt_percent" in the table is a fractional value from "Observation_standard_deviation.csv"

                obs.loc[mask_cn_and_notzero, "weight"] = 1 / (
                    obs_group_percent * obs.loc[mask_cn_and_notzero, "obsval"]
                )

                # For zero flows (optional, of user wants to set "0" flows to a diff wt, like "0"
                #               here we set the wt value using the "low_bound" value.
                low_bound = 5
                mask_cn_and_zero = (mask_cn_and_poi_group) & (obs["obsval"] == 0)
                obs.loc[mask_cn_and_zero, "weight"] = 1 / (
                    obs_group_percent * low_bound
                )

                # For flows greater than "0" but less than "low_bound" value)
                mask_cn_zero_and_less_than_low_bound = (
                    (mask_cn_and_poi_group)
                    & (obs["obsval"] >= 0)
                    & (obs["obsval"] < low_bound)
                )
                obs.loc[mask_cn_zero_and_less_than_low_bound, "weight"] = 1 / (
                    obs_group_percent * low_bound
                )

                min_val = obs.loc[mask_cn_and_poi_group, "weight"].min()
                max_val = obs.loc[mask_cn_and_poi_group, "weight"].max()
                print(
                    f"Observation weights {cn, poi_group} range {min_val} to {max_val} for n={len(obs.loc[mask_cn_and_poi_group])}"
                )

    else:  # For all other groups that are not streamflow (do these even matter here b/c of inequality calibration:
        obs_group_percent = obs_sdbnds.loc[cn, "wt_percent"]
        mask_cn = (obs.obgnme == cn) & (obs["obsval"] >= 0)
        obs.loc[mask_cn, "weight"] = 1 / obs_group_percent

        min_val = obs.loc[mask_cn, "weight"].min()
        max_val = obs.loc[mask_cn, "weight"].max()
        print(
            f"Observation weights {cn} range {min_val} to {max_val}for n={len(obs.loc[mask_cn])}"
        )

print(
    "Note: Monthly streamflow obs are still being weighted here based upon streamflow rules."
)

# %% [markdown]
# Assign "0" weights to streamflow observations for validation years

# %%
# # unweight the validation data and assign groups to indicate "validation" for these
# obs.loc[
#     (obs.wateryear.isin(val_water_years) & (obs.obgnme.str.startswith("streamflow"))),
#     "weight",
# ] = 0

# obs.loc[
#     (obs.wateryear.isin(val_water_years) & (obs.obgnme.str.startswith("streamflow"))),
#     "obgnme",
# ] = [
#     f"{i}_val"
#     for i in obs.loc[
#         (
#             obs.wateryear.isin(val_water_years)
#             & (obs.obgnme.str.startswith("streamflow"))
#         )
#     ].obgnme
# ]

# %% [markdown]
# #### Check weights for errors

# %%
if not obs.loc[obs.weight < 0].empty:
    print("[Warning]: Observations have negative weight values.")
    print(obs.loc[obs.weight < 0])
else:
    print("[PASS]: Observations have no negative weight values.")


if not obs.loc[obs.weight == np.nan].empty:
    print("[Warning]: Observations have NaN weight values.")
    print(obs.loc[obs.weight == np.nan])
else:
    print("[PASS]: Observations have no NaN weight values.")

if not obs.loc[obs.weight == np.inf].empty:
    print("[Warning]: Observations have np.inf weight values.")
    print(obs.loc[obs.weight == np.inf])
else:
    print("[PASS]: Observations have no np.inf weight values.")

# obs.loc[obs.weight.isnull()]
# obs.loc[obs.weight.isna()]
# obs.loc[obs.obgnme.str.startswith("streamflow_mon"), "weight"].min()

# %%
obs.weight.sample(50)

# %%
obs.loc[obs.obgnme.str.endswith("_val"), "weight"] = 0

# %%
for cn, _ in obs.groupby("obgnme"):

    if cn.startswith("streamflow_"):
        """
        Assign weight value for observatons in the obsevation group name "streamflow_no_data".
        """
        if cn == "streamflow_nodata":
            min_val = obs.loc[obs["obgnme"] == cn, "weight"].min()
            max_val = obs.loc[obs["obgnme"] == cn, "weight"].max()
            print(
                f"Observation weights {cn} range {min_val} to {max_val} for n={len(obs.loc[obs['obgnme'] == cn])}"
            )

        else:

            mask_cn_and_notzero = (obs.obgnme == cn) & (obs["obsval"] != 0)

            min_val = obs.loc[obs["obgnme"] == cn, "weight"].min()
            max_val = obs.loc[obs["obgnme"] == cn, "weight"].max()
            print(
                f"Observation weights {cn} range {min_val} to {max_val} for n={len(obs.loc[obs['obgnme'] == cn])}"
            )

    else:  # For all other groups that are not streamflow (do these even matter here b/c of inequality calibration:

        mask_cn = (obs.obgnme == cn) & (obs["obsval"] >= 0)

        min_val = obs.loc[mask_cn, "weight"].min()
        max_val = obs.loc[mask_cn, "weight"].max()
        print(
            f"Observation weights {cn} range {min_val} to {max_val}for n={len(obs.loc[mask_cn])}"
        )

print(
    "Note: Monthly streamflow obs are still being weighted here based upon streamflow rules."
)

# %% [markdown]
# ### Direct Editing of Params

# %%
par_starting_vals = pd.read_csv(
    pestpp_model_dir / "starting_par_vals.dat", index_col="parname", sep=" "
)

# %%
par_starting_vals

# %% [markdown]
# ### Copy parval1, upper bound and lower bound from "par_starting_vals" to pars.parval1 

# %%
pars = pst.parameter_data

# %%
# Alternative to below: Test; both pars and par_starting_vals must have the same index "parnme".

pars[["parval1", "parubnd", "parlbnd"]] = par_starting_vals[
    ["parval1", "parubnd", "parlbnd"]
].values

# # The old way
# for idx, row in pars.iterrows():
#     pars.loc[pars.parnme, "parval1"] = par_starting_vals.loc[pars.parnme, "parval1"]
#     pars.loc[pars.parnme, "parubnd"] = par_starting_vals.loc[pars.parnme, "parubnd"]
#     pars.loc[pars.parnme, "parlbnd"] = par_starting_vals.loc[pars.parnme, "parlbnd"]

# %%
pars.sample(50)

# %% [markdown]
# ### we can't log transform negative parameter values

# %%
pars.loc[pars.parlbnd <= 0, "partrans"] = "none"

# %% [markdown]
# ### and set the consolidated forward_run.py file to the pst object

# %%
pst.model_command = ["python forward_run.py"]

# %%
pst.control_data.noptmax = 0  # or -1 later, 0 at first

# %% [markdown]
# ### set some PEST++ specific parmeters

# %%
pst.pestpp_options["ies_num_reals"] = 500

pst.pestpp_options["ies_bad_phi_sigma"] = 2.5
pst.pestpp_options["overdue_giveup_fac"] = 4
pst.pestpp_options["ies_no_noise"] = False
pst.pestpp_options["ies_drop_conflicts"] = False
pst.pestpp_options["ies_pdc_sigma_distance"] = 3.0
pst.pestpp_options["ies_autoadaloc"] = False
pst.pestpp_options["ies_num_threads"] = 4
pst.pestpp_options["ies_lambda_mults"] = (0.1, 1.0, 10.0, 100.0)
pst.pestpp_options["lambda_scale_fac"] = (0.75, 0.9, 1.0, 1.1)
pst.pestpp_options["ies_subset_size"] = 20

# set SVD for some regularization
pst.svd_data.maxsing = 250

# %%
assert len(pst.observation_data.loc[pst.observation_data.weight == 0]) > 0

# %%
pst.parameter_data = pst.parameter_data[
    [
        "parnme",
        "partrans",
        "parchglim",
        "parval1",
        "parlbnd",
        "parubnd",
        "pargp",
        "scale",
        "offset",
        "dercom",
    ]
]

# %% [markdown]
# ### special case for just this one value with busted bounds 

# %%
# pst.parameter_data.loc['smidx_exp:hru_84017']
len(obs)

# %%
# if "smidx_exp:hru_84017" in pst.parameter_data.index:
#     pst.parameter_data.loc["smidx_exp:hru_84017", "parval1"] = 0.003
#     pst.parameter_data.loc["smidx_exp:hru_84017", "parubnd"] = 0.003 * 2


# %%
# pst.write(os.path.join(pestpp_model_dir, "prior_mc.pst"), version=2)

# %%
obs.weight.isnull().values.any()

# %%
len(pst.observation_data), len(pst.observation_data.dropna())

# %%
pst.observation_data.loc[
    list(set(pst.observation_data.index) - set(pst.observation_data.dropna().index))
]

# %%
pst.observation_data.loc[
    (pst.observation_data.obgnme == "streamflow_daily_ex_low")
    & (pst.observation_data.obsval == 0)
]

# %%
# pst.observation_data.loc[
#     (pst.observation_data.obsnme == "streamflow_daily_3_2:2000_7_11:05431022")
# ]  # &
# # (pst.observation_data.weight>0)]

# %%
# # set all obs with less_than == greater_than columns to have nan values for those columns
# zpars = pst.observation_data.loc[
#     pst.observation_data.less_than == pst.observation_data.greater_than
# ].copy()
# pst.observation_data.loc[zpars.index, "greater_than"] = np.nan
# pst.observation_data.loc[zpars.index, "less_than"] = np.nan

# %%
# make sure sca is zero-weighted
pst.observation_data.loc[pst.observation_data.obgnme == "sca_daily", "weight"] = 0

# %%
pst.write(os.path.join(pestpp_model_dir, "prior_mc.pst"), version=2)

# %% [markdown]
# ## now run with noptmax=0

# %%
pestpp_model_dir

# %%
# # check that pestpp executable exists and run. otherwise, get the exe
# if os.path.exists(os.path.join(pestpp_dir,exe_name)):
#     pyemu.os_utils.run('pestpp-ies prior_mc.pst',cwd=pestpp_dir)
# else:
#     pyemu.utils.get_pestpp(pestpp_dir)
#     pyemu.os_utils.run('pestpp-ies prior_mc.pst',cwd=pestpp_dir)

# %%
exe_name

# %%
# check that pestpp executable exists and run. otherwise, get the exe
if not pl.Path(pestpp_model_dir / exe_name).exists():
    print(".exe missing")
    pyemu.utils.get_pestpp(str(pestpp_model_dir))
    pyemu.os_utils.run("pestpp-ies prior_mc.pst", cwd=str(pestpp_model_dir))
else:
    print(".exe found")
    pyemu.os_utils.run("pestpp-ies prior_mc.pst", cwd=str(pestpp_model_dir))

# %%

# %%

# %%

# %%
