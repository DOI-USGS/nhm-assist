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
# # Create Segment Parameters
#
# This notebook computes segment-dimensioned parameters for the OHM v2 stream network
# by transferring and computing values from the NHDPlus reference flowlines and 
# NHD waterbody polygons.
#
# ## Parameters produced:
#
# | Parameter | Description | Method | Expected Range | Default |
# |-----------|-------------|--------|---------------|---------|
# | `seg_slope` | Surface slope of each segment as approximation for bed slope of stream | Length-weighted average of overlapping NHDPlus ref flowline slopes | 0.00001 – 1.0 | 0.0001 |
# | `mann_n` | Manning's roughness coefficient | Computed as `0.1 * seg_slope^0.18` | 0.01 – 0.2 | 0.04 |
# | `seg_width` | Bankfull channel width (m) | Length-weighted average of BANKFULL_CONUS dataset | 0.5 – 500+ | 5.0 |
# | `seg_depth` | Bankfull channel depth (m) | Length-weighted average of BANKFULL_CONUS dataset | 0.1 – 20+ | 1.0 |
# | `x_coef` | Muskingum routing weighting factor (attenuation of flow wave); set to 0.0 for reservoirs, diversions, and segments flowing out of the basin | Default 0.2; set to 0.0 for waterbody and outlet segments | 0.0 – 0.5 | 0.2 |
# | `segment_type` | Segment classification | 0=segment, 1=headwater, 2=lake, 5=outbound | 0 – 11 (integer) | 0 |
#
# ## Data sources:
# - **Reference flowlines**: `D:\reference_flowline.gpkg` (NHDPlusV2 with slope and roughness attributes)
# - **Bankfull geometry**: `D:\BANKFULL_CONUS\BANKFULL_CONUS.txt` (USGS Select Attributes for NHDPlus v2.1)
# - **Waterbodies**: `main_waterbodies.shp` (NHD waterbody polygons for lake/reservoir identification)
# - **OHM segments**: `model_layers.gpkg` nsegment layer
# - **Routing**: `tosegment.csv` from param_source_files
#
# ## Workflow:
# 1. Load v2 (OHM) segments and reference flowlines
# 2. Spatial overlay with buffer to find co-linear ref flowlines per OHM segment
# 3. Filter by overlap length (≥1% of v2 segment length) and exclude fill values
# 4. Extract COMID crosswalk and visualize coverage
# 5. Compute length-weighted slope → derive mann_n
# 6. Identify waterbody segments (>50% inside NHD waterbody polygons)
# 7. Compute bankfull width/depth from BANKFULL_CONUS via COMID lookup
# 8. Compute x_coef and segment_type
# 9. Write all parameters as paramdb-format CSVs
#
# Reference: PRMS parameter definitions from pywatershed
# (https://pywatershed.readthedocs.io) and pyPRMS metadata.
# Parameter definitions from: Regan, R.S., Markstrom, S.L., LaFontaine, J.H.,
# and Norton, P.A., 2025, The precipitation-runoff modeling system, software
# release version 6.0.0: U.S. Geological Survey Software Release,
# https://doi.org/10.5066/P97032NH.
#
# This notebook transfers slope from the NHDPlus reference
# flowlines to the OHM v2 segment network via spatial overlay and computes
# Manning's n from slope.

# %%
import pandas as pd
import numpy as np
import pathlib as pl
import geopandas as gpd
from shapely.ops import substring

# %% [markdown]
# ## Define paths

# %%
ref_flowline_path = pl.Path(r"D:\reference_flowline.gpkg")
v2_gpkg_path = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\GIS\model_layers.gpkg"
)
out_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files")
out_dir.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## Load v2 (OHM) segments

# %%
seg_v2_gdf = gpd.read_file(v2_gpkg_path, layer="nsegment")
print(f"Loaded {len(seg_v2_gdf)} v2 segments, CRS: {seg_v2_gdf.crs}")
print(f"Columns: {seg_v2_gdf.columns.tolist()}")
seg_v2_gdf.head()

# %% [markdown]
# ## Load reference flowlines (clipped to v2 extent)

# %%
# Read only flowlines within the v2 bounding box for performance
v2_bounds = seg_v2_gdf.to_crs(epsg=4326).total_bounds  # [minx, miny, maxx, maxy]
ref_gdf = gpd.read_file(
    ref_flowline_path,
    layer="reference_flowlines",
    bbox=tuple(v2_bounds),
)
print(f"Loaded {len(ref_gdf)} reference flowlines within v2 extent")
print(f"CRS: {ref_gdf.crs}")
print(f"Columns with slope: slope={ref_gdf['slope'].notna().sum()}")

# %% [markdown]
# ## Reproject to a common projected CRS

# %%
crs_proj = "EPSG:5070"
seg_v2_proj = seg_v2_gdf.to_crs(crs_proj)
ref_proj = ref_gdf.to_crs(crs_proj)

# %% [markdown]
# ## Spatial overlay: find reference flowlines that substantially overlap each v2 segment
# We buffer v2 segments slightly and require overlap of more than just a single
# vertex (minimum overlap length) to avoid averaging in perpendicular tributaries. Note, we should move this processing to find a comid for each derived hydrofabric segment to the original workflow for splitting, or at least, make it a pre-processing step to bring the GIS inline prior to this workflow.

# %%
# Buffer v2 segments by a small distance to catch nearby ref flowlines
buffer_distance = 50  # meters
seg_v2_buffered = seg_v2_proj.copy()
seg_v2_buffered["geometry"] = seg_v2_proj.geometry.buffer(buffer_distance)

# Spatial join: find ref flowlines that intersect each buffered v2 segment
joined = gpd.sjoin(
    ref_proj[["COMID", "slope", "LENGTHKM", "geometry"]],
    seg_v2_buffered[["model_seg_idx", "geometry"]],
    how="inner",
    predicate="intersects",
)
print(f"Raw spatial join: {len(joined)} ref-to-v2 matches")

# %%
# Filter: require substantial overlap (not just touching at a point)
# Compute the actual intersection length between each ref flowline and the v2 segment
# min_overlap_length is 1% of each v2 segment's total length

overlap_lengths = []
for idx, row in joined.iterrows():
    ref_geom = ref_proj.loc[idx, "geometry"]
    v2_seg_geom = seg_v2_proj.loc[
        seg_v2_proj["model_seg_idx"] == row["model_seg_idx"], "geometry"
    ].values[0]
    # Compute length of ref flowline within the v2 segment buffer
    intersection = ref_geom.intersection(v2_seg_geom.buffer(buffer_distance))
    overlap_lengths.append(intersection.length)

joined["overlap_length"] = overlap_lengths

# Compute 1% of each v2 segment's length as the minimum overlap threshold
v2_seg_lengths = seg_v2_proj.set_index("model_seg_idx")["geometry"].length
joined["v2_seg_length"] = joined["model_seg_idx"].map(v2_seg_lengths)
joined["min_overlap"] = joined["v2_seg_length"] * 0.01

# Keep only matches where overlap >= 1% of the v2 segment length
joined_filtered = joined[joined["overlap_length"] >= joined["min_overlap"]].copy()

# Remove fill values for slope (-9998)
joined_filtered = joined_filtered[joined_filtered["slope"] != -9998]

print(f"After filtering (>= 5% of v2 segment length, excluding slope=-9998): {len(joined_filtered)} matches")

# %%
# Save COMID list and weights per v2 segment
seg_total_len = joined_filtered.groupby("model_seg_idx")["overlap_length"].transform("sum")
joined_filtered["weight"] = joined_filtered["overlap_length"] / seg_total_len

comid_lists = joined_filtered.groupby("model_seg_idx").apply(
    lambda g: pd.Series({
        "comid_list": g["COMID"].tolist(),
        "weight_list": g["weight"].round(4).tolist(),
    })
).reset_index()

print(f"Built COMID/weight lists for {len(comid_lists)} v2 segments")
comid_lists.head()


# %% [markdown]
# ## Extract COMID list per OHM segment
# For each OHM segment, list the ref flowline COMIDs that overlap it
# (filtered to only those with >= 100m overlap, excluding tributaries).

# %%
# Build a table of COMIDs and their overlap with each OHM segment
comid_per_seg = joined_filtered[["model_seg_idx", "COMID", "overlap_length"]].copy()
comid_per_seg["COMID"] = comid_per_seg["COMID"].astype(int)

# Compute each COMID's fraction of the OHM segment's total overlapping length
seg_total_overlap = comid_per_seg.groupby("model_seg_idx")["overlap_length"].transform("sum")
comid_per_seg["overlap_frac"] = comid_per_seg["overlap_length"] / seg_total_overlap

# Sort by segment then by overlap (largest first)
comid_per_seg = comid_per_seg.sort_values(
    ["model_seg_idx", "overlap_length"], ascending=[True, False]
).reset_index(drop=True)

print(f"COMID-to-OHM-segment table: {len(comid_per_seg)} rows")
print(f"Unique OHM segments with COMIDs: {comid_per_seg['model_seg_idx'].nunique()}")

segs_without_comids = set(seg_v2_gdf["model_seg_idx"]) - set(comid_per_seg["model_seg_idx"])
if segs_without_comids:
    print(f"WARNING: {len(segs_without_comids)} OHM segments have no matching COMIDs")
else:
    print("All OHM segments have at least one matching COMID")
comid_per_seg.head(10)

# %%
# Save COMID crosswalk
comid_per_seg.to_csv(out_dir / "ohm_seg_to_comid_crosswalk.csv", index=False)
print(f"Saved COMID crosswalk to {out_dir / 'ohm_seg_to_comid_crosswalk.csv'}")

# %% [markdown]
# ## Map: v2 segments with/without COMID associations

# %% jupyter={"source_hidden": true}
# import folium

# # Determine which v2 segments have COMIDs
# segs_with_comids = set(comid_per_seg["model_seg_idx"])
# seg_v2_4326 = seg_v2_gdf.to_crs(epsg=4326).copy()

# # Build COMID list per segment for popup
# comid_lookup = comid_per_seg.groupby("model_seg_idx")["COMID"].apply(list).to_dict()
# seg_v2_4326["has_comids"] = seg_v2_4326["model_seg_idx"].isin(segs_with_comids)
# seg_v2_4326["comid_list"] = seg_v2_4326["model_seg_idx"].map(
#     lambda x: str(comid_lookup.get(x, []))
# )

# if segs_without_comids:
#     print(f"WARNING: {len(segs_without_comids)} v2 segments have NO associated COMIDs from the ref fabric.")
#     print(f"  model_seg_idx values (first 20): {sorted(list(segs_without_comids))[:20]}")
# else:
#     print("All v2 segments have at least one associated COMID.")

# # Center map
# bounds = seg_v2_4326.total_bounds
# center_lat = (bounds[1] + bounds[3]) / 2
# center_lon = (bounds[0] + bounds[2]) / 2

# m_comid = folium.Map(location=[center_lat, center_lon], zoom_start=8, tiles="CartoDB positron")

# folium.TileLayer(
#     tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
#     attr="OpenTopoMap",
#     name="OpenTopoMap",
#     show=False,
# ).add_to(m_comid)

# # Layer: reference flowlines
# ref_display = ref_gdf[["COMID", "geometry"]].to_crs(epsg=4326)
# folium.GeoJson(
#     ref_display.to_json(),
#     name="Reference flowlines",
#     style_function=lambda f: {"color": "gray", "weight": 1, "opacity": 0.5},
#     tooltip=folium.GeoJsonTooltip(fields=["COMID"]),
#     show=False,
# ).add_to(m_comid)

# # Layer: v2 segments colored by COMID status
# def comid_style(feature):
#     has = feature["properties"]["has_comids"]
#     return {
#         "color": "green" if has else "red",
#         "weight": 3,
#         "opacity": 0.8,
#     }

# folium.GeoJson(
#     seg_v2_4326[["model_seg_idx", "has_comids", "comid_list", "geometry"]].to_json(),
#     name="v2 segments (green=has COMIDs, red=no COMIDs)",
#     style_function=comid_style,
#     tooltip=folium.GeoJsonTooltip(fields=["model_seg_idx", "comid_list"]),
#     popup=folium.GeoJsonPopup(fields=["model_seg_idx", "comid_list"]),
# ).add_to(m_comid)

# folium.LayerControl().add_to(m_comid)
# m_comid

# %% [markdown]
# ## Compute parameters `seg_slope` and `mann_n` for v2 segments

# %%
# Weight by overlap length
joined_filtered["weighted_slope"] = joined_filtered["slope"] * joined_filtered["overlap_length"]

# Flag waterbody segments (slope == 0.00001)
# Referrence flowlines that have a waterbody flay have slopes set to 0.00001. These values were averaging in the calculations to give intermediate values to
# OHM segments, so the following blocks evaluate how much of the length of the OHM segment that is set to 0.00001 in the ref fabric, and then set the whole segment to 0.00001
# or, ignore the 0.00001 values and calcualte the slope using the other ref flowline values.

joined_filtered["is_waterbody"] = (joined_filtered["slope"] == 0.00001)

agg = joined_filtered.groupby("model_seg_idx").agg(
    sum_overlap=("overlap_length", "sum"),
    sum_weighted_slope=("weighted_slope", "sum"),
    n_ref_segments=("COMID", "count"),
    waterbody_overlap=("is_waterbody", lambda x: (x * joined_filtered.loc[x.index, "overlap_length"]).sum()),
).reset_index()

agg["slope_from_ref"] = agg["sum_weighted_slope"] / agg["sum_overlap"]

# If >50% of overlap length has slope=0.00001, assign slope=0.00001 (waterbody segment)
waterbody_frac = agg["waterbody_overlap"] / agg["sum_overlap"]
waterbody_mask = waterbody_frac > 0.5
agg.loc[waterbody_mask, "slope_from_ref"] = 0.00001
print(f"{waterbody_mask.sum()} segments classified as waterbody (>50% overlap with slope=0.00001)")

# Flag segments with >50% of length inside a waterbody
agg["waterbody_frac"] = waterbody_frac
agg["in_waterbody"] = waterbody_frac > 0.5
print(f"{agg['in_waterbody'].sum()} segments have >50% of length inside a waterbody")

# Compute mann_n from slope using the formula: 0.1 * slope^0.18
agg["mann_n_from_slope"] = 0.1 * (agg["slope_from_ref"] ** 0.18)

print(f"Computed parameters for {len(agg)} of {len(seg_v2_gdf)} v2 segments")
agg.head()

# %% [markdown]
# ###  Fetch NHD waterbody polygons and mask OHM segments
# Download NHDPlusV2 waterbody polygons (lakes/reservoirs) from USGS API or Read in the waterbody polygons used for depression storage worlflows 
# and flag OHM segments with >50% of their length inside a waterbody. This section will inforce a slope of 0.00001 for segments in reserviors or lakes not coded in the original hydrofabric v2.

# %%
import requests

# # Fetch all NHD waterbodies within the v2 domain bbox (API approach - commented out)
# v2_4326 = seg_v2_gdf.to_crs(epsg=4326)
# bb = v2_4326.total_bounds
# 
# all_wb_features = []
# offset = 0
# limit = 1000
# 
# print("Fetching NHD waterbody polygons from USGS API...")
# while True:
#     url = (
#         f"https://labs-beta.waterdata.usgs.gov/api/fabric/pygeoapi/collections/nhdwaterbody/items"
#         f"?bbox={bb[0]},{bb[1]},{bb[2]},{bb[3]}&limit={limit}&offset={offset}&f=json"
#     )
#     resp = requests.get(url, timeout=60)
#     resp.raise_for_status()
#     data = resp.json()
#     features = data.get("features", [])
#     if not features:
#         break
#     all_wb_features.extend(features)
#     offset += limit
#     print(f"  Fetched {len(all_wb_features)} waterbodies so far...")
# 
# wb_gdf = gpd.GeoDataFrame.from_features(all_wb_features, crs="EPSG:4326")
# # Filter to lakes and reservoirs (ftype: 390=Lake/Pond, 436=Reservoir)
# wb_gdf = wb_gdf[wb_gdf["ftype"].isin(["LakePond", "Reservoir", 390, 436, "390", "436"])].copy()
# print(f"Loaded {len(wb_gdf)} lake/reservoir waterbodies")

# Load waterbodies from local shapefile
wb_shp_path = pl.Path(r"D:\nhm-assist\nhf_assist\data_dependencies\main_waterbodies_conus\main_waterbodies.shp")
wb_gdf = gpd.read_file(wb_shp_path)
print(f"Loaded {len(wb_gdf)} waterbodies from {wb_shp_path.name}")

# Clip to OHM domain extent to save processing time
wb_gdf = wb_gdf.to_crs(seg_v2_gdf.crs)
domain_boundary = seg_v2_gdf.union_all().envelope
wb_gdf = wb_gdf[wb_gdf.intersects(domain_boundary)].copy()
print(f"Clipped to domain: {len(wb_gdf)} waterbodies")

# %%
# Reproject waterbodies and compute fraction of each OHM segment inside a waterbody
wb_proj = wb_gdf.to_crs(crs_proj)
wb_union = wb_proj.union_all()

# For each v2 segment, compute fraction of length inside waterbody polygons
seg_lengths = seg_v2_proj.geometry.length
inside_lengths = seg_v2_proj.geometry.intersection(wb_union).length
wb_frac = inside_lengths / seg_lengths

agg_with_wb = seg_v2_gdf[["model_seg_idx"]].copy()
agg_with_wb["waterbody_frac_poly"] = wb_frac.values
agg_with_wb["in_waterbody"] = agg_with_wb["waterbody_frac_poly"] > 0.50

# Update agg with polygon-based waterbody flag
agg = agg.drop(columns=["waterbody_frac", "in_waterbody"], errors="ignore")
agg = agg.merge(agg_with_wb[["model_seg_idx", "waterbody_frac_poly", "in_waterbody"]], on="model_seg_idx", how="left")

# Override slope for waterbody segments
agg.loc[agg["in_waterbody"] == True, "slope_from_ref"] = 0.00001
agg["mann_n_from_slope"] = 0.1 * (agg["slope_from_ref"] ** 0.18)

print(f"{agg['in_waterbody'].sum()} OHM segments have >50% of length inside NHD waterbody polygons")

# %%
# Compute x_coef: default 0.2, set to 0.0 for waterbody segments and outlet segments (tosegment=0)
toseg_df = pd.read_csv(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files\tosegment.csv"
)
toseg_df.rename(columns={"$id": "model_seg_idx"}, inplace=True)

agg = agg.drop(columns=["tosegment"], errors="ignore")
agg = agg.merge(toseg_df[["model_seg_idx", "tosegment"]], on="model_seg_idx", how="left")

# Default value
agg["x_coef"] = 0.2

# Set to 0.0 for waterbody segments
agg.loc[agg["in_waterbody"] == True, "x_coef"] = 0.0

# Set to 0.0 for outlet segments (tosegment == 0)
agg.loc[agg["tosegment"] == 0, "x_coef"] = 0.0

n_wb = (agg["in_waterbody"] == True).sum()
n_outlet = (agg["tosegment"] == 0).sum()
n_both = ((agg["in_waterbody"] == True) & (agg["tosegment"] == 0)).sum()
n_zero = (agg["x_coef"] == 0.0).sum()

print(f"x_coef: {(agg['x_coef'] == 0.2).sum()} segments at 0.2, {n_zero} segments at 0.0")
print(f"  (waterbody: {n_wb}, outlet: {n_outlet}, both: {n_both})")

# %%
# Compute segment_type:
# 0=segment (default), 1=headwater, 2=lake, 5=outbound (tosegment=0)
#
# Note: Other values exist and are important for computing other water budget output variable in prms 6.0, but it is not clear if this fuctinality extends
# to pywatershed yet:
# Segment type (0=segment; 1= headwater; 2=lake; 3=replace inflow; 4=inbound to NHM; 5=outbound from NHM; 6=inbound to region; 7=outbound from region; 8=drains to ocean; 9=sink; 
# 10=inbound from Great Lakes; 11=outbound to Great Lakes, add 100 to flag that the value is updated)
#
# Priority order: outbound first, then headwater, then lake (highest priority last)
agg["segment_type"] = 0

# Type 5: Outbound — segments where tosegment == 0 (outlets)
agg.loc[agg["tosegment"] == 0, "segment_type"] = 5

# Type 1: Headwater — segments that no other segment flows into
all_seg_ids = set(seg_v2_gdf["model_seg_idx"])
segments_that_receive_flow = set(toseg_df["tosegment"].values) - {0}
headwater_segs = all_seg_ids - segments_that_receive_flow
agg.loc[agg["model_seg_idx"].isin(headwater_segs), "segment_type"] = 1

# Type 2: Lake — segments inside waterbodies (highest priority)
agg.loc[agg["in_waterbody"] == True, "segment_type"] = 2

print(f"segment_type distribution:")
print(f"  0 (segment):   {(agg['segment_type'] == 0).sum()}")
print(f"  1 (headwater): {(agg['segment_type'] == 1).sum()}")
print(f"  2 (lake):      {(agg['segment_type'] == 2).sum()}")
print(f"  5 (outbound):  {(agg['segment_type'] == 5).sum()}")

# %% [markdown]
# ## Compute parameters `seg_width` and `seg_depth` for v2 segments
# Using bankfull width and bankfull depth from Select Attributes for NHDPlus Version 2.1, https://www.sciencebase.gov/catalog/item/5669a79ee4b08895842a1d47
# for OHM segments. Look up bankfull values for each COMID that overlaps with OHM segments, then compute length-weighted averages per OHM segment.

# %%
# Read BANKFULL_CONUS data
bankfull_df = pd.read_csv(r"D:\BANKFULL_CONUS\BANKFULL_CONUS.txt")
print(f"Loaded {len(bankfull_df)} BANKFULL records")

# Replace fill values with NaN
bankfull_df = bankfull_df.replace(-9999.0, np.nan)

# Merge bankfull data onto the COMID crosswalk
comid_with_bankfull = comid_per_seg.merge(
    bankfull_df[["COMID", "BANKFULL_WIDTH", "BANKFULL_DEPTH"]],
    on="COMID",
    how="left",
)

# Drop rows where bankfull data is missing
comid_with_bankfull = comid_with_bankfull.dropna(subset=["BANKFULL_WIDTH", "BANKFULL_DEPTH"])
print(f"COMIDs with bankfull data: {len(comid_with_bankfull)} of {len(comid_per_seg)}")

# Compute length-weighted averages per OHM segment
comid_with_bankfull["weighted_width"] = comid_with_bankfull["BANKFULL_WIDTH"] * comid_with_bankfull["overlap_length"]
comid_with_bankfull["weighted_depth"] = comid_with_bankfull["BANKFULL_DEPTH"] * comid_with_bankfull["overlap_length"]

bankfull_agg = comid_with_bankfull.groupby("model_seg_idx").agg(
    sum_overlap=("overlap_length", "sum"),
    sum_weighted_width=("weighted_width", "sum"),
    sum_weighted_depth=("weighted_depth", "sum"),
    n_comids=("COMID", "count"),
).reset_index()

bankfull_agg["bankfull_width"] = bankfull_agg["sum_weighted_width"] / bankfull_agg["sum_overlap"]
bankfull_agg["bankfull_depth"] = bankfull_agg["sum_weighted_depth"] / bankfull_agg["sum_overlap"]

print(f"Computed bankfull values for {len(bankfull_agg)} of {len(seg_v2_gdf)} OHM segments")
print(f"Bankfull width range: {bankfull_agg['bankfull_width'].min():.2f} - {bankfull_agg['bankfull_width'].max():.2f}")
print(f"Bankfull depth range: {bankfull_agg['bankfull_depth'].min():.3f} - {bankfull_agg['bankfull_depth'].max():.3f}")
bankfull_agg[["model_seg_idx", "bankfull_width", "bankfull_depth", "n_comids"]].head()

# %%
# Segments without bankfull data — fill via nearest neighbor
missing_bankfull = set(seg_v2_gdf["model_seg_idx"]) - set(bankfull_agg["model_seg_idx"])
print(f"OHM segments without bankfull data: {len(missing_bankfull)}")

if missing_bankfull:
    # Get midpoints of unmatched v2 segments
    unmatched_bf_segs = seg_v2_proj[seg_v2_proj["model_seg_idx"].isin(missing_bankfull)].copy()
    unmatched_bf_segs["geometry"] = unmatched_bf_segs.geometry.interpolate(0.5, normalized=True)

    # Build ref flowlines with bankfull data for nearest lookup
    ref_with_bankfull = ref_proj.merge(
        bankfull_df[["COMID", "BANKFULL_WIDTH", "BANKFULL_DEPTH"]],
        on="COMID",
        how="inner",
    )
    ref_with_bankfull = ref_with_bankfull.dropna(subset=["BANKFULL_WIDTH", "BANKFULL_DEPTH"])

    nn_bf = gpd.sjoin_nearest(
        unmatched_bf_segs[["model_seg_idx", "geometry"]],
        ref_with_bankfull[["COMID", "BANKFULL_WIDTH", "BANKFULL_DEPTH", "geometry"]],
        how="left",
        distance_col="nn_distance_m",
    ).drop(columns=["index_right", "geometry"])

    # Append to bankfull_agg
    nn_bf_agg = nn_bf[["model_seg_idx", "BANKFULL_WIDTH", "BANKFULL_DEPTH"]].rename(
        columns={"BANKFULL_WIDTH": "bankfull_width", "BANKFULL_DEPTH": "bankfull_depth"}
    )
    nn_bf_agg["n_comids"] = -1  # flag as nearest-neighbor fill
    nn_bf_agg["sum_overlap"] = 0.0
    nn_bf_agg["sum_weighted_width"] = 0.0
    nn_bf_agg["sum_weighted_depth"] = 0.0

    bankfull_agg = pd.concat([bankfull_agg, nn_bf_agg], ignore_index=True)
    print(f"Filled {len(nn_bf_agg)} segments via nearest neighbor")
    print(f"Total segments with bankfull data: {len(bankfull_agg)}")


# %% [markdown]
# ## Write seg_slope, mann_n, seg_width, and seg_depth CSVs in paramdb format

# %%
created_params_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\created_seg_params"
)
created_params_dir.mkdir(parents=True, exist_ok=True)

# Sort agg by model_seg_idx, merge onto full segment list for complete coverage
result = seg_v2_gdf[["model_seg_idx"]].merge(
    agg[["model_seg_idx", "slope_from_ref", "mann_n_from_slope", "n_ref_segments", "in_waterbody"]],
    on="model_seg_idx",
    how="left",
).sort_values("model_seg_idx").reset_index(drop=True)

# Fill unmatched segments via nearest neighbor
unmatched = result[result["slope_from_ref"].isna()]
print(f"Matched: {result['slope_from_ref'].notna().sum()}, Unmatched: {len(unmatched)}")

if len(unmatched) > 0:
    unmatched_segs = seg_v2_proj[seg_v2_proj["model_seg_idx"].isin(unmatched["model_seg_idx"])].copy()
    unmatched_segs["geometry"] = unmatched_segs.geometry.interpolate(0.5, normalized=True)

    nn = gpd.sjoin_nearest(
        unmatched_segs[["model_seg_idx", "geometry"]],
        ref_proj[ref_proj["slope"] != -9998][["COMID", "slope", "geometry"]],
        how="left",
        distance_col="nn_distance_m",
    ).drop(columns=["index_right"])

    nn["mann_n_from_slope"] = 0.1 * (nn["slope"] ** 0.18)

    for _, row in nn.iterrows():
        mask = result["model_seg_idx"] == row["model_seg_idx"]
        result.loc[mask, "slope_from_ref"] = row["slope"]
        result.loc[mask, "mann_n_from_slope"] = row["mann_n_from_slope"]
        result.loc[mask, "n_ref_segments"] = -1

    print(f"Filled {len(nn)} segments via nearest neighbor")

# seg_slope.csv
seg_slope_out = pd.DataFrame({
    "$id": result["model_seg_idx"].astype(int),
    "seg_slope": result["slope_from_ref"],
})
seg_slope_out.to_csv(created_params_dir / "seg_slope.csv", index=False)
print(f"Wrote seg_slope.csv: {len(seg_slope_out)} rows, range: {seg_slope_out['seg_slope'].min():.6f} - {seg_slope_out['seg_slope'].max():.6f}")

# mann_n.csv
mann_n_out = pd.DataFrame({
    "$id": result["model_seg_idx"].astype(int),
    "mann_n": result["mann_n_from_slope"],
})
mann_n_out.to_csv(created_params_dir / "mann_n.csv", index=False)
print(f"Wrote mann_n.csv: {len(mann_n_out)} rows, range: {mann_n_out['mann_n'].min():.6f} - {mann_n_out['mann_n'].max():.6f}")

# seg_width.csv
seg_width_result = seg_v2_gdf[["model_seg_idx"]].merge(
    bankfull_agg[["model_seg_idx", "bankfull_width"]],
    on="model_seg_idx",
    how="left",
).sort_values("model_seg_idx").reset_index(drop=True)

seg_width_out = pd.DataFrame({
    "$id": seg_width_result["model_seg_idx"].astype(int),
    "seg_width": seg_width_result["bankfull_width"],
})
seg_width_out.to_csv(created_params_dir / "seg_width.csv", index=False)
print(f"Wrote seg_width.csv: {len(seg_width_out)} rows, range: {seg_width_out['seg_width'].min():.3f} - {seg_width_out['seg_width'].max():.3f}")

# seg_depth.csv
seg_depth_result = seg_v2_gdf[["model_seg_idx"]].merge(
    bankfull_agg[["model_seg_idx", "bankfull_depth"]],
    on="model_seg_idx",
    how="left",
).sort_values("model_seg_idx").reset_index(drop=True)

seg_depth_out = pd.DataFrame({
    "$id": seg_depth_result["model_seg_idx"].astype(int),
    "seg_depth": seg_depth_result["bankfull_depth"],
})
seg_depth_out.to_csv(created_params_dir / "seg_depth.csv", index=False)
print(f"Wrote seg_depth.csv: {len(seg_depth_out)} rows, range: {seg_depth_out['seg_depth'].min():.3f} - {seg_depth_out['seg_depth'].max():.3f}")

# x_coef.csv
x_coef_result = seg_v2_gdf[["model_seg_idx"]].merge(
    agg[["model_seg_idx", "x_coef"]],
    on="model_seg_idx",
    how="left",
).sort_values("model_seg_idx").reset_index(drop=True)
x_coef_result["x_coef"] = x_coef_result["x_coef"].fillna(0.2)

x_coef_out = pd.DataFrame({
    "$id": x_coef_result["model_seg_idx"].astype(int),
    "x_coef": x_coef_result["x_coef"],
})
x_coef_out.to_csv(created_params_dir / "x_coef.csv", index=False)
print(f"Wrote x_coef.csv: {len(x_coef_out)} rows, range: {x_coef_out['x_coef'].min():.2f} - {x_coef_out['x_coef'].max():.2f}")

# segment_type.csv
seg_type_result = seg_v2_gdf[["model_seg_idx"]].merge(
    agg[["model_seg_idx", "segment_type"]],
    on="model_seg_idx",
    how="left",
).sort_values("model_seg_idx").reset_index(drop=True)
seg_type_result["segment_type"] = seg_type_result["segment_type"].fillna(0).astype(int)

seg_type_out = pd.DataFrame({
    "$id": seg_type_result["model_seg_idx"].astype(int),
    "segment_type": seg_type_result["segment_type"],
})
seg_type_out.to_csv(created_params_dir / "segment_type.csv", index=False)
print(f"Wrote segment_type.csv: {len(seg_type_out)} rows, values: {sorted(seg_type_out['segment_type'].unique().tolist())}")

print(f"\nAll files written to {created_params_dir}")

# %% [markdown]
# ## Map: all computed segment parameters

# %% jupyter={"source_hidden": true}
import folium
from branca.colormap import LinearColormap

# Merge all parameters onto v2 geometry for display
seg_v2_all = seg_v2_gdf.to_crs(epsg=4326).merge(
    agg[["model_seg_idx", "slope_from_ref", "mann_n_from_slope", "in_waterbody", "x_coef", "segment_type"]],
    on="model_seg_idx",
    how="left",
).merge(
    bankfull_agg[["model_seg_idx", "bankfull_width", "bankfull_depth"]],
    on="model_seg_idx",
    how="left",
)

# Center map
bounds = seg_v2_all.total_bounds
center_lat = (bounds[1] + bounds[3]) / 2
center_lon = (bounds[0] + bounds[2]) / 2

m = folium.Map(location=[center_lat, center_lon], zoom_start=8, tiles="CartoDB positron")

folium.TileLayer(
    tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attr="OpenTopoMap",
    name="OpenTopoMap",
    show=False,
).add_to(m)

# --- Colormap: mann_n ---
cmap_mann = LinearColormap(
    colors=["blue", "cyan", "yellow", "red"],
    vmin=seg_v2_all["mann_n_from_slope"].min(),
    vmax=seg_v2_all["mann_n_from_slope"].max(),
    caption="mann_n (from slope)",
)

# --- Colormap: bankfull width (quantile-scaled) ---
width_vals = seg_v2_all["bankfull_width"].dropna()
width_quantiles = width_vals.quantile([0, 0.2, 0.4, 0.6, 0.8, 0.95, 1.0]).values.tolist()
cmap_width = LinearColormap(
    colors=["darkblue", "blue", "cyan", "yellow", "orange", "red"],
    index=width_quantiles[:-1],
    vmin=width_quantiles[0],
    vmax=width_quantiles[-1],
    caption="Bankfull Width (m)",
)

# --- Colormap: bankfull depth (quantile-scaled) ---
depth_vals = seg_v2_all["bankfull_depth"].dropna()
depth_quantiles = depth_vals.quantile([0, 0.2, 0.4, 0.6, 0.8, 0.95, 1.0]).values.tolist()
cmap_depth = LinearColormap(
    colors=["darkblue", "blue", "cyan", "yellow", "orange", "red"],
    index=depth_quantiles[:-1],
    vmin=depth_quantiles[0],
    vmax=depth_quantiles[-1],
    caption="Bankfull Depth (m)",
)

# Layer: mann_n
folium.GeoJson(
    seg_v2_all[["model_seg_idx", "slope_from_ref", "mann_n_from_slope", "geometry"]].to_json(),
    name="mann_n (from slope)",
    style_function=lambda f: {
        "color": cmap_mann(f["properties"]["mann_n_from_slope"]) if f["properties"]["mann_n_from_slope"] is not None else "gray",
        "weight": 3, "opacity": 0.8,
    },
    tooltip=folium.GeoJsonTooltip(fields=["model_seg_idx", "slope_from_ref", "mann_n_from_slope"]),
    popup=folium.GeoJsonPopup(fields=["model_seg_idx", "slope_from_ref", "mann_n_from_slope"]),
    show=True,
).add_to(m)

# Layer: bankfull width
folium.GeoJson(
    seg_v2_all[["model_seg_idx", "bankfull_width", "bankfull_depth", "geometry"]].to_json(),
    name="Bankfull Width",
    style_function=lambda f: {
        "color": cmap_width(f["properties"]["bankfull_width"]) if f["properties"]["bankfull_width"] is not None else "gray",
        "weight": 3, "opacity": 0.8,
    },
    tooltip=folium.GeoJsonTooltip(fields=["model_seg_idx", "bankfull_width"]),
    popup=folium.GeoJsonPopup(fields=["model_seg_idx", "bankfull_width", "bankfull_depth"]),
    show=False,
).add_to(m)

# Layer: bankfull depth
folium.GeoJson(
    seg_v2_all[["model_seg_idx", "bankfull_width", "bankfull_depth", "geometry"]].to_json(),
    name="Bankfull Depth",
    style_function=lambda f: {
        "color": cmap_depth(f["properties"]["bankfull_depth"]) if f["properties"]["bankfull_depth"] is not None else "gray",
        "weight": 3, "opacity": 0.8,
    },
    tooltip=folium.GeoJsonTooltip(fields=["model_seg_idx", "bankfull_depth"]),
    popup=folium.GeoJsonPopup(fields=["model_seg_idx", "bankfull_width", "bankfull_depth"]),
    show=False,
).add_to(m)

# Layer: waterbody segments
wb_segs = seg_v2_all[seg_v2_all["in_waterbody"] == True]
if len(wb_segs) > 0:
    folium.GeoJson(
        wb_segs[["model_seg_idx", "geometry"]].to_json(),
        name="Segments in waterbodies (>50%)",
        style_function=lambda f: {"color": "purple", "weight": 5, "opacity": 0.9},
        tooltip=folium.GeoJsonTooltip(fields=["model_seg_idx"]),
        show=False,
    ).add_to(m)

# Layer: reference flowlines
ref_display = ref_gdf[["COMID", "slope", "geometry"]].to_crs(epsg=4326)
folium.GeoJson(
    ref_display.to_json(),
    name="Reference flowlines",
    style_function=lambda f: {"color": "gray", "weight": 1, "opacity": 0.6},
    tooltip=folium.GeoJsonTooltip(fields=["COMID", "slope"]),
    popup=folium.GeoJsonPopup(fields=["COMID", "slope"]),
    show=False,
).add_to(m)

# USGS NHD Hydro WMS overlay
folium.raster_layers.WmsTileLayer(
    url="https://basemap.nationalmap.gov/arcgis/services/USGSHydroCached/MapServer/WMSServer",
    layers="0",
    fmt="image/png",
    transparent=True,
    name="USGS NHD Hydro",
    overlay=True,
    control=True,
    show=False,
    attr="USGS National Map - NHD",
).add_to(m)

# Layer: x_coef
folium.GeoJson(
    seg_v2_all[["model_seg_idx", "x_coef", "geometry"]].to_json(),
    name="x_coef",
    style_function=lambda f: {
        "color": "green" if f["properties"]["x_coef"] == 0.2 else "purple",
        "weight": 3, "opacity": 0.8,
    },
    tooltip=folium.GeoJsonTooltip(fields=["model_seg_idx", "x_coef"]),
    popup=folium.GeoJsonPopup(fields=["model_seg_idx", "x_coef"]),
    show=False,
).add_to(m)

# Layer: segment_type
seg_type_colors = {0: "gray", 1: "green", 2: "blue", 5: "red"}
folium.GeoJson(
    seg_v2_all[["model_seg_idx", "segment_type", "geometry"]].to_json(),
    name="segment_type",
    style_function=lambda f: {
        "color": seg_type_colors.get(f["properties"]["segment_type"], "gray"),
        "weight": 3, "opacity": 0.8,
    },
    tooltip=folium.GeoJsonTooltip(fields=["model_seg_idx", "segment_type"]),
    popup=folium.GeoJsonPopup(fields=["model_seg_idx", "segment_type"]),
    show=False,
).add_to(m)

cmap_mann.add_to(m)
cmap_width.add_to(m)
cmap_depth.add_to(m)
folium.LayerControl().add_to(m)
m

# %%
