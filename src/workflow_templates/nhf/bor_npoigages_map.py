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
# # BOR Hydromet QU Gages vs. npoigages Map
#
# Interactive folium map for manually verifying which BOR Hydromet QU stations
# correspond to specific npoigages (resource_gages) POIs.
#
# - **Blue dots**: npoigages (resource_gages)
# - **Yellow dots**: BOR Hydromet stations with QU data (clipped to OHM domain)
#
# Use the popups to compare BOR `nearest_poi_id` / `dist_m` with the
# nearby blue dots to confirm or correct associations.

# %%
import os
import pathlib as pl
import pandas as pd
import geopandas as gpd
import folium

# Find the repo root via the editable-installed `assist` package
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"

# %% [markdown]
# ## Load data

# %%
# BOR Hydromet stations (all with QU data)
bor_csv = root_dir / "data_dependencies" / "hydromet_all_stations.csv"
bor_df = pd.read_csv(bor_csv)
bor_df = bor_df[bor_df["qu_days"] > 0].reset_index(drop=True)
print(f"BOR QU stations (global): {len(bor_df)}")

# npoigages (resource_gages from parent model)
poi_csv = root_dir / "hydrofabric_domain_data" / "OHM_2026_02_21" / "npoigages_data" / "resource_gages.csv"
poi_df = pd.read_csv(poi_csv)
print(f"npoigages (resource_gages): {len(poi_df)}")

# OHM domain boundary for clipping
ohm_gpkg = root_dir / "hydrofabric_domain_data" / "OHM_2026_02_21" / "GIS" / "model_layers.gpkg"
aoi_gdf = gpd.read_file(ohm_gpkg, layer="nhru")
seg_gdf = gpd.read_file(ohm_gpkg, layer="nsegment")
print(f"OHM domain CRS: {aoi_gdf.crs}")
print(f"Segments: {len(seg_gdf)}")

# %% [markdown]
# ## Clip BOR gages to OHM domain

# %%
bor_gdf = gpd.GeoDataFrame(
    bor_df,
    geometry=gpd.points_from_xy(bor_df["longitude"], bor_df["latitude"]),
    crs="EPSG:4326",
)
bor_gdf = bor_gdf.to_crs(aoi_gdf.crs)
bor_clipped = gpd.clip(bor_gdf, aoi_gdf).to_crs("EPSG:4326")
bor_clipped = bor_clipped.drop(columns="geometry")
print(f"BOR QU stations in OHM domain: {len(bor_clipped)}")

# %% [markdown]
# ## Build folium map

# %%
# Center map on the mean of clipped BOR stations
center_lat = bor_clipped["latitude"].mean()
center_lon = bor_clipped["longitude"].mean()

m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="OpenStreetMap")

# --- Segments layer (blue lines) ---
seg_layer = folium.FeatureGroup(name="segments", show=True)
seg_4326 = seg_gdf.to_crs("EPSG:4326")
folium.GeoJson(
    seg_4326,
    style_function=lambda x: {"color": "steelblue", "weight": 1.5, "opacity": 0.6},
    tooltip=folium.GeoJsonTooltip(fields=["segment_id"] if "segment_id" in seg_4326.columns else []),
).add_to(seg_layer)
seg_layer.add_to(m)

# --- npoigages markers (blue) ---
poi_markers = folium.FeatureGroup(name="npoigages markers", show=True)
for _, row in poi_df.iterrows():
    if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
        poi_id = str(int(row["poi_gage_id"])) if pd.notna(row["poi_gage_id"]) else ""
        popup_html = (
            f"<b>poi_gage_id:</b> {poi_id}<br>"
            f"<b>poi_name:</b> {row.get('poi_name', '')}<br>"
            f"<b>agency:</b> {row.get('poi_agency', '')}<br>"
            f"<b>lat:</b> {row['latitude']:.5f}<br>"
            f"<b>lon:</b> {row['longitude']:.5f}"
        )
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color="blue",
            fill=True,
            fill_color="blue",
            fill_opacity=0.6,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=poi_id,
        ).add_to(poi_markers)
poi_markers.add_to(m)

# --- npoigages labels (blue, toggleable) ---
poi_labels = folium.FeatureGroup(name="npoigages labels", show=False)
for _, row in poi_df.iterrows():
    if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
        poi_id = str(int(row["poi_gage_id"])) if pd.notna(row["poi_gage_id"]) else ""
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            icon=folium.DivIcon(
                icon_size=(0, 0),
                icon_anchor=(0, 0),
                html=f'<span style="font-size:10px;color:blue;font-weight:bold;white-space:nowrap;">{poi_id}</span>',
            ),
        ).add_to(poi_labels)
poi_labels.add_to(m)

# --- BOR QU markers (yellow, clipped to OHM) ---
bor_markers = folium.FeatureGroup(name="BOR QU markers", show=True)
for _, row in bor_clipped.iterrows():
    if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
        nearest = row.get("nearest_poi_id", "")
        # Format nearest_poi_id as integer(s)
        if pd.notna(nearest) and nearest != "":
            nearest = ";".join(str(int(float(x))) if "." in x else x for x in str(nearest).split(";"))
        popup_html = (
            f"<b>cbtt:</b> {row['cbtt']}<br>"
            f"<b>name:</b> {row['name']}<br>"
            f"<b>qu_days:</b> {row['qu_days']}<br>"
            f"<b>nearest_poi_id:</b> {nearest}<br>"
            f"<b>dist_m:</b> {row.get('dist_m', '')}<br>"
            f"<b>lat:</b> {row['latitude']:.5f}<br>"
            f"<b>lon:</b> {row['longitude']:.5f}<br>"
            f"<b>elev_ft:</b> {row.get('elevation_ft', '')}"
        )
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=7,
            color="goldenrod",
            fill=True,
            fill_color="yellow",
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=row["cbtt"],
        ).add_to(bor_markers)
bor_markers.add_to(m)

# --- BOR QU labels (yellow, toggleable) ---
bor_labels = folium.FeatureGroup(name="BOR QU labels", show=True)
for _, row in bor_clipped.iterrows():
    if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
        nearest = row.get("nearest_poi_id", "")
        if pd.notna(nearest) and nearest != "":
            nearest = ";".join(str(int(float(x))) if "." in x else x for x in str(nearest).split(";"))
        label = f'{row["cbtt"]} ({nearest})'
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            icon=folium.DivIcon(
                icon_size=(0, 0),
                icon_anchor=(0, 0),
                html=f'<span style="font-size:10px;color:#b8860b;font-weight:bold;white-space:nowrap;">{label}</span>',
            ),
        ).add_to(bor_labels)
bor_labels.add_to(m)

# Layer control toggle
folium.LayerControl().add_to(m)

m

# %% [markdown]
# ## Export clipped BOR stations with matched poi_name

# %%
# Join poi_name from resource_gages onto clipped BOR stations via nearest_poi_id
poi_lookup = poi_df.set_index("poi_gage_id")["poi_name"].to_dict()

def get_poi_names(nearest_id):
    """Look up poi_name(s) for semicolon-separated nearest_poi_id."""
    if pd.isna(nearest_id) or str(nearest_id).strip() == "":
        return ""
    names = []
    for pid in str(nearest_id).split(";"):
        try:
            key = int(float(pid))
        except (ValueError, TypeError):
            key = pid
        names.append(str(poi_lookup.get(key, "")))
    return ";".join(names)

bor_export = bor_clipped.copy()
bor_export["poi_name_match"] = bor_export["nearest_poi_id"].apply(get_poi_names)

# Reorder columns for readability
export_cols = ["cbtt", "name", "latitude", "longitude", "qu_days", "nearest_poi_id", "poi_name_match", "dist_m", "elevation_ft"]
export_cols = [c for c in export_cols if c in bor_export.columns]
bor_export = bor_export[export_cols]

out_path = root_dir / "hydrofabric_domain_data" / "OHM_2026_02_21" / "npoigages_data" / "BOR_QU_domain_review.csv"
bor_export.to_csv(out_path, index=False)
print(f"Saved {len(bor_export)} clipped BOR stations to:\n  {out_path}")
display(bor_export)

# %%
len(bor_export)
