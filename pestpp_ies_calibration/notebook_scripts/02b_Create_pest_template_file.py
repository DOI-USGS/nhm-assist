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
# # Read NHM subbasin model parameter file `.param`
# The following cell reads the parameter file, `.param`, and convert to a Json-style file, `parameters.json` and reads `parameters.json`. Values in this parameter file are used to set "starting values" for the pestpp-ies calibration.

# %%
param_file = config["model_dir"] / "myparam.param"
parameters_json_file = pestpp_dir / "parameters.json"

pardat = pws.parameters.PrmsParameters.load(param_file)
pardat.parameters_to_json(parameters_json_file)
pardat = pws.parameters.PrmsParameters.load_from_json(parameters_json_file)


# %% [markdown]
# ### List parameters in the parameter file `.param`

# %%
pars = pardat.parameters
dims = pardat.dimensions
con.print(pars.keys())
# con.print(dims)

# # Other
# pars["nhm_id"] #View values of one parameter
# [i for i in pars.keys() if "tmax" in i]# View list of parameters with "tmax" in parameter key.
# hrus = list(pars["nhm_id"])  # Make a list of hru id's from "pars"
# segs = list(pars["nhm_seg"])  # Make a list of segment id's from "pars"

# %% [markdown]
# ### List parameters needed to run NHM subbasin model using pyWatershed

# %%
nhm_processes = [
    pws.PRMSSolarGeometry,
    pws.PRMSAtmosphere,
    pws.PRMSCanopy,
    pws.PRMSSnow,
    pws.PRMSRunoff,
    pws.PRMSSoilzone,
    pws.PRMSGroundwater,
    pws.PRMSChannel,
]

pw_params = []
for proc in nhm_processes:
    pw_params += proc.get_parameters()

# %% [markdown]
# ### Parameter file check

# %%
missing_params = set(list(pw_params)) - set(list(pw_params))
extra_params = set(list(pw_params)) - set(list(pw_params))

if missing_params:
    con.print(
        f"The following parameters are missing and needed in the parameter file to run pywatershed: {missing_params}"
    )
else:
    con.print("Parameter file contains all the needed parameters to run pywatershed.")

if extra_params:
    con.print(
        f"The following parameters are NOT needed in the parameter file to run pywatershed: {extra_params}"
    )

# %% [markdown]
# # Create a PEST template file
# The template file, `parameters.json.tpl` is a json-style version of `myparam.param` with paramterter starting values. In this section, a dataframe of starting parameter values and parameter bounds is created, `par_starting_vals`, and used to write the template file. 

# %% [markdown]
# Create `par_starting_vals` dataframe
# This dataframe has **PEST++ specified column names**: **parname** (parameter name), **parval1** (starting value), **parubnd** (upper bound value), **parlbnd** (lower bound value).

# %%
par_starting_vals = pd.DataFrame(columns=["parname", "parval1", "parubnd", "parlbnd"])
# par_starting_vals

# %% [markdown]
# ### Make a list of parameters for PEST++ to calibrate.
# Commonly calibrated parameter sets may be found in published PRMS models. In this approach we have selected paramteters used in the calibration of the National Hydrologic Model version 1.1

# %% jupyter={"source_hidden": true}
cal_par_list = [
    "adjmix_rain",
    "carea_max",
    "cecn_coef",
    "emis_noppt",
    "fastcoef_lin",
    "freeh2o_cap",
    "gwflow_coef",
    "jh_coef",
    "mann_n",
    "potet_sublim",
    "rad_trncf",
    "radmax",
    "rain_cbh_adj",
    "slowcoef_sq",
    "smidx_coef",
    "smidx_exp",
    "snarea_thresh",
    "snowinfil_max",
    "snow_cbh_adj",
    "soil2gw_max",
    "soil_moist_max",
    "soil_rechr_max_frac",
    "ssr2gw_exp",
    "ssr2gw_rate",
    "tmax_allsnow",
    "tmax_cbh_adj",
    "tmin_cbh_adj",
]

# %% [markdown]
# Notes
# These "were" calibrated back in the day:
# dprst_depth_avg (use prms default range),
# dprst_flow_coef,
# dprst_seep_rate_open,
# op_flow_thres,
# sro_to_dprst_imperv,
# sro_to_dprst_perv,
# va_open_exp,
#
#
# Ones we are adding:
# dprst_frac -- For WI we decided to set at 0.1 and let vary from 0.8 to 1.2,
# dprst_et_coef -- range 0.5 to 1.5, default of 1.0,
# dprst_frac_open,
# dprst_seep_rate_clos,

# %% [markdown]
# ### Stage starting parameter values in `par_starting_vals`
# Using the function pars_to_tpl_entries(), write parameter values that PEST++ will be calibrating from the parameter file, `myparam.param`, to `par_starting_vals`

# %%
par_starting_vals = pd.DataFrame(columns=["parname", "parval1", "parubnd", "parlbnd"])

par_starting_vals = pars_to_tpl_entries_2(
    pars,
    cal_par_list,
    par_starting_vals,
)

par_starting_vals.set_index("parname", inplace=True, drop=False)
par_starting_vals

# xx = par_starting_vals.loc[par_starting_vals.parname.str.startswith("carea_max"), :]
# xx

# %% [markdown]
# ### Stage parameter bounds in `par_starting_vals`
# The NHM used three methods to set parameter bounds:
# 1) "not used", paramter values were unbound and able to move in the full prms parmeter value range.
# 2) "range", parameter values were bounded using ranges in table 1 (Hay and others, 2023). Matt will make table to insert here.
# 3) "percent" parameter values were bounded using a range of +/- 20% of the starting parameter value.

# %% [markdown]
# #### Read parameter bounds
# Paramter bounds from Hay and others (2023) are listed in `par_cal_bounds_use.csv` in the ancillary directory,

# %%
bnds_file = "par_cal_bounds_use.csv"
bnds_path = pestpp_model_dir / "ancillary" / bnds_file
bnds = pd.read_csv(bnds_path)  # Creates a data frame of the bounds for par catagories
bnds.set_index("parameter_name", inplace=True, drop=False)

# %% [markdown]
# #### Verify all parmeters have bounds

# %%
check_par_bounds(par_starting_vals, bnds, bnds_path=bnds_file)

# %% [markdown]
# #### Set bounds for parameters

# %% [markdown]
# Create the lists (pd.series) of parameters for the calibration methods

# %%
percent_list = bnds.loc[bnds.HRU_cal_method == "Percent", "parameter_name"].reset_index(
    drop=True
)
range_list = bnds.loc[bnds.HRU_cal_method == "Range", "parameter_name"]

not_used_list = bnds.loc[bnds.HRU_cal_method == "Not used", "parameter_name"]

# %% [markdown]
# Assign bounds for percent method parameters 

# %%
for cp in percent_list:
    cpars = par_starting_vals.loc[par_starting_vals.parname.str.startswith(cp)][
        "parname"
    ]
    par_starting_vals.loc[cpars, "parubnd"] = (
        par_starting_vals.loc[cpars]["parval1"] * 1.2
    )
    par_starting_vals.loc[cpars, "parlbnd"] = (
        par_starting_vals.loc[cpars]["parval1"] * 0.8
    )

# %% [markdown]
# Assign bounds for range parameters 

# %%
for cp in range_list:
    cpars = par_starting_vals.loc[par_starting_vals.parname.str.startswith(cp)][
        "parname"
    ]
    par_starting_vals.loc[cpars, "parubnd"] = bnds.loc[cp]["par_upper_bound"]
    par_starting_vals.loc[cpars, "parlbnd"] = bnds.loc[cp]["par_lower_bound"]


# %% [markdown]
# Review `par_starting_vals`

# %%
par_starting_vals

# %% [markdown]
# ### Write pestpp-ies template file `parameters.json.tpl`

# %%
# pars = pardat.parameters
# dims = pardat.dimensions
# pars_2 = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in pars.items()}

# %%

# %%
write_to_json_tpl(dims, pars, pestpp_model_dir / "parameters.json.tpl")
par_starting_vals.to_csv(
    pestpp_model_dir / "starting_par_vals.dat", index=None, sep=" "
)

# %% [markdown]
# <!-- ## Create PEST instruction file `.ins`
# Map observation name from allobs.dat (created in notebook 01_Create_allobs_dat) to the instruction file `modelobs.dat.ins` -->
