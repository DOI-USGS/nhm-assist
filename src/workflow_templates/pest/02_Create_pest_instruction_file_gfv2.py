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
from assist.nhf import efc

config = load_subdomain_config(root_dir)


import pandas as pd
import xarray as xr
import numpy as np
import shutil
import datetime

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

# %%
root_dir

# %% [markdown]
# # Create PEST++ Instruction File
#
# This notebook creates the PEST++ instruction file (`modelobs.dat.ins`) that tells
# PEST++ how to read simulated values from model output and match them to the
# observations defined in `allobs.dat` (created in notebook 01).
#
# **Output files:**
# - `modelobs.dat.ins` — The PEST++ instruction file. Each line maps an observation
#   name to a position in the model output file (`modelobs.dat`).
# - `forward_run.py` — The combined model run + post-processing script that PEST++
#   executes for each parameter realization.
# - `parameters.json` — JSON export of the PRMS parameter file for use by `forward_run.py`.
#
# **How PEST++ uses these files:**
# On each iteration, PEST++ calls `forward_run.py` which runs pywatershed and
# writes simulated values to `modelobs.dat`. PEST++ then reads `modelobs.dat.ins`
# to extract the simulated values and compares them line-by-line against the
# observed values in `allobs.dat`.
#
# **Workflow steps:**
# 1. Set up workspace directories and copy ancillary/model files.
# 2. Read `allobs.dat` and write the instruction file with one line per observation.
# 3. Copy the forward run script and export parameters to JSON.
# 4. (Optional) Run the model and verify that the instruction file, model output,
#    and observation file are consistent.
#
# ---
#
# ## Notes on matching `modelobs.dat` to `allobs.dat`
#
# The instruction file directives are `l1 w !obsname!` — PEST++ advances one
# line and reads the value token, so pairing is **positional**: `modelobs.dat`
# must list observations in the *same order and count* as `allobs.dat`. The
# `obsname` text in `modelobs.dat` is only used by the `check_ins_and_outs`
# validation below, not by PEST++ itself.
#
# Two things this notebook sets up to keep that alignment working:
#
# - **Calibration-gage list is shipped to `ancillary/`.** The Workspace Setup
#   copies `npoigages_cal_list_<subdomain>.xlsx` (which flags calibration gages
#   via `ohm_cal == "yes"`) into `ancillary/`, so the remote `forward_run` can
#   subset and order its `seg_outflow` to the exact same gages notebook 01 used
#   for the streamflow observations.
# - **`streamflow_5day` EFC suffix is stripped in the consistency check.** The
#   observation names include an `_<efc>_<high_low>` suffix classified from the
#   observed hydrograph; the model output omits it. `check_ins_and_outs` reduces
#   `streamflow_5day_<efc>_<hl>:...` to `streamflow_5day:...` before comparing so
#   the two reconcile.

# %% [markdown]
# ## Workspace Setup
# Create the `pestpp_ies/` directory structure and copy ancillary configuration
# files and model input files needed for remote PEST++ runs. This includes the
# calibration-gage list spreadsheet, which is shipped to `ancillary/` so the
# remote forward run can select the same streamflow calibration gages.

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

# Copy the calibration-gage list spreadsheet into ancillary/ so the remote
# forward_run can read the same cal_gages used to build the streamflow
# observations in notebook 01. (The forward run subsets/orders its seg_outflow
# to these gages so modelobs.dat aligns positionally with allobs.dat.)
_cal_list_src = (
    config["model_dir"] / "metadata" / f"npoigages_cal_list_{config['subdomain']}.xlsx"
)
if not _cal_list_src.exists():
    _cal_list_src = (
        config["model_dir"]
        / "metadata"
        / f"npoigages_cal_list_{config['subdomain']}.xls"
    )
if _cal_list_src.exists():
    shutil.copy2(_cal_list_src, ancillary_dir / _cal_list_src.name)
else:
    print(f"Warning: calibration-gage spreadsheet not found at {_cal_list_src}")

# %% [markdown]
# ## Write the Instruction File (`modelobs.dat.ins`)
# Read observation names from `allobs.dat` and write the PEST++ instruction file.
# Each observation gets a `l1 w !obsname!` directive that tells PEST++ to read
# whitespace-delimited values line by line from `modelobs.dat`.

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
# ## Prepare the Forward Run Script
# The forward run script (`forward_run.py`) is the executable that PEST++ calls
# for each parameter realization. It runs pywatershed with updated parameters and
# post-processes output into the `modelobs.dat` format that the instruction file expects.

# %%
nhm_assist_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]

# %%
# Instead of the code below that is commented out,  we will read in the .py version of
# both scripts combined from the notebook_scripts folder
# named "Create_model_run_and_post_processing_script.py"
# Copy it it the pest_dir and rename "forward_run.py"
# with open(os.path.join(pestpp_model_dir, "forward_run.py"), "w") as ofp:
#     [ofp.write(f"{line}\n") for line in imports + runbiz]

nhm_assist_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]
source = nhm_assist_dir / "src/workflow_templates/pest" / "forward_run_gfv2.py"
destination = pestpp_model_dir / "forward_run_gfv2.py"
shutil.copy2(source, destination)

# convert the
param_file = config["model_dir"] / "myparam.param"
parameters_json_file = pestpp_model_dir / "parameters.json"

params = pws.parameters.PrmsParameters.load(param_file)
params.parameters_to_json(parameters_json_file)
# params = pws.parameters.PrmsParameters.load_from_json(parameters_json_file)

# %%
print(config["model_dir"], pestpp_model_dir)

# %% [markdown]
# ## Run the Forward Model (Optional)
# Execute `forward_run.py` to produce `modelobs.dat`. This step is optional during
# setup but required before the consistency check below can pass.

# %%
cwd = os.getcwd()
# %cd "{pestpp_model_dir}"
# !python forward_run_gfv2.py
# %cd "{cwd}"

# %% [markdown]
# ## Verify Instruction File Consistency
# Check that the instruction file (`modelobs.dat.ins`), model output (`modelobs.dat`),
# and observation file (`allobs.dat`) are aligned:
# - Same number of observations
# - Same observation names in the same order
# - No duplicate observation names
#
# If a mismatch is found, the error message identifies which names are missing
# or out of order.
#
# **Streamflow handling.** Before comparing, the check reduces
# `streamflow_5day_<efc>_<high_low>:...` roots to `streamflow_5day:...` so the
# observation names (which carry the observed-hydrograph EFC/high_low suffix)
# reconcile with the model output (which omits it).
#
# **Common count mismatches to watch for** (each observation family should have
# the same count on both sides): a duplicated write block in notebook 01, or a
# `streamflow_5day_bins.csv` that was not derived from the same calibration-year
# 5-day object that produced the `streamflow_5day` observations.

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

    mask = ins["obsval_root"].str.contains("streamflow_5day_", na=False)
    # The observation names carry an EFC/high_low suffix, e.g.
    # "streamflow_5day_4_2:2011_1_5:08063048". The model output (modelobs.dat)
    # writes the same 5-day values without the EFC suffix, so strip it here so
    # the root reduces to "streamflow_5day:2011_1_5:08063048" for the comparison.
    ins.loc[mask, "obsval_root"] = (
        "streamflow_5day:" + ins.loc[mask, "obsval_root"].str.split(":", n=1).str[1]
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
