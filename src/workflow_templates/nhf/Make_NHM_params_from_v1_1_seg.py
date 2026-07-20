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

# %% [markdown]
# # Extract NHM v1.1 Segment Parameters
# This notebook extracts segment-dimensioned parameters from the NHM v1.1 parameter database
# and transfers them to v2 segments via spatial overlay.

# %%
import pandas as pd
import pathlib as pl
import geopandas as gpd
import numpy as np

# %% [markdown]
# ## Load mann_n parameter from CONUS CSV

# %%
mann_n_filepath = pl.Path(
    r"D:\version1_1_params\paramdb_v1.1_gridmet_CONUS-master\mann_n.csv"
)

mann_n_df = pd.read_csv(mann_n_filepath)
mann_n_df.rename(columns={"$id": "nsegment_v1_1"}, inplace=True)

print(f"Loaded {len(mann_n_df)} segment parameter values")
print(f"mann_n range: {mann_n_df['mann_n'].min():.6f} - {mann_n_df['mann_n'].max():.6f}")
mann_n_df.head()

# %% [markdown]
# ## Load v1.1 segment geospatial data from GDB

# %%
v1_gdb_path = pl.Path(
    r"D:\version1_1_params\GFv1.1.gdb"
)

seg_gdf = gpd.read_file(v1_gdb_path, layer="nsegment_v1_1").to_crs(epsg=4326)
print(f"Loaded {len(seg_gdf)} v1.1 segments")
print(seg_gdf.columns.tolist())
seg_gdf.head()

# %% [markdown]
# ## Merge parameter data with v1.1 segment geometry

# %%
seg_mann_gdf = seg_gdf.merge(mann_n_df, on="nsegment_v1_1")
print(f"Merged GeoDataFrame: {len(seg_mann_gdf)} segments")
seg_mann_gdf.head()

# %%
print(f"GDB segments: {len(seg_gdf)}")
print(f"CSV parameters: {len(mann_n_df)}")
print(f"Merged result: {len(seg_mann_gdf)}")
print(f"Any nulls in mann_n? {seg_mann_gdf['mann_n'].isna().sum()}")

# %%

# %% [markdown]
# ## Load v2 segment geospatial data

# %%
v2_gpkg_path = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\GIS\model_layers.gpkg"
)

seg_v2_gdf = gpd.read_file(v2_gpkg_path, layer="nsegment").to_crs(epsg=4326)
print(f"Loaded {len(seg_v2_gdf)} v2 segments")
print(seg_v2_gdf.columns.tolist())
seg_v2_gdf.head()

# %%

# %% [markdown]
# ## Transfer mann_n from v1.1 to v2 segments (nearest neighbor)
# For each v2 segment, find the nearest v1.1 segment and assign its mann_n value.
# We also compute the distance so we can flag v2 segments that are far from any
# v1.1 counterpart — those may need manual review.

# %%
# Reproject to a projected CRS for accurate distance calculations
crs_proj = "EPSG:5070"  # NAD83 / Conus Albers (meters)

v1_seg_proj = seg_mann_gdf.to_crs(crs_proj)
v2_seg_proj = seg_v2_gdf.to_crs(crs_proj)

# Use midpoints of v2 segments for the nearest join (faster and more stable than full line geometry)
v2_midpoints = v2_seg_proj.copy()
v2_midpoints["geometry"] = v2_midpoints.geometry.interpolate(0.5, normalized=True)

# Spatial join: find nearest v1.1 segment for each v2 midpoint
best_match_seg = gpd.sjoin_nearest(
    v2_midpoints[["nhm_seg_id", "geometry"]].rename(columns={"nhm_seg_id": "nhm_seg_v2"}),
    v1_seg_proj[["nsegment_v1_1", "mann_n", "geometry"]].rename(columns={"nsegment_v1_1": "nseg_v1_1"}),
    how="left",
    distance_col="distance_m",
).drop(columns=["index_right"])

print(f"Matched {best_match_seg['mann_n'].notna().sum()} of {len(seg_v2_gdf)} v2 segments")
print(f"Distance stats (meters):")
print(best_match_seg["distance_m"].describe())

# %%
# Flag segments where the nearest v1.1 segment is far away (e.g., > 500m)
distance_threshold = 200  # meters
far_segments = best_match_seg[best_match_seg["distance_m"] > distance_threshold]
close_segments = best_match_seg[best_match_seg["distance_m"] <= distance_threshold]

# Save a copy before upstream-count correction for comparison
best_match_seg_original = best_match_seg.copy()

print(f"\nSegments within {distance_threshold}m of a v1.1 match: {len(close_segments)}")
print(f"Segments farther than {distance_threshold}m (may need review): {len(far_segments)}")

if not far_segments.empty:
    print(f"\nFar segments nhm_seg_v2 IDs (first 20): {far_segments['nhm_seg_v2'].head(20).tolist()}")

# %%

# %% [markdown]
# ## Map v1.1, v2 (nearest only), and v2 (upstream-count corrected) for comparison

# %%
import folium
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from branca.colormap import LinearColormap

# Build a shared colormap for all layers
vmin = min(seg_mann_gdf["mann_n"].min(), best_match_seg["mann_n"].min())
vmax = max(seg_mann_gdf["mann_n"].max(), best_match_seg["mann_n"].max())

colormap = LinearColormap(
    colors=["blue", "cyan", "yellow", "red"],
    vmin=vmin,
    vmax=vmax,
    caption="mann_n",
)

# Center map on v2 domain
bounds = seg_v2_gdf.total_bounds
center_lat = (bounds[1] + bounds[3]) / 2
center_lon = (bounds[0] + bounds[2]) / 2

m = folium.Map(location=[center_lat, center_lon], zoom_start=8, tiles="CartoDB positron")

# --- Layer 1: v1.1 segments (clipped to v2 extent) ---
v2_bounds = seg_v2_gdf.total_bounds
v1_clipped = seg_mann_gdf.cx[v2_bounds[0]:v2_bounds[2], v2_bounds[1]:v2_bounds[3]]

v1_style = lambda feature: {
    "color": colormap(feature["properties"]["mann_n"]),
    "weight": 2,
    "opacity": 0.8,
}

folium.GeoJson(
    v1_clipped[["nsegment_v1_1", "mann_n", "geometry"]].to_json(),
    name="v1.1 segments (mann_n)",
    style_function=v1_style,
    tooltip=folium.GeoJsonTooltip(fields=["nsegment_v1_1", "mann_n"]),
    show=True,
).add_to(m)

# --- Layer 2: v2 segments (nearest neighbor only, before upstream correction) ---
seg_v2_nearest = seg_v2_gdf.merge(
    best_match_seg_original[["nhm_seg_v2", "mann_n"]],
    left_on="nhm_seg_id",
    right_on="nhm_seg_v2",
    how="left",
).drop(columns=["nhm_seg_v2"])

v2_style = lambda feature: {
    "color": colormap(feature["properties"]["mann_n"]) if feature["properties"]["mann_n"] is not None else "gray",
    "weight": 3,
    "opacity": 0.8,
}

folium.GeoJson(
    seg_v2_nearest[["nhm_seg_id", "mann_n", "geometry"]].to_json(),
    name="v2 nearest only (before correction)",
    style_function=v2_style,
    tooltip=folium.GeoJsonTooltip(fields=["nhm_seg_id", "mann_n"]),
    show=False,
).add_to(m)

# --- Layer 3: v2 segments (after upstream-count correction) ---
seg_v2_corrected = seg_v2_gdf.merge(
    best_match_seg[["nhm_seg_v2", "mann_n"]],
    left_on="nhm_seg_id",
    right_on="nhm_seg_v2",
    how="left",
).drop(columns=["nhm_seg_v2"])

v2_corrected_style = lambda feature: {
    "color": colormap(feature["properties"]["mann_n"]) if feature["properties"]["mann_n"] is not None else "gray",
    "weight": 3,
    "opacity": 0.8,
}

folium.GeoJson(
    seg_v2_corrected[["nhm_seg_id", "mann_n", "geometry"]].to_json(),
    name="v2 upstream-count corrected",
    style_function=v2_corrected_style,
    tooltip=folium.GeoJsonTooltip(fields=["nhm_seg_id", "mann_n"]),
    show=False,
).add_to(m)

# Add colormap and layer control
colormap.add_to(m)
folium.LayerControl().add_to(m)
m

# %%
print(seg_v2_gdf.columns.tolist())

# %%

# %% [markdown]
# ## Assign mann_n to far v2 segments using stream order matching
# For v2 segments far from any v1.1 counterpart, find the nearest v1.1 segment
# that has the same number of upstream contributing segments (proxy for stream size).

# %%
from collections import defaultdict, deque

def compute_upstream_count(seg_ids, toseg_values):
    """
    Given segment IDs and their downstream targets (tosegment),
    compute how many segments are upstream of each segment.
    """
    inflow = defaultdict(list)
    for seg_id, to_seg in zip(seg_ids, toseg_values):
        if to_seg != 0:
            inflow[to_seg].append(seg_id)

    upstream_count = {}
    for seg_id in seg_ids:
        count = 0
        queue = deque(inflow.get(seg_id, []))
        visited = set()
        while queue:
            us = queue.popleft()
            if us in visited:
                continue
            visited.add(us)
            count += 1
            queue.extend(inflow.get(us, []))
        upstream_count[seg_id] = count

    return upstream_count

# Compute upstream count for v1.1
v1_seg_ids = seg_gdf["nsegment_v1_1"].values
v1_toseg = seg_gdf["tosegment_v1_1"].values
v1_upstream_count = compute_upstream_count(v1_seg_ids, v1_toseg)
seg_mann_gdf["upstream_count"] = seg_mann_gdf["nsegment_v1_1"].map(v1_upstream_count)

print(f"v1.1 upstream count range: {seg_mann_gdf['upstream_count'].min()} - {seg_mann_gdf['upstream_count'].max()}")

# %%
# Compute upstream count for v2
v2_seg_ids = seg_v2_gdf["nhm_seg_id"].values
v2_toseg = seg_v2_gdf["to_nhm_seg"].fillna(0).astype(int).values
v2_upstream_count = compute_upstream_count(v2_seg_ids, v2_toseg)
seg_v2_gdf["upstream_count"] = seg_v2_gdf["nhm_seg_id"].map(v2_upstream_count)

print(f"v2 upstream count range: {seg_v2_gdf['upstream_count'].min()} - {seg_v2_gdf['upstream_count'].max()}")

# %%
# For far v2 segments, find nearest v1.1 segment with matching upstream count
if len(far_segments) > 0:
    # Get far v2 segment IDs and their upstream counts
    far_v2_ids = far_segments["nhm_seg_v2"].tolist()
    far_v2_gdf = v2_seg_proj[v2_seg_proj["nhm_seg_id"].isin(far_v2_ids)].copy()
    far_v2_gdf["upstream_count"] = far_v2_gdf["nhm_seg_id"].map(v2_upstream_count)
    far_v2_gdf["geometry"] = far_v2_gdf.geometry.interpolate(0.5, normalized=True)  # midpoints

    # For each unique upstream_count in far segments, find nearest v1.1 with same count
    v1_proj_with_count = v1_seg_proj.copy()
    v1_proj_with_count["upstream_count"] = v1_proj_with_count["nsegment_v1_1"].map(v1_upstream_count)

    reassigned = []
    for uc in far_v2_gdf["upstream_count"].unique():
        far_subset = far_v2_gdf[far_v2_gdf["upstream_count"] == uc]
        v1_subset = v1_proj_with_count[v1_proj_with_count["upstream_count"] == uc]

        if v1_subset.empty:
            # No exact match — try +/- 5
            v1_subset = v1_proj_with_count[
                v1_proj_with_count["upstream_count"].between(uc - 5, uc + 5)
            ]

        if not v1_subset.empty:
            matched = gpd.sjoin_nearest(
                far_subset[["nhm_seg_id", "geometry"]].rename(columns={"nhm_seg_id": "nhm_seg_v2"}),
                v1_subset[["nsegment_v1_1", "mann_n", "geometry"]].rename(columns={"nsegment_v1_1": "nseg_v1_1"}),
                how="left",
                distance_col="distance_m",
            ).drop(columns=["index_right", "geometry"])
            reassigned.append(matched)

    if reassigned:
        reassigned_df = pd.concat(reassigned, ignore_index=True)
        print(f"Reassigned {len(reassigned_df)} far segments using upstream count matching")
        print(reassigned_df[["nhm_seg_v2", "nseg_v1_1", "mann_n", "distance_m"]].head(10))

        # Update best_match_seg with reassigned values
        for _, row in reassigned_df.iterrows():
            mask = best_match_seg["nhm_seg_v2"] == row["nhm_seg_v2"]
            best_match_seg.loc[mask, "mann_n"] = row["mann_n"]
            best_match_seg.loc[mask, "distance_m"] = row["distance_m"]

        print(f"\nUpdated best_match_seg. Remaining nulls: {best_match_seg['mann_n'].isna().sum()}")
    else:
        print("No reassignments could be made.")
else:
    print("No far segments to reassign.")

# %%
