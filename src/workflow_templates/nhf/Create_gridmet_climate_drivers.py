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
# # GridMET Climate Drivers
#
# This notebook generates gridMET climate forcing files (precipitation, tmin, tmax)
# for a subdomain model using area-weighted spatial aggregation via `gdptools`.
#
# **Outputs:** `prcp.nc`, `tmin.nc`, `tmax.nc` — ready for pywatershed (notebook 4).
#
# > ⚠️ **Network Requirement:** This notebook accesses gridMET data via OPeNDAP
# > from `thredds.northwestknowledge.net`. The USGS/DOI VPN proxy blocks this
# > connection. **You must disconnect from VPN before running this notebook**, or
# > run it on a Hovenweep Data Transfer Node (hw-dtn1/hw-dtn2) which has
# > unrestricted internet access.

# %% [markdown]
# ## 1. Configuration

# %%
import sys
import os
import pathlib as pl
import warnings

import pandas as pd
import numpy as np
import geopandas as gpd
import xarray as xr
import rioxarray  # noqa: F401

from gdptools import WeightGen, AggGen, ClimRCatData

warnings.filterwarnings("ignore")

# --- Workspace bridge pattern (NHM) ---
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"

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

from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config

config = load_subdomain_config(config_root)

# --- Derived from config ---
GPKG_PATH = config["model_dir"] / "GIS" / "model_layers.gpkg"
GPKG_LAYER = "nhru"
START_DATE = config["start_date"]
END_DATE = config["end_date"]
OUT = config["model_dir"]
OUT.mkdir(parents=True, exist_ok=True)

print(f"Domain:  {config['subdomain']}")
print(f"GPKG:    {GPKG_PATH}")
print(f"Period:  {START_DATE} to {END_DATE}")
print(f"Output:  {OUT}")

# %% [markdown]
# ## 2. Load HRU Polygons

# %%
nhru_gdf = gpd.read_file(GPKG_PATH, layer=GPKG_LAYER)

# Ensure unique geometries per HRU (dissolve duplicates)
ID_FIELD = "hru_id"
nhru_gdf = nhru_gdf.sort_values(ID_FIELD).dissolve(by=ID_FIELD, as_index=False)

print(f"HRU count: {len(nhru_gdf)}")

# %% [markdown]
# ## 3. Load climateR Catalog
#
# Uses a local copy of the catalog to avoid VPN/SSL issues.
# Falls back to the remote URL if the local file is not found.

# %%
_local_catalog = root_dir / "data_dependencies" / "climateR_catalog.parquet"

if _local_catalog.exists():
    cat = pd.read_parquet(_local_catalog)
    print(f"Using local catalog: {_local_catalog}")
else:
    climater_cat_url = (
        "https://github.com/mikejohnson51/climateR-catalogs/"
        "releases/download/June-2024/catalog.parquet"
    )
    try:
        cat = pd.read_parquet(climater_cat_url)
        print("Downloaded catalog from GitHub")
    except Exception as e:
        raise RuntimeError(
            "Cannot load climateR catalog. If on VPN, disconnect and retry, "
            "or place catalog.parquet in data_dependencies/climateR_catalog.parquet"
        ) from e

# Filter to gridMET variables
_id = "gridmet"
tvars = ["tmmn", "tmmx", "pr"]
cat_params = [
    cat.query("id == @_id & variable == @_var").to_dict(orient="records")[0]
    for _var in tvars
]
cat_dict = dict(zip(tvars, cat_params))

# %% [markdown]
# ## 4. Calculate Area-Weights and Aggregate
#
# This uses `gdptools` to:
# 1. Compute area-weighted intersection of gridMET cells with HRU polygons
# 2. Aggregate daily gridMET data to HRU-level means via OPeNDAP

# %%
user_data = ClimRCatData(
    cat_dict=cat_dict,
    f_feature=nhru_gdf,
    id_feature=ID_FIELD,
    period=[START_DATE, END_DATE],
)

# --- Calculate weights (cached) ---
weights_file = OUT / "nhru_weights_gridmet.csv"
if not weights_file.exists():
    print("Calculating spatial weights...")
    wght_gen = WeightGen(
        user_data=user_data,
        method="serial",
        output_file=str(weights_file),
        weight_gen_crs=5070,
    )
    wght_gen.calculate_weights()
    print(f"  Saved: {weights_file}")
else:
    print(f"Using cached weights: {weights_file}")

# --- Aggregate (cached) ---
gridmet_nc = OUT / "nhru_GRIDMET_daily.nc"
if not gridmet_nc.exists():
    print("Running area-weighted aggregation (this may take a while)...")
    agg = AggGen(
        user_data=user_data,
        stat_method="mean",
        agg_engine="serial",
        agg_writer="netcdf",
        weights=str(weights_file),
        out_path=str(OUT),
        file_prefix="nhru_GRIDMET_daily",
    )
    ngdf, ds_out = agg.calculate_agg()
    print(f"  Saved: {gridmet_nc}")
    print(f"  Variables: {list(ds_out.data_vars)}")
else:
    print(f"Using cached aggregation: {gridmet_nc}")

# %% [markdown]
# ## 5. Postprocess for pywatershed
#
# Splits the combined gridMET NetCDF into individual forcing files with
# pywatershed-expected units:
# - Precipitation: mm → inches
# - Temperature: Kelvin → Fahrenheit
#
# > **Note:** pywatershed expects temperature inputs in Fahrenheit.

# %%
pws_prcp_file = OUT / "prcp.nc"
pws_tmin_file = OUT / "tmin.nc"
pws_tmax_file = OUT / "tmax.nc"

if pws_prcp_file.exists() and pws_tmin_file.exists() and pws_tmax_file.exists():
    print("All pywatershed input files already exist. Skipping postprocess.")
    print("  To regenerate, delete prcp.nc, tmin.nc, and tmax.nc and re-run this cell.")
else:
    print("Postprocessing for pywatershed...")
    with xr.open_dataset(gridmet_nc) as ds:
        model_input = ds.rename({"hru_id": "nhm_id"})
        model_input = model_input.rename_vars(
            {
                "precipitation_amount": "prcp",
                "daily_minimum_temperature": "tmin",
                "daily_maximum_temperature": "tmax",
            }
        )

        # --- Precipitation: mm → inches ---
        prcp = model_input["prcp"] / 25.4
        prcp.attrs["long_name"] = "Daily accumulated precipitation"
        prcp.attrs["units"] = "inch"
        prcp.attrs["grid_mapping"] = "crs"
        prcp.coords["time"].attrs["standard_name"] = "time"
        prcp.coords["time"].attrs["long_name"] = "time"
        prcp.coords["nhm_id"].attrs["long_name"] = (
            "Global model Hydrologic Response Unit ID (HRU)"
        )

        # --- Tmin: Kelvin → Fahrenheit ---
        tmin = (model_input["tmin"] - 273.15) * (9.0 / 5.0) + 32.0
        tmin.attrs["long_name"] = "Minimum daily air temperature"
        tmin.attrs["units"] = "degree_Fahrenheit"
        tmin.attrs["grid_mapping"] = "crs"
        tmin.coords["time"].attrs["standard_name"] = "time"
        tmin.coords["time"].attrs["long_name"] = "time"
        tmin.coords["nhm_id"].attrs["long_name"] = (
            "Global model Hydrologic Response Unit ID (HRU)"
        )

        # --- Tmax: Kelvin → Fahrenheit ---
        tmax = (model_input["tmax"] - 273.15) * (9.0 / 5.0) + 32.0
        tmax.attrs["long_name"] = "Maximum daily air temperature"
        tmax.attrs["units"] = "degree_Fahrenheit"
        tmax.attrs["grid_mapping"] = "crs"
        tmax.coords["time"].attrs["standard_name"] = "time"
        tmax.coords["time"].attrs["long_name"] = "time"
        tmax.coords["nhm_id"].attrs["long_name"] = (
            "Global model Hydrologic Response Unit ID (HRU)"
        )

        prcp.to_netcdf(pws_prcp_file)
        tmin.to_netcdf(pws_tmin_file)
        tmax.to_netcdf(pws_tmax_file)

    print(f"  Written: {pws_prcp_file.name}, {pws_tmin_file.name}, {pws_tmax_file.name}")

# %% [markdown]
# ## 6. Verification

# %%
print("Output files:")
for f in [weights_file, gridmet_nc, pws_prcp_file, pws_tmin_file, pws_tmax_file]:
    if f.exists():
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  [OK] {f.name:35s} ({size_mb:.1f} MB)")
    else:
        print(f"  [MISSING] {f.name:35s}")

# Quick sanity check on temperature range
if pws_tmin_file.exists():
    with xr.open_dataset(pws_tmin_file) as ds_check:
        tmin_mean = float(ds_check["tmin"].mean())
        print(f"\n  tmin mean: {tmin_mean:.1f} deg F (expect ~30-50 for PNW)")
if pws_tmax_file.exists():
    with xr.open_dataset(pws_tmax_file) as ds_check:
        tmax_mean = float(ds_check["tmax"].mean())
        print(f"  tmax mean: {tmax_mean:.1f} deg F (expect ~50-70 for PNW)")

print("\nDone! These files are ready for notebook 4 (pywatershed).")

# %%
