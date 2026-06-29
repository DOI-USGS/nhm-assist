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
# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg
root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"
from assist.nhf.nhm_hydrofabric_v2 import create_poi_df
# from assist.nhf.map_template_v2 import make_hf_map
from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config
import topojson

config = load_subdomain_config(root_dir)
# con.print(config)

# %% [markdown]
# ## Introduction
#

# %%
config

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
def find_missing_gage_info(root_dir, dest_dir, gages_list, info_file_name):
    """
    This is used to find metadata neede for gages in the list provided.

    First, metadata is sought for in the resource (suuplemental) gages file (if one exists).
    Second, location data specifically is sought for in the usgs_nldi_gages database,
    Third, metadata is sought for in USGS WaterData database.

    """
    npoigages_data_dir = root_dir / "data_dependencies/"

    dest_dir.mkdir(parents=True, exist_ok=True)

    info_file_path = dest_dir / f"{info_file_name}.csv"
    info_supplement_path = dest_dir / f"{info_file_name}_supplemental.csv"

    nan_list = [np.nan] * len(gages_list)  # Initialize empty list
    gages_df = pd.DataFrame(
        {
            "poi_gage_id": gages_list,
            "poi_agency": nan_list,
            "poi_name": nan_list,
            "latitude": nan_list,
            "longitude": nan_list,
            "drainage_area": nan_list,
            "drainage_area_contrib": nan_list,
        }
    )  # Initialize empty datafame

    # Check for resource (supplemental) file, if present, append information to gages_df
    if info_supplement_path.exists():
        col_names_1 = [
            "poi_gage_id",
            "poi_agency",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
        ]
        col_types_1 = [np.str_, np.str_, np.str_, float, float, float, float]
        cols = dict(zip(col_names_1, col_types_1))
        info_supplement_df = pd.read_csv(info_supplement_path, dtype=cols)

        gages_lacking_info_list = []
        gages_found_info_list = []
        check_list = info_supplement_df["poi_gage_id"].to_list()

        if len(check_list) > 0:
            print(
                f"The {info_file_name}_supplemental.csv exists and has {len(check_list)} gages."
            )
            for idx, row in gages_df.iterrows():
                columns = ["latitude", "longitude", "poi_name", "poi_agency"]
                item_lacking_list = []
                item_found_list = []
                for item in columns:
                    if pd.isnull(row[item]):
                        item_lacking_list.append(item)
                        gages_lacking_info_list.append(row["poi_gage_id"])
                        new_poi_id = row["poi_gage_id"]
                        if new_poi_id in check_list:
                            gages_found_info_list.append(row["poi_gage_id"])
                            item_found_list.append(item)
                            new_item = info_supplement_df.loc[
                                info_supplement_df.poi_gage_id == new_poi_id, item
                            ].values[0]
                            gages_df.loc[idx, item] = new_item
                        else:
                            pass

            lacking_info_list = list(set(gages_lacking_info_list))
            gages_found_info_list = list(set(gages_found_info_list))
            still_lacking_info_list = [
                x for x in lacking_info_list if x not in gages_found_info_list
            ]

            print(
                f"{len(gages_found_info_list)} gages founded needed metadata in {info_file_name}_supplemental.csv"
            )
        else:
            print(f"The {info_file_name}_supplemental.csv exists but is empty.")

    else:
        pass

    ##### Check NLDI database for missing gage info
    file_path = npoigages_data_dir / "usgs_nldi_gages.geojson"
    nldi_gdf = gpd.read_file(file_path)  # or .geojson

    # Split on the first '-' and create new columns
    nldi_gdf[["poi_agency", "poi_gage_id"]] = (
        nldi_gdf["id"]
        .astype("string")  # keeps NaN as <NA>
        .str.strip()
        .str.split("-", n=1, expand=True)  # split on the first dash only
    )
    nldi_gdf.to_file(
        npoigages_data_dir / "usgs_nldi_gages.gpkg",
        driver="GPKG",
    )

    nldi_gdf = nldi_gdf[["poi_agency", "name", "poi_gage_id", "geometry"]]
    nldi_gdf.rename(
        columns={
            "name": "poi_name",
        },
        inplace=True,
    )
    nldi_gdf["latitude"] = nldi_gdf.geometry.y
    nldi_gdf["longitude"] = nldi_gdf.geometry.x
    nldi_gdf["drainage_area"] = np.nan
    nldi_gdf["drainage_area_contrib"] = np.nan

    nldi_gdf = nldi_gdf[
        [
            "poi_gage_id",
            "poi_agency",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
            "geometry",
        ]
    ]

    gages_lacking_info_list = []
    gages_found_info_list = []
    check_list = nldi_gdf["poi_gage_id"].to_list()

    for idx, row in gages_df.iterrows():
        columns = ["latitude", "longitude", "poi_name", "poi_agency"]
        item_lacking_list = []
        item_found_list = []
        for item in columns:
            if pd.isnull(row[item]):
                item_lacking_list.append(item)
                gages_lacking_info_list.append(row["poi_gage_id"])
                new_poi_id = row["poi_gage_id"]
                if new_poi_id in check_list:
                    gages_found_info_list.append(row["poi_gage_id"])
                    item_found_list.append(item)
                    new_item = nldi_gdf.loc[
                        nldi_gdf.poi_gage_id == new_poi_id, item
                    ].values[0]
                    gages_df.loc[idx, item] = new_item
                else:
                    pass

    lacking_info_list = list(set(gages_lacking_info_list))
    gages_found_info_list = list(set(gages_found_info_list))
    still_lacking_info_list = [
        x for x in lacking_info_list if x not in gages_found_info_list
    ]

    print(
        f"Latitude and longitude for {len(gages_found_info_list)} gages found in NLDI database.csv",
        # f"{len(list(set(still_lacking_info_list)))} of {len(gages_df)} are still lacking gage info.",
    )

    # Get monitoring location information from USGS WaterData
    """Now, get the site infomation for the new list
            used the chunk format from the example: 
            https://github.com/DOI-USGS/dataretrieval-python/blob/dc9b614f646b2656c17acc77c0161762053afaf6/demos/WaterData_demo.ipynb
    """
    chunk_size = 100
    site_list = gages_df["poi_gage_id"].unique().tolist()

    chunks = [
        site_list[i : i + chunk_size] for i in range(0, len(site_list), chunk_size)
    ]
    domain_locations = pd.DataFrame()

    for site_group in chunks:
        try:
            chunk_data, _ = waterdata.get_monitoring_locations(
                monitoring_location_number=site_group,
                site_type_code="ST",
                properties=[
                    "monitoring_location_id",
                    "geometry",
                    "agency_code",
                    "agency_name",
                    "monitoring_location_number",
                    "monitoring_location_name",
                    "state_name",
                    "drainage_area",
                    "contributing_drainage_area",
                ],
            )
            if not chunk_data.empty:
                domain_locations = pd.concat([domain_locations, chunk_data])
            else:
                print("No info in NWIS.")

        except Exception as e:
            print(f"Chunk failed: {e}")
    if not domain_locations.empty:
        domain_locations["latitude"] = (
            domain_locations.geometry.y
        )  # need this for the notebooks
        domain_locations["longitude"] = (
            domain_locations.geometry.x
        )  # need this for the notebooks

        waterdata_info = None
        waterdata_info = (
            domain_locations.set_index(
                "monitoring_location_number", drop=False
            ).set_crs("EPSG:4326")
            # .to_crs(crs)
        )

        field_map = {
            "agency_code": "poi_agency",
            "monitoring_location_number": "poi_gage_id",
            "monitoring_location_name": "poi_name",
            "geometry": "geometry",
            "latitude": "latitude",
            "longitude": "longitude",
            "drainage_area": "drainage_area",
            "contributing_drainage_area": "drainage_area_contrib",
        }
        include_cols = list(field_map.keys())

        waterdata_info = waterdata_info.loc[:, include_cols]
        waterdata_info.rename(columns=field_map, inplace=True)
        waterdata_info.set_index("poi_gage_id", inplace=True)
        waterdata_info = waterdata_info.sort_index()
        waterdata_info.reset_index(inplace=True)

        gages_lacking_info_list = []
        gages_found_info_list = []
        check_list = waterdata_info["poi_gage_id"].to_list()

        for idx, row in gages_df.iterrows():
            columns = [
                "latitude",
                "longitude",
                "poi_name",
                "poi_agency",
                "drainage_area",
                "drainage_area_contrib",
            ]
            item_lacking_list = []
            item_found_list = []
            for item in columns:
                if pd.isnull(row[item]):
                    item_lacking_list.append(item)
                    gages_lacking_info_list.append(row["poi_gage_id"])
                    new_poi_id = row["poi_gage_id"]
                    if new_poi_id in check_list:
                        gages_found_info_list.append(row["poi_gage_id"])
                        item_found_list.append(item)
                        new_item = waterdata_info.loc[
                            waterdata_info.poi_gage_id == new_poi_id, item
                        ].values[0]
                        gages_df.loc[idx, item] = new_item
                    else:
                        pass

        lacking_info_list = list(set(gages_lacking_info_list))
        gages_found_info_list = list(set(gages_found_info_list))
        still_lacking_info_list = [
            x for x in lacking_info_list if x not in gages_found_info_list
        ]

        print(
            f"{len(gages_found_info_list)} gages found metadata in USGS WaterData database.",
            # f"{len(list(set(still_lacking_info_list)))} of {len(gages_df)} are still lacking gage info.",
        )
    else:
        print("Gage metadata not found in USGS WaterData database.")
    # Have to make code for if exists, check for, and then append so we don't overwrite
    cols = ["latitude", "longitude", "poi_name", "poi_agency"]
    gages_missing_info_df = gages_df.loc[gages_df[cols].isna().any(axis=1)]
    print(
        f"{len(gages_missing_info_df)} gages lacking metadata will be appended to the {info_file_name}_supplemental.csv",
        "User must complete needed information and rerun this notebook.",
    )

    if info_supplement_path.exists():
        existing_resource_df = info_supplement_df
        gages_missing_info_df = pd.concat(
            [existing_resource_df, gages_missing_info_df], ignore_index=True
        )
        gages_missing_info_df.to_csv(info_supplement_path, index=False)
    else:
        gages_missing_info_df.to_csv(info_supplement_path, index=False)

    gages_df.to_csv(dest_dir / f"{info_file_name}.csv", index=False)

    return gages_df


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


def fetch_ref_npoigages_info(root_dir, model_dir, hru_gdf):

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
        monitoring_station_number_list.append(
            (num_str)
        )  # or keep as string if you prefer

    all_ref_npoigages_info = find_missing_gage_info(
        root_dir,
        root_dir / "data_dependencies" / "ref_gages",
        monitoring_station_number_list,
        "ref_npoigages_info",
    )

    # Make a geodataframe from the info df
    gdf = gpd.GeoDataFrame(
        all_ref_npoigages_info,
        geometry=gpd.points_from_xy(
            all_ref_npoigages_info["longitude"], all_ref_npoigages_info["latitude"]
        ),
        crs="EPSG:4326",  # WGS84 lat/lon
    )

    # make sure CRS is projected (meters/feet) to add buffer distances in real units
    hru_proj = hru_gdf.to_crs("EPSG:3857")  # example projected CRS
    gdf_proj = gdf.to_crs(hru_proj.crs)

    # create a buffer around the mask, 1000 meters, to get gages that may be downstream from outlet segments
    hru_buffered = hru_proj.buffer(1000)

    # clip using the buffered mask to the model domain
    gdf_clipped = gpd.clip(gdf_proj, hru_buffered)

    # (optional) go back to original CRS and drop the "geometry" column
    gdf_clipped = gdf_clipped.to_crs(hru_gdf.crs)
    gdf_clipped.drop(columns={"geometry"}, inplace=True)

    ref_npoigages_info_file_path = model_dir / "ref_npoigages_info.csv"
    gdf_clipped.to_csv(ref_npoigages_info_file_path, index=False)

    return gdf_clipped


def fetch_non_ref_npoigages_info(root_dir, model_dir, hru_gdf):

    # list your three directories here (relative or absolute)
    dirs = [
        root_dir / "data_dependencies" / "non_ref_gages" / "region17",
        root_dir / "data_dependencies" / "non_ref_gages" / "region16",
        root_dir / "data_dependencies" / "non_ref_gages" / "region18",
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
        monitoring_station_number_list.append(
            (num_str)
        )  # or keep as string if you prefer

    all_non_ref_npoigages_info = find_missing_gage_info(
        root_dir,
        root_dir / "data_dependencies" / "non_ref_gages",
        monitoring_station_number_list,
        "non_ref_npoigages_info",
    )

    # Make a geodataframe from the info df
    gdf = gpd.GeoDataFrame(
        all_non_ref_npoigages_info,
        geometry=gpd.points_from_xy(
            all_non_ref_npoigages_info["longitude"],
            all_non_ref_npoigages_info["latitude"],
        ),
        crs="EPSG:4326",  # WGS84 lat/lon
    )

    # make sure CRS is projected (meters/feet) to add buffer distances in real units
    hru_proj = hru_gdf.to_crs("EPSG:3857")  # example projected CRS
    gdf_proj = gdf.to_crs(hru_proj.crs)

    # create a buffer around the mask, 1000 meters, to get gages that may be downstream from outlet segments
    hru_buffered = hru_proj.buffer(1000)

    # clip using the buffered mask to the model domain
    gdf_clipped = gpd.clip(gdf_proj, hru_buffered)

    # (optional) go back to original CRS and drop the "geometry" column
    gdf_clipped = gdf_clipped.to_crs(hru_gdf.crs)
    gdf_clipped.drop(columns={"geometry"}, inplace=True)

    non_ref_npoigages_info_file_path = model_dir / "non_ref_npoigages_info.csv"
    gdf_clipped.to_csv(non_ref_npoigages_info_file_path, index=False)

    return gdf_clipped


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
