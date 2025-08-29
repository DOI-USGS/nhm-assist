import dask
import shutil
import pandas as pd
import time
import os
import pywatershed as pws
import xarray as xr
import numpy as np
import pywatershed
import pathlib as pl


sttime = time.time()

model_output_netcdf = False

work_dir = pl.Path("./")

out_dir = pl.Path("./output")
#shutil.rmtree(out_dir)  # CAREFUL HERE
#out_dir.mkdir()
custom_output_file = out_dir / "model_custom_output.nc"

#param_file = work_dir / "myparam.param"
#params = pws.parameters.PrmsParameters.load(param_file)
param_file = work_dir / "parameters.json"
params = pws.parameters.PrmsParameters.load_from_json(param_file)
control = pws.Control.load_prms(work_dir / "control.default.bandit", warn_unused_options= False)

control.options = control.options | {
    "input_dir": work_dir,
    "budget_type": None,
    "verbosity": 0,
    "calc_method": "numba",
}

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
            "snowcov_area",
            "soil_rechr",
        ],
        "netcdf_output_dir": out_dir,
    }
else:
    control.options = control.options | {
        "netcdf_output_var_names": None,
        "netcdf_output_dir": None,
    }

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


# Custom model output at selected spatial locations for all times.
# Generally, i'd be careful with xarray performance, but just writing at the
# end should be fine.
# Could move to netcdf4 if performance is a concern.

# /////////////////////////////////
# specfications: what we want this to look like to the user

var_list = [
    "hru_actet",
    "seg_outflow",
    "hru_actet",
    "recharge",
    "snowcov_area",
    "soil_rechr",
]

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


# A novel, diagnostic variable
def sum_hru_flows(sroff_vol, ssres_flow_vol, gwres_flow_vol):
    return sroff_vol + ssres_flow_vol + gwres_flow_vol


diagnostic_var_dict = {
    "hru_streamflow_out": {
        "inputs": ["sroff_vol", "ssres_flow_vol", "gwres_flow_vol"],
        "function": sum_hru_flows,
        "like_var": "sroff_vol",
        "metadata": {"desc": "Total volume to stream network from each HRU", "units": "cubic feet"},
    },
}

# TODO: specify subsets in time
# TODO: specify different output files

# /////////////////////////////////
# code starts here

out_subset_ds = xr.Dataset()

needed_vars = var_list + [
    var for key, val in diagnostic_var_dict.items() for var in val["inputs"]
]
needed_metadata = pws.meta.get_vars(needed_vars)
dims = set([dim for val in needed_metadata.values() for dim in val["dims"]])

subset_vars = [
    var for key, val in spatial_subsets.items() for var in val["variables"]
]

var_subset_key = {
    var: subkey
    for var in subset_vars
    for subkey in spatial_subsets.keys()
    if var in spatial_subsets[subkey]["variables"]
}

diagnostic_vars = list(diagnostic_var_dict.keys())

# solve the processes for each variable
var_proc = {
    var: proc_key
    for var in needed_vars
    for proc_key, proc_val in model.processes.items()
    if var in proc_val.get_variables()
}

time_coord = np.arange(
    control.start_time, control.end_time + control.time_step, dtype="datetime64[D]"
)
n_time_steps = len(time_coord)
out_subset_ds["time"] = xr.Variable(["time"], time_coord)
out_subset_ds = out_subset_ds.set_coords("time")

# annoying to have to hard-code this
dim_coord = {"nhru": "nhm_id", "nsegment": "nhm_seg"}


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


out_subset_ds.to_netcdf(custom_output_file)

print(f"That took {time.time()-sttime:.3f} looong seconds")

del model
del out_subset_ds

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



rootdir = pl.Path('./')# Path to location of cutouts

#var_output_files = ['hru_actet.nc', 'recharge.nc', 'soil_rechr.nc', 'snowcov_area.nc', 'seg_outflow.nc',]#output files of interest


# ### Working currently from a single cutout directory

outvardir = rootdir / 'output'# stes path to location of NHM output folder where output files are.

# set the file name for the postprocessed model output file that PEST will read
of_name = 'modelobs.dat'# name of file

# make a file to hold the consolidated results
ofp = open(rootdir / 'modelobs.dat', 'w') # the 'w' will delete any existing file here and recreate; 'a' appends

modelobsdat  = xr.open_dataset(outvardir / 'model_custom_output.nc')

# ### Slice output to calibration periods for each variable
# #### These are as follows from table 2 (Hay and others, 2023):
#

aet_start = '2000-01-01'
aet_end = '2010-12-31'
recharge_start = '2000-01-01'
recharge_end = '2009-12-31'
runoff_start = '1982-01-01'
runoff_end = '2010-12-31'
soil_rechr_start = '1982-01-01'
soil_rechr_end = '2010-12-31'
sca_start = '2000-01-01'
sca_end = '2010-12-31'
seg_outflow_start = '1999-10-01'
seg_outflow_end = '2010-09-30'

# ### Actual ET
# #### Get and check the daily data

#actet_daily = (xr.open_dataset(outvardir / 'hru_actet.nc')['hru_actet']).sel(time=slice(aet_start, aet_end))
actet_daily = modelobsdat.hru_actet.sel(time=slice(aet_start, aet_end))

# #### Post-process daily output to match observation targets of "monthly" and "mean monthly"


#Creates a dataframe time series of monthly values (average daily rate for the month)
actet_monthly = actet_daily.resample(time = 'm').mean()


# Creates a dataframe time series of mean monthly (mean of all jan, feb, mar....)
actet_mean_monthly = actet_monthly.groupby('time.month').mean()


# #### Now write values to the template file

inds = [f'{i.year}_{i.month}:{j}' for i in actet_monthly.indexes['time'] for j in actet_monthly['nhm_id'].values]# set up the indices in sequence
varvals = np.ravel(actet_monthly, order = 'C')# flattens the 2D array to a 1D array--just playing

with open(rootdir / of_name, encoding="utf-8", mode='w') as ofp:
    ofp.write('obsname    obsval\n') # writing a header for the file
    [ofp.write(f'actet_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

#with open(rootdir / of_name, encoding="utf-8", mode='a') as ofp:
#    [ofp.write(f'g_min_actet_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

actet_monthly.sel(time='2000-01-31').values # look at a slice of the netcdf and compare to pest write

[(i,j) for i,j in zip(inds,varvals)] # playing around and learning adv lists making

inds = [f'{i}:{j}' for i in actet_mean_monthly.indexes['month'] for j in actet_mean_monthly['nhm_id'].values]
varvals =  np.ravel(actet_mean_monthly, order = 'C')# flattens the 2D array to a 1D array

with open(rootdir / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'actet_mean_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

#with open(rootdir / of_name, encoding="utf-8", mode='a') as ofp:
#    [ofp.write(f'g_min_actet_mean_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# ### Post Process recharge for calibration use
# #### Get daily output file from NHM for recharge

recharge_daily = modelobsdat.recharge.sel(time=slice(recharge_start, recharge_end))
# #### Post-process daily output to match observation target of "annual recharge" as an average daily rate for the year

recharge_annual = recharge_daily.resample(time = 'Y').mean()
recharge_annual_norm = (recharge_annual - recharge_annual.min())/(recharge_annual.max()-recharge_annual.min())
# #### Write values to template file


inds = [f'{i.year}:{j}' for i in recharge_annual_norm.indexes['time'] for j in recharge_annual_norm['nhm_id'].values]
varvals =  np.ravel(recharge_annual_norm, order = 'C')# flattens the 2D array to a 1D array

with open(rootdir  / of_name, encoding="utf-8",mode='a') as ofp:
    [ofp.write(f'recharge_ann:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# with open(rootdir  / of_name, encoding="utf-8",mode='a') as ofp:
    # [ofp.write(f'g_min_recharge_ann:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]


# ### Post Process "soil_rechr" to compare to target
# #### Get daily output file from NHM for soil recharge and normalize 0-1
soil_rechr_daily = modelobsdat.soil_rechr.sel(time=slice(soil_rechr_start, soil_rechr_end))

#Creates a dataframe time series of monthly values (average daily rate for each month, normalized)
soil_rechr_monthly = soil_rechr_daily.resample(time = 'm').mean()
soil_rechr_monthly_norm = (soil_rechr_monthly - soil_rechr_monthly.min())/(soil_rechr_monthly.max()-soil_rechr_monthly.min())

#Creates a dataframe time series of annual values (average daily value for each year, normalized)
soil_rechr_annual = soil_rechr_daily.resample(time = 'Y').mean()
soil_rechr_annual_norm = (soil_rechr_annual - soil_rechr_annual.min())/(soil_rechr_annual.max()-soil_rechr_annual.min())


inds = [f'{i.year}_{i.month}:{j}' for i in soil_rechr_monthly_norm.indexes['time'] for j in soil_rechr_monthly_norm['nhm_id'].values]
varvals = np.ravel(soil_rechr_monthly_norm, order = 'C')# flattens the 2D array to a 1D array

with open(rootdir  / of_name, encoding="utf-8",mode='a') as ofp:
    [ofp.write(f'soil_moist_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# with open(rootdir  / of_name, encoding="utf-8",mode='a') as ofp:
    # [ofp.write(f'g_min_soil_moist_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

inds = [f'{i.year}:{j}' for i in soil_rechr_annual_norm.indexes['time'] for j in soil_rechr_annual_norm['nhm_id'].values]
varvals =  np.ravel(soil_rechr_annual_norm, order = 'C')# flattens the 2D array to a 1D array

with open(rootdir   / of_name, encoding="utf-8",mode='a') as ofp:
    [ofp.write(f'soil_moist_ann:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# with open(rootdir   / of_name, encoding="utf-8",mode='a') as ofp:
    # [ofp.write(f'g_min_soil_moist_ann:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]


# ### Post Process "hru_outflow" to compare to target
# #### Get and check the daily data

# These units are in cubic feet (implied per day)
hru_streamflow_out_daily = modelobsdat.hru_streamflow_out.sel(time=slice(runoff_start, runoff_end))

hru_streamflow_out_monthly = hru_streamflow_out_daily.resample(time = 'm').mean()

#This converts the average daily rate to a rate in cubic feet per second to compare to observation
hru_streamflow_out_rate = (hru_streamflow_out_monthly)/(24*60*60)

inds = [f'{i.year}_{i.month}:{j}' for i in hru_streamflow_out_rate.indexes['time'] for j in hru_streamflow_out_rate['nhm_id'].values]
varvals = np.ravel(hru_streamflow_out_rate, order = 'C')# flattens the 2D array to a 1D array

with open(rootdir / of_name, encoding="utf-8",mode='a') as ofp:
    [ofp.write(f'runoff_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# with open(rootdir / of_name, encoding="utf-8",mode='a') as ofp:
    # [ofp.write(f'g_min_runoff_mon:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# ### Post Process "snowcov_area" to compare to target
# #### Get and check the daily data

snowcov_area_daily = modelobsdat.snowcov_area.sel(time=slice(sca_start, sca_end))
remove_ja = True #This is used the filter for removing July and August from the dataset

#Applying filter to remove months, July and August, from the dataset so same size as obs data.
if remove_ja:
    snowcov_area_daily_restr = snowcov_area_daily.sel(time=snowcov_area_daily.time.dt.month.isin([1, 2, 3, 4, 5, 6, 9, 10, 11, 12]))
else:
    snowcov_area_daily_restr = snowcov_area_daily
snowcov_area_daily.close()

inds = [f'{i.year}_{i.month}_{i.day}:{j}' for i in snowcov_area_daily_restr.indexes['time'] for j in snowcov_area_daily_restr['nhm_id'].values]
varvals = np.ravel(snowcov_area_daily_restr, order = 'C')# flattens the 2D array to a 1D array

with open(rootdir   / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'sca_daily:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]

# with open(rootdir   / of_name, encoding="utf-8", mode='a') as ofp:
    # [ofp.write(f'g_min_sca_daily:{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]
# #
#
# ### Get the daily streamflow values from segments associated with the gage pois
#
#Get seg_outflow data ############################################################################################
seg_outflow_daily = modelobsdat.seg_outflow.sel(time=slice(seg_outflow_start, seg_outflow_end))

## Set up validation years
start_water_year = pd.to_datetime(seg_outflow_start).year+1
end_water_year = pd.to_datetime(seg_outflow_end).year
streamflow_water_years = np.array(range(start_water_year,end_water_year+1))

## We will choose even years as validation
val_water_years = [i for i in streamflow_water_years if i%2==0]
cal_water_years = [i for i in streamflow_water_years if i%2!=0]


inds = [f'{i.year}_{i.month}_{i.day}:{j}' for j in seg_outflow_daily['poi_gages'].values for i in seg_outflow_daily.indexes['time']]
varvals = np.ravel(seg_outflow_daily, order = 'F')# flattens the 2D array to a 1D array

with open(rootdir / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'streamflow_daily:{i}          {j}\n') for i,j in zip(inds,varvals,strict=True)]


#########################################################################################################################
# #### Post-process daily output to match observation targets of "monthly" and "mean monthly"


#Creates a dataframe time series of monthly values (average daily rate for the month)
seg_outflow_monthly = seg_outflow_daily.resample(time = 'm').mean()
wateryears =np.array([(i+pd.DateOffset(30+31+31)).year for i in seg_outflow_monthly.time.values])

# Creates a dataframe time series of mean monthly (mean of all jan, feb, mar....)
# pro-tip - gotta use sel with two conditions, but .values breaks the connection to the index using
#           a boolean based on one condition to subset another
seg_outflow_monthly_val = seg_outflow_monthly.sel(time=[True if i in val_water_years else False for i in wateryears])
seg_outflow_monthly_cal = seg_outflow_monthly.sel(time=[True if i in cal_water_years else False for i in wateryears])

seg_outflow_mean_monthly_cal = seg_outflow_monthly_cal.groupby('time.month').mean(skipna=True)
seg_outflow_mean_monthly_val = seg_outflow_monthly_val.groupby('time.month').mean(skipna=True)

#Now write to the pest obs file
inds = [f'{i.year}_{i.month}:{j}' for j in seg_outflow_monthly['poi_gages'].values for i in seg_outflow_monthly.indexes['time'] ]# set up the indices in sequence
varvals = np.ravel(seg_outflow_monthly, order = 'F')# flattens the 2D array to a 1D array--just playing

with open(rootdir   / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'streamflow_mon:{i}          {j}\n') for i,j in zip(inds,varvals,strict=True)]

inds = [f'{i}:{j}' for j in seg_outflow_mean_monthly_cal['poi_gages'].values for i in seg_outflow_mean_monthly_cal.indexes['month'] ]
varvals =  np.ravel(seg_outflow_mean_monthly_cal, order = 'F')# flattens the 2D array to a 1D array

with open(rootdir  / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'streamflow_mean_mon_cal:{i}          {j}\n') for i,j in zip(inds,varvals,strict=True)]

inds = [f'{i}:{j}' for j in seg_outflow_mean_monthly_val['poi_gages'].values for i in seg_outflow_mean_monthly_val.indexes['month'] ]
varvals =  np.ravel(seg_outflow_mean_monthly_val, order = 'F')# flattens the 2D array to a 1D array

with open(rootdir  / of_name, encoding="utf-8", mode='a') as ofp:
    [ofp.write(f'streamflow_mean_mon_val:{i}          {j}\n') for i,j in zip(inds,varvals,strict=True)]


# seg_outflow_start = '2000-01-01'
# seg_outflow_end = '2010-12-31'
#  # This grabs the efc componets in the model_obs name from the obs name
# cdat_efc  = xr.open_dataset(rootdir/ cm / 'sf_data_with_EFC.nc').sel(time=slice(seg_outflow_start, seg_outflow_end))
# cdat_efc = cdat_efc.fillna(-9999)
# cdat_efc = cdat_efc[['efc', 'high_low']]

# seg_outflow_daily = modelobsdat.seg_outflow.sel(time=slice(seg_outflow_start, seg_outflow_end))

# inds = [f'_{int(cdat_efc["efc"].sel(poi_id=j, time=i).item())}_{int(cdat_efc["high_low"].sel(poi_id=j, time=i).item())}:{i.year}_{i.month}_{i.day}:{j}' for j in seg_outflow_daily['poi_gages'].values for i in seg_outflow_daily.indexes['time']]
# varvals = np.ravel(seg_outflow_daily, order = 'F')# flattens the 2D array to a 1D array

# with open(rootdir / cm / of_name, encoding="utf-8", mode='a') as ofp:
#      [ofp.write(f'streamflow_daily{i}          {j}\n') for i,j in zip(inds,varvals, strict=True)]


# seg_outflow_daily = modelobsdat.seg_outflow.sel(time=slice(seg_outflow_start, seg_outflow_end))
# inds = [f'{i.year}_{i.month}_{i.day}:{j}' for j in seg_outflow_daily['poi_gages'].values for i in seg_outflow_daily.indexes['time']]
# varvals = np.ravel(seg_outflow_daily, order = 'F')# flattens the 2D array to a 1D array

# with open(rootdir / of_name, encoding="utf-8", mode='a') as ofp:
#      [ofp.write(f'streamflow_daily:{i}          {j}\n') for i,j in zip(inds,varvals)]


