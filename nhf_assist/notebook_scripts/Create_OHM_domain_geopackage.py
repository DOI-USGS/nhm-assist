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
import glob
import os
import pydot
import networkx as nx
from pathlib import Path
import pathlib as pl

import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import geopandas as gpd
import fiona

from rich.console import Console
from rich.progress import track

from rich import pretty

pretty.install()

import jupyter_black

jupyter_black.load()

# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))

# %%
# Functions
from shapely.geometry import Polygon, MultiPolygon


def remove_holes(geom):
    if geom is None or geom.is_empty:
        return geom

    # MultiPolygon: process each part
    if isinstance(geom, MultiPolygon):
        return MultiPolygon([Polygon(p.exterior) for p in geom.geoms])

    # Single Polygon
    if isinstance(geom, Polygon):
        return Polygon(geom.exterior)

    # Other geometry types unchanged
    return geom


# %% [markdown]
# ### Introduction
# This notebook will use the nhru layer (with an added basin_id attribute) from a parent domain of the National Hydrologic Geospatial Fabric version 2 (NHGF_v2) to create a model domain. IN this example, values were added for each hru in the parent domain for "basin_id" to identify hrus associated with each administrative basin for the state of Oregon and create child domains from the NHGF_v2. 

# %% [markdown]
# Path to a shape file that is a copy of the parent domain hrus with an added subdomain attribute, in this example, "basin_id". 

# %%
child_model_nhrus_path = (
    root_dir
    / "nhf_assist/make_pws_model/domain_data/OHM_2026_02_21/GIS/child_models.shp"
)
gdf_child_models = gpd.read_file(child_model_nhrus_path)

# %%
gdf_child_models.columns

# %%
print("nhru:", len(gdf_child_models.hru_id))
print("nsegment:", len(gdf_child_models.hru_segmen.unique().tolist()))
print("max:", gdf_child_models.hru_segmen.max())

auto_list = gdf_child_models.nhm_seg_id.unique().tolist()
auto_list[0:5]

# %% [markdown]
# List has 5 less segments than the one we gave Andy, so check for missing segments.

# %%
manual_gpkg_path = (
    root_dir
    / "nhf_assist/make_pws_model/domain_data/OHM_2026_02_21/GIS/model_layers.gpkg"
)
manual_layers = fiona.listlayers(manual_gpkg_path)
# manual_layers
manual_seg_gdf = gpd.read_file(manual_gpkg_path, layer="nsegment")
manual_hru_gdf = gpd.read_file(manual_gpkg_path, layer="nhru")

# %%
manual_hru_gdf.columns

# %%
print("nsegment from nhrus", len(manual_hru_gdf.nhm_hru_seg.unique().tolist()))
from_nhru_manual_list = manual_hru_gdf.nhm_hru_seg.unique().tolist()
print("nseg:", len(from_nhru_manual_list), manual_hru_gdf.nhm_hru_seg.max())
manual_list[0:5]

# %%
print("nsegment from nsegment:", len(manual_seg_gdf.nhm_seg_id.unique().tolist()))
from_nseg_manual_list = manual_seg_gdf.nhm_seg_id.unique().tolist()
print("nseg:", len(from_nseg_manual_list), manual_seg_gdf.nhm_seg_id.max())
manual_list[0:5]

# %%
result = [x for x in from_nseg_manual_list if x not in from_nhru_manual_list]
print(len(result))

# %%
print(result)

# %% [markdown]
# [12343, columbia segment with no HRUs; user added
# 13033, same; user added
# 14380, fabric error;no hrus were descritzed for this segment
# 15398, columbia; user added
# 15901, fabric error;very small seg; no hrus were descritzed for this segment
# 15902, fabric error;very small seg; no hrus were descritzed for this segment
# 16654, columbia; user added
# 16666, columbia; user added
# 17989, fabric error; headwater segment upstream fragment; no hrus for this segment
# 20267, Klamath added outflow seg; user added

# %%
result = [x for x in from_nhru_manual_list if x not in from_nseg_manual_list]
print(len(result))
print(result)

# %% [markdown]
# 4595, Snake river segment and is missing from the model that we gave Andy:change to seg to fix
# 4602, Small HRU in model domain associated with snake river outside domain; hru could be dropped; change to seg to fix
# 13069, Small HRU in model domain associated with snake river outside domain; hru could be dropped;change to seg to fix
# 13596, Columbia river segment and is missing from the model that we gave Andy; change to seg to fix
# 0

# %% [markdown]
# Make domain polygon for each basin_id

# %%
basin_polygons = gdf_child_models.dissolve(by="basin_id")
basin_polygons = basin_polygons.reset_index()
basin_polygons = basin_polygons[
    [
        "basin_id",
        "geometry",
    ]
]
basin_polygons["geometry"] = basin_polygons["geometry"].apply(remove_holes)
# basin_polygons.crs

# %% [markdown]
# The child domain is then used to select hrus, segments and pois from the parent fabric and create a child fabric for each child domain. The child fabric will be used in the next notebook to create a pywatershed mode for the child domain.

# %%
basin_polygons.explore(column="basin_id")  # opens in a browser or Jupyter

# %% [markdown]
# ### Write each child domain as a layer in a geopackage

# %% [markdown]
# Write the child domains as a layer in a new geopackage in the source folder. For the time being, we will write this to the source, the (new) parent nhgf GIS folder.

# %%
# path to your GeoPackage
basin_gpkg = (
    root_dir
    / "NHGF_v2/NHGF_v2_pws_model/domain_data/OHM_2026_02_21/GIS/child_domains.gpkg"
)

# make sure basin_id is a column
if basin_polygons.index.name == "basin_id" and "basin_id" not in basin_polygons.columns:
    basin_polygons = basin_polygons.reset_index()

for _, row in basin_polygons.iterrows():
    basin_id = row["basin_id"]
    layer_name = basin_id
    gdf_one = gpd.GeoDataFrame([row], crs=basin_polygons.crs)
    gdf_one.to_file(basin_gpkg, layer=layer_name, driver="GPKG")

# %% [markdown]
# ### Create child domains for each basin_id

# %%
# make sure basin_id is a column
if basin_polygons.index.name == "basin_id" and "basin_id" not in basin_polygons.columns:
    basin_polygons = basin_polygons.reset_index()

for _, row in basin_polygons.iterrows():
    layer_name = row["basin_id"]
    gdf_one = gpd.GeoDataFrame([row], crs=basin_polygons.crs)

    # Make a new domain directory for each child
    child_dir = root_dir / f"NHGF_v2/NHGF_v2_pws_model/domain_data/{layer_name}"
    child_dir.mkdir(parents=True, exist_ok=True)
    child_gis_dir = child_dir / "GIS"
    child_gis_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = child_gis_dir / "child_nhgf_v2_domain.gpkg"

    gdf_one.to_file(gpkg_path, layer=layer_name, driver="GPKG")

# %% [markdown]
# Now, read the child_domain.gpkg (each subbasin is a layer), and the parent NHGF_v2 (source fabric). This is nessessary step. Depending on the subbasin geometery, segments that form child domain boundaries may not be included in the child nhgf_v2 domains. If this happend, these can be manually corrected (added) in the geopackages and then the corrected versions are read in below. (Eddie and Matt -- add overwrite protection)

# %%
# 1) GeoPackage with one layer per basin
basin_gpkg = (
    root_dir
    / "NHGF_v2/NHGF_v2_pws_model/domain_data/OHM_2026_02_21/GIS/child_domains.gpkg"
)

# 2) GeoPackage whose layers you want to subset
source_gpkg = (
    root_dir
    / "NHGF_v2/NHGF_v2_pws_model/domain_data/OHM_2026_02_21/GIS/model_layers.gpkg"
)

# %%
source_layers = fiona.listlayers(source_gpkg)
source_layers

# %%
# list layers
basin_layers = fiona.listlayers(basin_gpkg)

# source_layers = fiona.listlayers(source_gpkg)
source_layers = [
    "npoigages",
    "nhru",
    "nsegment",
]  # only the layers we need from the parent


for basin_layer in basin_layers:
    basin_gdf = gpd.read_file(basin_gpkg, layer=basin_layer)
    basin_geom = basin_gdf.geometry.unary_union

    basin_id = basin_layer

    # output GeoPackage for this basin
    out_gpkg = (
        root_dir
        / f"NHGF_v2/NHGF_v2_pws_model/domain_data/{basin_id}/GIS/child_nhgf_v2_domain.gpkg"
    )
    basin_gdf.to_file(
        out_gpkg, layer=f"domain", driver="GPKG"
    )  # save the domain outline as a layer

    # now make a child layer from each parent layer
    for src_layer in source_layers:
        src_gdf = gpd.read_file(source_gpkg, layer=src_layer)

        # match CRS
        if src_gdf.crs != basin_gdf.crs:
            src_gdf = src_gdf.to_crs(basin_gdf.crs)

        if src_layer == "nsegment":
            # spatial selection: intersecting features
            sel = src_gdf[src_gdf.geometry.intersects(basin_geom)]
        else:
            # centroid-based selection: centroid is within basin
            centroids = src_gdf.geometry.centroid
            mask = centroids.within(basin_geom)
            sel = src_gdf[mask]

        if sel.empty:
            continue

        # write selection as a layer with same name
        sel.to_file(out_gpkg, layer=src_layer, driver="GPKG")

# %% [markdown]
# ### View and inspect a child domain geopackage
#

# %%
# List of model names
domains_dir = Path(root_dir / f"NHGF_v2/NHGF_v2_pws_model/domain_data")

folders = [p for p in domains_dir.iterdir() if p.is_dir()]

for folder in folders:
    print(folder.name)  # just the folder name, not full path

# %%
child_model_name = "Rogue_River"  # "Malheur_Lake"

child_model_path = [f for f in folders if child_model_name in f.name]
print(child_model_path[0])
child_model_gdf = gpd.read_file(
    child_model_path[0] / "GIS/child_nhgf_v2_domain.gpkg", layer="nhru"
)

# %%
import folium

gpkg_path = child_model_path[0] / "GIS/child_nhgf_v2_domain.gpkg"
layer_name = "nhru"

gdf = gpd.read_file(gpkg_path, layer=layer_name)

# list all layer names in the GeoPackage
# layers = fiona.listlayers(gpkg_path)
layers = ["nsegment", "domain", "npoigages"]

layer_styles = {
    "nhru": dict(color="gray", fill=True, fillOpacity=0.3),
    "nsegment": dict(color="blue", weight=1),
    "domain": dict(color="black", fill=False, weight=2),
    "npoi": dict(color="yellow", fill=True, fillOpacity=1),
    # default for anything not listed
}

style = layer_styles.get(layer_name, dict(color="gray", fill=False))

m = child_model_gdf.explore(name=layer_name, style_kwds=style, tooltip=False)


for layer_name in layers:
    gdf = gpd.read_file(gpkg_path, layer=layer_name)

    style = layer_styles.get(layer_name, dict(color="gray", fill=False))

    # add each as a new layer; tweak style as needed
    m = gdf.explore(
        m=m,
        name=layer_name,
        style_kwds=style,
        # tooltip=False,
    )

# add layer control so you can toggle them
folium.LayerControl().add_to(m)

m  # display in Jupyter

# %%
