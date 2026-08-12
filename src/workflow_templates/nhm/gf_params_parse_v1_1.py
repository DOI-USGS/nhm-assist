# ---
# jupyter:
#   jupytext:
#     formats: notebooks///ipynb,src/workflow_templates/nhm///py:percent
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
# Find the repo root via the editable-installed `assist` package â€” robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]

# from assist.nhf.sf_data_retrieval_v2_1 import fetch_single_nwis_gage
from assist.nhf.sf_data_retrieval_v2_1 import fetch_daily_discharge_batch
from assist.nhf.nhm_assist_utilities_v2 import find_missing_gage_info


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


# %% [markdown]
# ### Introduction
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
parent_dir = root_dir / "data_dependencies" / "NHM_v1_1" / "version1_1_params"

# %% [markdown]
# The directory for all the paramerter .csv files:

# %%
pfile_name = "paramdb_v1.1_gridmet_CONUS-master"
parent_params_dir = f"{parent_dir}/{pfile_name}"

# %% [markdown]
# Get the list of parameter names from the .csv paramter files

# %%
gf_files = []
file_it = glob.glob(f"{parent_params_dir}/*.csv")
for kk in file_it:
    gf_files.append(kk)
gf_files.sort()

# %%
parent_dir

# %% [markdown]
# ### Read in the pywatershed control file.
# The control file used for the parent pywatershed model is somewhat universal and not model dependent

# %%
default_ctl_filename = root_dir / f"data_dependencies/NHM_v1_1/control.default.bandit"
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
child_name = "WWGW_Basin"  # Powder_River, John_Day_River

hydrofabric_dir = root_dir / "hydrofabric_domain_data"

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
hru_gdb.columns

# %%
nhm_id_temp = hru_gdb.nhru_v1_1.astype(int)
nhm_id_temp = nhm_id_temp.sort_values()
nhm_id_temp.index = range(1, len(nhm_id_temp) + 1)  # Change index from 0-n, to 1-n

with open(param_source_files_dir / "nhm_id.csv", "w", newline="") as f:
    f.write("$id,nhm_id\n")
    nhm_id_temp.to_csv(f, index=True, header=False)

# %% [markdown]
# #### Create the nhm_seg.csv from the GIS subset domain
# The nhm_seg.csv file contains the parent, or global, segment_id for each hru in the child domain, indexed from 1 to n. The index of the file is essentially the segment_id for each hru in the child domain. This file is key for connecting the child segment to the parent parameter database and for dispaying model parameters and output using the .gpkg in NHM-assist. It is strongly recommended that when creating the child .gpkg, that the nhm_seg be indexed in ascending order.

# %%
seg_gdb.columns

# %% [markdown]
# #### Create the poi_type.csv and all the npoigage dimensioned parameter .csv files
# These parameters are highly tailored for specific model application. In this section, a subset of pois associated with streamflow gages from the GFv2 are selected for the child domain and are filtered to include gages that have at least one year of daily discharge data. Note: this gage list is meant to be a starting point and often, and likely, incomplete for the domain. NHM-assist offers workflows that can be used to evaluate other gages in the domain and add gages to the paramter file if needed.

# %%
nhm_seg_temp = seg_gdb.nsegment_v1_1.astype(int)
nhm_seg_temp = nhm_seg_temp.sort_values()  # Sorting may be causing errors
nhm_seg_temp.index = range(1, len(nhm_seg_temp) + 1)

with open(param_source_files_dir / "nhm_seg.csv", "w", newline="") as f:
    f.write("$id,nhm_seg\n")
    nhm_seg_temp.to_csv(f, index=True, header=False)

# %%
poi_gdb.columns

# %%
poi_gdf_child = poi_gdb.copy()
# child_npoi_gdf = child_npoi_gdf.loc[~child_npoi_gdf["segment_id"].isna()]
poi_gdf_child = poi_gdf_child.loc[poi_gdf_child["Type_Gage"] != "0"]


poi_gdf_child["Type_Gage"] = poi_gdf_child["Type_Gage"].astype(
    str
)  # or 'int' / 'Int64'
# Put a drop rows with ["segment_id"] na

# %% [markdown]
# #### Create a (gage) poi dataframe to build needed poi params for the pywatershed model (child)
# This merge links the metadata for each poi to the segment_id and geometery from the child .gpkg using the `merge_id`.Merge geometry and segment_id from .gpkg npoi_layer with poi metadata table

# %% [markdown]
# Now create a mapping series to find the child segment_id (child) associated with the nhm_seg (parent) and add the segment_id to the dataframe.

# %%
seg_mapping_series = pd.Series(nhm_seg_temp.index, index=nhm_seg_temp.values)
seg_mapping_df = seg_mapping_series.reset_index()
seg_mapping_df.columns = ["poi_segment_v1_1", "segment_id"]  # rename as needed
seg_mapping = seg_mapping_df.set_index("poi_segment_v1_1")["segment_id"]

poi_gdf_child["segment_id"] = poi_gdf_child["poi_segment_v1_1"].map(seg_mapping)

# %% [markdown]
# Check if a gage was included in the poi dateframe (poi_gdf_child) that had no segment mapped to it. This would happen if the pois selected in the child domain fell on segments not included in the child segment domain.

# %%
poi_gdf_child

# %% [markdown]
# #### Remove poi's that have no flow data for period 1979-10-01 to 2025-09-30 and populated site information
# Update with Luca's fix when is done. On second thought, maybe we don't need to do this here. When we run notebook 1, it should sow if the gages have less than a length of record speified in notebook 0.

# %%
# result_1 = fetch_daily_discharge_batch(
#     monitoring_location_ids=list(poi_gdf_child.Type_Gage),
#     start_date="1979-10-01",
#     end_date="2025-09-30",
# )
# gage_poi_flow_list = [
#     x for x in list(poi_gdf_child.Type_Gage) if x not in result_1.missing_ids
# ]

# %% [markdown]
# #### Now, some reshaping an cleaning of the gage poi information prior to parameter csv file creation
# This involves reshaping the dataframe to these column names:
# 'poi_gage_id', 'poi_gage_segment', 'poi_type'

# %%
# Create npoigages_params_df (used to make params)
npoigages_params_gdf = poi_gdf_child.copy()
npoigages_params_gdf["poi_type"] = 1
npoigages_params_df = npoigages_params_gdf[
    ["Type_Gage", "segment_id", "poi_segment_v1_1", "poi_type"]
]
npoigages_params_df.rename(columns={"Type_Gage": "poi_gage_id"}, inplace=True)
npoigages_params_df = npoigages_params_df.sort_values("poi_gage_id")

# %%
# Create npoigages_info_df and .csv file
npoigages_data_dir = parent_dir / "npoigages_data"
npoigages_data_dir.mkdir(parents=True, exist_ok=True)

npoigages_info_df = find_missing_gage_info(
    root_dir,
    child_pws_dir,
    list(npoigages_params_df.poi_gage_id),
    parent_dir / "npoigages_data/resource_gages.csv",
)

# %%
# Add all gages in the domain to the info file to be used in all visualization notebooks.

# %%
# make the npoigages_info_df file in the child hf domain folser as well for backup
npoigages_file = child_hf_dir / "resource_gages.csv"
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
nhm_id_temp

# %%
# new HRUs
hru_mapping_series = pd.Series(nhm_id_temp.index, index=nhm_id_temp.values)
hru_mapping_df = hru_mapping_series.reset_index()
hru_mapping_df.columns = ["nhm_id", "hru_id"]  # rename as needed
hru_mapping = hru_mapping_df.set_index("nhm_id")["hru_id"]

# %%
hru_gdb.columns

# %%
hru_child_gdf = hru_gdb.copy()

# Change to column names to match child poigages gdf

# hru_child_gdf.drop(columns="nhm_hru_seg", inplace=True)  # Junk from national coverage
hru_child_gdf.drop(columns="nhm_id", inplace=True)  # Junk from national coverage

hru_child_gdf.rename(
    columns={"hru_segment_v1_1": "nhm_hru_seg", "nhru_v1_1": "nhm_id"}, inplace=True
)
hru_child_gdf["hru_id"] = hru_child_gdf["nhm_id"].map(hru_mapping)

hru_child_gdf["hru_segment"] = hru_child_gdf["nhm_hru_seg"].map(seg_mapping)
hru_child_gdf["hru_segment"] = hru_child_gdf["hru_segment"].fillna(
    0
)  # HRU's with Nan flow directly to the ocean; 0 = Ocean
hru_child_gdf.hru_segment = hru_child_gdf.hru_segment.astype(int)
hru_child_gdf

# %%
seg_gdb.columns

# %%
# print(
#     "Of the",
#     len(list(poi_gdf_child.Type_Gage)),
#     "'type_gage' pois in the GF, only",
#     len(gage_poi_flow_list),
#     "have discharge data in NWIS for the simulation period, and will be included in the parameter file.",
# )
# poi_gdf3 = poi_gdf_child.loc[poi_gdf_child["Type_Gage"].isin(gage_poi_flow_list)]
# print(
#     "Only the",
#     len(gage_poi_flow_list),
#     "poigages that have flow will be included in the parameter file.",
#     "If other gages are needed, refer to the following section.",
# )

# %%
# Change to column names to match child poigages gdf
seg_child_gdf = seg_gdb.copy()
seg_child_gdf.drop(columns="seg_id_nhm", inplace=True)  # vestigial ids
# seg_child_gdf.drop(columns="tosegment_v1_1", inplace=True)  # vestigial ids

seg_child_gdf.rename(
    columns={"nsegment_v1_1": "nhm_seg", "tosegment_v1_1": "to_nhm_seg"},
    inplace=True,
)

seg_child_gdf["segment_id"] = seg_child_gdf["nhm_seg"].map(seg_mapping)
seg_child_gdf["to_segment"] = seg_child_gdf["to_nhm_seg"].map(seg_mapping)
seg_child_gdf["to_segment"] = seg_child_gdf["to_segment"].fillna(
    0
)  # to_segments may not be in the model domain; 0 = Ocean
seg_child_gdf.to_segment = seg_child_gdf.to_segment.astype(int)
seg_child_gdf

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

# %%
npoigages_info_df

# %% [markdown]
# #### Write npoigages parameter files (.csv)

# %%
npoigages_params_df.columns

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
# npoigages_file = parent_dir / "npoigages_data/npoigages_info2.csv"
# npoigages_info_df.to_csv(npoigages_file, index=False)

#
child_npoigages_list = list(npoigages_params_df["poi_gage_id"])
child_npoigages_info_df = npoigages_info_df[
    npoigages_info_df["poi_gage_id"].isin(child_npoigages_list)
]
child_model_meta_dir = child_pws_dir / "metadata"
child_model_meta_dir.mkdir(parents=True, exist_ok=True)
child_npoigages_info_df.to_csv(child_model_meta_dir / "resource_gages.csv", index=False)
child_npoigages_info_df.to_csv(child_hf_dir / "resource_gages.csv", index=False)

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

# %%
hru_child_gdf.columns

# %% [markdown]
# Mapping for parent nhm_id and nhm_seg to child hru_id and seg_id

# %%
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
seg_child_gdf.columns

# %%
# Check validity for each geometry
# Change the name of the atttribut to make compatible with version 2.0 hydrofabric name.

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
npoigages_info_df.columns

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

npoigages_layer_gdf["nhm_seg"] = np.nan
npoigages_layer_gdf.poi_gage_id = npoigages_layer_gdf.poi_gage_id.astype(str)
npoigages_layer_gdf.nhm_seg = npoigages_layer_gdf.poi_segment_v1_1.astype(int)
npoigages_layer_gdf.drop(columns=["poi_segment_v1_1"], inplace=True)
npoigages_layer_gdf.segment_id = npoigages_layer_gdf.segment_id.astype(int)

npoigages_layer_gdf.sort_values(by="nhm_seg", inplace=True)

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
child_params_dir = child_hf_dir / "param_source_files"
child_params_dir.mkdir(parents=True, exist_ok=True)

# For now, move a copy of snarea_curve.csv into the param_source_files folder
sc_file_src = f"{parent_params_dir}/snarea_curve.csv"
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
control_file_src = (
    root_dir / "data_dependencies" / "NHM_v1_1" / "control.default.bandit"
)
control_file_dst = child_pws_dir
shutil.copy2(control_file_src, control_file_dst)

# %%
