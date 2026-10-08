# %% [markdown]
# # Create Subbasin Model from NHM (GFv2)
#
# This notebook provides an interactive map of the NHM v2 CONUS hydrofabric
# (GFv2, gfv2r2) for selecting subbasin domains. The user provides a shapefile or
# vector file defining their area of interest. The notebook:
#
# 1. Finds all segments that intersect the AOI
# 2. Traces the full upstream network from those segments
# 3. Finds all HRUs connected to those segments
# 4. Displays everything on an interactive map with click-to-highlight
#
# ## Data source
# - GFv2 GeoPackage: `data_dependencies/gfv2r2/gfv2r2.gpkg`
# - Layers used: `nsegment` (segments), `nhru` (HRUs), `npoi` (POIs),
#   `poi_data` (per-POI hydrologic-location attributes; the full ";"-delimited
#   list of reference types, plus the `type_gages` gage id, are joined onto
#   `npoi` by `nat_poi_id`)
#
# ## Key differences from GFv1.1
# - Source is a GeoPackage (`.gpkg`), not a GeoDatabase (`.gdb`).
# - Segment ID column is `seg_id` (was `nsegment_v1_1`); downstream is
#   `to_segment` (was `tosegment_v1_1`).
# - HRU ID column is `nat_hru_id` (was `nhru_v1_1`); HRU-to-segment is
#   `hru_segment` (was `hru_segment_v1_1`).
# - POI-to-segment column is `poi_segment` (was `poi_segment_v1_1`).
# - Outlets are marked by a **missing (NaN)** `to_segment`, not by a value of 0.
# - There is no `seg_id_nhm` / `nhm_id` column in GFv2; those fields are dropped.

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

# import assist as _assist_pkg
# root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"

from assist.workspace.bridge import resolve_repo_root
from assist.common.assist_utilities import find_missing_gage_info
from assist.common.sf_data_retrieval import fetch_daily_discharge_batch
from dataretrieval import waterdata

root_dir = resolve_repo_root()


def find_project_root(start=None):
    """Walk up from `start` (default: current working dir) to the nhm-assist
    project root, identified by the `.nhm-assist-project` marker file."""
    start = pl.Path(start or pl.Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".nhm-assist-project").is_file():
            return candidate
    raise FileNotFoundError(
        "Could not locate a '.nhm-assist-project' marker in any parent of "
        f"{start}. Open this notebook from within a project workspace."
    )


# Project workspace root (e.g. D:\\nhm-workspace\\GF2v2_conus). Outputs go here,
# under the project's `fabrics` folder — NOT back into the nhf_assist repo.
project_dir = find_project_root()
print(f"Project root: {project_dir}")


def drop_z(geom):
    """Remove Z dimension from geometry."""
    if geom.has_z:
        return transform(lambda x, y, z=None: (x, y), geom)
    return geom


# --- Shared basemap/widget helpers, matching the other NHM notebooks ----------
# These reproduce assist.common.map_template's basemaps and widgets inline so
# this notebook stays lightweight (importing that module pulls in numba/pyPRMS).
# All tiles use direct XYZ/ArcGIS tile URLs that need NO API key, which fixes
# the "API Key required" background from folium's keyed CartoDB shorthand.
from folium import plugins
from folium.plugins import MeasureControl


def add_nhm_basemaps(fmap):
    """Add the four standard NHM basemaps. Returns the default (USGSHydroCached)
    layer so it can also be reused as the minimap tile if desired."""
    usgs_hydro = folium.TileLayer(
        tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSHydroCached/MapServer/tile/{z}/{y}/{x}",
        attr="USGSHydroCached",
        name="USGSHydroCached",
    )
    usgs_topo = folium.TileLayer(
        tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        attr="USGS_topo",
        name="USGS Topography",
        show=False,
    )
    esri_imagery = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
        name="Esri_imagery",
        show=False,
    )
    open_topo = folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr='Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
        name="OpenTopoMap",
        show=False,
    )
    usgs_hydro.add_to(fmap)
    usgs_topo.add_to(fmap)
    esri_imagery.add_to(fmap)
    open_topo.add_to(fmap)
    return usgs_hydro


def add_nhm_map_widgets(fmap):
    """Add the inset minimap, measure tool, and fullscreen button used on the
    other NHM maps."""
    minimap = plugins.MiniMap(
        tile_layer="OpenStreetMap",
        position="topleft",
        height=200,
        width=200,
        collapsed_height=25,
        collapsed_width=25,
        zoom_level_fixed=5,
        toggle_display=True,
    )
    fmap.add_child(minimap)
    fmap.add_child(MeasureControl(position="bottomright"))
    plugins.Fullscreen(position="topleft").add_to(fmap)

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
# GFv2 fabric lives in the repo-root data_dependencies (one level above nhf_assist)
gpkg_path = pl.Path(root_dir / r"data_dependencies\gfv2r2\gfv2r2.gpkg")

# User-supplied area of interest (shapefile, gpkg, geojson, etc.)
aoi_path = pl.Path(project_dir / r"fabrics\FlamingGorge.shp")
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
# ## Load full NHM GFv2 segment network (needed for routing)
# We load all segments to build the complete routing table, then subset
# to only those connected to the AOI.

# %% jupyter={"source_hidden": true}
print("Loading all NHM GFv2 segments (for routing)...")
seg_all = gpd.read_file(gpkg_path, layer="nsegment")
seg_all = seg_all.to_crs(epsg=4326)
print(f"  {len(seg_all)} total segments loaded")

# Build upstream routing from the FULL network.
# In GFv2, outlets have a MISSING (NaN) to_segment rather than 0, and
# to_segment is stored as float, so guard against NaN before casting to int.
upstream_map = defaultdict(list)
for _, row in seg_all.iterrows():
    downstream = row["to_segment"]
    if pd.isna(downstream):
        continue  # outlet segment, no downstream
    downstream = int(downstream)
    seg_id = int(row["seg_id"])
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
seed_seg_ids = set(seg_all.loc[intersecting_mask, "seg_id"].astype(int))
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
# all NHM GFv2 segments within a buffer of the AOI (gray) for context. The
# buffer size is set by `context_buffer_km` in the cell below (smaller = fewer
# features = faster map).

# %%
# Context buffer around the AOI, in km. Smaller = fewer segments to draw =
# a faster map. Change this one value to adjust the gray context extent.
context_buffer_km = 10

# Buffer the AOI in EPSG:5070 (meters), which is also the fabric's native CRS.
aoi_proj = aoi_gdf.to_crs(epsg=5070)
aoi_buffered = aoi_proj.union_all().buffer(context_buffer_km * 1_000)
aoi_buffered_4326 = gpd.GeoDataFrame(geometry=[aoi_buffered], crs="EPSG:5070").to_crs(epsg=4326)

# Read with a bbox in the GeoPackage's NATIVE CRS (EPSG:5070) so the spatial
# index is actually used. Passing a 4326 bbox against a 5070 file matches
# nothing and forces a full-CONUS read + Python clip (very slow).
buffer_bbox_5070 = tuple(gpd.GeoSeries([aoi_buffered], crs="EPSG:5070").total_bounds)
seg_context = gpd.read_file(gpkg_path, layer="nsegment", bbox=buffer_bbox_5070)
if seg_context.empty:
    # Fallback: load all segments and clip manually
    print("  bbox filter returned empty â€” loading all and clipping...")
    seg_context = gpd.read_file(gpkg_path, layer="nsegment")
    seg_context = seg_context[seg_context.geometry.intersects(aoi_buffered)].copy()
seg_context = seg_context.to_crs(epsg=4326)

seg_context["seg_id"] = seg_context["seg_id"].astype(int)
seg_context["geometry"] = seg_context["geometry"].apply(drop_z)
seg_context = seg_context[["seg_id", "to_segment", "geometry"]]
print(f"Context segments ({context_buffer_km} km buffer): {len(seg_context)}")

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

# Basemaps + widgets (matching the other NHM notebooks)
add_nhm_basemaps(m_preview)
add_nhm_map_widgets(m_preview)

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

# Context segments (all within the buffer) â€” gray, lightweight.
# Rendered as a single non-interactive layer (no per-feature popup/highlight),
# which is what keeps a few-thousand-line context layer fast to draw.
if len(seg_context) > 0:
    folium.GeoJson(
        seg_context[["geometry"]],
        name=f"All segments ({context_buffer_km} km buffer)",
        style_function=lambda f: {
            "color": "brown",
            "weight": 2,
            "opacity": 0.5,
        },
        # No popup/highlight here: those add per-feature JS callbacks that make
        # a large context layer slow. Use the blue selected layer to inspect IDs.
    ).add_to(m_preview)

# Selected segments (from upstream trace) â€” blue
selected_segs_preview = seg_all[seg_all["seg_id"].astype(int).isin(all_network_segs)].to_crs(epsg=4326)
selected_features = []
for _, row in selected_segs_preview.iterrows():
    geom_2d = drop_z(row["geometry"])
    to_seg = row["to_segment"]
    to_seg_str = "outlet" if pd.isna(to_seg) else str(int(to_seg))
    selected_features.append({
        "type": "Feature",
        "geometry": geom_mapping(geom_2d),
        "properties": {
            "seg_id": str(int(row["seg_id"])),
            "to_segment": to_seg_str,
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
            fields=["seg_id", "to_segment"],
            aliases=["Segment ID:", "To Segment:"],
        ),
    ).add_to(m_preview)

folium.LayerControl(collapsed=True, position="bottomright").add_to(m_preview)

# Save the preview map into this child's fabric folder. The folder is named
# from the AOI file (same name used later when the child GeoPackage is written).
preview_gis_dir = project_dir / "fabrics" / aoi_path.stem / "GIS"
preview_gis_dir.mkdir(parents=True, exist_ok=True)
preview_map_file = preview_gis_dir / "segment_selection_preview.html"
m_preview.save(str(preview_map_file))
print(f"Preview map saved to: {preview_map_file}")

# Open the saved map in the default web browser
import webbrowser
webbrowser.open(preview_map_file.as_uri())

m_preview

# %% [markdown]
# ## Modify selected segments
#
# Use the preview map above to identify segment IDs (hover over segments to see
# their `seg_id` in the tooltip). Then edit the lists below:
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

# %%
# Edit these lists based on the preview map
add_to_selected_segments = []  # e.g. [49990, 50001]
remove_from_selected_segments = []  # e.g. [12345] (it seems to be chasing up the network when removing. Fix that)

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
# ## Modify selected segments II
# - **`remove_segment_from_selected_segments`**: Segment IDs from the blue selected
#   layer that you want to remove. This removes the listed segment(s) **and all
#   segments downstream** of them (following `to_segment` to the outlet), within
#   the current selection.
#
# Note: this is the mirror of the first modify step, which removes a segment and
# everything **upstream**. Removing downstream can leave upstream segments in the
# selection whose `to_segment` now points at a removed segment (a "dangling"
# reference). We intentionally leave those dangling values as-is here and filter
# them downstream.

# %%
# Build a downstream lookup: each segment -> its single downstream (to_segment).
# Outlets (NaN to_segment) have no entry.
downstream_map = {}
for _, _row in seg_all.iterrows():
    _ds = _row["to_segment"]
    if pd.isna(_ds):
        continue
    downstream_map[int(_row["seg_id"])] = int(_ds)


def get_all_downstream(seed_ids, downstream_lookup):
    """Follow to_segment links downstream from each seed until an outlet."""
    visited = set()
    for start in seed_ids:
        current = start
        while current is not None and current not in visited:
            visited.add(current)
            current = downstream_lookup.get(current)
    return visited


remove_segment_from_selected_segments = [137204]

if remove_segment_from_selected_segments:
    # Segment(s) to remove + everything downstream of them, limited to the
    # current selection.
    _seeds = set(remove_segment_from_selected_segments)
    remove_with_downstream = get_all_downstream(_seeds, downstream_map)
    removed = remove_with_downstream & all_network_segs
    all_network_segs -= removed
    n_seeds_removed = len(_seeds & removed)
    n_downstream = len(removed) - n_seeds_removed
    print(
        f"  Removed {n_seeds_removed} seed segment(s) + {n_downstream} "
        f"downstream = {len(removed)} total removed"
    )
    print(f"  Final selected segment count: {len(all_network_segs)}")
else:
    print("  No segments removed in this step.")

# %% [markdown]
# ## Find HRUs connected to the stream network

# %% jupyter={"source_hidden": true}
# Subset segments to only those in the network
seg_gdf = seg_all[seg_all["seg_id"].astype(int).isin(all_network_segs)].copy()
print(f"Segments for map: {len(seg_gdf)}")

# Load HRUs â€” load all, then filter by segment membership
# Cannot use bbox because some HRUs draining to network segments may be outside segment extent
print("Loading all HRUs...")
hru_all = gpd.read_file(gpkg_path, layer="nhru")
hru_all = hru_all.to_crs(epsg=4326)

# Keep only HRUs whose hru_segment is in the network segment set
hru_gdf = hru_all[hru_all["hru_segment"].astype(int).isin(all_network_segs)].copy()
print(f"HRUs connected to network: {len(hru_gdf)}")

# Cast columns to native Python types for JSON serialization
hru_gdf["nat_hru_id"] = hru_gdf["nat_hru_id"].astype(int)
hru_gdf["hru_segment"] = hru_gdf["hru_segment"].astype(int)

seg_gdf["seg_id"] = seg_gdf["seg_id"].astype(int)
# to_segment is float (NaN marks outlets); keep as-is and format per-feature

# Drop Z/M coordinates that cause serialization issues
hru_gdf["geometry"] = hru_gdf["geometry"].apply(drop_z)
seg_gdf["geometry"] = seg_gdf["geometry"].apply(drop_z)

# Keep only the columns we need (GFv2 has no seg_id_nhm / nhm_id equivalent)
hru_gdf = hru_gdf[["nat_hru_id", "hru_segment", "geometry"]].copy()
seg_gdf = seg_gdf[["seg_id", "to_segment", "geometry"]].copy()

print(f"HRUs connected to network: {len(hru_gdf)}")
print(f"Segments for map: {len(seg_gdf)}")

# %% [markdown]
# ## Check for interior HRUs not connected to the network
# Dissolve selected HRUs into one boundary, then find any unselected HRUs
# whose centroid falls inside that boundary. These are "orphan" HRUs â€” typically
# in closed basins or routing to segments outside the traced network, but can also occur as small loop anomolies in HRU boundaries.

# %%
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
selected_hru_ids = set(hru_gdf["nat_hru_id"].astype(int))
unselected_hrus = hru_all[~hru_all["nat_hru_id"].astype(int).isin(selected_hru_ids)].copy()
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
    print(f"  HRU IDs: {interior_hrus['nat_hru_id'].tolist()[:20]}{'...' if len(interior_hrus) > 20 else ''}")
    print(f"  Their hru_segment values: {interior_hrus['hru_segment'].astype(int).unique().tolist()[:20]}")

    # Keep a copy for map display
    interior_hrus_for_map = interior_hrus.copy()
else:
    interior_hrus_for_map = None
    print(f"[OK] No interior HRUs missing from selection.")

# %% [markdown]
# ## Preview: Selected HRUs vs all HRUs in AOI buffer
# This map shows the selected HRUs (green) alongside all NHM GFv2 HRUs within
# the AOI buffer (gray) for context. The buffer is the same `context_buffer_km`
# set in the segment-preview section above.

# %% jupyter={"source_hidden": true}
# Load all HRUs within the AOI buffer for context
hru_context = hru_all.to_crs(epsg=4326)
buffer_geom_4326 = aoi_buffered_4326.geometry.iloc[0]
hru_context = hru_context[hru_context.geometry.centroid.within(buffer_geom_4326)].copy()
print(f"Context HRUs ({context_buffer_km} km buffer): {len(hru_context)}")

# Build map
m_hru_preview = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=8,
    tiles=None,
    width="100%",
    height="100%",
)

add_nhm_basemaps(m_hru_preview)
add_nhm_map_widgets(m_hru_preview)

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

# Context HRUs (all within the buffer) â€” gray, lightweight.
# Single non-interactive layer (no per-feature popup/highlight) so a large
# context polygon layer stays fast to draw.
if len(hru_context) > 0:
    hru_context_2d = hru_context[["geometry"]].copy()
    hru_context_2d["geometry"] = hru_context_2d["geometry"].apply(drop_z)
    folium.GeoJson(
        hru_context_2d,
        name=f"All HRUs ({context_buffer_km} km buffer)",
        style_function=lambda f: {
            "color": "gray",
            "weight": 0.5,
            "fillOpacity": 0.2,
            "fillColor": "lightgray",
        },
    ).add_to(m_hru_preview)

# Selected HRUs â€” green
selected_hru_features = []
for _, row in hru_gdf.iterrows():
    selected_hru_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "nat_hru_id": str(int(row["nat_hru_id"])),
            "hru_segment": str(int(row["hru_segment"])),
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
            fields=["nat_hru_id", "hru_segment"],
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
                "nat_hru_id": str(int(row["nat_hru_id"])),
                "hru_segment": str(int(row["hru_segment"])),
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
            fields=["nat_hru_id", "hru_segment"],
            aliases=["HRU ID:", "HRU Segment:"],
        ),
    ).add_to(m_hru_preview)

folium.LayerControl(collapsed=True, position="bottomright").add_to(m_hru_preview)

# Save the HRU preview map into this child's fabric folder and open it.
hru_preview_gis_dir = project_dir / "fabrics" / aoi_path.stem / "GIS"
hru_preview_gis_dir.mkdir(parents=True, exist_ok=True)
hru_preview_map_file = hru_preview_gis_dir / "hru_selection_preview.html"
m_hru_preview.save(str(hru_preview_map_file))
print(f"HRU preview map saved to: {hru_preview_map_file}")

import webbrowser
webbrowser.open(hru_preview_map_file.as_uri())

m_hru_preview

# %% [markdown]
# ### User decision: include or exclude orphan HRUs?
# The following lists allow you to control which interior (orphan) HRUs are
# included in or excluded from the final selection. By default, all orphan HRUs
# are placed in the **included** list. Move HRU IDs to `orphan_hrus_excluded`
# if you want to drop them from the model. NOTE: because the default is to
# include, the to_segment parameter will need to be changed later to "0" or to a segment_id in the subbasin. This notebook will default to "0".

# %%
# Edit these lists to control which orphan HRUs are included/excluded
if interior_hrus_for_map is not None:
    all_orphan_hru_ids = interior_hrus_for_map["nat_hru_id"].astype(int).tolist()
else:
    all_orphan_hru_ids = []

# DEFAULT: all orphans included. Move IDs to orphan_hrus_excluded to drop them.
orphan_hrus_excluded = []  # e.g. [97949, 97994]
orphan_hrus_included = [hid for hid in all_orphan_hru_ids if hid not in orphan_hrus_excluded]

print(f"Orphan HRUs included: {len(orphan_hrus_included)} â€” {orphan_hrus_included}")
print(f"Orphan HRUs excluded: {len(orphan_hrus_excluded)} â€” {orphan_hrus_excluded}")

# Apply: add included orphan HRUs to the selection
if orphan_hrus_included and interior_hrus_for_map is not None:
    include_mask = interior_hrus_for_map["nat_hru_id"].astype(int).isin(orphan_hrus_included)
    orphan_add = interior_hrus_for_map[include_mask][["nat_hru_id", "hru_segment", "geometry"]].copy()
    orphan_add["geometry"] = orphan_add["geometry"].apply(drop_z)
    hru_gdf = pd.concat([hru_gdf, orphan_add], ignore_index=True)
    hru_gdf["nat_hru_id"] = hru_gdf["nat_hru_id"].astype(int)
    hru_gdf["hru_segment"] = hru_gdf["hru_segment"].astype(int)
    print(f"  Total HRUs after adding included orphans: {len(hru_gdf)}")
else:
    print(f"  No orphan HRUs added to selection.")

# %% [markdown]
# ### User decision: add other HRUs?
# If there are additional HRUs you want to include in the selection (e.g., HRUs
# you identified from the HRU preview map that are not connected to the network
# but should be part of the model domain), add their `nat_hru_id` IDs to the list below.
#
# **Note:** When you add an HRU, the segment it flows to (`hru_segment`) is
# automatically added to the selected segments as well. Only the direct segment
# is added â€” NOT its full upstream network. This ensures the HRU has a valid
# routing target in the model without pulling in an entire additional watershed. (Parker says that we should better set this to "0" and not include the segment.)

# %%
# Edit this list to add any additional HRUs to the selection
add_other_hrus = []  # e.g. [97949, 97994, 76500]

if add_other_hrus:
    other_hrus_to_add = hru_all[hru_all["nat_hru_id"].astype(int).isin(add_other_hrus)].copy()
    other_hrus_to_add = other_hrus_to_add.to_crs(hru_gdf.crs)
    other_hrus_to_add["geometry"] = other_hrus_to_add["geometry"].apply(drop_z)
    other_hrus_to_add = other_hrus_to_add[["nat_hru_id", "hru_segment", "geometry"]].copy()
    hru_gdf = pd.concat([hru_gdf, other_hrus_to_add], ignore_index=True)
    hru_gdf["nat_hru_id"] = hru_gdf["nat_hru_id"].astype(int)
    hru_gdf["hru_segment"] = hru_gdf["hru_segment"].astype(int)
    # Remove duplicates in case any were already selected
    hru_gdf = hru_gdf.drop_duplicates(subset="nat_hru_id").reset_index(drop=True)

    # Also add the segments these HRUs flow to (direct segment only, not upstream)
    new_seg_ids = set(other_hrus_to_add["hru_segment"].astype(int).unique())
    segs_to_add = new_seg_ids - all_network_segs
    if segs_to_add:
        all_network_segs.update(segs_to_add)
        # Also add to seg_gdf
        new_segs_gdf = seg_all[seg_all["seg_id"].astype(int).isin(segs_to_add)].copy()
        new_segs_gdf = new_segs_gdf.to_crs(seg_gdf.crs)
        new_segs_gdf["seg_id"] = new_segs_gdf["seg_id"].astype(int)
        new_segs_gdf["geometry"] = new_segs_gdf["geometry"].apply(drop_z)
        new_segs_gdf = new_segs_gdf[["seg_id", "to_segment", "geometry"]]
        seg_gdf = pd.concat([seg_gdf, new_segs_gdf], ignore_index=True)
        seg_gdf = seg_gdf.drop_duplicates(subset="seg_id").reset_index(drop=True)
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
# (exclude hru_segment == 0, which marks HRUs that drain to no segment)
referenced_seg_ids = set(hru_gdf["hru_segment"].astype(int).unique()) - {0}
missing_seg_ids = referenced_seg_ids - all_network_segs

if missing_seg_ids:
    # Find those segments in the full segment layer
    outside_segs = seg_all[seg_all["seg_id"].astype(int).isin(missing_seg_ids)].copy()
    outside_segs = outside_segs.to_crs(epsg=4326)

    # Find which HRUs reference these missing segments
    hrus_with_missing_segs = hru_gdf[hru_gdf["hru_segment"].astype(int).isin(missing_seg_ids)]

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

# Basemaps + widgets (matching the other NHM notebooks)
add_nhm_basemaps(m)
add_nhm_map_widgets(m)

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
            "nat_hru_id": str(int(row["nat_hru_id"])),
            "hru_segment": str(int(row["hru_segment"])),
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
            fields=["nat_hru_id", "hru_segment"],
            aliases=["HRU ID:", "HRU Segment:"],
        ),
    ).add_to(m)

# Add segment layer
seg_features = []
for _, row in seg_gdf.iterrows():
    to_seg = row["to_segment"]
    to_seg_str = "outlet" if pd.isna(to_seg) else str(int(to_seg))
    seg_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "seg_id": str(int(row["seg_id"])),
            "to_segment": to_seg_str,
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
            fields=["seg_id", "to_segment"],
            aliases=["Segment ID:", "To Segment:"],
        ),
    ).add_to(m)

folium.LayerControl(collapsed=True, position="bottomright").add_to(m)

# Fit map to show all features
m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

# Save into this child's fabric folder, alongside the preview maps, and open it.
map_gis_dir = project_dir / "fabrics" / aoi_path.stem / "GIS"
map_gis_dir.mkdir(parents=True, exist_ok=True)
map_file = map_gis_dir / "subbasin_selection_map.html"
m.save(str(map_file))
print(f"\nMap saved to: {map_file}")
print(f"  Final selection: {len(seg_gdf)} segments, {len(hru_gdf)} HRUs")

import webbrowser
webbrowser.open(map_file.as_uri())

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
# - `npoi` â€” POIs whose `poi_segment` is in the selected segments
# - `domain` â€” dissolved HRU boundary (holes filled)

# %%
# Derive child model name from AOI filename
child_model_name = aoi_path.stem  # e.g. "Malheur_Lake" from "Malheur_Lake.shp"

# Create child model directory in the project's `fabrics` folder
child_hf_dir = project_dir / "fabrics" / child_model_name
child_hf_dir.mkdir(parents=True, exist_ok=True)
child_gis_dir = child_hf_dir / "GIS"
child_gis_dir.mkdir(parents=True, exist_ok=True)

# Output GeoPackage path
child_gpkg = child_gis_dir / "child_nhf_domain.gpkg"
print(f"Child model: {child_model_name}")
print(f"Output: {child_gpkg}")

# Remove any existing child GeoPackage so this run rebuilds it from scratch.
# The layer writes below use mode="a" (append), so without this a re-run would
# accumulate duplicate rows in nsegment/npoi/npoigages (e.g. 898 segments
# becoming 3592 across four runs), leaving stale POIs mixed with current ones.
if child_gpkg.exists():
    child_gpkg.unlink()
    print(f"  Removed existing {child_gpkg.name} (rebuilding fresh)")

# %%
hru_gdf.columns

# %%
# Get the set of selected segment IDs for POI filtering
selected_seg_ids = set(seg_gdf["seg_id"].astype(int))

# Write HRU layer

hru_gdf.to_file(child_gpkg, layer="nhru", driver="GPKG")
print(f"  Wrote nhru: {len(hru_gdf)} features")

# Write segment layer
seg_gdf.to_file(child_gpkg, layer="nsegment", driver="GPKG", mode="a")
print(f"  Wrote nsegment: {len(seg_gdf)} features")

# Load POIs (npoi). Attributes and the gage-segment correction are applied to
# the FULL npoi set BEFORE selecting by segment, so that domain membership is
# decided on each POI's corrected segment (see the selection step below).
print("  Loading npoi...")
pois_gdf = gpd.read_file(gpkg_path, layer="npoi")
pois_gdf = pois_gdf.to_crs(epsg=4326)
pois_gdf["poi_segment"] = pois_gdf["poi_segment"].astype(int)

# Attach the hydrologic-location attributes from the poi_data layer.
#
# IMPORTANT: join on hy_id, NOT nat_poi_id. nat_poi_id is NOT consistent between
# the npoi layer and the poi_data table -- the same physical POI can carry a
# different nat_poi_id in each (e.g. gage 09216562 is nat_poi_id 134361 in
# poi_data but 134320 in npoi). Joining on nat_poi_id therefore cross-wires POIs
# to the wrong poi_data rows, which was the source of the wrong segment/gage
# assignments. hy_id is the stable cross-reference shared by both layers.
#
# The npoi layer carries POI geometry and poi_segment, but the per-POI
# hydrologic-location classification lives in the separate poi_data table. A POI
# can have several poi_data rows, one per "type" (e.g. type_gages, type_huc12,
# type_nid), so a POI may legitimately be several types at once.
#
# We carry two attributes onto npoi:
#   - hl_reference : a ";"-delimited list of ALL distinct reference types for
#                    the POI (sorted; null only for POIs with no poi_data row),
#                    so the child geopackage faithfully preserves the parent
#                    classification.
#   - poi_gage_id  : the USGS gage id (hl_link) for POIs whose types include
#                    type_gages, else null. Downstream parameter building
#                    (poi_gage_id / poi_gage_segment / poi_type) uses this.
print("  Loading poi_data (hydrologic-location attributes)...")
poi_data = gpd.read_file(gpkg_path, layer="poi_data")
poi_data["hl_reference"] = poi_data["hl_reference"].astype(str)

# All distinct reference types per POI (by hy_id), joined into one
# ";"-delimited string.
ref_lists = (
    poi_data.groupby("hy_id")["hl_reference"]
    .apply(lambda s: ";".join(sorted(set(s.dropna()))))
)
pois_gdf["hl_reference"] = pois_gdf["hy_id"].map(ref_lists)

# Gage id: the hl_link of the type_gages row (keep first for the few POIs that
# carry two gage rows), keyed by hy_id.
gage_lookup = (
    poi_data[poi_data["hl_reference"] == "type_gages"]
    .assign(hl_link=lambda d: d["hl_link"].astype(str))
    .sort_values(["hy_id", "hl_link"])
    .drop_duplicates(subset="hy_id", keep="first")
    .set_index("hy_id")["hl_link"]
)
pois_gdf["poi_gage_id"] = pois_gdf["hy_id"].map(gage_lookup)

# Correct EVERY POI's segment from poi_data.segment_id (keyed by hy_id), then
# select by that corrected segment. The npoi layer's own poi_segment is
# unreliable -- a POI's marker can sit on a different segment than the POI is
# hydrologically assigned to (e.g. gage 09216562: npoi.poi_segment = 137108
# where the marker lands, but poi_data segment_id = 139501 is the true segment).
# poi_data.segment_id is the authoritative POI-to-segment reference.
#
# A hy_id can carry more than one distinct segment_id in poi_data, so keep-first
# is applied and the in-domain exceptions are alerted below. Selecting on the
# corrected segment -- BEFORE any geometry step -- is what makes domain
# membership correct: a POI belongs iff its true segment is one of the domain's
# selected segments, regardless of where its marker happens to plot.
poi_seg_lookup = (
    poi_data.dropna(subset=["segment_id"])
    .drop_duplicates(subset="hy_id", keep="first")
    .set_index("hy_id")["segment_id"]
)
pois_gdf["corrected_seg"] = pois_gdf["hy_id"].map(poi_seg_lookup)

# Alert on the two edge cases the user asked to be warned about, scoped to the
# selected domain so the message is actionable.
#
#   (1) POIs with NO poi_data row (so no corrected segment). These are omitted
#       from selection. If any such POI's RAW npoi poi_segment is in the domain,
#       it would previously have been included -- flag those.
_no_pd = pois_gdf["corrected_seg"].isna()
_no_pd_in_domain = pois_gdf[_no_pd & pois_gdf["poi_segment"].isin(selected_seg_ids)]
if len(_no_pd_in_domain):
    print(
        f"  ALERT: {len(_no_pd_in_domain)} POI(s) have no poi_data entry but a raw "
        "poi_segment inside the domain; they are OMITTED (no authoritative "
        f"segment). hy_id(s): {_no_pd_in_domain['hy_id'].tolist()[:20]}"
    )

#   (2) hy_id(s) that map to more than one distinct poi_data segment_id
#       (keep-first was used). Flag any whose chosen segment is in the domain.
_multi_ids = (
    poi_data.groupby("hy_id")["segment_id"].nunique().pipe(lambda s: s[s > 1]).index
)
_multi_in_domain = pois_gdf[
    pois_gdf["hy_id"].isin(_multi_ids)
    & pois_gdf["corrected_seg"].isin(selected_seg_ids)
]
if len(_multi_in_domain):
    print(
        f"  ALERT: {len(_multi_in_domain)} in-domain POI(s) have multiple poi_data "
        "segment_ids; kept the first. Verify the segment assignment. "
        f"hy_id(s): {_multi_in_domain['hy_id'].tolist()[:20]}"
    )

# Replace poi_segment with the corrected (authoritative) segment, then select.
# POIs without a corrected segment are dropped by the isin() against the
# selected set (NaN never matches).
pois_gdf["poi_segment"] = pois_gdf["corrected_seg"]
pois_selected = pois_gdf[pois_gdf["poi_segment"].isin(selected_seg_ids)].copy()
pois_selected["poi_segment"] = pois_selected["poi_segment"].astype(int)

n_gages = int(pois_selected["poi_gage_id"].notna().sum())
n_no_attr = int(pois_selected["hl_reference"].isna().sum())
print(
    f"  POIs in domain (by corrected segment): {len(pois_selected)} "
    f"({n_gages} are streamgages, {n_no_attr} have no poi_data attributes)"
)

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
# ## Build the npoigages layer (gage metadata + flow check)
#
# The gage POIs selected above are enriched here with the metadata and
# streamflow availability needed by the downstream parameter workflow
# (`gf_params_parse_gf2r2`), and written as a dedicated `npoigages` layer in the
# child GeoPackage. Doing it here means the gage set, its true WaterData
# locations, and its flow availability are all resolved once, in the one place
# that knows the corrected gage-to-segment assignment.
#
# Attributes written:
#   - poi_gage_id   : USGS gage id (from poi_data type_gages hl_link)
#   - nhm_seg_id    : the corrected national segment id (poi_data segment_id)
#   - poi_type      : 1 (gage POI)
#   - obs_check     : 1 if the gage has daily discharge in the model period, else 0
#   - poi_agency, poi_name, latitude, longitude, drainage_area,
#     drainage_area_contrib : metadata from find_missing_gage_info
#
# Geometry is the gage's TRUE WaterData location (built from the fetched
# latitude/longitude), not the npoi marker point. Gages with obs_check == 0 are
# dropped from THIS layer only; the npoi layer written above is unchanged.
#
# Note: the child-local 1..N segment_id is NOT added here; it is derived in
# gf_params_parse_gf2r2 from this layer's nhm_seg_id via that notebook's segment
# mapping.

# %%
# Flow-availability check period (matches gf_params_parse_gf2r2).
_FLOW_START = "1979-10-01"
_FLOW_END = "2025-09-30"

gage_pois = pois_selected[pois_selected["poi_gage_id"].notna()].copy()
gage_pois["poi_gage_id"] = gage_pois["poi_gage_id"].astype(str)
print(f"  Building npoigages layer for {len(gage_pois)} gage POIs...")

if len(gage_pois) == 0:
    print("  No gage POIs in domain; skipping npoigages layer.")
else:
    gage_ids = gage_pois["poi_gage_id"].unique().tolist()

    # Resolve bare gage numbers to agency-prefixed WaterData ids (USGS-...).
    loc_df, _ = waterdata.get_monitoring_locations(
        monitoring_location_number=gage_ids,
        skip_geometry=True,
    )
    id_map = dict(
        zip(
            loc_df["monitoring_location_number"].astype(str),
            loc_df["monitoring_location_id"].astype(str),
        )
    )
    mon_ids = [id_map[s] for s in gage_ids if s in id_map]
    not_found = [s for s in gage_ids if s not in id_map]
    if not_found:
        print(f"    {len(not_found)} gage(s) unknown to WaterData: {not_found[:10]}")

    # obs_check: 1 if the gage returned any daily discharge in the period, else 0.
    flow_result = fetch_daily_discharge_batch(
        monitoring_location_ids=mon_ids,
        start_date=_FLOW_START,
        end_date=_FLOW_END,
    )
    _missing = set(flow_result.missing_ids)
    has_flow_bare = {
        m.split("-", 1)[1] for m in mon_ids if m not in _missing
    }
    gage_pois["obs_check"] = (
        gage_pois["poi_gage_id"].isin(has_flow_bare).astype(int)
    )
    print(
        f"    obs_check: {int(gage_pois['obs_check'].sum())} of {len(gage_pois)} "
        f"gage(s) have flow in {_FLOW_START}..{_FLOW_END}"
        + (f"; fetch error={flow_result.error}" if flow_result.error else "")
    )

    # Metadata (poi_agency, poi_name, latitude, longitude, drainage_area,
    # drainage_area_contrib) from the cascading resource/NLDI/WaterData lookup.
    gage_info_df = find_missing_gage_info(
        root_dir,
        child_hf_dir,
        gage_ids,
        child_hf_dir / "resource_gages.csv",
    )

    # Assemble: corrected segment + poi_type + obs_check, joined to metadata.
    npoigages_df = gage_pois[["poi_gage_id", "poi_segment", "obs_check"]].rename(
        columns={"poi_segment": "nhm_seg_id"}
    )
    npoigages_df["poi_type"] = 1
    npoigages_df = npoigages_df.merge(
        gage_info_df.drop_duplicates("poi_gage_id"), on="poi_gage_id", how="left"
    )

    # Geometry = TRUE gage location from the fetched lat/lon.
    npoigages_gdf = gpd.GeoDataFrame(
        npoigages_df,
        geometry=gpd.points_from_xy(
            npoigages_df["longitude"], npoigages_df["latitude"]
        ),
        crs="EPSG:4326",
    )

    # Drop gages with no flow in the period from the npoigages layer only.
    _n_before = len(npoigages_gdf)
    npoigages_gdf = npoigages_gdf[npoigages_gdf["obs_check"] == 1].copy()
    print(
        f"    Dropped {_n_before - len(npoigages_gdf)} gage(s) with obs_check == 0; "
        f"{len(npoigages_gdf)} remain."
    )

    npoigages_gdf.nhm_seg_id = npoigages_gdf.nhm_seg_id.astype(int)
    npoigages_gdf = npoigages_gdf.sort_values("nhm_seg_id")

    # --- Validation checks (warnings only; nothing is dropped here) ---
    #
    # Check 1 (segment membership): every gage's corrected nhm_seg_id should be
    # one of the segments selected for this domain. This is an invariant now
    # that gages are selected by their corrected segment, so a violation points
    # to a regression in the selection/correction logic.
    _bad_seg = npoigages_gdf[~npoigages_gdf["nhm_seg_id"].isin(selected_seg_ids)]
    if len(_bad_seg):
        print(
            f"  WARNING: {len(_bad_seg)} npoigages gage(s) have an nhm_seg_id "
            "NOT in the domain's selected segments:"
        )
        for _, _r in _bad_seg.iterrows():
            print(f"      poi_gage_id={_r['poi_gage_id']} nhm_seg_id={_r['nhm_seg_id']}")
    else:
        print("  Check: all npoigages gages are on segments inside the domain. OK")

    # Check 2 (spatial containment): each gage's TRUE location should fall within
    # the dissolved HRU domain polygon. Gages sit on streams at HRU edges, so a
    # point just outside the boundary is common and not necessarily an error --
    # hence a warning that reports the distance (meters) from the AOI boundary.
    # Distances are computed in EPSG:5070 (meters), the fabric's projected CRS.
    _dom_5070 = aoi_dissolved.to_crs(epsg=5070).union_all()
    _pts_5070 = npoigages_gdf.to_crs(epsg=5070)
    _outside = ~_pts_5070.geometry.within(_dom_5070)
    _n_outside = int(_outside.sum())
    # Persist the containment result so the final map can color out-of-domain
    # gages differently. 1 = inside the dissolved HRU domain, 0 = outside.
    npoigages_gdf["in_aoi"] = (~_outside.to_numpy()).astype(int)
    if _n_outside:
        _boundary = _dom_5070.boundary
        print(
            f"  WARNING: {_n_outside} npoigages gage(s) fall OUTSIDE the dissolved "
            "HRU domain (distance from AOI boundary):"
        )
        for _idx in _pts_5070.index[_outside]:
            _dist = _pts_5070.geometry.loc[_idx].distance(_dom_5070)
            _gid = npoigages_gdf.loc[_idx, "poi_gage_id"]
            _seg = npoigages_gdf.loc[_idx, "nhm_seg_id"]
            print(
                f"      poi_gage_id={_gid} nhm_seg_id={_seg} "
                f"distance={_dist:,.1f} m outside"
            )
    else:
        print("  Check: all npoigages gages fall inside the dissolved HRU domain. OK")

    npoigages_gdf.to_file(child_gpkg, layer="npoigages", driver="GPKG", mode="a")
    print(f"  Wrote npoigages: {len(npoigages_gdf)} features")

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

add_nhm_basemaps(m_child)
add_nhm_map_widgets(m_child)

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
            "nat_hru_id": str(int(row["nat_hru_id"])),
            "hru_segment": str(int(row["hru_segment"])),
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
            fields=["nat_hru_id", "hru_segment"],
            aliases=["HRU ID:", "HRU Segment:"],
        ),
    ).add_to(m_child)

# Segments (blue)
child_seg_features = []
for _, row in seg_gdf.iterrows():
    to_seg = row["to_segment"]
    to_seg_str = "outlet" if pd.isna(to_seg) else str(int(to_seg))
    child_seg_features.append({
        "type": "Feature",
        "geometry": geom_mapping(drop_z(row["geometry"])),
        "properties": {
            "seg_id": str(int(row["seg_id"])),
            "to_segment": to_seg_str,
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
            fields=["seg_id", "to_segment"],
            aliases=["Segment ID:", "To Segment:"],
        ),
    ).add_to(m_child)

# Gage POIs (npoigages layer), plotted at their TRUE WaterData location.
# Color-coded by containment: gages inside the dissolved HRU domain are red;
# gages whose true location falls OUTSIDE the domain are orange, so they stand
# out for review (their segment is in-domain but the point plots outside).
if "npoigages" in child_layers:
    npoigages_map_gdf = gpd.read_file(child_gpkg, layer="npoigages").to_crs(epsg=4326)
    _n_out_map = int((npoigages_map_gdf.get("in_aoi", 1) == 0).sum())

    # Two named, toggleable groups so the out-of-domain gages can be isolated in
    # the layer control: inside = red, outside = orange.
    fg_gages_in = folium.FeatureGroup(name="npoigages (inside AOI)", show=True)
    fg_gages_out = folium.FeatureGroup(name="npoigages (outside AOI)", show=True)
    for _, row in npoigages_map_gdf.iterrows():
        inside = int(row.get("in_aoi", 1)) == 1
        marker_color = "red" if inside else "orange"
        where_txt = "inside domain" if inside else "OUTSIDE domain"
        _name = row.get("poi_name")
        _name = "" if (_name is None or (isinstance(_name, float) and pd.isna(_name))) else str(_name)
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=6,
            color=marker_color,
            fill=True,
            fill_color=marker_color,
            fill_opacity=0.85,
            tooltip=f"{row['poi_gage_id']} — {_name}" if _name else f"{row['poi_gage_id']}",
            popup=(
                f"gage: {row['poi_gage_id']}<br>"
                f"name: {_name}<br>"
                f"nhm_seg_id: {int(row['nhm_seg_id'])}<br>"
                f"{where_txt}"
            ),
        ).add_to(fg_gages_in if inside else fg_gages_out)
    fg_gages_in.add_to(m_child)
    fg_gages_out.add_to(m_child)
    if _n_out_map:
        print(
            f"  Map: {_n_out_map} gage(s) drawn in orange (true location outside "
            "the dissolved HRU domain)."
        )

# npoi layer (all selected POIs, incl. non-gage), as a separate toggleable group
# drawn at the npoi marker location. Off by default to keep the map uncluttered.
if "npoi" in child_layers:
    npoi_map_gdf = gpd.read_file(child_gpkg, layer="npoi").to_crs(epsg=4326)
    fg_npoi = folium.FeatureGroup(name="npoi (all POIs)", show=False)
    for _, row in npoi_map_gdf.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        _gid = row.get("poi_gage_id")
        _gid = "" if (_gid is None or (isinstance(_gid, float) and pd.isna(_gid))) else str(_gid)
        _ref = row.get("hl_reference")
        _ref = "" if (_ref is None or (isinstance(_ref, float) and pd.isna(_ref))) else str(_ref)
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=4,
            color="purple",
            fill=True,
            fill_color="purple",
            fill_opacity=0.6,
            tooltip=(f"POI {_gid}".strip() if _gid else "POI"),
            popup=(
                f"poi_segment: {int(row['poi_segment'])}<br>"
                f"gage: {_gid}<br>"
                f"hl_reference: {_ref}"
            ),
        ).add_to(fg_npoi)
    fg_npoi.add_to(m_child)

folium.LayerControl(collapsed=True, position="bottomright").add_to(m_child)
m_child.fit_bounds([[child_bounds[1], child_bounds[0]], [child_bounds[3], child_bounds[2]]])

# Save
child_map_file = child_gis_dir / f"{child_model_name}_map.html"
m_child.save(str(child_map_file))
print(f"Map saved to: {child_map_file}")
m_child

# %%
