"""Verify whether the GridMET temperature forcing for the Sandy River NHM /
pywatershed model carries a WARM BIAS that is tied to ELEVATION, by comparing
the model forcing against independent SNOTEL/SCAN and GHCN-Daily station
temperature observations.

This is a READ-ONLY diagnostic. It never writes to the model run directory or
any source data; it only reads them and writes new artifacts (a Plotly HTML, a
per-station summary CSV, and cached raw station pulls) under ``--out-dir``.

For every discovered station the script builds TWO collocation series so the
warm bias can be attributed to the right layer:

* **MODEL HRU value** -- the model driver column (``tmax.nc`` / ``tmin.nc``) of
  the HRU polygon that CONTAINS the station (point-in-polygon on the ``nhru``
  layer, reprojected to EPSG:4326; fallback nearest ``hru_lat``/``hru_lon``).
  Driver column index == ``hru_id - 1`` (positional alignment, asserted at
  runtime). This is what the model actually "sees".
* **RAW GridMET cell** -- the actual GridMET daily cell series at the station
  lon/lat by nearest-cell lookup from the GridMET THREDDS OPeNDAP endpoint
  (Kelvin -> degF). This isolates whether the warm bias is already in the
  GridMET source grid vs. introduced by cell->HRU area-averaging. If the
  THREDDS pull fails (offline / VPN SSL inspection), it degrades to a
  "raw-approx (HRU driver)" series taken from the containing HRU's driver
  column, clearly labelled as such.

Bias = (MODEL - OBSERVED), computed daily over Water Years 2010-2021
(2009-10-01 .. 2021-09-30), then reduced to a winter (DJFM) mean per station.
Winter-mean bias is regressed against station elevation (metres) to test the
elevation tie, and three lapse rates are compared: the model's effective lapse
(winter tmax across all HRUs vs hru_elev), the observed station lapse, and the
nominal winter environmental lapse.

Every network pull is wrapped in try/except with a timeout and cached to
``--out-dir/stations_raw/`` so reruns work offline. A run that retrieves ZERO
stations is reported as a blockage, not a success.

Usage (in the pixi env, from the repo root ``d:\\nhm-assist``)::

    pixi run python scripts/verify_gridmet_temp_bias.py

    # offline / degraded rerun (cache only, no network):
    pixi run python scripts/verify_gridmet_temp_bias.py --offline
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib as pl

import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    import requests
except Exception:  # noqa: BLE001 - requests should be present; degrade if not
    requests = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AWDB_BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
GHCN_STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
GHCN_INVENTORY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-inventory.txt"
NCEI_ACCESS_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
GHCN_BYSTATION_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station/{sid}.csv.gz"
GRIDMET_TMMX = "http://thredds.northwestknowledge.net:8080/thredds/dodsC/MET/tmmx/tmmx_{yr}.nc"
GRIDMET_TMMN = "http://thredds.northwestknowledge.net:8080/thredds/dodsC/MET/tmmn/tmmn_{yr}.nc"

FT_TO_M = 0.3048
WINTER_MONTHS = (12, 1, 2, 3)
MIN_WINTER_DAYS = 60  # ~2 winters of DJFM data to enter the regression


def k_to_f(k):
    return (np.asarray(k, dtype=float) - 273.15) * 9.0 / 5.0 + 32.0


def tenthsC_to_f(v):
    return (np.asarray(v, dtype=float) / 10.0) * 9.0 / 5.0 + 32.0


# ---------------------------------------------------------------------------
# Simple OLS + Pearson r/p (scipy if present, else numpy/math)
# ---------------------------------------------------------------------------
def regress(x, y):
    """Return dict(slope, intercept, r, p, n) for y ~ x. slope is in y-units per x-unit."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    good = np.isfinite(x) & np.isfinite(y)
    x, y = x[good], y[good]
    n = len(x)
    out = {"slope": np.nan, "intercept": np.nan, "r": np.nan, "p": np.nan, "n": n}
    if n < 3 or np.allclose(x, x[0]):
        return out
    try:
        from scipy import stats
        res = stats.linregress(x, y)
        out.update(slope=res.slope, intercept=res.intercept, r=res.rvalue,
                   p=res.pvalue, n=n)
        return out
    except Exception:  # noqa: BLE001 - fall back to numpy
        slope, intercept = np.polyfit(x, y, 1)
        r = np.corrcoef(x, y)[0, 1]
        # two-sided p from t-distribution; approximate via survival of normal
        # if math.erf is enough, else leave as NaN with a note handled upstream
        try:
            import math
            t = r * math.sqrt((n - 2) / max(1e-12, (1 - r * r)))
            # normal approximation to the t survival (fine for n>=~20)
            p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t) / math.sqrt(2.0))))
        except Exception:  # noqa: BLE001
            p = np.nan
        out.update(slope=slope, intercept=intercept, r=r, p=p, n=n)
        return out


# ---------------------------------------------------------------------------
# Basin footprint + HRU table
# ---------------------------------------------------------------------------
def load_basin_and_hrus(gis_path: pl.Path, run: pl.Path, buffer_km: float):
    """Return (bbox_wgs84, nhru_gdf_wgs84, pj, collocation_method).

    bbox is (lon_min, lat_min, lon_max, lat_max) of the buffered basin.
    nhru_gdf is the nhru layer reprojected to EPSG:4326 with a verified
    positional identity to parameters.json HRU order.
    """
    nhru = gpd.read_file(gis_path, layer="nhru").to_crs(4326)
    try:
        domain = gpd.read_file(gis_path, layer="domain").to_crs(4326)
        basin = domain.union_all() if hasattr(domain, "union_all") else domain.unary_union
    except Exception:  # noqa: BLE001 - dissolve nhru if no domain layer
        basin = nhru.union_all() if hasattr(nhru, "union_all") else nhru.unary_union

    # buffer in a metric CRS (EPSG:5070) then back to 4326
    basin_m = gpd.GeoSeries([basin], crs=4326).to_crs(5070)
    buffered = basin_m.buffer(buffer_km * 1000.0).to_crs(4326)
    lon_min, lat_min, lon_max, lat_max = buffered.total_bounds
    bbox = (float(lon_min), float(lat_min), float(lon_max), float(lat_max))

    pj = json.load(open(run / "parameters.json"))

    # verify positional identity: nhru ordered by hru_id has nhm_id == pj nhm_id
    nhru_sorted = nhru.sort_values("hru_id").reset_index(drop=True)
    hru_ids = nhru_sorted["hru_id"].to_numpy()
    pj_nhm = np.asarray(pj["nhm_id"], dtype=int)
    identity_ok = (
        len(hru_ids) == len(pj_nhm)
        and np.array_equal(hru_ids, np.arange(1, len(hru_ids) + 1))
        and np.array_equal(nhru_sorted["nhm_id"].to_numpy(), pj_nhm)
    )
    collocation_method = "polygon" if identity_ok else "nearest-latlon"
    print(f"  HRU alignment: {collocation_method} "
          f"(identity_ok={identity_ok}, nhru n={len(nhru)}, pj n={len(pj_nhm)})")
    print(f"  basin buffered bbox (lon_min,lat_min,lon_max,lat_max): "
          f"{bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f}")
    return bbox, nhru_sorted, pj, collocation_method


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def _in_bbox(lat, lon, bbox):
    lon_min, lat_min, lon_max, lat_max = bbox
    return (lon_min <= lon <= lon_max) and (lat_min <= lat <= lat_max)


def discover_snotel(bbox, out_dir: pl.Path, timeout: float, offline: bool):
    """SNOTEL + SCAN stations (OR) within bbox. Returns a DataFrame; cached."""
    cache = out_dir / "stations_raw" / "snotel_stations.csv"
    cols = ["station_id", "triplet", "network", "name", "lat", "lon", "elevation_m"]
    if offline or requests is None:
        if cache.exists():
            print("  (SNOTEL/SCAN: using cached station list)")
            return pd.read_csv(cache, dtype={"station_id": str})
        print("  (SNOTEL/SCAN: offline and no cache; skipping)")
        return pd.DataFrame(columns=cols)
    rows = []
    try:
        for net in ("SNTL", "SCAN"):
            r = requests.get(f"{AWDB_BASE}/stations",
                             params={"stationTriplets": f"*:OR:{net}",
                                     "returnStationElements": "false"},
                             timeout=timeout)
            r.raise_for_status()
            for s in r.json():
                lat = s.get("latitude")
                lon = s.get("longitude")
                if lat is None or lon is None or not _in_bbox(lat, lon, bbox):
                    continue
                elev_ft = s.get("elevation")
                rows.append({
                    "station_id": str(s.get("stationId")),
                    "triplet": s.get("stationTriplet"),
                    "network": net.replace("SNTL", "SNOTEL"),
                    "name": s.get("name"),
                    "lat": float(lat), "lon": float(lon),
                    "elevation_m": float(elev_ft) * FT_TO_M if elev_ft is not None else np.nan,
                })
        df = pd.DataFrame(rows, columns=cols)
        df.to_csv(cache, index=False)
        print(f"  SNOTEL/SCAN: {len(df)} station(s) in bbox (cached)")
        return df
    except Exception as exc:  # noqa: BLE001 - degrade to cache
        print(f"  (SNOTEL/SCAN pull failed: {type(exc).__name__}: {str(exc)[:120]})")
        if cache.exists():
            print("   -> using cached SNOTEL/SCAN station list")
            return pd.read_csv(cache, dtype={"station_id": str})
        return pd.DataFrame(columns=cols)


def discover_ghcn(bbox, out_dir: pl.Path, timeout: float, offline: bool,
                  args_wy_start: int, args_wy_end: int):
    """GHCN-Daily stations within bbox from ghcnd-stations.txt (fixed-width).

    Pre-filtered by ghcnd-inventory.txt to stations whose TMAX record overlaps
    the analysis window, so the per-station daily pull is bounded.
    """
    cache = out_dir / "stations_raw" / "ghcn_stations.csv"
    cols = ["station_id", "triplet", "network", "name", "lat", "lon", "elevation_m"]
    if offline or requests is None:
        if cache.exists():
            print("  (GHCN: using cached station list)")
            return pd.read_csv(cache, dtype={"station_id": str})
        print("  (GHCN: offline and no cache; skipping)")
        return pd.DataFrame(columns=cols)
    rows = []
    try:
        # Pre-filter via the inventory to stations whose TMAX record overlaps the
        # analysis window. This keeps the (otherwise ~170) in-bbox GHCN set down
        # to the stations that can actually anchor the regression, and avoids
        # pulling daily series for stations with no winter data in WY2010-2021.
        tmax_ok = set()
        try:
            inv = requests.get(GHCN_INVENTORY_URL, timeout=timeout)
            inv.raise_for_status()
            for line in inv.text.splitlines():
                if len(line) < 45 or line[31:35].strip() != "TMAX":
                    continue
                try:
                    first = int(line[36:40])
                    last = int(line[41:45])
                except ValueError:
                    continue
                # overlap WY window (calendar 2009..2021), require >=3 yrs span in it
                if last >= args_wy_start - 1 and first <= args_wy_end and (last - max(first, args_wy_start - 1)) >= 2:
                    tmax_ok.add(line[0:11].strip())
            print(f"  (GHCN inventory: {len(tmax_ok)} station(s) with usable TMAX span)")
        except Exception as exc:  # noqa: BLE001 - no inventory => keep all in bbox
            print(f"  (GHCN inventory unavailable: {type(exc).__name__}; keeping all in-bbox)")
            tmax_ok = None

        r = requests.get(GHCN_STATIONS_URL, timeout=timeout)
        r.raise_for_status()
        for line in r.text.splitlines():
            if len(line) < 85:
                continue
            sid = line[0:11].strip()
            if tmax_ok is not None and sid not in tmax_ok:
                continue
            try:
                lat = float(line[12:20])
                lon = float(line[21:30])
                elev = float(line[31:37])
            except ValueError:
                continue
            if not _in_bbox(lat, lon, bbox):
                continue
            name = line[41:71].strip()
            rows.append({
                "station_id": sid, "triplet": "", "network": "GHCN",
                "name": name, "lat": lat, "lon": lon,
                "elevation_m": elev if elev > -999 else np.nan,
            })
        df = pd.DataFrame(rows, columns=cols)
        df.to_csv(cache, index=False)
        print(f"  GHCN: {len(df)} station(s) in bbox (cached)")
        return df
    except Exception as exc:  # noqa: BLE001 - degrade to cache
        print(f"  (GHCN pull failed: {type(exc).__name__}: {str(exc)[:120]})")
        if cache.exists():
            print("   -> using cached GHCN station list")
            return pd.read_csv(cache, dtype={"station_id": str})
        return pd.DataFrame(columns=cols)


# ---------------------------------------------------------------------------
# Daily station temperature pulls
# ---------------------------------------------------------------------------
def _cache_path(out_dir: pl.Path, network: str, sid: str) -> pl.Path:
    safe = sid.replace(":", "_").replace("/", "_")
    return out_dir / "stations_raw" / f"{network}_{safe}.csv"


def _load_daily_cache(path: pl.Path):
    if path.exists():
        df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        return df
    return None


def fetch_snotel_daily(triplet, out_dir, start, end, timeout, offline):
    """Daily TMAX/TMIN (degF) for a SNOTEL/SCAN triplet. Cached per station."""
    sid = triplet
    cache = _cache_path(out_dir, "SNOTEL", sid)
    if offline or requests is None:
        return _load_daily_cache(cache)
    try:
        r = requests.get(f"{AWDB_BASE}/data",
                         params={"stationTriplets": triplet,
                                 "elements": "TMAX,TMIN",
                                 "duration": "DAILY",
                                 "beginDate": start, "endDate": end},
                         timeout=timeout)
        r.raise_for_status()
        payload = r.json()
        series = {}
        for st in payload:
            for sde in st.get("data", []):
                code = sde.get("stationElement", {}).get("elementCode")
                if code not in ("TMAX", "TMIN"):
                    continue
                vals = {v["date"]: v.get("value") for v in sde.get("values", [])}
                series[code] = vals
        if not series:
            cached = _load_daily_cache(cache)
            if cached is not None:
                return cached
            return None
        idx = sorted(set().union(*[set(d) for d in series.values()]))
        df = pd.DataFrame(index=pd.to_datetime(idx))
        df.index.name = "date"
        for code, col in (("TMAX", "tmax_obs"), ("TMIN", "tmin_obs")):
            df[col] = pd.Series({pd.to_datetime(k): v for k, v in
                                 series.get(code, {}).items()})
        df = df.astype(float)
        df.to_csv(cache)
        return df
    except Exception as exc:  # noqa: BLE001 - degrade to cache
        print(f"    (SNOTEL {triplet} pull failed: {type(exc).__name__}; using cache if any)")
        return _load_daily_cache(cache)


def fetch_ghcn_daily(sid, out_dir, start, end, timeout, offline):
    """Daily TMAX/TMIN (degF) for a GHCN station. Cached per station.

    Primary: NCEI access service (units=standard => degF already).
    Fallback: by_station .csv.gz (tenths degC => degF).
    """
    cache = _cache_path(out_dir, "GHCN", sid)
    if offline or requests is None:
        return _load_daily_cache(cache)
    # primary: access service
    try:
        r = requests.get(NCEI_ACCESS_URL,
                         params={"dataset": "daily-summaries", "stations": sid,
                                 "startDate": start, "endDate": end,
                                 "dataTypes": "TMAX,TMIN", "format": "json",
                                 "units": "standard"},
                         timeout=timeout)
        r.raise_for_status()
        payload = r.json()
        if payload:
            df = pd.DataFrame(payload)
            df["date"] = pd.to_datetime(df["DATE"])
            df = df.set_index("date")
            out = pd.DataFrame(index=df.index)
            out.index.name = "date"
            out["tmax_obs"] = pd.to_numeric(df.get("TMAX"), errors="coerce")
            out["tmin_obs"] = pd.to_numeric(df.get("TMIN"), errors="coerce")
            out = out[~out.index.duplicated()].sort_index()
            out.to_csv(cache)
            return out
    except Exception as exc:  # noqa: BLE001 - try the flat-file fallback
        print(f"    (GHCN {sid} access service failed: {type(exc).__name__}; "
              f"trying by_station file)")
    # fallback: by_station csv.gz (tenths degC)
    try:
        import gzip
        r = requests.get(GHCN_BYSTATION_URL.format(sid=sid), timeout=timeout)
        r.raise_for_status()
        raw = gzip.decompress(r.content).decode("utf-8", "replace")
        # columns: ID,DATE,ELEMENT,VALUE,M,Q,S,OBS-TIME (no header)
        df = pd.read_csv(io.StringIO(raw), header=None,
                         names=["ID", "DATE", "ELEMENT", "VALUE", "M", "Q", "S", "OBST"])
        df = df[df["ELEMENT"].isin(["TMAX", "TMIN"])].copy()
        df["date"] = pd.to_datetime(df["DATE"], format="%Y%m%d", errors="coerce")
        df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
        piv = df.pivot_table(index="date", columns="ELEMENT", values="VALUE", aggfunc="first")
        out = pd.DataFrame(index=piv.index)
        out.index.name = "date"
        out["tmax_obs"] = tenthsC_to_f(piv["TMAX"]) if "TMAX" in piv else np.nan
        out["tmin_obs"] = tenthsC_to_f(piv["TMIN"]) if "TMIN" in piv else np.nan
        out = out.sort_index()
        out.to_csv(cache)
        return out
    except Exception as exc:  # noqa: BLE001 - degrade to cache
        print(f"    (GHCN {sid} by_station failed: {type(exc).__name__}; using cache if any)")
        return _load_daily_cache(cache)


# ---------------------------------------------------------------------------
# Collocation: MODEL HRU value and RAW GridMET cell
# ---------------------------------------------------------------------------
def station_to_hru(lon, lat, nhru_gdf, pj, collocation_method):
    """Return (hru_id, hru_elev_m, method_used) for the HRU containing the point."""
    from shapely.geometry import Point
    pt = Point(lon, lat)
    hru_elev = np.asarray(pj["hru_elev"], dtype=float)
    if collocation_method == "polygon":
        hit = nhru_gdf[nhru_gdf.contains(pt)]
        if len(hit):
            hid = int(hit.iloc[0]["hru_id"])
            return hid, float(hru_elev[hid - 1]), "polygon"
    # fallback: nearest hru_lat/hru_lon
    hlat = np.asarray(pj["hru_lat"], dtype=float)
    hlon = np.asarray(pj["hru_lon"], dtype=float)
    d2 = (hlat - lat) ** 2 + (hlon - lon) ** 2
    k = int(np.argmin(d2))
    return k + 1, float(hru_elev[k]), "nearest-latlon"


def fetch_gridmet_cell(lon, lat, years, out_dir, network, sid, timeout, offline):
    """Return cached raw GridMET daily tmax/tmin (degF) for a station, or None.

    The actual network pull is done in bulk by ``prefetch_gridmet_cells`` (one
    THREDDS open per year for all stations), which writes the per-station cache
    this reads. Kept as a function so the per-station loop stays simple and so
    an uncached station still degrades gracefully to raw-approx.
    """
    cache = _cache_path(out_dir, "gridmet_" + network, sid)
    return _load_daily_cache(cache)


def prefetch_gridmet_cells(stations, years, out_dir, timeout, offline):
    """Pull GridMET cells for all stations, caching one CSV per station.

    GridMET's THREDDS OPeNDAP server is slow and server-side subsetting works
    best for a single grid cell, so this opens each year's file once and, for
    every station, selects just that station's nearest cell by INTEGER INDEX
    (``.isel`` on a locally-computed nearest lat/lon index) -- a 1-cell request
    the server can satisfy cheaply -- rather than a vectorized multi-point
    ``.sel`` that drags large spatial slabs across the wire. Writes one
    per-station CSV (``gridmet_<network>_<id>.csv``). Resumable: stations with a
    cache are skipped, so a long pull can be rerun to completion. Degrades
    gracefully: a failed year is skipped with a note; a station that gets no
    year falls back to raw-approx upstream.
    """
    if offline or requests is None or stations.empty:
        if offline:
            print("  (GridMET: offline; using cached cells only)")
        return
    todo = []
    for _, st in stations.iterrows():
        sid = str(st["station_id"])
        net = st["network"]
        if _cache_path(out_dir, "gridmet_" + net, sid).exists():
            continue
        todo.append((net, sid, float(st["lat"]), float(st["lon"])))
    if not todo:
        print("  (GridMET: all station cells already cached)")
        return
    print(f"  GridMET: pulling {len(todo)} station cell(s) over "
          f"{len(years)} year(s) ...", flush=True)
    # Open each year's two files once and reuse the handles across all stations,
    # computing the nearest lat/lon index per station from the (small) coord
    # arrays, then pulling just that 1-D cell series. Write each station's cache
    # immediately so the pull is resumable and progress is visible.
    opened = {}
    coords = {}
    for yr in years:
        try:
            dx = xr.open_dataset(GRIDMET_TMMX.format(yr=yr), decode_timedelta=True)
            dn = xr.open_dataset(GRIDMET_TMMN.format(yr=yr), decode_timedelta=True)
            opened[yr] = (dx, dn)
            coords[yr] = (dx["lat"].values, dx["lon"].values,
                          pd.to_datetime(dx["day"].values))
            print(f"    GridMET {yr}: opened", flush=True)
        except Exception as exc:  # noqa: BLE001 - skip the year
            print(f"    (GridMET {yr} open failed: {type(exc).__name__}: "
                  f"{str(exc)[:100]}; skipping)", flush=True)
    wrote = 0
    for net, sid, lat, lon in todo:
        tmax_parts, tmin_parts = [], []
        for yr in years:
            if yr not in opened:
                continue
            dx, dn = opened[yr]
            glat, glon, days = coords[yr]
            try:
                ilat = int(np.abs(glat - lat).argmin())
                ilon = int(np.abs(glon - lon).argmin())
                vx = dx["air_temperature"].isel(lat=ilat, lon=ilon).values
                vn = dn["air_temperature"].isel(lat=ilat, lon=ilon).values
                tmax_parts.append(pd.Series(k_to_f(vx), index=days))
                tmin_parts.append(pd.Series(k_to_f(vn), index=days))
            except Exception as exc:  # noqa: BLE001 - skip this station-year
                print(f"      ({net} {sid} {yr} cell failed: {type(exc).__name__})",
                      flush=True)
        if not tmax_parts:
            continue
        df = pd.DataFrame({"tmax_raw": pd.concat(tmax_parts),
                           "tmin_raw": pd.concat(tmin_parts)}).sort_index()
        df.index.name = "date"
        df.to_csv(_cache_path(out_dir, "gridmet_" + net, sid))
        wrote += 1
        print(f"    GridMET cell cached: {net} {sid} ({wrote}/{len(todo)})", flush=True)
    for dx, dn in opened.values():
        dx.close()
        dn.close()
    print(f"  GridMET: wrote {wrote} station cell cache file(s)", flush=True)


# ---------------------------------------------------------------------------
# Winter-mean bias helpers
# ---------------------------------------------------------------------------
def winter_mean(series: pd.Series):
    s = series.dropna()
    if s.empty:
        return np.nan, 0
    win = s[s.index.month.isin(WINTER_MONTHS)]
    return (float(win.mean()) if len(win) else np.nan), int(len(win))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=pl.Path,
                    default=pl.Path("D:/test_hw_calibration_results/Sandy_beta4"))
    ap.add_argument("--gis", type=pl.Path,
                    default=pl.Path("D:/nhm-workspace/Oregon_Recharge/models/"
                                    "SandyRiver/inputs/source_data/GIS/model_layers.gpkg"))
    ap.add_argument("--weights", type=pl.Path,
                    default=pl.Path("D:/nhm-workspace/Oregon_Recharge/models/"
                                    "SandyRiver/inputs/source_data/nhru_weights_gridmet.csv"))
    ap.add_argument("--out-dir", type=pl.Path,
                    default=pl.Path("d:/nhm-assist/.agents/tasks/"
                                    "gridmet-warm-bias-verification"))
    ap.add_argument("--buffer-km", type=float, default=15.0)
    ap.add_argument("--wy-start", type=int, default=2010)
    ap.add_argument("--wy-end", type=int, default=2021)
    ap.add_argument("--offline", action="store_true",
                    help="Skip all network pulls; use cached raw data only.")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args(argv)

    run = args.run_dir.resolve()
    out_dir = args.out_dir.resolve()
    (out_dir / "stations_raw").mkdir(parents=True, exist_ok=True)

    # analysis window: WY2010-2021 = 2009-10-01 .. 2021-09-30
    start = f"{args.wy_start - 1}-10-01"
    end = f"{args.wy_end}-09-30"
    cal_years = list(range(args.wy_start - 1, args.wy_end + 1))
    win_start, win_end = pd.Timestamp(start), pd.Timestamp(end)
    print(f"Analysis window: WY{args.wy_start}-{args.wy_end} "
          f"({start} .. {end}); winter = DJFM")

    # --- basin footprint + HRU table ---
    print("Loading basin footprint and HRU table ...")
    bbox, nhru_gdf, pj, collocation_method = load_basin_and_hrus(
        args.gis, run, args.buffer_km)

    # --- station discovery ---
    print("Discovering stations ...")
    snotel = discover_snotel(bbox, out_dir, args.timeout, args.offline)
    ghcn = discover_ghcn(bbox, out_dir, args.timeout, args.offline,
                         args.wy_start, args.wy_end)
    # GHCN mirrors the SNOTEL network under IDs of the form ``USS********S``;
    # keeping both would double-count the same physical site in the regression.
    # Drop the GHCN copies that coincide (within ~1 km) with a discovered AWDB
    # SNOTEL/SCAN station, preferring the native AWDB record (degF, no unit
    # round-trip). Record the dropped count for the report.
    n_ghcn_dupe = 0
    if not ghcn.empty and not snotel.empty:
        keep = []
        for _, g in ghcn.iterrows():
            is_snotel_mirror = str(g["station_id"]).startswith("USS")
            if is_snotel_mirror:
                near = ((snotel["lat"] - g["lat"]).abs() < 0.01) & \
                       ((snotel["lon"] - g["lon"]).abs() < 0.01)
                if near.any():
                    n_ghcn_dupe += 1
                    continue
            keep.append(g)
        ghcn = pd.DataFrame(keep, columns=ghcn.columns) if keep else ghcn.iloc[0:0]
        if n_ghcn_dupe:
            print(f"  (dropped {n_ghcn_dupe} GHCN record(s) that mirror an AWDB "
                  f"SNOTEL/SCAN site; kept the native AWDB record)")

    stations = pd.concat([snotel, ghcn], ignore_index=True)
    if stations.empty:
        print("\n!! No stations discovered (network blocked and no cache). "
              "This run is NOT a success -- see the report's "
              "'data not retrievable' section.")

    # --- open model drivers once ---
    tmax_ds = xr.open_dataset(run / "tmax.nc", decode_timedelta=True)
    tmin_ds = xr.open_dataset(run / "tmin.nc", decode_timedelta=True)
    model_time = pd.to_datetime(tmax_ds["time"].values)
    tmax_arr = tmax_ds["tmax"]
    tmin_arr = tmin_ds["tmin"]
    win_mask = (model_time >= win_start) & (model_time <= win_end)

    # The GridMET->HRU weights file (nhru_weights_gridmet.csv) documents the
    # cell->HRU footprint used by the model; the raw-approx fallback maps a
    # station to its containing HRU's own driver column (that HRU's dominant
    # weighted cell), so the weights file is noted but not loaded here.
    if args.weights.exists():
        print(f"  (GridMET->HRU weights present: {args.weights.name})")

    # --- bulk GridMET cell pull (one THREDDS open per year, all stations) ---
    print("Pre-fetching raw GridMET cells (bulk) ...")
    prefetch_gridmet_cells(stations, cal_years, out_dir, args.timeout, args.offline)

    # --- per-station loop ---
    rows = []
    n_live_gridmet = 0
    n_raw_approx = 0
    print("Collocating and pulling daily series per station ...")
    for _, st in stations.iterrows():
        sid = str(st["station_id"])
        net = st["network"]
        lon, lat = float(st["lon"]), float(st["lat"])

        # observed daily
        if net == "GHCN":
            obs = fetch_ghcn_daily(sid, out_dir, start, end, args.timeout, args.offline)
        else:
            obs = fetch_snotel_daily(st["triplet"], out_dir, start, end,
                                     args.timeout, args.offline)
        if obs is None or obs.empty:
            rows.append(_blank_row(st, collocation_method))
            continue
        obs = obs[(obs.index >= win_start) & (obs.index <= win_end)]

        # MODEL HRU collocation
        hid, hru_elev_m, used = station_to_hru(lon, lat, nhru_gdf, pj, collocation_method)
        col = hid - 1
        model_tmax = pd.Series(np.asarray(tmax_arr[:, col].values, dtype=float),
                               index=model_time)
        model_tmin = pd.Series(np.asarray(tmin_arr[:, col].values, dtype=float),
                               index=model_time)
        model_tmax = model_tmax[(model_tmax.index >= win_start) & (model_tmax.index <= win_end)]
        model_tmin = model_tmin[(model_tmin.index >= win_start) & (model_tmin.index <= win_end)]

        # RAW GridMET cell (live) with raw-approx fallback
        raw = fetch_gridmet_cell(lon, lat, cal_years, out_dir, net, sid,
                                 args.timeout, args.offline)
        if raw is not None and not raw.empty:
            raw_source = "gridmet-thredds"
            n_live_gridmet += 1
            raw = raw[(raw.index >= win_start) & (raw.index <= win_end)]
            raw_tmax = raw["tmax_raw"]
            raw_tmin = raw["tmin_raw"]
        else:
            raw_source = "raw-approx"
            n_raw_approx += 1
            # approximate the raw cell by the containing HRU's own driver column
            raw_tmax = model_tmax
            raw_tmin = model_tmin

        # daily bias (MODEL - OBS), aligned on dates, then winter mean
        def _bias_winter(model_s, obs_s):
            df = pd.DataFrame({"m": model_s, "o": obs_s}).dropna()
            if df.empty:
                return np.nan, 0
            return winter_mean(df["m"] - df["o"])

        wtx_model, n_tx = _bias_winter(model_tmax, obs["tmax_obs"])
        wtn_model, _ = _bias_winter(model_tmin, obs["tmin_obs"])
        wtx_raw, _ = _bias_winter(raw_tmax, obs["tmax_obs"])
        wtn_raw, _ = _bias_winter(raw_tmin, obs["tmin_obs"])

        obs_winter_tmax, _ = winter_mean(obs["tmax_obs"])
        obs_winter_tmin, _ = winter_mean(obs["tmin_obs"])

        rows.append({
            "station_id": sid, "triplet": st.get("triplet", ""),
            "network": net, "name": st.get("name", ""),
            "lon": lon, "lat": lat,
            "elevation_m": float(st["elevation_m"]) if pd.notna(st["elevation_m"]) else np.nan,
            "n_days_tmax": int(pd.DataFrame({"m": model_tmax, "o": obs["tmax_obs"]}).dropna().shape[0]),
            "n_days_winter": int(n_tx),
            "hru_id": hid, "hru_elev_m": hru_elev_m,
            "collocation_method": used, "raw_source": raw_source,
            "obs_winter_tmax": obs_winter_tmax,
            "obs_winter_tmin": obs_winter_tmin,
            "winter_tmax_bias_model": wtx_model,
            "winter_tmin_bias_model": wtn_model,
            "winter_tmax_bias_raw": wtx_raw,
            "winter_tmin_bias_raw": wtn_raw,
        })

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values("elevation_m", na_position="last").reset_index(drop=True)

    # --- model effective lapse: winter-mean model tmax across all HRUs vs hru_elev ---
    hru_elev_all = np.asarray(pj["hru_elev"], dtype=float)
    model_tmax_win = np.asarray(tmax_arr.values[win_mask, :], dtype=float)
    # restrict winter months
    wt = model_time[win_mask]
    djfm = np.isin(wt.month, WINTER_MONTHS)
    hru_winter_tmax = model_tmax_win[djfm, :].mean(axis=0)  # per HRU
    model_lapse_fit = regress(hru_elev_all, hru_winter_tmax)  # degF per m
    # degF/m -> degC/km: slope[degF/m]*1000[m/km]*(5/9)[degC/degF]
    model_lapse_ckm = model_lapse_fit["slope"] * 1000.0 * (5.0 / 9.0) if np.isfinite(model_lapse_fit["slope"]) else np.nan

    # --- model effective TMIN lapse: winter-mean model tmin across all HRUs vs hru_elev ---
    # (mirrors the model tmax block above; uses the already-open tmin_arr and the
    # same win_mask / djfm masks. Must run before tmin_ds.close() below.)
    model_tmin_win = np.asarray(tmin_arr.values[win_mask, :], dtype=float)
    hru_winter_tmin = model_tmin_win[djfm, :].mean(axis=0)  # per HRU
    model_tmin_lapse_fit = regress(hru_elev_all, hru_winter_tmin)  # degF per m
    model_tmin_lapse_ckm = (model_tmin_lapse_fit["slope"] * 1000.0 * (5.0 / 9.0)
                            if np.isfinite(model_tmin_lapse_fit["slope"]) else np.nan)

    # --- observed station lapse: station winter-mean obs tmax vs elevation ---
    obs_lapse_fit = {"slope": np.nan, "r": np.nan, "p": np.nan, "n": 0}
    obs_lapse_ckm = np.nan
    if not summary.empty:
        obs_df = summary.dropna(subset=["elevation_m", "obs_winter_tmax"])
        obs_df = obs_df[obs_df["n_days_winter"] >= MIN_WINTER_DAYS]
        obs_lapse_fit = regress(obs_df["elevation_m"], obs_df["obs_winter_tmax"])
        obs_lapse_ckm = (obs_lapse_fit["slope"] * 1000.0 * (5.0 / 9.0)
                         if np.isfinite(obs_lapse_fit["slope"]) else np.nan)

    # --- observed station TMIN lapse: station winter-mean obs tmin vs elevation ---
    # (mirrors the observed tmax block above)
    obs_tmin_lapse_fit = {"slope": np.nan, "r": np.nan, "p": np.nan, "n": 0}
    obs_tmin_lapse_ckm = np.nan
    if not summary.empty:
        obs_tn_df = summary.dropna(subset=["elevation_m", "obs_winter_tmin"])
        obs_tn_df = obs_tn_df[obs_tn_df["n_days_winter"] >= MIN_WINTER_DAYS]
        obs_tmin_lapse_fit = regress(obs_tn_df["elevation_m"], obs_tn_df["obs_winter_tmin"])
        obs_tmin_lapse_ckm = (obs_tmin_lapse_fit["slope"] * 1000.0 * (5.0 / 9.0)
                              if np.isfinite(obs_tmin_lapse_fit["slope"]) else np.nan)

    # --- bias vs elevation regressions (both collocation variants, tmax & tmin) ---
    def _bias_regression(col):
        if summary.empty:
            return {"slope": np.nan, "intercept": np.nan, "r": np.nan, "p": np.nan, "n": 0}
        d = summary.dropna(subset=["elevation_m", col])
        d = d[d["n_days_winter"] >= MIN_WINTER_DAYS]
        res = regress(d["elevation_m"], d[col])
        # convert slope degF per m -> degF per 1000 m for reporting
        res["slope_per_1000m"] = res["slope"] * 1000.0 if np.isfinite(res["slope"]) else np.nan
        res["mean_bias"] = float(d[col].mean()) if len(d) else np.nan
        return res

    reg_tmax_model = _bias_regression("winter_tmax_bias_model")
    reg_tmin_model = _bias_regression("winter_tmin_bias_model")
    reg_tmax_raw = _bias_regression("winter_tmax_bias_raw")
    reg_tmin_raw = _bias_regression("winter_tmin_bias_raw")

    # --- write summary CSV ---
    csv_path = out_dir / "gridmet_temp_bias_summary.csv"
    summary.to_csv(csv_path, index=False)
    # also write the per-station alias name referenced by the plan
    summary.to_csv(out_dir / "gridmet_temp_bias_per_station.csv", index=False)
    print(f"wrote {csv_path}")

    # --- build the Plotly HTML ---
    html_path = out_dir / "gridmet_temp_bias_vs_elevation.html"
    _build_html(summary, hru_elev_all, hru_winter_tmax, model_lapse_fit,
                obs_lapse_fit, reg_tmax_model, reg_tmax_raw, reg_tmin_model,
                reg_tmin_raw, model_lapse_ckm, obs_lapse_ckm, run, args,
                html_path)
    print(f"wrote {html_path}")

    tmax_ds.close()
    tmin_ds.close()

    # --- headline numbers block ---
    n_snotel = int((summary["network"] != "GHCN").sum()) if not summary.empty else 0
    n_ghcn = int((summary["network"] == "GHCN").sum()) if not summary.empty else 0
    if not summary.empty:
        emin = np.nanmin(summary["elevation_m"].values)
        emax = np.nanmax(summary["elevation_m"].values)
    else:
        emin = emax = np.nan
    nominal_lo, nominal_hi = -5.0, -3.5  # degC/km winter environmental (negative=cooling with height)

    print("\n================ HEADLINE NUMBERS ================")
    print(f"stations: SNOTEL/SCAN={n_snotel}, GHCN={n_ghcn}, "
          f"elevation range {emin:.0f}-{emax:.0f} m" if not summary.empty
          else "stations: NONE retrieved")
    print(f"collocation_method={collocation_method}; "
          f"live GridMET cells={n_live_gridmet}, raw-approx={n_raw_approx}")
    for label, reg in (("tmax MODEL-HRU", reg_tmax_model),
                       ("tmax RAW-GridMET", reg_tmax_raw),
                       ("tmin MODEL-HRU", reg_tmin_model),
                       ("tmin RAW-GridMET", reg_tmin_raw)):
        print(f"  {label:18s} bias-vs-elev slope={reg.get('slope_per_1000m', np.nan):+.3f} degF/1000m "
              f"intercept={reg.get('intercept', np.nan):+.2f} r={reg.get('r', np.nan):+.3f} "
              f"p={reg.get('p', np.nan):.3g} n={reg.get('n', 0)} "
              f"meanbias={reg.get('mean_bias', np.nan):+.2f} degF")
    print(f"  lapse model-effective = {model_lapse_ckm:+.2f} degC/km (r={model_lapse_fit['r']:+.3f}, n={model_lapse_fit['n']})")
    print(f"  lapse observed-station= {obs_lapse_ckm:+.2f} degC/km (r={obs_lapse_fit.get('r', np.nan):+.3f}, n={obs_lapse_fit.get('n', 0)})")
    print(f"  lapse nominal winter  = {nominal_lo:.1f} to {nominal_hi:.1f} degC/km (dry adiabatic ~ -9.8)")
    if np.isfinite(model_lapse_ckm) and np.isfinite(obs_lapse_ckm):
        print(f"  model-minus-observed lapse gap = {model_lapse_ckm - obs_lapse_ckm:+.2f} degC/km "
              f"(positive => model under-lapses / too warm aloft)")
    print(f"  lapse model-effective tmin = {model_tmin_lapse_ckm:+.2f} degC/km (r={model_tmin_lapse_fit['r']:+.3f}, n={model_tmin_lapse_fit['n']})")
    print(f"  lapse observed-station tmin= {obs_tmin_lapse_ckm:+.2f} degC/km (r={obs_tmin_lapse_fit.get('r', np.nan):+.3f}, n={obs_tmin_lapse_fit.get('n', 0)})")
    if np.isfinite(model_tmin_lapse_ckm) and np.isfinite(obs_tmin_lapse_ckm):
        print(f"  tmin model-minus-observed lapse gap = {model_tmin_lapse_ckm - obs_tmin_lapse_ckm:+.2f} degC/km "
              f"(positive => model under-lapses / too warm aloft)")
    print("==================================================\n")

    return 0


def _blank_row(st, collocation_method):
    return {
        "station_id": str(st["station_id"]), "triplet": st.get("triplet", ""),
        "network": st["network"], "name": st.get("name", ""),
        "lon": float(st["lon"]), "lat": float(st["lat"]),
        "elevation_m": float(st["elevation_m"]) if pd.notna(st["elevation_m"]) else np.nan,
        "n_days_tmax": 0, "n_days_winter": 0,
        "hru_id": np.nan, "hru_elev_m": np.nan,
        "collocation_method": collocation_method, "raw_source": "none",
        "obs_winter_tmax": np.nan,
        "obs_winter_tmin": np.nan,
        "winter_tmax_bias_model": np.nan, "winter_tmin_bias_model": np.nan,
        "winter_tmax_bias_raw": np.nan, "winter_tmin_bias_raw": np.nan,
    }


def _fit_line(reg, x):
    if not np.isfinite(reg.get("slope", np.nan)):
        return None, None
    xs = np.array([np.nanmin(x), np.nanmax(x)])
    ys = reg["slope"] * xs + reg["intercept"]
    return xs, ys


def _annot(reg, per1000=True):
    sl = reg.get("slope_per_1000m" if per1000 else "slope", np.nan)
    unit = "degF/1000m" if per1000 else "degF/m"
    return (f"slope={sl:+.2f} {unit}, r={reg.get('r', np.nan):+.2f}, "
            f"p={reg.get('p', np.nan):.2g}, n={reg.get('n', 0)}")


def _build_html(summary, hru_elev_all, hru_winter_tmax, model_lapse_fit,
                obs_lapse_fit, reg_tmax_model, reg_tmax_raw, reg_tmin_model,
                reg_tmin_raw, model_lapse_ckm, obs_lapse_ckm, run, args,
                html_path):
    fig = make_subplots(
        rows=3, cols=1, vertical_spacing=0.09,
        subplot_titles=(
            "(i) Winter (DJFM) tmax bias (MODEL - OBS) vs station elevation",
            "(ii) Winter (DJFM) tmin bias (MODEL - OBS) vs station elevation",
            "(iii) Lapse-rate comparison: model winter tmax vs hru_elev, with observed-station fit",
        ),
    )

    def _scatter(row, model_col, raw_col, reg_model, reg_raw):
        if summary.empty:
            return
        for net, sym in (("SNOTEL", "circle"), ("SCAN", "square"), ("GHCN", "diamond")):
            d = summary[(summary["network"] == net)].dropna(subset=["elevation_m"])
            if d.empty:
                continue
            fig.add_trace(go.Scatter(
                x=d["elevation_m"], y=d[model_col], mode="markers",
                name=f"{net} MODEL-HRU", legendgroup="model",
                marker=dict(symbol=sym, color="#d62728", size=8,
                            line=dict(width=0.5, color="#333"))),
                row=row, col=1)
            fig.add_trace(go.Scatter(
                x=d["elevation_m"], y=d[raw_col], mode="markers",
                name=f"{net} RAW-GridMET", legendgroup="raw",
                marker=dict(symbol=sym, color="#1f77b4", size=7, opacity=0.8,
                            line=dict(width=0.5, color="#333"))),
                row=row, col=1)
        d_all = summary.dropna(subset=["elevation_m"])
        for reg, color, lbl in ((reg_model, "#d62728", "MODEL-HRU"),
                                (reg_raw, "#1f77b4", "RAW-GridMET")):
            xs, ys = _fit_line(reg, d_all["elevation_m"].values)
            if xs is not None:
                fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                              name=f"{lbl} fit", line=dict(color=color, width=2)),
                              row=row, col=1)
        # zero line
        if not d_all.empty:
            fig.add_hline(y=0, line=dict(color="#888", width=1, dash="dot"),
                          row=row, col=1)

    _scatter(1, "winter_tmax_bias_model", "winter_tmax_bias_raw",
             reg_tmax_model, reg_tmax_raw)
    _scatter(2, "winter_tmin_bias_model", "winter_tmin_bias_raw",
             reg_tmin_model, reg_tmin_raw)

    # panel (iii) lapse comparison
    fig.add_trace(go.Scatter(x=hru_elev_all, y=hru_winter_tmax, mode="markers",
                  name="per-HRU winter tmax (model)",
                  marker=dict(color="#9467bd", size=5, opacity=0.6)),
                  row=3, col=1)
    xs, ys = _fit_line(model_lapse_fit, hru_elev_all)
    if xs is not None:
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                      name=f"model lapse fit ({model_lapse_ckm:+.2f} degC/km)",
                      line=dict(color="#9467bd", width=2.5)), row=3, col=1)
    if not summary.empty:
        od = summary.dropna(subset=["elevation_m", "obs_winter_tmax"])
        if not od.empty:
            fig.add_trace(go.Scatter(x=od["elevation_m"], y=od["obs_winter_tmax"],
                          mode="markers", name="station obs winter tmax",
                          marker=dict(color="#2ca02c", size=8, symbol="x")),
                          row=3, col=1)
            xso, yso = _fit_line(obs_lapse_fit, od["elevation_m"].values)
            if xso is not None:
                fig.add_trace(go.Scatter(x=xso, y=yso, mode="lines",
                              name=f"observed lapse fit ({obs_lapse_ckm:+.2f} degC/km)",
                              line=dict(color="#2ca02c", width=2.5, dash="dash")),
                              row=3, col=1)

    # annotations with regression stats
    anns = []
    if not summary.empty:
        anns.append(("(i) " + _annot(reg_tmax_model) + " [MODEL-HRU]; "
                     + _annot(reg_tmax_raw) + " [RAW]", 0.0, 1.0))
        anns.append(("(ii) " + _annot(reg_tmin_model) + " [MODEL-HRU]; "
                     + _annot(reg_tmin_raw) + " [RAW]", 0.0, 0.635))
    anns.append((f"(iii) model lapse {model_lapse_ckm:+.2f} degC/km (r={model_lapse_fit['r']:+.2f}) | "
                 f"observed lapse {obs_lapse_ckm:+.2f} degC/km (r={obs_lapse_fit.get('r', np.nan):+.2f}) | "
                 f"nominal winter -3.5 to -5.0 degC/km", 0.0, 0.27))
    for text, xref, yref in anns:
        fig.add_annotation(xref="paper", yref="paper", x=xref, y=yref,
                           xanchor="left", yanchor="bottom", showarrow=False,
                           text=f"<sub>{text}</sub>", align="left",
                           font=dict(size=10, color="#444"))

    for r in (1, 2):
        fig.update_yaxes(title_text="bias degF (model-obs)", row=r, col=1)
        fig.update_xaxes(title_text="station elevation (m)", row=r, col=1)
    fig.update_yaxes(title_text="winter tmax (degF)", row=3, col=1)
    fig.update_xaxes(title_text="elevation (m)", row=3, col=1)

    fig.update_layout(
        title=(f"GridMET temperature warm-bias vs elevation — {run.name}"
               f"<br><sup>WY{args.wy_start}-{args.wy_end}, winter DJFM · "
               f"MODEL-HRU (red) vs RAW-GridMET-cell (blue) · "
               f"SNOTEL=circle, SCAN=square, GHCN=diamond</sup>"),
        height=1200, template="plotly_white", hovermode="closest",
        legend=dict(orientation="v", yanchor="top", y=1.0, xanchor="left", x=1.01),
    )
    fig.write_html(str(html_path), include_plotlyjs=True, full_html=True)


if __name__ == "__main__":
    raise SystemExit(main())
