# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -all
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
import dask
import shutil
import pandas as pd
import time
import os
import pywatershed as pws
import pywatershed
import xarray as xr
import numpy as np
import pathlib as pl

from rich.console import Console

# Console used by the parameter-guardrail warnings below.
con = Console()


# %%
sttime = time.time()

# %%
model_output_netcdf = False

# %%
work_dir = pl.Path("./")

# %%
out_dir = pl.Path("./output")
#shutil.rmtree(out_dir)  # CAREFUL HERE
#out_dir.mkdir()
custom_output_file = out_dir / "model_custom_output.nc"

# %%
# param_file = work_dir / "myparam.param"
# params = pws.parameters.PrmsParameters.load(param_file)
param_file = work_dir / "parameters.json"
params = pws.parameters.PrmsParameters.load_from_json(param_file)
control = pws.Control.load_prms(work_dir / "control.default.bandit", warn_unused_options= False)

# %%
# `params` was already loaded from parameters.json above. Do NOT re-parse the
# JSON with PrmsFile: PrmsFile is the classic PRMS *text*-format parser, and on
# a JSON file its dimensions/parameters scan loop never finds the "** Parameters **"
# marker and never checks EOF, so it spins forever (an apparent hang before the
# model runs). Apply the same two edits directly on the loaded params via the
# xarray round-trip (Parameter objects are not editable in place):
#   - drop stream_tave_init (if present)
#   - add pref_flow_infil_frac (if missing)
params_ds = params.to_xr_ds()
if "stream_tave_init" in params_ds:
    params_ds = params_ds.drop_vars("stream_tave_init")
if "pref_flow_infil_frac" not in params_ds:
    params_ds["pref_flow_infil_frac"] = params_ds.pref_flow_den[:] * 0.0
params = pws.parameters.PrmsParameters.from_ds(params_ds)

# --- pywatershed parameter guardrails ---
# pywatershed has SOME internal guards during soilzone initialization:
#   - soil_rechr_max < 1e-5 is clipped to 1e-5 (line 373 in prms_soilzone.py)
#   - soil_rechr_max > soil_moist_max is capped to soil_moist_max
#   - soil_lower_ratio division uses np.where(soil_lower_max > 0) guard
#
# pywatershed does NOT guard against:
#   - soil_moist_max == 0 (used as divisor in _compute_szactet without guard)
#   - soil_rechr_max_frac == 1.0 (makes soil_lower_max = 0; guarded in init
#     but not in the numba-compiled per-HRU loop)
#   - hru_frac_perv == 0 (used as divisor in capwater_maxin calculation;
#     comment says "has to be > zero" but no runtime check exists)
#
# The checks below catch these unguarded cases before they reach the model run.

# Check for zero soil_moist_max values which cause ZeroDivisionError in soilzone.
# PRMS documentation implicitly assumes soil_moist_max > 0 for all HRUs
# (even water bodies should have 10-60 inches). pywatershed processes all HRUs
# vectorially without the hru_type guards that the original Fortran code used,
# so zero values cause division by zero in soil moisture ratio calculations.
import numpy as np
smm = params.parameters["soil_moist_max"]
n_zero = np.sum(smm == 0)
if n_zero > 0:
    con.print(
        f"[bold yellow]Warning:[/bold yellow] {n_zero} of {len(smm)} HRU(s) have "
        f"[bold]soil_moist_max = 0[/bold], which causes division by zero in "
        f"pywatershed's soilzone calculation. PRMS documentation implicitly "
        f"assumes soil_moist_max > 0 for all HRUs. This is likely due to lake "
        f"or swale HRUs.\nResetting {n_zero} zero value(s) to 0.001 for "
        f"compatibility with pywatershed."
    )
    params_ds = params.to_xr_ds()
    params_ds["soil_moist_max"] = params_ds["soil_moist_max"].clip(min=0.001)
    params = pws.parameters.PrmsParameters.from_ds(params_ds)

# Check for soil_rechr_max_frac == 1.0 which causes soil_lower_max = 0
# (ZeroDivisionError). When soil_rechr_max_frac = 1.0, the recharge zone
# equals the full soil profile, leaving no lower zone. pywatershed divides
# by soil_lower_max in ratio calculations. Cap at 0.999 to ensure a nonzero
# lower zone exists.
srmf = params.parameters["soil_rechr_max_frac"]
n_one = np.sum(srmf >= 1.0)
if n_one > 0:
    con.print(
        f"[bold yellow]Warning:[/bold yellow] {n_one} of {len(srmf)} HRU(s) have "
        f"[bold]soil_rechr_max_frac >= 1.0[/bold], which makes soil_lower_max = 0 "
        f"and causes division by zero in pywatershed's soilzone calculation.\n"
        f"Capping soil_rechr_max_frac at 0.999 for compatibility with pywatershed."
    )
    params_ds = params.to_xr_ds()
    params_ds["soil_rechr_max_frac"] = params_ds["soil_rechr_max_frac"].clip(max=0.999)
    params = pws.parameters.PrmsParameters.from_ds(params_ds)

# Check for hru_frac_perv == 0 which causes division by zero in soilzone.
# hru_frac_perv = (hru_area - hru_percent_imperv*hru_area - dprst_frac*hru_area) / hru_area
# If dprst_frac + hru_percent_imperv >= 1.0, pervious fraction is zero.
# Cap dprst_frac so that hru_frac_perv remains > 0.
if "dprst_frac" in params.parameters and "hru_percent_imperv" in params.parameters:
    dprst = params.parameters["dprst_frac"]
    imperv = params.parameters["hru_percent_imperv"]
    total_non_perv = dprst + imperv
    n_bad = np.sum(total_non_perv >= 1.0)
    if n_bad > 0:
        con.print(
            f"[bold yellow]Warning:[/bold yellow] {n_bad} of {len(dprst)} HRU(s) have "
            f"[bold]dprst_frac + hru_percent_imperv >= 1.0[/bold], which makes "
            f"hru_frac_perv = 0 and causes division by zero in pywatershed's "
            f"soilzone calculation.\nReducing dprst_frac so that the sum does not "
            f"exceed 0.999 for compatibility with pywatershed."
        )
        params_ds = params.to_xr_ds()
        max_dprst = 0.999 - params_ds["hru_percent_imperv"]
        params_ds["dprst_frac"] = params_ds["dprst_frac"].clip(max=max_dprst)
        params = pws.parameters.PrmsParameters.from_ds(params_ds)

# %%
control.options = control.options | {
    "input_dir": work_dir,
    "budget_type": None,
    "verbosity": 0,
    "calc_method": "numba",
}

# %%
if model_output_netcdf:
    control.options = control.options | {
        "netcdf_output_var_names": [
            "hru_actet",
            "sroff_vol",
            "ssres_flow_vol",
            "gwres_flow_vol",
            "seg_outflow",
            "hru_streamflow_out",
            "recharge",
            "pkwater_equiv",
            "soil_rechr",
        ],
        "netcdf_output_dir": out_dir,
    }
else:
    control.options = control.options | {
        "netcdf_output_var_names": None,
        "netcdf_output_dir": None,
    }

# %%
print('About to run the model')

# %%
model = pws.Model(
    [
        pws.PRMSSolarGeometry,
        pws.PRMSAtmosphere,
        pws.PRMSCanopy,
        pws.PRMSSnow,
        pws.PRMSRunoff,
        pws.PRMSSoilzone,
        pws.PRMSGroundwater,
        pws.PRMSChannel,
    ],
    control=control,
    parameters=params,
)


# %% [markdown]
# Custom model output at selected spatial locations for all times.
# Generally, i'd be careful with xarray performance, but just writing at the
# end should be fine.
# Could move to netcdf4 if performance is a concern.

# %% [markdown]
# /////////////////////////////////
# specfications: what we want this to look like to the user

# %%
var_list = [
    "hru_actet",
    "seg_outflow",
    "hru_actet",
    "recharge",
    "pkwater_equiv",
    "soil_rechr",
]

# %%
# want seg_outflow just on poi_gages
# make it a tuple like the return of np.where
wh_gages = (params.parameters["poi_gage_segment"] - 1,)
spatial_subsets = {
    "poi_gages": {
        "coord_name": "nhm_seg",
        "indices": wh_gages,
        "new_coord": params.parameters["poi_gage_id"],
        "variables": ["seg_outflow"],
    },
}


# %%
# A novel, diagnostic variable
def sum_hru_flows(sroff_vol, ssres_flow_vol, gwres_flow_vol):
    return sroff_vol + ssres_flow_vol + gwres_flow_vol


# %%
diagnostic_var_dict = {
    "hru_streamflow_out": {
        "inputs": ["sroff_vol", "ssres_flow_vol", "gwres_flow_vol"],
        "function": sum_hru_flows,
        "like_var": "sroff_vol",
        "metadata": {"desc": "Total volume to stream network from each HRU", "units": "cubic feet"},
    },
}

# %% [markdown]
# TODO: specify subsets in time
# TODO: specify different output files

# %% [markdown]
# /////////////////////////////////
# code starts here

# %%
out_subset_ds = xr.Dataset()

# %%
needed_vars = var_list + [
    var for key, val in diagnostic_var_dict.items() for var in val["inputs"]
]
needed_metadata = pws.meta.get_vars(needed_vars)
dims = set([dim for val in needed_metadata.values() for dim in val["dims"]])

# %%
subset_vars = [
    var for key, val in spatial_subsets.items() for var in val["variables"]
]

# %%
var_subset_key = {
    var: subkey
    for var in subset_vars
    for subkey in spatial_subsets.keys()
    if var in spatial_subsets[subkey]["variables"]
}

# %%
diagnostic_vars = list(diagnostic_var_dict.keys())

# %%
# solve the processes for each variable
var_proc = {
    var: proc_key
    for var in needed_vars
    for proc_key, proc_val in model.processes.items()
    if var in proc_val.get_variables()
}

# %%
time_coord = np.arange(
    control.start_time, control.end_time + control.time_step, dtype="datetime64[D]"
)
n_time_steps = len(time_coord)
out_subset_ds["time"] = xr.Variable(["time"], time_coord)
out_subset_ds = out_subset_ds.set_coords("time")

# %%
# annoying to have to hard-code this
dim_coord = {"nhru": "nhm_id", "nsegment": "nhm_seg"}


# %%
# declare memory for the outputs
for var in var_list + diagnostic_vars:
    # impostor approach
    orig_diag_var = None
    if var in diagnostic_vars:
        orig_diag_var = var
        var = diagnostic_var_dict[var]["like_var"]

    proc = model.processes[var_proc[var]]
    dim_name = needed_metadata[var]["dims"][0]
    dim_len = proc._params.dims[dim_name]
    coord_name = dim_coord[dim_name]
    coord_data = proc._params.coords[dim_coord[dim_name]]
    type = needed_metadata[var]["type"]

    var_meta = {
        kk: vv
        for kk, vv in needed_metadata[var].items()
        if kk in ["desc", "units"]
    }

    if orig_diag_var is not None:
        var = orig_diag_var
        del var_meta["desc"]
        if "metadata" in diagnostic_var_dict[var]:
            var_meta = diagnostic_var_dict[var]["metadata"]
        if "desc" not in var_meta.keys():
            var_meta["desc"] = "Custom output diagnostic variable"

    if var in subset_vars:
        subset_key = var_subset_key[var]
        subset_info = spatial_subsets[subset_key]
        dim_name = f"n{subset_key}"
        coord_name = subset_key
        dim_len = len(subset_info["indices"][0])
        coord_data = subset_info["new_coord"]

    if coord_name not in list(out_subset_ds.variables):
        out_subset_ds[coord_name] = xr.DataArray(coord_data, dims=[dim_name])
        out_subset_ds = out_subset_ds.set_coords(coord_name)

    out_subset_ds[var] = xr.Variable(
        ["time", dim_name],
        np.full(
            [n_time_steps, dim_len],
            pws.constants.fill_values_dict[np.dtype(type)],
            type,
        ),
    )

    out_subset_ds[var].attrs = var_meta


# %%
for istep in range(n_time_steps):
    model.advance()
    model.calculate()

    if model_output_netcdf:
        model.output()

    for var in var_list:
        proc = model.processes[var_proc[var]]
        data = proc[var]
        if isinstance(proc[var], pws.base.timeseries.TimeseriesArray):
            data = data.current
        if var not in subset_vars:
            out_subset_ds[var][istep, :] = data
        else:
            indices = spatial_subsets[var_subset_key[var]]["indices"]
            out_subset_ds[var][istep, :] = data[indices]

    for diag_key, diag_val in diagnostic_var_dict.items():
        input_dict = {}
        for ii in diag_val["inputs"]:
            proc = model.processes[var_proc[ii]]
            input_dict[ii] = proc[ii]

        out_subset_ds[diag_key][istep, :] = diag_val["function"](**input_dict)


# %%
out_subset_ds.to_netcdf(custom_output_file)

# %%
print(f"That took {time.time()-sttime:.3f} looong seconds")

# %%
del model
del out_subset_ds

# %%
if model_output_netcdf:
    out_subset_ds = xr.open_dataset(custom_output_file)

    for vv in var_list:
        default_output_file = out_dir / f"{vv}.nc"
        print("checking variable: ", vv)
        answer = xr.load_dataarray(default_output_file)

        result = out_subset_ds[vv]

        if vv in subset_vars:
            indices = spatial_subsets[var_subset_key[vv]]["indices"]
            answer = answer[:, indices[0]]

        np.testing.assert_allclose(answer, result)
        answer.close()

    for diag_key, diag_val in diagnostic_var_dict.items():
        print("checking diagnostic variable: ", diag_key)
        input_dict = {}
        for ii in diag_val["inputs"]:
            default_output_file = out_dir / f"{ii}.nc"
            input_dict[ii] = xr.load_dataarray(default_output_file)

        answer = diag_val["function"](**input_dict)
        result = out_subset_ds[diag_key]

        np.testing.assert_allclose(answer, result)

    out_subset_ds.close()
print("#### RUN DONE, TIME TO POSTPROCESS ####")

# %%

# %%
rootdir = pl.Path('./')# Path to location of cutouts

# %% [markdown]
# var_output_files = ['hru_actet.nc', 'recharge.nc', 'soil_rechr.nc', 'snowcov_area.nc', 'seg_outflow.nc',]#output files of interest


# %% [markdown]
# ### Working currently from a single cutout directory

# %%
outvardir = rootdir / 'output'# stes path to location of NHM output folder where output files are.

# %%
# set the file name for the postprocessed model output file that PEST will read
of_name = 'modelobs.dat'# name of file

# %%
# make a file to hold the consolidated results
ofp = open(rootdir / 'modelobs.dat', 'w') # the 'w' will delete any existing file here and recreate; 'a' appends

# %%
modelobsdat  = xr.open_dataset(outvardir / 'model_custom_output.nc')

# %%
modelobsdat

# %% [markdown]
# ### Relabel the HRU axis from local `hru_id` to national `nhm_id`
#
# The model output's `nhm_id` coordinate is taken from the pywatershed param
# file, which actually stores the parent's **local** `hru_id`. The observation
# targets in `allobs.dat` are keyed by the parent's **national** `nhm_id`. To
# keep the model-output observation names internally consistent with
# `allobs.dat`, remap the HRU axis using the crosswalk shipped from notebook 00
# (`hru_nhm_id_crosswalk.csv`: columns `hru_id`, `nhm_id`). We map by id (not by
# position) so alignment holds regardless of ordering.

# %%
hru_xwalk = pd.read_csv(rootdir / "hru_nhm_id_crosswalk.csv")
# Build a local hru_id -> national nhm_id lookup and apply it to the HRU axis.
_hru_to_nhm = dict(zip(hru_xwalk["hru_id"].astype(int), hru_xwalk["nhm_id"].astype(int)))
_local_hru_ids = modelobsdat["nhm_id"].values.astype(int)
_national_nhm_ids = np.array([_hru_to_nhm[h] for h in _local_hru_ids], dtype=int)
# Overwrite the nhm_id coordinate (which is along the `nhru` dimension) with the
# national ids, then promote nhm_id to be the HRU *dimension* coordinate. Making
# nhm_id a real dimension (not just a coordinate along nhru) means it survives
# resample/groupby reductions below -- matching how the observation targets in
# 00/01 are keyed by nhm_id, and avoiding the KeyError when writing obs names.
modelobsdat = modelobsdat.assign_coords(nhm_id=("nhru", _national_nhm_ids))
modelobsdat = modelobsdat.swap_dims({"nhru": "nhm_id"})

# %%
modelobsdat

# %% [markdown]
# ### Slice output to calibration periods for each variable
# These are as follow the calibration table as listed in pestpp_ies_calibration/notebooks/00_Subset_NHM_baselines_gfv2.ipynb. They are manually entered here to decrease data file dependencies in the AWS setup.
#

# %%
# Set in "pestpp_ies_calibration/notebooks/00_Subset_NHM_baselines_gfv2.ipynb"
aet_start = '2009-01-01'
aet_end = '2020-12-31'
recharge_start = '2002-01-01'
recharge_end = '2013-12-31'
runoff_start = '2009-01-01'
runoff_end = '2020-12-31'
soil_rechr_start = '2014-01-01'
soil_rechr_end = '2025-12-31'
swe_start = '2010-01-01'
swe_end = '2021-12-31'

# set in "pestpp_ies_calibration/notebooks/01_Prepare_observations_gfv2.ipynb"
seg_outflow_start = '2011-01-01' 
seg_outflow_end = '2021-12-31'

# %% [markdown]
# ### Actual ET
# #### Get and check the daily data

# %%
#actet_daily = (xr.open_dataset(outvardir / 'hru_actet.nc')['hru_actet']).sel(time=slice(aet_start, aet_end))
actet_daily = modelobsdat.hru_actet.sel(time=slice(aet_start, aet_end))

# %% [markdown]
# #### Post-process daily output to match the observation target of "mean monthly"
#
# The observation file (01_Prepare_observations_gfv2) writes only the
# `actet_mean_mon` climatology, computed over the calibration (odd) years of the
# AET period. To match, we restrict the daily AET output to the calibration
# (odd) years -- the same odd/even split used in notebook 00 -- resample to
# monthly means, then average by calendar month.

# %%
# Calibration (odd) years for the AET period, matching notebook 00's
# _cal_val_years rule (odd years within [start.year, end.year] inclusive).
aet_years = np.arange(
    pd.to_datetime(aet_start).year, pd.to_datetime(aet_end).year + 1
)
aet_cal_years = [int(y) for y in aet_years if y % 2 != 0]

# Restrict the daily series to the calibration years BEFORE resampling so that
# no even (validation) year contributes to a calibration monthly value.
actet_daily_cal = actet_daily.sel(
    time=actet_daily["time"].dt.year.isin(aet_cal_years).values
)

# %%
# Creates a time series of monthly values (average daily rate for the month)
actet_monthly = actet_daily_cal.resample(time="m").mean()

# %%
# Creates a time series of mean monthly (mean of all jan, feb, mar....)
actet_mean_monthly = actet_monthly.groupby("time.month").mean()


# %%
actet_mean_monthly

# %% [markdown]
# #### Now write values to the template file
# `actet_mean_mon` is the first block written to modelobs.dat, so it opens the
# file ('w') and writes the header, matching allobs.dat in 01.

# %%
inds = [f'{i}:{j}' for i in actet_mean_monthly.indexes['month'] for j in actet_mean_monthly['nhm_id'].values]
varvals =  np.ravel(actet_mean_monthly, order = 'C')# flattens the 2D array to a 1D array

# %%
with open(rootdir / of_name, encoding="utf-8", mode='w') as ofp:
    ofp.write('obsname    obsval\n') # writing a header for the file
    [ofp.write(f'actet_mean_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %% [markdown]
# with open(rootdir / of_name, encoding="utf-8", mode='a') as ofp:
#    [ofp.write(f'g_min_actet_mean_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %% [markdown]
# ### Post Process recharge for calibration use
# #### Get daily output file from NHM for recharge

# %%
recharge_daily = modelobsdat.recharge.sel(time=slice(recharge_start, recharge_end))
# #### Post-process daily output to match observation target of "annual recharge" as an average daily rate for the year

# %%
# Annual mean of the daily recharge rate over the FULL recharge period.
recharge_annual = recharge_daily.resample(time = 'Y').mean()

# Normalize per HRU across time (each HRU scaled to its own 0-1), matching the
# target construction in notebook 06 (min/max over time per HRU, with a
# zero-range guard). This is done over the full recharge period BEFORE the
# calibration-year selection below, mirroring how the target normalizes over
# each source's full record and only later restricts to calibration years.
_rch_min = recharge_annual.min(dim='time')
_rch_max = recharge_annual.max(dim='time')
_rch_range = _rch_max - _rch_min
recharge_annual_norm = (recharge_annual - _rch_min) / _rch_range.where(_rch_range > 0)

# Restrict to calibration (odd) years AFTER normalizing over the full period,
# matching notebook 00's _cal_val_years rule (odd years within the recharge
# period). The target file RCH_annual.nc contains only these calibration years.
recharge_years = np.arange(
    pd.to_datetime(recharge_start).year, pd.to_datetime(recharge_end).year + 1
)
recharge_cal_years = [int(y) for y in recharge_years if y % 2 != 0]
recharge_annual_norm = recharge_annual_norm.sel(
    time=recharge_annual_norm['time'].dt.year.isin(recharge_cal_years).values
)
# #### Write values to template file


# %%
inds = [f'{i.year}:{j}' for i in recharge_annual_norm.indexes['time'] for j in recharge_annual_norm['nhm_id'].values]
varvals =  np.ravel(recharge_annual_norm, order = 'C')# flattens the 2D array to a 1D array

# %%
with open(rootdir  / of_name, encoding="utf-8",mode='a') as ofp:
    [ofp.write(f'recharge_ann:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %%
# with open(rootdir  / of_name, encoding="utf-8",mode='a') as ofp:
    # [ofp.write(f'g_min_recharge_ann:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]


# %%
# ### Post Process "soil_rechr" to compare to target
# #### Get daily output file from NHM for soil recharge and normalize 0-1
soil_rechr_daily = modelobsdat.soil_rechr.sel(time=slice(soil_rechr_start, soil_rechr_end))

# %%
# Soil moisture MEAN-MONTHLY target (soil_moist_mean_mon).
# Match the target construction in notebooks 06/00/01:
#   1. restrict to calibration (odd) years of the soil-moisture period,
#   2. resample daily -> monthly mean,
#   3. normalize per HRU per CALENDAR MONTH to 0-1 (each HRU's Jan values
#      scaled by that HRU's Jan min/max across years, etc.), and
#   4. average by calendar month (groupby('time.month').mean()).
soil_rechr_years = np.arange(
    pd.to_datetime(soil_rechr_start).year, pd.to_datetime(soil_rechr_end).year + 1
)
soil_rechr_cal_years = [int(y) for y in soil_rechr_years if y % 2 != 0]
soil_rechr_daily_cal = soil_rechr_daily.sel(
    time=soil_rechr_daily['time'].dt.year.isin(soil_rechr_cal_years).values
)

# monthly mean of the daily rate (calibration years only)
soil_rechr_monthly = soil_rechr_daily_cal.resample(time = 'm').mean()

# normalize per HRU per calendar month (with zero-range guard), matching
# notebook 06's normalize_per_month. min/max are computed over years within
# each calendar month, then mapped back onto the monthly time axis.
_sm_month_min = soil_rechr_monthly.groupby('time.month').min(dim='time')
_sm_month_max = soil_rechr_monthly.groupby('time.month').max(dim='time')
_sm_month_range = (_sm_month_max - _sm_month_min)
_sm_month_range = _sm_month_range.where(_sm_month_range > 0)
_sm_months = soil_rechr_monthly['time'].dt.month
_sm_min_on_time = _sm_month_min.sel(month=_sm_months).drop_vars('month')
_sm_range_on_time = _sm_month_range.sel(month=_sm_months).drop_vars('month')
soil_rechr_monthly_norm = (soil_rechr_monthly - _sm_min_on_time) / _sm_range_on_time

# mean monthly climatology (mean of all Jan, Feb, ... across cal years)
soil_rechr_mean_monthly = soil_rechr_monthly_norm.groupby('time.month').mean()

# %%
# Soil moisture ANNUAL target (soil_moist_ann).
# Match notebook 06's normalize_whole_period: annual mean, then normalize per
# HRU over the WHOLE period to 0-1 (min/max over time per HRU, zero-range
# guard). Normalize over the full soil-moisture period FIRST, then select the
# calibration (odd) years -- consistent with the recharge treatment.
soil_rechr_annual = soil_rechr_daily.resample(time = 'Y').mean()
_sma_min = soil_rechr_annual.min(dim='time')
_sma_max = soil_rechr_annual.max(dim='time')
_sma_range = (_sma_max - _sma_min)
soil_rechr_annual_norm = (soil_rechr_annual - _sma_min) / _sma_range.where(_sma_range > 0)
soil_rechr_annual_norm = soil_rechr_annual_norm.sel(
    time=soil_rechr_annual_norm['time'].dt.year.isin(soil_rechr_cal_years).values
)


# %%
inds = [f'{i}:{j}' for i in soil_rechr_mean_monthly.indexes['month'] for j in soil_rechr_mean_monthly['nhm_id'].values]
varvals = np.ravel(soil_rechr_mean_monthly, order = 'C')# flattens the 2D array to a 1D array

# %%
with open(rootdir  / of_name, encoding="utf-8",mode='a') as ofp:
    [ofp.write(f'soil_moist_mean_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %%
# with open(rootdir  / of_name, encoding="utf-8",mode='a') as ofp:
    # [ofp.write(f'g_min_soil_moist_mean_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %%
inds = [f'{i.year}:{j}' for i in soil_rechr_annual_norm.indexes['time'] for j in soil_rechr_annual_norm['nhm_id'].values]
varvals =  np.ravel(soil_rechr_annual_norm, order = 'C')# flattens the 2D array to a 1D array

# %%
with open(rootdir   / of_name, encoding="utf-8",mode='a') as ofp:
    [ofp.write(f'soil_moist_ann:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %%
# with open(rootdir   / of_name, encoding="utf-8",mode='a') as ofp:
    # [ofp.write(f'g_min_soil_moist_ann:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]


# %% [markdown]
# ### Post Process "hru_outflow" to compare to target
# #### Get and check the daily data

# %%
# These units are in cubic feet (implied per day)
hru_streamflow_out_daily = modelobsdat.hru_streamflow_out.sel(time=slice(runoff_start, runoff_end))

# %%
hru_streamflow_out_monthly = hru_streamflow_out_daily.resample(time = 'm').mean()

# Restrict to calibration (odd) years of the runoff period, matching notebook
# 00's _cal_val_years rule. The target file hru_streamflow_monthly.nc contains
# only these calibration years (in cfs, not normalized). Filter AFTER the
# monthly resample: resampling rebuilds a continuous monthly axis that would
# otherwise re-insert the even (validation) years as empty bins.
runoff_years = np.arange(
    pd.to_datetime(runoff_start).year, pd.to_datetime(runoff_end).year + 1
)
runoff_cal_years = [int(y) for y in runoff_years if y % 2 != 0]
hru_streamflow_out_monthly = hru_streamflow_out_monthly.sel(
    time=hru_streamflow_out_monthly['time'].dt.year.isin(runoff_cal_years).values
)

# %%
#This converts the average daily rate to a rate in cubic feet per second to compare to observation
hru_streamflow_out_rate = (hru_streamflow_out_monthly)/(24*60*60)
# For pest++-ies bug fix
threshold = 1.0e-5
hru_streamflow_out_rate = hru_streamflow_out_rate.where(hru_streamflow_out_rate >= threshold, 0)

# %%
inds = [f'{i.year}_{i.month}:{j}' for i in hru_streamflow_out_rate.indexes['time'] for j in hru_streamflow_out_rate['nhm_id'].values]
varvals = np.ravel(hru_streamflow_out_rate, order = 'C')# flattens the 2D array to a 1D array

# %%
with open(rootdir / of_name, encoding="utf-8",mode='a') as ofp:
    [ofp.write(f'runoff_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %%
# with open(rootdir / of_name, encoding="utf-8",mode='a') as ofp:
    # [ofp.write(f'g_min_runoff_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %% [markdown]
# ### Post Process SWE ("pkwater_equiv") to compare to target
# #### Get the daily data and build the monthly SWE target
#
# Matches the `SWE_monthly` target in 01_Prepare_observations_gfv2 (built from
# SWE_monthly.nc in notebook 00): monthly-mean SWE (inches) over the calibration
# (odd) years, with June-October dropped and NaNs filled with the -9999 PEST++
# no-data sentinel. Replaces the former snow-covered-area (SCA) target.

# %%
# Daily SWE (inches) over the SWE period, then monthly mean (month-end labels,
# '1ME') to match the target built in notebook 00 (resample('1ME').mean()).
swe_daily = modelobsdat.pkwater_equiv.sel(time=slice(swe_start, swe_end))
swe_monthly = swe_daily.resample(time='1ME').mean()

# Restrict to calibration (odd) years AFTER the monthly resample (resampling
# rebuilds a continuous monthly axis that would otherwise re-insert the even
# validation years as empty bins). Matches SWE_monthly.nc, which keeps only
# the calibration years.
swe_years = np.arange(
    pd.to_datetime(swe_start).year, pd.to_datetime(swe_end).year + 1
)
swe_cal_years = [int(y) for y in swe_years if y % 2 != 0]
swe_monthly = swe_monthly.sel(
    time=swe_monthly['time'].dt.year.isin(swe_cal_years).values
)

# %%
# Fill NaNs with the -9999 PEST++ no-data sentinel and drop June-October,
# exactly as notebook 01 does when writing the SWE_monthly target.
swe_monthly_restr = swe_monthly.fillna(-9999)
swe_monthly_restr = swe_monthly_restr.sel(
    time=~swe_monthly_restr['time'].dt.month.isin([6, 7, 8, 9, 10])
)

# %%
inds = [f'{i.year}_{i.month}_{i.day}:{j}' for i in swe_monthly_restr.indexes['time'] for j in swe_monthly_restr['nhm_id'].values]
varvals = np.ravel(swe_monthly_restr, order = 'C')# flattens the 2D array to a 1D array

# %%
with open(rootdir   / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'SWE_monthly:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# %%
# with open(rootdir   / of_name, encoding="utf-8", mode='a') as ofp:
    # [ofp.write(f'g_min_SWE_monthly:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]
# #
#
# ### Streamflow: get seg_outflow at the calibration gages
#
# Match notebook 01: subset/reorder to the calibration gages (ohm_cal == 'yes'
# in the shipped npoigages_cal_list spreadsheet) and use the same period. The
# EFC/high_low codes are NOT embedded in the model obs names (the instruction
# file / check_ins_and_outs strips the streamflow_5day EFC suffix), so alignment
# with allobs.dat is positional: same gages, same order, same time bins.
import glob as _glob
_cal_list = _glob.glob(str(rootdir / 'ancillary' / 'npoigages_cal_list*.xlsx')) + \
            _glob.glob(str(rootdir / 'ancillary' / 'npoigages_cal_list*.xls'))
_gage_df = pd.read_excel(_cal_list[0], dtype={'poi_gage_id': str})
_gage_df['poi_gage_id'] = _gage_df['poi_gage_id'].str.strip()
_cal_lookup = dict(zip(_gage_df['poi_gage_id'], _gage_df['ohm_cal'].astype(str).str.strip().str.lower()))
cal_gages = [g for g, v in _cal_lookup.items() if v == 'yes']

# seg_outflow over the streamflow period, subset+reindexed to cal_gages order.
# poi_gages is a non-dimension coordinate (on dim npoi_gages), so promote it to
# a dimension coordinate first; otherwise reindex can't reorder along it.
seg_outflow_daily = modelobsdat.seg_outflow.sel(time=slice(seg_outflow_start, seg_outflow_end))
seg_outflow_daily = seg_outflow_daily.swap_dims({'npoi_gages': 'poi_gages'})
_present_gages = set(str(x) for x in seg_outflow_daily['poi_gages'].values)
seg_outflow_daily = seg_outflow_daily.sel(
    poi_gages=[g for g in cal_gages if g in _present_gages]
).reindex(poi_gages=cal_gages)

# %%
## Calibration/validation year split, matching notebook 01 exactly:
##   streamflow_years = range(start_year, end_year)  # NOTE: end year EXCLUSIVE
##   odd years = calibration, even years = validation
start_year = pd.to_datetime(seg_outflow_start).year
end_year = pd.to_datetime(seg_outflow_end).year
streamflow_years = np.array(range(start_year, end_year))
val_years = [i for i in streamflow_years if i % 2 == 0]
cal_years = [i for i in streamflow_years if i % 2 != 0]

# %% [markdown]
# #### streamflow_5day: 5-day-averaged discharge on the calibration bins
#
# Mirrors notebook 01: filter the daily series to calibration (odd) years FIRST,
# then non-overlapping 5-day resample mean. The set of surviving 5-day bins is
# determined by observed-data availability in 01 (bins with any NaN were
# dropped); that surviving bin index is shipped as
# ancillary/streamflow_5day_bins.csv, and we select exactly those bins here so
# modelobs.dat aligns positionally with allobs.dat. Values are the modeled 5-day
# mean discharge; the EFC/high_low suffix in the observation name is omitted.


# %%
# Filter daily to calibration (odd) years BEFORE 5-day binning so no validation
# -year day leaks into a calibration 5-day bin (same reasoning as notebook 01).
seg_outflow_cal_daily = seg_outflow_daily.sel(
    time=seg_outflow_daily['time'].dt.year.isin(cal_years).values
)
seg_outflow_5day = seg_outflow_cal_daily.resample(time='5D').mean()

# Select exactly the surviving 5-day bins that notebook 01 kept (shipped index).
_bins_5day = pd.to_datetime(
    pd.read_csv(rootdir / 'ancillary' / 'streamflow_5day_bins.csv')['time']
).values
seg_outflow_5day = seg_outflow_5day.sel(time=_bins_5day)
seg_outflow_5day = seg_outflow_5day.fillna(-9999)

# outer loop gage, inner loop time; C-order ravel -- matching notebook 01.
inds = [f'{i.year}_{i.month}_{i.day}:{j}' for j in seg_outflow_5day['poi_gages'].values for i in seg_outflow_5day.indexes['time']]
varvals = np.ravel(seg_outflow_5day, order = 'C')# flattens the 2D array to a 1D array

# %%
with open(rootdir / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'streamflow_5day:{i}          {j}\n') for i,j in zip(inds,varvals,strict=True)]


# %% [markdown]
# #### Monthly and mean-monthly streamflow (matching notebook 01)
#
# Monthly mean discharge is built from the full-period daily series (a monthly
# bin never spans a year boundary, so the cal/val split is applied after the
# monthly aggregation). streamflow_mon and streamflow_mean_mon_cal are written
# for calibration (odd) years; streamflow_mean_mon_val for validation (even)
# years. All flattened in Fortran order (gage outer, time/month inner).


# %%
# Monthly means over the full period. (seg_outflow is a DataArray, so we do
# the cal/val split with a boolean mask on time.dt.year rather than adding a
# 'year' coordinate -- a second index on 'time' would break label selection.)
seg_outflow_monthly = seg_outflow_daily.resample(time='ME').mean(skipna=True)

# %%
# Split monthly series into calibration (odd) and validation (even) years
# using a mask on the month timestamps' year.
_mon_year = seg_outflow_monthly['time'].dt.year
seg_outflow_monthly_val = seg_outflow_monthly.sel(time=_mon_year.isin(val_years).values)
seg_outflow_monthly_cal = seg_outflow_monthly.sel(time=_mon_year.isin(cal_years).values)

# %%
seg_outflow_mean_monthly_cal = seg_outflow_monthly_cal.groupby('time.month').mean(skipna=True)
seg_outflow_mean_monthly_val = seg_outflow_monthly_val.groupby('time.month').mean(skipna=True)

# Fill NaNs with the -9999 PEST++ no-data sentinel (matching notebook 01).
seg_outflow_monthly_cal = seg_outflow_monthly_cal.fillna(-9999)
seg_outflow_mean_monthly_cal = seg_outflow_mean_monthly_cal.fillna(-9999)
seg_outflow_mean_monthly_val = seg_outflow_mean_monthly_val.fillna(-9999)

# %%
# streamflow_mon: calibration (odd) years only; gage outer, time inner, F-order.
inds = [f'{i.year}_{i.month}:{j}' for j in seg_outflow_monthly_cal['poi_gages'].values for i in seg_outflow_monthly_cal.indexes['time'] ]
varvals = np.ravel(seg_outflow_monthly_cal, order = 'F')# flattens the 2D array to a 1D array

# %%
with open(rootdir   / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'streamflow_mon:{i}          {j}\n') for i,j in zip(inds,varvals,strict=True)]

# %%
inds = [f'{i}:{j}' for j in seg_outflow_mean_monthly_cal['poi_gages'].values for i in seg_outflow_mean_monthly_cal.indexes['month'] ]
varvals =  np.ravel(seg_outflow_mean_monthly_cal, order = 'F')# flattens the 2D array to a 1D array

# %%
with open(rootdir  / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'streamflow_mean_mon_cal:{i}          {j}\n') for i,j in zip(inds,varvals,strict=True)]

# %%
inds = [f'{i}:{j}' for j in seg_outflow_mean_monthly_val['poi_gages'].values for i in seg_outflow_mean_monthly_val.indexes['month'] ]
varvals =  np.ravel(seg_outflow_mean_monthly_val, order = 'F')# flattens the 2D array to a 1D array

# %%
with open(rootdir  / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'streamflow_mean_mon_val:{i}          {j}\n') for i,j in zip(inds,varvals,strict=True)]


# %% [markdown]
# seg_outflow_start = '2000-01-01'
# seg_outflow_end = '2010-12-31'
#  # This grabs the efc componets in the model_obs name from the obs name
# cdat_efc  = xr.open_dataset(rootdir/ cm / 'sf_data_with_EFC.nc').sel(time=slice(seg_outflow_start, seg_outflow_end))
# cdat_efc = cdat_efc.fillna(-9999)
# cdat_efc = cdat_efc[['efc', 'high_low']]

# %% [markdown]
# seg_outflow_daily = modelobsdat.seg_outflow.sel(time=slice(seg_outflow_start, seg_outflow_end))

# %% [markdown]
# inds = [f'_{int(cdat_efc["efc"].sel(poi_id=j, time=i).item())}_{int(cdat_efc["high_low"].sel(poi_id=j, time=i).item())}:{i.year}_{i.month}_{i.day}:{j}' for j in seg_outflow_daily['poi_gages'].values for i in seg_outflow_daily.indexes['time']]
# varvals = np.ravel(seg_outflow_daily, order = 'F')# flattens the 2D array to a 1D array

# %% [markdown]
# with open(rootdir / cm / of_name, encoding="utf-8", mode='a') as ofp:
#      [ofp.write(f'streamflow_daily{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]


# %% [markdown]
# seg_outflow_daily = modelobsdat.seg_outflow.sel(time=slice(seg_outflow_start, seg_outflow_end))
# inds = [f'{i.year}_{i.month}_{i.day}:{j}' for j in seg_outflow_daily['poi_gages'].values for i in seg_outflow_daily.indexes['time']]
# varvals = np.ravel(seg_outflow_daily, order = 'F')# flattens the 2D array to a 1D array

# %% [markdown]
# with open(rootdir / of_name, encoding="utf-8", mode='a') as ofp:
#      [ofp.write(f'streamflow_daily:{i}          {j}\n') for i,j in zip(inds,varvals)]

# %%
