# ---
# jupyter:
#   jupytext:
#     formats: notebooks///ipynb,src/workflow_templates/nhm///py:percent
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
# # Stream Temperature Modeling
#
# This notebook models daily mean stream temperature using two approaches:
# 1. **Stratton-Garvin regression** — statistical model relating stream temp to air temp, flow, and seasonality
# 2. **SNTemp heat balance** — mechanistic energy balance model (USGS TM 6-D4)
#
# Both methods use pywatershed hydrology outputs and are validated against NWIS observed stream temperature.
#
# **Domain:** Willamette River

# %% [markdown]
# Compare against Markstrom's [repo](https://code.usgs.gov/wma/national-iwaas/nhm/dev/markstro/notebooks/-/blob/main/param-estimators/computers/solar_table/solar_table.ipynb?ref_type=heads)

# %% [markdown]
# ---
# ## 1. Setup & Domain Configuration

# %%
import warnings
import pandas as pd
import numpy as np
import pathlib as pl
import xarray as xr
import geopandas as gpd
from contextlib import redirect_stdout
import io
import sys
import os

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

from rich.console import Console
from rich import pretty

warnings.filterwarnings("ignore")
pretty.install()
con = Console()

# Find the repo root via the editable-installed `assist` package
import assist as _assist_pkg
root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]

from assist.workspace.bridge import resolve_project_notebook_context
from assist.workspace.service import get_active_model_root

project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
if project_context:
    active_model_root = get_active_model_root(
        project_context["workspace_root"], project_context["project_root"].name
    )
    config_root = active_model_root / "config"
else:
    config_root = root_dir

from assist.nhm.nhm_assist_utilities import load_subdomain_config
config = load_subdomain_config(config_root)

import dataretrieval.nwis as nwis
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

print(f"Domain: {config['model_dir'].name}")
print(f"Parameter file: {config['param_filename']}")

# %%
from assist.nhm.nhm_hydrofabric import (
    create_hru_gdf,
    create_segment_gdf,
    create_poi_df,
    create_default_gages_file,
    read_gages_file,
)

hru_gdf, hru_txt, hru_cal_level_txt = create_hru_gdf(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
)

seg_gdf, seg_txt = create_segment_gdf(
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
)

print(f"HRUs: {len(hru_gdf)}")
print(f"Segments: {len(seg_gdf)}")

# %% [markdown]
# ---
# ## 2. Parameter Inspection
#
# Checks which SNTemp parameters are present in the parameter file and which need to be derived.

# %%
params = pws.parameters.PrmsParameters.load(config["param_filename"])
all_param_names = set(params.parameters.keys())

# SNTemp required parameters
sntemp_params = {
    "seg_length": "Segment length (m)",
    "seg_slope": "Segment slope (dimensionless)",
    "seg_depth": "Segment depth (m)",
    "tosegment": "Downstream segment connectivity",
    "hru_segment": "HRU-to-segment mapping",
    "seg_width": "Wetted channel width (m)",
    "seg_shade": "Shade fraction (0-1)",
    "segshade_sum": "Summer shade fraction (0-1)",
    "segshade_win": "Winter shade fraction (0-1)",
    "seg_azimuth": "Flow direction (degrees from north)",
    "seg_lat": "Segment centroid latitude (degrees)",
}

print("SNTemp Parameter Availability")
print("=" * 60)
present = []
missing = []
for param, desc in sntemp_params.items():
    if param in all_param_names:
        present.append(param)
        print(f"  ✅ {param:20s} {desc}")
    else:
        missing.append(param)
        print(f"  ❌ {param:20s} {desc}")

print(f"\nPresent: {len(present)} / {len(sntemp_params)}")
print(f"Missing: {len(missing)} — need derivation")

nseg = len(params.parameters["seg_length"])
print(f"\nNumber of segments: {nseg}")

# %% [markdown]
# ---
# ## 3. Derive Missing Parameters
#
# Computes the missing SNTemp parameters from available GIS and hydrologic data:
# - `seg_lat` — from segment centroid coordinates
# - `seg_azimuth` — from segment polyline direction
# - `seg_width` — from hydraulic geometry (width = a * Q^b)
# - `seg_shade` — from NLCD canopy cover or placeholder estimates

# %%
# Derive seg_lat and seg_azimuth from segment geometry
seg_gdf_4326 = seg_gdf.to_crs(epsg=4326)

# seg_lat: latitude of segment centroid
seg_lat = seg_gdf_4326.geometry.centroid.y.values
print(f"seg_lat: min={seg_lat.min():.4f}, max={seg_lat.max():.4f}")

# seg_azimuth: direction from first to last vertex of each segment polyline
def compute_azimuth(geom):
    """Compute azimuth (degrees from north, clockwise) of a linestring or multilinestring."""
    from shapely.geometry import MultiLineString, LineString
    # Handle MultiLineString by using the longest component
    if isinstance(geom, MultiLineString):
        geom = max(geom.geoms, key=lambda g: g.length)
    if not isinstance(geom, LineString):
        return 0.0
    coords = list(geom.coords)
    if len(coords) < 2:
        return 0.0
    # Use first and last point
    lon1, lat1 = coords[0]
    lon2, lat2 = coords[-1]
    dlon = np.radians(lon2 - lon1)
    lat1_r = np.radians(lat1)
    lat2_r = np.radians(lat2)
    x = np.sin(dlon) * np.cos(lat2_r)
    y = np.cos(lat1_r) * np.sin(lat2_r) - np.sin(lat1_r) * np.cos(lat2_r) * np.cos(dlon)
    azimuth = np.degrees(np.arctan2(x, y))
    return azimuth % 360  # Normalize to 0-360

seg_azimuth = seg_gdf_4326.geometry.apply(compute_azimuth).values
print(f"seg_azimuth: min={seg_azimuth.min():.1f}°, max={seg_azimuth.max():.1f}°, mean={seg_azimuth.mean():.1f}°")

# %%
# Derive seg_width using hydraulic geometry relationship
# Leopold & Maddock (1953): width = a * Q^b
# Typical values for Pacific Northwest streams: a=2.7, b=0.5
# Using mean annual flow approximated from seg_cum_area (drainage area in acres)

HG_COEFF_A = 2.7  # width coefficient (adjust for region)
HG_COEFF_B = 0.5  # width exponent

# Approximate mean annual flow from drainage area (cfs)
# Pacific NW empirical: Q_mean ≈ 1.5 * drainage_area_mi2 (rough)
seg_cum_area_mi2 = params.parameters["seg_cum_area"] / 640.0  # acres to mi2
q_mean_est = 1.5 * seg_cum_area_mi2  # rough cfs estimate

# Convert cfs to cms for hydraulic geometry (most relationships use metric)
q_mean_cms = q_mean_est * 0.0283168

# Compute width
seg_width = HG_COEFF_A * np.power(np.maximum(q_mean_cms, 0.01), HG_COEFF_B)

print(f"seg_width (derived): min={seg_width.min():.1f} m, max={seg_width.max():.1f} m, mean={seg_width.mean():.1f} m")
print(f"\nNote: These are estimates from hydraulic geometry. Field data would improve accuracy.")

# %%
# Derive seg_shade from HRU vegetation cover density (already in param file)
# covden_sum/covden_win = vegetation cover density (0-1) per HRU
# Aggregate to segments using hru_segment mapping (area-weighted mean)

covden_sum_hru = params.parameters["covden_sum"]  # Summer cover density per HRU
covden_win_hru = params.parameters["covden_win"]  # Winter cover density per HRU
hru_segment_arr = params.parameters["hru_segment"]  # HRU -> segment mapping (1-indexed)
hru_area = params.parameters["hru_area"]            # HRU area

# Aggregate: area-weighted mean cover density per segment
segshade_sum = np.zeros(nseg)
segshade_win = np.zeros(nseg)
seg_area_total = np.zeros(nseg)

for hru_i in range(len(hru_segment_arr)):
    seg_i = hru_segment_arr[hru_i] - 1  # Convert to 0-indexed
    if 0 <= seg_i < nseg:
        area = hru_area[hru_i]
        segshade_sum[seg_i] += covden_sum_hru[hru_i] * area
        segshade_win[seg_i] += covden_win_hru[hru_i] * area
        seg_area_total[seg_i] += area

# Normalize by total area
mask = seg_area_total > 0
segshade_sum[mask] /= seg_area_total[mask]
segshade_win[mask] /= seg_area_total[mask]

# Use summer as the default/annual shade value
seg_shade = segshade_sum.copy()

print(f"seg_shade (from covden_sum): min={seg_shade.min():.3f}, max={seg_shade.max():.3f}, mean={seg_shade.mean():.3f}")
print(f"segshade_sum: mean={segshade_sum.mean():.3f}")
print(f"segshade_win: mean={segshade_win.mean():.3f}")
print(f"\nSegments with >70% cover: {(seg_shade > 0.7).sum()}")
print(f"Segments with <20% cover: {(seg_shade < 0.2).sum()}")
print(f"\nNote: Using HRU covden_sum/covden_win as shade proxy.")
print(f"This represents catchment-level vegetation density, not direct riparian shade.")

# %%
# Store all derived parameters in a dictionary for use in temperature modeling
derived_params = {
    "seg_lat": seg_lat,
    "seg_azimuth": seg_azimuth,
    "seg_width": seg_width,
    "seg_shade": seg_shade,
    "segshade_sum": segshade_sum,
    "segshade_win": segshade_win,
}

# Combine with existing parameters
existing_seg_params = {
    "seg_length": params.parameters["seg_length"],
    "seg_slope": params.parameters["seg_slope"],
    "seg_depth": params.parameters["seg_depth"],
    "tosegment": params.parameters["tosegment"],
}

temp_params = {**existing_seg_params, **derived_params}
print("Temperature modeling parameters ready:")
for k, v in temp_params.items():
    if isinstance(v, np.ndarray):
        print(f"  {k:20s} shape={v.shape}")
    else:
        print(f"  {k:20s} = {v}")

# %% [markdown]
# ---
# ## 4. Run Pywatershed Hydrology
#
# Runs the full PRMS model chain to generate streamflow and air temperature outputs needed for temperature modeling. Skips if output already exists.

# %%
# Prepare forcing files if needed
pws_prcp_input_file = config["model_dir"] / "prcp.nc"
pws_tmin_input_file = config["model_dir"] / "tmin.nc"
pws_tmax_input_file = config["model_dir"] / "tmax.nc"
nhmx_input_file = config["model_dir"] / "cbh.nc"
input_file_path_list = [pws_prcp_input_file, pws_tmin_input_file, pws_tmax_input_file]

rewrite_inputs = any([not ff.exists() for ff in input_file_path_list])
if rewrite_inputs:
    con.print("Rewriting prcp.nc, tmin.nc, tmax.nc from cbh.nc...")
    with xr.open_dataset(nhmx_input_file) as ds:
        model_input = ds.swap_dims({"nhru": "nhm_id"}).drop_vars("nhru", errors="ignore")
        model_input["prcp"].to_netcdf(pws_prcp_input_file)
        model_input["tmin"].to_netcdf(pws_tmin_input_file)
        model_input["tmax"].to_netcdf(pws_tmax_input_file)
    con.print("Done.")

# Fix pref_flow_infil_frac if missing
if "pref_flow_infil_frac" not in params.parameters.keys():
    params_ds = params.to_xr_ds()
    params_ds["pref_flow_infil_frac"] = params_ds["pref_flow_den"][:] * 0.0
    params = pws.parameters.PrmsParameters.from_ds(params_ds)

params_ds = params.to_xr_ds()
params_ds["pref_flow_infil_frac"] = params_ds["pref_flow_infil_frac"].where(
    (params_ds["pref_flow_infil_frac"] >= 0.0) &
    (params_ds["pref_flow_infil_frac"] <= 1.0),
    0.0,
)
params = pws.parameters.PrmsParameters.from_ds(params_ds)

# %%
# Run pywatershed — skip if seg_outflow already exists
seg_outflow_file = config["out_dir"] / "seg_outflow.nc"

if seg_outflow_file.exists():
    con.print(f"Hydrology output exists: {seg_outflow_file}")
    con.print("Skipping model run. Delete file to re-run.")
else:
    con.print("Running pywatershed hydrology model...")
    control = pws.Control.load_prms(
        config["model_dir"] / config["control_file_name"],
        warn_unused_options=False,
    )
    control.options = control.options | {
        "input_dir": config["model_dir"],
        "budget_type": None,
        "verbosity": 0,
        "calc_method": "numba",
        "netcdf_output_var_names": ["seg_outflow"],
        "netcdf_output_dir": config["out_dir"],
    }

    model = pws.Model(
        [
            pws.PRMSSolarGeometry,
            pws.PRMSAtmosphere,
            pws.PRMSCanopy,
            pws.PRMSSnow,
            pws.PRMSRunoff,
            pws.PRMSSoilzone,
            pws.PRMSGroundwater,
            pws.PRMSChannel,
        ],
        control=control,
        parameters=params,
    )
    model.run()
    con.print(f"Model run complete. Output: {seg_outflow_file}")
    del model

# %% [markdown]
# ---
# ## 5. Method 1 — Stratton-Garvin Regression
#
# Statistical model: stream_temp ~ f(air_temp, log_flow, day_of_year)
#
# Trained on observed NWIS temperature data at POIs with temperature records.

# %%
# Load temperature gage list
temp_gages = pd.read_csv(config["model_dir"] / "WaterDataTemperatureGages.csv")
print(f"Temperature gages available: {len(temp_gages)}")
print(temp_gages[["poi_id", "poi_name"]].head(10).to_string())


# %%
def load_air_temp_series(cbh_file):
    """Load domain-mean daily air temperature from CBH file. Converts F to C."""
    with xr.open_dataset(cbh_file) as ds:
        if "nhru" in ds.dims:
            tmin = ds["tmin"].mean(dim="nhru")
            tmax = ds["tmax"].mean(dim="nhru")
        elif "nhm_id" in ds.dims:
            tmin = ds["tmin"].mean(dim="nhm_id")
            tmax = ds["tmax"].mean(dim="nhm_id")
        else:
            raise ValueError(f"Unknown HRU dimension in {cbh_file}: {ds.dims}")
        tair = ((tmin + tmax) / 2.0).to_series().reset_index()
        tair.columns = ["date", "tair_mean"]
        tair["date"] = pd.to_datetime(tair["date"]).dt.floor("D")
        # NHM cbh.nc stores temperature in Fahrenheit — convert to Celsius
        tair["tair_mean"] = (tair["tair_mean"] - 32.0) * 5.0 / 9.0
    return tair


def fetch_nwis_temp_daily(site, start_date, end_date):
    """Fetch daily mean stream temperature from NWIS."""
    df = nwis.get_record(
        sites=site, service="dv",
        start=start_date, end=end_date,
        parameterCd="00010",
    )
    if df is None or len(df) == 0:
        # Try instantaneous values and aggregate to daily
        df = nwis.get_record(
            sites=site, service="iv",
            start=start_date, end=end_date,
            parameterCd="00010",
        )
    if df is None or len(df) == 0:
        return None

    df = df.reset_index()
    # Find the temperature value column
    val_cols = [c for c in df.columns if "00010" in c and "_cd" not in c.lower()]
    if not val_cols:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if not numeric_cols:
            return None
        val_cols = [numeric_cols[0]]

    # Find datetime column
    dt_col = [c for c in df.columns if "datetime" in c.lower() or c == "date"][0]
    out = df[[dt_col, val_cols[0]]].copy()
    out.columns = ["datetime", "obs_stream_temp"]
    out["date"] = pd.to_datetime(out["datetime"]).dt.floor("D")
    daily = out.groupby("date", as_index=False)["obs_stream_temp"].mean()
    return daily


def build_regression_features(df, rolling_days=7):
    """Add time/flow features for Stratton-Garvin regression."""
    df = df.sort_values("date").copy()
    doy = df["date"].dt.dayofyear
    df["sin_doy"] = np.sin(2 * np.pi * doy / 365.25)
    df["cos_doy"] = np.cos(2 * np.pi * doy / 365.25)
    df["log_flow"] = np.log1p(df["seg_outflow"].clip(lower=0.0))
    df["tair_lag1"] = df["tair_mean"].shift(1)
    df["tair_roll"] = df["tair_mean"].rolling(rolling_days, min_periods=1).mean()
    return df


# %%
# Load model outputs
seg_outflow = xr.load_dataarray(config["out_dir"] / "seg_outflow.nc")
air_temp_df = load_air_temp_series(config["model_dir"] / "cbh.nc")

# Get control dates
control = pws.Control.load_prms(
    config["model_dir"] / config["control_file_name"], warn_unused_options=False
)
start_date = pd.to_datetime(str(control.start_time)).strftime("%Y-%m-%d")
end_date = pd.to_datetime(str(control.end_time)).strftime("%Y-%m-%d")

# Map POI gages to segment indices
poi_gage_ids = params.parameters["poi_gage_id"]
poi_gage_segs = params.parameters["poi_gage_segment"] - 1  # 0-indexed

# Filter to gages that have temperature data
temp_gage_ids = set(temp_gages["poi_id"].astype(str))
temp_pois = [(gid, sidx) for gid, sidx in zip(poi_gage_ids, poi_gage_segs)
             if str(gid) in temp_gage_ids]

print(f"POIs with temperature observations: {len(temp_pois)}")
print(f"Model period: {start_date} to {end_date}")

# %%
# Fit Stratton-Garvin regression for each temperature POI
FEATURE_COLS = ["tair_mean", "tair_lag1", "tair_roll", "log_flow", "sin_doy", "cos_doy"]
ROLLING_DAYS = 7

sg_results = {}  # {poi_id: {model, metrics, predictions}}

for poi_id, seg_idx in temp_pois:  # All temperature POIs
    poi_id_str = str(poi_id)
    
    # Get observed temperature
    obs_df = fetch_nwis_temp_daily(poi_id_str, start_date, end_date)
    if obs_df is None or len(obs_df) < 30:
        continue
    # Strip timezone for merge compatibility
    obs_df["date"] = pd.to_datetime(obs_df["date"]).dt.tz_localize(None)
    
    # Get segment outflow time series
    seg_dim = [d for d in seg_outflow.dims if d != "time"][0]
    flow_series = seg_outflow.isel({seg_dim: int(seg_idx)}).to_series().reset_index()
    flow_series.columns = ["date", "seg_outflow"]
    flow_series["date"] = pd.to_datetime(flow_series["date"]).dt.floor("D")
    
    # Merge all data
    reg_df = (
        flow_series
        .merge(air_temp_df, on="date", how="inner")
        .merge(obs_df, on="date", how="inner")
    )
    reg_df = build_regression_features(reg_df, ROLLING_DAYS)
    reg_df = reg_df.dropna(subset=FEATURE_COLS + ["obs_stream_temp"])
    
    if len(reg_df) < 30:
        continue
    
    # Fit regression
    X = reg_df[FEATURE_COLS].values
    y = reg_df["obs_stream_temp"].values
    
    model_lr = LinearRegression()
    model_lr.fit(X, y)
    y_pred = model_lr.predict(X)
    
    # Metrics
    r2 = r2_score(y, y_pred)
    rmse = np.sqrt(mean_squared_error(y, y_pred))
    mae = mean_absolute_error(y, y_pred)
    
    sg_results[poi_id_str] = {
        "model": model_lr,
        "n_obs": len(reg_df),
        "r2": r2,
        "rmse": rmse,
        "mae": mae,
        "predictions": pd.DataFrame({"date": reg_df["date"].values, "obs": y, "pred": y_pred}),
    }
    print(f"  {poi_id_str}: n={len(reg_df):,}, R²={r2:.3f}, RMSE={rmse:.2f}°C, MAE={mae:.2f}°C")

print(f"\nSuccessfully fit models for {len(sg_results)} POIs")

# %% [markdown]
# ---
# ## 6. Method 2 — SNTemp Heat Balance
#
# Mechanistic energy balance model based on USGS TM 6-D4.
#
# Energy balance components:
# - Net solar radiation (shortwave, accounting for shade)
# - Longwave radiation (atmospheric + back radiation)
# - Convection/evaporation (wind-driven latent + sensible heat)
# - Advection (lateral inflows at estimated temperature)
# - Groundwater inflow (seasonal temperature function)

# %%
# SNTemp simplified energy balance implementation
# Based on USGS TM 6-D4 (Markstrom, 2012)
#
# Energy balance: dT/dt = (Qsw + Qlw + Qconv + Qevap + Qgw) / (rho * cp * V)
#
# For daily mean temperature, we solve a steady-state mixing/routing equation
# per segment per day.

STEFAN_BOLTZMANN = 5.67e-8  # W/m²/K⁴
WATER_DENSITY = 1000.0     # kg/m³
SPECIFIC_HEAT = 4186.0     # J/kg/°C
LATENT_HEAT_EVAP = 2.45e6  # J/kg


def solar_radiation_daily(day_of_year, latitude_deg):
    """Estimate clear-sky daily solar radiation (W/m²) for a given latitude and DOY."""
    lat_rad = np.radians(latitude_deg)
    declination = 23.45 * np.sin(np.radians(360 * (284 + day_of_year) / 365))
    decl_rad = np.radians(declination)
    hour_angle = np.arccos(-np.tan(lat_rad) * np.tan(decl_rad))
    hour_angle = np.clip(hour_angle, 0, np.pi)
    # Extraterrestrial radiation
    solar_const = 1367.0  # W/m²
    dr = 1 + 0.033 * np.cos(2 * np.pi * day_of_year / 365)
    ra = (24 * 60 / np.pi) * solar_const * dr * (
        hour_angle * np.sin(lat_rad) * np.sin(decl_rad) +
        np.cos(lat_rad) * np.cos(decl_rad) * np.sin(hour_angle)
    ) / (24 * 60)  # Convert from J/m²/day to W/m²
    # Apply atmospheric transmittance (~0.75 for clear sky)
    return ra * 0.75


def sntemp_segment_temperature(
    t_air,           # daily mean air temp (deg C)
    q_inflow,        # total inflow to segment (m3/s)
    t_upstream,      # upstream water temperature (deg C)
    seg_width,       # channel width (m)
    seg_length,      # segment length (m)
    seg_shade,       # shade fraction (0-1)
    seg_lat,         # latitude (degrees)
    day_of_year,     # DOY
    t_gw=None,       # groundwater temperature (deg C)
    gw_fraction=0.1, # fraction of inflow from groundwater
    wind_speed=2.0,  # wind speed (m/s)
):
    """
    Compute daily mean stream temperature using equilibrium temperature approach.
    
    T_out = T_in + (T_eq - T_in) * (1 - exp(-K * travel_time))
    
    Where T_eq is the temperature the stream would reach under current conditions,
    and the exponential decay represents how far toward equilibrium the water gets
    during its residence time in the segment.
    """
    if t_gw is None:
        t_gw = 10.0  # Default GW temp for PNW (long-term annual mean)
    
    # --- Advective mixing (upstream + groundwater) ---
    q_surface = q_inflow * (1.0 - gw_fraction)
    q_gw_flow = q_inflow * gw_fraction
    if q_inflow > 0:
        t_mixed = (q_surface * t_upstream + q_gw_flow * t_gw) / q_inflow
    else:
        t_mixed = t_gw
    
    # --- Equilibrium temperature ---
    # T_eq approximated as air temp + small solar warming, minus evaporative cooling
    # Net effect: streams are typically within +/- 2C of air temp
    # Shade reduces solar warming; evaporative cooling roughly balances solar for wide streams
    solar_potential = solar_radiation_daily(day_of_year, seg_lat)
    # Empirical: ~0.5-1C per 100 W/m2 net solar (after accounting for back-radiation & evap)
    solar_offset = (solar_potential * (1.0 - seg_shade)) * 0.005
    
    # Equilibrium temp: slightly above air temp in sun, at or below in shade
    # Also blend toward GW temp (streams never get as hot as equilibrium suggests
    # because of constant GW mixing and hyporheic exchange)
    t_eq = t_air + solar_offset
    # Dampen toward GW temp (represents hyporheic/GW buffering)
    t_eq = 0.85 * t_eq + 0.15 * t_gw
    t_eq = max(0.0, min(t_eq, 30.0))
    
    # --- Heat exchange rate ---
    # K * tau = (heat_exchange_coeff * width * length) / (rho_cp * Q)
    # Typical combined heat exchange: 20-40 W/m2/C
    heat_exchange_coeff = 20.0 + 5.0 * wind_speed  # W/m2/C
    RHO_CP = 4.18e6  # J/m3/C
    
    if q_inflow > 0.001:
        k_times_tau = (heat_exchange_coeff * seg_width * seg_length) / (RHO_CP * q_inflow)
    else:
        k_times_tau = 2.0  # Very low flow: nearly reach equilibrium
    
    # Clamp to prevent overflow
    k_times_tau = min(k_times_tau, 5.0)
    
    # --- Exponential relaxation toward equilibrium ---
    decay = 1.0 - np.exp(-k_times_tau)
    t_out = t_mixed + (t_eq - t_mixed) * decay
    
    # Physical bounds
    t_out = max(0.0, min(t_out, 30.0))
    
    return t_out


print("SNTemp energy balance functions defined.")
print("Ready for network routing in next cell.")


# %%
# Route temperature through the segment network
# Process segments in topological order (headwaters first)

def get_topological_order(tosegment):
    """Return segment indices in topological order (upstream to downstream)."""
    n = len(tosegment)
    # Build adjacency: which segments feed into each segment
    inflow_from = {i: [] for i in range(n)}
    for i, ds in enumerate(tosegment):
        if ds > 0:  # 0 means outlet
            inflow_from[ds - 1].append(i)  # 1-indexed to 0-indexed
    
    # Find headwaters (segments with no upstream inputs)
    has_upstream = set()
    for i, ds in enumerate(tosegment):
        if ds > 0:
            has_upstream.add(ds - 1)
    
    # Topological sort via Kahn's algorithm
    in_degree = np.zeros(n, dtype=int)
    for i, ds in enumerate(tosegment):
        if ds > 0:
            in_degree[ds - 1] += 1
    
    queue = [i for i in range(n) if in_degree[i] == 0]
    order = []
    while queue:
        seg = queue.pop(0)
        order.append(seg)
        ds = tosegment[seg]
        if ds > 0:
            in_degree[ds - 1] -= 1
            if in_degree[ds - 1] == 0:
                queue.append(ds - 1)
    return order


# Build network topology
toseg = params.parameters["tosegment"]
topo_order = get_topological_order(toseg)

# Build upstream map: for each segment, which segments flow into it
upstream_of = {i: [] for i in range(nseg)}
for i, ds in enumerate(toseg):
    if ds > 0:
        upstream_of[ds - 1].append(i)

print(f"Topological order computed: {len(topo_order)} segments")
print(f"Headwater segments: {sum(1 for i in range(nseg) if not upstream_of[i])}")
print(f"Outlet segments: {sum(1 for t in toseg if t == 0)}")

# %%
# Simulate stream temperature for the full model period
from tqdm import tqdm

# Load flow data
seg_outflow_da = xr.load_dataarray(config["out_dir"] / "seg_outflow.nc")
seg_dim = [d for d in seg_outflow_da.dims if d != "time"][0]
n_seg_in_file = seg_outflow_da.sizes[seg_dim]

if n_seg_in_file != nseg:
    print(f"ERROR: seg_outflow.nc has {n_seg_in_file} segments but domain has {nseg}.")
    print(f"The file likely contains POI-only output from a previous run.")
    print(f"Delete '{config['out_dir'] / 'seg_outflow.nc'}' and re-run Section 4 to get all segments.")
    raise ValueError(f"seg_outflow size mismatch: {n_seg_in_file} vs {nseg}")

times = pd.to_datetime(seg_outflow_da.time.values)
n_days = len(times)

# Air temperature per day (domain mean)
air_df = load_air_temp_series(config["model_dir"] / "cbh.nc")
air_df = air_df.set_index("date")

# Annual mean air temp for groundwater temperature estimate
t_gw_annual = air_df["tair_mean"].mean()

# Initialize temperature array
stream_temp = np.zeros((n_days, nseg))
stream_temp[0, :] = air_df.iloc[0]["tair_mean"]  # Initialize with first day air temp

print(f"Simulating stream temperature for {n_days} days, {nseg} segments...")

# Determine seasonal shade for each day
def get_shade_for_doy(doy):
    """Interpolate between summer and winter shade based on DOY."""
    summer_weight = np.clip((np.sin(2 * np.pi * (doy - 80) / 365) + 1) / 2, 0, 1)
    return segshade_win + (segshade_sum - segshade_win) * summer_weight

for t_idx in tqdm(range(1, n_days), desc="SNTemp simulation", unit="day"):
    date = times[t_idx]
    doy = date.dayofyear
    t_air_today = air_df.loc[date, "tair_mean"] if date in air_df.index else air_df["tair_mean"].mean()
    shade_today = get_shade_for_doy(doy)
    
    # Get flow for all segments today
    flow_today = seg_outflow_da.isel(time=t_idx).values  # cfs
    flow_today_cms = flow_today * 0.0283168  # Convert to m3/s
    
    # Process segments in topological order (upstream -> downstream)
    for seg_i in topo_order:
        # Get upstream temperature (flow-weighted average of upstream segments)
        upstream_segs = upstream_of[seg_i]
        if upstream_segs:
            us_flows = np.array([max(flow_today_cms[u], 0.001) for u in upstream_segs])
            us_temps = np.array([stream_temp[t_idx - 1, u] for u in upstream_segs])
            t_upstream = np.average(us_temps, weights=us_flows)
        else:
            # Headwater: GW-buffered temperature
            t_upstream = 0.4 * t_air_today + 0.6 * t_gw_annual
        
        # Compute segment temperature using equilibrium approach
        stream_temp[t_idx, seg_i] = sntemp_segment_temperature(
            t_air=t_air_today,
            q_inflow=max(flow_today_cms[seg_i], 0.001),
            t_upstream=t_upstream,
            seg_width=temp_params["seg_width"][seg_i],
            seg_length=temp_params["seg_length"][seg_i],
            seg_shade=shade_today[seg_i],
            seg_lat=temp_params["seg_lat"][seg_i],
            day_of_year=doy,
            t_gw=t_gw_annual,
        )

print(f"\nSimulation complete.")
print(f"Temperature range: {stream_temp[1:].min():.1f} to {stream_temp[1:].max():.1f} °C")

# %% [markdown]
# ---
# ## 7. Comparison & Validation
#
# Compare both methods against NWIS observations at temperature gage locations.

# %%
# Compare both methods against observations at temperature POIs
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Convert SNTemp results to a DataFrame for comparison
sntemp_df = pd.DataFrame(stream_temp, index=times, columns=range(nseg))

comparison_results = []

for poi_id_str, sg_data in sg_results.items():
    # Find segment index for this POI
    poi_match = [(gid, sidx) for gid, sidx in zip(poi_gage_ids, poi_gage_segs)
                 if str(gid) == poi_id_str]
    if not poi_match:
        continue
    seg_idx = int(poi_match[0][1])
    
    # Get SNTemp predictions for matching dates
    sg_pred_df = sg_data["predictions"]
    sg_pred_df["date"] = pd.to_datetime(sg_pred_df["date"])
    
    sntemp_series = sntemp_df.iloc[:, seg_idx]
    sntemp_series.index = pd.to_datetime(sntemp_series.index)
    
    # Merge on dates
    merged = sg_pred_df.set_index("date").join(
        sntemp_series.rename("sntemp_pred"), how="inner"
    )
    
    if len(merged) < 10:
        continue
    
    # SNTemp metrics
    sntemp_r2 = r2_score(merged["obs"], merged["sntemp_pred"])
    sntemp_rmse = np.sqrt(mean_squared_error(merged["obs"], merged["sntemp_pred"]))
    sntemp_mae = mean_absolute_error(merged["obs"], merged["sntemp_pred"])
    
    comparison_results.append({
        "poi_id": poi_id_str,
        "n_obs": len(merged),
        "sg_r2": sg_data["r2"],
        "sg_rmse": sg_data["rmse"],
        "sntemp_r2": sntemp_r2,
        "sntemp_rmse": sntemp_rmse,
    })

comp_df = pd.DataFrame(comparison_results)
if not comp_df.empty:
    print("Method Comparison (at POIs with both methods):")
    print("=" * 70)
    print(f"{'POI':<12} {'N':>5} {'SG R²':>7} {'SG RMSE':>8} {'SNT R²':>7} {'SNT RMSE':>9}")
    print("-" * 70)
    for _, row in comp_df.iterrows():
        print(f"{row['poi_id']:<12} {row['n_obs']:>5} {row['sg_r2']:>7.3f} {row['sg_rmse']:>7.2f}°C "
              f"{row['sntemp_r2']:>7.3f} {row['sntemp_rmse']:>7.2f}°C")
    print("-" * 70)
    print(f"{'Mean':<12} {'':<5} {comp_df['sg_r2'].mean():>7.3f} {comp_df['sg_rmse'].mean():>7.2f}°C "
          f"{comp_df['sntemp_r2'].mean():>7.3f} {comp_df['sntemp_rmse'].mean():>7.2f}°C")
else:
    print("No POIs available for comparison.")


# %%
# Compute KGE for both methods
def kling_gupta_efficiency(obs, sim):
    """Compute Kling-Gupta Efficiency."""
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 3:
        return np.nan
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else 0
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) != 0 else 0
    kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)
    return kge

# Add KGE to comparison results
kge_results = []
for poi_id_str, sg_data in sg_results.items():
    poi_match = [(gid, sidx) for gid, sidx in zip(poi_gage_ids, poi_gage_segs)
                 if str(gid) == poi_id_str]
    if not poi_match:
        continue
    seg_idx = int(poi_match[0][1])
    
    sg_pred_df = sg_data["predictions"].copy()
    sg_pred_df["date"] = pd.to_datetime(sg_pred_df["date"])
    
    sntemp_series = sntemp_df.iloc[:, seg_idx]
    sntemp_series.index = pd.to_datetime(sntemp_series.index)
    
    merged = sg_pred_df.set_index("date").join(
        sntemp_series.rename("sntemp_pred"), how="inner"
    )
    if len(merged) < 10:
        continue
    
    # Get lat/lon from temp_gages
    gage_row = temp_gages[temp_gages["poi_id"].astype(str) == poi_id_str]
    lat = gage_row["latitude"].values[0] if len(gage_row) else None
    lon = gage_row["longitude"].values[0] if len(gage_row) else None
    
    kge_results.append({
        "poi_id": poi_id_str,
        "latitude": lat,
        "longitude": lon,
        "n_obs": len(merged),
        "sg_kge": kling_gupta_efficiency(merged["obs"], merged["pred"]),
        "sg_r2": sg_data["r2"],
        "sg_rmse": sg_data["rmse"],
        "sntemp_kge": kling_gupta_efficiency(merged["obs"], merged["sntemp_pred"]),
        "sntemp_r2": r2_score(merged["obs"], merged["sntemp_pred"]),
        "sntemp_rmse": np.sqrt(mean_squared_error(merged["obs"], merged["sntemp_pred"])),
    })

kge_df = pd.DataFrame(kge_results)
if not kge_df.empty:
    print("KGE Comparison:")
    print(f"{'POI':<12} {'SG KGE':>7} {'SNT KGE':>8} {'SG RMSE':>8} {'SNT RMSE':>9}")
    print("-" * 50)
    for _, row in kge_df.iterrows():
        print(f"{row['poi_id']:<12} {row['sg_kge']:>7.3f} {row['sntemp_kge']:>8.3f} "
              f"{row['sg_rmse']:>7.2f}°C {row['sntemp_rmse']:>7.2f}°C")

# %%
# Build folium map comparing KGE for both methods
import folium
import branca.colormap as bcm
from IPython.display import display, HTML

if not kge_df.empty:
    valid = kge_df.dropna(subset=["latitude", "longitude"]).copy()
    center = [valid["latitude"].mean(), valid["longitude"].mean()]
    
    m = folium.Map(location=center, zoom_start=8, tiles="CartoDB Positron")
    
    kge_colormap = bcm.LinearColormap(
        colors=["#b2182b", "#fddbc7", "#d1e5f0", "#2166ac"],
        vmin=-1.0, vmax=1.0,
        caption="KGE",
    )
    
    # Stratton-Garvin markers (circles)
    sg_fg = folium.FeatureGroup(name="Stratton-Garvin KGE", show=True)
    sntemp_fg = folium.FeatureGroup(name="SNTemp KGE", show=True)
    
    for _, row in valid.iterrows():
        # S-G marker (left offset)
        sg_color = kge_colormap(np.clip(row["sg_kge"], -1, 1))
        popup_html = (
            f"<b>{row['poi_id']}</b><br>"
            f"<hr>"
            f"<b>Stratton-Garvin:</b><br>"
            f"  KGE: {row['sg_kge']:.3f}<br>"
            f"  R²: {row['sg_r2']:.3f}<br>"
            f"  RMSE: {row['sg_rmse']:.2f}°C<br>"
            f"<b>SNTemp:</b><br>"
            f"  KGE: {row['sntemp_kge']:.3f}<br>"
            f"  R²: {row['sntemp_r2']:.3f}<br>"
            f"  RMSE: {row['sntemp_rmse']:.2f}°C<br>"
            f"<b>N obs:</b> {row['n_obs']}"
        )
        
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"] - 0.02],
            radius=8,
            color="black", weight=1,
            fill=True, fill_color=sg_color, fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{row['poi_id']} | SG KGE={row['sg_kge']:.3f}",
        ).add_to(sg_fg)
        
        # SNTemp marker (right offset)
        snt_color = kge_colormap(np.clip(row["sntemp_kge"], -1, 1))
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"] + 0.02],
            radius=8,
            color="black", weight=1,
            fill=True, fill_color=snt_color, fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{row['poi_id']} | SNT KGE={row['sntemp_kge']:.3f}",
        ).add_to(sntemp_fg)
    
    sg_fg.add_to(m)
    sntemp_fg.add_to(m)
    kge_colormap.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    
    # Save and display
    map_path = config["out_dir"] / "stream_temperature_kge_map.html"
    m.save(str(map_path))
    print(f"Saved KGE map: {map_path}")
    display(HTML(f'<a href="{map_path.as_uri()}" target="_blank">Open KGE map in browser</a>'))
    m
else:
    print("No comparison data available for map.")

# %% [markdown]
# ---
# ## 8. Export Results

# %%
# Save results to netCDF
output_nc = config["out_dir"] / "stream_temperature_predictions.nc"

# Create xarray dataset with both methods
ds_out = xr.Dataset(
    {
        "sntemp_temperature": (["time", "nsegment"], stream_temp),
    },
    coords={
        "time": times,
        "nsegment": np.arange(nseg),
        "nhm_seg": ("nsegment", params.parameters["nhm_seg"]),
    },
)
ds_out["sntemp_temperature"].attrs = {"units": "degC", "long_name": "SNTemp predicted stream temperature"}
ds_out.attrs = {
    "title": "Stream Temperature Predictions",
    "source": "nhm-assist stream_temperature notebook",
    "methods": "SNTemp energy balance (Section 6)",
    "domain": config["model_dir"].name,
}
ds_out.to_netcdf(str(output_nc))
print(f"Saved SNTemp predictions: {output_nc}")

# Save comparison table
if not comp_df.empty:
    comp_csv = config["out_dir"] / "temperature_method_comparison.csv"
    comp_df.to_csv(comp_csv, index=False)
    print(f"Saved comparison metrics: {comp_csv}")

# Save Stratton-Garvin predictions per POI
sg_predictions_all = []
for poi_id, data in sg_results.items():
    pred_df = data["predictions"].copy()
    pred_df["poi_id"] = poi_id
    pred_df["method"] = "stratton_garvin"
    sg_predictions_all.append(pred_df)

if sg_predictions_all:
    sg_csv = config["out_dir"] / "stratton_garvin_predictions.csv"
    pd.concat(sg_predictions_all).to_csv(sg_csv, index=False)
    print(f"Saved S-G predictions: {sg_csv}")
