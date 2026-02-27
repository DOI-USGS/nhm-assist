# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.17.0
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
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))

from dotenv import load_dotenv

load_dotenv(
    dotenv_path=root_dir / ".env"
)  # this will load the environment variables from the .env file

from nhm_helpers.sf_data_retrieval_v2 import (
    create_nwis_sf_df,
    create_OR_sf_df,
    create_ecy_sf_df,
    create_sf_efc_df,
)
from nhm_helpers.nhm_hydrofabric_v2 import (
    create_hru_gdf,
    create_segment_gdf,
    create_poi_df,
    create_default_gages_file,
    read_gages_file,
)
from nhm_helpers.efc import plot_efc
from nhm_helpers.nhm_assist_utilities_v2 import (
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
# Critical in the evaluation of the NHM simulated flows is the comparison to observed flows. This notebook retrieves available streamflow observations from NWIS and two state agencies, the Oregon Water Resources Department (OWRD) and the Washington Department of Ecology (ECY), combines these data sets into one daily streamflow observations file with streamflow gage information and metadata, and writes the database out as a netCDF file (`sf_efc.nc`) to be used in Notebook "6_streamflow_output_visualization" and other notebooks in NHM-Assist. Included in the `sf_efc.nc` are Environmental Flow Components (EFC) for daily flows using a python workflow (also in this notebook) as described by [Risley and others, 2010](https://pubs.usgs.gov/sir/2010/5016/pdf/sir20105016.pdf). 
#
# This notebook also writes a default gages file (`default_gages.csv`) that includes gage information for gages in the parameter file and other NWIS gages that have data for the simulation period in the domain. A complete database of streamflow gages and observations in the model domain is necessary to evaluate the NHM and identify other gages that could be included in a model recalibration to improve the model performance.
#
# Three facts about streamflow observations and the NHM must be reviewed.
# - Streamflow observations are NOT used when running PRMS or `pywatershed`. These data are meant for comparison of simulated output only.
# - The NHM DOES use streamflow observations from NWIS in the model calibration workflow (not the streamflow file).
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
    default_gages_file=config["default_gages_file"],
    nwis_gage_nobs_min=config["nwis_gage_nobs_min"],
    seg_gdf=seg_gdf,
)

# %%
len(hru_gdf)

# %% [markdown]
# # Retrieve all NWIS gage information and streamflow observations.
# This function pulls time series data for all NWIS gages in the domain, and then filters data to the simulation period (`nwis_gages_cache.nc`), and creates `NWISgages.csv`. Both the time series data file and the NWISgages.csv contain all site information for gages with a period of record greater than the user specified threshold (`nwis_gage_nobs_min`, set in [notebook 0](./0_Workspace_setup.ipynb)) within the simulation period **AND** ALL gages in the parameter file regardless of a period of record less than the specified threshold.

# %%
# from nhm_helpers.nhm_assist_utilities import fetch_nwis_gage_info

# nwis_gage_info_aoi = fetch_nwis_gage_info(
#     root_dir=root_dir,
#     model_dir=config["model_dir"],
#     control_file_name=config["control_file_name"],
#     nwis_gage_nobs_min=config["nwis_gage_nobs_min"],
#     hru_gdf=hru_gdf,
#     seg_gdf=seg_gdf,
# )

# %% jupyter={"source_hidden": true}
# def fetch_single_nwis_gage(ii, nwis_start, nwis_end, poi_df, nwis_gage_nobs_min):
#     try:
#         NWISgage_data = nwis.get_record(
#             sites=str(ii),
#             service="dv",
#             start=nwis_start,
#             end=nwis_end,
#             parameterCd="00060",
#             StatCd="00003",
#         )

#         # Drop _cd columns
#         dropped = NWISgage_data.columns[NWISgage_data.columns.str.contains("_cd|_aux")]
#         if not dropped.empty:
#             print("Dropped columns:", list(dropped))
#             NWISgage_data = NWISgage_data.drop(columns=dropped)

#         # Rename column if needed
#         mean_col = [col for col in NWISgage_data.columns if "_Mean" in col][0]
#         if mean_col != "00060_Mean":
#             print(f"For gage {ii}, column '{mean_col}' was renamed '00060_Mean'.")
#             NWISgage_data.rename(columns={mean_col: "00060_Mean"}, inplace=True)

#         if NWISgage_data.empty:
#             return ii, "NO_DATA_IN_PERIOD"

#         if (
#             len(NWISgage_data.index) >= nwis_gage_nobs_min
#             or ii in poi_df["poi_id"].unique().tolist()
#         ):
#             return ii, NWISgage_data
#         else:
#             return ii, "TOO_FEW_OBS"
#     except Exception as e:
#         return ii, f"ERROR: {e}"

# %% jupyter={"source_hidden": true}
# ii = ["13214000"]  # list(nwis_gage_info_aoi.poi_id[1:2])
# ii

# %% jupyter={"source_hidden": true}
# from nhm_helpers.sf_data_retrieval import fetch_single_nwis_gage
# import numpy as np
# import pandas as pd

# control = pws.Control.load_prms(
#     pl.Path(
#         config["model_dir"] / config["control_file_name"],
#         warn_unused_options=False,
#     )
# )
# nwis_start = pd.to_datetime(str(control.start_time)).strftime("%Y-%m-%d")
# nwis_end = pd.to_datetime(str(control.end_time)).strftime("%Y-%m-%d")

# for i in ii:
#     tt = fetch_single_nwis_gage(
#         i, nwis_start, nwis_end, poi_df, config["nwis_gage_nobs_min"]
#     )
#     # print(len(tt[1].columns))
#     # Get index as a NumPy array (no .values)
#     pp = np.array(tt[1].index)

#     has_duplicates = len(np.unique(pp)) < pp.size
#     if has_duplicates:
#         print(f"{i} has duplicate flows for the same day.")
#     else:
#         print(f"{i} has NO duplicate flows for the same day.")

# %% jupyter={"source_hidden": true}
# df1 = tt[1]

# df2 = df1.loc[df1.iloc[:, 1] != df1.iloc[:, 2]]
# # df2

# df3 = df1.loc[df1.iloc[:, 1].isna()]
# df3

# %% jupyter={"source_hidden": true}
# import numpy as np

# pp = np.array(tt[1].index.values)
# pp
# has_duplicates = len(np.unique(pp)) < pp.size
# if has_duplicates == True:
#     print(f"{i} has duplicate flows for the same day."
# else:
#     pass

# %%
NWIS_df = create_nwis_sf_df(
    root_dir=root_dir,
    control_file_name=config["control_file_name"],
    model_dir=config["model_dir"],
    output_netcdf_filename=config["output_netcdf_filename"],
    hru_gdf=hru_gdf,
    poi_df=poi_df,
    nwis_gage_nobs_min=config["nwis_gage_nobs_min"],
    seg_gdf=seg_gdf,
)

# %%

# %% [markdown]
# ## Make the default gages file (default_gages.csv)
# The `default_gages.csv` contains gages from the parameter file and NWIS gages from the domain (`nwis_gages_cache.nc`). The gages from the parameter file are represented in the variable `poi_df`. The gages in the `default_gages.csv` are represented in the variable `gages_df` here. The `default_gages.csv` may be missing site information if there are gages in the parameter file that are not in NWIS. If this is the case, an error will be displayed below and the `default_gages.csv` must be manually updated, and the file must be renamed `gages.csv`, and this notebook must be re-run. If `gages.csv` exists, then gages in the `gages.csv` are represented in the variable `gages_df`.

# %%
default_gages_file = create_default_gages_file(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    control_file_name=config["control_file_name"],
    nwis_gage_nobs_min=config["nwis_gage_nobs_min"],
    hru_gdf=hru_gdf,
    poi_df=poi_df,
    seg_gdf=seg_gdf,
)

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
# The following cell creates the efc classification codes for the NWIS daily streamflow data, and daily streamflow data if collected from Washington or Oregon the data as an encoded netCDf file formatted to match the `sf.nc` file created during the NHM subdomain model extraction routine.
#
# EFCs include extreme low flows (1), low flows(2), high-flow pulses(3), small floods (4; 2-year events), and large floods (5; 10-year events). 

# %%
xr_streamflow = create_sf_efc_df(
    output_netcdf_filename=config["output_netcdf_filename"],
    owrd_df=owrd_df,
    ecy_df=ecy_df,
    NWIS_df=NWIS_df,
    gages_df=gages_df,
)

# %% [markdown]
# # Check streamflow observations file: plot discharge and efc information for a selected gage.
# The cell below plots data from the `sf_efc.nc` for diagnostic purposes using the start and end dates listed in the control file.

# %%
cpoi_id = xr_streamflow.poi_gage_id.values[1]  # "08049300" "130875049"
# cpoi_id = "130875049"
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
xr_streamflow

# %%
flows = xr_streamflow["discharge"]

# True where all times are NaN for each poi_id
all_nan_per_poi = flows.isnull().all(dim="time")

# Count poi_id with all-NaN flows
n_all_nan_poi = int(all_nan_per_poi.sum())
print(n_all_nan_poi)

# %%
# Get the poi_id values (as a DataArray)
poi_all_nan = all_nan_per_poi[all_nan_per_poi]  # boolean indexing on coord dim [web:19]
poi_ids_all_nan = poi_all_nan["poi_gage_id"].values

# %%
poi_ids_all_nan

# %%
