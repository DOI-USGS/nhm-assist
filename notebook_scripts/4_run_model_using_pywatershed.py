# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.6
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import warnings
import pandas as pd
import pathlib as pl
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
root_folder = "nhm-assist"
root_dir = pl.Path(os.getcwd().rsplit(root_folder, 1)[0] + root_folder)
sys.path.append(str(root_dir))

from nhm_helpers.nhm_assist_utilities import load_subdomain_config
config = load_subdomain_config(root_dir)
# con.print(config)

# %%
import xarray as xr

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

# %% [markdown]
# ### Parameter file check
# `pywatershed` requires the soilzone variable "pref_flow_infil_frac" to be present in the parameter file. If the variable is not in the parameter file, it must be added as all zeros before passing the parameters to `pywatershed`.

# %%
params = pws.parameters.PrmsParameters.load(config['param_filename'])
if "pref_flow_infil_frac" not in params.parameters.keys():
    # Parameter objects are not directly editable in pywatershed,
    # so we export to an equivalent object we can edit, in this case
    # an xarray dataset, then we convert back
    params_ds = params.to_xr_ds()
    params_ds["pref_flow_infil_frac"] = params_ds.pref_flow_den[:] * 0.0
    params = pws.parameters.PrmsParameters.from_ds(params_ds)

# Force pref_flow_infil_frac to be zero when outside valid range 0-1

params_ds = params.to_xr_ds()

# Replace values < 0 or > 1 with 0
params_ds["pref_flow_infil_frac"] = params_ds["pref_flow_infil_frac"].where(
    (params_ds["pref_flow_infil_frac"] >= 0) & (params_ds["pref_flow_infil_frac"] <= 1), 
    0.0
)

# Convert back to PrmsParameters
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
# For streamflow, just keep output on the POIs.
# - 1 is related to the indexing in fortran; made a a tuple see above
wh_gages = (params.parameters["poi_gage_segment"] - 1,)
for var in ["seg_outflow"]:
    data = xr.load_dataarray(f"{config['out_dir'] / var}.nc")[:, wh_gages[0]]
    data = data.assign_coords(npoi_gages=("nhm_seg", params.parameters["poi_gage_id"]))
    out_file = f"{config['out_dir'] / var}.nc"
    data.to_netcdf(out_file)
    del data
