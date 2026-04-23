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

from nhm_helpers.nhm_assist_utilities import (
    make_plots_par_vals,
    create_append_gages_to_param_file,
    make_myparam_addl_gages_param_file,
    load_subdomain_config,
)
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements
from nhm_helpers.map_template import make_par_map

config = load_subdomain_config(root_dir)
# con.print(config)


# %%
from ipywidgets import widgets
from IPython.display import display

# Import Notebook Packages
import numpy as np
import geopandas as gpd
from shapely.geometry import Point, LineString
import warnings
from collections.abc import KeysView
import networkx as nx
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
from rich import pretty

pretty.install()
warnings.filterwarnings("ignore")

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

# %% [markdown]
# ## Run the cell below makes a .csv file that is used to select additional gages to append the paramter file.

# %%
create_append_gages_to_param_file(
    gages_df=gages_df,
    seg_gdf=seg_gdf,
    poi_df=poi_df,
    model_dir=config["model_dir"],
)

# %% [markdown]
# ## Run the cell below to add the gages listed in the additional gages to append .csv file to the parameter file.

# %%
make_myparam_addl_gages_param_file(
    model_dir=config["model_dir"],
    param_filename=config["param_filename"],
)

# %% [markdown]
# ### To view the model with the new parameter file, update the `param_file` in [0_workspace_setup](./0_workspace_setup.ipynb). We strongly recommend renaming the new parameter file, delete the `notebook_output_files` folder in the model directory and delete the `output` folder in the model directory. Then, rerun all notebooks.

# %%
