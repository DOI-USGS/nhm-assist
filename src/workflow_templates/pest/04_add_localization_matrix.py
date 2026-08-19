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

# %%
# import sys

# sys.path.append("../dependencies/")
# import pandas as pd
# import pyemu
# import numpy as np
# import pathlib as pl

# %% [markdown]
# ### Read `prior_mc.pst`

# %%
pst = pyemu.Pst(str(pestpp_model_dir / "prior_mc.pst"))

# %% [markdown]
# ### Make parameter (pars) and observation (obs) data objects

# %%
pars = pst.parameter_data
obs = pst.observation_data

# %% [markdown]
# ### Review observation groups

# %%
pst.obs_groups

# %% [markdown]
# ### Read in the base localization matrix

# %%
base_loc = pd.read_csv(ancillary_dir / "localization_groups.csv", index_col=0)
base_loc

# %%
# Trim out obs groups that aren't present in the PST file nut are in the base localization matrix
print(base_loc.columns)
# Only selects groups from base_loc that are in the pest obs groups--excludeing those groups with "_val", "sca_daily"
base_loc = base_loc.loc[
    [i for i in pst.obs_groups if "_val" not in i and "sca_daily" not in i]
]
print(base_loc)

# %% [markdown]
# ### Find the unique combinations of observations
# Get a little creative with transposes and add a row with the combos of obs

# %%
base_loc = base_loc.T
base_loc["par_obs_combo"] = [
    set(base_loc.T.loc[base_loc.T[i] == 1].index) for i in base_loc.T.columns
]
base_loc.par_obs_combo

# %%
# we need to find the unique sets of observation super-groups from the localization matrix
all_combos = []
for i in base_loc.par_obs_combo.values:
    if i not in all_combos:
        all_combos.append(i)

# %% [markdown]
# ### now just make par group names according to combinations of obs

# %%
group_lookup = {f"obs_combo_{i+1}": j for i, j in enumerate(all_combos)}

# %% [markdown]
# ### assign the group names to the parameter base types according to the cols of the base localization matrix

# %%
base_loc["par_obs_group"] = [
    [k for k, v in group_lookup.items() if v == i][0] for i in base_loc.par_obs_combo
]

# %% [markdown]
# ### now we have a list of groups for parameters

# %%
new_par_groups = dict(
    zip(base_loc.index, base_loc.par_obs_group)
)  # mapping a new group name for each par type.

# %% [markdown]
# ### set up mapping for localization groups

# %%
# assign meaningful descriptive names to the parameter supergroups
group_name_lookup = dict(
    zip(
        [f"obs_combo_{i+1}" for i in range(7)],
        [
            "Daily, all",
            "Daily;\nLand Surface",
            "Daily, low",
            "Daily, low;\nLand Surface",
            "Land Surface",
            "Monthly;\nMean Monthly;\nLand Surface",
            "Daily, high;\nLand Surface",
        ],
    )
)
group_name_lookup

# %%
locgroup, datatype, currval, groupname = [], [], [], []

# %%
for cg in sorted(base_loc["par_obs_group"].unique()):
    for obs_name in group_lookup[cg]:
        locgroup.append(cg),
        datatype.append("obs")
        currval.append(obs_name)
        groupname.append(group_name_lookup[cg])
    for par_name in base_loc.loc[base_loc.par_obs_group == cg].index.values:
        locgroup.append(cg),
        datatype.append("par")
        currval.append(par_name)
        groupname.append(group_name_lookup[cg])
loc_mapping = pd.DataFrame(
    data={
        "loc_group": locgroup,
        "datatype": datatype,
        "currval": currval,
        "groupname": groupname,
    }
)
loc_mapping.to_csv(pestpp_model_dir / "localization_group_lookup.csv")

# %% [markdown]
# ### and we can cast the base_loc matrix back to original orientation and drop these names

# %%
base_loc = base_loc.drop(columns=["par_obs_combo", "par_obs_group"]).T

# %% [markdown]
# ### so, update the parameter groupnames

# %%
for k, v in new_par_groups.items():
    pars.loc[pars.parnme.str.startswith(k), "pargp"] = v

# %%
pars.pargp.unique()


# %% [markdown]
# ### make sure we didn't miss any parameters in the groupings

# %%
assert "pargp" not in pars.pargp.unique()

# %%
base_loc.columns

# %% [markdown]
# ### make the final localization matrix

# %%
locmat = pd.DataFrame(0, base_loc.index, group_lookup.keys())

# %% [markdown]
# ### loop over the groups and assign 1s where obs line up with par groups

# %%
for k, v in group_lookup.items():
    for cob in v:
        locmat.loc[cob, k] = 1.0

# %%
locmat

# %% [markdown]
# ### finally save it out to a text format

# %%
pyemu.Matrix.from_dataframe(locmat).to_ascii(str(pestpp_model_dir / "loc.mat"))

# %% [markdown]
# ### and refer to it in the PST file (TODO: add writing out the PST file)

# %%
pst.pestpp_options["ies_localizer"] = "loc.mat"
pst.control_data.noptmax = 0

# %%
# Write a new version of the PEST++ control file (.pst)
pst.write(str(pestpp_model_dir / "prior_mc_loc.pst"), version=2)

# will have to track this file and may need to add a bunch of files to be tracked

# %%
pyemu.os_utils.run("pestpp-ies prior_mc_loc.pst", cwd=pestpp_model_dir)

# %%
