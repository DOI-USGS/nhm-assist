
import xarray as xr
import pathlib as pl
import pandas as pd
import pywatershed
import os
import dask
import numpy as np


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


