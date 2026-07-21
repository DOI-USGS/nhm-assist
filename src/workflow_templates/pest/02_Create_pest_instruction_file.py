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
# Andy thoughts:
# Related files and definitions:
# read ---> written
# Matt's flow chart idea too!
# maybe say something about the difference in the iunstruction file and the template file here.
#
# This notebook will make two needed files for the pest-ies setup: the PEST instruction file, `modelobs.dat.ins`
#
# The pest instruction  file is a file that connects the pywatershed model output after each model run to the calibration targets listed in the observation file. For clarity, each line in the `allobs.dat` file corresponds to the same indexed line in the `modelobs.dat.ins` file, and also the model output file, `modelobs.dat`. 
#
# `The 01_Create_allobs_dat.ipynb` notebook consolidated the hru observation files that were written with notebook `Subset_NHM_baselines` for the model, assigned observation names for each observation, and wrote observations names and observations into a single file with 2 columns for PEST++ to read, `allobs.dat`.
#
# Then, the instruction file is made from the observations file with
#
# Lastly, this notebook will run the model and postprocess the model output to mirror the observations listed in the instruction file and perform checks to ensure that the lines in the model output file, instruction file, and observation file coorelate to the same observation name. If and error is found, some tips are offered for the corrective approach.
#
# This notebook will read in the consolidated NC files that were written with notebook  `Subset_NHM_baselines`for each subbasin extraction, assign names for each obs, and write names and observations into a single file with 2 columns for PEST++ to read.

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
# ## Check model output

# %% [markdown]
# #### Consolidate the run script (run-pynhm.py) and the model output post-processing script (post-process_model_output.py) into a single script.

# %% [markdown]
# #### Write out combined script (forward_run.py)

# %%
# Instead of the code below that is commented out,  we will read in the .py version of
# both scripts combined from the notebook_scripts folder
# named "Create_model_run_and_post_processing_script.py"
# Copy it it the pest_dir and rename "forward_run.py"
# with open(os.path.join(pestpp_model_dir, "forward_run.py"), "w") as ofp:
#     [ofp.write(f"{line}\n") for line in imports + runbiz]

source = pestpp_dir / "notebook_scripts" / "forward_run.py"
destination = pestpp_model_dir / "forward_run.py"
shutil.copy2(source, destination)

# convert the
param_file = config["model_dir"] / "myparam.param"
parameters_json_file = pestpp_model_dir / "parameters.json"

params = pws.parameters.PrmsParameters.load(param_file)
params.parameters_to_json(parameters_json_file)
# params = pws.parameters.PrmsParameters.load_from_json(parameters_json_file)

# %% [markdown]
# #### Run the model

# %%
cwd = os.getcwd()
# %cd "{pestpp_model_dir}"
# !python forward_run.py
# %cd "{cwd}"

# %% [markdown]
# #### Read in the model output and check against the instruction file
#

# %% jupyter={"source_hidden": true}
# check_ins_and_outs function
import pathlib
import pandas as pd


class InsOutMismatchError(Exception):
    """Raised when ins and output files are inconsistent."""

    pass


def check_ins_and_outs(pestpp_model_dir: str | pathlib.Path) -> None:
    pestpp_model_dir = pathlib.Path(pestpp_model_dir)

    # --- load data
    output_file = pestpp_model_dir / "modelobs.dat"
    output = pd.read_csv(output_file, delim_whitespace=True)

    ins_file = pestpp_model_dir / "modelobs.dat.ins"
    ins = pd.read_csv(ins_file, skiprows=1)

    # --- build obsval_root, including streamflow handling
    ins["obsval_root"] = ins["~obsval~"].str.extract(r"!(.*)!")

    mask = ins["obsval_root"].str.contains("streamflow_daily_", na=False)
    # If the raw pattern is e.g. "streamflow_daily_1999_10_1:08063048",
    # and you want "streamflow_daily:1999_10_1:08063048":
    ins.loc[mask, "obsval_root"] = (
        "streamflow_daily:" + ins.loc[mask, "obsval_root"].str.split(":", n=1).str[1]
    )

    # --- duplicate checks on the key columns
    dup_ins_mask = ins["obsval_root"].duplicated(keep=False)
    dup_out_mask = output["obsname"].duplicated(keep=False)

    ins_dups = ins[dup_ins_mask]
    out_dups = output[dup_out_mask]

    msgs = []
    if not out_dups.empty:
        dups = out_dups["obsname"].astype(str).unique()
        msgs.append(
            "Duplicate obsname values found in model output: "
            + ", ".join(dups[:20])
            + (" ..." if len(dups) > 20 else "")
        )

    if not ins_dups.empty:
        dups = ins_dups["obsval_root"].astype(str).unique()
        msgs.append(
            "Duplicate obsval_root values found in instruction file: "
            + ", ".join(dups[:20])
            + (" ..." if len(dups) > 20 else "")
        )

    if msgs:
        raise InsOutMismatchError(" ".join(msgs))

    # --- lists for order/content checks
    list_output_obsname = output["obsname"].tolist()
    list_ins_obsval_root = ins["obsval_root"].tolist()

    # --- length check
    if len(ins) != len(output):
        missing_in_ins = output.loc[
            ~output["obsname"].isin(ins["obsval_root"]), "obsname"
        ]
        missing_in_output = ins.loc[
            ~ins["obsval_root"].isin(output["obsname"]), "obsval_root"
        ]

        msg = [
            f"Length mismatch: ins has {len(ins)}, output has {len(output)}.",
        ]
        if not missing_in_ins.empty:
            msg.append(
                "Obsnames present in output but missing from ins: "
                + ", ".join(missing_in_ins.astype(str).head(20))
                + (" ..." if len(missing_in_ins) > 20 else "")
            )
        if not missing_in_output.empty:
            msg.append(
                "Obsnames present in ins but missing from output: "
                + ", ".join(missing_in_output.astype(str).head(20))
                + (" ..." if len(missing_in_output) > 20 else "")
            )

        raise InsOutMismatchError(" ".join(msg))

    # --- content check: same values, same order
    if list_output_obsname != list_ins_obsval_root:
        if set(list_output_obsname) == set(list_ins_obsval_root):
            raise InsOutMismatchError(
                "ins and output have the same obsnames but in a different order."
            )

        missing_in_ins = output.loc[
            ~output["obsname"].isin(ins["obsval_root"]), "obsname"
        ]
        missing_in_output = ins.loc[
            ~ins["obsval_root"].isin(output["obsname"]), "obsval_root"
        ]

        msg = ["ins and output have different obsnames."]
        if not missing_in_ins.empty:
            msg.append(
                "Obsnames present in output but missing from ins: "
                + ", ".join(missing_in_ins.astype(str).head(20))
                + (" ..." if len(missing_in_ins) > 20 else "")
            )
        if not missing_in_output.empty:
            msg.append(
                "Obsnames present in ins but missing from output: "
                + ", ".join(missing_in_output.astype(str).head(20))
                + (" ..." if len(missing_in_output) > 20 else "")
            )

        raise InsOutMismatchError(" ".join(msg))

    # --- if we reach here, all checks passed
    return "[bold green]ins and output files are consistent[/bold green]: no duplicates, lengths match, and [code]obsname[/code] / [code]obsval_root[/code] match in order."


# %%
try:
    msg = check_ins_and_outs(pestpp_model_dir)
    con.print(msg)  # success message
except InsOutMismatchError as e:
    con.print(f"ERROR: {e}")

# %%
output_file = pestpp_model_dir / "modelobs.dat"
output = pd.read_csv(output_file, delim_whitespace=True)
output

# %%
output.loc[output["obsname"].str.contains("soil")]

# %%
