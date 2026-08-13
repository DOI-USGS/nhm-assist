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

# %% [markdown]
# # Create Subbasin Model from NHM v1.1
#
# This notebook provides an interactive map of the NHM v1.1 CONUS hydrofabric
# (GFv1.1) for selecting subbasin domains. The user provides a shapefile or
# vector file defining their area of interest. The notebook:
#
# 1. Finds all segments that intersect the AOI
# 2. Traces the full upstream network from those segments
# 3. Finds all HRUs connected to those segments
# 4. Displays everything on an interactive map with click-to-highlight
#
# ## Data source
# - GFv1.1 GeoDatabase: `data_dependencies/NHM_v1_1/version1_1_params/GFv1.1.gdb`
# - Layers used: `nsegment_v1_1` (segments), `nhru_v1_1_simp` (simplified HRUs)

# %%
import geopandas as gpd
import pandas as pd
import numpy as np
import pathlib as pl
import folium
import json
import os
from collections import defaultdict
from shapely.ops import transform
from shapely.geometry import mapping as geom_mapping

# Auto-rebuild .shx index file if missing from shapefiles
os.environ["SHAPE_RESTORE_SHX"] = "YES"

import assist as _assist_pkg
root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"


def drop_z(geom):
    """Remove Z dimension from geometry."""
    if geom.has_z:
        return transform(lambda x, y, z=None: (x, y), geom)
    return geom

# %% [markdown]
# ## Define paths and user area of interest
#
# Provide a shapefile, GeoPackage, or GeoJSON that defines your general area of
# interest (AOI). This can be a watershed boundary, a study area polygon, or
# any rough outline of the region you want to model.
#
# **How it works:**
# - The AOI geometry is used to find all NHM v1.1 segments that **intersect** it.
# - From those intersecting segments, the notebook traces the **full upstream
#   network** â€” every segment that contributes flow to the segments in your AOI.
# - All HRUs connected to those upstream segments are included automatically.
#
# **Your AOI does not need to be precise.** It just needs to cover the outlet(s)
# of the watershed(s) you're interested in. The upstream trace does the rest.
# For example, if you draw a polygon around a gage location, the notebook will
# find the full contributing watershed above it.

# %%
gdb_path = pl.Path(root_dir / r"data_dependencies\NHM_v1_1\version1_1_params\GFv1.1.gdb")

# User-supplied area of interest (shapefile, gpkg, geojson, etc.)
aoi_path = pl.Path(root_dir / r"data_dependencies\Examples\WWGW_Basin.shp")
aoi_layer = None  # set to None for shapefiles

# %% [markdown]
# ## Load AOI

# %%
if aoi_layer:
    aoi_gdf = gpd.read_file(aoi_path, layer=aoi_layer)
else:
    # Allow reading incomplete shapefiles (missing .shx, .dbf, etc.)
    import os
    os.environ["SHAPE_RESTORE_SHX"] = "YES"
    aoi_gdf = gpd.read_file(aoi_path)

print(f"Loaded AOI: {len(aoi_gdf)} features, CRS: {aoi_gdf.crs}")

# %% [markdown]
# ## Load full NHM v1.1 segment network (needed for routing)
# We load all segments to build the complete routing table, then subset
# to only those connected to the AOI.

# %% jupyter={"source_hidden": true}
print("Loading all NHM v1.1 segments (for routing)...")
seg_all = gpd.read_file(gdb_path, layer="nsegment_v1_1")
seg_all = seg_all.to_crs(epsg=4326)
print(f"  {len(seg_all)} total segments loaded")

# Build upstream routing from the FULL network
upstream_map = defaultdict(list)
for _, row in seg_all.iterrows():
    downstream = int(row["tosegment_v1_1"])
    seg_id = int(row["nsegment_v1_1"])
    if downstream > 0:
        upstream_map[downstream].append(seg_id)

print(f"  Full routing built: {len(upstream_map)} segments have upstream contributors")

# %% [markdown]
# # Find segments intersecting AOI, then trace full upstream network

# %%
# Reproject AOI to match segments
aoi_match = aoi_gdf.to_crs(seg_all.crs)
aoi_union = aoi_match.union_all()

# Find segments that intersect the AOI
intersecting_mask = seg_all.geometry.intersects(aoi_union)
seed_seg_ids = set(seg_all.loc[intersecting_mask, "nsegment_v1_1"].astype(int))
print(f"Segments intersecting AOI: {len(seed_seg_ids)}")


# Trace all upstream segments from the seed set
def get_all_upstream(seed_ids, upstream_lookup):
    """Recursively find all upstream segments from a set of seed segments."""
    visited = set()
    stack = list(seed_ids)
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        for us_seg in upstream_lookup.get(current, []):
            stack.append(us_seg)
    return visited


all_network_segs = get_all_upstream(seed_seg_ids, upstream_map)
print(f"Full upstream network: {len(all_network_segs)} segments (including {len(seed_seg_ids)} seed)")

# %% [markdown]
# ## Preview: Selected network vs all segments in AOI buffer
# This map shows the segments selected via upstream tracing (blue) alongside
# all NHM v1.1 segments within a 100 km buffer of the AOI (gray) for context.

# %% jupyter={"source_hidden": true}
# Load all segments within 100 km buffer of AOI for context
aoi_proj = aoi_gdf.to_crs(epsg=5070)
aoi_buffered_100km = aoi_proj.union_all().buffer(100_000)
aoi_buffered_4326 = gpd.GeoDataFrame(geometry=[aoi_buffered_100km], crs="EPSG:5070").to_crs(epsg=4326)
buffer_bbox = tuple(aoi_buffered_4326.total_bounds)

# Note: bbox filter uses the file's native CRS internally in newer pyogrio/fiona
seg_context = gpd.read_file(gdb_path, layer="nsegment_v1_1", bbox=buffer_bbox)
if seg_context.empty:
    # Fallback: load all segments and clip manually
    print("  bbox filter returned empty â€” loading all and clipping...")
    seg_context = gpd.read_file(gdb_path, layer="nsegment_v1_1")
    seg_context = seg_context.to_crs(epsg=4326)
    buffer_geom = aoi_buffered_4326.geometry.iloc[0]
    seg_context = seg_context[seg_context.geometry.intersects(buffer_geom)].copy()
else:
    seg_context = seg_context.to_crs(epsg=4326)

seg_context["nsegment_v1_1"] = seg_context["nsegment_v1_1"].astype(int)
seg_context = seg_context[["nsegment_v1_1", "tosegment_v1_1", "seg_id_nhm", "geometry"]]
print(f"Context segments (100 km buffer): {len(seg_context)}")

# Build map
aoi_4326 = aoi_gdf.to_crs(epsg=4326)
bounds = aoi_4326.total_bounds
center_lat = (bounds[1] + bounds[3]) / 2
center_lon = (bounds[0] + bounds[2]) / 2

m_preview = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=8,
    tiles=None,
    width="100%",
    height="100%",
)

# Basemaps
folium.raster_layers.WmsTileLayer(
    url="https://basemap.nationalmap.gov/arcgis/services/USGSHydroCached/MapServer/WMSServer",
    layers="0",
    fmt="image/png",
    transparent=True,
    name="USGS Hydro",
    overlay=False,
    control=True,
    attr="USGS National Map - NHD",
).add_to(m_preview)

folium.TileLayer("CartoDB positron", name="CartoDB Light").add_to(m_preview)

# AOI boundary
folium.GeoJson(
    aoi_4326.union_all().__geo_interface__,
    name="Area of Interest",
    style_function=lambda f: {
        "color": "red",
        "weight": 2,
        "fillOpacity": 0.05,
        "dashArray": "5, 5",
    },
).add_to(m_preview)

# Context segments (all within 100 km buffer) â€” gray
context_features = []
for _, row in seg_context.iterrows():
    geom = row["geometry"]
    # Force 2D by extracting coords
    geom_2d = drop_z(geom)
    context_features.append({
        "type": "Feature",
        "geometry": geom_mapping(geom_2d),
        "properties": {
            "nsegment_v1_1": str(int(row["nsegment_v1_1"])),
            "tosegment_v1_1": str(int(row["tosegment_v1_1"])),
        },
    })
if context_features:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": context_features},
        name="All segments (100 km buffer)",
        style_function=lambda f: {
            "color": "brown",
            "weight": 3,
            "opacity": 0.5,
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 6,
            "opacity": 1.0,
        },
        popup=folium.GeoJsonPopup(
            fields=["nsegment_v1_1", "tosegment_v1_1"],
            aliases=["Segment ID:", "To Segment:"],
        ),
    ).add_to(m_preview)

# Selected segments (from upstream trace) â€” blue
selected_segs_preview = seg_all[seg_all["nsegment_v1_1"].astype(int).isin(all_network_segs)].to_crs(epsg=4326)
selected_features = []
for _, row in selected_segs_preview.iterrows():
    geom_2d = drop_z(row["geometry"])
    selected_features.append({
        "type": "Feature",
        "geometry": geom_mapping(geom_2d),
        "properties": {
            "nsegment_v1_1": str(int(row["nsegment_v1_1"])),
            "tosegment_v1_1": str(int(row["tosegment_v1_1"])),
        },
    })

if selected_features:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": selected_features},
        name="Selected segments (upstream trace)",
        style_function=lambda f: {
            "color": "blue",
            "weight": 5,
            "opacity": 0.8,
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 8,
            "opacity": 1.0,
        },
        popup=folium.GeoJsonPopup(
            fields=["nsegment_v1_1", "tosegment_v1_1"],
            aliases=["Segment ID:", "To Segment:"],
        ),
    ).add_to(m_preview)

folium.LayerControl().add_to(m_preview)
m_preview

# %% [markdown]
# ## Modify selected segments
#
# Use the preview map above to identify segment IDs (hover over segments to see
# their `nsegment_v1_1` ID in the tooltip). Then edit the lists below:
#
# - **`add_to_selected_segments`**: Segment IDs from the brown context layer that
#   you want to add to the selection. All upstream segments connected to these
#   will be automatically included (full upstream trace).
#
# - **`remove_from_selected_segments`**: Segment IDs from the blue selected layer
#   that you want to remove. All upstream segments connected to these will also
#   be removed (full upstream trace).
#
# After modifying the lists, re-run the cells below to update the selection.

# %% jupyter={"source_hidden": true}
# Edit these lists based on the preview map
add_to_selected_segments = []  # e.g. [49990, 50001]
remove_from_selected_segments = []  # e.g. [12345]

# Apply modifications â€” trace full upstream network for any added/removed segments
if add_to_selected_segments:
    # Find all upstream segments connected to the added segments
    add_with_upstream = get_all_upstream(set(add_to_selected_segments), upstream_map)
    all_network_segs.update(add_with_upstream)
    print(f"  Added {len(add_to_selected_segments)} seed segments + {len(add_with_upstream) - len(add_to_selected_segments)} upstream = {len(add_with_upstream)} total added")

if remove_from_selected_segments:
    # Find all upstream segments connected to the removed segments
    remove_with_upstream = get_all_upstream(set(remove_from_selected_segments), upstream_map)
    all_network_segs -= remove_with_upstream
    print(f"  Removed {len(remove_from_selected_segments)} seed segments + {len(remove_with_upstream) - len(remove_from_selected_segments)} upstream = {len(remove_with_upstream)} total removed")

if not add_to_selected_segments and not remove_from_selected_segments:
    print("  No modifications â€” using original selection.")

print(f"  Final selected segment count: {len(all_network_segs)}")

# %% [markdown]
# ## Find HRUs connected to the stream network

# %% jupyter={"source_hidden": true}
# Subset segments to only those in the network
seg_gdf = seg_all[seg_all["nsegment_v1_1"].astype(int).isin(all_network_segs)].copy()
print(f"Segments for map: {len(seg_gdf)}")

# Load HRUs (simplified) â€” load all, then filter by segment membership
# Cannot use bbox because some HRUs draining to network segments may be outside segment extent
print("Loading all HRUs (simplified)...")
hru_all = gpd.read_file(gdb_path, layer="nhru_v1_1_simp")
hru_all = hru_all.to_crs(epsg=4326)

# Keep only HRUs whose hru_segment_v1_1 is in the network segment set
hru_gdf = hru_all[hru_all["hru_segment_v1_1"].astype(int).isin(all_network_segs)].copy()
print(f"HRUs connected to network: {len(hru_gdf)}")

# Cast columns to native Python types for JSON serialization
hru_gdf["nhru_v1_1"] = hru_gdf["nhru_v1_1"].astype(int)
hru_gdf["hru_segment_v1_1"] = hru_gdf["hru_segment_v1_1"].astype(int)
hru_gdf["nhm_id"] = hru_gdf["nhm_id"].astype(int)

seg_gdf["nsegment_v1_1"] = seg_gdf["nsegment_v1_1"].astype(int)
seg_gdf["tosegment_v1_1"] = seg_gdf["tosegment_v1_1"].astype(int)
seg_gdf["seg_id_nhm"] = seg_gdf["seg_id_nhm"].astype(int)

# Drop Z/M coordinates that cause serialization issues
hru_gdf["geometry"] = hru_gdf["geometry"].apply(drop_z)
seg_gdf["geometry"] = seg_gdf["geometry"].apply(drop_z)

# Keep only the columns we need (drop any problematic GDB metadata columns)
hru_gdf = hru_gdf[["nhru_v1_1", "hru_segment_v1_1", "nhm_id", "geometry"]].copy()
seg_gdf = seg_gdf[["nsegment_v1_1", "tosegment_v1_1", "seg_id_nhm", "geometry"]].copy()

print(f"HRUs connected to network: {len(hru_gdf)}")
print(f"Segments for map: {len(seg_gdf)}")

# %% [markdown]
# ## Check for interior HRUs not connected to the network
# Dissolve selected HRUs into one boundary, then find any unselected HRUs
# whose centroid falls inside that boundary. These are "orphan" HRUs â€” typically
# in closed basins or routing to segments outside the traced network, but can also occur as small loop anomolies in HRU boundaries.

# %% jupyter={"source_hidden": true}
# Dissolve selected HRUs into a single boundary (fill holes so interior HRUs aren't missed)
from shapely.geometry import Polygon, MultiPolygon

def fill_holes(geom):
    """Remove interior holes from a polygon or multipolygon."""
    if geom.geom_type == "Polygon":
        return Polygon(geom.exterior)
    elif geom.geom_type == "MultiPolygon":
        return MultiPolygon([Polygon(p.exterior) for p in geom.geoms])
    return geom

selected_boundary = fill_holes(hru_gdf.union_all())

# Find unselected HRUs from the full set
selected_hru_ids = set(hru_gdf["nhru_v1_1"].astype(int))
unselected_hrus = hru_all[~hru_all["nhru_v1_1"].astype(int).isin(selected_hru_ids)].copy()
unselected_hrus = unselected_hrus.to_crs(epsg=4326)

# Check which unselected HRUs have centroids inside the selected boundary
# Project to EPSG:5070 for accurate centroid calculation
unselected_proj = unselected_hrus.to_crs(epsg=5070)
boundary_proj = gpd.GeoSeries([selected_boundary], crs="EPSG:4326").to_crs(epsg=5070).iloc[0]
unselected_centroids = unselected_proj.geometry.centroid
interior_mask = unselected_centroids.within(boundary_proj)
interior_hrus = unselected_hrus[interior_mask].copy()

if len(interior_hrus) > 0:
    print(f"[WARNING] {len(interior_hrus)} interior HRUs found inside the selected domain "
          f"but NOT connected to the network:")
    print(f"  HRU IDs: {interior_hrus['nhru_v1_1'].tolist()[:20]}{'...' if len(interior_hrus) > 20 else ''}")
    print(f"  Their hru_segment_v1_1 values: {interior_hrus['hru_segment_v1_1'].unique().tolist()[:20]}")

    # Keep a copy for map display
    interior_hrus_for_map = interior_hrus.copy()
else:
    interior_hrus_for_map = None
    print(f"[OK] No interior HRUs missing from selection.")

# %% [markdown]
# ## Preview: Selected HRUs vs all HRUs in AOI buffer
# This map shows the selected HRUs (green) alongside all NHM v1.1 HRUs within
# a 100 km buffer of the AOI (gray) for context.

# %% jupyter={"source_hidden": true}
# Load all HRUs within 100 km buffer of AOI for context
hru_context = hru_all.to_crs(epsg=4326)
buffer_geom_4326 = aoi_buffered_4326.geometry.iloc[0]
hru_context = hru_context[hru_context.geometry.centroid.within(buffer_geom_4326)].copy()
print(f"Context HRUs (100 km buffer): {len(hru_context)}")

# Build map
m_hru_preview = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=8,
    tiles=None,
    width="100%",
    height="100%",
)

folium.raster_layers.WmsTileLayer(
    url="https://basemap.nationalmap.gov/arcgis/services/USGSHydroCached/MapServer/WMSServer",
    layers="0",
    fmt="image/png",
    transparent=True,
    name="USGS Hydro",
    overlay=False,
    control=True,
    attr="USGS National Map - NHD",
).add_to(m_hru_preview)

folium.TileLayer("CartoDB positron", name="CartoDB Light").add_to(m_hru_preview)

# AOI boundary
folium.GeoJson(
    aoi_4326.union_all().__geo_interface__,
    name="Area of Interest",
    style_function=lambda f: {
        "color": "red",
        "weight": 2,
        "fillOpacity": 0.05,
        "dashArray": "5, 5",
    },
).add_to(m_hru_preview)

# Context HRUs (all within 100 km buffer) â€” gray
context_hru_features = []
for _, row in hru_context.iterrows():
    context_hru_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "nhru_v1_1": str(int(row["nhru_v1_1"])),
            "hru_segment_v1_1": str(int(row["hru_segment_v1_1"])),
        },
    })
if context_hru_features:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": context_hru_features},
        name="All HRUs (100 km buffer)",
        style_function=lambda f: {
            "color": "gray",
            "weight": 0.5,
            "fillOpacity": 0.2,
            "fillColor": "lightgray",
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 3,
            "fillOpacity": 0.5,
        },
        popup=folium.GeoJsonPopup(
            fields=["nhru_v1_1", "hru_segment_v1_1"],
            aliases=["HRU ID:", "HRU Segment:"],
        ),
    ).add_to(m_hru_preview)

# Selected HRUs â€” green
selected_hru_features = []
for _, row in hru_gdf.iterrows():
    selected_hru_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "nhru_v1_1": str(int(row["nhru_v1_1"])),
            "hru_segment_v1_1": str(int(row["hru_segment_v1_1"])),
        },
    })
if selected_hru_features:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": selected_hru_features},
        name="Selected HRUs",
        style_function=lambda f: {
            "color": "green",
            "weight": 1,
            "fillOpacity": 0.4,
            "fillColor": "green",
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 3,
            "fillOpacity": 0.6,
        },
        popup=folium.GeoJsonPopup(
            fields=["nhru_v1_1", "hru_segment_v1_1"],
            aliases=["HRU ID:", "HRU Segment:"],
        ),
    ).add_to(m_hru_preview)

# Interior HRUs (orphans found in Check 1) â€” orange
if interior_hrus_for_map is not None and len(interior_hrus_for_map) > 0:
    interior_hru_features = []
    for _, row in interior_hrus_for_map.iterrows():
        interior_hru_features.append({
            "type": "Feature",
            "geometry": geom_mapping(drop_z(row["geometry"])),
            "properties": {
                "nhru_v1_1": str(int(row["nhru_v1_1"])),
                "hru_segment_v1_1": str(int(row["hru_segment_v1_1"])),
            },
        })
    folium.GeoJson(
        {"type": "FeatureCollection", "features": interior_hru_features},
        name="Interior HRUs (not on network)",
        style_function=lambda f: {
            "color": "orange",
            "weight": 2,
            "fillOpacity": 0.5,
            "fillColor": "orange",
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 3,
            "fillOpacity": 0.7,
        },
        popup=folium.GeoJsonPopup(
            fields=["nhru_v1_1", "hru_segment_v1_1"],
            aliases=["HRU ID:", "HRU Segment:"],
        ),
    ).add_to(m_hru_preview)

folium.LayerControl().add_to(m_hru_preview)
m_hru_preview

# %% [markdown]
# ### User decision: include or exclude orphan HRUs?
# The following lists allow you to control which interior (orphan) HRUs are
# included in or excluded from the final selection. By default, all orphan HRUs
# are placed in the **excluded** list. Move HRU IDs to `orphan_hrus_included`
# if you want them in the model. NOTE: if included, the to_segment parameter will need to be changed later to "0" or to a segment_id in the subbasin. This notebook will default to "0".

# %%
# Edit these lists to control which orphan HRUs are included/excluded
if interior_hrus_for_map is not None:
    all_orphan_hru_ids = interior_hrus_for_map["nhru_v1_1"].astype(int).tolist()
else:
    all_orphan_hru_ids = []

# DEFAULT: all orphans excluded. Move IDs to orphan_hrus_included to add them.
orphan_hrus_included = []  # e.g. [97949, 97994]
orphan_hrus_excluded = [hid for hid in all_orphan_hru_ids if hid not in orphan_hrus_included]

print(f"Orphan HRUs included: {len(orphan_hrus_included)} â€” {orphan_hrus_included}")
print(f"Orphan HRUs excluded: {len(orphan_hrus_excluded)} â€” {orphan_hrus_excluded}")

# Apply: add included orphan HRUs to the selection
if orphan_hrus_included and interior_hrus_for_map is not Non:
    include_mask = interior_hrus_for_map["nhru_v1_1"].astype(int).isin(orphan_hrus_included)
    hru_gdf = pd.concat([hru_gdf, interior_hrus_for_map[include_mask]], ignore_index=True)
    hru_gdf["nhru_v1_1"] = hru_gdf["nhru_v1_1"].astype(int)
    hru_gdf["hru_segment_v1_1"] = hru_gdf["hru_segment_v1_1"].astype(int)
    hru_gdf["nhm_id"] = hru_gdf["nhm_id"].astype(int)
    print(f"  Total HRUs after adding included orphans: {len(hru_gdf)}")
else:
    print(f"  No orphan HRUs added to selection.")

# %% [markdown]
# ### User decision: add other HRUs?
# If there are additional HRUs you want to include in the selection (e.g., HRUs
# you identified from the HRU preview map that are not connected to the network
# but should be part of the model domain), add their `nhru_v1_1` IDs to the list below.
#
# **Note:** When you add an HRU, the segment it flows to (`hru_segment_v1_1`) is
# automatically added to the selected segments as well. Only the direct segment
# is added â€” NOT its full upstream network. This ensures the HRU has a valid
# routing target in the model without pulling in an entire additional watershed.

# %%
# Edit this list to add any additional HRUs to the selection
add_other_hrus = []  # e.g. [97949, 97994, 76500]

if add_other_hrus:
    other_hrus_to_add = hru_all[hru_all["nhru_v1_1"].astype(int).isin(add_other_hrus)].copy()
    other_hrus_to_add = other_hrus_to_add.to_crs(hru_gdf.crs)
    hru_gdf = pd.concat([hru_gdf, other_hrus_to_add], ignore_index=True)
    hru_gdf["nhru_v1_1"] = hru_gdf["nhru_v1_1"].astype(int)
    hru_gdf["hru_segment_v1_1"] = hru_gdf["hru_segment_v1_1"].astype(int)
    hru_gdf["nhm_id"] = hru_gdf["nhm_id"].astype(int)
    # Remove duplicates in case any were already selected
    hru_gdf = hru_gdf.drop_duplicates(subset="nhru_v1_1").reset_index(drop=True)

    # Also add the segments these HRUs flow to (direct segment only, not upstream)
    new_seg_ids = set(other_hrus_to_add["hru_segment_v1_1"].astype(int).unique())
    segs_to_add = new_seg_ids - all_network_segs
    if segs_to_add:
        all_network_segs.update(segs_to_add)
        # Also add to seg_gdf
        new_segs_gdf = seg_all[seg_all["nsegment_v1_1"].astype(int).isin(segs_to_add)].copy()
        new_segs_gdf = new_segs_gdf.to_crs(seg_gdf.crs)
        new_segs_gdf["nsegment_v1_1"] = new_segs_gdf["nsegment_v1_1"].astype(int)
        new_segs_gdf["tosegment_v1_1"] = new_segs_gdf["tosegment_v1_1"].astype(int)
        new_segs_gdf["seg_id_nhm"] = new_segs_gdf["seg_id_nhm"].astype(int)
        new_segs_gdf["geometry"] = new_segs_gdf["geometry"].apply(drop_z)
        new_segs_gdf = new_segs_gdf[["nsegment_v1_1", "tosegment_v1_1", "seg_id_nhm", "geometry"]]
        seg_gdf = pd.concat([seg_gdf, new_segs_gdf], ignore_index=True)
        seg_gdf = seg_gdf.drop_duplicates(subset="nsegment_v1_1").reset_index(drop=True)
        print(f"  Also added {len(segs_to_add)} segments (direct receivers): {sorted(segs_to_add)}")

    print(f"  Added {len(add_other_hrus)} HRUs: {add_other_hrus}")
    print(f"  Total HRUs: {len(hru_gdf)}, Total segments: {len(seg_gdf)}")
else:
    print("  No additional HRUs added.")

# %% [markdown]
# ## Check for segments outside the domain boundary
# Using the dissolved HRU outline, check if any segments that HRUs drain to
# are physically located outside the domain. These would be segments that receive
# flow from the domain but are not inside it.

# %% jupyter={"source_hidden": true}
# Check if any selected HRUs reference segments NOT in the selected segment list
referenced_seg_ids = set(hru_gdf["hru_segment_v1_1"].astype(int).unique())
missing_seg_ids = referenced_seg_ids - all_network_segs

if missing_seg_ids:
    # Find those segments in the full segment layer
    outside_segs = seg_all[seg_all["nsegment_v1_1"].astype(int).isin(missing_seg_ids)].copy()
    outside_segs = outside_segs.to_crs(epsg=4326)

    # Find which HRUs reference these missing segments
    hrus_with_missing_segs = hru_gdf[hru_gdf["hru_segment_v1_1"].astype(int).isin(missing_seg_ids)]

    print(f"[WARNING] {len(missing_seg_ids)} segments referenced by selected HRUs are NOT in the selected segments:")
    print(f"  Missing segment IDs: {sorted(missing_seg_ids)[:20]}{'...' if len(missing_seg_ids) > 20 else ''}")
    print(f"  HRUs referencing these segments: {len(hrus_with_missing_segs)}")
    outside_segs_for_map = outside_segs.copy()
else:
    outside_segs_for_map = None
    print(f"[OK] All selected HRUs flow to segments in the selected segment list.")

# %% [markdown]
# ## Create interactive map
# Final map showing the selected segments and HRUs after all checks and modifications.
# Click on any segment to highlight all upstream segments and their HRUs.

# %%
# Center on the network extent
bounds = seg_gdf.total_bounds
center_lat = (bounds[1] + bounds[3]) / 2
center_lon = (bounds[0] + bounds[2]) / 2

m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=9,
    tiles=None,
    width="100%",
    height="100%",
)

# USGS Hydro basemap
folium.raster_layers.WmsTileLayer(
    url="https://basemap.nationalmap.gov/arcgis/services/USGSHydroCached/MapServer/WMSServer",
    layers="0",
    fmt="image/png",
    transparent=True,
    name="USGS Hydro",
    overlay=False,
    control=True,
    attr="USGS National Map - NHD",
).add_to(m)

folium.TileLayer("CartoDB positron", name="CartoDB Light").add_to(m)

# Add AOI boundary for reference
folium.GeoJson(
    aoi_4326.union_all().__geo_interface__,
    name="Area of Interest",
    style_function=lambda f: {
        "color": "red",
        "weight": 2,
        "fillOpacity": 0.05,
        "dashArray": "5, 5",
    },
).add_to(m)

# Add HRU layer
hru_features = []
for _, row in hru_gdf.iterrows():
    hru_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "nhru_v1_1": str(int(row["nhru_v1_1"])),
            "hru_segment_v1_1": str(int(row["hru_segment_v1_1"])),
            "nhm_id": str(int(row["nhm_id"])),
        },
    })
if hru_features:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": hru_features},
        name="Selected HRUs",
        style_function=lambda f: {
            "color": "gray",
            "weight": 0.5,
            "fillOpacity": 0.2,
            "fillColor": "lightgreen",
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 3,
            "fillOpacity": 0.5,
        },
        popup=folium.GeoJsonPopup(
            fields=["nhru_v1_1", "hru_segment_v1_1", "nhm_id"],
            aliases=["HRU ID:", "HRU Segment:", "NHM ID:"],
        ),
    ).add_to(m)

# Add segment layer
seg_features = []
for _, row in seg_gdf.iterrows():
    seg_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "nsegment_v1_1": str(int(row["nsegment_v1_1"])),
            "tosegment_v1_1": str(int(row["tosegment_v1_1"])),
            "seg_id_nhm": str(int(row["seg_id_nhm"])),
        },
    })
if seg_features:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": seg_features},
        name="Selected Segments",
        style_function=lambda f: {
            "color": "blue",
            "weight": 3,
            "opacity": 0.8,
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 6,
            "opacity": 1.0,
        },
        popup=folium.GeoJsonPopup(
            fields=["nsegment_v1_1", "tosegment_v1_1", "seg_id_nhm"],
            aliases=["Segment ID:", "To Segment:", "NHM Seg ID:"],
        ),
    ).add_to(m)

folium.LayerControl().add_to(m)

# Fit map to show all features
m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

# Save
out_html = pl.Path(root_dir / r"notebooks\notebook_output_files\html_maps")
out_html.mkdir(parents=True, exist_ok=True)
map_file = out_html / "NHM_v1_1_subbasin_selector.html"
m.save(str(map_file))
print(f"\nMap saved to: {map_file}")
print(f"  Final selection: {len(seg_gdf)} segments, {len(hru_gdf)} HRUs")
m

# %%
len(seg_gdf)

# %%
len(hru_gdf)

# %% [markdown]
# ## Write child model GeoPackage
#
# This step creates a child model directory named after the AOI shapefile and
# writes a GeoPackage containing:
# - `nhru` â€” selected HRUs
# - `nsegment` â€” selected segments
# - `npoi` â€” POIs whose `poi_segment_v1_1` is in the selected segments
# - `domain` â€” dissolved HRU boundary (holes filled)

# %%
# Derive child model name from AOI filename
child_model_name = aoi_path.stem  # e.g. "Malheur_Lake" from "Malheur_Lake.shp"

# Create child model directory
child_hf_dir = root_dir / "hydrofabric_domain_data" / child_model_name
child_hf_dir.mkdir(parents=True, exist_ok=True)
child_gis_dir = child_hf_dir / "GIS"
child_gis_dir.mkdir(parents=True, exist_ok=True)

# Output GeoPackage path
child_gpkg = child_gis_dir / "child_nhf_domain.gpkg"
print(f"Child model: {child_model_name}")
print(f"Output: {child_gpkg}")

# %%
hru_gdf.columns

# %%
# Get the set of selected segment IDs for POI filtering
selected_seg_ids = set(seg_gdf["nsegment_v1_1"].astype(int))

# Write HRU layer

hru_gdf.to_file(child_gpkg, layer="nhru", driver="GPKG")
print(f"  Wrote nhru: {len(hru_gdf)} features")

# Write segment layer
seg_gdf.to_file(child_gpkg, layer="nsegment", driver="GPKG", mode="a")
print(f"  Wrote nsegment: {len(seg_gdf)} features")

# Load and filter POIs_v1_1
print("  Loading POIs_v1_1...")
pois_gdf = gpd.read_file(gdb_path, layer="POIs_v1_1")
pois_gdf = pois_gdf.to_crs(epsg=4326)
pois_gdf["poi_segment_v1_1"] = pois_gdf["poi_segment_v1_1"].astype(int)
pois_selected = pois_gdf[pois_gdf["poi_segment_v1_1"].isin(selected_seg_ids)].copy()
if len(pois_selected) > 0:
    pois_selected["geometry"] = pois_selected["geometry"].apply(drop_z)
    pois_selected.to_file(child_gpkg, layer="npoi", driver="GPKG", mode="a")
print(f"  Wrote npoi: {len(pois_selected)} features")

# Write dissolved HRU boundary (with holes filled) as domain layer
domain_boundary_final = fill_holes(hru_gdf.union_all())
aoi_dissolved = gpd.GeoDataFrame(
    geometry=[domain_boundary_final],
    crs=hru_gdf.crs,
)
aoi_dissolved.to_file(child_gpkg, layer="domain", driver="GPKG", mode="a")
print(f"  Wrote domain: 1 feature (dissolved HRU boundary, holes filled)")

print(f"\nChild model GeoPackage written to: {child_gpkg}")
print(f"  Layers: nhru ({len(hru_gdf)}), nsegment ({len(seg_gdf)}), "
      f"npoi ({len(pois_selected)}), domain (1)")

# %% [markdown]
# ## View child model GeoPackage
# Interactive map of the layers written to the child GeoPackage.

# %%
import fiona

# Read layers back from the child GeoPackage
child_layers = fiona.listlayers(str(child_gpkg))
print(f"Child GeoPackage layers: {child_layers}")

# Build map
child_bounds = hru_gdf.total_bounds
child_center_lat = (child_bounds[1] + child_bounds[3]) / 2
child_center_lon = (child_bounds[0] + child_bounds[2]) / 2

m_child = folium.Map(
    location=[child_center_lat, child_center_lon],
    zoom_start=9,
    tiles=None,
    width="100%",
    height="100%",
)

folium.raster_layers.WmsTileLayer(
    url="https://basemap.nationalmap.gov/arcgis/services/USGSHydroCached/MapServer/WMSServer",
    layers="0",
    fmt="image/png",
    transparent=True,
    name="USGS Hydro",
    overlay=False,
    control=True,
    attr="USGS National Map - NHD",
).add_to(m_child)

folium.TileLayer("CartoDB positron", name="CartoDB Light").add_to(m_child)

# Domain boundary (black dashed)
domain_gdf = gpd.read_file(child_gpkg, layer="domain")
folium.GeoJson(
    domain_gdf.to_json(),
    name="Domain",
    style_function=lambda f: {
        "color": "black",
        "weight": 3,
        "fillOpacity": 0.03,
        "dashArray": "8, 4",
    },
).add_to(m_child)

# HRUs (light green)
child_hru_features = []
for _, row in hru_gdf.iterrows():
    child_hru_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "nhru_v1_1": str(int(row["nhru_v1_1"])),
            "hru_segment_v1_1": str(int(row["hru_segment_v1_1"])),
            "nhm_id": str(int(row["nhm_id"])),
        },
    })
if child_hru_features:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": child_hru_features},
        name="nhru",
        style_function=lambda f: {
            "color": "green",
            "weight": 0.5,
            "fillOpacity": 0.2,
            "fillColor": "lightgreen",
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 3,
            "fillOpacity": 0.5,
        },
        popup=folium.GeoJsonPopup(
            fields=["nhru_v1_1", "hru_segment_v1_1", "nhm_id"],
            aliases=["HRU ID:", "HRU Segment:", "NHM ID:"],
        ),
    ).add_to(m_child)

# Segments (blue)
child_seg_features = []
for _, row in seg_gdf.iterrows():
    child_seg_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "nsegment_v1_1": str(int(row["nsegment_v1_1"])),
            "tosegment_v1_1": str(int(row["tosegment_v1_1"])),
            "seg_id_nhm": str(int(row["seg_id_nhm"])),
        },
    })
if child_seg_features:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": child_seg_features},
        name="nsegment",
        style_function=lambda f: {
            "color": "blue",
            "weight": 3,
            "opacity": 0.8,
        },
        highlight_function=lambda f: {
            "color": "yellow",
            "weight": 6,
            "opacity": 1.0,
        },
        popup=folium.GeoJsonPopup(
            fields=["nsegment_v1_1", "tosegment_v1_1", "seg_id_nhm"],
            aliases=["Segment ID:", "To Segment:", "NHM Seg ID:"],
        ),
    ).add_to(m_child)

# POIs (red markers)
if len(pois_selected) > 0:
    for _, row in pois_selected.iterrows():
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=6,
            color="red",
            fill=True,
            fill_color="red",
            fill_opacity=0.8,
            popup=f"POI seg: {int(row['poi_segment_v1_1'])}",
        ).add_to(m_child)

folium.LayerControl().add_to(m_child)
m_child.fit_bounds([[child_bounds[1], child_bounds[0]], [child_bounds[3], child_bounds[2]]])

# Save
child_map_file = child_gis_dir / f"{child_model_name}_map.html"
m_child.save(str(child_map_file))
print(f"Map saved to: {child_map_file}")
m_child

# %%
