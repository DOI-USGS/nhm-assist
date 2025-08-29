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

import pywatershed as pws
import xarray as xr
import numpy as np
import pandas as pd
import datetime

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
print(root_dir)
from nhm_helpers.nhm_assist_utilities import load_subdomain_config
from nhm_helpers import efc

config = load_subdomain_config(root_dir)

# %%

# %%
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements
from nhm_helpers.map_template import make_par_map
from nhm_helpers.nhm_assist_utilities import make_plots_par_vals
from nhm_helpers.nhm_helpers import *
from ipywidgets import widgets
from IPython.display import display

# Import Notebook Packages
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
# #### Segment ranking

# %%
# def hrus_by_poi_mod(pdb, poi):  # (custom code)
#     """
#     Extract subset of HRUs connected to the stream network upstream of slected poi.

#     Parameters
#     ----------
#     pdb : DataFrame
#         Database created using pyPRMS from parametr file
#     poi : string
#         Gage id


#     Returns
#     -------
#     List of HRUs for a poi or for pois in a list (gage)
#     """
#     if isinstance(poi, str):
#         poi = [poi]
#     elif isinstance(poi, KeysView):
#         poi = list(poi)

#     poi_hrus = {}
#     poi_segs = {}
#     nhm_seg = pdb.get("nhm_seg").data
#     pois_dict = pdb.poi_to_seg
#     seg_to_hru = pdb.seg_to_hru

#     # Generate stream network for the model
#     dag_streamnet = pdb.stream_network()

#     for cpoi in poi:
#         # Lookup global segment id for the current POI
#         dsmost_seg = [nhm_seg[pois_dict[cpoi] - 1]]

#         # Get subset of stream network for given POI
#         dag_ds_subset = subset_stream_network(dag_streamnet, set(), dsmost_seg)

#         # Create list of segments in the subset
#         toseg_idx = list(set(xx[0] for xx in dag_ds_subset.edges))

#         # Build list of HRUs that contribute to the POI
#         final_hru_list = []

#         for xx in toseg_idx:
#             try:
#                 for yy in seg_to_hru[xx]:
#                     final_hru_list.append(yy)
#             except KeyError:
#                 # Not all segments have HRUs connected to them
#                 # print(f'{cpoi}: Segment {xx} has no HRUs connected to it')
#                 pass
#         final_hru_list.sort()
#         hru_subset = hru_gdf[hru_gdf["nhm_id"].isin(final_hru_list)]
#         sum_hru_area = float(hru_subset["hru_area"].sum())

#         poi_hrus[cpoi] = sum_hru_area
#         poi_segs[cpoi] = len(toseg_idx)  # return number of segs

#     return poi_hrus, poi_segs

# %%
# _hrus_upstream = pdb.poi_upstream_hrus(poi_list[0])
# _hrus_upstream[poi_list[0]]

# %%
prms_meta = MetaData().metadata  # loads metadata functions for pyPRMS
pdb = ParameterFile(
    config["param_filename"], metadata=prms_meta, verbose=False
)  # loads parmaeterfile functions for pyPRMS

"""Make a dictionary of pois and the list of HRUs in the contributing area for each poi."""

poi_list = poi_df["poi_id"].values.tolist()
poi_hrus = {}
poi_segs = {}

for cpoi in poi_list:
    _hrus_upstream = pdb.poi_upstream_hrus(cpoi)
    _hru_subset = hru_gdf[hru_gdf["nhm_id"].isin(_hrus_upstream[cpoi])]
    _sum_hru_area = float(_hru_subset["hru_area"].sum())
    poi_hrus[cpoi] = _sum_hru_area

    _segs_upstream = pdb.poi_upstream_segments(cpoi)
    poi_segs[cpoi] = len(_segs_upstream[cpoi])


poi_df["poi_area"] = poi_df["poi_id"].map(poi_hrus)
subdomain_area = poi_df["poi_area"].max()
poi_df["poi_area_permyriad"] = (10000 * (poi_df["poi_area"] / subdomain_area)).astype(
    int
)
poi_df["poi_seg_count"] = poi_df["poi_id"].map(poi_segs)

poi_df["poi_name_alt"] = (
    "nseg"
    + poi_df["poi_seg_count"].astype(str)
    + "A"
    + poi_df["poi_area_permyriad"].astype(str)
)

poi_df.to_csv(config["model_dir"] / "poi_ranking.csv")

poi_df

# %%
"""Need to grad the lat/lon from the fabric for newly added non-gage pois to the par file."""

import geopandas as gpd

crs = 4326
geopackage_path = config["NHM_dir"] / "GFv1.1.gdb"
nhgf_gdf = gpd.read_file(geopackage_path, layer="POIs_v1_1").to_crs(crs)
nhgf_gdf["longitude"] = nhgf_gdf.geometry.x
nhgf_gdf["latitude"] = nhgf_gdf.geometry.y

# %%
"""
Updates the poi_df (gages_df) with user altered metadata in the gages.csv (nhgf.gdf) file, if present, or the default_gages.csv file

"""

count = 0
for idx, row in gages_df.iterrows():
    """
    Checks the gages_df for missing meta data and replace.

    """
    columns = ["latitude", "longitude"]
    for item in columns:
        if pd.isnull(row[item]):
            try:
                new_poi_name = "Not a gage poi."
                new_poi_agency = "NONE"
                nhm_seg = int(idx)
                new_item = float(
                    nhgf_gdf.loc[nhgf_gdf.poi_segment_v1_1 == nhm_seg, item].values[0]
                )
                print(nhm_seg, new_item)
                gages_df.loc[idx, item] = new_item
                gages_df.loc[idx, "poi_name"] = new_poi_name
                gages_df.loc[idx, "poi_agency"] = new_poi_agency

            except IndexError:
                nhm_seg = int(idx)
                new_item = -9999
                # con.print(f"{nhm_seg}, not in NHGF.")

# %%
# gages_df.reset_index(inplace=True)
gages_df.to_csv(config["model_dir"] / "default_gages_mod.csv", index=True)
gages_df.sample(20)

# %%
