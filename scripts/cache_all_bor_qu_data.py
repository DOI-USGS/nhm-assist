"""Cache ALL BOR Hydromet QU daily data (1980–present) for PNW stations.

Reads hydromet_all_stations.csv, filters to stations with qu_days > 0,
and pulls the full QU record from 1980-01-01 to today. Saves one CSV
per station plus a combined parquet file.

Designed to run on Hovenweep DTN (has internet access) or any machine
OFF VPN.

Usage (local):
    pixi run python scripts/cache_all_bor_qu_data.py

Usage (Hovenweep):
    python cache_all_bor_qu_data.py --output-dir /path/to/storage

Output:
    <output_dir>/bor_qu_cache/
        ├── individual/          (one CSV per station)
        │   ├── AFCI.csv
        │   ├── AGA.csv
        │   └── ...
        ├── bor_qu_all_stations_1980_present.parquet
        └── cache_log.csv        (retrieval status per station)
"""

import argparse
import os
import time
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import requests


def parse_args():
    parser = argparse.ArgumentParser(description="Cache all BOR Hydromet QU data")
    parser.add_argument(
        "--stations-csv",
        type=str,
        default="data_dependencies/hydromet_all_stations.csv",
        help="Path to hydromet_all_stations.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data_dependencies/bor_qu_cache",
        help="Output directory for cached data",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1980,
        help="Start year for data retrieval",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=date.today().year,
        help="End year for data retrieval (default: current year)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between requests in seconds",
    )
    return parser.parse_args()


def fetch_qu_data(station, start_year, end_year):
    """Fetch QU daily data for a single station."""
    url = (
        f"https://www.usbr.gov/pn-bin/daily"
        f"?station={station}&format=csv"
        f"&year={start_year}&month=1&day=1"
        f"&year={end_year}&month=12&day=31"
        f"&pcode=qu"
    )
    resp = requests.get(url, timeout=120)
    if not resp.ok:
        return None, f"HTTP {resp.status_code}"

    lines = [
        l
        for l in resp.text.strip().split("\n")
        if l.strip() and not l.startswith("#") and not l.startswith("BEGIN")
    ]
    if len(lines) <= 1:
        return None, "No data lines"

    # Format is: DateTime,STATION_QU (2 columns: date, value)
    df = pd.read_csv(StringIO("\n".join(lines)))

    if df.shape[1] < 2:
        return None, f"Only {df.shape[1]} columns"

    # Rename columns regardless of header names
    df.columns = ["date", "qu_cfs"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["qu_cfs"] = pd.to_numeric(df["qu_cfs"], errors="coerce")
    df = df.dropna(subset=["date", "qu_cfs"])
    df["station"] = station

    if df.empty:
        return None, "All values NaN"

    return df[["station", "date", "qu_cfs"]], "OK"


def main():
    args = parse_args()

    # Read station list
    stations_df = pd.read_csv(args.stations_csv)
    qu_stations = stations_df[stations_df["qu_days"] > 0]["cbtt"].tolist()
    print(f"Stations with QU data: {len(qu_stations)}")
    print(f"Period: {args.start_year}-01-01 to {args.end_year}-12-31")

    # Setup output dirs
    output_dir = Path(args.output_dir)
    individual_dir = output_dir / "individual"
    individual_dir.mkdir(parents=True, exist_ok=True)

    # Track results
    log = []
    all_data = []

    for i, station in enumerate(qu_stations, 1):
        print(f"[{i}/{len(qu_stations)}] {station}...", end=" ", flush=True)

        # Skip if already cached
        station_file = individual_dir / f"{station}.csv"
        if station_file.exists():
            existing = pd.read_csv(station_file, parse_dates=["date"])
            all_data.append(existing)
            log.append({"station": station, "status": "cached", "records": len(existing)})
            print(f"cached ({len(existing)} records)")
            continue

        try:
            df, status = fetch_qu_data(station, args.start_year, args.end_year)
            if df is not None:
                df.to_csv(station_file, index=False)
                all_data.append(df)
                log.append({"station": station, "status": status, "records": len(df)})
                print(f"{len(df)} records")
            else:
                log.append({"station": station, "status": status, "records": 0})
                print(f"SKIP: {status}")
        except Exception as e:
            log.append({"station": station, "status": str(e), "records": 0})
            print(f"ERROR: {e}")

        time.sleep(args.delay)

    # Combine and save
    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        parquet_path = output_dir / "bor_qu_all_stations_1980_present.parquet"
        combined.to_parquet(parquet_path, index=False)
        print(f"\nCombined: {len(combined)} total records across {combined['station'].nunique()} stations")
        print(f"Saved: {parquet_path}")
    else:
        print("\nNo data retrieved.")

    # Save log
    log_df = pd.DataFrame(log)
    log_path = output_dir / "cache_log.csv"
    log_df.to_csv(log_path, index=False)
    print(f"Log: {log_path}")
    print(f"\nSummary:")
    print(f"  OK: {(log_df.status == 'OK').sum()}")
    print(f"  Cached: {(log_df.status == 'cached').sum()}")
    print(f"  Failed: {(~log_df.status.isin(['OK', 'cached'])).sum()}")


if __name__ == "__main__":
    main()
