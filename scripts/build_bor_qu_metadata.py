"""Build the BOR Hydromet QU station metadata catalog (one-time provenance pipeline).

This script consolidates the multi-step, one-time process used to build the
master BOR Hydromet "Estimated Average Unregulated Flow" (QU) station list and
its metadata (coordinates, elevation, QU availability, USGS crosswalk, and
nearest NHM resource gage). It is a *data-cataloguing* record, not part of the
runtime nhf_assist workflow — it documents how the metadata files were produced
so the process is reproducible.

See `scripts/README_bor_qu_pipeline.md` for the narrative description of each
step, data sources, and access requirements.

Pipeline steps (run in order):
    1. parse_hydromet_html      — HTML station report -> stations CSV (coords, elev)
    2. discover_qu_stations     — station.js + Hydromet daily endpoint -> QU stations
    3. crosswalk_coords_rise    — RISE FeatureServer -> lat/lon for QU stations
    4. crosswalk_usgs           — USGS WaterData -> lat/lon + USGS site IDs
    5. find_nearest_poi         — spatial join to resource_gages -> nearest_poi_id

IMPORTANT ACCESS NOTES:
    - Steps 1-3 require being OFF VPN (usbr.gov / RISE blocked by DOI proxy).
    - Step 4 (USGS WaterData) generally requires being ON VPN.
    - This is why the pipeline is run manually, step by step, rather than as a
      single automated job.

Usage:
    # Run an individual step (recommended, given VPN toggling):
    pixi run python scripts/build_bor_qu_metadata.py --step parse_hydromet_html
    pixi run python scripts/build_bor_qu_metadata.py --step discover_qu_stations
    pixi run python scripts/build_bor_qu_metadata.py --step crosswalk_coords_rise
    pixi run python scripts/build_bor_qu_metadata.py --step crosswalk_usgs
    pixi run python scripts/build_bor_qu_metadata.py --step find_nearest_poi

    # List available steps:
    pixi run python scripts/build_bor_qu_metadata.py --list
"""

from __future__ import annotations

import argparse
import re
import time
from io import StringIO

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Paths (edit these to match your workspace / OHM hydrofabric snapshot)
# ---------------------------------------------------------------------------
DATA_DEPS = "data_dependencies"
NPOIGAGES_DIR = (
    "nhf_assist/hydrofabric_domain_data/OHM_2026_02_21/npoigages_data"
)

INPUT_HTML = (
    f"{DATA_DEPS}/Hydromet Pacific Northwest Region _ Bureau of Reclamation.html"
)
STATIONS_CSV = f"{DATA_DEPS}/hydromet_all_stations.csv"
RISE_REFERENCE_CSV = f"{DATA_DEPS}/rise_cpnw_stations.csv"

BOR_QU_GAGES_CSV = f"{NPOIGAGES_DIR}/BOR_QU_gages.csv"
BOR_QU_REVIEW_CSV = f"{NPOIGAGES_DIR}/BOR_QU_gages_crosswalk_review.csv"
BOR_QU_USGS_CSV = f"{NPOIGAGES_DIR}/BOR_QU_gages_usgs_crosswalk.csv"
RESOURCE_GAGES_CSV = f"{NPOIGAGES_DIR}/resource_gages.csv"

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
STATION_JS_URL = "https://www.usbr.gov/pn/hydromet/station.js"
HYDROMET_DAILY_URL = "https://www.usbr.gov/pn-bin/daily"
RISE_FEATURESERVER_URL = (
    "https://services1.arcgis.com/ixD30sld6F8MQ7V5/arcgis/rest/services/"
    "RISE_point_locations_(view)/FeatureServer/0/query"
)


# ===========================================================================
# Step 1 — Parse Hydromet HTML station report
# ===========================================================================
def _dms_to_dd(dms_str: str) -> float:
    """Convert 'DD-MM-SS' to decimal degrees."""
    d, m, s = (float(p) for p in dms_str.split("-"))
    return round(d + m / 60 + s / 3600, 6)


def parse_hydromet_html() -> pd.DataFrame:
    """Parse the Hydromet station report HTML into a stations CSV.

    Source: https://www.usbr.gov/pn/hydromet/decod_params.html (saved locally).
    Extracts CBTT code, name, lat/lon (DMS -> decimal degrees), and elevation.
    """
    with open(INPUT_HTML, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    station_pattern = re.compile(r"^\s{2}(\w{2,8})\s{2,}(.+?)\s*$", re.MULTILINE)
    latlon_pattern = re.compile(
        r"LAT=(\d+-\d+-\d+)\s+LONG=(\d+-\d+-\d+)\s+ELEV=\s*([\d.]+)"
    )

    stations = []
    current_cbtt = current_name = None

    for line in text.split("\n"):
        sm = station_pattern.match(line)
        if sm and not re.match(r"^\s{5,}", line):
            current_cbtt = sm.group(1)
            current_name = sm.group(2).strip()

        lm = latlon_pattern.search(line)
        if lm and current_cbtt:
            stations.append(
                {
                    "cbtt": current_cbtt,
                    "name": current_name,
                    "latitude": _dms_to_dd(lm.group(1)),
                    "longitude": -_dms_to_dd(lm.group(2)),  # West = negative
                    "elevation_ft": float(lm.group(3)),
                }
            )
            current_cbtt = current_name = None

    df = pd.DataFrame(stations)
    df.to_csv(STATIONS_CSV, index=False)
    print(f"[parse_hydromet_html] Parsed {len(df)} stations -> {STATIONS_CSV}")
    return df


# ===========================================================================
# Step 2 — Discover stations with QU data
# ===========================================================================
def _check_qu_days(station_code: str, start_year=1980, end_year=2024) -> int:
    """Return the number of days with valid QU data for a station, else 0."""
    url = (
        f"{HYDROMET_DAILY_URL}?station={station_code}&format=csv"
        f"&year={start_year}&month=1&day=1"
        f"&year={end_year}&month=12&day=31&pcode=qu"
    )
    try:
        resp = requests.get(url, timeout=30)
        if resp.ok and "DateTime" in resp.text:
            df = pd.read_csv(StringIO(resp.text))
            if df.shape[1] >= 2:
                return int(pd.to_numeric(df.iloc[:, 1], errors="coerce").notna().sum())
    except Exception:
        pass
    return 0


def discover_qu_stations() -> pd.DataFrame:
    """Discover all Hydromet stations that have QU (unregulated flow) data.

    Pulls the full station dropdown from station.js, then checks each station's
    QU availability on the legacy Hydromet daily endpoint. Run OFF VPN.
    """
    resp = requests.get(STATION_JS_URL, timeout=30)
    resp.raise_for_status()

    options = re.findall(r'value="([^"]+)"[^>]*>([^<]+)</option>', resp.text)
    print(f"[discover_qu_stations] Found {len(options)} Hydromet stations")

    stations = [
        {
            "poi_gage_id": code,
            "poi_name": (label.split(" - ", 1)[1] if " - " in label else label).strip(),
        }
        for code, label in options
    ]

    qu_stations = []
    for i, s in enumerate(stations):
        n_days = _check_qu_days(s["poi_gage_id"])
        if n_days > 0:
            s.update(
                qu_days=n_days,
                poi_agency="BOR-QU",
                drainage_area=None,
                drainage_area_contrib=None,
                latitude=None,
                longitude=None,
            )
            qu_stations.append(s)
            print(f"  QU {s['poi_gage_id']:8s} | {n_days:5d} days | {s['poi_name'][:50]}")
        if (i + 1) % 50 == 0:
            print(f"  ... checked {i + 1}/{len(stations)}")
        time.sleep(0.5)

    cols = [
        "poi_gage_id", "poi_agency", "poi_name",
        "latitude", "longitude",
        "drainage_area", "drainage_area_contrib", "qu_days",
    ]
    df = pd.DataFrame(qu_stations)[cols].sort_values("poi_gage_id").reset_index(drop=True)
    df.to_csv(BOR_QU_GAGES_CSV, index=False)
    print(f"[discover_qu_stations] {len(df)} QU stations -> {BOR_QU_GAGES_CSV}")
    return df


# ===========================================================================
# Step 3 — Crosswalk coordinates via RISE FeatureServer
# ===========================================================================
def _extract_cbtt(loc_name: str) -> str | None:
    """Extract a CBTT code from trailing parentheses in a location name."""
    match = re.search(r"\(([^)]+)\)$", str(loc_name).strip())
    return match.group(1) if match else None


def crosswalk_coords_rise() -> pd.DataFrame:
    """Populate lat/lon for QU stations from the RISE ArcGIS FeatureServer.

    Matches on CBTT code (exact, then 3-char fuzzy). Writes a review file and a
    coords file rather than overwriting the input. Run OFF VPN.
    """
    bor_df = pd.read_csv(BOR_QU_GAGES_CSV)
    print(f"[crosswalk_coords_rise] BOR QU stations: {len(bor_df)}")

    resp = requests.get(
        RISE_FEATURESERVER_URL,
        params={
            "where": "unifiedReg = 'Columbia-Pacific Northwest'",
            "outFields": "locName,lat,long,type",
            "f": "json",
            "resultRecordCount": 5000,
        },
        timeout=60,
    )
    resp.raise_for_status()
    features = resp.json().get("features", [])

    rise_records = []
    for feat in features:
        attrs = feat["attributes"]
        cbtt = _extract_cbtt(attrs.get("locName", ""))
        if cbtt:
            rise_records.append(
                {
                    "rise_code": cbtt.upper(),
                    "rise_name": attrs.get("locName", ""),
                    "lat": attrs.get("lat"),
                    "lon": attrs.get("long"),
                }
            )
    rise_df = pd.DataFrame(rise_records)
    rise_df.to_csv(RISE_REFERENCE_CSV, index=False)
    print(f"  RISE locations with codes: {len(rise_df)} -> {RISE_REFERENCE_CSV}")

    bor_df["code_upper"] = bor_df["poi_gage_id"].str.upper()
    rise_df["code_upper"] = rise_df["rise_code"].str.upper()

    matched = bor_df.merge(
        rise_df[["code_upper", "lat", "lon", "rise_name"]].drop_duplicates("code_upper"),
        on="code_upper",
        how="left",
    )
    has_coords = matched["lat"].notna()
    matched.loc[has_coords, "latitude"] = matched.loc[has_coords, "lat"]
    matched.loc[has_coords, "longitude"] = matched.loc[has_coords, "lon"]
    print(f"  Exact code matches: {int(has_coords.sum())}/{len(bor_df)}")

    review = matched[
        ["poi_gage_id", "poi_name", "rise_name", "latitude", "longitude", "qu_days"]
    ]
    review.to_csv(BOR_QU_REVIEW_CSV, index=False)
    print(f"[crosswalk_coords_rise] Review file -> {BOR_QU_REVIEW_CSV}")
    return matched


# ===========================================================================
# Step 4 — Crosswalk with USGS WaterData
# ===========================================================================
def _extract_state(name: str) -> str | None:
    """Extract a full state name from a trailing ', OR' / ' WA' style suffix."""
    state_map = {
        "OR": "Oregon", "WA": "Washington", "ID": "Idaho",
        "MT": "Montana", "WY": "Wyoming", "CA": "California",
    }
    for abbr, full in state_map.items():
        if f", {abbr}" in name or name.strip().endswith(f" {abbr}"):
            return full
    return None


def crosswalk_usgs() -> pd.DataFrame:
    """Fill lat/lon and USGS site IDs by matching QU station names to USGS.

    Uses dataretrieval.waterdata monitoring-location name search. This step
    generally requires being ON VPN for USGS WaterData API access.
    """
    from dataretrieval import waterdata

    def search(name, state):
        try:
            params = {"monitoring_location_name": name}
            if state:
                params["state_name"] = state
            loc_df, _ = waterdata.get_monitoring_locations(**params)
            if not loc_df.empty:
                row = loc_df.iloc[0]
                return {
                    "usgs_id": row.get("monitoring_location_id", "").replace("USGS-", ""),
                    "usgs_name": row.get("monitoring_location_name"),
                    "usgs_lat": row.get("latitude"),
                    "usgs_lon": row.get("longitude"),
                }
        except Exception:
            pass
        return None

    df = pd.read_csv(BOR_QU_REVIEW_CSV)
    for col in ("usgs_id", "usgs_name", "usgs_lat", "usgs_lon"):
        df[col] = None

    for idx, row in df.iterrows():
        name = row["poi_name"]
        state = _extract_state(name)
        result = search(name, state)
        if not result and "," in name:
            result = search(name.split(",")[0].strip(), state)
        if result:
            df.loc[idx, ["usgs_id", "usgs_name", "usgs_lat", "usgs_lon"]] = [
                result["usgs_id"], result["usgs_name"],
                result["usgs_lat"], result["usgs_lon"],
            ]
            print(f"  USGS {row['poi_gage_id']:8s} -> {result['usgs_id']} {str(result['usgs_name'])[:40]}")
        else:
            print(f"  ---- {row['poi_gage_id']:8s} | no USGS match: {name[:40]}")
        time.sleep(0.5)

    df.to_csv(BOR_QU_USGS_CSV, index=False)
    print(f"[crosswalk_usgs] {int(df['usgs_id'].notna().sum())}/{len(df)} matched -> {BOR_QU_USGS_CSV}")
    return df


# ===========================================================================
# Step 5 — Nearest NHM resource gage (spatial join)
# ===========================================================================
def find_nearest_poi() -> pd.DataFrame:
    """Attach the nearest NHM resource gage (poi_gage_id) + distance to each BOR station.

    Both datasets are projected to EPSG:5070 (CONUS Albers) before a nearest
    spatial join. Distance reported in meters.
    """
    import geopandas as gpd

    bor_df = pd.read_csv(BOR_QU_REVIEW_CSV)
    poi_df = pd.read_csv(RESOURCE_GAGES_CSV)
    print(f"[find_nearest_poi] BOR: {len(bor_df)}  resource_gages: {len(poi_df)}")

    id_col = "bor_id" if "bor_id" in bor_df.columns else "poi_gage_id"

    bor_gdf = gpd.GeoDataFrame(
        bor_df,
        geometry=gpd.points_from_xy(bor_df["longitude"], bor_df["latitude"]),
        crs="EPSG:4326",
    ).to_crs("EPSG:5070")
    poi_gdf = gpd.GeoDataFrame(
        poi_df,
        geometry=gpd.points_from_xy(poi_df["longitude"], poi_df["latitude"]),
        crs="EPSG:4326",
    ).to_crs("EPSG:5070")

    joined = gpd.sjoin_nearest(
        bor_gdf[[id_col, "geometry"]],
        poi_gdf[["poi_gage_id", "geometry"]],
        how="left",
        distance_col="dist_m",
    )
    bor_df["nearest_poi_id"] = joined["poi_gage_id"].values
    bor_df["dist_m"] = joined["dist_m"].round(1).values

    bor_df.to_csv(BOR_QU_REVIEW_CSV, index=False)
    print(f"[find_nearest_poi] Wrote nearest_poi_id + dist_m -> {BOR_QU_REVIEW_CSV}")
    return bor_df


# ===========================================================================
# CLI
# ===========================================================================
STEPS = {
    "parse_hydromet_html": parse_hydromet_html,
    "discover_qu_stations": discover_qu_stations,
    "crosswalk_coords_rise": crosswalk_coords_rise,
    "crosswalk_usgs": crosswalk_usgs,
    "find_nearest_poi": find_nearest_poi,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", choices=list(STEPS), help="Run a single pipeline step.")
    parser.add_argument("--list", action="store_true", help="List available steps in order.")
    args = parser.parse_args()

    if args.list or not args.step:
        print("BOR QU metadata pipeline steps (run in order):")
        for i, name in enumerate(STEPS, 1):
            note = ""
            if name in ("parse_hydromet_html", "discover_qu_stations", "crosswalk_coords_rise"):
                note = "  (OFF VPN)"
            elif name == "crosswalk_usgs":
                note = "  (ON VPN)"
            print(f"  {i}. {name}{note}")
        print("\nRun one with:  --step <name>")
        return

    STEPS[args.step]()


if __name__ == "__main__":
    main()
