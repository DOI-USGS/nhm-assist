"""Interactive time-series: climate drivers over a POI's contributing HRUs vs
the simulated runoff at that POI.

For a given POI gage, this finds the HRUs that drain to the POI's segment
(walking the ``tosegment`` network upstream), averages the temperature and
precipitation drivers over those HRUs, and plots them against the simulated
``seg_outflow`` at the POI from the model's custom output file. Output is a
self-contained interactive Plotly HTML.

Driver units are taken from the NetCDF metadata (here degF / inch) and runoff
from the output metadata (cfs). Temperature is averaged over the contributing
HRUs (basin-mean); precipitation is likewise the per-HRU mean (basin-average
depth per day), not a sum, so it reads as an intensity.

Usage (in the pixi env)::

    pixi run python scripts/plot_poi_drivers_vs_runoff.py \
        --run-dir D:/test_hw_calibration_results/Sandy_beta4 \
        --poi 14131400
"""
from __future__ import annotations

import argparse
import json
import pathlib as pl

import numpy as np
import pandas as pd
import xarray as xr
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def contributing_hrus(pj: dict, target_seg_1based: int):
    """Return (hru_index_array, contributing_segments_set) upstream of a segment."""
    hru_segment = np.asarray(pj["hru_segment"], dtype=int)   # 1-based seg per HRU
    tosegment = np.asarray(pj["tosegment"], dtype=int)       # 1-based downstream, 0=outlet
    nseg = len(tosegment)

    upstream = {s: [] for s in range(1, nseg + 1)}
    for s in range(1, nseg + 1):
        d = tosegment[s - 1]
        if d != 0:
            upstream[d].append(s)

    contrib = set()
    stack = [target_seg_1based]
    while stack:
        s = stack.pop()
        if s in contrib:
            continue
        contrib.add(s)
        stack.extend(upstream[s])

    mask = np.isin(hru_segment, list(contrib))
    return np.where(mask)[0], contrib


def _read_observed_5day(run: pl.Path, poi: str):
    """Return (dates, values_cfs) of observed 5-day-avg streamflow for a POI.

    Reads the PEST++ ``*.obs_data.csv`` (auto-detected from the .pst case name).
    Observation names are ``streamflow_5day_<bin>:<YYYY_MM_DD>:<gageid>`` with
    obsval in cfs; the date is the 5-day bin-start. Only weighted (real)
    observations are kept -- nodata rows carry weight 0 and value -9999.
    """
    psts = sorted(run.glob("*.pst"))
    case = psts[0].stem if psts else None
    od_path = run / f"{case}.obs_data.csv"
    if not od_path.exists():
        cands = sorted(run.glob("*.obs_data.csv"))
        if not cands:
            print("    (no obs_data.csv found; skipping observed 5-day)")
            return pd.DatetimeIndex([]), np.array([])
        od_path = cands[0]
    od = pd.read_csv(od_path, low_memory=False)
    name = od["obsnme"].astype(str)
    sel = name.str.contains("streamflow_5day") & name.str.endswith(f":{poi}")
    g = od[sel & (od["weight"] > 0)].copy()
    if g.empty:
        print(f"    (no weighted observed 5-day streamflow for POI {poi})")
        return pd.DatetimeIndex([]), np.array([])
    datestr = g["obsnme"].astype(str).str.split(":").str[1]
    dates = pd.to_datetime(datestr, format="%Y_%m_%d")
    order = np.argsort(dates.values)
    return dates.values[order], g["obsval"].to_numpy()[order]


def _read_observed_daily(obs_sf_file: pl.Path | None, poi: str, start, end):
    """Return (dates, values_cfs) of observed DAILY streamflow for a POI.

    The run does not store a daily observed series (the PEST obs table only has
    5-day bins). Instead, read daily values from a local streamflow-observations
    NetCDF produced by this project's notebook 1 (``sf_efc.nc``). That file has
    a data variable ``discharge`` (dims ``poi_gage_id`` x ``time``) in units
    ``ft3 s-1`` (== cfs, matching the plot's runoff units, so no unit conversion
    is done); ``poi_gage_id`` is a string-id coordinate and ``time`` is a daily
    datetime axis. Missing days are NaN and are dropped.

    The file path is passed in via ``--obs-sf-file``. Degrades gracefully: if no
    path is given, the POI is not present, or the file is bad/corrupt, print a
    short note and return empty arrays so the plot still builds. Values are
    clipped to the ``[start, end]`` window (the plot's simulated time range) and
    returned sorted by date.
    """
    if obs_sf_file is None:
        print("    (no --obs-sf-file given; skipping daily observed streamflow)")
        return pd.DatetimeIndex([]), np.array([])
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    ds = None
    try:
        ds = xr.open_dataset(obs_sf_file, decode_timedelta=True)
        gage_ids = list(map(str, ds["poi_gage_id"].values))
        if str(poi) not in gage_ids:
            print(f"    (POI {poi} not in {pl.Path(obs_sf_file).name}; "
                  f"skipping daily observed streamflow)")
            return pd.DatetimeIndex([]), np.array([])
        q = ds["discharge"].sel(poi_gage_id=str(poi))
        dates = pd.to_datetime(q["time"].values)
        vals = np.asarray(q.values, dtype=float)
        good = ~np.isnan(vals)
        dates, vals = dates[good], vals[good]
        win = (dates >= s) & (dates <= e)
        dates, vals = dates[win], vals[win]
        order = np.argsort(dates.values)
        return pd.DatetimeIndex(dates.values[order]), vals[order]
    except Exception as exc:  # noqa: BLE001 - any failure => graceful skip
        print(f"    (could not read daily observed streamflow for POI {poi} from "
              f"{obs_sf_file}; skipping: {type(exc).__name__})")
        return pd.DatetimeIndex([]), np.array([])
    finally:
        if ds is not None:
            ds.close()


def _compute_hru_snow(run: pl.Path):
    """Run pywatershed's atmosphere to get hru_snow and hru_rain (inches).

    Returns (snow[time, nhru], rain[time, nhru], time_index). Mirrors the run's
    forward_run.py param loading (JSON params, the stream_tave_init /
    pref_flow_infil_frac fix-ups) so the atmosphere forcing matches the
    calibrated run. hru_snow + hru_rain should sum to hru_ppt (~ prcp).
    """
    import pywatershed as pws

    params = pws.parameters.PrmsParameters.load_from_json(run / "parameters.json")
    pds = params.to_xr_ds()
    if "stream_tave_init" in pds:
        pds = pds.drop_vars("stream_tave_init")
    if "pref_flow_infil_frac" not in pds:
        pds["pref_flow_infil_frac"] = pds.pref_flow_den[:] * 0.0
    params = pws.parameters.PrmsParameters.from_ds(pds)

    control = pws.Control.load_prms(run / "control.default.bandit",
                                    warn_unused_options=False)
    control.options = control.options | {
        "input_dir": run, "budget_type": None, "verbosity": 0,
        "calc_method": "numba",
        "netcdf_output_var_names": None, "netcdf_output_dir": None,
    }
    model = pws.Model([pws.PRMSSolarGeometry, pws.PRMSAtmosphere],
                      control=control, parameters=params)
    atm = model.processes["PRMSAtmosphere"]

    time = pd.to_datetime(np.arange(
        control.start_time, control.end_time + control.time_step,
        dtype="datetime64[D]"))
    nt = len(time)

    # PRMSAtmosphere exposes hru_snow / hru_rain as TimeseriesArrays that are
    # only valid after advancing. Step through time and collect .current each
    # day; this is robust whether the series is precomputed or stepped. Falls
    # back to reading the full .data array if advancing isn't required.
    nhru = params.dims["nhru"]
    snow = np.full((nt, nhru), np.nan)
    rain = np.full((nt, nhru), np.nan)
    for istep in range(nt):
        model.advance()
        model.calculate()
        cur_s = atm["hru_snow"]
        cur_s = cur_s.current if hasattr(cur_s, "current") else np.asarray(cur_s.data)
        snow[istep, :] = np.asarray(cur_s).ravel()[:nhru]
        cur_r = atm["hru_rain"]
        cur_r = cur_r.current if hasattr(cur_r, "current") else np.asarray(cur_r.data)
        rain[istep, :] = np.asarray(cur_r).ravel()[:nhru]
    return snow, rain, time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=pl.Path, required=True)
    ap.add_argument("--poi", required=True, help="POI gage id, e.g. 14131400")
    ap.add_argument("--out", type=pl.Path, default=None,
                    help="Output HTML path (default: <run-dir>/poi_<poi>_drivers_vs_runoff.html)")
    ap.add_argument("--snow-agg", choices=["mean", "sum"], default="mean",
                    help="How to aggregate hru_snow over the contributing HRUs. "
                         "'mean' (default) is basin-average depth, directly "
                         "comparable to the precip line; 'sum' totals across HRUs.")
    ap.add_argument("--obs-sf-file", type=pl.Path, default=None,
                    help="Local streamflow-observations NetCDF (sf_efc.nc) with a "
                         "'discharge' variable (poi_gage_id x time, ft3 s-1) for the "
                         "daily observed streamflow trace. If omitted, that trace is "
                         "skipped.")
    ap.add_argument("--obs-swe-file", type=pl.Path, default=None,
                    help="Observed-SWE NetCDF (SWE_monthly.nc) with an "
                         "'ensemble_mean' variable (time x hru_id, inches, indexed "
                         "by national nhm_id) -- the NHM SWE calibration target. "
                         "Monthly month-end values. If omitted, the observed-SWE "
                         "trace is skipped (simulated SWE still plots).")
    args = ap.parse_args(argv)

    run = args.run_dir.resolve()
    pj = json.load(open(run / "parameters.json"))

    poi_ids = list(map(str, pj["poi_gage_id"]))
    if args.poi not in poi_ids:
        raise SystemExit(f"POI {args.poi} not in run. Available: {poi_ids}")
    pidx = poi_ids.index(args.poi)
    target_seg = int(pj["poi_gage_segment"][pidx])  # 1-based

    hru_idx, contrib_segs = contributing_hrus(pj, target_seg)
    nhm_id = np.asarray(pj["nhm_id"], dtype=int)
    contrib_ids = nhm_id[hru_idx]
    print(f"POI {args.poi}: segment {target_seg}, "
          f"{len(contrib_segs)} contributing segment(s), {len(hru_idx)} HRU(s)")
    print("  HRUs:", sorted(contrib_ids.tolist()))

    # --- drivers (per-HRU) ---
    tmax = xr.open_dataset(run / "tmax.nc", decode_timedelta=True)["tmax"]
    tmin = xr.open_dataset(run / "tmin.nc", decode_timedelta=True)["tmin"]
    prcp = xr.open_dataset(run / "prcp.nc", decode_timedelta=True)["prcp"]
    t_units = tmax.attrs.get("units", "degF")
    p_units = prcp.attrs.get("units", "inch")

    tmax_b = tmax.values[:, hru_idx].mean(axis=1)
    tmin_b = tmin.values[:, hru_idx].mean(axis=1)
    prcp_b = prcp.values[:, hru_idx].mean(axis=1)

    # --- hru_snow: computed by running pywatershed's atmosphere process ---
    # hru_snow (snow fraction of precip, inches) is not in the drivers or the
    # custom output file, so reproduce it exactly as the model does by running
    # PRMSSolarGeometry -> PRMSAtmosphere on this run's own params/control/drivers.
    # PRMSAtmosphere precomputes the full timeseries, so this is cheap.
    snow_hru, rain_hru, snow_time = _compute_hru_snow(run)
    agg = np.sum if args.snow_agg == "sum" else np.mean
    snow_b = agg(snow_hru[:, hru_idx], axis=1)
    rain_b = agg(rain_hru[:, hru_idx], axis=1)

    # --- simulated runoff at POI ---
    out = xr.open_dataset(run / "output" / "model_custom_output.nc", decode_timedelta=True)
    poi_coord = list(map(str, out["poi_gages"].values))
    oidx = poi_coord.index(args.poi)
    runoff = out["seg_outflow"].values[:, oidx]
    r_units = out["seg_outflow"].attrs.get("units", "cfs")
    time = pd.to_datetime(out["time"].values)

    # --- simulated SWE (basin-mean) read directly from the custom output file ---
    # pkwater_equiv (time x nhru, inches, same positional HRU order as
    # parameters.json) is already in the custom-output file, so read it rather
    # than re-running PRMSSnow. Basin SWE is the mean over contributing HRUs.
    sim_swe = out["pkwater_equiv"].values[:, hru_idx].mean(axis=1)
    swe_units = out["pkwater_equiv"].attrs.get("units", p_units)

    # --- observed SWE (NHM calibration target, monthly) from --obs-swe-file ---
    # SWE_monthly.nc is indexed by NATIONAL hru_id (== parameters.json nhm_id),
    # not the local 1..nhru the driver files use, so select by LABEL. Values are
    # monthly (month-end), so keep them on their own dates (do not resample).
    # Degrades gracefully: on any failure, skip just the observed-SWE trace.
    obs_swe_t, obs_swe_v = pd.DatetimeIndex([]), np.array([])
    if args.obs_swe_file is None:
        print("    (no --obs-swe-file given; skipping observed SWE)")
    else:
        swe_ds = None
        try:
            swe_ds = xr.open_dataset(args.obs_swe_file, decode_timedelta=True)
            obs_ids = np.asarray(pj["nhm_id"], dtype=int)[hru_idx]
            obs = swe_ds["ensemble_mean"].sel(hru_id=obs_ids)
            obs_swe_v = np.asarray(obs.mean(dim="hru_id").values, dtype=float)
            obs_swe_t = pd.to_datetime(obs["time"].values)
        except Exception as exc:  # noqa: BLE001 - any failure => graceful skip
            print(f"    (could not read observed SWE from {args.obs_swe_file}; "
                  f"skipping: {type(exc).__name__})")
            obs_swe_t, obs_swe_v = pd.DatetimeIndex([]), np.array([])
        finally:
            if swe_ds is not None:
                swe_ds.close()

    # --- observed 5-day averages for this POI (from the obs_data table) ---
    # obsname: streamflow_5day_<bin>:<YYYY_MM_DD>:<gageid>, obsval in cfs, the
    # date is the 5-day bin-start. Keep only weighted (real) obs; drop nodata.
    obs_t, obs_v = _read_observed_5day(run, args.poi)

    # --- observed DAILY streamflow for this POI (from local sf_efc.nc) ---
    # Not stored in the run; read daily discharge (ft3 s-1 == cfs) from the local
    # streamflow-observations NetCDF passed via --obs-sf-file, over the sim time
    # range. Degrades gracefully to empty on any failure (see helper).
    obs_daily_t, obs_daily_v = _read_observed_daily(
        args.obs_sf_file, args.poi, time.min(), time.max())

    # --- simulated 5-day average on the SAME windows as the observed bins ---
    # The observed 5-day bins (built in notebook 01, calibration years only) do
    # NOT align with a naive resample('5D') grid anchored at the sim start, so
    # match each observed bin-start date to the mean of simulated seg_outflow
    # over that same date..date+4d window. This reproduces the model-vs-obs
    # comparison PEST made and keeps the sim line and obs markers date-aligned.
    daily = pd.Series(runoff, index=time)
    sim_5t, sim_5v = [], []
    for d in pd.to_datetime(obs_t):
        win = daily.loc[d:d + pd.Timedelta(days=4)]
        if len(win):
            sim_5t.append(d)
            sim_5v.append(float(win.mean()))
    sim_5t = pd.to_datetime(sim_5t)
    sim_5v = np.array(sim_5v)

    # driver files may have their own time axis; align by position (same length here)
    n = min(len(time), len(tmax_b), len(snow_b))
    time, tmax_b, tmin_b, prcp_b, runoff, snow_b, rain_b, sim_swe = (
        time[:n], tmax_b[:n], tmin_b[:n], prcp_b[:n], runoff[:n], snow_b[:n],
        rain_b[:n], sim_swe[:n])

    # --- figure: 4 stacked rows sharing x (precip, temp, SWE, runoff) ---
    # The SWE panel (row 3) is where the too-much-rain diagnosis is visible:
    # simulated SWE sits far below the observed calibration target.
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.18, 0.24, 0.26, 0.32],
        subplot_titles=(
            f"Precipitation + rain/snow split (over {len(hru_idx)} contributing HRUs)",
            "Air temperature (basin-mean)",
            f"Snow water equivalent (basin-mean over {len(hru_idx)} HRUs): simulated vs observed target",
            f"Streamflow at POI {args.poi}: simulated seg_outflow + 5-day avgs vs observed (5-day + daily)",
        ),
    )

    snow_label = f"hru_snow {args.snow_agg} ({p_units})"
    rain_label = f"hru_rain {args.snow_agg} ({p_units})"
    fig.add_trace(go.Scatter(x=time, y=prcp_b, name=f"prcp ({p_units})",
                             line=dict(color="#1f77b4", width=1), fill="tozeroy"),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=time, y=rain_b, name=rain_label,
                             line=dict(color="#ff7f0e", width=1), fill="tozeroy"),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=time, y=snow_b, name=snow_label,
                             line=dict(color="#17becf", width=1), fill="tozeroy"),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=time, y=tmax_b, name=f"tmax ({t_units})",
                             line=dict(color="#d62728", width=1)), row=2, col=1)
    fig.add_trace(go.Scatter(x=time, y=tmin_b, name=f"tmin ({t_units})",
                             line=dict(color="#2ca02c", width=1)), row=2, col=1)
    fig.add_trace(go.Scatter(x=time, y=sim_swe, name=f"sim SWE ({swe_units})",
                             line=dict(color="#17becf", width=1.2)), row=3, col=1)
    if len(obs_swe_t):
        fig.add_trace(go.Scatter(x=obs_swe_t, y=obs_swe_v,
                                 name=f"obs SWE ens-mean ({swe_units})",
                                 mode="markers",
                                 marker=dict(color="#000000", size=6,
                                             symbol="circle-open")),
                      row=3, col=1)
    fig.add_trace(go.Scatter(x=time, y=runoff, name=f"sim daily ({r_units})",
                             line=dict(color="#9467bd", width=1),
                             opacity=0.5), row=4, col=1)
    if len(sim_5t):
        fig.add_trace(go.Scatter(x=sim_5t, y=sim_5v,
                                 name=f"sim 5-day avg ({r_units})",
                                 mode="lines+markers",
                                 line=dict(color="#9467bd", width=1.6),
                                 marker=dict(size=3)), row=4, col=1)
    if len(obs_t):
        fig.add_trace(go.Scatter(x=obs_t, y=obs_v, name=f"obs 5-day avg ({r_units})",
                                 mode="markers",
                                 marker=dict(color="#000000", size=5, symbol="circle-open")),
                      row=4, col=1)
    if len(obs_daily_t):
        fig.add_trace(go.Scatter(x=obs_daily_t, y=obs_daily_v,
                                 name=f"obs daily ({r_units})",
                                 mode="lines",
                                 line=dict(color="#555555", width=1),
                                 opacity=0.6), row=4, col=1)

    fig.update_yaxes(title_text=p_units, row=1, col=1)
    fig.update_yaxes(title_text=t_units, row=2, col=1)
    fig.update_yaxes(title_text=swe_units, row=3, col=1)
    fig.update_yaxes(title_text=r_units, row=4, col=1)
    fig.update_xaxes(title_text="date", row=4, col=1,
                     rangeslider=dict(visible=True), rangeslider_thickness=0.05)

    fig.update_layout(
        title=(f"POI {args.poi} — contributing-area drivers, SWE vs simulated runoff"
               f"<br><sup>run: {run.name} · segment {target_seg} · "
               f"HRUs: {', '.join(map(str, sorted(contrib_ids.tolist())))}</sup>"),
        height=1050, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    out_path = args.out or (run / f"poi_{args.poi}_drivers_vs_runoff.html")
    fig.write_html(str(out_path), include_plotlyjs=True, full_html=True)
    print(f"wrote {out_path}")
    for ds in (tmax, tmin, prcp, out):
        ds.close() if hasattr(ds, "close") else None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
