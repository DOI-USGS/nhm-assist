# ---
# jupyter:
#   jupytext:
#     formats: nhf_assist/notebooks///ipynb,src/workflow_templates/nhf///py:percent
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
import warnings
import pandas as pd
import pathlib as pl
from pathlib import Path
from pyPRMS.metadata.metadata import MetaData
from pyPRMS import ParameterFile
from contextlib import redirect_stdout
import io
f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws
from rich.console import Console
from rich import pretty
warnings.filterwarnings("ignore")
#import jupyter_black
pretty.install()
con = Console()
#jupyter_black.load()

import sys
import os
root_folder = "nhf_assist"
root_dir = pl.Path(os.getcwd().rsplit(root_folder, 1)[0] + root_folder)
sys.path.append(str(root_dir))

from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config
config = load_subdomain_config(root_dir)
# con.print(config)

# %%
import xarray as xr
from assist.nhm.streamflow_postprocess import subset_seg_outflow_to_poi_gages

# %% [markdown]
# ## Introduction
# The purpose of this model is first, to reformat any input files provided in the NHM subdomain model for running `pywatershed`. Next the notebook will run the NHM subdomain model using `pywatershed` using a customized run script. Other `pywatershed` run script examples can be found [here.](https://github.com/EC-USGS/pywatershed/tree/develop/examples) and generate a output files for selected variables and two customized output variables. 
#
# What is pywatershed?
#
# Pywatershed is Python package for simulating hydrologic processes motivated by the need to modernize important, legacy hydrologic models at the USGS, particularly the [Precipitation-Runoff Modeling System](https://www.usgs.gov/software/precipitation-runoff-modeling-system-prms) (PRMS, Markstrom et al., 2015) and its role in GSFLOW (Markstrom et al., 2008). The goal of modernization is to make these legacy models more flexible as process representations, to support testing of alternative hydrologic process conceptualizations, and to facilitate the incorporation of cutting edge modeling techniques and data sources. Pywatershed is a place for experimentation with software design, process representation, and data fusion in the context of well-established hydrologic process modeling.
#
# For more information on the goals and status of `pywatershed`, please see the [pywatershed docs](https://pywatershed.readthedocs.io/en/main/).

# %% [markdown]
# ## Prepare NHM subdomain for `pywatershed` run
# As development of `pywatershed` and extraction methods for NHM subdomain models continues, the NHM subdomain model input files and/or parameter files may need some modification to prepare the NHM subdomain model for `pywatershed`. In this section, tailored modification of model files can be made. Currently two modifications are needed.

# %% [markdown]
# ### Make `pywatershed` .nc input files from NHM domain input file (`cbh.nc`).
# The NHM subdomain model input was provided as one file, `cbh.nc`, that included tmin, tmax, and precipitation data. These data need to be split into individual files to be read by `pywatershed`.

# %%
pws_prcp_input_file = config['model_dir'] / "prcp.nc"

pws_tmin_input_file = config['model_dir'] / "tmin.nc"

pws_tmax_input_file = config['model_dir'] / "tmax.nc"


nhmx_input_file = config['model_dir'] / "cbh.nc"
input_file_path_list = [pws_prcp_input_file, pws_tmin_input_file, pws_tmax_input_file]

for input_file_path in input_file_path_list:
    if not input_file_path.exists():
        con.print(
            "One or more of the pywatershed input files does not exist. All input file will be rewritten from the cbh.nc file."
        )
        with xr.open_dataset(
            nhmx_input_file
        ) as input:  # This is the input file given with NHMx
            #model_input = input.swap_dims({"hruid": "nhm_id"}).drop("hruid")
            # Handle different dimension names across model versions:
            # v1.1 cbh.nc uses 'hruid', v2 uses 'nhm_id', some use 'nhru'
            if "hruid" in input.dims or "hruid" in input.coords:
                model_input = input.rename({"hruid": "nhm_id"})
            elif "nhru" in input.dims and "nhm_id" in input.data_vars:
                # nhm_id exists as a variable; swap dims to use it as the coordinate
                model_input = input.swap_dims({"nhru": "nhm_id"}).drop_vars("nhru", errors="ignore")
            elif "nhru" in input.dims and "nhm_id" not in input.dims:
                model_input = input.rename({"nhru": "nhm_id"})
            else:
                model_input = input
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
# for f in input_file_path_list:
#     with xr.open_dataset(f) as ds:
#         new_name = f.with_suffix(".renamed.nc")
#         ds2 = ds.rename({"hruid": "nhm_id"})
#         ds2.to_netcdf(new_name)



# %%
with xr.open_dataset(pws_prcp_input_file) as ds:
    print(ds)

# %% [markdown]
# ### Parameter file check
# `pywatershed` requires the soilzone variable "pref_flow_infil_frac" to be present in the parameter file. If the variable is not in the parameter file, it must be added as all zeros before passing the parameters to `pywatershed`.
#
# The parameter `stream_tave_init` in NHM v1.1 is dimensioned by `nsegment`,
# but pywatershed metadata expects it as a scalar. We remove it before loading
# to avoid a dimension mismatch error.

# %%
from pywatershed.utils.prms5_file_util import PrmsFile

param_data = PrmsFile(config['param_filename'], "parameter").get_data()
param_data["parameter"]["parameters"].pop("stream_tave_init", None)

params = pws.parameters.PrmsParameters._process_file_input(
    param_data["parameter"]["parameters"],
)
if "pref_flow_infil_frac" not in params.parameters.keys():
    # Parameter objects are not directly editable in pywatershed,
    # so we export to an equivalent object we can edit, in this case
    # an xarray dataset, then we convert back
    params_ds = params.to_xr_ds()
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

# %% [markdown]
# ## Custom Run for NHM subdomain model
# The custom run loop will output the `pywatershed` standard output variables only and outputs each variable as a .nc file. The standard output variables, `selected_output_variables`, were selected in [notebook 0](.\0_Workspace_setup.ipynb).

# %%
control = pws.Control.load_prms(
    config['model_dir'] / config['control_file_name'], warn_unused_options=False
)
# Sets control options for both cases
control.options = control.options | {
    "input_dir": config['model_dir'],
    "budget_type": None,
    "verbosity": 0,
    "calc_method": "numba",
}

control.options = control.options | {
    "netcdf_output_var_names": config['selected_output_variables'],
    "netcdf_output_dir": config['out_dir'],
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

model.run()

# %% [markdown]
# ### Create custom output variables from standard output variables.
# Below, we create a customized variable `hru_streamflow_out` from three other output variables. This variable represents each HRU's daily contribution to streamflow, and is useful when evaluating HRU water budgets.

# %%
hru_streamflow_out = sum(
    xr.load_dataarray(f"{config['out_dir']/ ff}.nc")
    for ff in ["sroff_vol", "ssres_flow_vol", "gwres_flow_vol"]
)
hru_streamflow_out.to_netcdf(config['out_dir'] / "hru_streamflow_out.nc")
del hru_streamflow_out

# %% [markdown]
# ### Filter `seg_outflow` for only segments that have gages
# To reduce the size of the output file, seg_outflow is only written for segments that have gages in the model, and the output is dimensioned by gage id for utility in notebook [6_streamflow_output_visualization.ipynb](./6_streamflow_output_visualization.ipynb).

# %%
for var in ["seg_outflow"]:
    data = xr.load_dataarray(f"{config['out_dir'] / var}.nc")
    data = subset_seg_outflow_to_poi_gages(
        data,
        poi_gage_segment=params.parameters["poi_gage_segment"],
        poi_gage_id=params.parameters["poi_gage_id"],
        nhm_seg=params.parameters["nhm_seg"],
    )
    out_file = f"{config['out_dir'] / var}.nc"
    data.to_netcdf(out_file)
    del data

# %%

# %%

# %% [markdown]
# ### Quick look at the recharge output

# %%
recharge = xr.load_dataarray(config['out_dir'] / "recharge.nc")
recharge

# %%
