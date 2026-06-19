# ---
# jupyter:
#   jupytext:
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
# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg
root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"
from assist.nhf.nhm_hydrofabric_v2 import make_hf_map_elements, evaluate_and_fix_nhru_geometry
from assist.nhf.map_template_v2 import make_hf_map, make_geo_map, make_geo_legend

from assist.nhf.nhm_assist_utilities_v2 import (
    load_subdomain_config,
    find_missing_gage_info,
    fetch_non_ref_npoigages_info,
    fetch_ref_npoigages_info,
)

# import topojson


config = load_subdomain_config(root_dir)
# con.print(config)

# %% [markdown]
# ## Introduction
# The purpose of this notebook is to assist in verifying NHM subdomain model location, HRU to segment connections, segment routing order, and the locations of gages and associated streamflow segments. This notebook displays hydrofabric elements: HRUs, streamflow segments, and gages both in the parameter file and additional WaterData gages in the domain (potential streamflow gages).
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
# The cell below creates a map that displays NHM subdomain model hydrofabric elements: HRUs, streamflow segments, and gages both in the parameter file and additional WaterData gages in the domain (potential streamflow gages). Gage locations are overlays in the map of NHM headwater basins (HWs) that are color coded to calibration type: yellow indicates HWs that were calibrated with statistical streamflow targets at the HW outlet; green indicates HWs that were further calibrated with streamflow observations at selected gage locations.

# %%
(
    hru_gdf,
    hru_txt,
    # hru_cal_level_txt,
    seg_gdf,
    seg_txt,
    waterdata_gages_aoi,
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
    waterdata_gages_file=config["waterdata_gages_file"],
    gages_file=config["gages_file"],
    resource_gages_file=config["resource_gages_file"],
    default_gages_file=config["default_gages_file"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
)
con.print(
    f"{config['workspace_txt']}\n",
    f"\n{gages_txt}{seg_txt}{hru_txt}",
    # f"\n     {hru_cal_level_txt}\n",
    f"\n{gages_txt_nb2}",
)

# %%
poi_df

# %%
map_file = make_hf_map(
    root_dir=root_dir,
    hru_gdf=hru_gdf,
    # HW_basins_gdf=HW_basins_gdf,
    # HW_basins=HW_basins,
    poi_df=poi_df,
    poi_gage_id_sel="",
    seg_gdf=seg_gdf,
    waterdata_gages_aoi=waterdata_gages_aoi,
    gages_df=gages_df,
    html_maps_dir=config["html_maps_dir"],
    Folium_maps_dir=config["Folium_maps_dir"],
    param_filename=config["param_filename"],
    subdomain=config["subdomain"],
)

# %%
poi_df

# %% [markdown]
# # Want to Add a potential gage to the parameter file? [Click here!](./add_pois_to_parameters.ipynb)

# %%
# Make meta_table
import numpy as np
import pandas as pd
import geopandas as gpd

model_dir = config["model_dir"]

# %%
npoigages_df_file = model_dir / "metadata" / "resource_gages.csv"
ref_df_file = model_dir / "metadata" / "ref_npoigages_info.csv"
non_ref_df_file = model_dir / "metadata" / "non_ref_npoigages_info.csv"

col_names = [
    "poi_gage_id",
    "poi_agency",
    "poi_name",
    "latitude",
    "longitude",
    "drainage_area",
    "drainage_area_contrib",
]
col_types = [
    np.str_,
    np.str_,
    np.str_,
    float,
    float,
    float,
    float,
]
cols = dict(
    zip(col_names, col_types)
)  # Creates a dictionary of column header and datatype called below.

npoigages_df = pd.read_csv(
    npoigages_df_file,
    dtype=cols,
    usecols=[
        "poi_gage_id",
        "poi_agency",
        "poi_name",
        "latitude",
        "longitude",
    ],
)

try:
    non_ref_df = pd.read_csv(
        non_ref_df_file,
        dtype=cols,
        usecols=[
            "poi_gage_id",
        ],
    )
    non_ref_list = list(non_ref_df.poi_gage_id)
except FileNotFoundError:
    non_ref_list = []


try:
    ref_df = pd.read_csv(
        ref_df_file,
        dtype=cols,
        usecols=[
            "poi_gage_id",
        ],
    )
    ref_list = list(ref_df.poi_gage_id)
except FileNotFoundError:
    ref_list = []


npoigages_df["gagesII"] = "nan"

npoigages_df.loc[npoigages_df["poi_gage_id"].isin(ref_list), "gagesII"] = "ref"
npoigages_df.loc[npoigages_df["poi_gage_id"].isin(non_ref_list), "gagesII"] = "non_ref"

# Find the HUC10
huc10_map = gpd.read_file(
    root_dir / "data_dependencies/huc10/HUC_10_boundaries.shp"
).to_crs(epsg=4326)
print(huc10_map.columns)

# Make sure both are in the same CRS
gdf_points = gpd.GeoDataFrame(
    npoigages_df,
    geometry=gpd.points_from_xy(npoigages_df["longitude"], npoigages_df["latitude"]),
    crs="EPSG:4326",
)

# Spatial join: each line gets attributes of the polygon it intersects
gdf_points_with_huc = gpd.sjoin(
    gdf_points,
    huc10_map[["huc10", "geometry"]],
    how="left",
    predicate="within",  # or 'within' if you prefer strict containment
)


# # Clean up: keep original columns plus huc10
gdf_points_with_huc = gdf_points_with_huc.drop_duplicates(
    subset="poi_gage_id", keep="first"
)
gdf_points_with_huc = gdf_points_with_huc.drop(columns=["index_right"])
npoigages_df = gdf_points_with_huc.copy()

#### READ FMI table (.csv) for selected gages
fmi_df_file = model_dir / "metadata" / "fmi_gages_info.csv"

col_names = [
    "storage_index",
    "use_index",
    "flow_management_index",
    "poi_gage_id",
    "poi_agency",
    "poi_name",
    "latitude",
    "longitude",
    "drainage_area",
    "drainage_area_contrib",
]
col_types = [
    np.int_,
    np.int_,
    np.int_,
    np.str_,
    np.str_,
    np.str_,
    float,
    float,
    float,
    float,
]
cols = dict(
    zip(col_names, col_types)
)  # Creates a dictionary of column header and datatype called below.

fmi_df = pd.read_csv(
    fmi_df_file,
    dtype=cols,
    usecols=[
        "storage_index",
        "use_index",
        "flow_management_index",
        "poi_gage_id",
    ],
)

npoigages_df = fmi_df.merge(
    npoigages_df,
    left_on="poi_gage_id",
    right_on="poi_gage_id",
    how="outer",
)
npoigages_df["ohm_cal"] = "no"
cols = [
    "huc10",
    "poi_gage_id",
    "ohm_cal",
    "gagesII",
    "flow_management_index",
    "storage_index",
    "use_index",
    "poi_agency",
    "poi_name",
    "latitude",
    "longitude",
]
npoigages_df = npoigages_df[cols]
npoigages_df.sort_values(by=["huc10", "poi_gage_id"], inplace=True)


npoigages_info_file_path = model_dir / "metadata" / "npoigages_cal_list.csv"
npoigages_df.to_csv(npoigages_info_file_path, index=False)

# %%

# %%
npoigages_df

# %%
