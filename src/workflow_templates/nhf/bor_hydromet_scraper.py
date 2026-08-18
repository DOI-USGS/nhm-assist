# ---
# jupyter:
#   jupytext:
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
# # Bureau of Reclamation Hydromet — QU (Unregulated Flow)
#
# Retrieves daily estimated unregulated flow (QU parameter) from BoR Pacific
# Northwest Hydromet stations that fall within the model AOI.
#
# **Outputs:**
# - Metadata table (matches gages file format for appending to notebook 1)
# - Daily QU values for integration into the streamflow observations workflow
#
# Hydromet PNW: https://www.usbr.gov/pn/hydromet/

# %% [markdown]
# ## 1. Configuration (from subdomain config)

# %%
import sys
import os
import pathlib as pl
import warnings

import requests
import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
from io import StringIO
import time

warnings.filterwarnings("ignore")

# --- Workspace bridge pattern (NHF) ---
root_folder = "nhf_assist"
root_dir = pl.Path(os.getcwd().rsplit(root_folder, 1)[0] + root_folder)
sys.path.append(str(root_dir.parent))

from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config

config = load_subdomain_config(root_dir)

# Derived from config
MODEL_DIR = config["model_dir"]
START_DATE = config["start_date"]
END_DATE = config["end_date"]
GPKG_PATH = MODEL_DIR / "GIS" / "model_layers.gpkg"

# Parse years from config dates
START_YEAR = int(START_DATE.split("/")[2]) if "/" in START_DATE else int(START_DATE.split("-")[0])
END_YEAR = int(END_DATE.split("/")[2]) if "/" in END_DATE else int(END_DATE.split("-")[0])

print(f"Domain: {config['subdomain']}")
print(f"Period: {START_DATE} to {END_DATE} (years {START_YEAR}-{END_YEAR})")
print(f"GPKG:   {GPKG_PATH}")

# %% [markdown]
# ## 2. Load model AOI (bounding box from HRU layer)

# %%
hru_gdf = gpd.read_file(GPKG_PATH, layer="nhru")
hru_gdf = hru_gdf.to_crs(4326)

# Get bounding box
minx, miny, maxx, maxy = hru_gdf.total_bounds
print(f"AOI bounding box: ({minx:.3f}, {miny:.3f}) to ({maxx:.3f}, {maxy:.3f})")

# %% [markdown]
# ## 3. Known PNW Hydromet stations (Oregon/Washington)
#
# This is the master list of PNW Hydromet stations to check for QU data.
# Stations outside the model AOI will be filtered out.

# %%
# Known PNW Hydromet stations — station_code, name, lat, lon
# Expand this list as needed from https://www.usbr.gov/pn/hydromet/
ALL_HYDROMET_STATIONS = [
    # Klamath
    ("LORO", "Lost River nr Lorella", 42.09, -121.51),
    ("KFLO", "Klamath River at Keno", 42.13, -121.93),
    ("BOBO", "Boyle PP nr Keno", 42.11, -121.93),
    ("JCKO", "JC Boyle PP Tailrace", 42.07, -121.93),
    ("COPW", "Copco #1 PP", 41.96, -122.34),
    ("IGDO", "Iron Gate Dam", 41.93, -122.44),
    # Umatilla / Deschutes
    ("MCKO", "McKay Reservoir nr Pendleton", 45.65, -118.83),
    ("UMAO", "Umatilla River at Yoakum", 45.73, -118.71),
    ("PRDO", "Prineville Reservoir", 44.15, -120.73),
    ("WICO", "Wickiup Reservoir", 43.68, -121.69),
    ("CRCO", "Crane Prairie Reservoir", 43.79, -121.77),
    ("BENO", "Bend", 44.06, -121.31),
    # Rogue River
    ("LSRO", "Lost Creek Dam", 42.67, -122.66),
    ("GRTO", "Gold Ray Dam", 42.43, -122.79),
    # Willamette
    ("DEHO", "Dexter Dam", 43.92, -122.81),
    ("HILO", "Hills Creek Dam", 43.71, -122.42),
    ("CGRO", "Cottage Grove Dam", 43.72, -123.05),
    ("DTRO", "Detroit Dam", 44.72, -122.25),
    ("GPRO", "Green Peter Dam", 44.45, -122.55),
    ("FBKO", "Foster Dam", 44.42, -122.67),
    # Owyhee
    ("OWYO", "Owyhee Dam", 43.67, -117.25),
    # Boise / Payette (Idaho but may be relevant)
    ("ARKI", "Arrowrock Dam", 43.60, -115.93),
    ("ANDI", "Anderson Ranch Dam", 43.35, -115.47),
]

# Filter to stations within the model AOI bounding box (with small buffer)
BUFFER_DEG = 0.1  # ~10 km buffer
aoi_stations = [
    (code, name, lat, lon)
    for code, name, lat, lon in ALL_HYDROMET_STATIONS
    if (minx - BUFFER_DEG) <= lon <= (maxx + BUFFER_DEG)
    and (miny - BUFFER_DEG) <= lat <= (maxy + BUFFER_DEG)
]

print(f"Stations within AOI: {len(aoi_stations)} / {len(ALL_HYDROMET_STATIONS)}")
for code, name, lat, lon in aoi_stations:
    print(f"  {code:6s} | {name}")

# %% [markdown]
# ## 4. Fetch QU data availability for AOI stations

# %%
results = []

for station, name, lat, lon in aoi_stations:
    url = (
        f"https://www.usbr.gov/pn-bin/daily.pl"
        f"?station={station}&format=csv"
        f"&year={START_YEAR}&month=1&day=1"
        f"&year={END_YEAR}&month=12&day=31"
        f"&pcode=QU"
    )
    try:
        resp = requests.get(url, timeout=30)
        if resp.ok:
            lines = [l for l in resp.text.strip().split("\n")
                     if l.strip() and not l.startswith("#") and not l.startswith("BEGIN")]
            if len(lines) > 1:
                df_tmp = pd.read_csv(StringIO("\n".join(lines)))
                val_col = [c for c in df_tmp.columns if c != "DateTime" and "date" not in c.lower()]
                if val_col:
                    n_days = int(pd.to_numeric(df_tmp[val_col[0]], errors="coerce").notna().sum())
                else:
                    n_days = 0
            else:
                n_days = 0
        else:
            n_days = 0
    except Exception:
        n_days = 0

    results.append({
        "station": station,
        "name": name,
        "latitude": lat,
        "longitude": lon,
        "qu_days": n_days,
        "geometry": Point(lon, lat),
    })
    print(f"  {station:6s} | {name:35s} | QU days: {n_days}")
    time.sleep(0.5)

stations_gdf = gpd.GeoDataFrame(results, crs="EPSG:4326")

# Drop stations with 0 QU days
stations_gdf = stations_gdf[stations_gdf["qu_days"] > 0].reset_index(drop=True)
print(f"\nStations with QU data in AOI: {len(stations_gdf)}")

# %% [markdown]
# ## 5. Map of QU stations in model AOI

# %%
if len(stations_gdf) > 0:
    # Plot model domain + stations
    m = hru_gdf.dissolve().boundary.explore(color="black", style_kwds={"weight": 2})
    stations_gdf.explore(
        m=m,
        column="qu_days",
        cmap="YlGnBu",
        tooltip=["station", "name", "qu_days"],
        popup=["station", "name", "latitude", "longitude", "qu_days"],
        marker_kwds={"radius": 8},
        legend=True,
        legend_kwds={"caption": f"Days with QU data ({START_YEAR}-{END_YEAR})"},
    )
    display(m)
else:
    print("No stations with QU data found in model AOI.")

# %% [markdown]
# ## 6. Build metadata table (gages file format)
#
# Columns match the format expected by notebook 1 for appending to the gages file:
# `poi_gage_id`, `poi_agency`, `poi_name`, `latitude`, `longitude`,
# `drainage_area`, `drainage_area_contrib`

# %%
if len(stations_gdf) > 0:
    bor_gages_df = pd.DataFrame({
        "poi_gage_id": stations_gdf["station"],
        "poi_agency": "BOR-HM",
        "poi_name": stations_gdf["name"],
        "latitude": stations_gdf["latitude"],
        "longitude": stations_gdf["longitude"],
        "drainage_area": np.nan,
        "drainage_area_contrib": np.nan,
    })

    print("BOR Hydromet gages metadata (ready to append to gages file):")
    display(bor_gages_df)

    # Save to metadata folder
    out_path = MODEL_DIR / "metadata" / "BOR_HM_gages.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bor_gages_df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")
else:
    print("No BOR-HM gages to save.")
    bor_gages_df = pd.DataFrame()

# %% [markdown]
# ## 7. Fetch daily QU timeseries for all stations
#
# Downloads the actual daily values for integration into notebook 1's
# streamflow observations workflow.

# %%
all_qu_data = []

for _, row in stations_gdf.iterrows():
    station = row["station"]
    url = (
        f"https://www.usbr.gov/pn-bin/daily.pl"
        f"?station={station}&format=csv"
        f"&year={START_YEAR}&month=1&day=1"
        f"&year={END_YEAR}&month=12&day=31"
        f"&pcode=QU"
    )
    try:
        resp = requests.get(url, timeout=60)
        if resp.ok:
            lines = [l for l in resp.text.strip().split("\n")
                     if l.strip() and not l.startswith("#") and not l.startswith("BEGIN")]
            if len(lines) > 1:
                df_tmp = pd.read_csv(StringIO("\n".join(lines)))
                # Identify date and value columns
                date_col = [c for c in df_tmp.columns if "date" in c.lower() or "time" in c.lower()]
                val_col = [c for c in df_tmp.columns if c not in date_col]
                if date_col and val_col:
                    df_tmp = df_tmp.rename(columns={date_col[0]: "datetime", val_col[0]: "value"})
                    df_tmp["datetime"] = pd.to_datetime(df_tmp["datetime"], errors="coerce")
                    df_tmp["value"] = pd.to_numeric(df_tmp["value"], errors="coerce")
                    df_tmp = df_tmp.dropna(subset=["datetime", "value"])
                    df_tmp["station"] = station
                    all_qu_data.append(df_tmp[["datetime", "station", "value"]])
                    print(f"  {station}: {len(df_tmp)} days of QU data")
    except Exception as e:
        print(f"  {station}: ERROR - {e}")
    time.sleep(0.5)

if all_qu_data:
    qu_df = pd.concat(all_qu_data, ignore_index=True)
    print(f"\nTotal: {len(qu_df)} daily QU records across {qu_df['station'].nunique()} stations")
else:
    qu_df = pd.DataFrame(columns=["datetime", "station", "value"])
    print("No QU data retrieved.")

# %%
# Preview the timeseries
if not qu_df.empty:
    # Pivot to wide format (one column per station)
    qu_wide = qu_df.pivot(index="datetime", columns="station", values="value")
    print(f"Date range: {qu_wide.index.min()} to {qu_wide.index.max()}")
    print(f"Shape: {qu_wide.shape}")
    qu_wide.head()

# %% [markdown]
# ## 8. Save QU timeseries for notebook 1
#
# Saves the daily QU data in a format that can be loaded by the streamflow
# observations notebook.

# %%
if not qu_df.empty:
    qu_out_path = MODEL_DIR / "metadata" / "bor_hm_qu_daily.csv"
    qu_df.to_csv(qu_out_path, index=False)
    print(f"Saved daily QU data: {qu_out_path}")
    print(f"  Stations: {qu_df['station'].unique().tolist()}")
    print(f"  Period: {qu_df['datetime'].min()} to {qu_df['datetime'].max()}")
    print(f"  Records: {len(qu_df):,}")
