"""
Standalone HRRR data download and processing script using FastHerbie.
Run from terminal: python scripts/run_hrrr_download.py

Uses FastHerbie for parallel downloads, then processes sequentially.
"""

import numpy as np
import pandas as pd
import calendar
from datetime import datetime
from pathlib import Path
from herbie import FastHerbie

# === CONFIGURATION ===
hrrr_start_year = 2014
hrrr_end_year = 2026
output_cache = Path(r"D:\ERA5_data\hrrr_processed_cache.npz")

# Search string to download all 3 variables in one subset
search_str = ":TMP:2 m above ground|:CSNOW:surface|:CRAIN:surface"

print(f"HRRR Processing: {hrrr_start_year}-09 to {hrrr_end_year}-06")
print(f"Output: {output_cache}")
print(f"Using FastHerbie for parallel downloads")
print("=" * 60)

# Initialize or load existing cache
hrrr_lats = None
hrrr_lons = None
hrrr_snow_sum = None
hrrr_rain_sum = None
hrrr_snow_count = None
hrrr_rain_count = None

if output_cache.exists():
    print(f"Loading existing cache to resume...")
    cache = np.load(output_cache)
    hrrr_snow_sum = cache["hrrr_snow_sum"]
    hrrr_rain_sum = cache["hrrr_rain_sum"]
    hrrr_snow_count = cache["hrrr_snow_count"]
    hrrr_rain_count = cache["hrrr_rain_count"]
    hrrr_lats = cache["hrrr_lats"]
    hrrr_lons = cache["hrrr_lons"]
    print(f"  Cache loaded. Shape: {hrrr_snow_sum.shape}")

total_processed = 0
total_failed = 0

for year in range(hrrr_start_year, hrrr_end_year + 1):
    for month in range(1, 13):
        # Skip months outside the data range
        if year == 2014 and month < 9:
            continue
        if year == 2026 and month > 6:
            continue

        days_in_month = calendar.monthrange(year, month)[1]
        month_snow_count = 0
        month_rain_count = 0
        month_failed = 0

        # Create date range for the entire month (hourly)
        start = f"{year}-{month:02d}-01"
        end = f"{year}-{month:02d}-{days_in_month}"
        dates = pd.date_range(start, end, freq="1h")

        print(f"\n  {year}-{month:02d}: Downloading {len(dates)} timesteps...")

        try:
            # FastHerbie downloads in parallel
            FH = FastHerbie(dates, model="hrrr", product="sfc", fxx=1)
            FH.download(search_str, verbose=False)
            print(f"  {year}-{month:02d}: Downloads complete. Processing...")
        except Exception as e:
            print(f"  {year}-{month:02d}: FastHerbie download error: {e}")
            # Fall through to process whatever was cached

        # Process each timestep from local cache
        for date in dates:
            try:
                from herbie import Herbie
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

                # Initialize on first read
                if hrrr_lats is None:
                    hrrr_lats = ds_tmp["latitude"].values
                    hrrr_lons = ds_tmp["longitude"].values
                    ny, nx = hrrr_lats.shape
                    hrrr_snow_sum = np.zeros((12, ny, nx))
                    hrrr_rain_sum = np.zeros((12, ny, nx))
                    hrrr_snow_count = np.zeros((12, ny, nx))
                    hrrr_rain_count = np.zeros((12, ny, nx))

                # Accumulate where snow
                snow_mask = csnow == 1
                hrrr_snow_sum[month - 1][snow_mask] += t2m[snow_mask]
                hrrr_snow_count[month - 1][snow_mask] += 1

                # Accumulate where rain
                rain_mask = crain == 1
                hrrr_rain_sum[month - 1][rain_mask] += t2m[rain_mask]
                hrrr_rain_count[month - 1][rain_mask] += 1

                month_snow_count += snow_mask.sum()
                month_rain_count += rain_mask.sum()
                total_processed += 1

                del ds_tmp, ds_csnow, ds_crain, t2m, csnow, crain

            except Exception:
                month_failed += 1
                total_failed += 1

        print(f"  {year}-{month:02d}: snow={month_snow_count:,}, rain={month_rain_count:,}, failed={month_failed}")

        # Save checkpoint after each month
        np.savez(
            output_cache,
            hrrr_snow_sum=hrrr_snow_sum,
            hrrr_rain_sum=hrrr_rain_sum,
            hrrr_snow_count=hrrr_snow_count,
            hrrr_rain_count=hrrr_rain_count,
            hrrr_lats=hrrr_lats,
            hrrr_lons=hrrr_lons,
        )

print(f"\n{'=' * 60}")
print(f"DONE. Processed: {total_processed:,} timesteps, Failed: {total_failed:,}")
print(f"Cache saved to: {output_cache}")
