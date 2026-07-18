"""
Rebuild HRRR processed cache from local Herbie files for a specific date range.
Run from terminal: python scripts/rebuild_hrrr_cache.py

This reads ONLY from Herbie's local cache (no network needed).
Produces a fresh hrrr_processed_cache.npz for the specified period.
"""

import numpy as np
import calendar
from datetime import datetime
from pathlib import Path
from herbie import Herbie

# === CONFIGURATION ===
rebuild_start = "2014-10-01"
rebuild_end = "2025-09-30"
output_cache = Path(r"D:\ERA5_data\hrrr_processed_cache.npz")

# Parse dates
start_dt = datetime.strptime(rebuild_start, "%Y-%m-%d")
end_dt = datetime.strptime(rebuild_end, "%Y-%m-%d")

print(f"Rebuilding HRRR cache: {rebuild_start} to {rebuild_end}")
print(f"Output: {output_cache}")
print("=" * 60)

# Initialize fresh arrays
hrrr_lats = None
hrrr_lons = None
hrrr_snow_sum = None
hrrr_rain_sum = None
hrrr_snow_count = None
hrrr_rain_count = None

total_processed = 0
total_failed = 0

for year in range(start_dt.year, end_dt.year + 1):
    for month in range(1, 13):
        # Skip months outside the specified range
        month_start = datetime(year, month, 1)
        month_end_day = calendar.monthrange(year, month)[1]
        month_end = datetime(year, month, month_end_day)

        if month_end < start_dt or month_start > end_dt:
            continue

        days_in_month = calendar.monthrange(year, month)[1]
        month_snow_count = 0
        month_rain_count = 0
        month_failed = 0

        for day in range(1, days_in_month + 1):
            # Skip days outside the range
            current_date = datetime(year, month, day)
            if current_date < start_dt or current_date > end_dt:
                continue

            for hour in range(24):
                try:
                    date = datetime(year, month, day, hour)
                    H = Herbie(date, model="hrrr", product="sfc", fxx=1)

                    # This will read from local cache only (fails if not cached)
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

        # Checkpoint after each month
        if hrrr_snow_sum is not None:
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
print(f"DONE. Processed: {total_processed:,}, Failed: {total_failed:,}")
print(f"Date range: {rebuild_start} to {rebuild_end}")
print(f"Cache saved to: {output_cache}")
