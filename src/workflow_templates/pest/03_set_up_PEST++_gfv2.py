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
from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config


config = load_subdomain_config(root_dir)


import pandas as pd
import xarray as xr
import numpy as np
import shutil

from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

from dotenv import load_dotenv

# Use home directory for Nebari, otherwise use repo root_dir
if "NEBARI_CONDA_STORE_SERVER_SERVICE_HOST" in os.environ:
    dotenv_path = pl.Path.home() / ".env"
else:
    dotenv_path = root_dir / ".env"

load_dotenv(dotenv_path=dotenv_path)

############################################

config = load_subdomain_config(root_dir)

from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config
from assist.nhf import efc

from assist.pest.pest_utils import (
    pars_to_tpl_entries,
    pars_to_tpl_entries_2,
    write_to_json_tpl,
    check_par_bounds,
)


sys.path.insert(0, r"D:\nhm-assist\pestpp_ies_calibration\dependencies")
import pyemu
import platform

if "Windows" in platform.system():
    exe_name = "pestpp-ies.exe"
else:
    exe_name = "pestpp-ies"

# %% [markdown]
# ## Workspace Setup
# Create the `pestpp_ies/` directory structure and copy ancillary configuration
# files and model input files needed for PEST++ IES runs.

# %%
if not (config["model_dir"] / "pestpp_ies").exists():
    (config["model_dir"] / "pestpp_ies").mkdir()
pestpp_model_dir = config["model_dir"] / "pestpp_ies"
pestpp_dir = pl.Path("../").resolve()

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
# # Set Up the PEST++ Control File
#
# This notebook assembles the PEST++ control file (`prior_mc.pst`) which defines
# the complete parameter estimation problem: parameters, observations, weights,
# bounds, and algorithmic settings for PEST++ IES.
#
# **Output file:**
# - `prior_mc.pst` — The PEST++ control file that ties together the template file,
#   instruction file, forward run script, observation values/weights, and parameter
#   values/bounds into a single configuration.
#
# **Workflow steps:**
# 1. Create the PST object from template (`.tpl`) and instruction (`.ins`) files using `pyemu`.
# 2. Populate observation values from `allobs.dat` and set observation bounds from `allobs_bounds.dat`.
# 3. Assign observation group names (`obgnme`) based on variable type and EFC classification.
# 4. Split streamflow observations into parameter estimation and validation sets by water year.
# 5. Set observation weights and standard deviations from the ancillary configuration file.
# 6. Populate parameter starting values and bounds from `starting_par_vals.dat`.
# 7. Configure PEST++ IES algorithmic options (ensemble size, lambda, localization, etc.).
# 8. Write the control file and run an initial `noptmax=0` check.

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
# ## Direct Editing of the PEST++ Control Object
# The following sections modify the PST object in memory before writing the
# final control file.

# %% [markdown]
# ### Set observation values and bounds
# The `obsval` column in `pst.observation_data` is initially populated from
# `modelobs.dat` (model output). We overwrite it with the true observation values
# from `allobs.dat`.

# %% [markdown]
# #### Read `allobs.dat`

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
# #### Set observation bounds (inequality constraints)
# PEST++ supports range-based observations where the target is a band rather than
# a single value. This replicates the approach in Hay and others (2023).

# %% [markdown]
# Read `allobs_bounds.dat`

# %%
# obs_bounds = pd.read_csv(os.path.join(pestpp_model_dir, "allobs_bounds.dat"))
# # obs_bounds.rename(columns={"obsname": "obsnme"}, inplace=True)

# %% [markdown]
# Write observation bounds to the observation_data dataframe

# %%
# greater_than_dict = dict(
#     zip(
#         obs_bounds["obsname"],
#         obs_bounds["greater_than"],
#     )
# )
# less_than_dict = dict(
#     zip(
#         obs_bounds["obsname"],
#         obs_bounds["less_than"],
#     )
# )

# obs.loc[:, "less_than"] = np.nan
# obs.loc[:, "greater_than"] = np.nan

# obs.loc[:, "less_than"] = obs.loc[:, "obsnme"].map(less_than_dict)
# obs.loc[:, "greater_than"] = obs.loc[:, "obsnme"].map(greater_than_dict)

# %% [markdown]
# ## Assign Observation Group Names (`obgnme`)
# Observation groups control how PEST++ aggregates phi (objective function)
# contributions. Groups are assigned based on variable type, temporal resolution,
# and EFC flow classification.

# %%
obs.obgnme = "obgnme"
print(f"The default value of obgnme is set to {list(set(obs['obgnme']))}.")

# %% [markdown]
# #### HRU observation groups (no validation split for these targets)

# %%
obs.loc[obs.obsnme.str.startswith("actet_mon"), "obgnme"] = "actet_mon"

obs.loc[obs.obsnme.str.startswith("actet_mean_mon"), "obgnme"] = "actet_mean_mon"

obs.loc[obs.obsnme.str.startswith("recharge_ann"), "obgnme"] = "recharge_ann"

obs.loc[obs.obsnme.str.startswith("soil_moist_mon"), "obgnme"] = "soil_moist_mon"

obs.loc[obs.obsnme.str.startswith("soil_moist_ann"), "obgnme"] = "soil_moist_ann"

obs.loc[obs.obsnme.str.startswith("runoff_mon"), "obgnme"] = "runoff_mon"

obs.loc[obs.obsnme.str.startswith("swe_monthly"), "obgnme"] = "sca_daily"

# %% [markdown]
# #### Streamflow observation groups (by EFC classification and hydrograph position)
# EFC codes: 1=Large flood, 2=Small flood, 3=High flow pulse, 4=Low flow, 5=Extreme low flow.
# Hydrograph position: 1=Low flow, 2=Ascending limb, 3=Descending limb.

# %%
obs.loc[obs.obsnme.str.startswith("streamflow_5day_1_2"), "obgnme"] = (
    "streamflow_daily_large_ascnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_5day_1_3"), "obgnme"] = (
    "streamflow_daily_large_dscnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_5day_2_2"), "obgnme"] = (
    "streamflow_daily_small_ascnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_5day_2_3"), "obgnme"] = (
    "streamflow_daily_small_dscnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_5day_3_2"), "obgnme"] = (
    "streamflow_daily_pulse_ascnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_5day_3_3"), "obgnme"] = (
    "streamflow_daily_pulse_dscnd"
)
obs.loc[obs.obsnme.str.startswith("streamflow_5day_4_1"), "obgnme"] = (
    "streamflow_daily_low"
)
obs.loc[obs.obsnme.str.startswith("streamflow_5day_5_1"), "obgnme"] = (
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
# #### Handle no-data streamflow observations
# Observations with -9999 (no data) are moved to the `streamflow_nodata` group
# and will be zero-weighted.

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
# #### Handle missing EFC classifications
# Observations with valid streamflow but missing EFC codes (-1) are moved to
# the no-data group to avoid contaminating EFC-based groups.

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
# #### Fix EFC assignment for zero-flow days
# The EFC algorithm may incorrectly assign the first zero-flow day to a non-low-flow
# group. Any observation with discharge = 0 should be in `streamflow_daily_ex_low`.

# %%
obs_group = "streamflow_daily_ex_low"
mask = (obs.obsnme.str.startswith("streamflow_daily")) & (obs.obsval == 0)

obgnme_list = list(set(obs.loc[mask, "obgnme"]))

if len(obgnme_list) == 0:
    print(f"[PASS]: No '0' streamflow observations found — nothing to reassign.")
elif len(obgnme_list) == 1 and obgnme_list[0] == "streamflow_daily_ex_low":
    print(f"[PASS]: All '0' streamflow observations are in {obs_group}.")
else:
    change_list = [x for x in obgnme_list if x != obs_group]
    chang_mask = (mask) & (obs["obgnme"].isin(change_list))

    print(
        f"[WARNING]: '0' value streamflows were found in {len(chang_mask)} observations in groups {change_list}.",
        f"The obgnme for these observations will be changes to {obs_group}.",
    )

# %%
obgnme_list

# %% [markdown]
# #### Split streamflow into parameter estimation and validation sets
# Following Hay and others (2023), odd water years are used for parameter estimation
# and even water years for validation. Validation observations receive `_val` suffix
# on their group name and are zero-weighted.
#
# Note: `streamflow_mean_mon_val` and `streamflow_mean_mon_cal` groups were already
# created in notebook 01.

# %% [markdown]
# #### Determine water year for each observation

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
# #### Define the parameter estimation period
# The parameter estimation period for Fienen and others (2025) was 1999-2010.
# Edit the start/end dates below to adjust.

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
# #### Assign validation group suffix to even water year observations

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
# ## Set Standard Deviations for Observation Noise Ensemble
# Standard deviations define the noise added to observations when generating the
# observation noise ensemble. Values are computed as a fraction of the observation
# value, with the fraction specified per group in `Observation_standard_deviation.csv`.

# %%
# obs.loc[:,'standard_deviation'] = [1/w if w!=0 else 1e-6 for w in obs.weight]

# %% [markdown]
# ## Read Observation SD and Bounds Configuration
# Standard deviations and weight percentages are defined per observation group in
# `Observation_standard_deviation.csv`. Edit that file to change noise/weight behavior.

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
# #### Compute standard deviation per observation

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
# ## Set Observation Weights
# Weights control the relative influence of each observation on the objective function.
# Streamflow weights are inversely proportional to flow magnitude (per gage), while
# HRU observations use a flat group-level weight. Validation observations and
# no-data observations receive zero weight.

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
# #### Zero-weight validation observations

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
# #### Validate weights (check for negatives, NaN, inf)

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
# ### Populate Parameter Values and Bounds
# Copy starting values and bounds from `starting_par_vals.dat` into the PST object.

# %%
par_starting_vals = pd.read_csv(
    pestpp_model_dir / "starting_par_vals.dat", index_col="parname", sep=" "
)

# %%
par_starting_vals

# %% [markdown]
# #### Transfer parval1, parubnd, parlbnd to PST parameter_data

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
# #### Disable log-transformation for parameters with non-positive lower bounds

# %%
pars.loc[pars.parlbnd <= 0, "partrans"] = "none"

# %% [markdown]
# #### Set the forward model command

# %%
pst.model_command = ["python forward_run.py"]

# %%
pst.control_data.noptmax = 0  # or -1 later, 0 at first

# %% [markdown]
# ### Configure PEST++ IES Options
# Key algorithmic settings for the iterative ensemble smoother.

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
# ### Special case: fix individual parameter bounds if needed

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
# ## Write the Control File and Run Initial Check (`noptmax=0`)
# Writing with `noptmax=0` runs a single forward model evaluation to verify that
# all files are consistent before launching the full ensemble run.

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

    # First, look for a local pestpp distribution in data_dependencies
    dep_dir = pestpp_dir / "data_dependencies"
    local_pestpp_dirs = sorted(dep_dir.glob("pestpp-*-win"))

    if local_pestpp_dirs:
        # Use the most recent local distribution
        local_bin = local_pestpp_dirs[-1] / "bin"
        print(f"  Found local PEST++ distribution: {local_pestpp_dirs[-1].name}")
        import shutil

        for exe_file in local_bin.glob("*.exe"):
            shutil.copy2(exe_file, pestpp_model_dir / exe_file.name)
            print(f"    Copied {exe_file.name}")
    else:
        # No local distribution found — download via pyemu
        print("  No local PEST++ distribution found, downloading via pyemu...")
        pyemu.utils.get_pestpp(str(pestpp_model_dir))

    pyemu.os_utils.run("pestpp-ies prior_mc.pst", cwd=str(pestpp_model_dir))
else:
    print(".exe found")
    pyemu.os_utils.run("pestpp-ies prior_mc.pst", cwd=str(pestpp_model_dir))

# %%
