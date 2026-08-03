# ---
# jupyter:
#   jupytext:
#     formats: nhf_assist/notebooks//ipynb,src/workflow_templates/nhf//py:percent
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
# This notebook will use the nhru layer (with an added basin_id attribute) from a National Hydrofabric version 2 (nhf) parent domain .gpkg to create a child domain .gpkg. The child domain .gpkg will be used to build a pws model for the child domain in the following notebook. In this example, values were added for each hru in the parent domain for "basin_id" to identify hrus associated with each administrative basin for the state of Oregon and create hydrofabric .gpkg for each child domain. 

# %% [markdown]
# Path to a shape file that is a copy of the parent domain hrus with an added subdomain attribute, in this example, "basin_id". 

# %%
child_model_nhrus_path = (
    root_dir / "nhf_assist/hydrofabric_domain_data/OHM_2026_02_21/GIS/child_models.shp"
)
gdf_child_models = gpd.read_file(child_model_nhrus_path)

# %%
gdf_child_models

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
# Write the child domains as a layer in a new geopackage in the source folder. For the time being, we will write this to the source, the parent nhgf GIS folder.

# %%
# path to your GeoPackage
basin_gpkg = (
    root_dir
    / "nhf_assist/hydrofabric_domain_data/OHM_2026_02_21/GIS/child_domains.gpkg"
)

# make sure basin_id is a column
if basin_polygons.index.name == "basin_id" and "basin_id" not in basin_polygons.columns:
    basin_polygons = basin_polygons.reset_index()

for _, row in basin_polygons.iterrows():

    basin_id = row["basin_id"]
    print(basin_id)
    layer_name = basin_id
    gdf_one = gpd.GeoDataFrame([row], crs=basin_polygons.crs)
    gdf_one.to_file(basin_gpkg, layer=layer_name, driver="GPKG")

# %% [markdown]
# ### The follwing code creates a child hf .gpkg for each child and adds the domain layer to each child .gpkg

# %%
# make sure basin_id is a column
if basin_polygons.index.name == "basin_id" and "basin_id" not in basin_polygons.columns:
    basin_polygons = basin_polygons.reset_index()

for _, row in basin_polygons.iterrows():
    layer_name = row["basin_id"]
    gdf_one = gpd.GeoDataFrame([row], crs=basin_polygons.crs)

    # Make a new domain directory for each child
    child_dir = root_dir / f"nhf_assist/hydrofabric_domain_data/{layer_name}"
    child_dir.mkdir(parents=True, exist_ok=True)
    child_gis_dir = child_dir / "GIS"
    child_gis_dir.mkdir(parents=True, exist_ok=True)
    gpkg_path = child_gis_dir / "child_nhf_domain.gpkg"

    gdf_one.to_file(gpkg_path, layer=layer_name, driver="GPKG")

# %% [markdown]
# Now, read the child_domain.gpkg (each subbasin is a layer), and the parent NHGF_v2 (source fabric). This is nessessary step. Depending on the subbasin geometery, segments that form child domain boundaries may not be included in the child nhgf_v2 domains. If this happend, these can be manually corrected (added) in the geopackages and then the corrected versions are read in below. (Eddie and Matt -- add overwrite protection)

# %%
# 1) GeoPackage with one layer per basin
basin_gpkg = (
    root_dir
    / "nhf_assist/hydrofabric_domain_data/OHM_2026_02_21/GIS/child_domains.gpkg"
)

# 2) GeoPackage whose layers you want to subset
source_gpkg = (
    root_dir / "nhf_assist/hydrofabric_domain_data/OHM_2026_02_21/GIS/model_layers.gpkg"
)

# %%
source_layers = fiona.listlayers(source_gpkg)
source_layers

# %% jupyter={"source_hidden": true}
# list layers
basin_layers = fiona.listlayers(basin_gpkg)
print(basin_layers)

# source_layers = fiona.listlayers(source_gpkg)
source_layers = [
    "npoi",
    "nhru",
    "nsegment",
]  # only the layers we need from the parent


for basin_layer in basin_layers:
    print(basin_layer)
    basin_gdf = gpd.read_file(basin_gpkg, layer=basin_layer)
    basin_geom = basin_gdf.geometry.unary_union

    basin_id = basin_layer

    # output GeoPackage for this basin
    out_gpkg = (
        root_dir
        / f"nhf_assist/hydrofabric_domain_data/{basin_id}/GIS/child_nhf_domain.gpkg"
    )
    basin_gdf.to_file(
        out_gpkg, layer=f"domain", driver="GPKG"
    )  # save the domain outline as a layer

    child_hru_segments = set()  # populated when nhru is processed

    # now make a child layer from each parent layer
    for src_layer in source_layers:
        src_gdf = gpd.read_file(source_gpkg, layer=src_layer)

        # match CRS
        if src_gdf.crs != basin_gdf.crs:
            src_gdf = src_gdf.to_crs(basin_gdf.crs)

        if src_layer == "nhru":
            # centroid-based selection: centroid is within basin
            centroids = src_gdf.geometry.centroid
            mask = centroids.within(basin_geom)
            sel = src_gdf[mask].copy()

            # Filter out edge-case HRUs whose centroid is inside but polygon
            # is mostly outside. Require >= 50% of HRU area within the domain.
            overlap_area = sel.geometry.intersection(basin_geom).area
            hru_area = sel.geometry.area
            overlap_frac = overlap_area / hru_area
            edge_hrus = sel[overlap_frac < 0.5]
            if len(edge_hrus) > 0:
                print(
                    f"  Removed {len(edge_hrus)} edge HRUs with <50% overlap: "
                    f"hru_id={edge_hrus['hru_id'].tolist()}"
                )
            sel = sel[overlap_frac >= 0.5]

            # Save selected HRU segment indices for segment selection below
            child_hru_segments = set(sel["hru_segment"].unique())

        elif src_layer == "nsegment":
            # Method 1 (attribute-based): Select segments that child HRUs drain to.
            sel_by_hru = src_gdf[src_gdf["model_seg_idx"].isin(child_hru_segments)]

            # Also include segments that are contained within the domain AND are a
            # downstream receiver (to_segment) of the hru_segment set.
            # This captures outlet/pass-through segments that have no local HRUs
            # but are routed to by segments in the child domain.
            hru_seg_to_segments = set(sel_by_hru["to_segment"]) - {0}
            sel_within = src_gdf[src_gdf.geometry.within(basin_geom)]
            within_seg_ids = set(sel_within["model_seg_idx"])

            # Segments within the domain that are downstream receivers of child segments
            downstream_keepers = within_seg_ids & hru_seg_to_segments
            # Combine: hru_segment segments + downstream receivers within domain
            final_seg_ids = child_hru_segments | downstream_keepers

            sel = src_gdf[src_gdf["model_seg_idx"].isin(final_seg_ids)]

            # Report differences for debugging
            only_in_within = within_seg_ids - final_seg_ids
            only_in_final = final_seg_ids - within_seg_ids

            print(
                f"  Segments selected: {len(final_seg_ids)} "
                f"(hru_segment: {len(child_hru_segments)}, "
                f"+ downstream keepers: {len(downstream_keepers)})"
            )
            if only_in_within:
                print(
                    f"    Excluded from within (no HRU, not a to_segment): {sorted(only_in_within)}"
                )
            if only_in_final:
                print(f"    In final but not in intersect: {sorted(only_in_final)}")

        else:
            # spatial selection: intersecting features (npoi, etc.)
            sel = src_gdf[src_gdf.geometry.intersects(basin_geom)]

        if sel.empty:
            continue

        # write selection as a layer with same name
        sel.to_file(out_gpkg, layer=src_layer, driver="GPKG")

# %% [markdown]
# ### View and inspect a child domain geopackage
#

# %%
# List of model names
domains_dir = Path(root_dir / f"nhf_assist/hydrofabric_domain_data")

folders = [p for p in domains_dir.iterdir() if p.is_dir()]

for folder in folders:
    print(folder.name)  # just the folder name, not full path

# %%
child_model_name = "UpperWillamette"  # "Rogue_River"  #

child_model_path = [f for f in folders if child_model_name in f.name]
print(child_model_path[0])
child_model_gdf = gpd.read_file(
    child_model_path[0] / "GIS/child_nhf_domain.gpkg", layer="nhru"
)

# %% jupyter={"source_hidden": true}
import folium

gpkg_path = child_model_path[0] / "GIS/child_nhf_domain.gpkg"
layer_name = "nhru"

gdf = gpd.read_file(gpkg_path, layer=layer_name)

# list all layer names in the GeoPackage
# layers = fiona.listlayers(gpkg_path)
layers = ["nsegment", "domain", "npoi"]

layer_styles = {
    "nhru": dict(color="gray", fill=True, fillOpacity=0.3),
    "nsegment": dict(color="blue", weight=1),
    "domain": dict(color="black", fill=False, weight=2),
    "npoi": dict(color="yellow", fill=True, fillOpacity=1),
    # default for anything not listed
}

style = layer_styles.get(layer_name, dict(color="gray", fill=False))

m = child_model_gdf.explore(
    name=layer_name, style_kwds=style, tooltip=["hru_id", "hru_segment"]
)


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

# --- Add segment comparison layers ---
# Read the full parent segment layer and the child basin polygon
source_gpkg_map = (
    root_dir / "nhf_assist/hydrofabric_domain_data/OHM_2026_02_21/GIS/model_layers.gpkg"
)
all_segs = gpd.read_file(source_gpkg_map, layer="nsegment")

# Get child HRU segments (attribute-based method)
child_nhru = gpd.read_file(gpkg_path, layer="nhru")
child_hru_seg_ids = set(child_nhru["hru_segment"].unique())

# Get segments contained within the domain
basin_domain = gpd.read_file(gpkg_path, layer="domain")
basin_geom_map = basin_domain.geometry.unary_union
if all_segs.crs != basin_domain.crs:
    all_segs = all_segs.to_crs(basin_domain.crs)
within_seg_ids = set(
    all_segs[all_segs.geometry.within(basin_geom_map)]["model_seg_idx"]
)

# Downstream keepers: segments within domain that are to_segment targets of child segments
sel_by_hru_map = all_segs[all_segs["model_seg_idx"].isin(child_hru_seg_ids)]
hru_seg_to_segments = set(sel_by_hru_map["to_segment"]) - {0}
downstream_keepers = within_seg_ids & hru_seg_to_segments
final_seg_ids = child_hru_seg_ids | downstream_keepers

# Segments excluded: within domain but not in final (no HRU, not a downstream receiver)
excluded_ids = within_seg_ids - final_seg_ids
# Segments in final but not within domain
only_in_final = final_seg_ids - within_seg_ids

if excluded_ids:
    segs_excluded = all_segs[all_segs["model_seg_idx"].isin(excluded_ids)]
    m = segs_excluded.explore(
        m=m,
        name="Excluded segments (within domain, no HRU or to_segment link)",
        style_kwds=dict(color="red", weight=4),
    )
    print(f"  Excluded segments (red): {len(excluded_ids)}")

if downstream_keepers:
    segs_downstream = all_segs[all_segs["model_seg_idx"].isin(downstream_keepers)]
    m = segs_downstream.explore(
        m=m,
        name="Downstream keepers (no HRU, but is a to_segment of child)",
        style_kwds=dict(color="orange", weight=4),
    )
    print(f"  Downstream keeper segments (orange): {len(downstream_keepers)}")

if only_in_final:
    segs_only_final = all_segs[all_segs["model_seg_idx"].isin(only_in_final)]
    m = segs_only_final.explore(
        m=m,
        name="Segments in final but not within domain",
        style_kwds=dict(color="green", weight=4),
    )
    print(f"  Segments in final but not within domain (green): {len(only_in_final)}")

if not excluded_ids and not downstream_keepers and not only_in_final:
    print("  All methods agree — no differences to display.")

# add layer control so you can toggle them
folium.LayerControl().add_to(m)

m  # display in Jupyter

# %% [markdown]
# ### Test: Check for HRU and segment overlap between child domains

# %%
# Read all child domain GeoPackages and check for shared HRUs or segments
from collections import defaultdict

domains_dir_test = Path(root_dir / "nhf_assist/hydrofabric_domain_data")
child_folders = [
    p
    for p in domains_dir_test.iterdir()
    if p.is_dir() and (p / "GIS" / "child_nhf_domain.gpkg").exists()
]

hru_to_basins = defaultdict(list)
seg_to_basins = defaultdict(list)

for folder in child_folders:
    gpkg = folder / "GIS" / "child_nhf_domain.gpkg"
    basin_name = folder.name

    # Check HRUs
    try:
        nhru = gpd.read_file(gpkg, layer="nhru")
        for hru_id in nhru["hru_id"].values:
            hru_to_basins[hru_id].append(basin_name)
    except Exception:
        pass

    # Check segments
    try:
        nseg = gpd.read_file(gpkg, layer="nsegment")
        for seg_idx in nseg["model_seg_idx"].values:
            seg_to_basins[seg_idx].append(basin_name)
    except Exception:
        pass

# Find overlaps
hru_overlaps = {k: v for k, v in hru_to_basins.items() if len(v) > 1}
seg_overlaps = {k: v for k, v in seg_to_basins.items() if len(v) > 1}

print("=" * 70)
print("Child Domain Overlap Test")
print("=" * 70)
print(f"  Child domains checked: {len(child_folders)}")
print()

if hru_overlaps:
    print(f"  [WARNING] {len(hru_overlaps)} HRUs appear in multiple child domains:")
    for hru_id, basins in sorted(hru_overlaps.items()):
        print(f"    hru_id {hru_id}: {basins}")
else:
    print("  [PASS] No HRU overlap between child domains.")

print()

if seg_overlaps:
    print(f"  [WARNING] {len(seg_overlaps)} segments appear in multiple child domains:")
    for seg_idx, basins in sorted(seg_overlaps.items()):
        print(f"    model_seg_idx {seg_idx}: {basins}")
else:
    print("  [PASS] No segment overlap between child domains.")

# %%
