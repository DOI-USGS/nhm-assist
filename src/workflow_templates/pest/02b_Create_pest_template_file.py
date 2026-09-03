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
import pathlib as pl
import warnings

warnings.filterwarnings("ignore")
from rich.console import Console

con = Console()
from rich import pretty

pretty.install()
import jupyter_black

jupyter_black.load()

import pandas as pd
import shutil
import pywatershed as pws
import xarray as xr
import numpy as np
import datetime

# import pathlib as pl
# from pyPRMS.metadata.metadata import MetaData
# from pyPRMS import ParameterFile
from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

# Find and set the "nhm-assist" root directory
# Find the repo root via pixi's PIXI_PROJECT_ROOT (set by any `pixi run`), with a
# fallback to the package location — works for editable and non-editable installs.
from assist.workspace.bridge import resolve_repo_root

root_dir = resolve_repo_root()

from assist.workspace.bridge import resolve_project_notebook_context
from assist.workspace.service import get_active_model_root

project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
if project_context:
    active_model_root = get_active_model_root(
        project_context["workspace_root"], project_context["project_root"].name
    )
    config_root = active_model_root / "config"
else:
    config_root = root_dir

from dotenv import load_dotenv

# Use home directory for Nebari, otherwise use repo root_dir
if "NEBARI_CONDA_STORE_SERVER_SERVICE_HOST" in os.environ:
    dotenv_path = pl.Path.home() / ".env"
else:
    dotenv_path = root_dir / ".env"

load_dotenv(dotenv_path=dotenv_path)

###################################################


from assist.nhm.nhm_assist_utilities import load_subdomain_config
from assist.nhm import efc

from assist.pest.pest_utils import (
    pars_to_tpl_entries,
    pars_to_tpl_entries_2,
    write_to_json_tpl,
    check_par_bounds,
)

config = load_subdomain_config(root_dir)

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
# # Create PEST++ Template File
#
# This notebook creates the PEST++ template file (`parameters.json.tpl`) that defines
# which model parameters PEST++ IES will adjust during parameter estimation, along with
# their starting values and bounds.
#
# **Output files:**
# - `parameters.json.tpl` — The PEST++ template file. A JSON-formatted parameter file
#   where adjustable parameter values are replaced with PEST++ placeholder tokens.
# - `starting_par_vals.dat` — A table of parameter names, starting values, and
#   upper/lower bounds in PEST++ format.
#
# **How PEST++ uses the template file:**
# Before each forward model run, PEST++ reads the template file, substitutes the
# placeholder tokens with parameter values from the current realization, and writes
# the filled `parameters.json` that `forward_run.py` uses to run pywatershed.
#
# **Workflow steps:**
# 1. Load the PRMS parameter file and export to JSON format.
# 2. Identify which parameters PEST++ will estimate (the "adjustable" parameter list).
# 3. Set starting values from the current parameter file.
# 4. Assign parameter bounds using one of three methods (percent, range, or unbounded).
# 5. Write the template file and starting parameter values table.

# %% [markdown]
# ## Read the NHM Parameter File
# Load `myparam.param`, convert to JSON format (`parameters.json`), and reload.
# The JSON format is what `forward_run.py` reads during PEST++ runs.

# %%
param_file = config["model_dir"] / "myparam.param"
parameters_json_file = pestpp_dir / "parameters.json"

pardat = pws.parameters.PrmsParameters.load(param_file)
pardat.parameters_to_json(parameters_json_file)
pardat = pws.parameters.PrmsParameters.load_from_json(parameters_json_file)


# %% [markdown]
# ### List parameters in the parameter file

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
# ### List parameters required by pywatershed
# These are all parameters needed across the eight PRMS process modules. Any
# parameter in this list that is also in the adjustable list will be estimated.

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
# ### Parameter file completeness check
# Verify the parameter file contains all parameters required by pywatershed.

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
# ## Build the Template File
# The template file `parameters.json.tpl` is a JSON-formatted version of the parameter
# file where adjustable parameter values are replaced with PEST++ placeholder tokens.
# This section builds the `par_starting_vals` dataframe that defines parameter names,
# starting values, and bounds for the template.

# %% [markdown]
# ### Initialize `par_starting_vals`
# This dataframe uses PEST++ column conventions: `parname` (parameter name),
# `parval1` (starting value), `parubnd` (upper bound), `parlbnd` (lower bound).

# %%
par_starting_vals = pd.DataFrame(columns=["parname", "parval1", "parubnd", "parlbnd"])
# par_starting_vals

# %% [markdown]
# ### Define adjustable parameters
# These parameters will be estimated by PEST++ IES. The list follows the parameter
# set used in the NHM v1.1 parameter estimation (Hay and others, 2023).

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
# ### Additional parameters under consideration
# These parameters were historically estimated or are candidates for future inclusion:
# - Depression storage: `dprst_depth_avg`, `dprst_flow_coef`, `dprst_seep_rate_open`,
#   `op_flow_thres`, `sro_to_dprst_imperv`, `sro_to_dprst_perv`, `va_open_exp`
# - New additions: `dprst_frac` (set at 0.1, vary 0.8-1.2), `dprst_et_coef` (range 0.5-1.5),
#   `dprst_frac_open`, `dprst_seep_rate_clos`

# %% [markdown]
# ### Populate starting values from the parameter file
# Extract current parameter values from `myparam.param` for each adjustable parameter
# and write them to `par_starting_vals`.

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
# ### Assign parameter bounds
# The NHM v1.1 used three methods to define parameter bounds:
# 1. **Percent** — bounds are +/- 20% of the starting parameter value.
# 2. **Range** — bounds are fixed values from published ranges (Hay and others, 2023).
# 3. **Not used** — parameter is unbounded (full PRMS valid range).
#
# Bounds are read from `par_cal_bounds_use.csv` in the ancillary directory.

# %% [markdown]
# #### Read parameter bounds from ancillary file

# %%
bnds_file = "par_cal_bounds_use.csv"
bnds_path = pestpp_model_dir / "ancillary" / bnds_file
bnds = pd.read_csv(bnds_path)  # Creates a data frame of the bounds for par catagories
bnds.set_index("parameter_name", inplace=True, drop=False)

# %% [markdown]
# #### Verify all adjustable parameters have defined bounds

# %%
check_par_bounds(par_starting_vals, bnds, bnds_path=bnds_file)

# %% [markdown]
# #### Set bounds for parameters
# Separate parameters by bounding method and apply the appropriate bounds.

# %% [markdown]
# Create the lists (pd.series) of parameters for the calibration methods

# %%
percent_list = bnds.loc[bnds.HRU_cal_method == "Percent", "parameter_name"].reset_index(
    drop=True
)
range_list = bnds.loc[bnds.HRU_cal_method == "Range", "parameter_name"]

not_used_list = bnds.loc[bnds.HRU_cal_method == "Not used", "parameter_name"]

# %% [markdown]
# #### Assign bounds — Percent method (+/- 20% of starting value)

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
# #### Assign bounds — Range method (fixed upper/lower from literature)

# %%
for cp in range_list:
    cpars = par_starting_vals.loc[par_starting_vals.parname.str.startswith(cp)][
        "parname"
    ]
    par_starting_vals.loc[cpars, "parubnd"] = bnds.loc[cp]["par_upper_bound"]
    par_starting_vals.loc[cpars, "parlbnd"] = bnds.loc[cp]["par_lower_bound"]


# %% [markdown]
# #### Review final `par_starting_vals`

# %%
par_starting_vals

# %% [markdown]
# ### Write the template file and starting values
# Write `parameters.json.tpl` (the PEST++ template) and `starting_par_vals.dat`
# (the parameter table with names, values, and bounds).

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
