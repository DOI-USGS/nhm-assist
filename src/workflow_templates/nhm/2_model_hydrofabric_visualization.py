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
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements
from nhm_helpers.map_template import make_hf_map
from nhm_helpers.nhm_assist_utilities import load_subdomain_config

config = load_subdomain_config(root_dir)
# con.print(config)

# %% [markdown]
# ## Introduction
# The purpose of this notebook is to assist in verifying NHM subdomain model location, HRU to segment connections, segment routing order, and the locations of gages and associated streamflow segments. This notebook displays hydrofabric elements: HRUs, streamflow segments, and gages both in the parameter file and additional NWIS gages in the domain (potential streamflow gages).
#
# The cell below reads the NHM subdomain model hydrofabric elements for mapping purposes using make_hf_map_elements() and writes general NHM subdomain model run and hydrofabric information.

# %% [markdown]
# ## Make interactive map of hydrofabric elements
# The cell below creates a map that displays NHM subdomain model hydrofabric elements: HRUs, streamflow segments, and gages both in the parameter file and additional NWIS gages in the domain (potential streamflow gages). Gage locations are overlays in the map of NHM headwater basins (HWs) that are color coded to calibration type: yellow indicates HWs that were calibrated with statistical streamflow targets at the HW outlet; green indicates HWs that were further calibrated with streamflow observations at selected gage locations.

# %%
(
    hru_gdf,
    hru_txt,
    hru_cal_level_txt,
    seg_gdf,
    seg_txt,
    nwis_gages_aoi,
    poi_df,
    gages_df,
    gages_txt,
    gages_txt_nb2,
    HW_basins_gdf,
    HW_basins,
) = make_hf_map_elements(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    control_file_name=config["control_file_name"],
    nwis_gages_file=config["nwis_gages_file"],
    gages_file=config["gages_file"],
    default_gages_file=config["default_gages_file"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
    nwis_gage_nobs_min=config["nwis_gage_nobs_min"],
)
con.print(
    f"{config['workspace_txt']}\n",
    f"\n{gages_txt}{seg_txt}{hru_txt}",
    f"\n     {hru_cal_level_txt}\n",
    f"\n{gages_txt_nb2}",
)

# %%
map_file = make_hf_map(
    root_dir=root_dir,
    hru_gdf=hru_gdf,
    HW_basins_gdf=HW_basins_gdf,
    HW_basins=HW_basins,
    poi_df=poi_df,
    poi_id_sel="",
    seg_gdf=seg_gdf,
    nwis_gages_aoi=nwis_gages_aoi,
    gages_df=gages_df,
    html_maps_dir=config["html_maps_dir"],
    Folium_maps_dir=config["Folium_maps_dir"],
    param_filename=config["param_filename"],
    subdomain=config["subdomain"],
)

# %% [markdown]
# # Want to Add a potential gage to the parameter file? [Click here!](./add_pois_to_parameters.ipynb)

# %%
