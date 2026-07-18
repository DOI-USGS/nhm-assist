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
# # Extract NHM v1.1 Parameters
# This notebook extracts parameters from the NHM v1.1 parameter database (CONUS CSV)
# and transfers them to v2 HRUs via spatial overlay.

# %%
import pandas as pd
import pathlib as pl
import geopandas as gpd
import numpy as np

# %% [markdown]
# ## Load hru_deplcrv parameter from CONUS CSV
# from https://code.usgs.gov/wma/national-iwaas/nhm/nhm-applications/nhm-v1.1-conus/paramdb_v1.1_gridmet_CONUS/-/tree/master?ref_type=heads

# %%
hru_deplcrv_filepath = pl.Path(
    r"D:\version1_1_params\paramdb_v1.1_gridmet_CONUS-master\hru_deplcrv.csv"
)

deplcrv_df = pd.read_csv(hru_deplcrv_filepath)
deplcrv_df.rename(columns={"$id": "nhm_id"}, inplace=True)

print(f"Loaded {len(deplcrv_df)} HRU parameter values")
print(f"hru_deplcrv unique values: {sorted(deplcrv_df['hru_deplcrv'].unique())}")
deplcrv_df.head()

# %% [markdown]
# ## Load v1.1 HRU geospatial data from GDB

# %%
v1_gdb_path = pl.Path(
    r"D:\version1_1_params\GFv1.1.gdb"
)

hru_gdf = gpd.read_file(v1_gdb_path, layer="nhru_v1_1_simp").to_crs(epsg=4326)
print(f"Loaded {len(hru_gdf)} v1.1 HRUs")
print(hru_gdf.columns.tolist())

# %% [markdown]
# ## Merge parameter data with v1.1 HRU geometry

# %%
# nhm_id in the CSV (1-based sequential) matches nhru_v1_1 in the GDB
hru_deplcrv_gdf = hru_gdf.merge(deplcrv_df, left_on="nhru_v1_1", right_on="nhm_id")
print(f"Merged GeoDataFrame: {len(hru_deplcrv_gdf)} HRUs")
hru_deplcrv_gdf.head()

# %% [markdown]
# ## Load v2 HRU geospatial data

# %%
v2_gpkg_path = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\GIS\model_layers.gpkg"
)

hru_v2_gdf = gpd.read_file(v2_gpkg_path, layer="nhru").to_crs(epsg=4326)
print(f"Loaded {len(hru_v2_gdf)} v2 HRUs")
print(hru_v2_gdf.columns.tolist())

# %% [markdown]
# ## Transfer hru_deplcrv from v1.1 to v2 HRUs (largest overlap)
# For each v2 HRU, find which v1.1 HRU has the most spatial overlap
# and assign that HRU's `hru_deplcrv` value.

# %%
# Reproject to a projected CRS for accurate area calculations
crs_proj = "EPSG:5070"  # NAD83 / Conus Albers (meters)

v1_proj = hru_deplcrv_gdf.to_crs(crs_proj)
v2_proj = hru_v2_gdf.to_crs(crs_proj)

# Compute the overlay (intersection) between v2 and v1.1 HRUs
# Use model_hru_idx as the v2 identifier (defines canonical parameter ordering)
overlay = gpd.overlay(
    v2_proj[["model_hru_idx", "nhm_id", "geometry"]].rename(columns={"model_hru_idx": "model_hru_idx_v2", "nhm_id": "nhm_id_v2"}),
    v1_proj[["nhru_v1_1", "hru_deplcrv", "geometry"]].rename(columns={"nhru_v1_1": "nhm_id_v1"}),
    how="intersection",
)

# Calculate the area of each intersection polygon
overlay["overlap_area"] = overlay.geometry.area

# For each v2 HRU, keep only the v1.1 HRU with the largest overlap
idx_max_overlap = overlay.groupby("model_hru_idx_v2")["overlap_area"].idxmax()
best_match = overlay.loc[idx_max_overlap, ["model_hru_idx_v2", "nhm_id_v2", "nhm_id_v1", "hru_deplcrv", "overlap_area"]]
best_match = best_match.reset_index(drop=True)

print(f"Matched {len(best_match)} of {len(hru_v2_gdf)} v2 HRUs")
best_match.head()

# %%
# Fill unmatched v2 HRUs using nearest neighbor
# These are typically very small HRUs that fall in gaps/slivers between v1.1 polygons
unmatched_ids = set(hru_v2_gdf["model_hru_idx"]) - set(best_match["model_hru_idx_v2"])
print(f"{len(unmatched_ids)} v2 HRUs unmatched — assigning via nearest neighbor")

if unmatched_ids:
    unmatched_gdf = v2_proj[v2_proj["model_hru_idx"].isin(unmatched_ids)].copy()
    unmatched_gdf["geometry"] = unmatched_gdf.geometry.centroid

    nn_join = gpd.sjoin_nearest(
        unmatched_gdf[["model_hru_idx", "nhm_id", "geometry"]].rename(columns={"model_hru_idx": "model_hru_idx_v2", "nhm_id": "nhm_id_v2"}),
        v1_proj[["nhru_v1_1", "hru_deplcrv", "geometry"]].rename(columns={"nhru_v1_1": "nhm_id_v1"}),
        how="left",
    ).drop(columns=["index_right", "geometry"])

    nn_join["overlap_area"] = 0.0
    best_match = pd.concat([best_match, nn_join[["model_hru_idx_v2", "nhm_id_v2", "nhm_id_v1", "hru_deplcrv", "overlap_area"]]], ignore_index=True)

print(f"Total matched after nearest neighbor: {len(best_match)} of {len(hru_v2_gdf)} v2 HRUs")

# %% [markdown]
# ## Map v2 HRUs that have hru_deplcrv from best_match

# %%
import matplotlib.pyplot as plt

# Get the v2 HRUs that appear in best_match
matched_nhm_ids = best_match["model_hru_idx_v2"].tolist()
v2_matched_gdf = hru_v2_gdf[hru_v2_gdf["model_hru_idx"].isin(matched_nhm_ids)].merge(
    best_match[["model_hru_idx_v2", "hru_deplcrv"]],
    left_on="model_hru_idx",
    right_on="model_hru_idx_v2",
).drop(columns=["model_hru_idx_v2"])

fig, ax = plt.subplots(1, 1, figsize=(12, 10))

# Plot all v2 HRUs as light gray background
hru_v2_gdf.plot(ax=ax, color="lightgray", edgecolor="gray", linewidth=0.2)

# Plot matched HRUs colored by hru_deplcrv
v2_matched_gdf.plot(
    ax=ax,
    column="hru_deplcrv",
    categorical=True,
    cmap="viridis",
    edgecolor="black",
    linewidth=0.2,
    legend=True,
    legend_kwds={"title": "hru_deplcrv", "loc": "lower right"},
)

ax.set_title("v2 HRUs with hru_deplcrv assigned from v1.1 (largest overlap)")
ax.set_axis_off()
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Load snarea_curve from CONUS CSV

# %%
snarea_curve_filepath = pl.Path(
    r"D:\version1_1_params\paramdb_v1.1_gridmet_CONUS-master\snarea_curve.csv"
)
snarea_raw = pd.read_csv(snarea_curve_filepath)
n_curves = len(snarea_raw) // 11
snarea_df = pd.DataFrame(
    snarea_raw["snarea_curve"].values.reshape(n_curves, 11),
    index=range(1, n_curves + 1),
    columns=[f"frac_{i}" for i in range(11)],
)
snarea_df.index.name = "curve_id"
print(f"Loaded {len(snarea_raw)} values = {n_curves} curves x 11")
snarea_df

# %%
# Copy snarea_curve.csv to created_seg_params directory
import shutil

created_params_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\created_seg_params"
)
created_params_dir.mkdir(parents=True, exist_ok=True)

dest_file = created_params_dir / "snarea_curve.csv"
shutil.copy2(snarea_curve_filepath, dest_file)
print(f"Copied snarea_curve.csv to {dest_file}")

# %% [markdown]
# ## Write hru_deplcrv CSV in paramdb format

# %%
created_hru_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\created_hru_params"
)
created_hru_dir.mkdir(parents=True, exist_ok=True)

# Read nhm_id.csv to get the canonical ordering. For OHM, this has been reset to the hru index because this is a unique fabric and no national ID has been set yet.
nhm_id_order = pd.read_csv(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files\nhm_id.csv"
)
print(f"Canonical ordering: {len(nhm_id_order)} HRUs")

# Sort best_match by model_hru_idx_v2 (which equals $id in the param files)
hru_deplcrv_result = best_match[["model_hru_idx_v2", "nhm_id_v2", "hru_deplcrv"]].sort_values("model_hru_idx_v2").reset_index(drop=True)

# Verify ordering matches nhm_id.csv
assert (hru_deplcrv_result["model_hru_idx_v2"].values == nhm_id_order["nhm_id"].values).all(), \
    "ERROR: nhm_id ordering does not match nhm_id.csv! Check model_hru_idx mapping."
print("Verified: nhm_id ordering matches nhm_id.csv")

# Write with $id as model_hru_idx
hru_deplcrv_out = pd.DataFrame({
    "$id": hru_deplcrv_result["model_hru_idx_v2"].astype(int),
    "hru_deplcrv": hru_deplcrv_result["hru_deplcrv"].astype(int),
})
hru_deplcrv_out.to_csv(created_hru_dir / "hru_deplcrv.csv", index=False)
print(f"Wrote hru_deplcrv.csv: {len(hru_deplcrv_out)} rows to {created_hru_dir}")
hru_deplcrv_out.head()

# %%
best_match

# %%
