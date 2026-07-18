"""
HRRR download and processing script.
Run from terminal: python scripts/run_hrrr_download_s3.py

Uses Herbie for reliable GRIB parsing with parallel day processing.
Processes one day at a time (24 hours sequentially) to limit memory.
"""

import numpy as np
import calendar
from datetime import datetime
from pathlib import Path
from herbie import Herbie

# === CONFIGURATION ===
hrrr_start_year = 2014
hrrr_end_year = 2026
output_cache = Path(r"D:\ERA5_data\hrrr_processed_cache.npz")

print(f"HRRR Processing: {hrrr_start_year}-09 to {hrrr_end_year}-06")
print(f"Output: {output_cache}")
print("=" * 60)

# Initialize or load existing cache
hrrr_lats = None
hrrr_lons = None
hrrr_snow_sum = None
hrrr_rain_sum = None
hrrr_snow_count = None
hrrr_rain_count = None

# Track which year-months are complete
completed_months_file = output_cache.parent / "hrrr_completed_months.txt"
completed_months = set()

if completed_months_file.exists():
    completed_months = set(completed_months_file.read_text().strip().split("\n"))
    print(f"Previously completed months: {len(completed_months)}")

if output_cache.exists():
    print(f"Loading existing cache...")
    cache = np.load(output_cache)
    hrrr_snow_sum = cache["hrrr_snow_sum"]
    hrrr_rain_sum = cache["hrrr_rain_sum"]
    hrrr_snow_count = cache["hrrr_snow_count"]
    hrrr_rain_count = cache["hrrr_rain_count"]
    hrrr_lats = cache["hrrr_lats"]
    hrrr_lons = cache["hrrr_lons"]
    print(f"  Loaded. Shape: {hrrr_snow_sum.shape}")

total_processed = 0
total_failed = 0

for year in range(hrrr_start_year, hrrr_end_year + 1):
    for month in range(1, 13):
        if year == 2014 and month < 9:
            continue
        if year == 2026 and month > 6:
            continue

        month_key = f"{year}-{month:02d}"
        if month_key in completed_months:
            print(f"  {month_key}: already complete, skipping")
            continue

        days_in_month = calendar.monthrange(year, month)[1]
        month_snow_count = 0
        month_rain_count = 0
        month_failed = 0

        for day in range(1, days_in_month + 1):
            for hour in range(24):
                try:
                    date = datetime(year, month, day, hour)
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
                    total_processed += 1

                    del ds_tmp, ds_csnow, ds_crain, t2m, csnow, crain

                except Exception:
                    month_failed += 1
                    total_failed += 1

            # Print progress per day
            if day % 5 == 0:
                print(f"    {month_key}-{day:02d} done ({day}/{days_in_month})")

        print(f"  {month_key}: snow={month_snow_count:,}, rain={month_rain_count:,}, failed={month_failed}")

        # Checkpoint
        np.savez(
            output_cache,
            hrrr_snow_sum=hrrr_snow_sum,
            hrrr_rain_sum=hrrr_rain_sum,
            hrrr_snow_count=hrrr_snow_count,
            hrrr_rain_count=hrrr_rain_count,
            hrrr_lats=hrrr_lats,
            hrrr_lons=hrrr_lons,
        )

        # Mark month as complete
        completed_months.add(month_key)
        completed_months_file.write_text("\n".join(sorted(completed_months)))

print(f"\n{'=' * 60}")
print(f"DONE. Processed: {total_processed:,}, Failed: {total_failed:,}")
print(f"Cache: {output_cache}")
