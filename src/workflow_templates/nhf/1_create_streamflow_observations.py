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

import pandas as pd

# import pathlib as pl
from pyPRMS.metadata.metadata import MetaData
from pyPRMS import ParameterFile
from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg
root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"

from dotenv import load_dotenv

load_dotenv(
    dotenv_path=root_dir / ".env"
)  # this will load the environment variables from the .env file


# Changed path here
from assist.nhf.sf_data_retrieval_v2_1 import (
    # create_waterdata_sf_df,
    create_waterdata_sf_df,
    create_OR_sf_df,
    create_ecy_sf_df,
    create_sf_efc_df,
)
from assist.nhf.nhm_hydrofabric_v2 import (
    create_hru_gdf,
    create_segment_gdf,
    create_poi_df,
    create_default_gages_file,
    read_gages_file,
)
from assist.nhf.efc import plot_efc
from assist.nhf.nhm_assist_utilities_v2 import (
    make_obs_plot_files,
    delete_notebook_output_files,
    load_subdomain_config,
)

config = load_subdomain_config(root_dir)


# %%
delete_notebook_output_files(
    notebook_output_dir=config["notebook_output_dir"], model_dir=config["model_dir"]
)

# %% [markdown]
# # Introduction

# %% [markdown]
# Critical in the evaluation of the NHM simulated flows is the comparison to observed flows. This notebook retrieves available streamflow observations from WaterData and two state agencies, the Oregon Water Resources Department (OWRD) and the Washington Department of Ecology (ECY), combines these data sets into one daily streamflow observations file with streamflow gage information and metadata, and writes the database out as a netCDF file (`sf_efc.nc`) to be used in Notebook "6_streamflow_output_visualization" and other notebooks in NHM-Assist. Included in the `sf_efc.nc` are Environmental Flow Components (EFC) for daily flows using a python workflow (also in this notebook) as described by [Risley and others, 2010](https://pubs.usgs.gov/sir/2010/5016/pdf/sir20105016.pdf). 
#
# This notebook also writes a default gages file (`default_gages.csv`) that includes gage information for gages in the parameter file and other WaterData gages that have data for the simulation period in the domain. A complete database of streamflow gages and observations in the model domain is necessary to evaluate the NHM and identify other gages that could be included in a model recalibration to improve the model performance.
#
# Three facts about streamflow observations and the NHM must be reviewed.
# - Streamflow observations are NOT used when running PRMS or `pywatershed`. These data are meant for comparison of simulated output only.
# - The NHM DOES use streamflow observations from WaterData in the model calibration workflow (not the streamflow file).
# - Limited streamflow gage information is stored in the parameter file.
#
# The parameter file has few parameters associated with gages (dimensioned by npoigages):
# - poi_gage_id, the agency identification number
# - poi_gage_segment, model segment identification number (nhm_seg) on which the gage falls (1 gage/segment only),
# - poi_type, historically used, but not currently used.
#
# It is important to note that the gages in the parameter file are NOT a complete set of gages in the model domain, and were NOT all used to calibrate the model.
#
# The cell below reads the NHM subdomain model hydrofabric elements for mapping HRUs and gages.

# %%
hru_gdf, hru_text = create_hru_gdf(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
)

seg_gdf, seg_txt = create_segment_gdf(
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
)

poi_df = create_poi_df(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    param_filename=config["param_filename"],
    control_file_name=config["control_file_name"],
    hru_gdf=hru_gdf,
    gages_file=config["gages_file"],
    resource_gages_file=config["resource_gages_file"],
    default_gages_file=config["default_gages_file"],
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
    seg_gdf=seg_gdf,
)

# %%
len(hru_gdf)

# %% [markdown]
# # Retrieve all WaterData gage information and streamflow observations.
# This function pulls time series data for all WaterData gages in the domain, and then filters data to the simulation period (`waterdata_gages_cache.nc`), and creates `WaterDataGages.csv`. Both the time series data file and the NWISgages.csv contain all site information for gages with a period of record greater than the user specified threshold (`waterdata_gage_nobs_min`, set in [notebook 0](./0_Workspace_setup.ipynb)) within the simulation period **AND** ALL gages in the parameter file regardless of a period of record less than the specified threshold.

# %%
waterdata_df = create_waterdata_sf_df(
    root_dir=root_dir,
    control_file_name=config["control_file_name"],
    model_dir=config["model_dir"],
    output_netcdf_filename=config["output_netcdf_filename"],
    hru_gdf=hru_gdf,
    poi_df=poi_df,
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
    seg_gdf=seg_gdf,
)

# %% [markdown]
# ## Make the default gages file (default_gages.csv)
# The `default_gages.csv` contains gages from:
#     -the parameter file (`poi_df`)
#     -any other USGS WaterData gages having streamflow data from 1980-2026 present in the domain (`waterdata_gages_cache.nc`). 
#     
# The gages in the `default_gages.csv` are represented in the variable `gages_df`. The `default_gages.csv` may be missing metadata if not found in the `resourece_gages.csv`, or the NLDI and USGS WaterData databases. If this is the case, an error will be displayed below. The gage numbers for gages missing metadata will be added to the resource_file, the file must be manually updated, and this notebook must be re-run. 
#
# Note: If the user wants to add a gage to the default gages file to be displayed in the notebooks (wihtout adding the gage to the model parameter file), the user can add the gage and its metadata and save the file as `gages.csv`. When the notebook is rerun, then the `gages_df` will me made using the `gages.csv` and NOT `default_gages.csv`.

# %%
default_gages_file = create_default_gages_file(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    control_file_name=config["control_file_name"],
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
    hru_gdf=hru_gdf,
    poi_df=poi_df,
    seg_gdf=seg_gdf,
)

# %%

# %%
gages_df, gages_txt, gages_txt_nb2 = read_gages_file(
    model_dir=config["model_dir"],
    poi_df=poi_df,
    gages_file=config["gages_file"],
)

con.print(
    f"\n{gages_txt}",
    f"\n{gages_txt_nb2}",
)

# %% [markdown]
# #  NHM subdomains within Oregon and Washington: retrieve state collected daily streamflow data
# This section was developed to integrate state collected records of streamflow for NHM subdomain models related to hydrological investigations in the states of Washington and Oregon. This section must still be run if your subdomain model lies outside those state boundaries. Ultimately future software updates will incorporate additional state databases. 
#
# Cells in this section use gages listed in the `gages_df` (created from gages listed in the `default_gages.csv`, or the updated version, `gages.csv`). This will be useful later for the user when adding gages to the subdomain model, or for model validation/calibration. Also, the `gages.csv` can be used to record gages that cannot be in the parameter file, such as the case where multiple gages cannot be associated with the same segment in the parameter file. Additional gages in the domain that cannot be in listed in the parameter file may appended to the `default_gages.csv` and therefore included in the `gages_df` and `sf_efc.nc`.
#
# The first cell below will retrieve available daily streamflow data from [Oregon Water Resources Department (OWRD)](https://apps.wrd.state.or.us/apps/sw/hydro_near_real_time/)
#
# The second cell below will retrieve available daily streamflow data from [Washington Department of Ecology (ECY)](https://waecy.maps.arcgis.com/apps/Viewer/index.html?appid=832e254169e640fba6e117780e137e7b)

# %%
owrd_df = create_OR_sf_df(
    root_dir=root_dir,
    control_file_name=config["control_file_name"],
    model_dir=config["model_dir"],
    output_netcdf_filename=config["output_netcdf_filename"],
    hru_gdf=hru_gdf,
    gages_df=gages_df,
)

# %%
ecy_df = create_ecy_sf_df(
    root_dir=root_dir,
    control_file_name=config["control_file_name"],
    model_dir=config["model_dir"],
    output_netcdf_filename=config["output_netcdf_filename"],
    hru_gdf=hru_gdf,
    gages_df=gages_df,
)

# %% [markdown]
# # Create streamflow observations file with appended EFC values (sf_efc.nc)
# The following cell creates the efc classification codes for the WaterData daily streamflow data, and daily streamflow data if collected from Washington or Oregon the data as an encoded netCDf file formatted to match the `sf.nc` file created during the NHM subdomain model extraction routine.
#
# EFCs include extreme low flows (1), low flows(2), high-flow pulses(3), small floods (4; 2-year events), and large floods (5; 10-year events). 

# %%
xr_streamflow = create_sf_efc_df(
    output_netcdf_filename=config["output_netcdf_filename"],
    owrd_df=owrd_df,
    ecy_df=ecy_df,
    waterdata_df=waterdata_df,
    gages_df=gages_df,
)

# %%
xr_streamflow

# %% [markdown]
# # Check streamflow observations file: plot discharge and efc information for a selected gage.
# The cell below plots data from the `sf_efc.nc` for diagnostic purposes using the start and end dates listed in the control file.

# %%
cpoi_id = xr_streamflow.poi_gage_id.values[0]  # "08049300" "130875049"
# cpoi_id = "14053000"
print(
    f"Daily streamflow with EFC classifications for gage: {cpoi_id}; Some gages may show no data because some gages in the parameter file have data outside the simulation period."
)

# control = pws.Control.load_prms(
#     model_dir / control_file_name, warn_unused_options=False
# )

start_date = config[
    "start_date"
]  # pd.to_datetime(str(control.start_time)).strftime("%m/%d/%Y")
end_date = config[
    "end_date"
]  # pd.to_datetime(str(control.end_time)).strftime("%m/%d/%Y")
ds_sub = xr_streamflow.sel(poi_gage_id=cpoi_id, time=slice(start_date, end_date))
ds_sub = ds_sub.to_dataframe()
flow_col = "discharge"
plot_efc(ds_sub, flow_col)

# %% [markdown]
# # Create daily streamflow observation plots
# #### The cell below creates plots of daily streamflow observations and saves the plots as html.txt files for all gages listed in the `gages_df`.

# %%
make_obs_plot_files(
    start_date=config["start_date"],
    end_date=config["end_date"],
    gages_df=gages_df,
    xr_streamflow=xr_streamflow,
    Folium_maps_dir=config["Folium_maps_dir"],
)

# %%
