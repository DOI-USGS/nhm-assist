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
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]

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
# # Add Localization Matrix for PEST++ IES
#
# This notebook constructs a localization matrix (`loc.mat`) that restricts which
# parameters can be updated by which observations during the PEST++ IES ensemble
# update step. Localization prevents spurious correlations between physically
# unrelated parameter-observation pairs from degrading the estimation.
#
# **Output files:**
# - `loc.mat` — The localization matrix in PEST++ ASCII matrix format.
# - `prior_mc_loc.pst` — Updated control file that references the localization matrix.
# - `localization_group_lookup.csv` — Human-readable mapping of parameter/observation
#   group assignments for documentation.
#
# **How localization works in PEST++ IES:**
# The localization matrix is a binary (0/1) matrix where rows are observation groups
# and columns are parameter groups. A value of 1 means that observation group can
# inform that parameter group during the ensemble update. A value of 0 blocks the
# update pathway, preventing physically implausible correlations from influencing
# parameter adjustments.
#
# **Workflow steps:**
# 1. Load the existing control file (`prior_mc.pst`).
# 2. Read the base localization configuration from `localization_groups.csv`.
# 3. Identify unique parameter-observation group combinations.
# 4. Reassign parameter group names based on their localization behavior.
# 5. Build the localization matrix and write to `loc.mat`.
# 6. Update the control file with the localizer reference and write `prior_mc_loc.pst`.

# %% [markdown]
# ## Load the Control File

# %%
pst = pyemu.Pst(str(pestpp_model_dir / "prior_mc.pst"))

# %% [markdown]
# ### Extract parameter and observation data from the PST object

# %%
pars = pst.parameter_data
obs = pst.observation_data

# %% [markdown]
# ### Review observation groups

# %%
pst.obs_groups

# %% [markdown]
# ## Read the Base Localization Configuration
# The `localization_groups.csv` defines which parameter types are informed by which
# observation groups (1 = allowed, 0 = blocked).

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
# ## Identify Unique Parameter-Observation Combinations
# Parameters that share the same set of informing observation groups are placed
# into a common "super-group" for localization purposes.

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
# ### Assign group names to parameter-observation combinations

# %%
group_lookup = {f"obs_combo_{i+1}": j for i, j in enumerate(all_combos)}

# %% [markdown]
# ### Map parameter types to their localization group

# %%
base_loc["par_obs_group"] = [
    [k for k, v in group_lookup.items() if v == i][0] for i in base_loc.par_obs_combo
]

# %% [markdown]
# ### Build the parameter group name mapping

# %%
new_par_groups = dict(
    zip(base_loc.index, base_loc.par_obs_group)
)  # mapping a new group name for each par type.

# %% [markdown]
# ### Create descriptive group labels and export lookup table

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
# ### Reset the base localization matrix orientation

# %%
base_loc = base_loc.drop(columns=["par_obs_combo", "par_obs_group"]).T

# %% [markdown]
# ### Update parameter group names in the PST object

# %%
for k, v in new_par_groups.items():
    pars.loc[pars.parnme.str.startswith(k), "pargp"] = v

# %%
pars.pargp.unique()


# %% [markdown]
# ### Verify no parameters were left ungrouped

# %%
assert "pargp" not in pars.pargp.unique()

# %%
base_loc.columns

# %% [markdown]
# ## Build the Final Localization Matrix

# %%
locmat = pd.DataFrame(0, base_loc.index, group_lookup.keys())

# %% [markdown]
# ### Populate the matrix (1 where obs group informs parameter group)

# %%
for k, v in group_lookup.items():
    for cob in v:
        locmat.loc[cob, k] = 1.0

# %%
locmat

# %% [markdown]
# ### Write `loc.mat` in PEST++ ASCII matrix format

# %%
pyemu.Matrix.from_dataframe(locmat).to_ascii(str(pestpp_model_dir / "loc.mat"))

# %% [markdown]
# ## Write Updated Control File and Run Verification
# Add the localizer reference to the PST and write `prior_mc_loc.pst`.
# Run with `noptmax=0` to verify everything is consistent.

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
