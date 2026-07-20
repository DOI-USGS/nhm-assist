"""Functions for computing pywatershed (PRMS) parameters.

This module provides reusable functions for the parameter creation workflows
in the nhf_assist notebooks. Each function corresponds to a discrete workflow
step (data fetching, processing, grid-to-HRU mapping, etc.).
"""

import calendar
import pathlib as pl

import geopandas as gpd
import numpy as np
import xarray as xr


def fetch_era5_data(gpkg_path, data_dir, start_year, end_year):
    """Download ERA5 2m_temperature and precipitation_type for a domain.

    Downloads hourly ERA5 reanalysis data clipped to the bounding box of the
    HRUs in the provided GeoPackage. Skips files that already exist.
    After downloading, validates that each file has the expected number of
    time steps.

    Parameters
    ----------
    gpkg_path : pathlib.Path
        Path to the v2 GeoPackage containing an "nhru" layer (used for bbox).
    data_dir : pathlib.Path
        Directory where ERA5 NetCDF files will be stored.
    start_year : int
        First year to download (inclusive).
    end_year : int
        Last year to download (inclusive).

    Returns
    -------
    bool
        True if all files are present and valid, False otherwise.
    """
    import cdsapi

    data_dir = pl.Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    c = cdsapi.Client()

    # Get bounding box from OHM HRUs
    hru_gdf = gpd.read_file(gpkg_path, layer="nhru").to_crs(epsg=4326)
    bounds = hru_gdf.total_bounds  # [minx, miny, maxx, maxy]
    # ERA5 area format: [N, W, S, E]
    area = [bounds[3] + 1, bounds[0] - 1, bounds[1] - 1, bounds[2] + 1]

    # Download 2m_temperature and precipitation_type separately
    for year in range(start_year, end_year + 1):
        # --- 2m_temperature ---
        t2m_file = data_dir / f"t2m_{year}.nc"
        if not t2m_file.exists():
            print(f"Downloading t2m {year}...")
            c.retrieve('reanalysis-era5-single-levels',
                       {'product_type': 'reanalysis',
                        'variable': '2m_temperature',
                        'year': year,
                        'month': [f'{m:02d}' for m in range(1, 13)],
                        'day': [f'{d:02d}' for d in range(1, 32)],
                        'area': area,
                        'time': [f'{h:02d}:00' for h in range(24)],
                        'format': 'netcdf'},
                       str(t2m_file))
        else:
            print(f"  t2m_{year}.nc already exists, skipping.")

        # --- precipitation_type ---
        ptype_file = data_dir / f"ptype_{year}.nc"
        if not ptype_file.exists():
            print(f"Downloading ptype {year}...")
            c.retrieve('reanalysis-era5-single-levels',
                       {'product_type': 'reanalysis',
                        'variable': 'precipitation_type',
                        'year': year,
                        'month': [f'{m:02d}' for m in range(1, 13)],
                        'day': [f'{d:02d}' for d in range(1, 32)],
                        'area': area,
                        'time': [f'{h:02d}:00' for h in range(24)],
                        'format': 'netcdf'},
                       str(ptype_file))
        else:
            print(f"  ptype_{year}.nc already exists, skipping.")

    print(f"\nDownload complete. Data directory: {data_dir}")
    print(f"  Years: {start_year}-{end_year}")

    # --- Validate downloaded files ---
    print(f"\n{'Year':<6} {'Variable':<8} {'Expected hrs':<14} {'Actual hrs':<12} {'Status'}")
    print("-" * 55)

    all_valid = True
    for year in range(start_year, end_year + 1):
        days_in_year = 366 if calendar.isleap(year) else 365
        expected_hours = days_in_year * 24

        for var_name, prefix in [("t2m", "t2m"), ("ptype", "ptype")]:
            fpath = data_dir / f"{prefix}_{year}.nc"
            if not fpath.exists():
                print(f"{year:<6} {var_name:<8} {'—':<14} {'MISSING':<12}")
                all_valid = False
                continue

            ds = xr.open_dataset(fpath)
            time_dim = "valid_time" if "valid_time" in ds.dims else "time"
            actual_hours = ds.sizes.get(time_dim, 0)
            ds.close()

            status = "ok" if actual_hours == expected_hours else f"INCOMPLETE (missing {expected_hours - actual_hours})"
            if actual_hours != expected_hours:
                all_valid = False
            print(f"{year:<6} {var_name:<8} {expected_hours:<14} {actual_hours:<12} {status}")

    if all_valid:
        print("\nAll files complete.")
    else:
        print("\nSome files are incomplete or missing. Re-download those years.")

    return all_valid


def process_era5_ptype_masking(data_dir, start_year, end_year):
    """Process ERA5 data: mask temperature by precipitation type and compute monthly climatology.

    For each year, masks 2m temperature by ERA5 precipitation type:
    - Snow (ptype == 5): t2m clipped to [271.04, 274.4] K
    - Rain (ptype == 1): t2m clipped to [274.65, 276.48] K

    Computes monthly means per year, then averages across all years to produce
    a 12-month climatology (equivalent to CDO ymonmean).

    Parameters
    ----------
    data_dir : pathlib.Path
        Directory containing ERA5 NetCDF files (t2m_{year}.nc, ptype_{year}.nc).
    start_year : int
        First year to process (inclusive).
    end_year : int
        Last year to process (inclusive).

    Returns
    -------
    xarray.Dataset or None
        Dataset with variables 't2m_snow' and 't2m_rain', dimensioned
        (month, latitude, longitude) with month 1-12. Returns None if no
        valid files were found.
    """
    data_dir = pl.Path(data_dir)
    monthly_files = []

    for year in range(start_year, end_year + 1):
        t2m_file = data_dir / f"t2m_{year}.nc"
        ptype_file = data_dir / f"ptype_{year}.nc"

        if not t2m_file.exists() or not ptype_file.exists():
            print(f"  WARNING: files for {year} not found, skipping")
            continue

        print(f"Processing {year}...")
        ds_t2m = xr.open_dataset(t2m_file)
        ds_ptype = xr.open_dataset(ptype_file)

        # Drop extra coordinates/dims that cause broadcasting issues
        t2m = ds_t2m["t2m"].squeeze(drop=True)
        if "expver" in t2m.coords:
            t2m = t2m.drop_vars("expver")
        if "number" in t2m.coords:
            t2m = t2m.drop_vars("number")

        # ptype variable name may vary — find it
        ptype_var = [v for v in ds_ptype.data_vars if "ptype" in v.lower() or "precipitation_type" in v.lower()]
        if not ptype_var:
            ptype_var = [v for v in ds_ptype.data_vars if v not in ["latitude", "longitude", "number", "expver"]]
        ptype = ds_ptype[ptype_var[0]].squeeze(drop=True)
        if "expver" in ptype.coords:
            ptype = ptype.drop_vars("expver")
        # Convert ptype longitude from 0-360 to -180-180 if needed
        if ptype.longitude.values.max() > 180:
            ptype = ptype.assign_coords(longitude=(ptype.longitude.values + 180) % 360 - 180)
            ptype = ptype.sortby("longitude")
        # Align ptype coordinates to match t2m exactly
        ptype = ptype.assign_coords(latitude=t2m.latitude, longitude=t2m.longitude)
        print(f"  Using ptype variable: '{ptype_var[0]}'")

        # t2m when snow (ptype==5), clipped
        t2m_snow = t2m.where(ptype == 5)
        t2m_snow = t2m_snow.clip(min=271.04, max=274.4)

        # t2m when rain (ptype==1), clipped
        t2m_rain = t2m.where(ptype == 1)
        t2m_rain = t2m_rain.clip(min=274.65, max=276.48)

        # Compute monthly mean
        time_dim = "valid_time" if "valid_time" in t2m_snow.dims else "time"
        ds_masked = xr.Dataset({
            "t2m_snow": t2m_snow,
            "t2m_rain": t2m_rain,
        })
        if time_dim == "valid_time":
            ds_masked = ds_masked.rename({"valid_time": "time"})
        monthly = ds_masked.resample(time="1MS").mean()
        monthly_files.append(monthly)

        ds_t2m.close()
        ds_ptype.close()
        print(f"  {year} done.")

    if not monthly_files:
        print("No ERA5 files found. Download data first (Step 1).")
        return None

    # Concatenate all years and compute mean monthly (ymonmean equivalent)
    all_monthly = xr.concat(monthly_files, dim="time")
    ymon_mean = all_monthly.groupby("time.month").mean(dim="time")
    print(f"\nFinal dataset: {ymon_mean.dims}")
    print(f"  t2m_snow shape: {ymon_mean['t2m_snow'].shape}")
    print(f"  t2m_rain shape: {ymon_mean['t2m_rain'].shape}")

    return ymon_mean


def compute_era5_hru_weights(gpkg_path, data_dir, start_year, grid_spacing, output_dir,
                             hru_id_col="model_hru_idx"):
    """Compute area-weighted intersection between ERA5 grid cells and v2 HRUs.

    Creates polygons for each ERA5 grid cell (based on the downloaded data grid),
    then computes the fractional intersection area with each HRU. Saves the
    resulting weights table to CSV.

    Parameters
    ----------
    gpkg_path : pathlib.Path
        Path to the v2 GeoPackage containing an "nhru" layer.
    data_dir : pathlib.Path
        Directory containing ERA5 NetCDF files (uses t2m_{start_year}.nc for grid).
    start_year : int
        Year used to determine the ERA5 grid structure.
    grid_spacing : float
        ERA5 grid spacing in degrees (typically 0.25).
    output_dir : pathlib.Path
        Directory where era5_weights.csv will be saved.
    hru_id_col : str, optional
        Column name in the GeoPackage nhru layer to use as the HRU identifier.
        Default is "model_hru_idx".

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns: grid_id, <hru_id_col>, weight.
    """
    import pandas as pd
    from shapely.geometry import Polygon
    from tqdm.auto import tqdm

    data_dir = pl.Path(data_dir)
    output_dir = pl.Path(output_dir)

    # Load OHM HRUs
    hru_gdf = gpd.read_file(gpkg_path, layer="nhru").to_crs(epsg=4326)
    print(f"Loaded {len(hru_gdf)} v2 HRUs")

    if hru_id_col not in hru_gdf.columns:
        raise ValueError(f"Column '{hru_id_col}' not found in GeoPackage nhru layer. "
                         f"Available columns: {hru_gdf.columns.tolist()}")

    # Use the actual ERA5 downloaded data grid
    sample_file = data_dir / f"t2m_{start_year}.nc"
    ds_grid = xr.open_dataset(sample_file)
    lat = ds_grid["latitude"].values
    lon = ds_grid["longitude"].values
    ds_grid.close()

    print(f"ERA5 grid from downloaded data: {len(lat)} lat x {len(lon)} lon = {len(lat) * len(lon)} cells")

    # Create grid cell polygons
    res = grid_spacing / 2.0
    polys = []
    grid_indices = []
    idx = 0

    for i, la in enumerate(lat):
        for j, lo in enumerate(lon):
            poly = Polygon([
                (lo - res, la - res),
                (lo + res, la - res),
                (lo + res, la + res),
                (lo - res, la + res),
            ])
            polys.append(poly)
            grid_indices.append(idx)
            idx += 1

    grid_gdf = gpd.GeoDataFrame(
        {"grid_id": grid_indices},
        geometry=polys,
        crs="EPSG:4326",
    )
    print(f"Created {len(grid_gdf)} grid cell polygons")

    # Compute intersection weights between grid cells and HRUs
    weights = []

    for hru_idx, hru_row in tqdm(hru_gdf.iterrows(), total=len(hru_gdf), desc="Computing weights"):
        hru_geom = hru_row["geometry"]
        hru_area = hru_geom.area
        hru_id = hru_row[hru_id_col]

        # Use spatial index to find candidate grid cells
        candidates = grid_gdf[grid_gdf.intersects(hru_geom)]

        for _, cell_row in candidates.iterrows():
            intersection = hru_geom.intersection(cell_row["geometry"])
            if not intersection.is_empty:
                weight = intersection.area / hru_area
                weights.append({
                    "grid_id": cell_row["grid_id"],
                    hru_id_col: hru_id,
                    "weight": weight,
                })

    weights_df = pd.DataFrame(weights)
    print(f"Computed {len(weights_df)} weight entries for {weights_df[hru_id_col].nunique()} HRUs")

    # Save weights
    weights_file = output_dir / "era5_weights.csv"
    weights_df.to_csv(weights_file, index=False)
    print(f"Saved weights to {weights_file}")

    return weights_df


def apply_era5_weights_to_hrus(ymon_mean, weights_df, nhru, hru_id_col="model_hru_idx"):
    """Apply ERA5 grid-to-HRU area weights to compute tmax_allsnow and tmax_allrain_offset.

    For each HRU and month, computes the area-weighted mean of the masked ERA5
    temperature fields (t2m_snow, t2m_rain) using the intersection weights.
    Converts from Kelvin to Fahrenheit and computes the rain-snow offset.

    Parameters
    ----------
    ymon_mean : xarray.Dataset
        Monthly climatology with variables 't2m_snow' and 't2m_rain',
        dimensioned (month, latitude, longitude). Output of
        process_era5_ptype_masking().
    weights_df : pandas.DataFrame
        Grid-to-HRU weights with columns: grid_id, <hru_id_col>, weight.
        Output of compute_era5_hru_weights().
    nhru : int
        Total number of HRUs.
    hru_id_col : str, optional
        Column name in weights_df used as the HRU identifier.
        Default is "model_hru_idx".

    Returns
    -------
    tuple of (numpy.ndarray, numpy.ndarray, numpy.ndarray)
        - allsnow_f: tmax_allsnow in °F, shape (nhru, 12)
        - allsnow_f: same as above (kept for clarity)
        - allrain_offset: tmax_allrain_offset in °F, shape (nhru, 12)
    """
    def _compute_weighted_param(ymon_data, var_name, weights, n_hru, id_col, nan_default=np.nan):
        """Compute area-weighted monthly values per HRU."""
        hru_groups = weights.groupby(id_col)
        result = np.full((n_hru, 12), nan_default)

        months = ymon_data["month"].values

        for i, month in enumerate(months):
            grid_values = ymon_data[var_name].sel(month=month).values.flatten()

            if grid_values.size == 0:
                print(f"  WARNING: no data for month {month}")
                continue

            for hru_id, group in hru_groups:
                grid_ids = group["grid_id"].values
                wgts = group["weight"].values

                # Bounds check
                valid_ids = grid_ids[grid_ids < len(grid_values)]
                valid_wgts = wgts[grid_ids < len(grid_values)]

                if len(valid_ids) == 0:
                    continue

                # Get values at grid cells, mask NaN
                vals = grid_values[valid_ids]
                valid = ~np.isnan(vals)

                if valid.sum() > 0:
                    result[int(hru_id) - 1, i] = np.average(vals[valid], weights=valid_wgts[valid])

        return result

    print("Computing tmax_allsnow...")
    allsnow = _compute_weighted_param(ymon_mean, "t2m_snow", weights_df, nhru, hru_id_col,
                                      nan_default=273.15)
    allsnow_f = (allsnow - 273.15) * 1.8 + 32.0
    print(f"  tmax_allsnow range: {np.nanmin(allsnow_f):.2f} — {np.nanmax(allsnow_f):.2f} °F")

    print("Computing tmax_allrain...")
    allrain = _compute_weighted_param(ymon_mean, "t2m_rain", weights_df, nhru, hru_id_col,
                                      nan_default=274.65)
    allrain_f = (allrain - 273.15) * 1.8 + 32.0
    allrain_offset = allrain_f - allsnow_f
    print(f"  tmax_allrain_offset range: {np.nanmin(allrain_offset):.2f} — {np.nanmax(allrain_offset):.2f} °F")

    return allsnow_f, allrain_f, allrain_offset


def fetch_hrrr_ptype_data(start_date, end_date, cache_file):
    """Download and process HRRR hourly data, masking t2m by snow/rain flags.

    For each hour in the date range, fetches HRRR 2m temperature, CSNOW, and
    CRAIN fields. Accumulates monthly sums and counts of t2m masked by snow
    and rain flags. Results are saved to a .npz cache file.

    If the cache file already exists, loads from cache and skips processing.

    Parameters
    ----------
    start_date : str
        Start date in "YYYY-MM-DD" format (inclusive).
    end_date : str
        End date in "YYYY-MM-DD" format (inclusive).
    cache_file : pathlib.Path
        Path to the .npz cache file for saving/loading results.

    Returns
    -------
    dict
        Dictionary with keys: 'hrrr_snow_sum', 'hrrr_rain_sum',
        'hrrr_snow_count', 'hrrr_rain_count', 'hrrr_lats', 'hrrr_lons'.
        Each value is a numpy array. Sum/count arrays have shape (12, ny, nx).
    """
    import calendar
    from datetime import datetime as dt

    from herbie import Herbie

    cache_file = pl.Path(cache_file)

    if cache_file.exists():
        print(f"Loading HRRR processed cache from {cache_file}")
        cache = np.load(cache_file)
        result = {
            "hrrr_snow_sum": cache["hrrr_snow_sum"],
            "hrrr_rain_sum": cache["hrrr_rain_sum"],
            "hrrr_snow_count": cache["hrrr_snow_count"],
            "hrrr_rain_count": cache["hrrr_rain_count"],
            "hrrr_lats": cache["hrrr_lats"],
            "hrrr_lons": cache["hrrr_lons"],
        }
        print(f"  Loaded. Shape: {result['hrrr_snow_sum'].shape}")
        print("  To re-process, delete the cache file and re-run.")
        return result

    _start = dt.strptime(start_date, "%Y-%m-%d")
    _end = dt.strptime(end_date, "%Y-%m-%d")

    hrrr_lats = None
    hrrr_lons = None
    hrrr_snow_sum = None
    hrrr_rain_sum = None
    hrrr_snow_count = None
    hrrr_rain_count = None

    for year in range(_start.year, _end.year + 1):
        for month in range(1, 13):
            # Skip months outside the specified date range
            if dt(year, month, 1) < dt(_start.year, _start.month, 1):
                continue
            if dt(year, month, 1) > dt(_end.year, _end.month, 1):
                continue

            days_in_month = calendar.monthrange(year, month)[1]
            month_snow_count = 0
            month_rain_count = 0

            for day in range(1, days_in_month + 1):
                for hour in range(24):
                    try:
                        date = dt(year, month, day, hour)
                        H = Herbie(date, model="hrrr", product="sfc", fxx=1)
                        ds_tmp = H.xarray(":TMP:2 m above ground")
                        ds_csnow = H.xarray(":CSNOW:surface")
                        ds_crain = H.xarray(":CRAIN:surface")

                        t2m_var = [v for v in ds_tmp.data_vars if v not in ["gribfile_projection"]][0]
                        csnow_var = [v for v in ds_csnow.data_vars if v not in ["gribfile_projection"]][0]
                        crain_var = [v for v in ds_crain.data_vars if v not in ["gribfile_projection"]][0]

                        t2m = ds_tmp[t2m_var].values
                        csnow = ds_csnow[csnow_var].values
                        crain = ds_crain[crain_var].values

                        if hrrr_lats is None:
                            hrrr_lats = ds_tmp["latitude"].values
                            hrrr_lons = ds_tmp["longitude"].values
                            ny, nx = hrrr_lats.shape
                            hrrr_snow_sum = np.zeros((12, ny, nx))
                            hrrr_rain_sum = np.zeros((12, ny, nx))
                            hrrr_snow_count = np.zeros((12, ny, nx))
                            hrrr_rain_count = np.zeros((12, ny, nx))

                        snow_mask = csnow == 1
                        hrrr_snow_sum[month - 1][snow_mask] += t2m[snow_mask]
                        hrrr_snow_count[month - 1][snow_mask] += 1

                        rain_mask = crain == 1
                        hrrr_rain_sum[month - 1][rain_mask] += t2m[rain_mask]
                        hrrr_rain_count[month - 1][rain_mask] += 1

                        month_snow_count += snow_mask.sum()
                        month_rain_count += rain_mask.sum()

                        del ds_tmp, ds_csnow, ds_crain, t2m, csnow, crain

                    except Exception:
                        pass

            print(f"  {year}-{month:02d}: snow_obs={month_snow_count:,}, rain_obs={month_rain_count:,}")

    print(f"\nDone processing HRRR {_start.year}-{_end.year}")

    # Save processed results as a checkpoint
    np.savez(
        cache_file,
        hrrr_snow_sum=hrrr_snow_sum,
        hrrr_rain_sum=hrrr_rain_sum,
        hrrr_snow_count=hrrr_snow_count,
        hrrr_rain_count=hrrr_rain_count,
        hrrr_lats=hrrr_lats,
        hrrr_lons=hrrr_lons,
    )
    print(f"Saved HRRR processed cache to {cache_file}")

    return {
        "hrrr_snow_sum": hrrr_snow_sum,
        "hrrr_rain_sum": hrrr_rain_sum,
        "hrrr_snow_count": hrrr_snow_count,
        "hrrr_rain_count": hrrr_rain_count,
        "hrrr_lats": hrrr_lats,
        "hrrr_lons": hrrr_lons,
    }


def fetch_hrrr_ptype_data_zarr(start_date, end_date, cache_file, gpkg_path=None):
    """Download and process HRRR hourly data from S3 Zarr archive.

    Reads HRRR analysis data directly from the University of Utah HRRR Zarr
    archive on S3 (s3://hrrrzarr/). For each hour in the date range, reads
    2m temperature, CSNOW, and CRAIN fields. Accumulates monthly sums and
    counts of t2m masked by snow and rain flags.

    When gpkg_path is provided, only the spatial subset of the HRRR grid
    covering the model domain is read (domain-clipped). This dramatically
    reduces data transfer compared to reading the full CONUS grid.

    This replaces the Herbie-based approach (fetch_hrrr_ptype_data) with
    cloud-native S3 Zarr access, avoiding GRIB download/decode overhead.

    Parameters
    ----------
    start_date : str
        Start date in "YYYY-MM-DD" format (inclusive).
    end_date : str
        End date in "YYYY-MM-DD" format (inclusive).
    cache_file : pathlib.Path
        Path to the .npz cache file for saving/loading results.
    gpkg_path : pathlib.Path or str, optional
        Path to the OHM GeoPackage. If provided, only HRRR grid cells
        overlapping the domain bounding box (plus a small buffer) are read.
        If None, the full CONUS grid is read.

    Returns
    -------
    dict
        Dictionary with keys: 'hrrr_snow_sum', 'hrrr_rain_sum',
        'hrrr_snow_count', 'hrrr_rain_count', 'hrrr_lats', 'hrrr_lons'.
        Each value is a numpy array. Sum/count arrays have shape
        (12, ny_sub, nx_sub) where sub is the clipped domain if gpkg_path
        was provided, or full CONUS otherwise.
    """
    import calendar
    from datetime import datetime as dt

    import geopandas as _gpd

    cache_file = pl.Path(cache_file)

    if cache_file.exists():
        print(f"Loading HRRR processed cache from {cache_file}")
        cache = np.load(cache_file)
        result = {
            "hrrr_snow_sum": cache["hrrr_snow_sum"],
            "hrrr_rain_sum": cache["hrrr_rain_sum"],
            "hrrr_snow_count": cache["hrrr_snow_count"],
            "hrrr_rain_count": cache["hrrr_rain_count"],
            "hrrr_lats": cache["hrrr_lats"],
            "hrrr_lons": cache["hrrr_lons"],
        }
        print(f"  Loaded. Shape: {result['hrrr_snow_sum'].shape}")
        print("  To re-process, delete the cache file and re-run.")
        return result

    s3opts = dict(anon=True)

    _start = dt.strptime(start_date, "%Y-%m-%d")
    _end = dt.strptime(end_date, "%Y-%m-%d")

    # Read full lat/lon grid from the static HRRR grid index
    grid_ds = xr.open_zarr("s3://hrrrzarr/grid/HRRR_chunk_index.zarr", storage_options=s3opts)
    full_lats = grid_ds["latitude"].values
    full_lons = grid_ds["longitude"].values
    grid_ds.close()

    # Determine spatial subset if domain GeoPackage is provided
    y_slice = slice(None)
    x_slice = slice(None)

    if gpkg_path is not None:
        gpkg_path = pl.Path(gpkg_path)
        hru_gdf = _gpd.read_file(gpkg_path, layer="nhru")
        bounds = hru_gdf.to_crs(epsg=4326).total_bounds  # [minlon, minlat, maxlon, maxlat]

        # Add a small buffer (0.5 degrees) to ensure full coverage
        buf = 0.5
        # HRRR longitudes are in 0-360 range; convert domain bounds if negative
        minlon = bounds[0] + 360.0 if bounds[0] < 0 else bounds[0]
        maxlon = bounds[2] + 360.0 if bounds[2] < 0 else bounds[2]
        minlat = bounds[1]
        maxlat = bounds[3]

        # Check if HRRR lons are in -180 to 180 or 0 to 360
        if full_lons.max() > 180:
            # HRRR uses 0-360 longitude
            lon_for_mask = full_lons
            domain_minlon = minlon - buf
            domain_maxlon = maxlon + buf
        else:
            # HRRR uses -180 to 180 longitude
            lon_for_mask = full_lons
            domain_minlon = bounds[0] - buf
            domain_maxlon = bounds[2] + buf

        mask = (
            (full_lats >= minlat - buf) & (full_lats <= maxlat + buf) &
            (lon_for_mask >= domain_minlon) & (lon_for_mask <= domain_maxlon)
        )

        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]

        if len(rows) == 0 or len(cols) == 0:
            raise ValueError(
                f"No HRRR grid cells found within domain bounds {bounds}. "
                "Check CRS and longitude convention."
            )

        y_slice = slice(int(rows.min()), int(rows.max()) + 1)
        x_slice = slice(int(cols.min()), int(cols.max()) + 1)

        print(f"Domain clipping enabled:")
        print(f"  Domain bounds (EPSG:4326): lon=[{bounds[0]:.2f}, {bounds[2]:.2f}], lat=[{bounds[1]:.2f}, {bounds[3]:.2f}]")
        print(f"  HRRR subset: y=[{y_slice.start}:{y_slice.stop}], x=[{x_slice.start}:{x_slice.stop}]")
        print(f"  Full grid: {full_lats.shape[0]} x {full_lats.shape[1]} → Subset: {y_slice.stop - y_slice.start} x {x_slice.stop - x_slice.start}")

    # Extract the (possibly clipped) lat/lon arrays
    hrrr_lats = full_lats[y_slice, x_slice]
    hrrr_lons = full_lons[y_slice, x_slice]
    ny, nx = hrrr_lats.shape

    hrrr_snow_sum = np.zeros((12, ny, nx))
    hrrr_rain_sum = np.zeros((12, ny, nx))
    hrrr_snow_count = np.zeros((12, ny, nx))
    hrrr_rain_count = np.zeros((12, ny, nx))

    print(f"HRRR processing grid shape: {ny} x {nx}")
    print(f"Processing {_start.date()} to {_end.date()} from s3://hrrrzarr/ ...")

    for year in range(_start.year, _end.year + 1):
        for month in range(1, 13):
            if dt(year, month, 1) < dt(_start.year, _start.month, 1):
                continue
            if dt(year, month, 1) > dt(_end.year, _end.month, 1):
                continue

            days_in_month = calendar.monthrange(year, month)[1]
            month_snow_count = 0
            month_rain_count = 0

            for day in range(1, days_in_month + 1):
                date_str = f"{year}{month:02d}{day:02d}"
                for hour in range(24):
                    try:
                        zarr_base = f"s3://hrrrzarr/sfc/{date_str}/{date_str}_{hour:02d}z_anl.zarr"

                        # Read TMP (2m temperature in K) — domain subset only
                        # Data is at: {base}/2m_above_ground/TMP/2m_above_ground/TMP
                        ds_tmp = xr.open_zarr(
                            f"{zarr_base}/2m_above_ground/TMP/2m_above_ground/TMP",
                            storage_options=s3opts,
                        )
                        t2m = ds_tmp[list(ds_tmp.data_vars)[0]].values[y_slice, x_slice]
                        ds_tmp.close()

                        # Read CSNOW (categorical snow flag) — domain subset only
                        ds_csnow = xr.open_zarr(
                            f"{zarr_base}/surface/CSNOW/surface/CSNOW",
                            storage_options=s3opts,
                        )
                        csnow = ds_csnow[list(ds_csnow.data_vars)[0]].values[y_slice, x_slice]
                        ds_csnow.close()

                        # Read CRAIN (categorical rain flag) — domain subset only
                        ds_crain = xr.open_zarr(
                            f"{zarr_base}/surface/CRAIN/surface/CRAIN",
                            storage_options=s3opts,
                        )
                        crain = ds_crain[list(ds_crain.data_vars)[0]].values[y_slice, x_slice]
                        ds_crain.close()

                        # Accumulate snow-masked temperature
                        snow_mask = csnow == 1
                        hrrr_snow_sum[month - 1][snow_mask] += t2m[snow_mask]
                        hrrr_snow_count[month - 1][snow_mask] += 1

                        # Accumulate rain-masked temperature
                        rain_mask = crain == 1
                        hrrr_rain_sum[month - 1][rain_mask] += t2m[rain_mask]
                        hrrr_rain_count[month - 1][rain_mask] += 1

                        month_snow_count += snow_mask.sum()
                        month_rain_count += rain_mask.sum()

                    except Exception:
                        pass

            print(f"  {year}-{month:02d}: snow_obs={month_snow_count:,}, rain_obs={month_rain_count:,}")

    print(f"\nDone processing HRRR {_start.year}-{_end.year}")

    np.savez(
        cache_file,
        hrrr_snow_sum=hrrr_snow_sum,
        hrrr_rain_sum=hrrr_rain_sum,
        hrrr_snow_count=hrrr_snow_count,
        hrrr_rain_count=hrrr_rain_count,
        hrrr_lats=hrrr_lats,
        hrrr_lons=hrrr_lons,
    )
    print(f"Saved HRRR processed cache to {cache_file}")

    return {
        "hrrr_snow_sum": hrrr_snow_sum,
        "hrrr_rain_sum": hrrr_rain_sum,
        "hrrr_snow_count": hrrr_snow_count,
        "hrrr_rain_count": hrrr_rain_count,
        "hrrr_lats": hrrr_lats,
        "hrrr_lons": hrrr_lons,
    }


def process_hrrr_climatology_and_weights(cache_file, gpkg_path, hru_id_col="model_hru_idx"):
    """Compute HRRR monthly climatology and grid-to-HRU weights.

    Loads the HRRR processed cache (.npz), computes mean monthly t2m for snow
    and rain conditions, clips to physical bounds, then builds point-in-polygon
    weights mapping HRRR grid cells to HRUs.

    Parameters
    ----------
    cache_file : pathlib.Path
        Path to the .npz cache file produced by fetch_hrrr_ptype_data().
    gpkg_path : pathlib.Path
        Path to the v2 GeoPackage containing an "nhru" layer.
    hru_id_col : str, optional
        Column name in the GeoPackage nhru layer to use as the HRU identifier.
        Default is "model_hru_idx".

    Returns
    -------
    tuple of (numpy.ndarray, numpy.ndarray, pandas.DataFrame)
        - hrrr_ymon_snow: monthly mean snow temperature (12, ny, nx) in K,
          clipped to [271.04, 274.4]
        - hrrr_ymon_rain: monthly mean rain temperature (12, ny, nx) in K,
          clipped to [274.65, 276.48]
        - hrrr_weights: DataFrame with columns: grid_id, <hru_id_col>, weight
    """
    import pandas as pd

    cache_file = pl.Path(cache_file)

    # --- Step H2: Compute monthly climatology ---
    print(f"Loading HRRR processed cache from {cache_file}...")
    cache = np.load(cache_file)
    hrrr_snow_sum = cache["hrrr_snow_sum"]
    hrrr_rain_sum = cache["hrrr_rain_sum"]
    hrrr_snow_count = cache["hrrr_snow_count"]
    hrrr_rain_count = cache["hrrr_rain_count"]
    hrrr_lats = cache["hrrr_lats"]
    hrrr_lons = cache["hrrr_lons"]
    print(f"  Loaded. Shape: {hrrr_snow_sum.shape}")
    print(f"  Snow observations total: {hrrr_snow_count.sum():,.0f}")
    print(f"  Rain observations total: {hrrr_rain_count.sum():,.0f}")

    # Compute means (avoid division by zero)
    with np.errstate(invalid="ignore", divide="ignore"):
        hrrr_ymon_snow = np.where(hrrr_snow_count > 0, hrrr_snow_sum / hrrr_snow_count, np.nan)
        hrrr_ymon_rain = np.where(hrrr_rain_count > 0, hrrr_rain_sum / hrrr_rain_count, np.nan)

    # Clip to physical bounds (same as ERA5 workflow)
    hrrr_ymon_snow = np.clip(hrrr_ymon_snow, 271.04, 274.4)
    hrrr_ymon_rain = np.clip(hrrr_ymon_rain, 274.65, 276.48)

    print(f"  HRRR mean monthly t2m_snow shape: {hrrr_ymon_snow.shape}")
    print(f"  HRRR mean monthly t2m_rain shape: {hrrr_ymon_rain.shape}")
    print(f"  Snow NaN fraction: {np.isnan(hrrr_ymon_snow).mean():.2%}")
    print(f"  Rain NaN fraction: {np.isnan(hrrr_ymon_rain).mean():.2%}")

    # --- Step H3: Compute HRRR grid-to-HRU weights (point-in-polygon) ---
    hrrr_lats_flat = hrrr_lats.flatten()
    hrrr_lons_flat = hrrr_lons.flatten()

    # Convert HRRR longitudes from 0-360 to -180/180 if needed
    if hrrr_lons_flat.max() > 180:
        hrrr_lons_flat = ((hrrr_lons_flat + 180) % 360) - 180

    # Create GeoDataFrame of HRRR grid points
    hrrr_points = gpd.GeoDataFrame(
        {"grid_id": range(len(hrrr_lats_flat))},
        geometry=gpd.points_from_xy(hrrr_lons_flat, hrrr_lats_flat),
        crs="EPSG:4326",
    )

    # Load HRUs and clip grid points to domain extent
    hru_gdf = gpd.read_file(gpkg_path, layer="nhru")
    hru_4326 = hru_gdf.to_crs(epsg=4326)

    if hru_id_col not in hru_4326.columns:
        raise ValueError(f"Column '{hru_id_col}' not found in GeoPackage nhru layer. "
                         f"Available columns: {hru_4326.columns.tolist()}")

    domain_bounds = hru_4326.total_bounds
    mask = (
        (hrrr_lats_flat >= domain_bounds[1] - 0.1) &
        (hrrr_lats_flat <= domain_bounds[3] + 0.1) &
        (hrrr_lons_flat >= domain_bounds[0] - 0.1) &
        (hrrr_lons_flat <= domain_bounds[2] + 0.1)
    )
    hrrr_points_clipped = hrrr_points[mask].copy()
    print(f"  HRRR grid points in domain: {len(hrrr_points_clipped)} of {len(hrrr_points)}")

    # Spatial join: assign each HRRR point to an HRU
    hrrr_weights = gpd.sjoin(
        hrrr_points_clipped,
        hru_4326[[hru_id_col, "geometry"]],
        how="inner",
        predicate="within",
    ).drop(columns=["index_right"])

    print(f"  HRRR points matched to HRUs: {len(hrrr_weights)}")
    print(f"  HRUs with HRRR data: {hrrr_weights[hru_id_col].nunique()}")

    # For HRUs with no grid points inside, assign the nearest HRRR grid point
    matched_hru_ids = set(hrrr_weights[hru_id_col])
    all_hru_ids = set(hru_4326[hru_id_col])
    unmatched_hru_ids = all_hru_ids - matched_hru_ids
    print(f"  HRUs without grid points: {len(unmatched_hru_ids)} — assigning nearest neighbor")

    if unmatched_hru_ids:
        unmatched_hrus = hru_4326[hru_4326[hru_id_col].isin(unmatched_hru_ids)].copy()
        # Reproject to EPSG:5070 for accurate centroid and distance calculations
        unmatched_hrus_proj = unmatched_hrus.to_crs(epsg=5070)
        unmatched_hrus_proj["geometry"] = unmatched_hrus_proj.geometry.centroid

        hrrr_points_proj = hrrr_points_clipped.to_crs(epsg=5070)

        nn_result = gpd.sjoin_nearest(
            unmatched_hrus_proj[[hru_id_col, "geometry"]],
            hrrr_points_proj[["grid_id", "geometry"]],
            how="left",
        ).drop(columns=["index_right", "geometry"])

        nn_result["weight"] = 1.0
        hrrr_weights = pd.concat([
            hrrr_weights,
            nn_result[["grid_id", hru_id_col, "weight"]],
        ], ignore_index=True)

        print(f"  After nearest-neighbor fill: {hrrr_weights[hru_id_col].nunique()} HRUs covered")

    # Count points per HRU (for equal-weight averaging)
    hrrr_weights["weight"] = 1.0
    pts_per_hru = hrrr_weights.groupby(hru_id_col)["weight"].transform("sum")
    hrrr_weights["weight"] = 1.0 / pts_per_hru

    # Keep only the columns needed downstream
    hrrr_weights = hrrr_weights[["grid_id", hru_id_col, "weight"]].reset_index(drop=True)

    return hrrr_ymon_snow, hrrr_ymon_rain, hrrr_weights
