"""Core gridMET processing logic — extracted from the notebook for HPC use.

This module contains the functions that do the actual work of downloading
and aggregating gridMET data to HRU polygons using gdptools. It's imported by:
- run_gridmet_single.py (HPC batch use via SLURM)

The logic here mirrors what happens in the interactive notebook
(Create_gridmet_climate_drivers_gdptools.ipynb) but is structured for
headless execution on HPC.
"""

import pathlib as pl

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr


def run_gridmet_for_domain(
    gpkg_path: pl.Path,
    gpkg_layer: str,
    start_date: str,
    end_date: str,
    variables: list,
    output_dir: pl.Path,
    work_dir: pl.Path,
):
    """
    Run the full gridMET processing pipeline for one domain.

    1. Read HRU polygons from geopackage
    2. Build area-weights using gdptools WeightGen
    3. Compute area-weighted averages per HRU using gdptools AggGen
    4. Postprocess to pywatershed-compatible forcing files (prcp.nc, tmin.nc, tmax.nc)

    Parameters
    ----------
    gpkg_path : Path to the domain geopackage
    gpkg_layer : Layer name (typically 'nhru')
    start_date : Start date string (YYYY-MM-DD)
    end_date : End date string (YYYY-MM-DD)
    variables : List of gridMET variables ['ppt', 'tmin', 'tmax']
    output_dir : Where to write final forcing files
    work_dir : Temporary working directory for intermediate files
    """
    from gdptools import AggGen, ClimRCatData, WeightGen

    # ------------------------------------------------------------------
    # 1. Read and prepare HRU polygons
    # ------------------------------------------------------------------
    print(f"  Reading HRU polygons from: {gpkg_path}")
    nhru_gdf = gpd.read_file(gpkg_path, layer=gpkg_layer)

    ID_FIELD = "hru_id"
    nhru_gdf = nhru_gdf.sort_values(ID_FIELD).dissolve(by=ID_FIELD, as_index=False)
    print(f"  HRU count: {len(nhru_gdf)}")

    # ------------------------------------------------------------------
    # 2. Set up climateR catalog for gridMET
    # ------------------------------------------------------------------
    print("  Loading climateR catalog...")
    # Use local catalog if available (avoids SSL issues on HPC compute nodes)
    # Check in the script directory (where catalog.parquet is transferred alongside scripts)
    script_dir = pl.Path(__file__).resolve().parent
    local_catalog = script_dir / "catalog.parquet"
    if not local_catalog.exists():
        # Also check relative to gpkg (3 levels up from GIS/<file>.gpkg)
        local_catalog = gpkg_path.parent.parent.parent / "catalog.parquet"
    if local_catalog.exists():
        cat = pd.read_parquet(local_catalog)
        print(f"  Using local catalog: {local_catalog}")
    else:
        climater_cat_url = (
            "https://github.com/mikejohnson51/climateR-catalogs/releases/"
            "download/June-2024/catalog.parquet"
        )
        cat = pd.read_parquet(climater_cat_url)

    _id = "gridmet"
    # Map our variable names to gridMET catalog variable names
    tvars = ["tmmn", "tmmx", "pr"]  # gridMET names: tmin, tmax, precip

    cat_params = [
        cat.query("id == @_id & variable == @_var").to_dict(orient="records")[0]
        for _var in tvars
    ]
    cat_dict = dict(zip(tvars, cat_params))

    # ------------------------------------------------------------------
    # 3. Build gdptools user data object
    # ------------------------------------------------------------------
    user_data = ClimRCatData(
        cat_dict=cat_dict,
        f_feature=nhru_gdf,
        id_feature=ID_FIELD,
        period=[start_date, end_date],
    )

    # ------------------------------------------------------------------
    # 4. Calculate area-weights (if not already cached)
    # ------------------------------------------------------------------
    weights_file = output_dir / "nhru_weights_gridmet.csv"
    if not weights_file.exists():
        print("  Calculating spatial weights (this may take a while)...")
        wght_gen = WeightGen(
            user_data=user_data,
            method="serial",
            output_file=str(weights_file),
            weight_gen_crs=5070,
        )
        wght_gen.calculate_weights()
        print(f"  Weights saved: {weights_file}")
    else:
        print(f"  Using cached weights: {weights_file}")

    # ------------------------------------------------------------------
    # 5. Aggregate gridMET to HRU polygons
    # ------------------------------------------------------------------
    gridmet_nc = output_dir / "nhru_GRIDMET_daily.nc"
    if not gridmet_nc.exists():
        print("  Running area-weighted aggregation...")
        agg = AggGen(
            user_data=user_data,
            stat_method="mean",
            agg_engine="serial",
            agg_writer="netcdf",
            weights=str(weights_file),
            out_path=str(output_dir),
            file_prefix="nhru_GRIDMET_daily",
        )
        ngdf, ds_out = agg.calculate_agg()
        print(f"  Aggregated NetCDF saved: {gridmet_nc}")
        print(f"  Variables: {list(ds_out.data_vars)}")
    else:
        print(f"  Using cached aggregation: {gridmet_nc}")

    # ------------------------------------------------------------------
    # 6. Postprocess for pywatershed (split into prcp.nc, tmin.nc, tmax.nc)
    #    - Precipitation: mm -> inches
    #    - Temperature: Kelvin -> Fahrenheit
    #    (NHM/pywatershed expects Fahrenheit for temperature inputs)
    # ------------------------------------------------------------------
    print("  Postprocessing for pywatershed...")
    _postprocess_for_pywatershed(output_dir, gridmet_nc)

    print("  Done!")


def _postprocess_for_pywatershed(output_dir: pl.Path, gridmet_nc: pl.Path):
    """
    Split the combined gridMET NetCDF into individual pywatershed input files.

    Converts:
    - precipitation_amount (mm) -> prcp (inches)
    - daily_minimum_temperature (K) -> tmin (°F)
    - daily_maximum_temperature (K) -> tmax (°F)
    """
    pws_prcp_file = output_dir / "prcp.nc"
    pws_tmin_file = output_dir / "tmin.nc"
    pws_tmax_file = output_dir / "tmax.nc"

    # Check if all files already exist
    if pws_prcp_file.exists() and pws_tmin_file.exists() and pws_tmax_file.exists():
        print("    All pywatershed input files already exist. Skipping postprocess.")
        return

    with xr.open_dataset(gridmet_nc) as ds:
        # Rename dimensions to match pywatershed expectations
        model_input = ds.rename({"hru_id": "nhm_id"})
        model_input = model_input.rename_vars(
            {
                "precipitation_amount": "prcp",
                "daily_minimum_temperature": "tmin",
                "daily_maximum_temperature": "tmax",
            }
        )

        # --- Precipitation: mm -> inches ---
        prcp = model_input["prcp"] / 25.4
        prcp.attrs["long_name"] = "Daily accumulated precipitation"
        prcp.attrs["units"] = "inch"
        prcp.attrs["grid_mapping"] = "crs"
        prcp.coords["time"].attrs["standard_name"] = "time"
        prcp.coords["time"].attrs["long_name"] = "time"
        prcp.coords["nhm_id"].attrs["long_name"] = (
            "Global model Hydrologic Response Unit ID (HRU)"
        )

        # --- Tmin: Kelvin -> Fahrenheit ---
        tmin = (model_input["tmin"] - 273.15) * (9.0 / 5.0) + 32.0
        tmin.attrs["long_name"] = "Minimum daily air temperature"
        tmin.attrs["units"] = "degree_Fahrenheit"
        tmin.attrs["grid_mapping"] = "crs"
        tmin.coords["time"].attrs["standard_name"] = "time"
        tmin.coords["time"].attrs["long_name"] = "time"
        tmin.coords["nhm_id"].attrs["long_name"] = (
            "Global model Hydrologic Response Unit ID (HRU)"
        )

        # --- Tmax: Kelvin -> Fahrenheit ---
        tmax = (model_input["tmax"] - 273.15) * (9.0 / 5.0) + 32.0
        tmax.attrs["long_name"] = "Maximum daily air temperature"
        tmax.attrs["units"] = "degree_Fahrenheit"
        tmax.attrs["grid_mapping"] = "crs"
        tmax.coords["time"].attrs["standard_name"] = "time"
        tmax.coords["time"].attrs["long_name"] = "time"
        tmax.coords["nhm_id"].attrs["long_name"] = (
            "Global model Hydrologic Response Unit ID (HRU)"
        )

        # Write individual files
        prcp.to_netcdf(pws_prcp_file)
        print(f"    Written: {pws_prcp_file}")

        tmin.to_netcdf(pws_tmin_file)
        print(f"    Written: {pws_tmin_file}")

        tmax.to_netcdf(pws_tmax_file)
        print(f"    Written: {pws_tmax_file}")
