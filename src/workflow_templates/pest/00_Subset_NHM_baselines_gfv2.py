# ---
# jupyter:
#   jupytext:
#     formats: pestpp_ies_calibration/notebooks//ipynb,src/workflow_templates/pest//py:percent
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
import os
import pathlib as pl
import warnings
import pandas as pd
import xarray as xr
import numpy as np
import shutil

warnings.filterwarnings("ignore")
from rich.console import Console

con = Console()
from rich import pretty

pretty.install()
import jupyter_black

jupyter_black.load()
import io

# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg

from contextlib import redirect_stdout

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"
from assist.nhf.nhm_hydrofabric_v2 import make_hf_map_elements
from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config

config = load_subdomain_config(root_dir)

# %% [markdown]
# # Introduction
#
# This notebook subsets the CONUS-scale NHM (National Hydrologic Model) baseline target datasets to the spatial and temporal extent of a user-specified subdomain model. The resulting observation NetCDF files are written to the subdomain's `pestpp_ies/observation_data/` directory and serve as calibration targets for PEST++ IES (Iterative Ensemble Smoother) in the subsequent notebooks of this workflow.
#
# **This notebook only needs to be run once per subdomain extraction.**
#
# ---
#
# ## Summary of Steps
#
# 1. **Load configuration and hydrofabric elements** -- Read the subdomain configuration (`load_subdomain_config`) and build HRU/segment GeoDataFrames, gage lists, and POI tables via `make_hf_map_elements`.
#
# 2. **Create output directories** -- Ensure `pestpp_ies/`, `pestpp_ies/observation_data/`, and `pestpp_ies/ancillary/` folders exist under the subdomain model directory.
#
# 3. **Copy ancillary template** -- Copy `target_and_output_vars_table.csv` into the ancillary directory for downstream reference.
#
# 4. **Build the HRU crosswalk** -- Map the child model's `nhm_id` (which is actually the parent model's `hru_id`) to the parent model's national `nhm_id` so the correct HRUs can be selected from CONUS baseline datasets. This will not be the case for a custom derived modeling fabric, such as the Oregon Recharge Model modeling hydrofabric with more hrus than the planned gfv2 modeling fabric release. In these cases, the nhm_id will be set to the custom derived modeling fabrics local indices. The crosswalk will technically be unnessessary, but the workflow will hold for all modeling fabrics.
#
# 5. **Define calibration periods** -- Assign variable-specific calibration windows.
#
# 6. **Subset and write observation targets for each variable:**
#    - **AET (Actual Evapotranspiration)** -- Monthly upper/lower bounds and mean-monthly climatology (`AET_monthly.nc`, `AET_mean_monthly.nc`).
#    - **HRU Streamflow (Runoff)** -- Monthly upper/lower bounds (`hru_streamflow_monthly.nc`).
#    - **Recharge** -- Annual upper/lower bounds as average daily rates (`RCH_annual.nc`).
#    - **Soil Moisture** -- Annual and monthly upper/lower bounds (`Soil_Moisture_annual.nc`, `Soil_Moisture_monthly.nc`).
#    - **Snow Water Equivalent (SWE)** -- Daily bounds, monthly mean, and 5-day resampled mean (`SWE.nc`, `SWE_monthly.nc`, `SWE_5day_avg.nc`).
#
# 7. **Visual QA/QC** -- Interactive Plotly maps and time-series plots verify spatial alignment (crosswalk links) and inspect SWE target bounds at daily, 5-day averaged, weekly, and monthly temporal resolutions.

# %% jupyter={"source_hidden": true}
(
    hru_gdf,
    hru_txt,
    # hru_cal_level_txt,
    seg_gdf,
    seg_txt,
    waterdata_gages_aoi,
    poi_df,
    gages_df,
    gages_txt,
    gages_txt_nb2,
    # HW_basins_gdf,
    # HW_basins,
) = make_hf_map_elements(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    control_file_name=config["control_file_name"],
    waterdata_gages_file=config["waterdata_gages_file"],
    gages_file=config["gages_file"],
    resource_gages_file=config["resource_gages_file"],
    default_gages_file=config["default_gages_file"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
)

# %% [markdown]
# ## Directory Setup

# %% [markdown]
# #### Set Pestpp-iES directory and make a pestpp-ies directory in the subdomain model folder
# The pestpp-ies directory in the subdomain model folder will contain all files for running pestpp-ies.

# %%
if not (config["model_dir"] / "pestpp_ies").exists():
    (config["model_dir"] / "pestpp_ies").mkdir()
pestpp_model_dir = config["model_dir"] / "pestpp_ies"
pestpp_dir = pl.Path("../").resolve()

# %% [markdown]
# #### Make observation_data folder in the subbasin model directory

# %%
if not (pestpp_model_dir / "observation_data").exists():
    (pestpp_model_dir / "observation_data").mkdir()
obsdir = pestpp_model_dir / "observation_data"

# %%
if not (pestpp_model_dir / "ancillary").exists():
    (pestpp_model_dir / "ancillary").mkdir()
ancillary_dir = pestpp_model_dir / "ancillary"

# %% [markdown]
# ## Review available HRU calibration targets

# %%
baselines_dir = pestpp_dir / "data_dependencies/OHM_targets"
[i.name for i in baselines_dir.glob("*.nc")]

# %% [markdown]
# ## Select calibration and validation periods for each HRU calibrations target
# Approach as of 08-25-26, take the most recent 12 years of data from each HRU target. 

# %%
# Copy template to subdomain model folder for editing (skip if already present)
source = (
    pestpp_dir / "data_dependencies/ancillary_template/target_and_output_vars_table.csv"
)
destination = ancillary_dir / "target_and_output_vars_table.csv"

if destination.exists():
    print(f"File already exists at {destination}, skipping copy.")
else:
    shutil.copy2(source, destination)
    print(f"Copied {source.name} to {destination}")

# %%
cal_config_table = pd.read_csv(
    ancillary_dir / "target_and_output_vars_table.csv",
    dtype=str,
    skipinitialspace=True,
)
cal_config_table

# %% [markdown]
# ### Calibration / validation year split
#
# Each target's period of record is split into **calibration** and
# **validation** years using an odd/even rule: **odd years are used for
# calibration** and **even years are withheld for validation**. Interleaving the
# two by year (rather than, say, taking the first half for calibration) spreads
# both sets across the full climatic range — wet and dry years land in both
# groups — so the validation set is a fair, independent test of the calibrated
# model rather than a different climate regime.
#
# Every target below is filtered to its calibration years before being written
# as an observation. Where a target is aggregated in time (monthly, 5-day), the
# filtering is applied so that no validation-year day contributes to a
# calibration-year value (see the SWE section for the binning details).

# %%
# Build calibration/validation year lists from the config table.
# Each target_id + time_aggregation pair defines a calibration window;
# odd years = calibration, even years = validation.


def _cal_val_years(start, end):
    """Return (cal_years, val_years) from start/end date strings."""
    years = np.arange(pd.to_datetime(start).year, pd.to_datetime(end).year + 1)
    return [int(y) for y in years if y % 2 != 0], [int(y) for y in years if y % 2 == 0]


def _get_period(target_id, time_agg):
    """Look up start/end dates from cal_config_table."""
    row = cal_config_table.loc[
        (cal_config_table["target_id"] == target_id)
        & (cal_config_table["time_aggregation"] == time_agg)
    ].iloc[0]
    return row["start_date"].strip(), row["end_date"].strip()


aet_start, aet_end = _get_period("aet", "monthly")
aet_cal_years, aet_val_years = _cal_val_years(aet_start, aet_end)

recharge_start, recharge_end = _get_period("recharge_norm", "annual")
recharge_cal_years, recharge_val_years = _cal_val_years(recharge_start, recharge_end)

runoff_start, runoff_end = _get_period("runoff", "monthly")
runoff_cal_years, runoff_val_years = _cal_val_years(runoff_start, runoff_end)

soil_rechr_start, soil_rechr_end = _get_period("soil_moist_norm", "monthly")
soil_rechr_cal_years, soil_rechr_val_years = _cal_val_years(
    soil_rechr_start, soil_rechr_end
)

swe_start, swe_end = _get_period("swe", "monthly")
swe_cal_years, swe_val_years = _cal_val_years(swe_start, swe_end)

# %%
swe_cal_years

# %% [markdown]
# ### Subset AET NHM baseline data

# %%
# Use larger, manual chunks for efficiency
AET_all = xr.open_dataset(
    baselines_dir / "aet_targets.nc", chunks={"time": 12, "nhru": 500}
)

# %%
AET_all

# %% [markdown]
# #### Quick spatial check of the target data as referrenced by nhm_id to the model HRUs by nhm_id

# %%
# Step 1: Load parent geopackage and create cross-walk table for nhm_id for the child model.
import geopandas as gpd

# Load the nhru layer from the parent model geopackage
parent_gpkg = root_dir / "hydrofabric_domain_data/OHM_2026_02_21/GIS/model_layers.gpkg"
parent_hru_gdf = gpd.read_file(parent_gpkg, layer="nhru")

# %% [markdown]
# #### Crosswalk: child model `nhm_id` to parent model `nhm_id`
#
# The child model's `nhm_id` parameter (from the param file) is actually the **parent model's `hru_id`** (local index), not the national HRU identifier. To select the correct HRUs from the CONUS baseline datasets (which use the parent's `nhm_id`), we need a crosswalk:
#
# - **Parent gpkg** has: `nhm_id` (national ID) and `hru_id` (parent-local index)
# - **Child model** has: `nhm_id` (= parent's `hru_id`) and `hru_id` (child-local index)
#
# Join: `child nhm_id` == `parent hru_id` → retrieve `parent nhm_id`
#
# Add an ! emoji here

# %%
# Crosswalk: child model nhm_id (= parent hru_id) -> parent nhm_id
# The child's "nhm_id" param is actually the parent's local hru_id.
# Look up each child nhm_id in the parent gpkg's hru_id column to get the parent nhm_id.

crosswalk = parent_hru_gdf[["nhm_id", "hru_id"]].copy()
crosswalk = crosswalk.rename(
    columns={"nhm_id": "parent_nhm_id", "hru_id": "parent_hru_id"}
)

# nhm_ids from child param file = parent's hru_id
nhm_ids = pws.parameters.PrmsParameters.load(
    config["model_dir"] / config["param_file"]
).parameters["nhm_id"]
child_df = pd.DataFrame({"child_nhm_id": nhm_ids})
child_df["child_hru_id"] = range(1, len(nhm_ids) + 1)  # child local index (1-based)

# Join: child_nhm_id == parent_hru_id to get the parent_nhm_id
xwalk = child_df.merge(
    crosswalk, left_on="child_nhm_id", right_on="parent_hru_id", how="left"
)

print(f"Child HRUs: {len(child_df)}")
print(f"Matched to parent nhm_id: {xwalk['parent_nhm_id'].notna().sum()}")
print(f"Unmatched: {xwalk['parent_nhm_id'].isna().sum()}")

nhm_ids = list(xwalk["parent_nhm_id"])

# %% [markdown]
# #### Ship the HRU crosswalk for the remote forward run
#
# The subset observation `.nc` files (and therefore `allobs.dat`) are keyed by
# the parent **national** `nhm_id`. But the pywatershed param file that the
# remote `forward_run_gfv2` loads carries only the parent-**local** `hru_id`
# (stored under the name `nhm_id`), and the parent geopackage used to build this
# crosswalk is not shipped to the remote run. To keep the model-output
# observation names (`modelobs.dat`) internally consistent with `allobs.dat`,
# write the `hru_id -> parent_nhm_id` mapping to a small CSV that ships with the
# other remote run files. `forward_run_gfv2` loads it and relabels its HRU axis
# from the local `hru_id` to the national `nhm_id` before writing observations.

# %%
# child_nhm_id here is the value stored as "nhm_id" in the pywatershed param
# file, which is actually the parent's local hru_id. parent_nhm_id is the
# national id used by the observation targets.
hru_crosswalk_df = xwalk[["child_nhm_id", "parent_nhm_id"]].rename(
    columns={"child_nhm_id": "hru_id", "parent_nhm_id": "nhm_id"}
)
hru_crosswalk_df.to_csv(pestpp_model_dir / "hru_nhm_id_crosswalk.csv", index=False)
con.print(
    f"Wrote HRU crosswalk ({len(hru_crosswalk_df)} rows) to "
    f"{pestpp_model_dir / 'hru_nhm_id_crosswalk.csv'}"
)

# %% [markdown]
# #### Subset the target datasets by centroid, not by `nhm_id`
#
# **Why not just select by `nhm_id`?** The `nhm_id` coordinate stored *inside*
# the CONUS target files (`aet_targets.nc`, `recharge_targets.nc`, etc.) is
# **not** the same national identifier as the parent hydrofabric geopackage.
# Spot-checking this subdomain, every one of the model's HRUs matches a target
# grid point almost exactly in space (nearest-neighbor separations are a small
# fraction of a degree), yet the target file's `nhm_id` at that location
# disagrees with the geopackage's national `nhm_id` for **100%** of the HRUs
# (0 of 619 agree). In other words, the target files' locations are trustworthy
# but their `nhm_id` labels are not.
#
# **The fix (applied uniformly to every target below):**
# 1. Match each model HRU to a target grid point by **centroid location** using
#    a nearest-neighbor search. The query points are the model's own HRU
#    centroids (`hru_lat` / `hru_lon` from the pywatershed param file); the
#    candidate points are the target file's `lat` / `lon`.
# 2. Select the target rows at those matched positions (`isel`).
# 3. **Relabel** the selected rows with the **geopackage national `nhm_id`**
#    (`nhm_ids`, in model param-file order), discarding the target file's own
#    unreliable `nhm_id`.
#
# All six target files share an identical HRU layout (same `nhm_id` dimension
# length of 16814, with 1-D `lat` / `lon` indexed by that dimension in the same
# order). So the centroid -> row-position mapping is computed **once** here and
# reused for every target via the `subset_target_by_centroid` helper. This keeps
# the spatial identity of every subset target consistent with each other, with
# the geopackage, and with the model.
#
# A tolerance guard warns if any HRU's nearest target point is farther than
# `MATCH_TOL_DEG` away, which would indicate a domain/projection problem rather
# than the expected near-coincident grid match.

# %%
from scipy.spatial import cKDTree

# National nhm_id for each model HRU, in model param-file order (from the
# geopackage crosswalk above). This is the identifier we relabel targets with.
national_nhm_ids = np.asarray([int(i) for i in nhm_ids], dtype=int)

# Model HRU centroids from the pywatershed param file (the model's own
# definition of each HRU location), in param-file order.
_pardat = pws.parameters.PrmsParameters.load(config["model_dir"] / config["param_file"])
model_hru_lat = np.asarray(_pardat.parameters["hru_lat"], dtype=float)
model_hru_lon = np.asarray(_pardat.parameters["hru_lon"], dtype=float)

# Warn (rather than silently mismatch) if any centroid match is implausibly far.
# ~0.1 deg is roughly 11 km; expected matches are a small fraction of a degree.
MATCH_TOL_DEG = 0.1


def _match_positions_by_centroid(target_ds):
    """Return target-file row positions (into the nhm_id dim) nearest to each
    model HRU centroid, matching on (lon, lat)."""
    t_lon = target_ds["lon"].values
    t_lat = target_ds["lat"].values
    tree = cKDTree(np.column_stack([t_lon, t_lat]))
    dist, pos = tree.query(np.column_stack([model_hru_lon, model_hru_lat]), k=1)
    n_far = int(np.sum(dist > MATCH_TOL_DEG))
    if n_far > 0:
        con.print(
            f"[bold yellow]Warning:[/bold yellow] {n_far} of {len(dist)} HRU(s) "
            f"matched a target point farther than {MATCH_TOL_DEG} deg "
            f"(max {dist.max():.4f} deg). Check the target/domain alignment."
        )
    return pos


def subset_target_by_centroid(target_ds):
    """Subset a CONUS target dataset to this model's HRUs by centroid match, and
    relabel the nhm_id coordinate with the geopackage national nhm_id (in model
    param-file order). The target file's own (unreliable) nhm_id is discarded."""
    pos = _match_positions_by_centroid(target_ds)
    subset = target_ds.isel(nhm_id=pos)
    subset = subset.assign_coords(nhm_id=("nhm_id", national_nhm_ids))
    return subset


# %%
# Interactive map: compare parent gpkg centroids vs AET_all centroids (plotly)
import plotly.graph_objects as go

# Parent gpkg centroids (reproject to WGS84)
parent_hru_gdf_wgs = parent_hru_gdf.to_crs(epsg=4326)
parent_hru_gdf_wgs["centroid_lat"] = parent_hru_gdf_wgs.geometry.centroid.y
parent_hru_gdf_wgs["centroid_lon"] = parent_hru_gdf_wgs.geometry.centroid.x

# AET point locations (entire AET domain, not clipped)
aet_all_lats = AET_all["lat"].values
aet_all_lons = AET_all["lon"].values
aet_all_ids = AET_all["nhm_id"].values

# Interactive Folium map (same style family as the hydrofabric viz notebook):
# selectable basemaps, toggleable point layers, hover/click popups, and smooth
# scroll-zoom. Three layers:
#   - Parent gpkg centroids (blue), labeled by national nhm_id
#   - AET_all centroids -- ALL points in the AET dataset (red), labeled by
#     national nhm_id. AET_all is CONUS-scale, so this can be many thousands of
#     points; they are clustered (FastMarkerCluster) to keep the map responsive.
#   - Crosswalk links (green) connecting the SAME national nhm_id in both
#     datasets -- follow a green line to compare a matched pair rather than
#     eyeballing neighboring markers.
import folium
from folium.plugins import FastMarkerCluster

# Build lookups keyed by national nhm_id for the crosswalk links
xwalk_matched = xwalk[xwalk["parent_nhm_id"].notna()].copy()
gpkg_lookup = parent_hru_gdf_wgs.set_index("nhm_id")[["centroid_lat", "centroid_lon"]]
aet_lookup = pd.DataFrame(
    {
        "nhm_id": aet_all_ids,
        "aet_lat": aet_all_lats,
        "aet_lon": aet_all_lons,
    }
).set_index("nhm_id")

_center = [
    float(parent_hru_gdf_wgs["centroid_lat"].mean()),
    float(parent_hru_gdf_wgs["centroid_lon"].mean()),
]
centroid_map = folium.Map(location=_center, zoom_start=7, tiles=None)

# Selectable basemaps (USGS Hydro shown by default; others available in the
# layer control).
folium.TileLayer(
    tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSHydroCached/MapServer/tile/{z}/{y}/{x}",
    attr="USGSHydroCached",
    name="USGS Hydro",
).add_to(centroid_map)
folium.TileLayer(
    tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
    attr="USGS_topo",
    name="USGS Topography",
    show=False,
).add_to(centroid_map)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery",
    name="Esri Imagery",
    show=False,
).add_to(centroid_map)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False).add_to(centroid_map)

# Parent gpkg centroids (blue)
gpkg_layer = folium.FeatureGroup(name="Parent gpkg (nhm_id)", show=True)
for _, r in parent_hru_gdf_wgs.iterrows():
    folium.CircleMarker(
        location=[r["centroid_lat"], r["centroid_lon"]],
        radius=4,
        color="blue",
        fill=True,
        fill_opacity=0.6,
        weight=1,
        popup=folium.Popup(f"gpkg nhm_id: {int(r['nhm_id'])}", max_width=200),
        tooltip=f"gpkg nhm_id: {int(r['nhm_id'])}",
    ).add_to(gpkg_layer)
gpkg_layer.add_to(centroid_map)

# AET_all centroids -- ALL points in the AET dataset (red). Because AET_all is
# CONUS-scale (many thousands of points), draw them via FastMarkerCluster so the
# map stays responsive; markers de-cluster into individual points as you zoom in.
aet_layer = folium.FeatureGroup(name="AET_all (all points)", show=True)
# FastMarkerCluster takes [lat, lon, nhm_id] rows; a JS callback renders each as
# a red circle marker with an nhm_id popup/tooltip.
_aet_callback = (
    "function (row) {"
    "  var marker = L.circleMarker(new L.LatLng(row[0], row[1]),"
    "    {radius: 3, color: 'red', fillColor: 'red', fillOpacity: 0.7, weight: 1});"
    "  marker.bindPopup('AET_all nhm_id: ' + row[2]);"
    "  marker.bindTooltip('AET_all nhm_id: ' + row[2]);"
    "  return marker;"
    "}"
)
_aet_data = [
    [float(_lat), float(_lon), int(_id)]
    for _lat, _lon, _id in zip(aet_all_lats, aet_all_lons, aet_all_ids)
]
FastMarkerCluster(data=_aet_data, callback=_aet_callback).add_to(aet_layer)
aet_layer.add_to(centroid_map)

# Crosswalk links (green): connect the SAME national nhm_id in both datasets
link_layer = folium.FeatureGroup(name="Crosswalk links (same nhm_id)", show=True)
for _, row in xwalk_matched.iterrows():
    pid = int(row["parent_nhm_id"])
    if pid in gpkg_lookup.index and pid in aet_lookup.index:
        g = gpkg_lookup.loc[pid]
        a = aet_lookup.loc[pid]
        folium.PolyLine(
            locations=[
                [g["centroid_lat"], g["centroid_lon"]],
                [a["aet_lat"], a["aet_lon"]],
            ],
            color="green",
            weight=1,
            opacity=0.6,
            tooltip=f"nhm_id: {pid}",
        ).add_to(link_layer)
link_layer.add_to(centroid_map)

folium.LayerControl(collapsed=False).add_to(centroid_map)

centroid_map

# %% [markdown]
# #### Verify same-`nhm_id` points are co-located (numeric check)
#
# The map above is easy to misread: the blue (parent gpkg) and red (`AET_all`)
# marker clouds are *not* paired by position, and the red cloud now includes
# every AET HRU in the (CONUS-scale) dataset -- the vast majority of which are
# not in this child model. So hovering compares *neighboring* HRUs, whose
# national `nhm_id`s legitimately differ.
#
# The check below instead matches strictly **by national `nhm_id`** (the id that
# should be identical in both datasets) and reports how far apart each shared id
# sits in the two datasets. If the distances are tiny, the ids and locations are
# consistent and the visual "mismatch" is just unpaired neighbors. Large
# distances would indicate a genuine centroid-definition or projection
# difference (gpkg polygon centroid computed in EPSG:4326 vs. the `lat`/`lon`
# stored in `AET_all`).

# %%
# gpkg centroids keyed by national nhm_id (computed above in parent_hru_gdf_wgs)
_gpkg_pts = parent_hru_gdf_wgs.set_index("nhm_id")[["centroid_lat", "centroid_lon"]]
# AET_all stored locations keyed by national nhm_id
_aet_pts = pd.DataFrame(
    {"nhm_id": aet_all_ids, "aet_lat": aet_all_lats, "aet_lon": aet_all_lons}
).set_index("nhm_id")

# Compare only the national nhm_ids that belong to THIS child model
_model_nhm_ids = [int(i) for i in nhm_ids if pd.notna(i)]
_shared = [i for i in _model_nhm_ids if i in _gpkg_pts.index and i in _aet_pts.index]

id_check = pd.DataFrame(index=_shared)
id_check["gpkg_lat"] = _gpkg_pts.loc[_shared, "centroid_lat"].values
id_check["aet_lat"] = _aet_pts.loc[_shared, "aet_lat"].values
id_check["gpkg_lon"] = _gpkg_pts.loc[_shared, "centroid_lon"].values
id_check["aet_lon"] = _aet_pts.loc[_shared, "aet_lon"].values
# Approximate separation in km (1 deg lat ~= 111 km; scale lon by cos(lat))
_dlat = id_check["gpkg_lat"] - id_check["aet_lat"]
_dlon = (id_check["gpkg_lon"] - id_check["aet_lon"]) * np.cos(
    np.radians(id_check["gpkg_lat"])
)
id_check["dist_km"] = np.hypot(_dlat, _dlon) * 111.0

_n_model = len(_model_nhm_ids)
_n_shared = len(_shared)
_n_missing_aet = sum(
    1 for i in _model_nhm_ids if i in _gpkg_pts.index and i not in _aet_pts.index
)
con.print(
    f"Model HRUs (national nhm_id): {_n_model} | matched in both gpkg & AET_all: "
    f"{_n_shared} | in gpkg but not AET_all: {_n_missing_aet}"
)
con.print(
    f"Same-id separation (km) -> max: {id_check['dist_km'].max():.3f}, "
    f"mean: {id_check['dist_km'].mean():.3f}"
)

# Show the worst offenders, if any (largest same-id separations)
id_check.sort_values("dist_km", ascending=False).head(10)

# %%
# Centroid-match to this model's HRUs (relabels nhm_id with the gpkg national
# id), then restrict to the calibration years.
c_da = subset_target_by_centroid(AET_all)
c_da = c_da.sel(time=c_da["time.year"].isin(aet_cal_years))

# Always pre-load before writing for speed
# c_da[["upper_bound", "lower_bound"]].load().to_netcdf(obsdir / f"AET_monthly.nc")
c_da.load().to_netcdf(obsdir / f"AET_monthly.nc")

# Compute mean in memory, then write
c_da.groupby("time.month").mean().load().to_netcdf(obsdir / f"AET_mean_monthly.nc")

AET_all.close()

# %% [markdown]
# ### Peek at AET targets

# %%
import plotly.graph_objects as go
import plotly.colors as pc

# Pick a representative HRU to inspect
aet_hru_sel = nhm_ids[0]

# Load subset data for plotting
AET_plot = xr.open_dataset(obsdir / "AET_monthly.nc")
AET_mean_monthly = xr.open_dataset(obsdir / "AET_mean_monthly.nc")

# Extract time series for selected HRU
members = ["mod16a2_v061", "ssebop", "mwbm_climgrid"]
member_colors = pc.qualitative.Set2[: len(members)]

fig_aet = go.Figure()

# Plot individual ensemble members
for member, color in zip(members, member_colors):
    if member in AET_plot:
        ts = AET_plot[member].sel(nhm_id=aet_hru_sel)
        fig_aet.add_trace(
            go.Scatter(
                x=ts.time.values,
                y=ts.values,
                mode="lines",
                name=member,
                line=dict(color=color, width=1),
                opacity=0.7,
            )
        )

# Ensemble mean +/- std shading
ens_mean = AET_plot["ensemble_mean"].sel(nhm_id=aet_hru_sel)
ens_std = AET_plot["ensemble_std"].sel(nhm_id=aet_hru_sel)

fig_aet.add_trace(
    go.Scatter(
        x=np.concatenate([ens_mean.time.values, ens_mean.time.values[::-1]]),
        y=np.concatenate(
            [(ens_mean + ens_std).values, (ens_mean - ens_std).values[::-1]]
        ),
        fill="toself",
        fillcolor="rgba(100,100,100,0.2)",
        line=dict(width=0),
        name="Mean +/- 1 Std",
        showlegend=True,
    )
)

fig_aet.add_trace(
    go.Scatter(
        x=ens_mean.time.values,
        y=ens_mean.values,
        mode="lines",
        name="Ensemble Mean",
        line=dict(color="black", width=2),
    )
)

# Mean monthly climatology (repeated across years for visual reference)
mean_mon = AET_mean_monthly["ensemble_mean"].sel(nhm_id=aet_hru_sel)
std_mon = AET_mean_monthly["ensemble_std"].sel(nhm_id=aet_hru_sel)
# Build a synthetic time axis by mapping month number back to the time series
month_map_mean = pd.Series(mean_mon.values, index=mean_mon.month.values)
month_map_std = pd.Series(std_mon.values, index=std_mon.month.values)
monthly_ref = pd.Series(ens_mean.time.values).dt.month.map(month_map_mean)
monthly_std_ref = pd.Series(ens_mean.time.values).dt.month.map(month_map_std)

fig_aet.add_trace(
    go.Scatter(
        x=np.concatenate([ens_mean.time.values, ens_mean.time.values[::-1]]),
        y=np.concatenate(
            [
                (monthly_ref + monthly_std_ref).values,
                (monthly_ref - monthly_std_ref).values[::-1],
            ]
        ),
        fill="toself",
        fillcolor="rgba(128,0,128,0.15)",
        line=dict(width=0),
        name="Mean Monthly +/- 1 Std",
        showlegend=True,
    )
)

fig_aet.add_trace(
    go.Scatter(
        x=ens_mean.time.values,
        y=monthly_ref.values,
        mode="lines",
        name="Mean Monthly Climatology",
        line=dict(color="purple", width=2, dash="dash"),
    )
)

fig_aet.update_layout(
    title=f"AET Ensemble Members & Statistics (nhm_id={aet_hru_sel})",
    xaxis_title="Time",
    yaxis_title="AET (inches/day)",
    height=500,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_aet.show()

AET_plot.close()
AET_mean_monthly.close()

# %% [markdown]
# ### AET Mean Monthly Climatology

# %% jupyter={"source_hidden": true}
# Reload mean monthly for climatology plot
AET_mean_monthly = xr.open_dataset(obsdir / "AET_mean_monthly.nc")

mean_mon = AET_mean_monthly["ensemble_mean"].sel(nhm_id=aet_hru_sel)
std_mon = AET_mean_monthly["ensemble_std"].sel(nhm_id=aet_hru_sel)
months = mean_mon.month.values

fig_aet_mm = go.Figure()

# Std shading
fig_aet_mm.add_trace(
    go.Scatter(
        x=np.concatenate([months, months[::-1]]),
        y=np.concatenate(
            [(mean_mon + std_mon).values, (mean_mon - std_mon).values[::-1]]
        ),
        fill="toself",
        fillcolor="rgba(128,0,128,0.15)",
        line=dict(width=0),
        name="Mean +/- 1 Std",
    )
)

# Mean line
fig_aet_mm.add_trace(
    go.Scatter(
        x=months,
        y=mean_mon.values,
        mode="lines+markers",
        name="Mean Monthly",
        line=dict(color="purple", width=2),
        marker=dict(size=6),
    )
)

fig_aet_mm.update_layout(
    title=f"AET Mean Monthly Climatology (nhm_id={aet_hru_sel})",
    xaxis_title="Month",
    yaxis_title="AET (inches/day)",
    xaxis=dict(
        tickmode="array",
        tickvals=list(range(1, 13)),
        ticktext=[
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
    ),
    height=400,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_aet_mm.show()

AET_mean_monthly.close()

# %% [markdown]
# ###  Subset HRU Streamflow (RUNOFF NHM) baseline data--The MWBM term, "runoff" is total contribution to streamflow from each HRU. We are re-terming this in the subset file to "hru_streamflow" to clearly describe HRU contributions to streamflow.

# %%
RUN_all = xr.open_dataset(baselines_dir / "runoff_targets.nc", chunks="auto")
# RUN_all

# %%
c_da = subset_target_by_centroid(RUN_all)
c_da = c_da.sel(time=c_da["time.year"].isin(runoff_cal_years))
c_da.to_netcdf(obsdir / f"hru_streamflow_monthly.nc")
RUN_all.close()

# %% [markdown]
# ### Subset Annual Recharge
# ### These annual values are actually the average daily rate; and, match the units of the output.

# %%
RCH_all = xr.open_dataset(baselines_dir / "recharge_targets.nc", chunks="auto")
# RCH_all

# %%
recharge_cal_years

# %%
c_da = subset_target_by_centroid(RCH_all)
c_da = c_da.sel(time=c_da["time.year"].isin(recharge_cal_years))
c_da.to_netcdf(obsdir / f"RCH_annual.nc")
RCH_all.close()

# %% [markdown]
# ### Peek at Recharge targets

# %%
rch_hru_sel = nhm_ids[100]

RCH_plot = xr.open_dataset(obsdir / "RCH_annual.nc")

rch_members = ["reitz2017", "era5_land"]
rch_member_colors = pc.qualitative.Set2[: len(rch_members)]

fig_rch = go.Figure()

# Plot individual ensemble members
for member, color in zip(rch_members, rch_member_colors):
    if member in RCH_plot:
        ts = RCH_plot[member].sel(nhm_id=rch_hru_sel)
        fig_rch.add_trace(
            go.Scatter(
                x=ts.time.values,
                y=ts.values,
                mode="lines+markers",
                name=member,
                line=dict(color=color, width=1),
                marker=dict(size=5),
                opacity=0.7,
            )
        )

# Ensemble mean +/- std shading
rch_mean = RCH_plot["ensemble_mean"].sel(nhm_id=rch_hru_sel)
rch_std = RCH_plot["ensemble_std"].sel(nhm_id=rch_hru_sel)

fig_rch.add_trace(
    go.Scatter(
        x=np.concatenate([rch_mean.time.values, rch_mean.time.values[::-1]]),
        y=np.concatenate(
            [(rch_mean + rch_std).values, (rch_mean - rch_std).values[::-1]]
        ),
        fill="toself",
        fillcolor="rgba(100,100,100,0.2)",
        line=dict(width=0),
        name="Mean +/- 1 Std",
    )
)

fig_rch.add_trace(
    go.Scatter(
        x=rch_mean.time.values,
        y=rch_mean.values,
        mode="lines+markers",
        name="Ensemble Mean",
        line=dict(color="black", width=2),
        marker=dict(size=6),
    )
)

fig_rch.update_layout(
    title=f"Annual Recharge Ensemble Members & Statistics (nhm_id={rch_hru_sel})",
    xaxis_title="Time",
    yaxis_title="Recharge (normalized 0-1)",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_rch.show()

# %% [markdown]
# ### Subset Annual Soil Moisture

# %%
SOM_ann_all = xr.open_dataset(
    baselines_dir / "soil_moisture_targets_annual.nc", chunks="auto"
)
SOM_ann_all

# %%
c_da = subset_target_by_centroid(SOM_ann_all)
c_da = c_da.sel(time=c_da["time.year"].isin(soil_rechr_cal_years))
c_da.to_netcdf(obsdir / f"Soil_Moisture_annual.nc")
SOM_ann_all.close()

# %% [markdown]
# ### Subset Monthly Soil Moisture

# %%
SOM_mon_all = xr.open_dataset(
    baselines_dir / "soil_moisture_targets_monthly.nc", chunks="auto"
)
print(
    f"Source time range: {SOM_mon_all.time.values[0]} to {SOM_mon_all.time.values[-1]}"
)
print(f"Cal years requested: {soil_rechr_cal_years}")

# %%
c_da = subset_target_by_centroid(SOM_mon_all)
c_da = c_da.sel(time=c_da["time.year"].isin(soil_rechr_cal_years))
c_da.to_netcdf(obsdir / "Soil_Moisture_monthly.nc")
SOM_mon_all.close()

# Compute mean in memory, then write
c_da.groupby("time.month").mean().load().to_netcdf(
    obsdir / f"Soil_Moisture_mean_monthly.nc"
)

# %% [markdown]
# ### Peek at Soil Moisture (monthly) targets

# %%
_sm_hru = nhm_ids[0]
sm_members = ["merra2", "nldas_mosaic", "nldas_noah"]

# Read the written subset file
SM_plot = xr.open_dataset(obsdir / "Soil_Moisture_monthly.nc")
time_vals = SM_plot.time.values

fig_sm = go.Figure()

# Ensemble members (thin lines)
for member, color in zip(sm_members, ["#66c2a5", "#fc8d62", "#8da0cb"]):
    if member in SM_plot:
        vals = SM_plot[member].sel(nhm_id=_sm_hru, method="nearest").values.ravel()
        fig_sm.add_trace(
            go.Scatter(
                x=time_vals,
                y=vals,
                mode="lines",
                name=member,
                line=dict(color=color, width=1),
                connectgaps=False,
            )
        )

# Ensemble mean +/- std shading
_ens_da = SM_plot["ensemble_mean"].sel(nhm_id=_sm_hru, method="nearest")
ens_mean = _ens_da.values.ravel()
ens_std = SM_plot["ensemble_std"].sel(nhm_id=_sm_hru, method="nearest").values.ravel()

fig_sm.add_trace(
    go.Scatter(
        x=np.concatenate([time_vals, time_vals[::-1]]),
        y=np.concatenate([ens_mean + ens_std, (ens_mean - ens_std)[::-1]]),
        fill="toself",
        fillcolor="rgba(100,100,100,0.2)",
        line=dict(width=0),
        name="Mean +/- 1 Std",
        connectgaps=False,
    )
)

# Ensemble mean (thick black line)
fig_sm.add_trace(
    go.Scatter(
        x=time_vals,
        y=ens_mean,
        mode="lines",
        name="Ensemble Mean",
        line=dict(color="black", width=2),
        connectgaps=False,
    )
)

# Mean monthly climatology +/- std
# Compute manually to avoid xarray groupby issues with gapped time coords
_sm_ts = pd.Series(ens_mean, index=pd.DatetimeIndex(time_vals))
_sm_by_month = _sm_ts.groupby(_sm_ts.index.month)
sm_clim_mean = _sm_by_month.mean()
sm_clim_std = _sm_by_month.std()

months_idx = pd.DatetimeIndex(time_vals).month
monthly_ref = sm_clim_mean.loc[months_idx].values
monthly_std_ref = sm_clim_std.loc[months_idx].values

fig_sm.add_trace(
    go.Scatter(
        x=np.concatenate([time_vals, time_vals[::-1]]),
        y=np.concatenate(
            [monthly_ref + monthly_std_ref, (monthly_ref - monthly_std_ref)[::-1]]
        ),
        fill="toself",
        fillcolor="rgba(180,0,180,0.15)",
        line=dict(width=0),
        name="Mean Monthly +/- 1 Std",
        connectgaps=False,
    )
)

# Mean monthly climatology (dashed purple)
fig_sm.add_trace(
    go.Scatter(
        x=time_vals,
        y=monthly_ref,
        mode="lines",
        name="Mean Monthly Climatology",
        line=dict(color="purple", width=2, dash="dash"),
        connectgaps=False,
    )
)

fig_sm.update_layout(
    title=f"Soil Moisture Ensemble Members & Statistics (nhm_id={_sm_hru})",
    xaxis_title="Time",
    yaxis_title="Soil Moisture (normalized 0-1)",
    height=500,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_sm.show()

SM_plot.close()

# %% [markdown]
# ## Subset and pre-process Daily Snow Water Equivalent (SWE)
#
# Three SWE products are written from the daily `swe_targets.nc` baseline, all
# restricted to the **calibration years** (odd years; even years are held out
# for validation):
#
# - `SWE.nc` — daily values, calibration years only.
# - `SWE_monthly.nc` — monthly mean of the daily values.
# - `SWE_5day_avg.nc` — mean over non-overlapping 5-day windows.
#
# **Filtering vs. binning — order matters.** The raw series is *daily*, so the
# monthly and 5-day products are produced by resampling (binning) in time. A
# subtlety of `xarray`/`pandas` resampling is that `resample()` rebuilds a
# *continuous* time axis spanning the earliest-to-latest remaining timestamp. If
# we filtered to the calibration years first and then resampled, resample would
# re-insert every intervening validation year as empty (all-NaN) bins — and, at
# the edges, a bin could straddle a Dec→Jan boundary and mix a calibration year
# with an adjacent validation year.
#
# To keep each product strictly within the calibration years:
#
# - **`SWE.nc` (daily):** filter the daily series to the calibration years
#   directly — no binning, so no boundary effects.
# - **`SWE_monthly.nc`:** resample the daily series to monthly means **first**,
#   then keep only the calibration-year months. (Monthly bins never span a year
#   boundary, so every monthly value contains only that month's days.)
# - **`SWE_5day_avg.nc`:** built from `SWE.nc` (already calibration-only at the
#   daily level), so the 5-day bins can only contain calibration-year days.
#   After resampling we still mask to the calibration years to drop the empty
#   validation-year bins that resample creates across the year gaps.

# %%
# Read the raw data set.
# SWE.nc: filter the DAILY series to the calibration years (no binning here, so
# there are no resample year-boundary effects to worry about).
SWE_daily = xr.open_dataset(baselines_dir / "swe_targets.nc", chunks="auto")
c_da_swe = subset_target_by_centroid(SWE_daily)
c_da_swe = c_da_swe.sel(time=c_da_swe["time.year"].isin(swe_cal_years))
c_da_swe.to_netcdf(obsdir / "SWE.nc")

# %%
# SWE_daily = xr.open_dataset(baselines_dir / "swe_targets.nc", chunks="auto")
# c_da_mo = (
#     SWE_daily.sel(nhm_id=nhm_ids, time=SWE_daily["time.year"].isin(swe_cal_years))
#     .resample(time="1ME")
#     .mean()
# )

# c_da_mo.to_netcdf(obsdir / "SWE_monthly.nc")
# SWE_daily.close()

SWE_daily = xr.open_dataset(baselines_dir / "swe_targets.nc", chunks="auto")

# Monthly mean of daily SWE, restricted to the calibration years.
#
# NOTE: filter the years AFTER resampling, not before. `resample(time="1ME")`
# rebuilds a *continuous* monthly axis spanning the min-to-max of whatever time
# values remain, so selecting the calibration years first (which keeps the first
# and last odd years) causes resample to re-introduce every in-between off year
# as empty (all-NaN) months. Resampling first, then masking to the calibration
# years, yields only the intended months.
c_da_mo = subset_target_by_centroid(SWE_daily).resample(time="1ME").mean()
c_da_mo = c_da_mo.isel(time=c_da_mo["time"].dt.year.isin(swe_cal_years).values)

c_da_mo.to_netcdf(obsdir / "SWE_monthly.nc")
SWE_daily.close()

# %%
c_da_mo

# %%
# 5-day averaged SWE dataset
# Calculation: resample to non-overlapping 5-day windows and compute the mean
# of each window. This produces one value per 5-day period (not a smoothed daily
# series). The first 2 days and last 2 days are dropped so that every retained
# timestamp sits at the center of a complete 5-day window.
#
# NOTE: as with the monthly block, restrict to the calibration years AFTER
# resampling. `resample(time="5D")` rebuilds a continuous 5-day axis spanning
# 1979-2025, re-introducing the off years as empty bins. The following
# `dropna(how="any")` removes bins by data completeness, not by year, so the off
# years must be masked out explicitly.
c_da_swe_5day = c_da_swe.resample(time="5D").mean()
c_da_swe_5day = c_da_swe_5day.isel(
    time=c_da_swe_5day["time"].dt.year.isin(swe_cal_years).values
)
c_da_swe_5day = c_da_swe_5day.dropna(dim="time", how="any")
c_da_swe_5day.attrs["averaging_method"] = (
    "5-day resample mean (non-overlapping 5-day windows)"
)
c_da_swe_5day.to_netcdf(obsdir / "SWE_5day_avg.nc")

SWE_daily.close()

# %% [markdown]
# ### Peek at SWE

# %% jupyter={"source_hidden": true}
import plotly.graph_objects as go
import plotly.colors as pc

hru_sel = [nhm_ids[10], nhm_ids[100], nhm_ids[500]]
colors = pc.qualitative.Set1[: len(hru_sel)]  # distinct colors per HRU
time_slice = slice("2002-11-01", "2008-01-30")


# Reload for plotting (subset already saved)
SWE_plot = xr.open_dataset(obsdir / "SWE.nc")
time_slice_swe = slice(swe_start, swe_end)

# SWE.nc holds only the calibration (odd) years, so whole years are ABSENT from
# the time axis (they are missing timesteps, not NaN values). Plotly would draw
# a straight line across those absent spans regardless of `connectgaps`, because
# there is no NaN between the two real points to break on. Reindex onto a
# continuous daily axis so the missing dates become explicit NaNs; then
# `connectgaps=False` breaks the line over the gaps as intended. The resample/
# rolling plots below inherit these NaNs and their empty windows stay NaN too.
_full_daily = pd.date_range(
    pd.to_datetime(swe_start), pd.to_datetime(swe_end), freq="D"
)
SWE_plot = SWE_plot.reindex(time=_full_daily)

# --- Daily SWE bounds ---
fig = go.Figure()
for hru, color in zip(hru_sel, colors):
    swe_max = SWE_plot["upper_bound"].sel(nhm_id=hru, time=time_slice_swe)
    swe_min = SWE_plot["lower_bound"].sel(nhm_id=hru, time=time_slice_swe)
    fig.add_trace(
        go.Scatter(
            x=swe_max.time.values,
            y=swe_max.values,
            mode="lines",
            name=f"{hru} upper (line)",
            line=dict(color=color),
            connectgaps=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=swe_max.time.values,
            y=swe_max.values,
            mode="markers",
            name=f"{hru} upper (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=swe_min.time.values,
            y=swe_min.values,
            mode="lines",
            name=f"{hru} lower (line)",
            line=dict(color=color, dash="dash"),
            connectgaps=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=swe_min.time.values,
            y=swe_min.values,
            mode="markers",
            name=f"{hru} lower (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig.update_layout(
    title="SWE bounds (daily)",
    xaxis_title="Time",
    yaxis_title="SWE",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig.show()

# %% jupyter={"source_hidden": true}
# --- Weekly mean SWE bounds ---
fig_w = go.Figure()
for hru, color in zip(hru_sel, colors):
    swe_max_w = (
        SWE_plot["upper_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1W")
        .mean()
    )
    swe_min_w = (
        SWE_plot["lower_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1W")
        .mean()
    )
    fig_w.add_trace(
        go.Scatter(
            x=swe_max_w.time.values,
            y=swe_max_w.values,
            mode="lines",
            name=f"{hru} upper (line)",
            line=dict(color=color),
            connectgaps=False,
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=swe_max_w.time.values,
            y=swe_max_w.values,
            mode="markers",
            name=f"{hru} upper (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=swe_min_w.time.values,
            y=swe_min_w.values,
            mode="lines",
            name=f"{hru} lower (line)",
            line=dict(color=color, dash="dash"),
            connectgaps=False,
        )
    )
    fig_w.add_trace(
        go.Scatter(
            x=swe_min_w.time.values,
            y=swe_min_w.values,
            mode="markers",
            name=f"{hru} lower (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_w.update_layout(
    title="SWE bounds (weekly mean)",
    xaxis_title="Time",
    yaxis_title="SWE",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_w.show()

# %% jupyter={"source_hidden": true}
# --- 5-day rolling average SWE bounds ---
fig_5d = go.Figure()
for hru, color in zip(hru_sel, colors):
    swe_max_5d = (
        SWE_plot["upper_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .rolling(time=5, center=True)
        .mean()
    )
    swe_min_5d = (
        SWE_plot["lower_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .rolling(time=5, center=True)
        .mean()
    )
    fig_5d.add_trace(
        go.Scatter(
            x=swe_max_5d.time.values,
            y=swe_max_5d.values,
            mode="lines",
            name=f"{hru} upper (line)",
            line=dict(color=color),
            connectgaps=False,
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=swe_max_5d.time.values,
            y=swe_max_5d.values,
            mode="markers",
            name=f"{hru} upper (points)",
            marker=dict(size=4, color=color),
            visible="legendonly",
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=swe_min_5d.time.values,
            y=swe_min_5d.values,
            mode="lines",
            name=f"{hru} lower (line)",
            line=dict(color=color, dash="dash"),
            connectgaps=False,
        )
    )
    fig_5d.add_trace(
        go.Scatter(
            x=swe_min_5d.time.values,
            y=swe_min_5d.values,
            mode="markers",
            name=f"{hru} lower (points)",
            marker=dict(size=4, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_5d.update_layout(
    title="SWE bounds (5-day rolling average)",
    xaxis_title="Time",
    yaxis_title="SWE",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_5d.show()

# %% jupyter={"source_hidden": true}
# --- Monthly mean SWE bounds ---
fig_m = go.Figure()
for hru, color in zip(hru_sel, colors):
    swe_max_m = (
        SWE_plot["upper_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1ME")
        .mean()
    )
    swe_min_m = (
        SWE_plot["lower_bound"]
        .sel(nhm_id=hru, time=time_slice_swe)
        .resample(time="1ME")
        .mean()
    )
    fig_m.add_trace(
        go.Scatter(
            x=swe_max_m.time.values,
            y=swe_max_m.values,
            mode="lines",
            name=f"{hru} upper (line)",
            line=dict(color=color),
            connectgaps=False,
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=swe_max_m.time.values,
            y=swe_max_m.values,
            mode="markers",
            name=f"{hru} upper (points)",
            marker=dict(size=5, color=color),
            visible="legendonly",
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=swe_min_m.time.values,
            y=swe_min_m.values,
            mode="lines",
            name=f"{hru} lower (line)",
            line=dict(color=color, dash="dash"),
            connectgaps=False,
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=swe_min_m.time.values,
            y=swe_min_m.values,
            mode="markers",
            name=f"{hru} lower (points)",
            marker=dict(size=5, color=color, symbol="diamond"),
            visible="legendonly",
        )
    )

fig_m.update_layout(
    title="SWE bounds (monthly mean)",
    xaxis_title="Time",
    yaxis_title="SWE",
    height=450,
    legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
)
fig_m.show()

# %%
