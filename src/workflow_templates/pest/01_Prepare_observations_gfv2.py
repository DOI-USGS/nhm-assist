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

# %%
config["model_dir"]

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
#
# ---
#
# ## Key conventions (must stay consistent with the forward run)
#
# The model side (`forward_run_gfv2`) writes `modelobs.dat` and must reproduce
# the observations here **line-for-line, in the same order**, because PEST++
# pairs simulated and observed values *positionally* (the instruction file reads
# by line, not by matching names). Keep the following aligned between this
# notebook and the forward run:
#
# - **Spatial IDs are the national `nhm_id`.** HRU targets are keyed by the
#   parent national `nhm_id`. Note the pywatershed param file stores the parent's
#   *local* `hru_id` under the name `nhm_id`, so the forward run relabels its HRU
#   axis via a shipped crosswalk before writing obs names.
# - **Calibration/validation split.** HRU targets (AET, recharge, soil moisture,
#   runoff, SWE) use odd years = calibration, even years = validation, over each
#   variable's own period. Streamflow uses the same odd/even rule but note its
#   year list is built with `range(start, end)` (end-year exclusive).
# - **Normalization is per-HRU.** Recharge and soil-moisture targets are
#   normalized 0–1 per HRU (soil-moisture mean-monthly is per calendar month);
#   the forward run mirrors this exactly rather than a global min/max.
# - **`-9999` is the PEST++ no-data sentinel** used for missing values (SWE,
#   streamflow); these observations are zero-weighted downstream.
# - **Files shipped to `ancillary/` for the remote forward run:**
#   `npoigages_cal_list_<subdomain>.xlsx` (copied in notebook 02) selects the
#   calibration gages, and `streamflow_5day_bins.csv` (written below) records the
#   surviving 5-day streamflow bins so the forward run emits values for exactly
#   those bins.
# - **EFC/high_low suffix.** `streamflow_5day` observation names carry an
#   `_<efc>_<high_low>` suffix classified from the *observed* hydrograph. The
#   forward run omits it (the model has no EFC classification); notebook 02's
#   consistency check strips the suffix so the two still align.

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
# all_nc_files  # Checks all the subset observation files from the CONUS NHM outputs

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
    if path.name in ("AET_mean_monthly.nc", "Soil_Moisture_mean_monthly.nc"):
        months = ds["month"].values
        print(f"{path.name}: months = {months}")

    else:
        # adjust 'time' to your actual coordinate name if different
        time = ds["time"]
        # If time is already decoded as datetimes
        t_start = pd.to_datetime(time.min().values)
        t_end = pd.to_datetime(time.max().values)
        print(
            f"{path.name}: {t_start.strftime('%Y/%m/%d')}  ->  {t_end.strftime('%Y/%m/%d')}"
        )

    ds.close()

# %%
# Make a file to hold the consolidated results used for the pest++ .ins file
ofp = open(
    pestpp_model_dir / "allobs.dat", "w"
)  # the 'w' will delete any existing file here and recreate; 'a' appends

# # !Commenting out bounds aspects of the notebounds.
# # Make a file to hold the consolidated results used for the pest++ range bounds
# # in the pest observation file (notebook 3)
# ofp = open(pestpp_model_dir / "allobs_bounds.dat", "w")

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
# # ! We are not using monthly for now. Starting with only AET mean_monthly targets for "General" calibration.
# cdat = xr.open_dataset(obsdir / "AET_monthly.nc")
# # set up the indices in sequence
# inds = [
#     f"actet_mon:{i.year}_{i.month}:{j}"
#     for i in cdat.indexes["time"]
#     for j in cdat.indexes["nhm_id"]
# ]

# # Write the observations to the observations.dat file for use in creating the instruction file
# _actet_mon = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
# varvals = np.ravel(_actet_mon, order="C")  # flattens the 2D array to a 1D array
# with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
#     ofp.write("obsname    obsval\n")  # writing a header for the file
#     [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]
# _______________________________________________________________________________________________________________
# # ! we don't needs this anymore
# obsvals_max = np.ravel(
#     cdat.upper_bound, order="C"
# )  # flattens the 2D array to a 1D array
# obsvals_min = np.ravel(
#     cdat.lower_bound, order="C"
# )  # flattens the 2D array to a 1D array
# obs_bounds_df = pd.DataFrame(
#     {
#         "obsname": inds,
#         "less_than": obsvals_max,
#         "greater_than": obsvals_min,
#     }
# )

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

actet_mean_mon = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(actet_mean_mon, order="C")  # flattens the 2D array to a 1D array

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    ofp.write("obsname    obsval\n")  # writing a header for the file
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]


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

recharge_ann = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(recharge_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

# obsvals_max = np.ravel(
#     cdat.upper_bound, order="C"
# )  # flattens the 2D array to a 1D array
# obsvals_min = np.ravel(
#     cdat.lower_bound, order="C"
# )  # flattens the 2D array to a 1D array

# obs_bounds_df_new = pd.DataFrame(
#     {
#         "obsname": inds,
#         "less_than": obsvals_max,
#         "greater_than": obsvals_min,
#     }
# )

# obs_bounds_df = pd.concat([obs_bounds_df, obs_bounds_df_new], ignore_index=True)

# %% [markdown]
# ### Soil Moisture — Monthly

# %%
# cdat = xr.open_dataset(obsdir / "Soil_Moisture_monthly.nc")
# # set up the indices in sequence
# inds = [
#     f"soil_moist_mon:{i.year}_{i.month}:{j}"
#     for i in cdat.indexes["time"]
#     for j in cdat.indexes["nhm_id"]
# ]

# soil_moist_mon = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
# varvals = np.ravel(soil_moist_mon, order="C")  # flattens the 2D array to a 1D array
# with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
#     [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

# %% [markdown]
# ### Soil Moisture — Mean Monthly

# %%
cdat = xr.open_dataset(obsdir / "Soil_Moisture_mean_monthly.nc")
# set up the indices in sequence
inds = [
    f"soil_moist_mean_mon:{i}:{j}"
    for i in cdat.indexes["month"]
    for j in cdat.indexes["nhm_id"]
]

soil_moist_mean_mon = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(
    soil_moist_mean_mon, order="C"
)  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

# %% [markdown]
# #### Plot Soil Moisture — Monthly ensemble members and statistics by HRU
# Plots the ensemble members (MERRA-2, NLDAS MOSAIC, NLDAS NOAH), the ensemble
# mean, and ±1 standard deviation shading for four HRUs from the monthly soil
# moisture dataset. The four HRUs are chosen automatically from the `nhm_id`
# values present in this subdomain (edit `hru_plot_sm` to pick specific HRUs).

# %% jupyter={"source_hidden": true}
# import plotly.graph_objects as go
# from plotly.subplots import make_subplots

# # Re-open the monthly soil moisture dataset for plotting (kept self-contained)
# sm_mon_out_ds = xr.open_dataset(obsdir / "Soil_Moisture_monthly.nc")

# # Pick four HRUs to plot. Defaults to the first four nhm_id values present in
# # this subdomain so the plot works regardless of which HRUs exist. Replace the
# # values below with specific nhm_id integers if you want particular HRUs.
# _sm_hru_ids = sm_mon_out_ds["nhm_id"].values[:4]
# hru_plot_sm = {
#     "upper_left": int(_sm_hru_ids[0]),
#     "upper_right": int(_sm_hru_ids[1]),
#     "lower_left": int(_sm_hru_ids[2]),
#     "lower_right": int(_sm_hru_ids[3]),
# }
# positions_sm = {
#     "upper_left": (1, 1),
#     "upper_right": (1, 2),
#     "lower_left": (2, 1),
#     "lower_right": (2, 2),
# }

# fig_sm = make_subplots(
#     rows=2,
#     cols=2,
#     shared_xaxes=True,
#     vertical_spacing=0.10,
#     horizontal_spacing=0.06,
#     subplot_titles=[
#         f"nhm_id {hru_plot_sm['upper_left']}",
#         f"nhm_id {hru_plot_sm['upper_right']}",
#         f"nhm_id {hru_plot_sm['lower_left']}",
#         f"nhm_id {hru_plot_sm['lower_right']}",
#     ],
# )

# for panel, hru_id in hru_plot_sm.items():
#     row, col = positions_sm[panel]
#     show_legend = panel == "upper_left"
#     time_vals = sm_mon_out_ds.time.values
#     mean_vals = sm_mon_out_ds["ensemble_mean"].sel(nhm_id=hru_id).values
#     std_vals = sm_mon_out_ds["ensemble_std"].sel(nhm_id=hru_id).values

#     # +/- 1 std shading
#     fig_sm.add_trace(
#         go.Scatter(
#             x=time_vals,
#             y=mean_vals + std_vals,
#             mode="lines",
#             line=dict(width=0),
#             showlegend=False,
#         ),
#         row=row,
#         col=col,
#     )
#     fig_sm.add_trace(
#         go.Scatter(
#             x=time_vals,
#             y=mean_vals - std_vals,
#             mode="lines",
#             line=dict(width=0),
#             fill="tonexty",
#             fillcolor="rgba(150,150,150,0.25)",
#             name="±1 std",
#             showlegend=show_legend,
#             legendgroup="std",
#         ),
#         row=row,
#         col=col,
#     )

#     # Individual members
#     fig_sm.add_trace(
#         go.Scatter(
#             x=time_vals,
#             y=sm_mon_out_ds["merra2"].sel(nhm_id=hru_id).values,
#             mode="lines+markers",
#             name="MERRA-2",
#             line=dict(color="blue", width=1),
#             marker=dict(size=4),
#             showlegend=show_legend,
#             legendgroup="merra2",
#         ),
#         row=row,
#         col=col,
#     )
#     fig_sm.add_trace(
#         go.Scatter(
#             x=time_vals,
#             y=sm_mon_out_ds["nldas_mosaic"].sel(nhm_id=hru_id).values,
#             mode="lines+markers",
#             name="NLDAS MOSAIC",
#             line=dict(color="green", width=1),
#             marker=dict(size=4),
#             showlegend=show_legend,
#             legendgroup="mosaic",
#         ),
#         row=row,
#         col=col,
#     )
#     fig_sm.add_trace(
#         go.Scatter(
#             x=time_vals,
#             y=sm_mon_out_ds["nldas_noah"].sel(nhm_id=hru_id).values,
#             mode="lines+markers",
#             name="NLDAS NOAH",
#             line=dict(color="orange", width=1),
#             marker=dict(size=4),
#             showlegend=show_legend,
#             legendgroup="noah",
#         ),
#         row=row,
#         col=col,
#     )

#     # Ensemble mean
#     fig_sm.add_trace(
#         go.Scatter(
#             x=time_vals,
#             y=mean_vals,
#             mode="lines+markers",
#             name="Ensemble Mean",
#             line=dict(color="black", width=2),
#             marker=dict(size=4),
#             showlegend=show_legend,
#             legendgroup="mean",
#         ),
#         row=row,
#         col=col,
#     )

# fig_sm.update_yaxes(title_text="Soil Moisture (normalized)", col=1)
# fig_sm.update_xaxes(title_text="Time", row=2)
# fig_sm.update_layout(
#     height=700,
#     width=1100,
#     title_text="Soil Moisture Monthly Ensemble Members and Statistics by HRU",
#     legend=dict(
#         orientation="h",
#         yanchor="top",
#         y=-0.08,
#         xanchor="center",
#         x=0.5,
#     ),
# )
# sm_mon_out_ds.close()
# fig_sm.show()

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

soil_moist_ann = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(soil_moist_ann, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

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
runoff_mon = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(runoff_mon, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

# %% [markdown]
# ### Snow Water Equivalent (SWE) — Monthly
# NaN values are filled with -9999 (a PEST++ no-data sentinel). These
# observations will be zero-weighted in the PEST++ control file where the
# sentinel value appears.

# %% [markdown]
# #### Plot: mean monthly SWE averaged over 200 random HRUs
# Reads `SWE_monthly.nc`, selects 200 randomly chosen HRUs (fixed seed for
# reproducibility), averages `ensemble_mean` across those HRUs, and then groups
# by calendar month to show the mean seasonal cycle (Jan–Dec).

# %% jupyter={"source_hidden": true}
# import plotly.graph_objects as go

# # Read the monthly SWE dataset (self-contained; independent of the write cell)
# swe_plot_ds = xr.open_dataset(obsdir / "SWE_monthly.nc")
# swe_plot_da = swe_plot_ds["ensemble_mean"]  # dims (time, nhm_id)

# # Select 200 random HRUs (or all of them if fewer than 200 are present)
# _n_hru = swe_plot_da.sizes["nhm_id"]
# _n_pick = min(200, _n_hru)
# _rng = np.random.default_rng(42)
# _rand_idx = np.sort(_rng.choice(_n_hru, size=_n_pick, replace=False))
# swe_rand = swe_plot_da.isel(nhm_id=_rand_idx)

# # Average across the selected HRUs, then mean per calendar month (seasonal cycle)
# swe_hru_mean = swe_rand.mean(dim="nhm_id", skipna=True)
# swe_monthly_climatology = swe_hru_mean.groupby("time.month").mean("time")

# _months = swe_monthly_climatology["month"].values
# _month_labels = [
#     "Jan",
#     "Feb",
#     "Mar",
#     "Apr",
#     "May",
#     "Jun",
#     "Jul",
#     "Aug",
#     "Sep",
#     "Oct",
#     "Nov",
#     "Dec",
# ]

# fig_swe_clim = go.Figure()
# fig_swe_clim.add_trace(
#     go.Scatter(
#         x=[_month_labels[m - 1] for m in _months],
#         y=swe_monthly_climatology.values,
#         mode="lines+markers",
#         line=dict(color="royalblue", width=2),
#         marker=dict(size=7),
#         name="Mean SWE",
#     )
# )
# fig_swe_clim.update_layout(
#     height=450,
#     width=800,
#     title_text=f"Mean Monthly SWE averaged over {_n_pick} random HRUs",
#     xaxis_title="Month",
#     yaxis_title="SWE (inches)",
# )
# fig_swe_clim.show()

# swe_plot_ds.close()

# %% [markdown]
# #### HRUs with mean annual SWE below 0.25 inches
# For each HRU, compute the mean annual SWE (average of `ensemble_mean` across
# all timesteps, NaNs skipped) and list the `nhm_id`s whose mean annual SWE is
# less than 0.25 inches.

# %% jupyter={"source_hidden": true}
# swe_mean_ds = xr.open_dataset(obsdir / "SWE_monthly.nc")

# # Mean annual SWE per HRU: average across the full time series (skip NaNs)
# swe_mean_annual = swe_mean_ds["ensemble_mean"].mean(dim="time", skipna=True)

# # HRUs where the mean annual SWE is below 0.25 inches
# low_swe = swe_mean_annual.where(swe_mean_annual < 0.02, drop=True)
# low_swe_hrus = low_swe["nhm_id"].values.tolist()

# con.print(
#     f"[bold]{len(low_swe_hrus)}[/bold] of {swe_mean_annual.sizes['nhm_id']} HRUs "
#     f"have mean annual SWE < 0.25 inches:"
# )
# con.print(low_swe_hrus)

# swe_mean_ds.close()

# %% [markdown]
# #### Map: HRUs below the SWE threshold
# Map of the HRU polygons from the child hydrofabric
# (`GIS/model_layers.gpkg`, `nhru` layer). HRUs with mean annual SWE < 0.25
# inches are shaded red; the rest are light gray for context.
#
# The child gpkg's `nhm_id` is actually the parent model's local `hru_id`, not
# the national `nhm_id` used by `SWE_monthly.nc`. We use the same crosswalk as
# notebook 00 (child `nhm_id` == parent `hru_id` → parent `nhm_id`) to attach
# each polygon to the correct SWE HRU, rather than matching by centroid.

# %% jupyter={"source_hidden": true}
# import geopandas as gpd
# import folium

# # Crosswalk from the parent hydrofabric: parent hru_id -> parent nhm_id
# # (the national nhm_id used by the SWE target file).
# parent_gpkg = (
#     root_dir
#     / "hydrofabric_domain_data"
#     / "OHM_2026_02_21"
#     / "GIS"
#     / "model_layers.gpkg"
# )
# parent_hru_gdf = gpd.read_file(parent_gpkg, layer="nhru")
# crosswalk = parent_hru_gdf[["nhm_id", "hru_id"]].rename(
#     columns={"nhm_id": "parent_nhm_id", "hru_id": "parent_hru_id"}
# )

# # Child HRU polygons; child nhm_id == parent hru_id -> look up parent nhm_id
# child_gpkg = config["model_dir"] / "GIS" / "model_layers.gpkg"
# hru_polys = gpd.read_file(child_gpkg, layer="nhru").to_crs(epsg=4326)
# hru_polys = hru_polys.merge(
#     crosswalk, left_on="nhm_id", right_on="parent_hru_id", how="left"
# )

# # Attach each HRU's mean annual SWE value and the below-threshold flag
# _swe_mean_lookup = dict(
#     zip(swe_mean_annual["nhm_id"].values, np.round(swe_mean_annual.values, 4))
# )
# hru_polys["mean_annual_swe"] = hru_polys["parent_nhm_id"].map(_swe_mean_lookup)
# hru_polys["swe_below"] = hru_polys["parent_nhm_id"].isin(low_swe_hrus)
# hru_polys["swe_class"] = np.where(
#     hru_polys["swe_below"], "SWE < 0.25 in", "SWE ≥ 0.25 in"
# )

# # Interactive Folium map (same style family as the hydrofabric viz notebook):
# # selectable basemaps, GeoJson HRU layer colored by the threshold flag, hover
# # popups, and a toggleable layer control.
# _bounds = hru_polys.total_bounds  # [minx, miny, maxx, maxy]
# _center = [(_bounds[1] + _bounds[3]) / 2, (_bounds[0] + _bounds[2]) / 2]

# # Start with no default tiles; add the same selectable basemaps as the
# # hydrofabric visualization notebook (USGS Hydro shown by default; USGS Topo,
# # Esri imagery, and OpenTopoMap available from the layer control).
# swe_map = folium.Map(location=_center, zoom_start=9, tiles=None)

# folium.TileLayer(
#     tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSHydroCached/MapServer/tile/{z}/{y}/{x}",
#     attr="USGSHydroCached",
#     name="USGSHydroCached",
# ).add_to(swe_map)
# folium.TileLayer(
#     tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
#     attr="USGS_topo",
#     name="USGS Topography",
#     show=False,
# ).add_to(swe_map)
# folium.TileLayer(
#     tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
#     attr=(
#         "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, "
#         "GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"
#     ),
#     name="Esri_imagery",
#     show=False,
# ).add_to(swe_map)
# folium.TileLayer(
#     tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
#     attr=(
#         'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">'
#         "OpenStreetMap</a> contributors, "
#         '<a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; '
#         '<a href="https://opentopomap.org">OpenTopoMap</a> '
#         '(<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)'
#     ),
#     name="OpenTopoMap",
#     show=False,
# ).add_to(swe_map)


# def _swe_style(feature):
#     below = feature["properties"]["swe_below"]
#     return {
#         "fillColor": "#d62728" if below else "#c7c7c7",
#         "color": "black",
#         "weight": 0.4,
#         "fillOpacity": 0.55 if below else 0.25,
#     }


# def _swe_highlight(feature):
#     return {"weight": 2, "color": "royalblue", "fillOpacity": 0.7}


# folium.GeoJson(
#     hru_polys[
#         [
#             "nhm_id",
#             "parent_nhm_id",
#             "mean_annual_swe",
#             "swe_class",
#             "swe_below",
#             "geometry",
#         ]
#     ],
#     name="HRUs by mean annual SWE",
#     style_function=_swe_style,
#     highlight_function=_swe_highlight,
#     tooltip=folium.GeoJsonTooltip(
#         fields=["parent_nhm_id", "mean_annual_swe", "swe_class"],
#         aliases=["nhm_id", "mean annual SWE (in)", "class"],
#         localize=True,
#     ),
# ).add_to(swe_map)

# # Fit the view to the HRU extent
# swe_map.fit_bounds([[_bounds[1], _bounds[0]], [_bounds[3], _bounds[2]]])

# # Simple HTML legend (red = below threshold, gray = above)
# _n_below = int(hru_polys["swe_below"].sum())
# _n_total = len(hru_polys)
# _legend_html = f"""
# <div style="position: fixed; bottom: 25px; left: 25px; z-index: 9999;
#      background: white; padding: 10px 12px; border: 1px solid #888;
#      border-radius: 4px; font-size: 13px;">
#   <b>Mean annual SWE</b><br>
#   <span style="display:inline-block;width:12px;height:12px;background:#d62728;
#         opacity:0.55;margin-right:6px;"></span>&lt; 0.25 in ({_n_below})<br>
#   <span style="display:inline-block;width:12px;height:12px;background:#c7c7c7;
#         opacity:0.25;margin-right:6px;"></span>&ge; 0.25 in ({_n_total - _n_below})
# </div>
# """
# swe_map.get_root().html.add_child(folium.Element(_legend_html))

# folium.LayerControl(collapsed=False).add_to(swe_map)

# swe_map

# %%
cdat = xr.open_dataset(obsdir / "SWE_monthly.nc")

# %%
cdat

# %%
cdat = xr.open_dataset(obsdir / "SWE_monthly.nc")
cdat = cdat.fillna(-9999)
cdat = cdat.sel(
    time=~cdat["time"].dt.month.isin([6, 7, 8, 9, 10])
)  # drop months July, August, and September
# set up the indices in sequence
inds = [
    f"swe_monthly:{i.year}_{i.month}_{i.day}:{j}"
    for i in cdat.indexes["time"]
    for j in cdat.indexes["nhm_id"]
]
SWE_monthly = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
varvals = np.ravel(SWE_monthly, order="C")  # flattens the 2D array to a 1D array
with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

# cdat.close()

# %% [markdown]
# ### Snow Water Equivalent (SWE) — 5-day Average
# NaN values are filled with -9999 (a PEST++ no-data sentinel). These
# observations will be zero-weighted in the PEST++ control file where the
# sentinel value appears.

# %%
# cdat = xr.open_dataset(obsdir / "SWE_5day_avg.nc")
# cdat = cdat.fillna(-9999)
# cdat = cdat.sel(
#     time=~cdat["time"].dt.month.isin([7, 8, 9])
# )  # drop months July, August, and September
# # set up the indices in sequence
# inds = [
#     f"SWE_5day:{i.year}_{i.month}_{i.day}:{j}"
#     for i in cdat.indexes["time"]
#     for j in cdat.indexes["nhm_id"]
# ]
# SWE_5day = cdat.ensemble_mean  # (cdat.upper_bound + cdat.lower_bound) / 2
# varvals = np.ravel(SWE_5day, order="C")  # flattens the 2D array to a 1D array
# with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
#     [ofp.write(f"{i}          {j}\n") for i, j in zip(inds, varvals, strict=True)]

# cdat.close()

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
seg_outflow_start = "2011-01-01"
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
#
# **Shipping the surviving bins to the forward run.** Because bins are dropped
# based on *observed* data availability, the forward run (which has no observed
# data) cannot reproduce which bins survive. The surviving calibration-year bin
# times are therefore written to `ancillary/streamflow_5day_bins.csv` (below,
# derived from `cdat_5day_cal` so it exactly matches the `streamflow_5day` obs
# written here), and the forward run selects those same bins from its own 5-day
# resampled `seg_outflow`.
#
# **Calibration-only, and why the filtering happens *before* binning.**
# Only calibration (odd) years are written as observations; validation (even)
# years are withheld. Because these are *daily* data being aggregated into 5-day
# bins, the order of filtering and binning matters:
#
# - If we binned the full continuous daily series first and then dropped
#   validation years by bin label, the late-December bins of a calibration year
#   would straddle the Dec→Jan boundary and average in 1–2 days from the
#   following validation year — quietly contaminating those calibration values.
# - Instead we filter the daily series to the calibration years **first**
#   (`cdat_cal_daily`), then resample. With the validation-year days already
#   removed, every 5-day bin can only contain calibration-year days. (The
#   year gap between calibration years is a full year — far larger than a 5-day
#   window — so no bin bridges two different calibration years either.)
#
# The full daily `cdat` is left untouched here so the monthly series and the
# separate validation-year mean-monthly output can still be built from it.

# %%
# Restrict to calibration (odd) years at the DAILY level BEFORE 5-day binning.
# If we resampled the full continuous daily series and filtered afterward by bin
# label, late-December calibration-year bins would straddle Dec->Jan and pull in
# 1-2 days from the following validation (even) year. Masking the daily series
# first guarantees every 5-day calibration value is built only from calibration
# -year days. (cdat itself is left intact for the monthly/validation outputs.)
cdat_cal_daily = cdat.sel(time=cdat["time"].dt.year.isin(cal_years).values)

# Discharge: 5-day resample mean — do not skip NaN so incomplete bins produce NaN
cdat_5day_discharge = cdat_cal_daily["discharge"].resample(time="5D").mean(skipna=False)

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


_efc_5day_da = _resample_mode(cdat_cal_daily["efc"])
_hl_5day_da = _resample_mode(cdat_cal_daily["high_low"])

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
moo = cdat_5day.discharge.to_dataframe()
# moo.loc[moo['discharge'] <0]
obs_poi_list = moo.index.get_level_values(0).unique().tolist()

# %%
obs_poi_list

# %% [markdown]
# ## Make monthly and mean-monthly streamflow values
#
# Two monthly aggregations are built from the daily streamflow (`cdat`):
#
# - **Monthly time series (`cdat_monthly`)** — the average daily discharge
#   within each calendar month, one value per month per gage.
# - **Mean-monthly climatology** — the average of all Januaries, all
#   Februaries, etc. (`groupby("time.month").mean()`), computed **separately**
#   for calibration and validation years (`cdat_mean_monthly_cal` /
#   `cdat_mean_monthly_val`), giving 12 values per gage for each set.
#
# **Filtering and the calibration/validation split.** Unlike the 5-day case,
# monthly binning is safe to do before filtering: a monthly bin never spans a
# year boundary, so an odd-year month contains only that odd year's days — no
# validation-year contamination is possible. The calibration/validation split
# is therefore applied *after* the monthly aggregation, by selecting on a `year`
# coordinate:
#
# - `cdat_monthly_cal` / `cdat_monthly_val` — the monthly series restricted to
#   calibration (odd) or validation (even) years.
# - The mean-monthly climatologies are then computed from those, so the
#   calibration climatology averages only odd-year months and the validation
#   climatology only even-year months.
#
# When written to `allobs.dat`, the monthly time series and the mean-monthly
# climatology are emitted for the calibration years (the validation
# mean-monthly is written under its own `..._val` name for independent checking).

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

# Only the calibration (odd) years are written to allobs.dat; validation
# (even) years are omitted here.
cdat_5day_cal = cdat_5day.isel(time=cdat_5day["time"].dt.year.isin(cal_years).values)

# Ship the surviving 5-day bin time index so the remote forward_run can emit
# modeled streamflow_5day values for EXACTLY these bins (and no others). The
# forward run has no observed data, so it cannot reproduce which 5-day bins were
# dropped for missing observations; it reads this list and selects the same bins
# from its own 5-day-resampled seg_outflow. These bins MUST come from
# cdat_5day_cal (the calibration-year-only object that drives the streamflow_5day
# observation names below) -- not the pre-filter cdat_5day, whose resample can
# carry a few even-year boundary bin labels that are excluded from the obs.
_bins_5day = pd.DataFrame(
    {"time": pd.DatetimeIndex(cdat_5day_cal["time"].values).strftime("%Y-%m-%d")}
)
_bins_5day.to_csv(ancillary_dir / "streamflow_5day_bins.csv", index=False)

# set up the indices in sequence
inds = [
    f'_{int(cdat_5day_cal["efc"].sel(poi_gage_id=j, time=i).item())}_{int(cdat_5day_cal["high_low"].sel(poi_gage_id=j, time=i).item())}:{i.year}_{i.month}_{i.day}:{j}'
    for j in cdat_5day_cal.indexes["poi_gage_id"]
    for i in cdat_5day_cal.indexes["time"]
]

# get the variable names
# dvs = list(cdat_5day_cal.keys())

varvals = np.ravel(
    cdat_5day_cal["discharge"], order="C"
)  # flattens the 2D array to a 1D array

with open(pestpp_model_dir / "allobs.dat", encoding="utf-8", mode="a") as ofp:
    [
        ofp.write(f"streamflow_5day{i}          {j}\n")
        for i, j in zip(inds, varvals, strict=True)
    ]

# %%
# Now write to the pest obs file
# Only the calibration (odd) years are written to allobs.dat; validation
# (even) years are omitted here. cdat_monthly carries a "year" coordinate, so
# select on both time and year (matching the cdat_monthly_cal idiom above).
cdat_monthly_cal_write = cdat_monthly.sel(
    time=cdat_monthly.year.isin(cal_years).values,
    year=cdat_monthly.year.isin(cal_years),
)

inds = [
    f"{i.year}_{i.month}:{j}"
    for j in cdat_monthly_cal_write.indexes["poi_gage_id"]
    for i in cdat_monthly_cal_write.indexes["time"]
]  # set up the indices in sequence
varvals = np.ravel(
    cdat_monthly_cal_write["discharge"], order="F"
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
