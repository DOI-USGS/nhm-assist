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
    write_to_json_tpl,
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
# ## Read NHM subbasin model parameter file `.param`
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
con.print(dims)

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
# ## Create a PEST template file version of json-style of myparam_starting_vals.param, "pars"

# %% [markdown]
# ### Create `par_starting_vals` empty dataframe with pestpp column names: parname (pestpp param name) and parval1 (pestpp starting value)

# %%
par_starting_vals = pd.DataFrame(columns=["parname", "parval1", "parubnd", "parlbnd"])
# par_starting_vals

# %% [markdown]
# ### Using `pars_to_tpl_entries()`, write `.param` values to a new dataframe `par_starting_vals`

# %% jupyter={"source_hidden": true}
# notes
# These "were" calibrated back in the day:
#'dprst_depth_avg',  (use prms default range)
#'dprst_flow_coef',
#'dprst_seep_rate_open',
#'op_flow_thres',
#'sro_to_dprst_imperv',
#'sro_to_dprst_perv',
#'va_open_exp'
#

# Ones we are adding:
#'dprst_frac', For WI we decided to set at 0.1 and let vary from 0.8 to 1.2

#'dprst_et_coef', range 0.5 to 1.5, default of 1.0

#'dprst_frac_open', 'dprst_seep_rate_clos',

# %%
pars = pardat.parameters
hrus = pars["nhm_id"]
segs = pars["nhm_seg"]

par_starting_vals = pars_to_tpl_entries(
    pars,
    "adjmix_rain",
    hrus,  # could be defined in function and not passed
    segs,  # could be defined in function and not passed
    par_starting_vals,
    hru_based=True,  # These three argument could be checked and not passed using pw dict from the function
    seg_based=False,
    month_based=True,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "carea_max",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "cecn_coef",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=True,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "emis_noppt",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "fastcoef_lin",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "freeh2o_cap",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "gwflow_coef",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "jh_coef",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=True,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "mann_n",
    hrus,
    segs,
    par_starting_vals,
    hru_based=False,
    seg_based=True,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "potet_sublim",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "rad_trncf",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "radmax",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=True,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "rain_cbh_adj",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=True,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "slowcoef_sq",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "smidx_coef",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "smidx_exp",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "snarea_thresh",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "snowinfil_max",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "snow_cbh_adj",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=True,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "soil2gw_max",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "soil_moist_max",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "soil_rechr_max_frac",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "ssr2gw_exp",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "ssr2gw_rate",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=False,
)
# par_starting_vals = pars_to_tpl_entries(
#     pars,
#     "tmax_allrain_offset",
#     hrus,
#     segs,
#     par_starting_vals,
#     hru_based=True,
#     seg_based=False,
#     month_based=True,
# )
par_starting_vals = pars_to_tpl_entries(
    pars,
    "tmax_allsnow",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=True,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "tmax_cbh_adj",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=True,
)
par_starting_vals = pars_to_tpl_entries(
    pars,
    "tmin_cbh_adj",
    hrus,
    segs,
    par_starting_vals,
    hru_based=True,
    seg_based=False,
    month_based=True,
)

par_starting_vals.set_index("parname", inplace=True, drop=False)
par_starting_vals

# xx = par_starting_vals.loc[par_starting_vals.parname.str.startswith("carea_max"), :]
# xx


# %% [markdown]
# ### Setting parameter bounds in `par_starting_vals`
# There were three ways to set parameter bounds in NHM calibration:
# 1) "not used" in the by_HRU calibration, all HRU values for this type were grouped and moved as a group in the full calibration range for the parameter.
# 2) "range" were calibrated by HRU so will move independently within the calibrations range in table 3.
# 3) "percent" were calibrated by HRU but only allowed a range of +/- 20% of the starting value.

# %%
bnds_path = pestpp_model_dir / "ancillary/par_cal_bounds_use.csv"
bnds = pd.read_csv(bnds_path)  # Creates a data frame of the bounds for par catagories
bnds.set_index("parameter_name", inplace=True, drop=False)

# %% [markdown]
# #### Check bounds

# %%
bnds
# bnds.parameter_name.unique()

# bnds check
bnds_params = bnds.parameter_name.unique()
par_starting_vals_params_groups = (
    par_starting_vals["parname"].str.split(":").str[0].unique()
)

missing_bounds = set(list(par_starting_vals_params_groups)) - set(list(bnds_params))
extra_bounds = set(list(bnds_params)) - set(list(par_starting_vals_params_groups))

if missing_params:
    con.print(
        f"The following parameters need bounds added to {bnds_path}: {missing_params}"
    )
else:
    con.print("All parmaeters in `par_starting_vals` have bounds.")

if extra_params:
    con.print(
        f"The following parameters have bounds listed in{bnds_path}, but are not present in `par_starting_vals`:{extra_params}"
    )

# %% [markdown]
# #### Create the lists of parameters for the calibration methods used

# %%
percent_list = bnds.loc[bnds.HRU_cal_method == "Percent", "parameter_name"].reset_index(
    drop=True
)
range_list = bnds.loc[
    bnds.HRU_cal_method == "Range", "parameter_name"
]  # .to_list() Note, all values are uniform starting values populated from the table 'par_vale_use.csv'
not_used_list = bnds.loc[
    bnds.HRU_cal_method == "Not used", "parameter_name"
]  # .to_list()
print(not_used_list)

# %% [markdown]
# #### set bounds based on percentages or ranges

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

# %%
for cp in range_list:
    cpars = par_starting_vals.loc[par_starting_vals.parname.str.startswith(cp)][
        "parname"
    ]
    par_starting_vals.loc[cpars, "parubnd"] = bnds.loc[cp]["par_upper_bound"]
    par_starting_vals.loc[cpars, "parlbnd"] = bnds.loc[cp]["par_lower_bound"]


# %% [markdown]
# ### Write pestpp-ies template file `parameters.json.tpl`

# %%
write_to_json_tpl(dims, pars, pestpp_model_dir / "parameters.json.tpl")
par_starting_vals.to_csv(
    pestpp_model_dir / "starting_par_vals.dat", index=None, sep=" "
)
par_starting_vals

# %% [markdown]
# ## Create PEST instruction file `.ins`
# Map observation name from allobs.dat (created in notebook 01_Create_allobs_dat) to the instruction file `modelobs.dat.ins`

# %%
obsvals = pd.read_csv(pestpp_model_dir / "allobs.dat", delim_whitespace=True)
obsvals.set_index("obsname", inplace=True, drop=False)
# obsvals.sample(5)
# print(obsvals)
print(f'The {len(obsvals)} values for "obsval" are the true observation values.')

# %%
with open(os.path.join(pestpp_model_dir, "modelobs.dat.ins"), "w") as ofp:
    ofp.write("pif ~\n")
    ofp.write("~obsval~\n")
    [ofp.write(f"l1 w !{i}!\n") for i in obsvals.obsname]

# %% [markdown]
# ## Create PEST control file object with `pyemu`

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

# %% [markdown]
# ## Direct editing of the PEST parameter file

# %% [markdown]
# ## Starting parameter values
# ### Starting values were set from the initial parameter file used, in our case it was the "pre-calibration" values given to us by Parker. SO! No changes to those values, but we will need to customize the upper and lower bounds!

# %%
pars = pst.parameter_data
pars

# %%
par_starting_vals

# %%
# pars.loc['adjmix_rain:hru_5621:mon_1','parval1'] = 987236
# pst.parameter_data


# %% [markdown]
# ### Copy parval1, upper bound and lower bound from "par_starting_vals" to pars.parval1 

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

# %%
len(pars)

# %% [markdown]
# ### Copy upper and lower bounds from par_cal_bounds_use.csv to par.parubnd and par.parlbnd
# ### AND...overwite parval1 with new strating values determined from default values listed in PRMS table 5.2.1 (published), https://water.usgs.gov/water-resources/software/PRMS/--Chack with jacob and make sure these jive with what they used in the cal script. NO we are not doing this anymore!

# %%
bnds

# %%
prms_parnme_list = bnds[
    "parameter_name"
]  # Make a list of the nhm par names for loops below
# print(prms_parnme_list)

# %%
# We recan delete this because we replaced this assignment above
# for idx, row in pars.iterrows():
#    for i in prms_parnme_list:
#        pst_parnme = str(row.parnme)
#        prms_parnme = prms_parnme_list[i]
#        x = pst_parnme.startswith(prms_parnme)# Just a yes not response to if the pst parname starts with the root in "".
#        if x :
#            pars.loc[pst_parnme,'parubnd'] = bnds.loc[prms_parnme,'par_upper_bound']
#            pars.loc[pst_parnme,'parlbnd'] = bnds.loc[prms_parnme,'par_lower_bound']
#            #pars.loc[pst_parnme,'parval1'] = bnds.loc[prms_parnme,'par_start_val'] remove

# %% [markdown]
# ### we can't log transform negative parameter values

# %%
pars.loc[pars.parlbnd <= 0, "partrans"] = "none"

# %%
### obs.loc[obsvals.obsname, 'obsval'] = obsvals.obsval.values

# %% [markdown]
# #### Set obsval in the "pst.observation_data" frame back to the true observation value

# %%
obs = (
    pst.observation_data
)  # This pulls the "observation data" from the pst dataframe and sets it to the "obs" object (dataframe)

# %%
obs.loc[obs.obgnme.str.contains("obgnme"), :]

# %%
obs.loc[
    obs.obsnme == "actet_mon:2000_1:5621", :
]  # This is the value in the modelobs.dat file?

# %%
obsvals.loc[obsvals.obsname == "actet_mon:2000_1:5621", :]

# %%
# obs = obs.loc[obsvals.obsname,:] #resorts datframe for easy in reading

# %%
obs.loc[obsvals.obsname, "obsval"] = (
    obsvals.obsval.values
)  # True observation value is copied over to obs
obs

# %%
obs.loc[obs.obsnme == "actet_mon:2000_1:5621", :]  # Check for change

# %% [markdown]
# #### PEST++ now allows for ranges to be set for obs, so we set those here (and comment out the old approach below)

# %%
# obs.loc[obs.obgnme.str.startswith("streamflow_daily_low")]
obs.sample(50)

# %%
obs.loc[:, "less_than"] = np.nan
obs.loc[:, "greater_than"] = np.nan

obs_bounds = pd.read_csv(
    os.path.join(pestpp_model_dir, "allobs_bounds.dat"), delim_whitespace=True
)
l_bnd_dict = dict(
    zip(
        obs_bounds.loc[obs_bounds.obsname.str.contains("l_max_"), "obsname"],
        obs_bounds.loc[obs_bounds.obsname.str.contains("l_max_"), "obsval"],
    )
)
g_bnd_dict = dict(
    zip(
        obs_bounds.loc[obs_bounds.obsname.str.contains("g_min_"), "obsname"],
        obs_bounds.loc[obs_bounds.obsname.str.contains("g_min_"), "obsval"],
    )
)
l_bnd_dict = {k.replace("l_max_", ""): v for k, v in l_bnd_dict.items()}
g_bnd_dict = {k.replace("g_min_", ""): v for k, v in g_bnd_dict.items()}

obs.loc[:, "less_than"] = obs.loc[:, "obsnme"].map(l_bnd_dict)
obs.loc[:, "greater_than"] = obs.loc[:, "obsnme"].map(g_bnd_dict)

obs.loc[obs.obsnme.str.startswith("actet_mon"), "obgnme"] = "actet_mon"

obs.loc[obs.obsnme.str.startswith("actet_mean_mon"), "obgnme"] = "actet_mean_mon"

obs.loc[obs.obsnme.str.startswith("recharge_ann"), "obgnme"] = "recharge_ann"

obs.loc[obs.obsnme.str.startswith("soil_moist_mon"), "obgnme"] = "soil_moist_mon"

obs.loc[obs.obsnme.str.startswith("soil_moist_ann"), "obgnme"] = "soil_moist_ann"

obs.loc[obs.obsnme.str.startswith("runoff_mon"), "obgnme"] = "runoff_mon"

obs.loc[obs.obsnme.str.startswith("sca_daily"), "obgnme"] = "sca_daily"

# %% [markdown]
# #### Creating Groups observations

# %%
# obs.loc[obs.obsnme.str.startswith('l_max_actet_mon'),'obgnme'] = 'l_max_actet_mon'
# obs.loc[obs.obsnme.str.startswith('g_min_actet_mon'),'obgnme'] = 'g_min_actet_mon'

# obs.loc[obs.obsnme.str.startswith('l_max_actet_mean_mon'),'obgnme'] = 'l_max_actet_mean_mon'
# obs.loc[obs.obsnme.str.startswith('g_min_actet_mean_mon'),'obgnme'] = 'g_min_actet_mean_mon'

# obs.loc[obs.obsnme.str.startswith('l_max_recharge_ann'),'obgnme'] = 'l_max_recharge_ann'
# obs.loc[obs.obsnme.str.startswith('g_min_recharge_ann'),'obgnme'] = 'g_min_recharge_ann'

# obs.loc[obs.obsnme.str.startswith('l_max_soil_moist_mon'),'obgnme'] = 'l_max_soil_moist_mon'
# obs.loc[obs.obsnme.str.startswith('g_min_soil_moist_mon'),'obgnme'] = 'g_min_soil_moist_mon'

# obs.loc[obs.obsnme.str.startswith('l_max_soil_moist_ann'),'obgnme'] = 'l_max_soil_moist_ann'
# obs.loc[obs.obsnme.str.startswith('g_min_soil_moist_ann'),'obgnme'] = 'g_min_soil_moist_ann'


# #obs.loc[obs.obsnme.str.startswith('runoff_mon'),'obgnme'] = 'runoff_mon'
# obs.loc[obs.obsnme.str.startswith('l_max_runoff_mon'),'obgnme'] = 'l_max_runoff_mon'
# obs.loc[obs.obsnme.str.startswith('g_min_runoff_mon'),'obgnme'] = 'g_min_runoff_mon'

# #obs.loc[obs.obsnme.str.startswith('sca_daily'),'obgnme'] = 'sca_daily'
# obs.loc[obs.obsnme.str.startswith('l_max_sca_daily'),'obgnme'] = 'l_max_sca_daily'
# obs.loc[obs.obsnme.str.startswith('g_min_sca_daily'),'obgnme'] = 'g_min_sca_daily'


# obs.loc[obs.obsnme.str.startswith('streamflow_daily'),'obgnme'] = 'streamflow_daily'

# Create EFC Groups for daily streamflows
# streamflow_daily is followed by a suffix: "efc"_"high_low" integers
# efc [1, 2, 3, 4, 5] are ['Large flood', 'Small flood', 'High flow pulse', 'Low flow', 'Extreme low flow']
# high_low [1, 2, 3] are ['Low flow', 'Ascending limb', 'Descending limb']
# Pest++ group names were written with flows in mind.

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

# Special group for daily streamflow and no EFC code
obs.loc[
    (obs.obsnme.str.startswith("streamflow_daily")) & (obs.obsnme.str.contains("-1")),
    "obgnme",
] = "streamflow_no_efc"

# Special group for no flow
obs.loc[obs.obsnme.str.startswith("streamflow_daily_-9999_-9999"), "obgnme"] = (
    "streamflow_nodata"
)
obs.loc[
    (obs.obsnme.str.startswith("streamflow_daily")) & (obs.obsval == -9999), "obgnme"
] = "streamflow_nodata"
# for ex in exclude_gages[c_model]:
#     obs.loc[(obs.obsnme.str.startswith('streamflow_daily')) & (obs.obsnme.str.endswith(ex)), 'obgnme'] = 'streamflow_nodata'
#     obs.loc[(obs.obsnme.str.startswith('streamflow_mon')) & (obs.obsnme.str.endswith(ex)), 'obgnme'] = 'streamflow_nodata'
#     obs.loc[(obs.obsnme.str.startswith('streamflow_mean_mon')) & (obs.obsnme.str.endswith(ex)), 'obgnme'] = 'streamflow_nodata'

obs.loc[obs.obsnme.str.startswith("streamflow_mon"), "obgnme"] = "streamflow_mon"
obs.loc[obs.obsnme.str.startswith("streamflow_mean_mon_cal"), "obgnme"] = (
    "streamflow_mean_mon_cal"
)
obs.loc[obs.obsnme.str.startswith("streamflow_mean_mon_val"), "obgnme"] = (
    "streamflow_mean_mon_val"
)
obs.sample(30)

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
# exclude_gages[c_model][0]

# %%
# Set weights for groups"
## TODO: Assign weights for all but streamflow that make sense as 1/std

###Need to tailor these wts individually to the STDV values that we assume are "good."

# obs.loc[obs.obgnme=='l_max_actet_mean_mon','weight'] = 3.0E+04
# obs.loc[obs.obgnme=='g_min_actet_mean_mon','weight'] = 3.0E+04

# obs.loc[obs.obgnme=='l_max_actet_mon','weight'] = 0.75E+04
# obs.loc[obs.obgnme=='g_min_actet_mon','weight'] = 0.75E+04

# obs.loc[obs.obgnme=='l_max_recharge_ann','weight'] = 0.4E+04
# obs.loc[obs.obgnme=='g_min_recharge_ann','weight'] = 0.4E+04

# obs.loc[obs.obgnme=='l_max_soil_moist_ann','weight'] = 2.5E+03
# obs.loc[obs.obgnme=='g_min_soil_moist_ann','weight'] = 2.5E+03

# obs.loc[obs.obgnme=='l_max_soil_moist_mon','weight'] = 8E+02
# obs.loc[obs.obgnme=='g_min_soil_moist_mon','weight'] = 8E+02


# obs.loc[obs.obgnme=='l_max_sca_daily','weight'] = 0 #3E-03
# obs.loc[obs.obgnme=='g_min_sca_daily','weight'] = 0 #3E-03

# obs.loc[obs.obgnme=='l_max_runoff_mon','weight'] = 3.5
# obs.loc[obs.obgnme=='g_min_runoff_mon','weight'] = 3.5


# obs.loc[obs.obgnme.str.startswith('streamflow'), 'weight'] = \
#     10 / obs.loc[obs.obgnme.str.startswith('streamflow'),'obsval']
# obs.loc[obs.obgnme=='streamflow_nodata','weight'] = 0

# # special case for streamflow with 0 observed value
# obs.loc[(obs.obsval<=1) & (obs.obgnme.str.startswith('stream')), 'weight'] = 1.0

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
# khm edited this for the new obs groups (no l_ or g_)
obs_sdbnds = obs_sdbnds.loc[~obs_sdbnds.obsgroup.str.contains("g_min_"), :]
obs_sdbnds.replace({"l_max_": ""}, regex=True, inplace=True)
# also in order to do phi factor, had to change this group name
obs_sdbnds.replace({"exlow": "ex_low"}, regex=True, inplace=True)
obs_sdbnds.replace({"asc": "ascnd"}, regex=True, inplace=True)
obs_sdbnds.replace({"dsc": "dscnd"}, regex=True, inplace=True)

# %%
obs_sdbnds.set_index("obsgroup", inplace=True, drop=False)
obs_sdbnds

# %%
obs_sdbnds.index = [
    i.strip() for i in obs_sdbnds.index
]  # strip removes the extra spaces and /n etc

# %%
obs_sdbnds

# %%
obs_sdbnds.index.unique()

# %%
obsgroup_list = obs_sdbnds["obsgroup"]
obsgroup_list

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
obs.loc[obs.obgnme == "streamflow_nodata"]

# %%
set(obs.obgnme)
# set(obs_sdbnds.index)

# %%
for cn, _ in obs.groupby("obgnme"):
    if "streamflow" in cn:
        obs.loc[obs.obgnme == cn, "upper_bound"] = obs_sdbnds.loc[cn, "obsubnd"]
        obs.loc[obs.obgnme == cn, "lower_bound"] = obs_sdbnds.loc[cn, "obslbnd"]
    # print(cn)

# %%
obs.loc[obs.obgnme.str.startswith("streamflow_daily_low")]

# %%
# # print(list(obs_sdbnds.index))
# # print(obgnme_list)
# list(set(obgnme_list) - set(list(obs_sdbnds.index)))

# # list(set(obgnme_list) - set(list(obs_sdbnds.index)))

# %%
# obs_sdbnds.index
obs.obgnme.unique()

# %%
obgnme_list = list(set(obs.obgnme))
print(len(obgnme_list))

for cn in obgnme_list:
    if cn in obs.obgnme.values:
        obs_group_percent = obs_sdbnds.loc[cn, "noise_percent"]
        print(cn)
    else:
        print(f"{cn} is not in there")
# obs_group_percent

# %%
obgnme_list = list(set(obs.obgnme))

for cn, _ in obs.groupby("obgnme"):
    if cn in obs.obgnme.values:
        obs_group_percent = obs_sdbnds.loc[cn, "noise_percent"]
        obs.loc[obs.obgnme == cn, "standard_deviation"] = obs_group_percent * (
            obs.loc[obs.obgnme == cn, "obsval"]
        )
    # print(cn)

# Replace std value with 9999 where obsval values with "9999"
obs.loc[obs.obsval == -9999, "standard_deviation"] = 9999

# %%
# obs.loc[obs.standard_deviation.isnull()]
obs.loc[obs.standard_deviation == np.nan]


# %%
# obs.loc[(obs.obsval == 0) & (obs.obgnme == "streamflow_daily_low")]
# obs.loc[(obs.obsval == 0) & (obs.obgnme == "streamflow_daily_low")]
# obs.loc[obs.obgnme.str.startswith("streamflow_daily_low"), "weight"].max()

# %%
# But, to read in the "other" SD, the SD for the value, not the noise.

# %%
# Do this for streamflow but not the rest
for cn, _ in obs.groupby("obgnme"):
    if cn.startswith("streamflow_"):
        obs_group_percent = obs_sdbnds.loc[
            cn, "wt_percent"
        ]  # "wt_percent" in the table is a fractional value from "Observation_standard_deviation.csv"
        obs.loc[obs.obgnme == cn, "weight"] = 1 / (
            obs_group_percent * (obs.loc[obs.obgnme == cn, "obsval"])
        )
    else:
        obs_group_percent = obs_sdbnds.loc[cn, "wt_percent"]
        obs.loc[obs.obgnme == cn, "weight"] = 1 / obs_group_percent


# # For the inequality calibration obs, do NOT take weight calc using the obs val
# obs.loc[obs.obgnme.str.startswith("streamflow_"), "weight"] = (
#     "streamflow_daily_large_ascnd"
# )


# %%
obs.weight.sample(50)

# %%
# obs.loc[obs.obgnme=='l_max_sca_daily','weight'] = 10#3E-03
# obs.loc[obs.obgnme=='sca_daily','weight'] = 10#3E-00

# Eddie commented out, seemed to just undo the code in the above cell
obs.loc[obs.obgnme.str.startswith("streamflow"), "weight"] = (
    10 / obs.loc[obs.obgnme.str.startswith("streamflow"), "obsval"]
)

obs.loc[obs.obgnme == "streamflow_nodata", "weight"] = 0

"""Replace -9999 obs_val values with 0 weight"""
obs.loc[obs.obsval == -9999, "weight"] = 0

# %%
obs.weight.sample(50)

# %%
"""special case for ex_lowflow group values (less than 1 cfs). This avoids a division by zero.
This code will calculate the weight for flows less than 1 cfs (ex_low) not using the obsval
for the ex_low val, but use 1/2 the flow of the lowest value from the low group."""

"""Set variables for calculation"""
ex_low_min = 1.0  # units in cfs

"""Calculation"""
low_bound = obs.loc[obs.obgnme.str.contains("streamflow_daily_lo"), "obsval"].min()
ex_low_val = 0.5 * (low_bound)


obs_group_percent = obs_sdbnds.loc[
    obs_sdbnds.obsgroup.str.contains("streamflow_daily_ex_low"), "wt_percent"
]
obs.loc[
    (obs.obsval <= ex_low_min) & (obs.obgnme.str.contains("streamflow_daily_ex_lo")),
    "weight",
] = 1 / (obs_group_percent[0].astype(float) * (ex_low_val))

# %%
# print(f"obs_group_percent is {obs_group_percent}")
# print(f"low_bound is {low_bound}")
# print(f"ex_low_val is {ex_low_val}")

# %%
obs.loc[obs.obgnme.str.contains("streamflow_daily_-9999")]

# %%
# obs.loc[obs.weight.isna()]

# %%
# obs.loc[(obs.obsval <= ex_low_min) & (obs.obgnme.str.contains("streamflow_daily"))]

# %%
type(obs_group_percent[0].astype(float))

# %%
# obs.weight.sample(50)
obs.loc[obs.obgnme.str.startswith("streamflow_daily_ex_low")]

# %%
# obs.loc[
#     (obs.obsval <= ex_low_min) & (obs.obgnme.str.startswith("streamflow_")),
#     "weight",
# ]

# %%
# obs.loc[obs.weight.isnull()]
# obs.loc[obs.weight == np.nan]
obs.loc[obs.obgnme.str.startswith("streamflow"), "weight"].max()

# %%
obs.loc[(obs.obgnme.str.startswith("streamflow_")) & (obs.weight == np.inf)]

# %%
# # Matt and Eddie trying to fix the Nan's issue when writng the pst
# obs["less_than"].replace(np.nan, -9999, inplace=True)
# obs["greater_than"].replace(np.nan, -9999, inplace=True)
# obs["upper_bound"].replace(np.nan, -9999, inplace=True)
# obs["lower_bound"].replace(np.nan, -9999, inplace=True)

# %%
obs["wateryear"] = -999

# %%
# Bot suggested alternative to faster form of celle below

# Mean monthly — untouched in original code
mask_mean_mon = obs.obgnme.str.contains("mean_mon")

# Monthly (no "mean")
mask_mon = obs.obgnme.str.contains("mon") & ~obs.obgnme.str.contains("mean")
obs.loc[mask_mon, "wateryear"] = (
    pd.to_datetime(
        obs.loc[mask_mon].index.str.split(":").str[1].str.replace("_", "-", regex=False)
        + "-01",
        errors="coerce",
    )
    + pd.DateOffset(30 + 31 + 31)
).year

# Annual
mask_ann = obs.obgnme.str.contains("ann")

obs_index_series = pd.Series(obs.loc[mask_ann].index)  # Convert Index to Series
obs_index_split = obs_index_series.str.split(":").str[1]  # Extract substring part
obs.loc[mask_ann, "wateryear"] = obs_index_split.astype(
    int
).values  # Assign as numpy array to avoid index alignment issues

# Daily
mask_daily = obs.obgnme.str.contains("daily")
obs.loc[mask_daily, "wateryear"] = (
    pd.to_datetime(
        obs.loc[mask_daily]
        .index.str.split(":")
        .str[1]
        .str.replace("_", "-", regex=False),
        errors="coerce",
    )
    + pd.DateOffset(30 + 31 + 31)
).year

print(f"Are there NaN's in the water years? {obs['wateryear'].isna().any()}")

# %%
obs.loc[obs.weight.isna()]
# obs.loc[(obs.obsval <= 0.99) & (obs.obsnme.str.startswith("streamflow"))]

# %%
# # Do not delete this; save for ref and testing above block
# for cgroup in obs.obgnme.unique():
#     if "mean_mon" in cgroup:
#         pass
#     elif ("mon" in cgroup) & ("mean" not in cgroup):
#         obs.loc[obs.obgnme == cgroup, "wateryear"] = [
#             (
#                 pd.to_datetime(f"{'-'.join(i.split(':')[1].split('_'))}-1")
#                 + pd.DateOffset(30 + 31 + 31)
#             ).year
#             for i in obs.loc[obs.obgnme == cgroup].index
#         ]

#     elif "ann" in cgroup:
#         obs.loc[obs.obgnme == cgroup, "wateryear"] = [
#             int(i.split(":")[1]) for i in obs.loc[obs.obgnme == cgroup].index
#         ]

#     elif "daily" in cgroup:
#         obs.loc[obs.obgnme == cgroup, "wateryear"] = [
#             (
#                 pd.to_datetime((i.split(":")[1]).replace("_", "-"))
#                 + pd.DateOffset(30 + 31 + 31)
#             ).year
#             for i in obs.loc[obs.obgnme == cgroup].index
#         ]


# %% [markdown]
#

# %%
obs.wateryear

# %%
## Set up validation years
seg_outflow_start = "1999-10-01"
seg_outflow_end = "2010-09-30"
start_water_year = pd.to_datetime(seg_outflow_start).year + 1
end_water_year = pd.to_datetime(seg_outflow_end).year
streamflow_water_years = np.array(range(start_water_year, end_water_year + 1))

## We will choose even years as validation
val_water_years = [i for i in streamflow_water_years if i % 2 == 0]
val_water_years

# %%
# unweight the validation data and assign groups to indicate "validation" for these
obs.loc[
    (obs.wateryear.isin(val_water_years) & (obs.obgnme.str.startswith("streamflow"))),
    "weight",
] = 0
obs.loc[
    (obs.wateryear.isin(val_water_years) & (obs.obgnme.str.startswith("streamflow"))),
    "obgnme",
] = [
    f"{i}_val"
    for i in obs.loc[
        (
            obs.wateryear.isin(val_water_years)
            & (obs.obgnme.str.startswith("streamflow"))
        )
    ].obgnme
]

# %%
obs.weight.sample(50)

# %%
obs.loc[obs.obgnme.str.endswith("_val"), "weight"] = 0

# %% [markdown]
# # consolidate the run scripts into a single script
# ### Eddie commented out after modification of the forward_run.py file with James during debugging. Eddie will eventually fix this and bring it back in.

# %%
imports = [
    i.strip()
    for i in open(pestpp_dir / "helpers/run-pynhm.py", "r").readlines()
    if i.strip().startswith("import")
]
imports.extend(
    [
        i.strip()
        for i in open(
            pestpp_dir / "helpers/post-process_model_output.py", "r"
        ).readlines()
        if i.strip().startswith("import")
    ]
)

runbiz = [
    i.rstrip()
    for i in open(pestpp_dir / "helpers/run-pynhm.py", "r").readlines()
    if not i.strip().startswith("import")
]
runbiz.append('print("#### RUN DONE, TIME TO POSTPROCESS ####")')
runbiz.extend(
    [
        i.rstrip()
        for i in open(
            pestpp_dir / "helpers/post-process_model_output.py", "r"
        ).readlines()
        if not i.strip().startswith("import")
    ]
)


# %%
# runbiz

# %%
# dedupe the imports
imports = list(set(imports))


# %% [markdown]
# ### now write out all the forward run stuff

# %%
with open(os.path.join(pestpp_model_dir, "forward_run.py"), "w") as ofp:
    [ofp.write(f"{line}\n") for line in imports + runbiz]

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
if "smidx_exp:hru_84017" in pst.parameter_data.index:
    pst.parameter_data.loc["smidx_exp:hru_84017", "parval1"] = 0.003
    pst.parameter_data.loc["smidx_exp:hru_84017", "parubnd"] = 0.003 * 2


# %%
pst.write(os.path.join(pestpp_model_dir, "prior_mc.pst"), version=2)

# %%
# [pst.observation_data[i].isnull().unique() for i in pst.observation_data.columns]
obs.loc[obs.weight.isnull()].obgnme.unique()

# %%
obs.sample(50)

# %%
obs.isnull().values.any()

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
pst.observation_data.loc[
    (pst.observation_data.obsnme == "streamflow_daily_3_2:2000_7_11:05431022")
]  # &
# (pst.observation_data.weight>0)]

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
    pyemu.utils.get_pestpp(str(pestpp_model_dir))
    pyemu.os_utils.run("pestpp-ies prior_mc.pst", cwd=str(pestpp_model_dir))
else:
    pyemu.os_utils.run("pestpp-ies prior_mc.pst", cwd=str(pestpp_model_dir))


# if os.path.exists(os.path.join(pestpp_model_dir,exe_name)):
#     pyemu.os_utils.run('pestpp-ies prior_mc.pst',cwd=pestpp_model_dir)
# else:
#     pyemu.utils.get_pestpp(pestpp_model_dir)
#     pyemu.os_utils.run('pestpp-ies prior_mc.pst',cwd=pestpp_model_dir)

# %%

# %%

# %%

# %%
