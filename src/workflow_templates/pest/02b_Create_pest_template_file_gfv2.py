# %%
import os
import sys
import pathlib as pl
import warnings
import pandas as pd
import xarray as xr
import numpy as np
import shutil
import datetime

import jupyter_black

jupyter_black.load()
import io

from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

from rich.console import Console
from rich import pretty

warnings.filterwarnings("ignore")
pretty.install()
con = Console()


# One template set serves every workflow, so the root cannot be hardcoded the
# way the per-workflow copies did (`resolve_repo_root() / "nhf_assist"`). The
# workflow is inferred from where this notebook runs: nhm and pest use the repo
# root, nhf uses <repo>/nhf_assist. Built on resolve_repo_root, so it honours
# PIXI_PROJECT_ROOT and works for non-editable installs too.
from assist.workspace.bridge import resolve_workflow_root

root_dir = resolve_workflow_root(cwd=os.getcwd())

from assist.workspace.bridge import resolve_project_notebook_context
from assist.workspace.service import get_active_model_root

project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
if project_context:
    active_model_root = get_active_model_root(
        project_context["workspace_root"], project_context["project_root"].name
    )
    config_root = active_model_root / "config"
else:
    active_model_root = None
    config_root = root_dir

print(root_dir)

from assist.common.hydrofabric import (
    make_hf_map_elements,
    evaluate_and_fix_nhru_geometry,
)
from assist.common.map_template import make_hf_map, make_geo_map, make_geo_legend

from assist.common.assist_utilities import (
    load_subdomain_config,
    find_missing_gage_info,
    fetch_non_ref_npoigages_info,
    fetch_ref_npoigages_info,
)

from assist.pest.pest_utils import (
    pars_to_tpl_entries_2,
    check_par_bounds,
    write_to_json_tpl,
)

from assist.common import efc

config = load_subdomain_config(config_root)
# con.print(config)


# sys.path.insert(0, r"D:\nhm-assist\pestpp_ies_calibration\dependencies")
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

if not (root_dir / "pestpp_ies_calibration").exists():
    (root_dir / "pestpp_ies_calibration").mkdir()
pestpp_dep_dir = root_dir / "data_dependencies" / "pestpp_ies_dependencies"

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
    source = pestpp_dep_dir / f"ancillary_template/{file}"
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
parameters_json_file = pestpp_model_dir / "parameters.json"

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
    "hru_deplcrv",
    "jh_coef",
    "mann_n",
    "potet_sublim",
    "rad_trncf",
    "radmax",
    "rain_cbh_adj",
    "slowcoef_sq",
    "smidx_coef",
    "snarea_thresh",
    "snowinfil_max",
    "snow_cbh_adj",
    "soil2gw_max",
    "soil_moist_max",
    "soil_rechr_max_frac",
    "ssr2gw_exp",
    "ssr2gw_rate",
    "tmax_allrain_offset",
    "tmax_allsnow",
    # "tmax_cbh_adj",
    # "tmin_cbh_adj",
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
# #### Bound overrides for snow parameters
#
# These replace the Percent / Range bounds above for three snow parameters. The
# values come from forward-run tests on the SandyRiver prior (Nov 2026):
#
# - **`tmax_allsnow`: `parval1` +/- `offset` (6 F).** The Range method gave
#   -10 to 40 F, so the prior spread was about +/-12.5 F. Raising it 4 F at a
#   mid-elevation HRU turned late-melting snow into a 183-inch pack, and with
#   the wide prior 31% of mid-elevation HRU samples kept snow through
#   August-September (19% with +/- 6 F, 17% with +/- 4 F, 10% at the starting
#   values). The wide prior also inflated peak SWE (median 1.19 x target).
# - **`snarea_thresh`: lower bound `lower_factor` x `parval1` (0.5).**
# - **`rad_trncf`: upper bound `upper_factor` x `parval1` (1.5).**
#   With the Percent method (+/- 20%) neither could reach values that let
#   HRU 7304 melt out on time. Melt-out matched the observations only when
#   `snarea_thresh` x0.5, `rad_trncf` x1.5, `cecn_coef` x2 and depletion curve 4
#   were combined (Aug-Sep SWE 2.98 -> 0.20 in, peak unchanged). The other
#   bound of each keeps its Percent value.
#
# Every override is clipped to the physical limits in `par_cal_bounds_use.csv`
# (`par_lower_bound`, `par_upper_bound`). `BOUND_OVERRIDE_HRUS = None` applies
# them to every HRU; a list of `nhm_id` values limits them to those HRUs. Set
# `BOUND_OVERRIDES = {}` to keep the Percent / Range bounds. Notebook 03 keeps
# `tmax_allsnow` untransformed (no log), since its lower bound is now positive.

# %%
BOUND_OVERRIDES = {
    "tmax_allsnow": {"offset": 6.0},  # parval1 +/- 6 F
    "snarea_thresh": {"lower_factor": 0.5},  # lower bound 0.5 x parval1
    "rad_trncf": {"upper_factor": 1.5},  # upper bound 1.5 x parval1
}
BOUND_OVERRIDE_HRUS = None  # None = all HRUs, or e.g. [7304, 7303, 11843]

for _p, _rule in BOUND_OVERRIDES.items():
    _sel = par_starting_vals.parname.str.startswith(_p + ":")
    if BOUND_OVERRIDE_HRUS is not None:
        _hrus = {f"hru_{h}" for h in BOUND_OVERRIDE_HRUS}
        _sel &= par_starting_vals.parname.str.split(":").str[1].isin(_hrus)
    if not _sel.any():
        print(f"Bound override: no {_p} parameters selected, skipped")
        continue
    _v = par_starting_vals.loc[_sel, "parval1"].astype(float)
    _lo = par_starting_vals.loc[_sel, "parlbnd"].astype(float)
    _hi = par_starting_vals.loc[_sel, "parubnd"].astype(float)
    if "offset" in _rule:
        _lo, _hi = _v - _rule["offset"], _v + _rule["offset"]
    if "lower_factor" in _rule:
        _lo = _v * _rule["lower_factor"]
    if "upper_factor" in _rule:
        _hi = _v * _rule["upper_factor"]
    # Clip only the side(s) this rule sets to the physical limits, and never let a
    # bound cross parval1 (some starting values lie outside the csv limits, e.g.
    # snarea_thresh above 50 in at glacier HRUs; their other bound is left as is).
    _plo, _phi = float(bnds.loc[_p, "par_lower_bound"]), float(
        bnds.loc[_p, "par_upper_bound"]
    )
    if "offset" in _rule or "lower_factor" in _rule:
        _lo = _lo.clip(lower=_plo, upper=_phi)
    if "offset" in _rule or "upper_factor" in _rule:
        _hi = _hi.clip(lower=_plo, upper=_phi)
    _lo, _hi = np.minimum(_lo, _v), np.maximum(_hi, _v)
    par_starting_vals.loc[_sel, "parlbnd"] = _lo
    par_starting_vals.loc[_sel, "parubnd"] = _hi
    _bad = int((_lo >= _hi).sum())
    print(
        f"Bound override {_p} {_rule}: {int(_sel.sum())} parameters | "
        f"lower {_lo.min():.4g}-{_lo.max():.4g} | upper {_hi.min():.4g}-{_hi.max():.4g}"
        + (f" | WARNING: {_bad} with lower >= upper" if _bad else "")
    )


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
