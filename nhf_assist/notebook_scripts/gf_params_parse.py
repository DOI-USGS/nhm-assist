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

from helpers.sf_data_retrieval_v2 import fetch_single_nwis_gage
from helpers.nhm_assist_utilities_v2 import find_missing_gage_info


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

# from pyPRMS.base.console import get_console_instance
from pyPRMS.metadata.metadata import MetaData
from pyPRMS import Parameters, ParameterFile
from pyPRMS import ParameterNetCDF
from pyPRMS import ParamDb
from pyPRMS import ControlFile
from pyPRMS.constants import NEW_PTYPE_TO_DTYPE
from pyPRMS.Exceptions_custom import ParameterNotValidError

# from rich.console import Console
# from rich.progress import track
from rich import pretty

# con = get_console_instance(width=200, force_jupyter=False)

pretty.install()


# %%
# Functions
def check_for_disconnected_graphs(g):
    # Check for disconnected graphs within the graph object
    tot_weak_comp = 0
    node_size_cnt = Counter()

    for xx in nx.weakly_connected_components(g):
        out_node = [ii for ii in list(xx) if "Out_" in str(ii)]
        tot_weak_comp += 1
        node_size_cnt[len(xx)] += 1

        try:
            print("{}: nodes {}".format(out_node[0], len(xx)))
        except IndexError:
            # If this occurs it most likely indicates a loop or cycle
            print("WEIRD: ", xx)
    print("Total weakly connected components: {}".format(tot_weak_comp))

    print("Top 10 node sizes (size, count)")
    print(node_size_cnt.most_common(10))


def _data_it(filename):
    """Get iterator to a parameter db file.

    :returns: iterator
    """

    # Read the data
    fhdl = open(filename)
    rawdata = fhdl.read().splitlines()
    fhdl.close()
    return iter(rawdata)


def read_data(filename):
    it = _data_it(filename)
    next(it)

    data = []

    # Read the parameter values
    for rec in it:
        idx, val = rec.split(",")
        data.append(val)

    return data


# def find_missing_gage_info(root_dir, dest_dir, gages_list, info_file_name):
#     """
#     This is used to find metadata neede for gages in the list provided.

#     First, metadata is sought for in the resource (suuplemental) gages file (if one exists).
#     Second, location data specifically is sought for in the usgs_nldi_gages database,
#     Third, metadata is sought for in USGS WaterData database.

#     """
#     npoigages_data_dir = root_dir / "data_dependencies/"

#     # dest_dir.mkdir(parents=True, exist_ok=True)

#     info_file_path = dest_dir / f"{info_file_name}.csv"
#     info_supplement_path = dest_dir / f"{info_file_name}_supplemental.csv"

#     nan_list = [np.nan] * len(gages_list)  # Initialize empty list
#     gages_df = pd.DataFrame(
#         {
#             "poi_gage_id": gages_list,
#             "poi_agency": nan_list,
#             "poi_name": nan_list,
#             "latitude": nan_list,
#             "longitude": nan_list,
#             "drainage_area": nan_list,
#             "drainage_area_contrib": nan_list,
#         }
#     )  # Initialize empty datafame

#     # Check for resource (supplemental) file, if present, append information to gages_df
#     if info_supplement_path.exists():
#         col_names_1 = [
#             "poi_gage_id",
#             "poi_agency",
#             "poi_name",
#             "latitude",
#             "longitude",
#             "drainage_area",
#             "drainage_area_contrib",
#         ]
#         col_types_1 = [np.str_, np.str_, np.str_, float, float, float, float]
#         cols = dict(zip(col_names_1, col_types_1))
#         info_supplement_df = pd.read_csv(info_supplement_path, dtype=cols)

#         gages_lacking_info_list = []
#         gages_found_info_list = []
#         check_list = info_supplement_df["poi_gage_id"].to_list()

#         if len(check_list) > 0:
#             print(
#                 f"The {info_file_name}_supplemental.csv exists and has {len(check_list)} gages."
#             )
#             for idx, row in gages_df.iterrows():
#                 columns = ["latitude", "longitude", "poi_name", "poi_agency"]
#                 item_lacking_list = []
#                 item_found_list = []
#                 for item in columns:
#                     if pd.isnull(row[item]):
#                         item_lacking_list.append(item)
#                         gages_lacking_info_list.append(row["poi_gage_id"])
#                         new_poi_id = row["poi_gage_id"]
#                         if new_poi_id in check_list:
#                             gages_found_info_list.append(row["poi_gage_id"])
#                             item_found_list.append(item)
#                             new_item = info_supplement_df.loc[
#                                 info_supplement_df.poi_gage_id == new_poi_id, item
#                             ].values[0]
#                             gages_df.loc[idx, item] = new_item
#                         else:
#                             pass

#             lacking_info_list = list(set(gages_lacking_info_list))
#             gages_found_info_list = list(set(gages_found_info_list))
#             still_lacking_info_list = [
#                 x for x in lacking_info_list if x not in gages_found_info_list
#             ]

#             print(
#                 f"{len(gages_found_info_list)} gages found in {info_file_name}_supplemental.csv"
#             )
#         else:
#             print(f"The {info_file_name}_supplemental.csv exists but is empty.")

#     else:
#         pass

#     ##### Check NLDI database for missing gage info
#     file_path = npoigages_data_dir / "usgs_nldi_gages.geojson"
#     nldi_gdf = gpd.read_file(file_path)  # or .geojson

#     # Split on the first '-' and create new columns
#     nldi_gdf[["poi_agency", "poi_gage_id"]] = (
#         nldi_gdf["id"]
#         .astype("string")  # keeps NaN as <NA>
#         .str.strip()
#         .str.split("-", n=1, expand=True)  # split on the first dash only
#     )
#     nldi_gdf.to_file(
#         npoigages_data_dir / "usgs_nldi_gages.gpkg",
#         driver="GPKG",
#     )

#     nldi_gdf = nldi_gdf[["poi_agency", "name", "poi_gage_id", "geometry"]]
#     nldi_gdf.rename(
#         columns={
#             "name": "poi_name",
#         },
#         inplace=True,
#     )
#     nldi_gdf["latitude"] = nldi_gdf.geometry.y
#     nldi_gdf["longitude"] = nldi_gdf.geometry.x
#     nldi_gdf["drainage_area"] = np.nan
#     nldi_gdf["drainage_area_contrib"] = np.nan

#     nldi_gdf = nldi_gdf[
#         [
#             "poi_gage_id",
#             "poi_agency",
#             "poi_name",
#             "latitude",
#             "longitude",
#             "drainage_area",
#             "drainage_area_contrib",
#             "geometry",
#         ]
#     ]

#     gages_lacking_info_list = []
#     gages_found_info_list = []
#     check_list = nldi_gdf["poi_gage_id"].to_list()

#     for idx, row in gages_df.iterrows():
#         columns = ["latitude", "longitude", "poi_name", "poi_agency"]
#         item_lacking_list = []
#         item_found_list = []
#         for item in columns:
#             if pd.isnull(row[item]):
#                 item_lacking_list.append(item)
#                 gages_lacking_info_list.append(row["poi_gage_id"])
#                 new_poi_id = row["poi_gage_id"]
#                 if new_poi_id in check_list:
#                     gages_found_info_list.append(row["poi_gage_id"])
#                     item_found_list.append(item)
#                     new_item = nldi_gdf.loc[
#                         nldi_gdf.poi_gage_id == new_poi_id, item
#                     ].values[0]
#                     gages_df.loc[idx, item] = new_item
#                 else:
#                     pass

#     lacking_info_list = list(set(gages_lacking_info_list))
#     gages_found_info_list = list(set(gages_found_info_list))
#     still_lacking_info_list = [
#         x for x in lacking_info_list if x not in gages_found_info_list
#     ]

#     print(
#         f"{len(gages_found_info_list)} gages found in NLDI database.csv",
#         # f"{len(list(set(still_lacking_info_list)))} of {len(gages_df)} are still lacking gage info.",
#     )

#     # Get monitoring location information from USGS WaterData
#     """Now, get the site infomation for the new list
#             used the chunk format from the example: 
#             https://github.com/DOI-USGS/dataretrieval-python/blob/dc9b614f646b2656c17acc77c0161762053afaf6/demos/WaterData_demo.ipynb
#     """
#     chunk_size = 100
#     site_list = gages_df["poi_gage_id"].unique().tolist()

#     chunks = [
#         site_list[i : i + chunk_size] for i in range(0, len(site_list), chunk_size)
#     ]
#     domain_locations = pd.DataFrame()

#     for site_group in chunks:
#         try:
#             chunk_data, _ = waterdata.get_monitoring_locations(
#                 monitoring_location_number=site_group,
#                 site_type_code="ST",
#                 properties=[
#                     "monitoring_location_id",
#                     "geometry",
#                     "agency_code",
#                     "agency_name",
#                     "monitoring_location_number",
#                     "monitoring_location_name",
#                     "state_name",
#                     "drainage_area",
#                     "contributing_drainage_area",
#                 ],
#             )
#             if not chunk_data.empty:
#                 domain_locations = pd.concat([domain_locations, chunk_data])
#             else:
#                 print("No info in NWIS.")

#         except Exception as e:
#             print(f"Chunk failed: {e}")
#     if not domain_locations.empty:
#         domain_locations["latitude"] = (
#             domain_locations.geometry.y
#         )  # need this for the notebooks
#         domain_locations["longitude"] = (
#             domain_locations.geometry.x
#         )  # need this for the notebooks

#         waterdata_info = None
#         waterdata_info = (
#             domain_locations.set_index(
#                 "monitoring_location_number", drop=False
#             ).set_crs("EPSG:4326")
#             # .to_crs(crs)
#         )

#         field_map = {
#             "agency_code": "poi_agency",
#             "monitoring_location_number": "poi_gage_id",
#             "monitoring_location_name": "poi_name",
#             "geometry": "geometry",
#             "latitude": "latitude",
#             "longitude": "longitude",
#             "drainage_area": "drainage_area",
#             "contributing_drainage_area": "drainage_area_contrib",
#         }
#         include_cols = list(field_map.keys())

#         waterdata_info = waterdata_info.loc[:, include_cols]
#         waterdata_info.rename(columns=field_map, inplace=True)
#         waterdata_info.set_index("poi_gage_id", inplace=True)
#         waterdata_info = waterdata_info.sort_index()
#         waterdata_info.reset_index(inplace=True)

#         gages_lacking_info_list = []
#         gages_found_info_list = []
#         check_list = waterdata_info["poi_gage_id"].to_list()

#         for idx, row in gages_df.iterrows():
#             columns = [
#                 "latitude",
#                 "longitude",
#                 "poi_name",
#                 "poi_agency",
#                 "drainage_area",
#                 "drainage_area_contrib",
#             ]
#             item_lacking_list = []
#             item_found_list = []
#             for item in columns:
#                 if pd.isnull(row[item]):
#                     item_lacking_list.append(item)
#                     gages_lacking_info_list.append(row["poi_gage_id"])
#                     new_poi_id = row["poi_gage_id"]
#                     if new_poi_id in check_list:
#                         gages_found_info_list.append(row["poi_gage_id"])
#                         item_found_list.append(item)
#                         new_item = waterdata_info.loc[
#                             waterdata_info.poi_gage_id == new_poi_id, item
#                         ].values[0]
#                         gages_df.loc[idx, item] = new_item
#                     else:
#                         pass

#         lacking_info_list = list(set(gages_lacking_info_list))
#         gages_found_info_list = list(set(gages_found_info_list))
#         still_lacking_info_list = [
#             x for x in lacking_info_list if x not in gages_found_info_list
#         ]

#         print(
#             f"{len(gages_found_info_list)} gages found metadata in USGS WaterData database.",
#             # f"{len(list(set(still_lacking_info_list)))} of {len(gages_df)} are still lacking gage info.",
#         )
#     else:
#         print("Gage metadata not found in USGS WaterData database.")
#     # Have to make code for if exists, check for, and then append so we don't overwrite
#     cols = ["latitude", "longitude", "poi_name", "poi_agency"]
#     gages_missing_info_df = gages_df.loc[gages_df[cols].isna().any(axis=1)]
#     print(
#         f"{len(gages_missing_info_df)} gages lacking metadata will be appended to the {info_file_name}_supplemental.csv",
#         f"User must complete needed information and rerun this notebook to include these gages {list(gages_missing_info_df['poi_gage_id'])}.",
#     )
#     gages_df = gages_df[
#         ~gages_df["poi_gage_id"].isin(gages_missing_info_df["poi_gage_id"])
#     ]

#     if info_supplement_path.exists():
#         existing_resource_df = info_supplement_df.copy()
#         gages_missing_info_df = pd.concat(
#             [existing_resource_df, gages_missing_info_df], ignore_index=True
#         )
#         gages_missing_info_df.to_csv(info_supplement_path, index=False)
#     else:
#         if not gages_missing_info_df.empty:
#             gages_missing_info_df.to_csv(info_supplement_path, index=False)
#         else:
#             print(
#                 "All gages in the gage list provided have all required metadata.",
#                 f"see gage meta data file at {dest_dir}/npoigages_info.csv",
#             )

#     gages_df.to_csv(dest_dir / f"{info_file_name}.csv", index=False)

#     return gages_df


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
    # dups_df["dist_to_line"] = dups_df.apply(
    #     lambda r: r.geometry.distance(r.line_geom), axis=1
    # )
    dups_df["dist_to_line"] = dups_df.geometry.distance(dups_df["line_geom"])

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
# ## Introduction
# This notebook creates a pywatershed model for a specified domain from a Geospatial Fabric Version 2 domain data sets--list data sets. 
#
# The NHGF_v2 source files consist of two primary data sources. 1) The GIS for the domain consiting of a geopackage that contains layers for the nHRU, nsegment, and npoi geometries, and 2) "parameter name".csv files that have parameter values for each segment and hrus in the fabric.
#
# Prior to running this notebook, the user should have selected HRUs, stream segments, and pois from the parent GIS for the child model domain

# %% [markdown]
# ### Setup directories

# %% [markdown]
# ### Set path to GFv2 parent domain data sets
# The parent domain may be CONUS in scale or a regional domain. In this case, the parent domain is portions of Region 16, 17, and 18 that cover contributing areas to the Oregon Satae watersheds.

# %%
parent_dir = root_dir / f"hydrofabric_domain_data/OHM_2026_02_21"

# %% [markdown]
# The directory for all the paramerter .csv files:

# %%
parent_params_dir = f"{parent_dir}/param_source_files"

# %% [markdown]
# Get the list of parameter names from the .csv paramter files

# %%
gf_files = []
file_it = glob.glob(f"{parent_params_dir}/*.csv")
for kk in file_it:
    gf_files.append(kk)
gf_files.sort()

# %% [markdown]
# ### Read in the pywatershed control file.
# The control file used for the parent pywatershed model is somewhat universal and not model dependent

# %%
default_ctl_filename = root_dir / f"data_dependencies/control.default.bandit"
prms_meta = MetaData(verbose=False).metadata
ctl = ControlFile(default_ctl_filename, metadata=prms_meta, verbose=True)

# %% [markdown]
# ### Create the parent parameter database using pyPRMS (parent_pdb)

# %%
parent_pdb = Parameters(metadata=prms_meta, verbose=False)
parent_pdb.control = ctl

# Some dimensions are derived from particular parameters
derived_dimensions = {
    "nhru": "nhm_id",
    "nsegment": "nhm_seg",
    "npoigages": "poi_type",  # Note: this isn't really
    "ndeplval": "snarea_curve",
}

for kk, vv in derived_dimensions.items():
    tmp_data = read_data(f"{parent_params_dir}/{vv}.csv")
    parent_pdb.dimensions.add(kk, size=len(tmp_data))

# Add the constant-size dimensions
parent_pdb.dimensions.add("ndays", size=366)
parent_pdb.dimensions.add("nmonths", size=12)
parent_pdb.dimensions.add("one", size=1)


# %%
parent_pdb.dimensions.get("npoigages")

# %%
for cfile in gf_files:
    cname = os.path.basename(os.path.splitext(cfile)[0])
    # print(cname)

    try:
        parent_pdb.add(cname)
    except ParameterNotValidError:
        con.print(f"[red]{cname}[/] is not a valid parameter... skipping")
        continue

    try:
        cdtype = NEW_PTYPE_TO_DTYPE[parent_pdb.get(cname).meta["datatype"]]
        tmp_data = (
            pd.read_csv(cfile, skiprows=0, usecols=[1], dtype={1: cdtype})
            .squeeze("columns")
            .to_numpy()
        )
        #### Added code to force a minimum hru area for very small hrus in the GFv2
        if cname == "hru_area":
            tmp_data[tmp_data < 0.0001] = 0.0001
        else:
            pass
        ####
        try:
            parent_pdb.get(cname).data = tmp_data
        except IndexError:
            con.print(f"[red]{cname}[/] has incorrect size... skipping")
            parent_pdb.remove(cname)
    except ValueError as err:
        con.print(f"[red]{cname}[/]: {err} - skipping")
        parent_pdb.remove(cname)

# %%
parent_pdb.check()

# %% [markdown]
# ### Create pywatershed model for specified domain in the GFv2
#
# Specify the root directory for all files created for the specified domain (child) pywatershed model

# %%
child_name = "Sandy_River"  # Powder_River, John_Day_River
child_path = f"hydrofabric_domain_data/{child_name}"
child_hf_dir = root_dir / child_path
if child_hf_dir.is_dir():
    child_pws_dir = root_dir / f"domain_data/{child_name}"
    child_pws_dir.mkdir(parents=True, exist_ok=True)
else:
    print(f"The child directory {child_path} does not exist.")
    p = root_dir / "hydrofabric_domain_data/"
    print(f"Please choose from the folowing list. ({p.resolve()}):")
    for folder in p.iterdir():
        if folder.is_dir():
            print(folder.name)

# %% [markdown]
# ### Read in .gpkg layers from the specified domain (child)
# Apart from the this workflow, the user has created a subset of the GFv2 domain from the .gpkg provided with the GFv2 files. The number and name of layer attributes must remain unchanged.

# %%
child_gpkg_name = "child_nhf_domain.gpkg"
print(gpd.list_layers(f"{child_hf_dir}/GIS/{child_gpkg_name}"))

# %%
hru_gdb = gpd.read_file(
    f"{child_hf_dir}/GIS/{child_gpkg_name}", layer="nhru"
)  # Reads HRU file to Geopandas.

seg_gdb = gpd.read_file(
    f"{child_hf_dir}/GIS/{child_gpkg_name}", layer="nsegment"
)  # Reads HRU file to Geopandas.

poi_gdb = gpd.read_file(
    f"{child_hf_dir}/GIS/{child_gpkg_name}", layer="npoi"
)  # Reads HRU file to Geopandas.

aoi_gdb = gpd.read_file(
    f"{child_hf_dir}/GIS/{child_gpkg_name}", layer="domain"
)  # Reads HRU file to Geopandas.

# %%
hru_gdb

# %% [markdown]
# ### Create pyPRMS dimensioning parameter files .csv from the .gpkg
# This section creates several .csv files from the child .gpkg that are used by pyPRMS to generate a parameter database (child.pdb) and write the pywatershed parameter file.

# %% [markdown]
# #### Create the nhm_id.csv from the GIS subset domain
# The nhm_id.csv file contains the parent, or global, hru index for each hru in the child domain, indexed from 1 to n. The index of the nhm_id.csv file is used by pywatershed for internal processing when running the child model, indexed from 1 to n. This file is key for connecting the child hru to the parent parameter database and for dispaying model parameters and output using the .gpkg in NHM-assist. It is strongly recommended that when creating the child .gpkg, that the nhm_id be indexed in ascending order.

# %%
param_source_files_dir = child_hf_dir / "param_source_files"
param_source_files_dir.mkdir(parents=True, exist_ok=True)

# %%
nhm_id_temp = hru_gdb.hru_id.astype(int)
nhm_id_temp = nhm_id_temp.sort_values()
nhm_id_temp.index = range(1, len(nhm_id_temp) + 1)  # Change index from 0-n, to 1-n

with open(param_source_files_dir / "nhm_id.csv", "w", newline="") as f:
    f.write("$id,nhm_id\n")
    nhm_id_temp.to_csv(f, index=True, header=False)

# %% [markdown]
# #### Create the nhm_seg.csv from the GIS subset domain
# The nhm_seg_id.csv file contains the parent, or global, segment_id for each hru in the child domain, indexed from 1 to n. The index of the file is essentially the segment_id for each hru in the child domain. This file is key for connecting the child segment to the parent parameter database and for dispaying model parameters and output using the .gpkg in NHM-assist. It is strongly recommended that when creating the child .gpkg, that the nhm_seg_id be indexed in ascending order.

# %%
nhm_seg_temp = seg_gdb.segment_id.astype(int)
nhm_seg_temp = nhm_seg_temp.sort_values()  # Sorting may be causing errors
nhm_seg_temp.index = range(1, len(nhm_seg_temp) + 1)

with open(param_source_files_dir / "nhm_seg.csv", "w", newline="") as f:
    f.write("$id,nhm_seg\n")
    nhm_seg_temp.to_csv(f, index=True, header=False)

# %% [markdown]
# #### Create the poi_type.csv and all the npoigage dimensioned parameter .csv files
# These parameters are highly tailored for specific model application. In this section, a subset of pois associated with streamflow gages from the GFv2 are selected for the child domain and are filtered to include gages that have at least one year of daily discharge data. Note: this gage list is meant to be a starting point and often, and likely, incomplete for the domain. NHM-assist offers workflows that can be used to evaluate other gages in the domain and add gages to the paramter file if needed.

# %%
child_npoi_gdf = poi_gdb.copy()
child_npoi_gdf["segment_id"] = child_npoi_gdf["segment_id"].astype(
    int
)  # or 'int' / 'Int64'

# %%
poi_gdb.columns

# %% [markdown]
# ##### Create a unique id for each poi for cross-reference
# At this time, the poi_id is only unique to each regional watershed. A unique poi_id much be created for the OHM regional model domain that includes 3 regional watershed. This id, `merge_id`, is only used to cross-referrence the pois in the Gfv2 .gpkg with poi metadata in a GFv2 table provided in the .gpkg.

# %%
child_npoi_gdf["merge_id"] = (
    child_npoi_gdf["vpu"].astype(str) + "-" + child_npoi_gdf["vpu_poi_id"].astype(str)
)

# %%
child_npoi_gdf

# %% [markdown]
# ##### `merge_id` checks

# %%
# Check if merge-id are all unique
has_duplicates = child_npoi_gdf["merge_id"].duplicated().any()
print(
    f"Does the poi merge_id have_duplicates? {has_duplicates}"
)  # True if duplicates exist

# Check for NaNs in geometry and segment id
if child_npoi_gdf["geometry"].isna().any() == True:
    rows_with_geo_nan = child_npoi_gdf[child_npoi_gdf["geometry"].isna()]
    print("The following pois have NaN for geometry")
    print(rows_with_geo_nan)
else:
    print("All pois have values for geometry")

if child_npoi_gdf["segment_id"].isna().any():
    rows_with_geo_nan = child_npoi_gdf[child_npoi_gdf["segment_id"].isna()]
    print("The following pois have NaN for segment_id")
    print(rows_with_geo_nan)
else:
    print("All pois have values for segment_id")

# Kepp only selected columns
cols_to_keep = ["segment_id", "geometry", "merge_id"]
child_npoi_gdf = child_npoi_gdf[cols_to_keep].copy()

# %%
child_npoi_gdf.info()

# %%
# child_npoi_gdf.loc[child_npoi_gdf["segment_id"] == 0]
# child_npoi_gdf.loc[child_npoi_gdf["merge_id"] == "17-15012"]

# %% [markdown]
# ##### Import the poi metadata (npoi_data) included in the GF
# The metadata is referrenced directly from the parent .gpkg

# %%
gpkg_path = root_dir / "hydrofabric_domain_data/OR_v2_domain/GIS/NHM_OR_draft.gpkg"
npoi_data = gpd.read_file(gpkg_path, layer="npoi_data")

gage_data_df = npoi_data.loc[
    npoi_data.hl_reference == "type_gage"
]  # not to be confused with pws "poi_typo" param

# Get the list of HUC-12s for the child model area
huc12pp_df = npoi_data.loc[npoi_data.hl_reference == "type_huc12"]

# %% [markdown]
# ##### Create a unique id for each poi for cross-reference

# %%
gage_data_df["merge_id"] = (
    gage_data_df["vpu"].astype(str) + "-" + gage_data_df["vpu_poi_id"].astype(str)
)

huc12pp_df["merge_id"] = (
    huc12pp_df["vpu"].astype(str) + "-" + huc12pp_df["vpu_poi_id"].astype(str)
)

# %% [markdown]
# ##### Dataframe checks

# %%
# Check for duplicates in the merge_id
if gage_data_df["merge_id"].duplicated().any():
    dupe_rows = gage_data_df[
        gage_data_df["merge_id"].duplicated(keep=False)
    ].sort_values("merge_id")
    print(
        "The following POIs have multiple associated gages. Please correct below and notify A. Bock."
    )
    display(dupe_rows)
else:
    print(
        "All POIs have only one associated gage. Clear to move ahead in the notebook."
    )

if gage_data_df["hl_link"].duplicated().any():
    dupe_rows = gage_data_df[
        gage_data_df["hl_link"].duplicated(keep=False)
    ].sort_values("hl_link")
    print(
        "The following POIs have the same associated gage. To correct these, the segment_id must be merged from the npoi layer."
    )
    display(dupe_rows)

# %% [markdown]
# ##### Pre-merge Meta data corrections

# %% [markdown]
# After Review of merge_id duplicates, merge_id TB-890 should have a hl_link value of 12404500.

# %%
gage_data_df.loc[gage_data_df.merge_id == "TB-890", "hl_link"] = "12404500"
# Drop duplicates
gage_data_df.drop_duplicates(inplace=True)

# %% [markdown]
# After review of the pois with "gages" for a gage_id...
# 18-8687 : 11532700, ROWDY C A SMITH R CA
# 18-8714 : no gage present

# %%
gage_data_df.loc[gage_data_df.merge_id == "18-8687", "hl_link"] = "11532700"

# %% [markdown]
# #### Create a (gage) poi dataframe to build needed poi params for the pywatershed model (child)
# This merge links the metadata for each poi to the segment_id and geometery from the child .gpkg using the `merge_id`.Merge geometry and segment_id from .gpkg npoi_layer with poi metadata table

# %%
poi_gdf = pd.merge(
    child_npoi_gdf,
    gage_data_df,
    left_on="merge_id",
    right_on="merge_id",
    how="inner",
)

huc12pp_gdf = pd.merge(
    child_npoi_gdf,
    huc12pp_df,
    left_on="merge_id",
    right_on="merge_id",
    how="inner",
)

# %% [markdown]
# #### Post-merge corrections
# Now we can correct the POIs have the same associated gage. 

# %% jupyter={"source_hidden": true}
if poi_gdf["segment_id"].isna().any():
    na_rows = poi_gdf[poi_gdf["segment_id"].isna()].sort_values("hl_link")
    print(
        "The following POIs have no value for segment_id. Please correct below and notify A. Bock."
    )
    display(na_rows)
else:
    print(
        "All POIs have values for segment_id. Move on to correct POIs that have the same associated gage."
    )

if poi_gdf["hl_link"].duplicated().any():
    dupe_rows = poi_gdf[poi_gdf["hl_link"].duplicated(keep=False)].sort_values(
        "hl_link"
    )
    print(
        "The following POIs have the same associated gage. Please correct below and notify A. Bock."
    )
    display(dupe_rows)
else:
    print("All POIs have only one associated gage.")

# %% [markdown]
# #### Corrections for segment_id no values
# If no values, or NaNs, exist in the segment id column, make those corrections first and note they may superceed previous corrections.

# %%
# # for gage 14011000, the poi is not present in npoi layer --tell Andy. But correct here.
# # note: hl_link is object and segment_id is float64
# # Add segment id of 17516 for this gage
# poi_gdf.loc[poi_gdf.hl_link == "14011000", "segment_id"] = 17516
# #
# # for gage 12399600, the poi is associated with the wrong merge_id that doesn't exist in the npoi_data layer --tell Andy.
# # should be associated with 17-1808 merge_id. Fix here and Tell Andy.
# poi_gdf.loc[poi_gdf.hl_link == "12399600", "segment_id"] = 8455
# #
# # for gage 12404500, this gage should be associated with TB-890, which exists in the df, but has the wrong gage associated.
# # fix by changing the gage_id for TB-890 to 12404500.
# poi_gdf.loc[poi_gdf.merge_id == "TB-890", "hl_link"] = "12404500"
# # but this won't fix the whole issue,
# # now we have to look into this meta data record and either delete it or see in another gage should be here at 17-1920.
# # We find that 17 1920 doesn't exist in the npoi layer, so delete the record and tell Andy.
# poi_gdf.drop(1842, inplace=True)

# %% [markdown]
# #### Now that the NaNs are removed, we can convert the data type back to Int

# %%
poi_gdf["segment_id"] = poi_gdf["segment_id"].astype(int)

# %% [markdown]
# #### Make remaining corrections

# %%
# # segment 19897 should be associated with gage id: 11531500
# poi_gdf.loc[poi_gdf.segment_id == 19897, "hl_link"] = "11531500"
# #
# # segment 20342 appears to be an outflow point into CA, and has this gage_id 11532700
# poi_gdf.loc[poi_gdf.segment_id == 20342, "hl_link"] = "11532700"
# #
# 17-19652 and 17-19570 should have no gage on it. Tell Andy to change the poi_type to non cntributing segment. for now, drop.
# poi_gdf = poi_gdf.drop(poi_gdf[poi_gdf["merge_id"] == "17-19652"].index)
poi_gdf = poi_gdf.drop(poi_gdf[poi_gdf["merge_id"] == "17-19570"].index)

# %%
poi_gdf[poi_gdf["segment_id"].isna()]

# %% [markdown]
# #### Note: Column rename
# In the child .gpkg, the original column headers remain. The `segment_id` column in this dataframe is misnamed, and represents the parent segment_id, and therefore must be renamed `nhm_seg_id`

# %%
poi_gdf_child = poi_gdf.copy()
poi_gdf_child.rename(columns={"segment_id": "nhm_seg_id"}, inplace=True)

# %% [markdown]
# Now create a mapping series to find the child segment_id (child) associated with the nhm_seg_id (parent) and add the segment_id to the dataframe.

# %%
seg_mapping_series = pd.Series(nhm_seg_temp.index, index=nhm_seg_temp.values)
seg_mapping_df = seg_mapping_series.reset_index()
seg_mapping_df.columns = ["nhm_seg_id", "segment_id"]  # rename as needed
seg_mapping = seg_mapping_df.set_index("nhm_seg_id")["segment_id"]

poi_gdf_child["segment_id"] = poi_gdf_child["nhm_seg_id"].map(seg_mapping)

# %%
huc12pp_gdf_child = huc12pp_gdf.copy()
huc12pp_gdf_child.rename(columns={"segment_id": "nhm_seg_id"}, inplace=True)
huc12pp_gdf_child["segment_id"] = huc12pp_gdf_child["nhm_seg_id"].map(seg_mapping)

# %% [markdown]
# Check if a gage was included in the poi dateframe (poi_gdf_child) that had no segment mapped to it. This would happen if the pois selected in the child domain fell on segments not included in the child segment domain.

# %%
nan_rows = poi_gdf_child[poi_gdf_child["segment_id"].isna()]
print(
    list(nan_rows["hl_link"]),
    " removed, and associated with a segment(s) outside of the model domain.",
)

poi_gdf_child = poi_gdf_child.dropna(subset=["segment_id"])
poi_gdf_child["segment_id"] = poi_gdf_child["segment_id"].astype(int)
poi_gdf_child.sort_values(by="hl_link", ascending=True, inplace=True)
poi_gdf_child.reset_index(inplace=True, drop=True)
poi_gdf_child["poi_type"] = 1

# %%
nan_rows = huc12pp_gdf_child[huc12pp_gdf_child["segment_id"].isna()]
print(
    list(nan_rows["hl_link"]),
    " removed, and associated with a segment(s) outside of the model domain.",
)
huc12pp_gdf_child = huc12pp_gdf_child.dropna(subset=["segment_id"])
huc12pp_gdf_child["segment_id"] = huc12pp_gdf_child["segment_id"].astype(int)
huc12pp_gdf_child.sort_values(by="hl_link", ascending=True, inplace=True)
huc12pp_gdf_child.reset_index(inplace=True, drop=True)

# %% [markdown]
# #### Remove poi's that have no flow data for period 1979-10-01 to 2025-09-30 and populated site information
# Update with Luca's fix when is done

# %%
noq_list = []
poi_gdf_child["poi_id"] = (
    np.nan
)  # Added temporarily as fetch function criteria for NHM-assist.

for ii in list(poi_gdf_child.hl_link):
    data = fetch_single_nwis_gage(ii, "1979-10-01", "2025-09-30", poi_gdf_child, 365)
    df = data[1]

    if isinstance(df, pd.DataFrame):
        if df["00060_Mean"].isna().all():
            noq_list.append(ii)
            print(
                f"{ii} --Added to noq_gages_file. No streamflow obs from 10/01/1979 to 9/30/2025."
            )
        else:
            print(
                f"{ii} --Added parameter file. >365 streamflow obs from 10/01/1979 to 9/30/2025. "
            )
    else:
        noq_list.append(ii)

# Update list of gages for the param file to those only with discharge data in NWIS
gage_poi_flow_list = [x for x in list(poi_gdf_child.hl_link) if x not in noq_list]
poi_gdf_child.drop(columns=["poi_id"], inplace=True)  # Remove column to avoid confusion

# %% [markdown]
# #### Now, some reshaping an cleaning of the gage poi information prior to parameter csv file creation
# This involves reshaping the dataframe to these column names:
# 'poi_gage_id', 'poi_gage_segment', 'poi_type'

# %%
# Create npoigages_params_df (used to make params)
npoigages_params_gdf = poi_gdf_child.copy()
npoigages_params_df = npoigages_params_gdf[
    ["hl_link", "segment_id", "nhm_seg_id", "poi_type"]
]
npoigages_params_df.rename(columns={"hl_link": "poi_gage_id"}, inplace=True)
npoigages_params_df = npoigages_params_df.sort_values("poi_gage_id")

# %% [markdown]
# The parmater file cannot have more than one gage associated with a segment. If more than one gage has been associated with a segment, all gages will be written to the gage_resource_info.csv. These gages can be further evaluated and can be exchanged in the model using using NHM-assist. The gage with the longest POR will be selected here and associated with the segment.

# %% jupyter={"source_hidden": true}
has_duplicates = npoigages_params_df["segment_id"].duplicated().any()
if has_duplicates == True:
    rows_with_duplicates = npoigages_params_df[
        npoigages_params_df["segment_id"].duplicated(keep=False)
    ]
    segment_list = list(set(rows_with_duplicates["segment_id"]))
    for segment in segment_list:
        segment_gages_list = list(
            set(
                rows_with_duplicates.loc[rows_with_duplicates["segment_id"] == segment][
                    "poi_gage_id"
                ]
            )
        )

        ###Eval gage lengths here
        display(
            dup_segment_gages_info.loc[
                dup_segment_gages_info["poi_gage_id"].isin(segment_gages_list)
            ]
        )
        print(f"{segment_gages_list} are associated with segment {segment}.")
else:
    print("No duplicates.")

# %%
# npoigages_params_df.drop_duplicates(subset=["segment_id"], inplace=True, keep="last")

# %%
# Create npoigages_info_df and .csv file
npoigages_info_df = find_missing_gage_info(
    root_dir, child_pws_dir, list(npoigages_params_df.poi_gage_id), "npoigages_info"
)

# %%
# Add all gages in the domain to the info file to be used in all visualization notebooks.

# %%
# make the npoigages_info_df file in the child hf domain folser as well for backup
npoigages_file = child_hf_dir / "npoigages_info.csv"
npoigages_info_df.to_csv(npoigages_file, index=False)

# %%
# Create the poi_type.csv from the GIS subset domain
nhm_poi_temp = npoigages_params_df.poi_type.astype(int)
nhm_poi_temp.index = nhm_poi_temp.index + 1
with open(child_hf_dir / "param_source_files/poi_type.csv", "w", newline="") as f:
    f.write("$id,poi_type\n")
    nhm_poi_temp.to_csv(f, index=True, header=False)

# create the poi_gage_id.csv from the GIS subset domain
nhm_poi_temp = npoigages_params_df.poi_gage_id.astype(str)
nhm_poi_temp.index = nhm_poi_temp.index + 1
with open(child_hf_dir / "param_source_files/poi_gage_id.csv", "w", newline="") as f:
    f.write("$id,poi_gage_id\n")
    nhm_poi_temp.to_csv(f, index=True, header=False)

# create the poi_gage_segment.csv from the GIS subset domain
nhm_poi_temp = npoigages_params_df.segment_id.astype(int)
nhm_poi_temp.index = nhm_poi_temp.index + 1
with open(
    child_hf_dir / "param_source_files/poi_gage_segment.csv", "w", newline=""
) as f:
    f.write("$id,poi_gage_segment\n")
    nhm_poi_temp.to_csv(f, index=True, header=False)

# %% [markdown]
# Save out a new gpkg of model layers

# %%
gpkg_dir = child_pws_dir / "GIS"
gpkg_path = gpkg_dir / "model_layers.gpkg"

# %%
# new HRUs
hru_mapping_series = pd.Series(nhm_id_temp.index, index=nhm_id_temp.values)
hru_mapping_df = hru_mapping_series.reset_index()
hru_mapping_df.columns = ["nhm_id", "hru_id"]  # rename as needed
hru_mapping = hru_mapping_df.set_index("nhm_id")["hru_id"]

hru_child_gdf = hru_gdb.copy()
# hru_child_gdf["segment_id"] = hru_child_gdf["nhm_hru_seg"].map(seg_mapping)

# Change to column names to match child poigages gdf

hru_child_gdf.drop(columns="nhm_hru_seg", inplace=True)  # Junk from national coverage
hru_child_gdf.drop(columns="nhm_id", inplace=True)  # Junk from national coverage

hru_child_gdf.rename(
    columns={"hru_segment": "nhm_hru_seg", "hru_id": "nhm_id"}, inplace=True
)
hru_child_gdf["hru_id"] = hru_child_gdf["nhm_id"].map(hru_mapping)

hru_child_gdf["hru_segment"] = hru_child_gdf["nhm_hru_seg"].map(seg_mapping)
hru_child_gdf["hru_segment"] = hru_child_gdf["hru_segment"].fillna(
    0
)  # HRU's with Nan flow directly to the ocean; 0 = Ocean
hru_child_gdf.hru_segment = hru_child_gdf.hru_segment.astype(int)
hru_child_gdf

# %%
# Change to column names to match child poigages gdf
seg_child_gdf = seg_gdb.copy()
seg_child_gdf.drop(columns="nhm_seg_id", inplace=True)  # vestigial ids
seg_child_gdf.drop(columns="to_nhm_seg", inplace=True)  # vestigial ids

seg_child_gdf.rename(
    columns={"segment_id": "nhm_seg_id", "to_segment": "to_nhm_seg"}, inplace=True
)

seg_child_gdf["segment_id"] = seg_child_gdf["nhm_seg_id"].map(seg_mapping)
seg_child_gdf["to_segment"] = seg_child_gdf["to_nhm_seg"].map(seg_mapping)
seg_child_gdf["to_segment"] = seg_child_gdf["to_segment"].fillna(
    0
)  # to_segments may not be in the model domain; 0 = Ocean
seg_child_gdf.to_segment = seg_child_gdf.to_segment.astype(int)
seg_child_gdf

# %%
# ###### Merge and make layer for the child .gpkg
# npoigages_gpkg_df = pd.merge(npoigages_params_df, npoigages_info_df, on="poi_gage_id")
# geopackage_gdf = gpd.GeoDataFrame(
#     npoigages_gpkg_df,
#     geometry=gpd.points_from_xy(npoigages_gpkg_df["longitude"], npoigages_gpkg_df["latitude"]),
#     crs="EPSG:4326",  # WGS84 lat/lon
# ).to_crs(seg_child_gdf.crs)

# # geopackage_gdf.to_file("my_data.gpkg", layer="my_layer", driver="GPKG")

# %%
print(
    "Of the",
    len(list(poi_gdf_child.hl_link)),
    "'type_gage' pois in the GF, only",
    len(gage_poi_flow_list),
    "have discharge data in NWIS for the simulation period, and will be included in the parameter file.",
)
poi_gdf3 = poi_gdf_child.loc[poi_gdf_child["hl_link"].isin(gage_poi_flow_list)]
print(
    "Only the",
    len(gage_poi_flow_list),
    "poigages that have flow will be included in the parameter file.",
    "If other gages are needed, refer to the following section.",
)

# %% [markdown]
# ### Customizing the npoigages to be added to the model
# This section allows the user to supply a list of gages, with metadata, to be added to the parametr file. These will likely be non-USGS gages or USGS-gages that have no streamflow data.
#
# Gage lists are typically supplied (preferred) as .csv or .shp files with these 7 fields (the first 5 are required):
# >**poi_gage_id, poi_agency, poi_name, latitude, longitude,** drainage_area, drainage_area_contrib
#
# If a gage file lacks the required fields, missing fields will be added from existing gage databases in this order:
# >1. NLDI database, https://github.com/internetofwater/ref_gages/releases/tag/v1.6
# >2. USGS Water Data for the Nation database,
# >3. A resource file (resource_gage_info.csv) supplied by user
# > **Note: If the resource file has already been created, this file will be prioritized in the order.
# >   Allowing users to correct information that was gathered on a previous pull.**
#
#

# %% [markdown]
# #### Reading, Reshaping, and Appending supplemental gages to the parameter file
# Gage list(s) are read from place in the `child_dir / supplemental_gages` folder 
# Two cases are covered in this section. Gage files contain:
# >Case 1 (preferred) - Gages are supplied with
# >1. Gage id number (poi_gage_id),
# >2. Agency managng the gage (poi_agency),
# >3. gage names (poi_name)
# >4. geometry or lat/lon coordinates (latitude, longitude)
#
# >Case 2 (minimum) - 
# >1. Gage id number (poi_gage_id)

# %% [markdown]
# ##### Add Oregon Recharge Project "base-flow" (BF) gages file
# Read in gage file (.shp) of gages used in the Oregon Statewide Recharge project's baseflow study

# %%
bf_gages_dir = f"{parent_dir}/npoigages_data/baseflow_gages"
bf_gages_gdf = gpd.read_file(f"{bf_gages_dir}/baseflow_gages.shp").to_crs(
    seg_child_gdf.crs
)

col = "site_no"
num = pd.to_numeric(bf_gages_gdf[col], errors="coerce")

# Make site ids ints (if numbers), then and back to string, preserving original non-numeric strings
bf_gages_gdf[col] = num.dropna().astype(int).astype(str)  # numeric ones -> "3454"
bf_gages_gdf[col] = bf_gages_gdf[col].fillna(
    bf_gages_gdf[col].astype(str)
)  # fill NaNs with original strings

bf_gages_gdf = gpd.clip(bf_gages_gdf, aoi_gdb)  # Clip to the child domain


bf_gages_gdf = bf_gages_gdf[
    ["site_no", "most_recen", "station_na", "latitude_d", "longitude_", "geometry"]
]
bf_gages_gdf.rename(
    columns={
        "site_no": "poi_gage_id",
        "most_recen": "poi_agency",
        "station_na": "poi_name",
        "latitude_d": "latitude",
        "longitude_": "longitude",
    },
    inplace=True,
)
bf_gages_gdf["drainage_area"] = np.nan
bf_gages_gdf["drainage_area_contrib"] = np.nan
bf_gages_gdf["poi_type"] = 1

new_gages_list = [
    x
    for x in list(set(bf_gages_gdf.poi_gage_id))
    if x not in list(npoigages_params_df.poi_gage_id)
]
if len(new_gages_list) != 0:
    print(
        f"There are {len(new_gages_list)} poi_gage_id that are not currently in the {len(npoigages_params_df)} npoigages_params_df."
    )
    ###### Make new gages geodataframe, create needed npoigages params and concatenate to existing
    new_gages_gdf = bf_gages_gdf[bf_gages_gdf["poi_gage_id"].isin(new_gages_list)]
    new_npoigages_params = find_nearest_endpoint(
        new_gages_gdf, seg_child_gdf, line_id_col="nhm_seg_id"
    )
    npoigages_params_df_temp = pd.concat(
        [npoigages_params_df, new_npoigages_params], ignore_index=True
    )
    npoigages_params_df = npoigages_params_df_temp.copy()

    ######## Make npoigages_info_df and concatenate to existing
    info_cols = [
        "poi_gage_id",
        "poi_agency",
        "poi_name",
        "latitude",
        "longitude",
        "drainage_area",
        "drainage_area_contrib",
    ]
    new_gages_info_df = bf_gages_gdf[bf_gages_gdf["poi_gage_id"].isin(new_gages_list)]
    new_gages_info_df = new_gages_info_df[info_cols]
    npoigages_info_df_temp = pd.concat(
        [npoigages_info_df, new_gages_info_df], ignore_index=True
    )
    npoigages_info_df = npoigages_info_df_temp.copy()
else:
    print(
        f"All poi_gage_id are currently in the {len(npoigages_params_df)} npoigages_params_df."
    )

# %% [markdown]
# ##### Add Oregon Recharge Project "current" Specific Conductance sites (SC_current)
# Read in gage file (.shp) of gages used in the Oregon Statewide Recharge project's SC data collection sites

# %%
### List of current gages where SC data was collected (Oregon Recharge Project)
sc_current_dir = f"{parent_dir}/npoigages_data/OR_SC_sites"
sc_current_gdf = gpd.read_file(f"{sc_current_dir}/OR_current_SC.shp").to_crs(
    seg_child_gdf.crs
)

col = "site_no"
num = pd.to_numeric(sc_current_gdf[col], errors="coerce")

# Make site ids ints (if numbers), then and back to string, preserving original non-numeric strings
sc_current_gdf[col] = num.dropna().astype(int).astype(str)  # numeric ones -> "3454"
sc_current_gdf[col] = sc_current_gdf[col].fillna(
    sc_current_gdf[col].astype(str)
)  # fill NaNs with original strings

sc_current_gdf = gpd.clip(sc_current_gdf, aoi_gdb)  # Clip to the child domain

sc_current_gdf = sc_current_gdf[
    ["site_no", "station_na", "latitude_d", "longitude_", "geometry"]
]
sc_current_gdf.rename(
    columns={
        "site_no": "poi_gage_id",
        "station_na": "poi_name",
        "latitude_d": "latitude",
        "longitude_": "longitude",
    },
    inplace=True,
)
sc_current_gdf["poi_agency"] = "UNKWN"
sc_current_gdf["drainage_area"] = np.nan
sc_current_gdf["drainage_area_contrib"] = np.nan
sc_current_gdf["poi_type"] = 1

new_gages_list = [
    x
    for x in list(set(sc_current_gdf.poi_gage_id))
    if x not in list(npoigages_params_df.poi_gage_id)
]
if len(new_gages_list) != 0:
    print(
        f"There are {len(new_gages_list)} poi_gage_id that are not currently in the {len(npoigages_params_df)} npoigages_params_df."
    )
    ###### Make new gages geodataframe, create needed npoigages params and concatenate to existing
    new_gages_gdf = sc_current_gdf[sc_current_gdf["poi_gage_id"].isin(new_gages_list)]
    new_npoigages_params = find_nearest_endpoint(
        new_gages_gdf, seg_child_gdf, line_id_col="nhm_seg_id"
    )
    npoigages_params_df_temp = pd.concat(
        [npoigages_params_df, new_npoigages_params], ignore_index=True
    )
    npoigages_params_df = npoigages_params_df_temp.copy()

    ######## Make npoigages_info_df and concatenate to existing
    info_cols = [
        "poi_gage_id",
        "poi_agency",
        "poi_name",
        "latitude",
        "longitude",
        "drainage_area",
        "drainage_area_contrib",
    ]
    new_gages_info_df = sc_current_gdf[
        sc_current_gdf["poi_gage_id"].isin(new_gages_list)
    ]
    new_gages_info_df = new_gages_info_df[info_cols]
    npoigages_info_df_temp = pd.concat(
        [npoigages_info_df, new_gages_info_df], ignore_index=True
    )
    npoigages_info_df = npoigages_info_df_temp.copy()
else:
    print(
        f"All poi_gage_id are currently in the {len(npoigages_params_df)} npoigages_params_df."
    )

# %% [markdown]
# ##### Add Oregon Recharge Project "possible" Specific Conductance sites (SC_current)
# Read in gage file (.shp) of gages used in the Oregon Statewide Recharge project's SC data collection sites

# %%
### List of possible gages where SC data was collected (Oregon Recharge Project)
sc_possible_dir = f"{parent_dir}/npoigages_data/OR_SC_sites"
sc_possible_gdf = gpd.read_file(f"{sc_possible_dir}/OR_possible_SC.shp").to_crs(
    seg_child_gdf.crs
)

col = "site_no"
num = pd.to_numeric(sc_possible_gdf[col], errors="coerce")

# Make site ids ints (if numbers), then and back to string, preserving original non-numeric strings
sc_possible_gdf[col] = num.dropna().astype(int).astype(str)  # numeric ones -> "3454"
sc_possible_gdf[col] = sc_possible_gdf[col].fillna(
    sc_possible_gdf[col].astype(str)
)  # fill NaNs with original strings

sc_possible_gdf = gpd.clip(sc_possible_gdf, aoi_gdb)  # Clip to the child domain

sc_possible_list = sc_possible_gdf["site_no"].astype(str).tolist()


sc_possible_gdf = sc_possible_gdf[
    ["site_no", "station_na", "latitude_d", "longitude_", "geometry"]
]
sc_possible_gdf.rename(
    columns={
        "site_no": "poi_gage_id",
        "station_na": "poi_name",
        "latitude_d": "latitude",
        "longitude_": "longitude",
    },
    inplace=True,
)
sc_possible_gdf["poi_agency"] = "UNKWN"
sc_possible_gdf["drainage_area"] = np.nan
sc_possible_gdf["drainage_area_contrib"] = np.nan
sc_possible_gdf["poi_type"] = 1

new_gages_list = [
    x
    for x in list(set(sc_possible_gdf.poi_gage_id))
    if x not in list(npoigages_params_df.poi_gage_id)
]
if len(new_gages_list) != 0:
    print(
        f"There are {len(new_gages_list)} poi_gage_id that are not currently in the {len(npoigages_params_df)} npoigages_params_df."
    )
    ###### Make new gages geodataframe, create needed npoigages params and concatenate to existing
    new_gages_gdf = sc_possible_gdf[sc_possible_gdf["poi_gage_id"].isin(new_gages_list)]
    new_npoigages_params = find_nearest_endpoint(
        new_gages_gdf, seg_child_gdf, line_id_col="nhm_seg_id"
    )
    npoigages_params_df_temp = pd.concat(
        [npoigages_params_df, new_npoigages_params], ignore_index=True
    )
    npoigages_params_df = npoigages_params_df_temp.copy()

    ######## Make npoigages_info_df and concatenate to existing
    info_cols = [
        "poi_gage_id",
        "poi_agency",
        "poi_name",
        "latitude",
        "longitude",
        "drainage_area",
        "drainage_area_contrib",
    ]
    new_gages_info_df = sc_possible_gdf[
        sc_possible_gdf["poi_gage_id"].isin(new_gages_list)
    ]
    new_gages_info_df = new_gages_info_df[info_cols]
    npoigages_info_df_temp = pd.concat(
        [npoigages_info_df, new_gages_info_df], ignore_index=True
    )
    npoigages_info_df = npoigages_info_df_temp.copy()
else:
    print(
        f"All poi_gage_id are currently in the {len(npoigages_params_df)} npoigages_params_df."
    )

# %% [markdown]
# ##### Add Oregon Recharge Project streamflow gages where Flow Management Index was determined (FMI_npoigages)
# Read in gage file (.shp) of gages used in the Oregon Statewide Recharge project's FMI gages

# %%
# If just given a list of Gage IDs
FMI_GagedWatersheds_dir = pl.Path(f"{parent_dir}/npoigages_data/FMI_gages")
FMI_GagedWatersheds_gdf = gpd.read_file(
    FMI_GagedWatersheds_dir / "GagedWatersheds.shp"
).to_crs(seg_child_gdf.crs)
col = "Name"
num = pd.to_numeric(FMI_GagedWatersheds_gdf[col], errors="coerce")

# Make site ids ints (if numbers), then and back to string, preserving original non-numeric strings
FMI_GagedWatersheds_gdf[col] = (
    num.dropna().astype(int).astype(str)
)  # numeric ones -> "3454"
FMI_GagedWatersheds_gdf[col] = FMI_GagedWatersheds_gdf[col].fillna(
    FMI_GagedWatersheds_gdf[col].astype(str)
)  # fill NaNs with original strings

FMI_gages_df = FMI_GagedWatersheds_gdf[["Name", "areasqmi"]]
FMI_gages_df.rename(
    columns={
        "Name": "poi_gage_id",
        "areasqmi": "drainage_area",
    },
    inplace=True,
)
FMI_gages_df["poi_agency"] = np.nan
FMI_gages_df["poi_name"] = np.nan
FMI_gages_df["drainage_area_contrib"] = np.nan
FMI_gages_df["latitude"] = np.nan
FMI_gages_df["longitude"] = np.nan
FMI_gages_df["poi_type"] = 1

FMI_gages_list = FMI_gages_df["poi_gage_id"].astype(str).tolist()
new_gages_list = [
    x
    for x in list(set(FMI_gages_list))
    if x not in list(npoigages_params_df.poi_gage_id)
]
if len(new_gages_list) != 0:
    #
    # new_gages_df = FMI_gages_df[FMI_gages_df["poi_gage_id"].isin(new_gages_list)]

    # root_dir, dest_dir, gages_list, info_file_name
    new_gages_df = find_missing_gage_info(
        root_dir, FMI_GagedWatersheds_dir, new_gages_list, "fmi_npoigages_info"
    )
    new_gages_df["poi_type"] = 1

    ###### Make new gages geodataframe, create needed npoigages params and concatenate to existing
    new_gages_gdf = gpd.GeoDataFrame(
        new_gages_df,
        geometry=gpd.points_from_xy(
            new_gages_df["longitude"], new_gages_df["latitude"]
        ),
        crs="EPSG:4326",  # WGS84 lat/lon
    ).to_crs(seg_child_gdf.crs)
    print(new_gages_gdf.crs)

    new_gages_gdf = gpd.clip(new_gages_gdf, aoi_gdb)
    # print(
    #     f"... of the {len(new_gages_list)} FMI gages, {len(new_gages_gdf)} are in the child domain."
    # )

    if len(new_gages_gdf) != 0:
        new_npoigages_params = find_nearest_endpoint(
            new_gages_gdf, seg_child_gdf, line_id_col="nhm_seg_id"
        )
        npoigages_params_df_temp = pd.concat(
            [npoigages_params_df, new_npoigages_params], ignore_index=True
        )
        npoigages_params_df = npoigages_params_df_temp.copy()

        ######## Make npoigages_info_df and concatenate to existing
        info_cols = [
            "poi_gage_id",
            "poi_agency",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
        ]
        new_gages_info_df = new_gages_df[
            new_gages_df["poi_gage_id"].isin(new_gages_list)
        ]
        new_gages_info_df = new_gages_info_df[info_cols]
        npoigages_info_df_temp = pd.concat(
            [npoigages_info_df, new_gages_info_df], ignore_index=True
        )
        npoigages_info_df = npoigages_info_df_temp.copy()
    else:
        print("There are no FMI gages that intersect the child domain.")
else:
    print(
        f"All poi_gage_id are currently in the {len(npoigages_params_df)} npoigages_params_df."
    )

# %%
npoigages_info_df

# %% [markdown]
# #### Write npoigages parameter files (.csv)

# %% [markdown]
# The parmater file cannot have more than one gage associated with a segment. If more than one gage has been associated with a segment, all gages will be written to the gage_resource_info.csv. These gages can be further evaluated and can be exchanged in the model using using NHM-assist. The gage with the longest POR will be selected here and associated with the segment.

# %%
has_duplicates = npoigages_params_df["segment_id"].duplicated().any()
if has_duplicates == True:
    rows_with_duplicates = npoigages_params_df[
        npoigages_params_df["segment_id"].duplicated(keep=False)
    ]
    segment_list = list(set(rows_with_duplicates["segment_id"]))
    for segment in segment_list:
        segment_gages_list = list(
            set(
                rows_with_duplicates.loc[rows_with_duplicates["segment_id"] == segment][
                    "poi_gage_id"
                ]
            )
        )
        dup_segment_gages_info = rows_with_duplicates.loc[
            rows_with_duplicates["segment_id"] == segment
        ]
        ###Eval gage lengths here
        display(
            dup_segment_gages_info.loc[
                dup_segment_gages_info["poi_gage_id"].isin(segment_gages_list)
            ]
        )
        print(f"{segment_gages_list} are associated with segment {segment}.")
else:
    print("No duplicates.")

# %%
npoigages_params_df.drop_duplicates(subset=["segment_id"], inplace=True, keep="last")

# %%
# create the poi_type.csv from the GIS subset domain
nhm_poi_temp = npoigages_params_df.poi_type.astype(int)
nhm_poi_temp.index = nhm_poi_temp.index + 1
with open(child_hf_dir / "param_source_files/poi_type.csv", "w", newline="") as f:
    f.write("$id,poi_type\n")
    nhm_poi_temp.to_csv(f, index=True, header=False)

# create the poi_gage_id.csv from the GIS subset domain
nhm_poi_temp = npoigages_params_df.poi_gage_id.astype(str)
nhm_poi_temp.index = nhm_poi_temp.index + 1
with open(child_hf_dir / "param_source_files/poi_gage_id.csv", "w", newline="") as f:
    f.write("$id,poi_gage_id\n")
    nhm_poi_temp.to_csv(f, index=True, header=False)

# create the poi_gage_segment.csv from the GIS subset domain
nhm_poi_temp = npoigages_params_df.segment_id.astype(int)
nhm_poi_temp.index = nhm_poi_temp.index + 1
with open(
    child_hf_dir / "param_source_files/poi_gage_segment.csv", "w", newline=""
) as f:
    f.write("$id,poi_gage_segment\n")
    nhm_poi_temp.to_csv(f, index=True, header=False)

# %% [markdown]
# Write the npoigages_info file

# %%
# make the npoigages_info_df file here to match
npoigages_file = parent_dir / "npoigages_data/npoigages_info2.csv"
npoigages_info_df.to_csv(npoigages_file, index=False)

#
child_npoigages_list = list(npoigages_params_df["poi_gage_id"])
child_npoigages_info_df = npoigages_info_df[
    npoigages_info_df["poi_gage_id"].isin(child_npoigages_list)
]
child_npoigages_info_df.to_csv(child_pws_dir / "resource_gages.csv", index=False)

# %%
# gages_gf = list(set(poi_gdf.hl_link))
# gages_info = list(set(npoigages_info_df.poi_gage_id))
# gages_not_in_fabric = [x for x in gages_info if x not in gages_gf]

# df = npoigages_layer_gdf.loc[
#     npoigages_layer_gdf["poi_gage_id"].isin(gages_not_in_fabric)
# ]
# print(len(df))
# print(len(gages_not_in_fabric))
# df.to_csv(child_dir / "npoigages_data/gages_not_in_GF.csv", index=False)

# %% [markdown]
# ## Build the Child model

# %% [markdown]
# #### Transform the GF child geopackage into a pyPRMS geopackage
# This will allow for geopackage compatibility with NHM-assist notebooks.

# %%
from pathlib import Path
import shutil

child_model_gis_dir = child_pws_dir / "GIS"
child_model_gis_dir.mkdir(parents=True, exist_ok=True)

pyprms_proj = "ESRI:102039"

# %% [markdown]
# Mapping for parent nhm_id and nhm_seg_id to child hru_id and seg_id

# %%
# hru_mapping_series = pd.Series(nhm_id_temp.index, index=nhm_id_temp.values)
# hru_mapping_df = hru_mapping_series.reset_index()
# hru_mapping_df.columns = ["nhm_id", "hru_id"]  # rename as needed
# hru_mapping = hru_mapping_df.set_index("nhm_id")["hru_id"]

# seg_mapping_series = pd.Series(nhm_seg_temp.index, index=nhm_seg_temp.values)
# seg_mapping_df = seg_mapping_series.reset_index()
# seg_mapping_df.columns = ["nhm_seg_id", "segment_id"]  # rename as needed
# seg_mapping = seg_mapping_df.set_index("nhm_seg_id")["segment_id"]

# %%
# # nhru layer
# nhru_layer_gdf = hru_gdb.copy()
# nhru_layer_gdf.drop(
#     columns="nhm_seg_id", inplace=True
# )  # This was for the regional extraction from CONUS
# nhru_layer_gdf.rename(
#     columns={"hru_segment": "nhm_hru_seg", "hru_id": "nhm_id"}, inplace=True
# )
# nhru_layer_gdf["hru_segment"] = nhru_layer_gdf["nhm_hru_seg"].map(
#     seg_mapping
# )  # makes the OHM segment_id from parent and mapping
# nhru_layer_gdf["hru_segment"] = nhru_layer_gdf["hru_segment"].fillna(
#     0
# )  # HRU's with Nan flow directly to the ocean; 0 = Ocean
# nhru_layer_gdf.hru_segment = nhru_layer_gdf.hru_segment.astype(int)

# nhru_layer_gdf["hru_id"] = nhru_layer_gdf["nhm_id"].map(
#     hru_mapping
# )  # makes the OHM hru_id from parent and mapping
# # hru_child_gdf
# nhru_layer_gdf["model_hru_idx"] = nhru_layer_gdf["hru_id"]
# nhru_layer_gdf.to_file(
#     f"{child_model_gis_dir}/model_layers.gpkg",
#     layer="nhru",
#     driver="GPKG",
# )

# print(nhru_layer_df[~nhru_layer_df.geometry.is_valid])
# Check validity for each geometry
validity_series = hru_child_gdf.geometry.is_valid

# Check if ALL geometries are valid
all_valid = validity_series.all()
print("All nhru geometries valid?", all_valid)

# If some are invalid, print their hru_id values (and optionally why)
if not all_valid:
    bad_rows = hru_child_gdf.loc[~validity_series, ["hru_id", "geometry"]]
    print("Rows with invalid geometry (by hru_id):")
    print(bad_rows["hru_id"].tolist())

    # Optional: show validity reason for each bad geometry
    # bad_rows = bad_rows.assign(
    #     validity_reason=bad_rows["geometry"].apply(explain_validity)
    # )
    # print(bad_rows[["hru_id", "validity_reason"]])

hru_child_gdf.to_file(
    f"{child_model_gis_dir}/model_layers.gpkg",
    layer="nhru",
    driver="GPKG",
)

# Add the child model domain layer to the model GIS .gdpk
aoi_layer_df = aoi_gdb.copy().to_crs(pyprms_proj)
aoi_layer_df.to_file(
    f"{child_model_gis_dir}/model_layers.gpkg",
    layer="domain",
    driver="GPKG",
)

# %%
# Check validity for each geometry
validity_series = seg_child_gdf.geometry.is_valid

# Check if ALL geometries are valid
all_valid = validity_series.all()
print("All nsegment geometries valid?", all_valid)

# If some are invalid, print their hru_id values (and optionally why)
if not all_valid:
    bad_rows = seg_child_gdf.loc[~validity_series, ["segment_id", "geometry"]]
    print("Rows with invalid geometry (by segment_id):")
    print(bad_rows["segment_id"].tolist())

    # # Optional: show validity reason for each bad geometry
    # bad_rows = bad_rows.assign(
    #     validity_reason=bad_rows["geometry"].apply(explain_validity)
    # )
    # print(bad_rows[["segment_id", "validity_reason"]])

seg_child_gdf.to_file(
    f"{child_model_gis_dir}/model_layers.gpkg",
    layer="nsegment",
    driver="GPKG",
)

# %%
# Check validity for each geometry
validity_series = huc12pp_gdf_child.geometry.is_valid

# Check if ALL geometries are valid
all_valid = validity_series.all()
print("All huc12pp_gdf_child geometries valid?", all_valid)

# If some are invalid, print their hru_id values (and optionally why)
if not all_valid:
    bad_rows = huc12pp_gdf_child.loc[~validity_series, ["segment_id", "geometry"]]
    print("Rows with invalid geometry (by segment_id):")
    print(bad_rows["segment_id"].tolist())

    # # Optional: show validity reason for each bad geometry
    # bad_rows = bad_rows.assign(
    #     validity_reason=bad_rows["geometry"].apply(explain_validity)
    # )
    # print(bad_rows[["segment_id", "validity_reason"]])

huc12pp_gdf_child.to_file(
    f"{child_model_gis_dir}/model_layers.gpkg",
    layer="huc12_pp",
    driver="GPKG",
)

# %%
huc12pp_gdf_child

# %%
# npoigages layer
###### Merge and make layer for the child .gpkg
npoigages_layer_df = pd.merge(npoigages_params_df, npoigages_info_df, on="poi_gage_id")
npoigages_layer_gdf = gpd.GeoDataFrame(
    npoigages_layer_df,
    geometry=gpd.points_from_xy(
        npoigages_layer_df["longitude"], npoigages_layer_df["latitude"]
    ),
    crs="EPSG:4326",  # WGS84 lat/lon
).to_crs(seg_child_gdf.crs)

npoigages_layer_gdf.poi_gage_id = npoigages_layer_gdf.poi_gage_id.astype(str)
npoigages_layer_gdf.nhm_seg_id = npoigages_layer_gdf.nhm_seg_id.astype(int)
npoigages_layer_gdf.segment_id = npoigages_layer_gdf.segment_id.astype(int)

npoigages_layer_gdf.sort_values(by="nhm_seg_id", inplace=True)

# Check validity for each geometry
validity_series = npoigages_layer_gdf.geometry.is_valid

# Check if ALL geometries are valid
all_valid = validity_series.all()
print("All npoigage geometries valid?", all_valid)

# If some are invalid, print their hru_id values (and optionally why)
if not all_valid:
    bad_rows = npoigages_layer_gdf.loc[~validity_series, ["poi_gage_id", "geometry"]]
    print("Rows with invalid geometry (by poi_gage_id):")
    print(bad_rows["poi_gage_id"].tolist())

    # Optional: show validity reason for each bad geometry
    # bad_rows = bad_rows.assign(
    #     validity_reason=bad_rows["geometry"].apply(explain_validity)
    # )
    # print(bad_rows[["poi_gage_id", "validity_reason"]])

npoigages_layer_gdf.to_file(
    f"{child_model_gis_dir}/model_layers.gpkg",
    layer="npoigages",
    driver="GPKG",
)

# %%
# child_pws_dir
child_hf_dir

# %%
child_params_dir = child_hf_dir / "param_source_files"
child_params_dir.mkdir(parents=True, exist_ok=True)

# For now, move a copy of snarea_curve.csv into the param_source_files folder
sc_file_src = root_dir / "data_dependencies" / "snarea_curve.csv"
sc_file_dst = child_params_dir
shutil.copy2(sc_file_src, sc_file_dst)

child_pdb = Parameters(metadata=prms_meta, verbose=False)
child_pdb.control = ctl

# derive the new dimensions from the new shape files?
derived_dimensions = {
    "nhru": "nhm_id",
    "nsegment": "nhm_seg",
    "npoigages": "poi_type",
    "ndeplval": "snarea_curve",
}

for kk, vv in derived_dimensions.items():
    tmp_data = read_data(f"{child_params_dir}/{vv}.csv")
    child_pdb.dimensions.add(kk, size=len(tmp_data))

# Add the constant-size dimensions
# child_pdb.dimensions.add("ndays", size=366)
child_pdb.dimensions.add("nmonths", size=12)
child_pdb.dimensions.add("one", size=1)

# %%
# Make the list of child params to add to the child_pdb from the parent, excluding the params we have already made
# param_ignore_list = ['hru_id', 'segment_id', 'poi_type','poi_gage_id','poi_gage_segment']
param_ignore_list = []

# Get the list of parameter files to read
child_gf_files = []

file_it = glob.glob(f"{child_params_dir}/*.csv")
for kk in file_it:
    child_gf_files.append(kk)

child_gf_files.sort()

# Load the params we have already made
for cfile in child_gf_files:
    cname = os.path.basename(os.path.splitext(cfile)[0])
    # print(cname)

    try:
        child_pdb.add(cname)
    except ParameterNotValidError:
        con.print(f"[red]{cname}[/] is not a valid parameter... skipping")
        continue

    try:
        cdtype = NEW_PTYPE_TO_DTYPE[child_pdb.get(cname).meta["datatype"]]
        tmp_data = (
            pd.read_csv(cfile, skiprows=0, usecols=[1], dtype={1: cdtype})
            .squeeze("columns")
            .to_numpy()
        )

        try:
            child_pdb.get(cname).data = tmp_data
            param_ignore_list.append(cname)
        except IndexError:
            con.print(f"[red]{cname}[/] has incorrect size... skipping")
            child_pdb.remove(cname)
    except ValueError as err:
        con.print(f"[red]{cname}[/]: {err} - skipping")
        child_pdb.remove(cname)

# %%
# parent_pdb.get("temp_units").meta["dimensions"]
nhm_id_temp
hru_list = list(nhm_id_temp)
len(hru_list)

# %%
cname_list = [x for x in list(parent_pdb.keys()) if x not in param_ignore_list]

# Read in the list of hru_id from the parent.
# Note that the hru_list in the parent was change to nhm_id in the child .gpkg and we are returning to the source.
# We could use the values in the child. consider on revision

# Or, maybe we need to use the nhm_id.csv already made!
# hru_list = list(hru_gdb.hru_id)
hru_list = list(nhm_id_temp)


# Move these checks up in the NB, when we make the nhm_id and seg dim pars.
# # non-strict ascending (allows equal neighbors)
# is_sorted_asc = hru_list == sorted(hru_list)

# # strict ascending (every next value greater than previous)
# is_strict_asc = all(hru_list[i] < hru_list[i + 1] for i in range(len(hru_list) - 1))

# if (is_sorted_asc == True) and (is_strict_asc == True):
#     print("nhrus are in ascending order, and there are no duplicates.")
# if (is_sorted_asc == True) and (is_strict_asc == False):
#     print("nhrus are in ascending order, but duplicates are present. Please revise.")
# if is_sorted_asc == False:
#     print("nhrus are not in ascending order. This will create errors. Please revise.")
hru_idx_list = [x - 1 for x in hru_list]  # list/array of index labels


# segment_list = list(seg_gdb.segment_id)
segment_list = list(nhm_seg_temp)
seg_idx_list = [x - 1 for x in segment_list]

# list(parent_pdb.keys())

for cname in cname_list:
    # cname = os.path.basename(os.path.splitext(cfile)[0])
    child_pdb.remove(cname)  # remove when finished with test
    # print(cname)

    try:
        child_pdb.add(cname)
    except ParameterNotValidError:
        con.print(f"[red]{cname}[/] is not a valid parameter... skipping")
        continue

    try:
        cdtype = NEW_PTYPE_TO_DTYPE[child_pdb.get(cname).meta["datatype"]]

        ### New code
        _param_dims = parent_pdb.get(cname).meta["dimensions"]
        if _param_dims == ["nhru", "nmonths"]:
            parent_data = parent_pdb[cname].data
            child_data = parent_data[hru_idx_list, :]
        if _param_dims == ["nhru"]:
            parent_data = parent_pdb[cname].data
            child_data = parent_data[hru_idx_list]
        if _param_dims == ["nsegment"]:
            parent_data = parent_pdb[cname].data
            child_data = parent_data[seg_idx_list]
        if _param_dims == ["one"]:
            parent_data = parent_pdb[cname].data
            child_data = parent_data

        tmp_data = child_data
        # tmp_data = (
        #     pd.read_csv(cfile, skiprows=0, usecols=[1], dtype={1: cdtype})
        #     .squeeze("columns")
        #     .to_numpy()
        # )

        try:
            child_pdb.get(cname).data = tmp_data
        except IndexError:
            con.print(f"[red]{cname}[/] has incorrect size... skipping")
            child_pdb.remove(cname)
    except ValueError as err:
        con.print(f"[red]{cname}[/]: {err} - skipping")
        child_pdb.remove(cname)

# %%
# Special
special_list = ["hru_segment_nhm"]
for cname in special_list:
    # cname = os.path.basename(os.path.splitext(cfile)[0])
    child_pdb.remove(cname)  # remove when finished with test
    # print(cname)

    try:
        child_pdb.add(cname)
    except ParameterNotValidError:
        con.print(f"[red]{cname}[/] is not a valid parameter... skipping")
        continue

    try:
        cdtype = NEW_PTYPE_TO_DTYPE[child_pdb.get(cname).meta["datatype"]]

        ### New code
        _param_dims = ["nhru"]  # parent_pdb.get(cname).meta["dimensions"]
        # if _param_dims == ["nhru", "nmonths"]:
        #     parent_data = parent_pdb[cname].data
        #     child_data = parent_data[hru_idx_list, :]
        if _param_dims == ["nhru"]:
            parent_data = parent_pdb["hru_segment"].data
            child_data = parent_data[hru_idx_list]
        # if _param_dims == ["nsegment"]:
        #     parent_data = parent_pdb[cname].data
        #     child_data = parent_data[seg_idx_list]

        tmp_data = child_data
        # tmp_data = (
        #     pd.read_csv(cfile, skiprows=0, usecols=[1], dtype={1: cdtype})
        #     .squeeze("columns")
        #     .to_numpy()
        # )

        try:
            child_pdb.get(cname).data = tmp_data
        except IndexError:
            con.print(f"[red]{cname}[/] has incorrect size... skipping")
            child_pdb.remove(cname)
    except ValueError as err:
        con.print(f"[red]{cname}[/]: {err} - skipping")
        child_pdb.remove(cname)

# %%
parent_pdb.parameters.keys()

# %%
# Special
special_list = ["tosegment_nhm"]
for cname in special_list:
    # cname = os.path.basename(os.path.splitext(cfile)[0])
    child_pdb.remove(cname)  # remove when finished with test
    # print(cname)

    try:
        child_pdb.add(cname)
    except ParameterNotValidError:
        con.print(f"[red]{cname}[/] is not a valid parameter... skipping")
        continue

    try:
        cdtype = NEW_PTYPE_TO_DTYPE[child_pdb.get(cname).meta["datatype"]]

        ### New code
        _param_dims = ["nsegment"]
        if _param_dims == ["nsegment"]:
            parent_data = parent_pdb["tosegment"].data
            child_data = parent_data[seg_idx_list]
        # Build a check the compares the _nhm pars from par file to those in gis
        tmp_data = child_data
        # tmp_data = (
        #     pd.read_csv(cfile, skiprows=0, usecols=[1], dtype={1: cdtype})
        #     .squeeze("columns")
        #     .to_numpy()
        # )

        try:
            child_pdb.get(cname).data = tmp_data
        except IndexError:
            con.print(f"[red]{cname}[/] has incorrect size... skipping")
            child_pdb.remove(cname)
    except ValueError as err:
        con.print(f"[red]{cname}[/]: {err} - skipping")
        child_pdb.remove(cname)

# %%
orig_data = child_pdb["hru_segment"].data
od_df = pd.DataFrame(orig_data)
od_df.index = range(1, len(od_df) + 1)
od_df.reset_index(inplace=True, drop=False)
od_df.rename(columns={"index": "hru_id", 0: "parent_hru_segment"}, inplace=True)

od_df["hru_segment"] = od_df["parent_hru_segment"].map(seg_mapping)
od_df.loc[od_df["parent_hru_segment"] == 0, "hru_segment"] = 0
od_df.loc[od_df["hru_segment"].isna(), "hru_segment"] = 0
od_df["hru_segment"] = od_df["hru_segment"].astype(int)
new_data = od_df["hru_segment"].values
child_pdb.get("hru_segment").data = new_data

# %%
orig_data = child_pdb["tosegment"].data
od_df = pd.DataFrame(orig_data)
od_df.index = range(1, len(od_df) + 1)
od_df.reset_index(inplace=True, drop=False)
od_df.rename(columns={"index": "segment_id", 0: "parent_tosegment"}, inplace=True)

od_df["tosegment"] = od_df["parent_tosegment"].map(seg_mapping)
od_df.loc[od_df["parent_tosegment"] == 0, "tosegment"] = 0
od_df.loc[od_df["tosegment"].isna(), "tosegment"] = 0
od_df["tosegment"] = od_df["tosegment"].astype(int)
new_data = od_df["tosegment"].values
child_pdb.get("tosegment").data = new_data

# %%
od_df

# %%
child_pdb.parameters.keys()

# %%
# Build the stream network
dag_ds = child_pdb.stream_network(tosegment="tosegment_nhm")  # , seg_id="segment_id")

# %%
dag_ds

# %%
import networkx as nx
import pydot

G = dag_ds
# G.add_edges_from([(1, 2), (2, 3), (3, 1)])

P = nx.nx_pydot.to_pydot(G)
# Let Graphviz fit the drawing within a generous size (in inches)
P.set_size("0,0")  # 0,0 = no explicit max size; natural size used [web:132]
P.set_page("")  # no page tiling [web:140]
P.set_ratio("compress")  # optional: tighter packing if you did set a size [web:135]

P.write_pdf(f"{child_pws_dir}/digraph.pdf")

# %%
child_pdb.write_parameter_file(
    f"{child_pws_dir}/myparam.param",
    header=["GFv2 derived"],
)
# child_pdb.write_parameter_file(
#     f"{child_dir}/"pywatershed_model_files/myparam.param",
#     header=["GFv2 derived OHM domain"],
# )

# %%
# For now, move a copy of the contro file into the model folder folder
control_file_src = root_dir / "data_dependencies" / "control.default.bandit"
control_file_dst = child_pws_dir
shutil.copy2(control_file_src, control_file_dst)

# %%
