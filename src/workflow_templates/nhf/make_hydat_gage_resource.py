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
# from pyPRMS.metadata.metadata import MetaData
# from pyPRMS import ParameterFile
from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))

from assist.nhf.sf_data_retrieval_v2_1 import (
    create_nwis_sf_df,
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
hydat_nc_filename = root_dir / "data_dependencies/NHM_v1_1/TB/HYDAT_pois.nc"

# %%
import xarray as xr

with xr.open_dataset(hydat_nc_filename) as hydat:
    poi_vars = [var for var in hydat.data_vars if hydat[var].dims == ("poi_id",)]
    ds_poi_only = hydat[poi_vars]
    hydat_poi_info = ds_poi_only.to_dataframe().reset_index()
    hydat_poi_info["poi_agency"] = "HYDAT"

# %%
hydat_poi_info

# %%
# Suppose you want to move 'target_column' to the second position
col = "poi_agency"

# Get all columns
cols = list(hydat_poi_info.columns)

# Remove the column you want to move
cols.remove(col)

# Insert it at position 1 (second place)
cols.insert(1, col)

# Reorder the DataFrame
hydat_poi_info = hydat_poi_info[cols]



# %%
hydat_poi_info

# %%
resource_csv = pd.read_csv(config["model_dir"] / "resource_gages.csv")

# %%
resource_csv

# %%

# %%

# %%
filtered_df = hydat_poi_info[hydat_poi_info["poi_id"].isin(list(resource_csv.poi_id))]
filtered_df

# %%
duplicates = filtered_df[filtered_df.duplicated(subset="poi_id", keep=False)]

# %%
filtered_df = filtered_df.drop_duplicates()

# %%
filtered_df

# %%
filtered_list = list(filtered_df.poi_id)
len(filtered_list)

# %%
len(resource_csv)

# %%
filtered_df.to_csv(config["model_dir"] / "hydat_resource_gages.csv")

# %%
