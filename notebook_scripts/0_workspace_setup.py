# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.18.1
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
print(root_dir)
#pppo


# %% [markdown]
# ## Introduction
# The purpose of this notebook is to setup paths and directories for all nhm-assist notebooks using a provided or requested National Hydrologic Model (NHM) subdomain model (`model_dir`) **Note: all nhm-assist output files, maps, and plots are saved to the subdomain model folder.**
# A sample NHM subdomain model is provided in nhm-assist `domain_data` folder for the Willamette River subdomain.

# %% [markdown]
# ### A National Hydrologic Model (NHM) subdomain model
# A NHM subdomain model is extracted from NHM domain (CONUS) using an automated workflow that generates a complete set of Preciptation Runoff Modeling System (PRMS) input files that contain the data and parameters required for a NHM-PRMS model [Regan and others, 2018](https://pubs.usgs.gov/publication/tm6B9). This tool is written in the [Python language](https://www.python.org) and is designed to be run from the command line on [USGS high-performance computing resources](https://www.usgs.gov/advanced-research-computing). At this time, users do not need to download this software and instead can request a subdomain model following these steps:
#
# 1. Go to the web page [https://www.sciencebase.gov/catalog/item/5e29b87fe4b0a79317cf7df5](https://www.sciencebase.gov/catalog/item/5e29b87fe4b0a79317cf7df5)
# 2. Click the child item titled, [“GIS Features of the Geospatial Fabric for the National Hydrologic Model, version 1.1.”](https://www.sciencebase.gov/catalog/item/5e29d1a0e4b0a79317cf7f63)
# 3. Download attached files "GFv1.1.gdb.zip" and compare NHM segments to your area-of-interest.
# 4. Send an email to pnorton@usgs.gov that includes the following:
#    * Name, Email address, Organization, and optionally, Phone;
#    * Using GFv1.1.gdb, include one or more national model segments (nhm_seg) associated with watershed outlet points in your area-of-interest.
#    * Include a short descriptive summary of your modeling application and **specify using `pywatershed`** with the NHM subdomain model.
# 5. **Once you have received an NHM subdomain model, unzip and place the model folder in the nhm-assist `domain_data` folder.**

# %% [markdown]
# ### USGS NHM training (USGS personnel only)
# If you have been provided a NHM subdomain model, such as the example subdomain "willamette_river", it can be downloaded from the USGS [HyTEST](https://hytest-org.github.io/hytest/doc/About.html) OSN storage pod by following these steps.
# 1. Open up a miniforge prompt.
# 2. `cd` to the location of the cloned **nhm-assist** repository folder
# 3. type `python pull_domain.py --name=willamette_river`

# %% [markdown]
# ## Workspace Setup
# The default paths to subdomain model files are relative to the provided or requested NHM subdomain model folder (variable `model_dir`) placed, specifically, in the "nhm-assist/domain_data" folder. If the subdomain model folder is placed in a different location, then the `model_dir` path must be modified manually by the user to reflect that location. **Note: all nhm-assist output files, maps, and plots are saved to the subdomain model folder.**
#
# ### The nhm-assist repository is designed to access critical supporting documents placed in 2 repository subfolders:
#
# 1. The **data_dependencies** folder with needed supporting files 
#     - **[HUC2](https://www.sciencebase.gov/catalog/item/6407a507d34e76f5f75e39ec)**
#     - **NHM-V1_1*** not included in the NHM v1.1 data release [(Markstrom and others, 2024).](https://www.sciencebase.gov/catalog/item/626c0d67d34e76103cd2ce4a)
#
# 2. The **data_domain** folder contains the NHM subdomain model folder(s).
#     Any **NHM subdomain model folder** should contain:
#     - **control.default.bandit** (a control file)
#     - **myparam.param** (a parameter file)
#     - **sf_data.nc** (an optional streamflow observations file not used by nhm-assist)
#     - **cbh.nc** (an input data file)
#     - **GIS** folder containing
#         - **model_nhru.shp**
#         - **model_nsegment.shp**
#         - **model_npoigages.shp**
#         - and/or **model_layers.gpkg**
#
# >Note: If these file names have been changed, then the path names must be changes as well in this notebook (below)

# %% [markdown]
# ### The nhm-assist will create additional files and folders in NHM subdomain folder. These include:
#
# - **default_gages.csv**
# - **NWISgages.csv**
#  - **tmin.nc**
# - **tmax.nc**
# - **prcp.nc**
# - **model_output** folder
# - **notebook_output_files** folder containing:
#     - **Folium_maps** folder
#     - **html_maps** folder
#     - **html_plots** folder
#     - **nc_files** folder
#
# **Note:** If subfolders do no exist, they will be created when needed.
#

# %% [markdown]
# ## **User Provided Information**
# <font size=4>The user must provide and/or review information in the cells following <font color='green'>&#x270D;**Enter Information:**</font> prompts. 

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **selected NHM domain folder name**.</font><br>
# <font size = '3'>The default is set to the example NHM subdomain model name, "willamette_river". Note: The default paths to subdomain model files are relative to the provided or requested NHM subdomain model folder (variable model_dir) placed, specifically, in the "nhm-assist/domain_data" folder. If the subdomain model folder is placed in a different location, then the model_dir path must be modified manually by the user to reflect that location. Note: all nhm-assist output files, maps, and plots are saved to the subdomain model folder.</font>

# %%
subdomain = "Walla_Walla"

model_dir = root_dir / "domain_data" / subdomain

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **GIS file format**. </font><br>
# <font size = '3'>The default format is a geopackage (**.gpkg**) but other formats such as ESRI shape file (**.shp**) may have been provided.

# %%
GIS_format = ".gpkg"

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **parameter file name**. </font><br>
# <font size = '3'> The default file name, **myparam.param**, is the name of the parameter file provided with NHM subdomain models. If another parameter file is desired or the name has been changed, modify `param_file` here:

# %%
param_file = "myparam.param"
# param_file = "myparam_addl_gages.param"
param_filename = model_dir / param_file

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **control file name**. </font><br>
# <font size = '3'> The default file name, **control.default.bandit** is the name of the control file provided with NHM subdomain models. If another control file is desired or the name has been changed, modify `control_file_name` here:

# %%
control_file_name = "control.default.bandit"
#control_file_name = "control.bandit"

control = pws.Control.load_prms(
    model_dir / control_file_name, warn_unused_options=False
)

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **Minimum number of total streamflow observations (days) at a gage**.</font><br> 
# <font size = '3'> Notebook 2 displays additional NWIS gages NOT listed the parameter file. `nwis_gage_nobs_min` is used to identify gages from NWIS that have a total number of daily stream observations >= `nwis_gage_nobs_min`.

# %%
nwis_gage_nobs_min = 365  # days

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **List of parameters**.</font><br>
# <font size = '3'> Notebook 3 visualizes parameter values from the parameter file. Type the parameters you wish to visualize in the list(s) below. To view complete lists of parameters, copy/paste the functions below into a code block. The default parameters in the list below represent parameters calibrated during calibration of the NHM version 1.1. Calibrated values from NHM v 1.1 are displayed in Notebook 3 ([Markstrom and others, 2024](https://www.sciencebase.gov/catalog/item/626c0d67d34e76103cd2ce4a)). More information about NHM parameters can be found in [Markstrom and others, 2015](https://water.usgs.gov/water-resources/software/PRMS/PRMS_tables_5.2.1.pdf)
# >
# ```
# from nhm_helpers.nhm_assist_utilities import bynhru_parameter_list, bynmonth_bynhru_parameter_list, bynsegment_parameter_list
# bynhru_parameter_list(param_filename)
# bynmonth_bynhru_parameter_list(param_filename)
# bynsegment_parameter_list(param_filename)
# ```

# %%
# List(s) of NHM calibration parameters with different dimensions
nhru_params = [
    "carea_max",
    "emis_noppt",
    "fastcoef_lin",
    "freeh2o_cap",
    "gwflow_coef",
    "potet_sublim",
    "rad_trncf",
    "slowcoef_sq",
    "smidx_coef",
    "smidx_exp",
    "snowinfil_max",
    "soil2gw_max",
    "soil_moist_max",
    "soil_rechr_max_frac",
    "ssr2gw_exp",
    "ssr2gw_rate",
]

nhru_nmonths_params = [
    "adjmix_rain",
    "cecn_coef",
    "jh_coef",
    "radmax",
    "rain_cbh_adj",
    "snow_cbh_adj",
    "tmax_allrain_offset",
    "tmax_allsnow",
    "tmax_cbh_adj",
    "tmin_cbh_adj",
]

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **List of output variables**.</font><br>
# <font size = '3'> Notebooks 5 and 6 visualize model output variables from the output file file. List the output variables desired to visualize. To find a list of additional variables for each process, use ".get_variables()". Examples are below.
#
# ```python
# pws.PRMSCanopy.get_variables()
# pws.PRMSSnow.get_variables()
# pws.PRMSRunoff.get_variables()
# pws.PRMSSoilzone.get_variables()
# pws.PRMSGroundwater.get_variables()
# pws.PRMSChannel.get_variables()
# pws.PRMSStarfit.get_variables()
# pws.meta.find_variables([pws.PRMSChannel.get_variables()[2]])
# ```

# %%
selected_output_variables = [
    "gwres_flow",
    "gwres_flow_vol",
    "gwres_sink",
    "gwres_stor",
    "gwres_stor_change",
    "hru_actet",
    "net_ppt",
    "net_rain",
    "net_snow",
    "recharge",
    "seg_outflow",
    "snowmelt",
    "sroff",
    "sroff_vol",
    "ssres_flow",
    "ssres_flow_vol",
    "ssres_stor",
    "unused_potet",
]

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **Display output in calendar years (January 1st - December 31st) or water years (October 1st - September 30th)**.</font><br>
# <font size = '3'> Notebooks 5 and 6 visualize model output variables based upon calendar years or water years.
# <br>Default is water years set to **True**. Change to **False** if calendar years are preferred.

# %%
water_years = True

# %% [markdown]
# <font size = '3'>All needed information has been provided above. Run the cell below to create the needed objects, paths and directories for nhm-assist notebooks.
# You're <font size=5 color="red">**NOT FINISHED YET! SAVE YOUR NOTEBOOK**</font> <font size = '3'>to retain entered information!

# %%
# Establish paths and file names
gages_file = model_dir / "gages.csv"
default_gages_file = model_dir / "default_gages.csv"
nwis_gages_file = model_dir / "NWISgages.csv"
output_netcdf_filename = model_dir / "notebook_output_files/nc_files/sf_efc.nc"
NHM_dir = root_dir / "data_dependencies/NHM_v1_1"
prms_meta = MetaData().metadata
pdb = ParameterFile(param_filename, metadata=prms_meta, verbose=False)

# Create/verify Jupyter notebooks output folder and subfolders in the model directory.
out_dir = model_dir / "output"
out_dir.mkdir(parents=True, exist_ok=True)

notebook_output_dir = model_dir / "notebook_output_files"
notebook_output_dir.mkdir(parents=True, exist_ok=True)

Folium_maps_dir = notebook_output_dir / "Folium_maps"
Folium_maps_dir.mkdir(parents=True, exist_ok=True)

html_maps_dir = notebook_output_dir / "html_maps"
html_maps_dir.mkdir(parents=True, exist_ok=True)

html_plots_dir = notebook_output_dir / "html_plots"
html_plots_dir.mkdir(parents=True, exist_ok=True)

nc_files_dir = notebook_output_dir / "nc_files"
nc_files_dir.mkdir(parents=True, exist_ok=True)

# Print messages to display
workspace_txt = f"NHM model domain: [bold black]{subdomain}[/bold black], parameter file: [bold black]{param_file}[/bold black]\nSimulation and observation data range: {pd.to_datetime(str(control.start_time)).strftime('%m/%d/%Y')} - {pd.to_datetime(str(control.end_time)).strftime('%m/%d/%Y')} (from [bold]{control_file_name}[/bold])."

# %%
import yaml

dict_file = {
    "subdomain": subdomain,
    "model_dir": str(model_dir),
    "GIS_format": GIS_format,
    "param_file": param_file,
    "param_filename": str(param_filename),
    "control_file_name": control_file_name,
    "nwis_gage_nobs_min": nwis_gage_nobs_min,
    "nhru_params": nhru_params,
    "nhru_nmonths_params": nhru_nmonths_params,
    "selected_output_variables": selected_output_variables,
    "water_years": water_years,
    "gages_file": str(model_dir / "gages.csv"),
    "default_gages_file": str(model_dir / "default_gages.csv"),
    "nwis_gages_file": str(model_dir / "NWISgages.csv"),
    "output_netcdf_filename": str(
        model_dir / "notebook_output_files/nc_files/sf_efc.nc"
    ),
    "NHM_dir": str(root_dir / "data_dependencies/NHM_v1_1"),
    "out_dir": str(model_dir / "output"),
    "notebook_output_dir": str(model_dir / "notebook_output_files"),
    "Folium_maps_dir": str(notebook_output_dir / "Folium_maps"),
    "html_maps_dir": str(notebook_output_dir / "html_maps"),
    "html_plots_dir": str(notebook_output_dir / "html_plots"),
    "nc_files_dir": str(notebook_output_dir / "nc_files"),
    "start_date" : str(control.start_time),# pd.to_datetime(str(control.start_time)).strftime("%m/%d/%Y")
    "end_date" : str(control.end_time),# pd.to_datetime(str(control.end_time)).strftime("%m/%d/%Y")
    "workspace_txt": f"NHM model domain: [bold black]{subdomain}[/bold black], parameter file: [bold black]{param_file}[/bold black]\nSimulation and observation data range: {pd.to_datetime(str(control.start_time)).strftime('%m/%d/%Y')} - {pd.to_datetime(str(control.end_time)).strftime('%m/%d/%Y')} (from [bold]{control_file_name}[/bold]).",
}

with open(root_dir / "subdomain_config.yaml", "w") as file:
    documents = yaml.dump(dict_file, file)

# %%
