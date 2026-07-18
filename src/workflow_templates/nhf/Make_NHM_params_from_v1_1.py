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
# # Transfer NHM v1.1 HRU Parameters to v2
# This notebook reads any HRU-dimensioned parameter from the NHM v1.1 CONUS
# parameter database CSV, transfers values to v2 HRUs via spatial overlay
# (largest area overlap), and writes the result in paramdb CSV format.

# %%
import pandas as pd
import pathlib as pl
import geopandas as gpd
import numpy as np

# %% [markdown]
# ## Configuration
# Set the parameter name and paths below.

# %%
# === USER CONFIGURATION ===
param_name = "snarea_thresh"  # Change this to any nhru-dimensioned parameter

param_source_dir = pl.Path(r"D:\version1_1_params\paramdb_v1.1_gridmet_CONUS-master")
v1_gdb_path = pl.Path(r"D:\version1_1_params\GFv1.1.gdb")
v2_gpkg_path = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\GIS\model_layers.gpkg")
output_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\created_hru_params")
param_source_files_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files")

output_dir.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## Load parameter from CONUS CSV

# %%
param_filepath = param_source_dir / f"{param_name}.csv"
param_df = pd.read_csv(param_filepath)
param_df.rename(columns={"$id": "nhm_id"}, inplace=True)

print(f"Loaded {len(param_df)} values for '{param_name}'")
print(f"Columns: {param_df.columns.tolist()}")
print(f"Value range: {param_df[param_name].min()} - {param_df[param_name].max()}")
param_df.head()

# %% [markdown]
# ## Load v1.1 HRU geospatial data from GDB

# %%
hru_gdf = gpd.read_file(v1_gdb_path, layer="nhru_v1_1_simp").to_crs(epsg=4326)
print(f"Loaded {len(hru_gdf)} v1.1 HRUs")

# %% [markdown]
# ## Merge parameter data with v1.1 HRU geometry

# %%
hru_param_gdf = hru_gdf.merge(param_df, left_on="nhru_v1_1", right_on="nhm_id")
print(f"Merged GeoDataFrame: {len(hru_param_gdf)} HRUs")
hru_param_gdf.head()

# %% [markdown]
# ## Load v2 HRU geospatial data

# %%
hru_v2_gdf = gpd.read_file(v2_gpkg_path, layer="nhru").to_crs(epsg=4326)
print(f"Loaded {len(hru_v2_gdf)} v2 HRUs")

# %% [markdown]
# ## Transfer parameter from v1.1 to v2 HRUs (largest overlap)

# %%
# Reproject to a projected CRS for accurate area calculations
crs_proj = "EPSG:5070"

v1_proj = hru_param_gdf.to_crs(crs_proj)
v2_proj = hru_v2_gdf.to_crs(crs_proj)

# Compute the overlay (intersection) between v2 and v1.1 HRUs
overlay = gpd.overlay(
    v2_proj[["model_hru_idx", "nhm_id", "geometry"]].rename(columns={"model_hru_idx": "model_hru_idx_v2", "nhm_id": "nhm_id_v2"}),
    v1_proj[["nhru_v1_1", param_name, "geometry"]].rename(columns={"nhru_v1_1": "nhm_id_v1"}),
    how="intersection",
)

# Calculate the area of each intersection polygon
overlay["overlap_area"] = overlay.geometry.area

# For each v2 HRU, compute the transferred value based on data type:
# - Float parameters: area-weighted average across all overlapping v1.1 HRUs
# - Integer/categorical parameters: value from the v1.1 HRU with largest overlap
is_float_param = param_df[param_name].dtype in [np.float64, np.float32, float]

if is_float_param:
    # Area-weighted average
    overlay["weighted_value"] = overlay[param_name] * overlay["overlap_area"]
    agg = overlay.groupby("model_hru_idx_v2").agg(
        nhm_id_v2=("nhm_id_v2", "first"),
        total_area=("overlap_area", "sum"),
        weighted_sum=("weighted_value", "sum"),
    ).reset_index()
    agg[param_name] = agg["weighted_sum"] / agg["total_area"]
    best_match = agg[["model_hru_idx_v2", "nhm_id_v2", param_name]].copy()
    best_match["overlap_area"] = agg["total_area"]
    print(f"Used area-weighted average for float parameter '{param_name}'")
else:
    # Largest overlap (categorical/integer)
    idx_max_overlap = overlay.groupby("model_hru_idx_v2")["overlap_area"].idxmax()
    best_match = overlay.loc[idx_max_overlap, ["model_hru_idx_v2", "nhm_id_v2", "nhm_id_v1", param_name, "overlap_area"]]
    best_match = best_match.reset_index(drop=True)
    print(f"Used largest-overlap for integer/categorical parameter '{param_name}'")

print(f"Matched {len(best_match)} of {len(hru_v2_gdf)} v2 HRUs")
best_match.head()

# %%
# Fill unmatched v2 HRUs using nearest neighbor
unmatched_ids = set(hru_v2_gdf["model_hru_idx"]) - set(best_match["model_hru_idx_v2"])
print(f"{len(unmatched_ids)} v2 HRUs unmatched — assigning via nearest neighbor")

if unmatched_ids:
    unmatched_gdf = v2_proj[v2_proj["model_hru_idx"].isin(unmatched_ids)].copy()
    unmatched_gdf["geometry"] = unmatched_gdf.geometry.centroid

    nn_join = gpd.sjoin_nearest(
        unmatched_gdf[["model_hru_idx", "nhm_id", "geometry"]].rename(columns={"model_hru_idx": "model_hru_idx_v2", "nhm_id": "nhm_id_v2"}),
        v1_proj[["nhru_v1_1", param_name, "geometry"]].rename(columns={"nhru_v1_1": "nhm_id_v1"}),
        how="left",
    ).drop(columns=["index_right", "geometry"])

    nn_join["overlap_area"] = 0.0
    best_match = pd.concat([best_match, nn_join[["model_hru_idx_v2", "nhm_id_v2", "nhm_id_v1", param_name, "overlap_area"]]], ignore_index=True)

print(f"Total matched after nearest neighbor: {len(best_match)} of {len(hru_v2_gdf)} v2 HRUs")

# %% [markdown]
# ## Map transferred parameter values

# %%
import matplotlib.pyplot as plt

matched_ids = best_match["model_hru_idx_v2"].tolist()
v2_matched_gdf = hru_v2_gdf[hru_v2_gdf["model_hru_idx"].isin(matched_ids)].merge(
    best_match[["model_hru_idx_v2", param_name]],
    left_on="model_hru_idx",
    right_on="model_hru_idx_v2",
).drop(columns=["model_hru_idx_v2"])

fig, ax = plt.subplots(1, 1, figsize=(12, 10))
hru_v2_gdf.plot(ax=ax, color="lightgray", edgecolor="gray", linewidth=0.2)
v2_matched_gdf.plot(
    ax=ax,
    column=param_name,
    cmap="viridis",
    edgecolor="black",
    linewidth=0.2,
    legend=True,
    legend_kwds={"label": param_name, "shrink": 0.6},
)
ax.set_title(f"v2 HRUs with {param_name} transferred from v1.1")
ax.set_axis_off()
plt.tight_layout()
plt.show()

# %% [markdown]
# ## Write parameter CSV in paramdb format

# %%
# Read nhm_id.csv to verify canonical ordering
nhm_id_order = pd.read_csv(param_source_files_dir / "nhm_id.csv")
print(f"Canonical ordering: {len(nhm_id_order)} HRUs")

# Sort by model_hru_idx_v2
param_result = best_match[["model_hru_idx_v2", "nhm_id_v2", param_name]].sort_values("model_hru_idx_v2").reset_index(drop=True)

# Verify ordering matches nhm_id.csv
assert (param_result["model_hru_idx_v2"].values == nhm_id_order["nhm_id"].values).all(), \
    "ERROR: ordering does not match nhm_id.csv! Check model_hru_idx mapping."
print("Verified: ordering matches nhm_id.csv")

# Write CSV
param_out = pd.DataFrame({
    "$id": param_result["model_hru_idx_v2"].astype(int),
    param_name: param_result[param_name],
})
param_out.to_csv(output_dir / f"{param_name}.csv", index=False)
print(f"Wrote {param_name}.csv: {len(param_out)} rows to {output_dir}")
param_out.head()

# %%
