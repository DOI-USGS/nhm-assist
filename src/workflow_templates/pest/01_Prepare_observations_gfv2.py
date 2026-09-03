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
# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"


from assist.nhf.nhm_hydrofabric_v2 import (
    make_hf_map_elements,
    evaluate_and_fix_nhru_geometry,
)
from assist.nhf.map_template_v2 import make_hf_map, make_geo_map, make_geo_legend

from assist.nhf.nhm_assist_utilities_v2 import (
    load_subdomain_config,
    find_missing_gage_info,
    fetch_non_ref_npoigages_info,
    fetch_ref_npoigages_info,
)

from assist.nhf import efc

# import topojson


config = load_subdomain_config(root_dir)
# con.print(config)


import pandas as pd
import xarray as xr
import numpy as np
import datetime
import shutil

from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.


# from assist.workspace.bridge import resolve_project_notebook_context
# from assist.workspace.service import get_active_model_root

# project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
# if project_context:
#     active_model_root = get_active_model_root(
#         project_context["workspace_root"], project_context["project_root"].name
#     )
#     config_root = active_model_root / "config"
# else:
#     config_root = root_dir

from dotenv import load_dotenv

# Use home directory for Nebari, otherwise use repo root_dir
if "NEBARI_CONDA_STORE_SERVER_SERVICE_HOST" in os.environ:
    dotenv_path = pl.Path.home() / ".env"
else:
    dotenv_path = root_dir / ".env"

load_dotenv(dotenv_path=dotenv_path)

############################################


# from assist.nhm.nhm_assist_utilities import load_subdomain_config
# from assist.nhm import efc

config = load_subdomain_config(root_dir)

# import sys
# import os
# import pathlib as pl
# import warnings

# import pandas as pd
# import xarray as xr
# import numpy as np
# import datetime

# import shutil

# warnings.filterwarnings("ignore")
# from rich.console import Console

# con = Console()
# from rich import pretty

# pretty.install()
# import jupyter_black
# from contextlib import redirect_stdout
# import io

# f = io.StringIO()
# with redirect_stdout(f):
#     import pywatershed as pws

# jupyter_black.load()
# # Find and set the "nhm-assist" root directory
# # Find the repo root via the editable-installed `assist` package — robust
# # against sibling clones, cwd quirks, and arbitrary checkout directory names.
# import assist as _assist_pkg

# root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"


# from assist.nhf.nhm_hydrofabric_v2 import (
#     make_hf_map_elements,
#     evaluate_and_fix_nhru_geometry,
# )
# from assist.nhf.map_template_v2 import make_hf_map, make_geo_map, make_geo_legend

# from assist.nhf.nhm_assist_utilities_v2 import (
#     load_subdomain_config,
#     find_missing_gage_info,
#     fetch_non_ref_npoigages_info,
#     fetch_ref_npoigages_info,
# )

# from assist.nhf import efc

# # import topojson


# config = load_subdomain_config(root_dir)
# # con.print(config)

# from dotenv import load_dotenv

# # Use home directory for Nebari, otherwise use repo root_dir
# if "NEBARI_CONDA_STORE_SERVER_SERVICE_HOST" in os.environ:
#     dotenv_path = pl.Path.home() / ".env"
# else:
#     dotenv_path = root_dir / ".env"

# load_dotenv(dotenv_path=dotenv_path)

# ############################################

# import assist as _assist_pkg

# root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]

# from assist.workspace.bridge import resolve_project_notebook_context
# from assist.workspace.service import get_active_model_root

# project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
# if project_context:
#     active_model_root = get_active_model_root(
#         project_context["workspace_root"], project_context["project_root"].name
#     )
#     config_root = active_model_root / "config"
# else:
#     config_root = root_dir

# from dotenv import load_dotenv

# # Use home directory for Nebari, otherwise use repo root_dir
# if "NEBARI_CONDA_STORE_SERVER_SERVICE_HOST" in os.environ:
#     dotenv_path = pl.Path.home() / ".env"
# else:
#     dotenv_path = root_dir / ".env"

# load_dotenv(dotenv_path=dotenv_path)

# ###########################################################################

# %%
root_dir

# %% [markdown]
# # Prepare Observations for PEST++ IES Parameter Estimation
#
# This notebook consolidates observation datasets into the files required by
# PEST++ iterative ensemble smoother (IES) for model parameter estimation:
#
# **Output files:**
# - `allobs.dat` — Two-column file (observation name, observation value) containing
#   all parameter estimation targets that PEST++ will compare against model output.
# - `allobs_bounds.dat` — Range bounds (min/max) for each observation, used to
#   define the observation uncertainty in the PEST++ control file (notebook 03).
#
# **How PEST++ uses these files:**
# Each line in `allobs.dat` corresponds to the same indexed line in the instruction
# file (`modelobs.dat.ins`) and the model output file (`modelobs.dat`). PEST++ reads
# the instruction file to extract simulated values from model output, then compares
# them against the observed values listed here.
#
# **Workflow steps:**
# 1. Set up the PEST++ workspace directories and copy ancillary files.
# 2. Read HRU-based observation NetCDF files (created by the `Subset_NHM_baselines` notebook).
# 3. Format each observation type (AET, recharge, soil moisture, runoff, snow cover, streamflow)
#    with structured names and write to `allobs.dat`.
# 4. Build the corresponding bounds file for observation uncertainty.
#
# **Observation naming convention:** `<variable>_<timestep>:<time_index>:<spatial_id>`

# %% [markdown]
# ## Workspace Setup
# Create the `pestpp_ies/` directory structure within the model folder. All files
# needed to run PEST++ IES will be organized here:
# - `observation_data/` — source NetCDF observation files
# - `ancillary/` — configuration CSVs (localization, weighting, bounds)
# - `output/` — model output from parameter estimation runs

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

# %%
pws_prcp_input_file = config["model_dir"] / "prcp.nc"
pws_tmin_input_file = config["model_dir"] / "tmin.nc"
pws_tmax_input_file = config["model_dir"] / "tmax.nc"
nhmx_input_file = config["model_dir"] / "cbh.nc"
input_file_path_list = [pws_prcp_input_file, pws_tmin_input_file, pws_tmax_input_file]

for input_file_path in input_file_path_list:
    if not input_file_path.exists():
        con.print(
            "One or more of the pywatershed input files does not exist. All input file will be rewritten from the cbh.nc file."
        )
        with xr.open_dataset(
            nhmx_input_file
        ) as input:  # This is the input file given with NHMx
            model_input = input.swap_dims({"nhru": "nhm_id"}).drop("nhru")
            prcp = getattr(model_input, "prcp")
            tmin = getattr(model_input, "tmin")
            tmax = getattr(model_input, "tmax")
        prcp.to_netcdf(pws_prcp_input_file)
        tmin.to_netcdf(pws_tmin_input_file)
        tmax.to_netcdf(pws_tmax_input_file)
        con.print(
            f"The pywatershed input file [bold]{pl.Path(input_file_path).stem}[/bold] was missing. All pywatershed input files were created in {config['model_dir']} from the cbh.nc file."
        )
    else:
        pass
con.print(
    f"[bold][green]Optional:[/bold][/green] To recreate pywatershed input files in {config['model_dir']}, delete [bold]prcp.nc[/bold], [bold]tmin.nc[/bold], and [bold]tmax.nc[/bold] files and re-run this notebook."
)

# %%
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
all_nc_files = sorted([i for i in (obsdir).glob("*.nc")])  # Read in the files to check
# all_nc_files #Checks all the subset observation files from the CONUS NHM outputs

# %%
# from netCDF4 import Dataset

# all_nc_files = sorted(obsdir.glob("*.nc"))

# for path in all_nc_files:
#     print(f"\nFile: {path.name}")
#     with Dataset(path) as nc:
#         for vname, var in nc.variables.items():
#             dims = var.dimensions  # tuple of dimension names
#             shape = var.shape  # tuple of sizes along dims
#             print(f"  {vname}: dims={dims}, shape={shape}")

# %%
for path in all_nc_files:
    ds = xr.open_dataset(path)
    if path.name == "AET_mean_monthly.nc":
        months = ds["month"].values

    else:
        # adjust 'time' to your actual coordinate name if different
        time = ds["time"]
        # If time is already decoded as datetimes
        t_start = pd.to_datetime(time.min().values)
        t_end = pd.to_datetime(time.max().values)

    if path.name == "AET_mean_monthly.nc":
        print(f"{path.name}: months = {months}")
    else:
        print(
            f"{path.name}: {t_start.strftime('%Y/%m/%d')}  ->  {t_end.strftime('%Y/%m/%d')}"
        )

    ds.close()

# %%
# Make a file to hold the consolidated results used for the pest++ .ins file
ofp = open(
    pestpp_model_dir / "allobs.dat", "w"
)  # the 'w' will delete any existing file here and recreate; 'a' appends

# Make a file to hold the consolidated results used for the pest++ range bounds
# in the pest observation file (notebook 3)
ofp = open(pestpp_model_dir / "allobs_bounds.dat", "w")

# %%

# %% [markdown]
# ## Format HRU Observations
# The following cells read each observation NetCDF file, construct structured
# observation names, compute the midpoint between min/max bounds as the target
# value, and append to `allobs.dat`. Bounds are tracked in `obs_bounds_df` for
# later export.
#
# ### Actual Evapotranspiration (AET) — Monthly
# Values are in inches/day (daily average rate for the month).

# %%
cdat = xr.open_dataset(obsdir / "AET_monthly.nc")
# set up the indices in sequence
cdat

# %%
cdat = xr.open_dataset(obsdir / "AET_monthly.nc")
# set up the indices in sequence
inds = [
    f"actet_mon:{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhm_id"]
]

# Write the observations to the observations.dat file for use in creating the instruction file
actet_mon = (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(actet_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    ofp.write("obsname    obsval\n")  # writing a header for the file
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]


obsvals_max = np.ravel(
    cdat.upper_bound, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.lower_bound, order="C"
)  # flattens the 2D array to a 1D array
obs_bounds_df = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

# %%
obs_bounds_df

# %% [markdown]
# ### AET — Mean Monthly (climatological average by month)

# %%
cdat = xr.open_dataset(obsdir / "AET_mean_monthly.nc")
# set up the indices in sequence
inds = [
    f"actet_mean_mon:{i}:{j}"
    for i in cdat.indexes["month"]
    for j in cdat.indexes["nhm_id"]
]

actet_mean_mon = (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(actet_mean_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]


obsvals_max = np.ravel(
    cdat.upper_bound, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.lower_bound, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %%
# aet_mean_obs.sel(month= 1)

# %% [markdown]
# ### Recharge — Annual

# %%
cdat = xr.open_dataset(obsdir / "RCH_annual.nc")
# set up the indices in sequence
inds = [
    f"recharge_ann:{i.year}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhm_id"]
]

recharge_ann = (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(recharge_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

obsvals_max = np.ravel(
    cdat.upper_bound, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.lower_bound, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %% [markdown]
# ### Soil Moisture — Monthly

# %%
cdat = xr.open_dataset(obsdir / "Soil_Moisture_monthly.nc")
# set up the indices in sequence
inds = [
    f"soil_moist_mon:{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhm_id"]
]

soil_moist_mon = (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(soil_moist_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]


obsvals_max = np.ravel(
    cdat.upper_bound, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.lower_bound, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %% [markdown]
# ### Soil Moisture — Annual

# %%
cdat = xr.open_dataset(obsdir / "Soil_Moisture_annual.nc")
# set up the indices in sequence
inds = [
    f"soil_moist_ann:{i.year}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhm_id"]
]

soil_moist_ann = (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(soil_moist_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

obsvals_max = np.ravel(
    cdat.upper_bound, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.lower_bound, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)
obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %% [markdown]
# ### HRU Runoff — Monthly (average daily rate in cfs for each month)

# %%
cdat = xr.open_dataset(obsdir / "hru_streamflow_monthly.nc")
# set up the indices in sequence
inds = [
    f"runoff_mon:{i.year}_{i.month}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhm_id"]
]
runoff_mon = (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(runoff_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

obsvals_max = np.ravel(
    cdat.upper_bound, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.lower_bound, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)
obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %% [markdown]
# ### Snow Water Equivalent (SWE) — 5-day Average
# NaN values are filled with -9999 (a PEST++ no-data sentinel). These
# observations will be zero-weighted in the PEST++ control file where the
# sentinel value appears.

# %%
cdat = xr.open_dataset(obsdir / "SWE_5day_avg.nc")
cdat

# %%
cdat = xr.open_dataset(obsdir / "SWE_5day_avg.nc")
cdat = cdat.fillna(-9999)
# set up the indices in sequence
inds = [
    f"swe_5day:{i.year}_{i.month}_{i.day}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhm_id"]
]
swe_5day = (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(swe_5day, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

obsvals_max = np.ravel(
    cdat.upper_bound, order="C"
)  # flattens the 2D array to a 1D array
obsvals_min = np.ravel(
    cdat.lower_bound, order="C"
)  # flattens the 2D array to a 1D array

obs_bounds_df_new = pd.DataFrame(
    {
        "obsname": inds,
        "less_than": obsvals_max,
        "greater_than": obsvals_min,
    }
)

obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)
cdat.close()

# %%
# Write the bounds_df
obs_bounds_df.to_csv(pestpp_model_dir / "allobs_bounds.dat", index=False)

# %% [markdown]
# ## Format Streamflow Observations
# Streamflow observations are handled separately from HRU observations because
# they are indexed by POI gage ID rather than HRU ID, and include EFC
# (Environmental Flow Component) classifications and hydrograph position (ascending/
# descending limb) as suffixes in the observation name.
#
# Calibration and validation years are split by alternating water years (odd = cal,
# even = val). Mean monthly streamflow is computed separately for each set.
#
# **Prerequisite:** The EFC notebook (notebook 1 in nhm-assist) must be run first
# to create the `sf_efc.nc` file with EFC codes.

# %%
_sf_efc_raw = xr.open_dataset(config["nc_files_dir"] / "sf_efc.nc")
_sf_efc_raw

# %%
# Summary table: for each gage in sf_efc.nc, show the begin/end dates of
# available discharge data, the count of valid (non-NaN) values, the
# number of days with no data in that range, and whether it is a calibration gage.
_sf_efc_raw = xr.open_dataset(config["nc_files_dir"] / "sf_efc.nc")

# Load calibration gage info from the metadata spreadsheet
_metadata_dir = config["model_dir"] / "metadata"
_xls_path = _metadata_dir / f"npoigages_cal_list_{config['subdomain']}.xlsx"
if not _xls_path.exists():
    _xls_path = _metadata_dir / f"npoigages_cal_list_{config['subdomain']}.xls"
if _xls_path.exists():
    _cal_df = pd.read_excel(_xls_path, dtype={"poi_gage_id": str})
    # Ensure poi_gage_id is clean strings
    _cal_df["poi_gage_id"] = _cal_df["poi_gage_id"].str.strip()
    # Build a lookup dict: poi_gage_id -> ohm_cal value
    _cal_lookup = dict(
        zip(
            _cal_df["poi_gage_id"],
            _cal_df["ohm_cal"].astype(str).str.strip().str.lower(),
        )
    )
else:
    _cal_lookup = {}
    print(f"Warning: calibration spreadsheet not found at {_xls_path}")

_summary_rows = []
for poi in _sf_efc_raw.poi_gage_id.values:
    _poi_str = str(poi).strip()
    _discharge = _sf_efc_raw["discharge"].sel(poi_gage_id=poi)
    _valid_mask = _discharge.notnull()
    _valid_times = _discharge.time.where(_valid_mask, drop=True)
    _is_cal = _cal_lookup.get(_poi_str, "no")
    if _valid_times.size == 0:
        _summary_rows.append(
            {
                "poi_gage_id": _poi_str,
                "begin_date": None,
                "end_date": None,
                "n_valid": 0,
                "n_missing": int(_discharge.time.size),
                "calibration_gage": _is_cal,
            }
        )
    else:
        _begin = pd.to_datetime(_valid_times.min().values)
        _end = pd.to_datetime(_valid_times.max().values)
        _n_valid = int(_valid_mask.sum().values)
        _total_days = (_end - _begin).days + 1
        _n_missing = _total_days - _n_valid
        _summary_rows.append(
            {
                "poi_gage_id": _poi_str,
                "begin_date": _begin.strftime("%Y-%m-%d"),
                "end_date": _end.strftime("%Y-%m-%d"),
                "n_valid": _n_valid,
                "n_missing": _n_missing,
                "calibration_gage": _is_cal,
            }
        )

_sf_efc_raw.close()
gage_summary_df = pd.DataFrame(_summary_rows)
gage_summary_df

# %%
cal_gages = list(
    gage_summary_df.loc[gage_summary_df["calibration_gage"] == "yes", "poi_gage_id"]
)
cal_gages

# %%
# These can be tailored for any specific model
seg_outflow_start = "2000-01-01"
seg_outflow_end = "2021-12-31"

# seg_outflow_start = "2011-01-01"  # Note: For ease, the start and end dates must be same as those designated in
# seg_outflow_end = "2022-12-31"  #    "the Create_pest_model_observation_file."

## Set up validation years
start_year = pd.to_datetime(seg_outflow_start).year
end_year = pd.to_datetime(seg_outflow_end).year
streamflow_years = np.array(range(start_year, end_year))

## We will choose even years as validation
val_years = [i for i in streamflow_years if i % 2 == 0]
cal_years = [i for i in streamflow_years if i % 2 != 0]

# read in param file
param_file = config["model_dir"] / "myparam.param"
# parameters_json_file = pestpp_model_dir / "parameters.json"
pardat = pws.parameters.PrmsParameters.load(param_file)
paramfile_poi_gage_id_list = pardat.parameters.get("poi_gage_id").tolist()


cdat = xr.open_dataset(config["nc_files_dir"] / "sf_efc.nc").sel(
    time=slice(seg_outflow_start, seg_outflow_end)
)

cdat = cdat.sel(poi_gage_id=cdat.poi_gage_id.isin(cal_gages))
cdat = cdat.reindex(poi_gage_id=cal_gages)

cdat = cdat[["discharge", "efc", "high_low"]]

# %% [markdown]
# ## Make 5-day averages for streamflow values
#
# Non-overlapping 5-day resampling (`resample(time="5D")`) is applied to the
# daily streamflow observations, matching the same averaging approach used for
# SWE in the `00_Subset_NHM_baselines_gfv2` notebook. Each 5-day bin produces
# a single value; the 2 days before and 2 days after are consumed into the bin
# (not retained as separate timesteps).
#
# - **Discharge:** The mean of each 5-day bin. If any day in the bin has a
#   NaN, the bin result is NaN (skipna=False).
# - **EFC and high_low:** The most frequent (mode) classification value in
#   each 5-day bin.
# - **NaN handling:** Any 5-day bin containing a NaN in discharge is dropped
#   from all three variables (discharge, efc, high_low) so they stay aligned.

# %%
# Discharge: 5-day resample mean — do not skip NaN so incomplete bins produce NaN
cdat_5day_discharge = cdat["discharge"].resample(time="5D").mean(skipna=False)

# Create a mask of valid (non-NaN) 5-day discharge averages
_valid_mask = cdat_5day_discharge.notnull()


# efc and high_low: 5-day resample mode (most frequent value in each bin)
def _resample_mode(da):
    """Resample a DataArray to 5-day bins using the mode (most frequent value)."""
    df = da.to_dataframe().unstack("poi_gage_id")
    df.columns = df.columns.droplevel(0)

    def _mode_agg(group):
        return group.apply(
            lambda col: col.mode().iloc[0] if not col.mode().empty else np.nan
        )

    resampled = df.resample("5D").apply(_mode_agg)

    # Convert back to xarray
    stacked = resampled.stack(dropna=False)
    stacked.index.names = ["time", "poi_gage_id"]
    return stacked.to_xarray()


_efc_5day_da = _resample_mode(cdat["efc"])
_hl_5day_da = _resample_mode(cdat["high_low"])

# Combine into a single dataset and apply the discharge validity mask so that
# any 5-day bin containing a NaN in discharge is dropped from all variables.
cdat_5day = xr.Dataset(
    {
        "discharge": cdat_5day_discharge,
        "efc": _efc_5day_da,
        "high_low": _hl_5day_da,
    }
)

# Apply the discharge validity mask to efc and high_low
cdat_5day["efc"] = cdat_5day["efc"].where(_valid_mask)
cdat_5day["high_low"] = cdat_5day["high_low"].where(_valid_mask)

# Drop time steps where any gage has NaN (incomplete 5-day bins)
cdat_5day = cdat_5day.dropna(dim="time", how="any")

# %%
moo = cdat.discharge.to_dataframe()
# moo.loc[moo['discharge'] <0]
obs_poi_list = moo.index.get_level_values(0).unique().tolist()

# %%
# Creates a dataframe time series of monthly values (average daily rate for the month)
cdat_monthly = cdat.resample(time="ME").mean(skipna=True)
cdat_monthly

# %%
# Creates a dataframe time series of monthly values (average daily rate for the month)
cdat_monthly = cdat.resample(time="ME").mean(skipna=True)
cdat_monthly["year"] = [pd.to_datetime(i).year for i in cdat_monthly.time.values]

# %%
# Creates dataframe time series of mean monthly (mean of all jan, feb, mar....) for parameter estimation and validation
# years separately
# cdat_mean_monthly = cdat_monthly.groupby('time.month').mean(skipna=True)

# pro-tip - gotta use sel with two conditions, but .values breaks the connection to the index using
#           a boolean based on one condition to subset another
cdat_monthly_val = cdat_monthly.sel(
    time=cdat_monthly.year.isin(val_years).values,
    year=cdat_monthly.year.isin(val_years),
)
cdat_monthly_cal = cdat_monthly.sel(
    time=cdat_monthly.year.isin(cal_years).values,
    year=cdat_monthly.year.isin(cal_years),
)

cdat_mean_monthly_cal = cdat_monthly_cal.groupby("time.month").mean(skipna=True)
cdat_mean_monthly_val = cdat_monthly_val.groupby("time.month").mean(skipna=True)

# %%
cdat_mean_monthly_cal = cdat_mean_monthly_cal.fillna(-9999)
cdat_mean_monthly_val = cdat_mean_monthly_val.fillna(-9999)
cdat_monthly = cdat_monthly.fillna(-9999)
cdat_5day = cdat_5day.fillna(-9999)

# %%
# streamflow_daily is followed by a suffix: "efc"_"high_low" integers
# efc [1, 2, 3, 4, 5] are ['Large flood', 'Small flood', 'High flow pulse', 'Low flow', 'Extreme low flow']
# high_low [1, 2, 3] are ['Low flow', 'Ascending limb', 'Descending limb']

# set up the indices in sequence
inds = [
    f'_{int(cdat_5day["efc"].sel(poi_gage_id=j, time=i).item())}_{int(cdat_5day["high_low"].sel(poi_gage_id=j, time=i).item())}:{i.year}_{i.month}_{i.day}:{j}'
    for j in cdat_5day.indexes["poi_gage_id"]
    for i in cdat_5day.indexes["time"]
]

# get the variable names
# dvs = list(cdat_5day.keys())

varvals = np.ravel(
    cdat_5day["discharge"], order="C"
)  # flattens the 2D array to a 1D array

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_daily{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# Now write to the pest obs file
inds = [
    f"{i.year}_{i.month}:{j}"
    for j in cdat_monthly.indexes["poi_gage_id"]
    for i in cdat_monthly.indexes["time"]
]  # set up the indices in sequence
varvals = np.ravel(
    cdat_monthly["discharge"], order="F"
)  # flattens the 2D array to a 1D array--just playing

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_mon:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
inds = [
    f"{i}:{j}"
    for j in cdat_mean_monthly_cal.indexes["poi_gage_id"]
    for i in cdat_mean_monthly_cal.indexes["month"]
]
varvals = np.ravel(
    cdat_mean_monthly_cal["discharge"], order="F"
)  # flattens the 2D array to a 1D array

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_mean_mon_cal:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
inds = [
    f"{i}:{j}"
    for j in cdat_mean_monthly_val.indexes["poi_gage_id"]
    for i in cdat_mean_monthly_val.indexes["month"]
]
varvals = np.ravel(
    cdat_mean_monthly_val["discharge"], order="F"
)  # flattens the 2D array to a 1D array

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_mean_mon_val:{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
