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
# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhf_assist", 1)[0] + "nhf_assist")
sys.path.append(str(root_dir))
from helpers.nhm_hydrofabric_v2 import make_hf_map_elements
from helpers.map_template_v2 import make_hf_map
from helpers.nhm_assist_utilities_v2 import load_subdomain_config, find_missing_gage_info, fetch_non_ref_npoigages_info, fetch_ref_npoigages_info
import topojson


config = load_subdomain_config(root_dir)
#con.print(config)

# %% [markdown]
# ## Introduction
# The purpose of this notebook is to assist in verifying NHM subdomain model location, HRU to segment connections, segment routing order, and the locations of gages and associated streamflow segments. This notebook displays hydrofabric elements: HRUs, streamflow segments, and gages both in the parameter file and additional NWIS gages in the domain (potential streamflow gages).
#
# The cell below reads the NHM subdomain model hydrofabric elements for mapping purposes using make_hf_map_elements() and writes general NHM subdomain model run and hydrofabric information.

# %% jupyter={"source_hidden": true}
def find_nearest_endpoint(points_gdf, lines_gdf, line_id_col):
    points_gdf = points_gdf[["poi_gage_id", "poi_type", "geometry"]]

    # Explode MultiLineStrings into individual LineStrings: This prevents the NotImplementedError with multi-part geometries
    lines_exploded = lines_gdf.explode(index_parts=False)

    # Extract start and end points for every exploded line: .interpolate(0, normalized=True) gets the start; 1 gets the end
    start_pts = lines_exploded.copy()
    start_pts["geometry"] = lines_exploded.geometry.interpolate(0, normalized=True)

    end_pts = lines_exploded.copy()
    end_pts["geometry"] = lines_exploded.geometry.interpolate(1, normalized=True)

    # Combine all endpoints into a single candidate GDF
    endpoints_gdf = pd.concat([end_pts], ignore_index=True)

    # Perform the nearest join: distance_col automatically calculates 'dist_to_end'
    result_endpoints = gpd.sjoin_nearest(
        points_gdf,
        endpoints_gdf[[line_id_col, "geometry", "segment_id"]],
        how="left",
        distance_col="dist_to_end",
    )

    if "index_right" in result_endpoints.columns:
        result_endpoints = result_endpoints.drop(columns="index_right")

    # Where gages are located near a confluence, 2 endpoints are returned.
    # The endpoint associated with the closest segment to the gage will be selected

    dup_mask = result_endpoints.duplicated(
        subset="poi_gage_id", keep=False
    )  # Finds rows with duplicated gages (poi_ids)
    dups_df = result_endpoints[dup_mask].copy()  # all duplicated rows
    uniq_df = result_endpoints[~dup_mask].copy()  # all non-duplicated rows

    # Unique results are saved as a df to concat later
    results = uniq_df.copy()[
        ["poi_gage_id", "segment_id", "nhm_seg_id", "poi_type", "geometry"]
    ]

    """
    Now we have to deal with the duplicates
    """
    # map line geometries into dups_df
    line_geom_map = lines_gdf.set_index("nhm_seg_id")["geometry"]
    dups_df["line_geom"] = dups_df["nhm_seg_id"].map(line_geom_map)

    # distance between point geometry and its line geometry
    dups_df["dist_to_line"] = dups_df.apply(
        lambda r: r.geometry.distance(r.line_geom), axis=1
    )

    dups_df = dups_df.sort_values(
        by=["poi_gage_id", "dist_to_line"], ascending=[True, True]
    )
    dups_df = dups_df.drop_duplicates(subset=["poi_gage_id"], keep="first")
    results2 = dups_df.copy()[
        ["poi_gage_id", "segment_id", "nhm_seg_id", "poi_type", "geometry"]
    ]

    combined = pd.concat([results, results2], ignore_index=True)

    return combined


# %% [markdown]
# ## Make interactive map of hydrofabric elements
# The cell below creates a map that displays NHM subdomain model hydrofabric elements: HRUs, streamflow segments, and gages both in the parameter file and additional NWIS gages in the domain (potential streamflow gages). Gage locations are overlays in the map of NHM headwater basins (HWs) that are color coded to calibration type: yellow indicates HWs that were calibrated with statistical streamflow targets at the HW outlet; green indicates HWs that were further calibrated with streamflow observations at selected gage locations.

# %%
(
    hru_gdf,
    hru_txt,
    # hru_cal_level_txt,
    seg_gdf,
    seg_txt,
    nwis_gages_aoi,
    poi_df,
    gages_df,
    gages_txt,
    gages_txt_nb2,
    # HW_basins_gdf,
    # HW_basins,
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
    # f"\n     {hru_cal_level_txt}\n",
    f"\n{gages_txt_nb2}",
)

# %%
ref_npoigages_df = fetch_ref_npoigages_info(root_dir, config["model_dir"], hru_gdf)

# %%
non_ref_npoigages_df = fetch_non_ref_npoigages_info(
    root_dir, config["model_dir"], hru_gdf
)

# %%
map_file = make_hf_map(
    root_dir=root_dir,
    hru_gdf=hru_gdf,
    # HW_basins_gdf=HW_basins_gdf,
    # HW_basins=HW_basins,
    poi_df=poi_df,
    poi_gage_id_sel="",
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

# %% [markdown]
# ### Find the ref gages

# %%
import glob
import os

# list your three directories here (relative or absolute)
dirs = [
    root_dir / "data_dependencies" / "ref_gages" / "region17",
    root_dir / "data_dependencies" / "ref_gages" / "region16",
    root_dir / "data_dependencies" / "ref_gages" / "region18",
]

# collect all matching files from the three directories
files = []
for d in dirs:
    # adjust pattern if needed, e.g. "*.txt" or "output_*.txt"
    files.extend(glob.glob(os.path.join(d, "output_*.txt")))

# extract the numeric part after "_" and before ".txt"
monitoring_station_number_list = []
for f in files:
    base = os.path.basename(f)  # e.g. "output_10396000.txt"
    num_str = base.split("_")[1].split(".")[0]  # "10396000"
    monitoring_station_number_list.append((num_str))  # or keep as string if you prefer

print(len(list(set(monitoring_station_number_list))))
print(len(monitoring_station_number_list))

# %%
import glob
import os
import pydot
import networkx as nx
from dataretrieval import waterdata
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(
    dotenv_path=root_dir / ".env"
)  # this will load the environment variables from the .env file


# def fetch_ref_npoigages_info(root_dir, model_dir, hru_gdf):

#     # list your three directories here (relative or absolute)
#     dirs = [
#         root_dir / "data_dependencies" / "ref_gages" / "region17",
#         root_dir / "data_dependencies" / "ref_gages" / "region16",
#         root_dir / "data_dependencies" / "ref_gages" / "region18",
#     ]

#     # collect all matching files from the three directories
#     files = []
#     for d in dirs:
#         # adjust pattern if needed, e.g. "*.txt" or "output_*.txt"
#         files.extend(glob.glob(os.path.join(d, "output_*.txt")))

#     # extract the numeric part after "_" and before ".txt"
#     monitoring_station_number_list = []
#     for f in files:
#         base = os.path.basename(f)  # e.g. "output_10396000.txt"
#         num_str = base.split("_")[1].split(".")[0]  # "10396000"
#         monitoring_station_number_list.append(
#             (num_str)
#         )  # or keep as string if you prefer

#     all_ref_npoigages_info = find_missing_gage_info(
#         root_dir,
#         root_dir / "data_dependencies" / "ref_gages",
#         monitoring_station_number_list,
#         "ref_npoigages_info",
#     )

#     # Make a geodataframe from the info df
#     gdf = gpd.GeoDataFrame(
#         all_ref_npoigages_info,
#         geometry=gpd.points_from_xy(
#             all_ref_npoigages_info["longitude"], all_ref_npoigages_info["latitude"]
#         ),
#         crs="EPSG:4326",  # WGS84 lat/lon
#     )

#     # make sure CRS is projected (meters/feet) to add buffer distances in real units
#     hru_proj = hru_gdf.to_crs("EPSG:3857")  # example projected CRS
#     gdf_proj = gdf.to_crs(hru_proj.crs)

#     # create a buffer around the mask, 1000 meters, to get gages that may be downstream from outlet segments
#     hru_buffered = hru_proj.buffer(1000)

#     # clip using the buffered mask to the model domain
#     gdf_clipped = gpd.clip(gdf_proj, hru_buffered)

#     # (optional) go back to original CRS and drop the "geometry" column
#     gdf_clipped = gdf_clipped.to_crs(hru_gdf.crs)
#     gdf_clipped.drop(columns={"geometry"}, inplace=True)

#     ref_npoigages_info_file_path = model_dir / "ref_npoigages_info.csv"
#     gdf_clipped.to_csv(ref_npoigages_info_file_path, index=False)

#     return gdf_clipped


# def fetch_non_ref_npoigages_info(root_dir, model_dir, hru_gdf):

#     # list your three directories here (relative or absolute)
#     dirs = [
#         root_dir / "data_dependencies" / "non_ref_gages" / "region17",
#         root_dir / "data_dependencies" / "non_ref_gages" / "region16",
#         root_dir / "data_dependencies" / "non_ref_gages" / "region18",
#     ]

#     # collect all matching files from the three directories
#     files = []
#     for d in dirs:
#         # adjust pattern if needed, e.g. "*.txt" or "output_*.txt"
#         files.extend(glob.glob(os.path.join(d, "output_*.txt")))

#     # extract the numeric part after "_" and before ".txt"
#     monitoring_station_number_list = []
#     for f in files:
#         base = os.path.basename(f)  # e.g. "output_10396000.txt"
#         num_str = base.split("_")[1].split(".")[0]  # "10396000"
#         monitoring_station_number_list.append(
#             (num_str)
#         )  # or keep as string if you prefer

#     all_non_ref_npoigages_info = find_missing_gage_info(
#         root_dir,
#         root_dir / "data_dependencies" / "non_ref_gages",
#         monitoring_station_number_list,
#         "non_ref_npoigages_info",
#     )

#     # Make a geodataframe from the info df
#     gdf = gpd.GeoDataFrame(
#         all_non_ref_npoigages_info,
#         geometry=gpd.points_from_xy(
#             all_non_ref_npoigages_info["longitude"],
#             all_non_ref_npoigages_info["latitude"],
#         ),
#         crs="EPSG:4326",  # WGS84 lat/lon
#     )

#     # make sure CRS is projected (meters/feet) to add buffer distances in real units
#     hru_proj = hru_gdf.to_crs("EPSG:3857")  # example projected CRS
#     gdf_proj = gdf.to_crs(hru_proj.crs)

#     # create a buffer around the mask, 1000 meters, to get gages that may be downstream from outlet segments
#     hru_buffered = hru_proj.buffer(1000)

#     # clip using the buffered mask to the model domain
#     gdf_clipped = gpd.clip(gdf_proj, hru_buffered)

#     # (optional) go back to original CRS and drop the "geometry" column
#     gdf_clipped = gdf_clipped.to_crs(hru_gdf.crs)
#     gdf_clipped.drop(columns={"geometry"}, inplace=True)

#     non_ref_npoigages_info_file_path = model_dir / "non_ref_npoigages_info.csv"
#     gdf_clipped.to_csv(non_ref_npoigages_info_file_path, index=False)

#     return gdf_clipped

# %%
ref_npoigages_df = fetch_ref_npoigages_info(root_dir, config["model_dir"], hru_gdf)

# %%
non_ref_npoigages_df = fetch_non_ref_npoigages_info(
    root_dir, config["model_dir"], hru_gdf
)

# %%
non_ref_npoigages_df

# %%
# gdf = gpd.GeoDataFrame(
#     test,
#     geometry=gpd.points_from_xy(test["longitude"], test["latitude"]),
#     crs="EPSG:4326",  # WGS84 lat/lon
# )
# # make sure CRS is projected (meters/feet) if you want buffer distances in real units
# hru_proj = hru_gdf.to_crs("EPSG:3857")  # example projected CRS
# gdf_proj = gdf.to_crs(hru_proj.crs)

# # create a buffer around the mask, e.g. 1000 meters
# hru_buffered = hru_proj.buffer(1000)

# # clip using the buffered mask
# gdf_clipped = gpd.clip(gdf_proj, hru_buffered)

# # (optional) go back to original CRS
# gdf_clipped = gdf_clipped.to_crs(hru_gdf.crs)
# gdf_clipped.drop(columns={"geometry"}, inplace=True)

# %%
poi_df

# %%
