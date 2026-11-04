"""Calibration-evaluation plots for a PEST++ IES run: observed vs simulated.

For every POI gage and every calibration-target group, this module draws the
observed value against the simulated value on the target's natural time axis,
for a small set of realizations:

* ``starting`` -- the iteration-0 ``base`` (pre-calibration)
* ``base``     -- the final-iteration ``base``
* ``rand_<id>`` -- N random members of the final ensemble (seeded)

Everything is read from files PEST++ IES already wrote; **no model is run**.

Data sources (all in the run folder)
------------------------------------
``<case>.obs_data.csv``      observation names and their groups
``<case>.<iter>.obs.csv``    simulated model-equivalent of every observation
``<case>.obs+noise.csv``     the noise-sampled observation ensemble
``parameters.json``          stream-network topology (to find upstream HRUs)

Observed display
----------------
Observed values are drawn as the ``base`` realization's value with a whisker
from the 5th to the 95th percentile across **all** obs+noise realizations.
Observations are aggregated to the gage *per realization first*, then the
percentiles are taken across realizations.

Aggregation to gages
--------------------
Target names end in either an HRU ``nhm_id`` (HRU targets) or a gage id
(streamflow targets). For HRU targets the contributing HRUs of a gage are its
own segment plus every segment upstream of it, and the plotted value is the
**mean** over those HRUs per time key (applied identically to sim and obs).
Streamflow targets are selected directly by gage id.

The ``streamflow_5day_*`` signature groups are drawn together in ONE plot per
gage, so the 5-day record reads as a continuous time series. Observed points
are colored by signature group (low, ex_low, pulse, small, large; ascending and
descending); the simulated series are neutral.

Values at or below ``SENTINEL`` (-9990, the PEST++ no-data fill) are masked.
"""
from __future__ import annotations

import pathlib as pl
import re
from collections import defaultdict, deque
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import xarray as xr

TARGETS_ARCHIVE = "calib_eval_targets.nc"
SENTINEL = -9990.0

# HRU-based target groups -> aggregated by MEAN over the contributing HRUs.
HRU_GROUPS = {
    "actet_mean_mon", "recharge_ann", "soil_moist_ann",
    "soil_moist_mean_mon", "runoff_mon", "swe_monthly",
}
# Monthly streamflow target groups: one plot each.
STREAMFLOW_MONTHLY_GROUPS = {"streamflow_mon", "streamflow_mean_mon"}
# All streamflow_5day_* signature groups are drawn together in ONE plot per gage
# (output key below). Observed points are colored by signature group; the
# simulated series stay neutral so the starting/base/random convention holds.
FIVEDAY_KEY = "streamflow_5day"
FIVEDAY_COLORS = {
    "streamflow_5day_low": "#1f77b4",
    "streamflow_5day_ex_low": "#9467bd",
    "streamflow_5day_pulse_ascnd": "#ff7f0e",
    "streamflow_5day_pulse_dscnd": "#d62728",
    "streamflow_5day_small_ascnd": "#e377c2",
    "streamflow_5day_small_dscnd": "#8c564b",
    "streamflow_5day_large_ascnd": "#17becf",
    "streamflow_5day_large_dscnd": "#bcbd22",
}
_FALLBACK_COLORS = ["#7f7f7f", "#aec7e8", "#ffbb78", "#98df8a", "#c5b0d5"]
# Every streamflow group; used to tell which gages had a streamflow target.
STREAMFLOW_GROUPS = STREAMFLOW_MONTHLY_GROUPS | {
    "streamflow_5day_low", "streamflow_5day_ex_low",
    "streamflow_5day_pulse_ascnd", "streamflow_5day_pulse_dscnd",
    "streamflow_5day_small_ascnd", "streamflow_5day_small_dscnd",
    "streamflow_5day_large_ascnd", "streamflow_5day_large_dscnd",
}
SKIP_GROUPS = {"streamflow_nodata"}

BOLD = {"starting", "base"}
BOLD_STYLE = {
    "starting": dict(color="#1a9850", size=7, symbol="circle"),
    "base": dict(color="#000000", size=7, symbol="circle"),
}
FAINT_SIM = dict(color="rgba(30,30,30,0.30)", size=3, symbol="circle")

X_TITLE = {
    "actet_mean_mon": "month", "soil_moist_mean_mon": "month",
    "streamflow_mean_mon": "month",
    "recharge_ann": "year", "soil_moist_ann": "year",
    "runoff_mon": "date", "streamflow_mon": "date",
    "swe_monthly": "date",
}
Y_TITLE = {
    "actet_mean_mon": "actual ET (in/day, mean monthly)",
    "recharge_ann": "recharge (normalized 0-1)",
    "soil_moist_ann": "soil moisture (normalized 0-1)",
    "soil_moist_mean_mon": "soil moisture (normalized 0-1)",
    "runoff_mon": "HRU streamflow (cfs)",
    "swe_monthly": "SWE (inches)",
    "streamflow_mon": "streamflow (cfs)",
    "streamflow_mean_mon": "streamflow (cfs, mean monthly)",
}


# --------------------------------------------------------------------------- #
# Reading the ensembles
# --------------------------------------------------------------------------- #
def read_ensemble(path) -> pd.DataFrame:
    """Read an ensemble csv; index = realization name, columns = names (str)."""
    df = pd.read_csv(path, index_col=0, low_memory=False)
    df.index = [str(i) for i in df.index]
    df.columns = [str(c) for c in df.columns]
    return df


def choose_realizations(run_dir, case: str, iteration: int,
                        n_random: int = 10, seed: int = 0):
    """Return the evaluation plan: ``[(label, param_iteration, realization_id)]``.

    ``starting`` (iteration-0 base), ``base`` (final-iteration base), then
    ``n_random`` random final-ensemble members drawn with a fixed ``seed``.
    """
    run_dir = pl.Path(run_dir)
    sim_final = read_ensemble(run_dir / f"{case}.{iteration}.obs.csv")
    pool = [i for i in sim_final.index if i != "base"]
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(pool), size=min(n_random, len(pool)), replace=False)
    rand_ids = [pool[k] for k in sorted(pick)]
    plan = [("starting", 0, "base"), ("base", iteration, "base")]
    plan += [(f"rand_{rid}", iteration, rid) for rid in rand_ids]
    return plan


def check_ensemble_names(run_dir, case: str, iteration: int) -> dict:
    """Count observation names missing from the sim / obs+noise ensembles.

    Simulated and observed values are looked up by observation *name*, so any
    name in ``obs_data.csv`` that is absent from an ensemble would plot as
    empty. All counts should be zero.
    """
    run_dir = pl.Path(run_dir)
    names = pd.read_csv(run_dir / f"{case}.obs_data.csv")["obsnme"].astype(str)
    sim_cols = set(pd.read_csv(run_dir / f"{case}.{iteration}.obs.csv",
                               nrows=0, index_col=0).columns.astype(str))
    obs_cols = set(pd.read_csv(run_dir / f"{case}.obs+noise.csv",
                               nrows=0, index_col=0).columns.astype(str))
    return {
        "n_obs_names": len(names),
        "missing_in_sim": int((~names.isin(sim_cols)).sum()),
        "missing_in_obs+noise": int((~names.isin(obs_cols)).sum()),
    }


def check_forward_run_5day(run_dir) -> str:
    """Report whether the run's ``forward_run.py`` has the 5-day alignment fix.

    Older forward runs ravelled the 5-day streamflow array time-outer/gage-inner
    while labelling it gage-outer/time-inner, so every simulated 5-day value sat
    under the wrong gage/date name. The fixed script transposes the array to
    ``(poi_gages, time)`` first. Returns one of ``"ok"``, ``"missing_fix"``,
    ``"no_5day_block"``, ``"no_forward_run"``.
    """
    fr = pl.Path(run_dir) / "forward_run.py"
    if not fr.is_file():
        return "no_forward_run"
    text = fr.read_text(encoding="utf-8", errors="replace")
    if "streamflow_5day" not in text:
        return "no_5day_block"
    return "ok" if re.search(r"transpose\(\s*['\"]poi_gages['\"]\s*,\s*['\"]time['\"]", text) else "missing_fix"


# --------------------------------------------------------------------------- #
# Extraction: write the targets archive
# --------------------------------------------------------------------------- #
def extract_targets(run_dir, case: str, iteration: int, plan, out_path) -> pl.Path:
    """Write the sim/obs target archive (netCDF) for the planned realizations.

    Variables: ``sim`` and ``obs`` (realization x obsnme) for the planned
    realizations, ``obs_ensemble`` (obs_realization x obsnme) holding the full
    obs+noise ensemble, and ``obgnme`` (obsnme) with each name's group.
    """
    run_dir = pl.Path(run_dir)
    od = pd.read_csv(run_dir / f"{case}.obs_data.csv")
    od["obsnme"] = od["obsnme"].astype(str)
    names = list(od["obsnme"])
    obgnme = pd.Series(od["obgnme"].astype(str).values, index=od["obsnme"].values)

    sim_by_iter = {
        0: read_ensemble(run_dir / f"{case}.0.obs.csv"),
        iteration: read_ensemble(run_dir / f"{case}.{iteration}.obs.csv"),
    }
    obs_noise = read_ensemble(run_dir / f"{case}.obs+noise.csv")

    labels, sim_rows, obs_rows = [], [], []
    for label, it, rid in plan:
        sim_df = sim_by_iter[it]
        sim_id = rid if rid in sim_df.index else "base"
        obs_id = rid if rid in obs_noise.index else "base"
        labels.append(label)
        sim_rows.append(sim_df.loc[sim_id].reindex(names).values)
        obs_rows.append(obs_noise.loc[obs_id].reindex(names).values)

    obs_full = obs_noise.reindex(columns=names)
    ds = xr.Dataset(
        {
            "sim": (("realization", "obsnme"), np.array(sim_rows, dtype=float)),
            "obs": (("realization", "obsnme"), np.array(obs_rows, dtype=float)),
            "obs_ensemble": (("obs_realization", "obsnme"),
                             obs_full.values.astype(float)),
            "obgnme": (("obsnme",), obgnme.reindex(names).values),
        },
        coords={
            "realization": labels,
            "obs_realization": [str(i) for i in obs_full.index],
            "obsnme": names,
        },
    )
    ds.attrs["case"] = case
    ds.attrs["final_iteration"] = iteration
    out_path = pl.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out_path)
    return out_path


@dataclass
class TargetData:
    """The extracted targets, as plain DataFrames ready for aggregation."""

    sim: pd.DataFrame          # realization x obsnme
    obs_ens: pd.DataFrame      # obs_realization x obsnme (full obs+noise ensemble)
    obgnme: pd.Series          # obsnme -> observation group
    realizations: list         # evaluation realization labels, in plot order


def load_targets(path) -> TargetData:
    """Load an archive written by :func:`extract_targets`."""
    with xr.open_dataset(path) as ds:
        sim = ds["sim"].to_pandas()
        sim.columns = [str(c) for c in sim.columns]
        obs_ens = ds["obs_ensemble"].to_pandas()
        obs_ens.columns = [str(c) for c in obs_ens.columns]
        obs_ens.index = [str(i) for i in obs_ens.index]
        obgnme = pd.Series(
            ds["obgnme"].values.astype(str),
            index=[str(n) for n in ds["obsnme"].values],
        )
        realizations = [str(r) for r in ds["realization"].values]
    return TargetData(sim=sim, obs_ens=obs_ens, obgnme=obgnme,
                      realizations=realizations)


# --------------------------------------------------------------------------- #
# Stream-network topology: which HRUs contribute to a gage
# --------------------------------------------------------------------------- #
def load_run_parameters(run_dir):
    """The run's ``parameters.json`` as a pywatershed parameters mapping."""
    import pywatershed as pws  # slow import; kept lazy

    return pws.parameters.PrmsParameters.load_from_json(
        str(pl.Path(run_dir) / "parameters.json")
    ).parameters


def build_child_map(tosegment) -> dict:
    """``{downstream_seg: [upstream child segs]}`` using 1-based indices."""
    tos = np.asarray(tosegment).astype(int)
    children = defaultdict(list)
    for seg in range(1, len(tos) + 1):
        dn = int(tos[seg - 1])
        if dn != 0:  # 0 marks an outlet
            children[dn].append(seg)
    return children


def upstream_segments(start_seg: int, children: dict) -> set:
    """``start_seg`` plus every segment upstream of it."""
    seen, dq = set(), deque([int(start_seg)])
    while dq:
        s = dq.popleft()
        if s in seen:
            continue
        seen.add(s)
        dq.extend(children.get(s, []))
    return seen


def contributing_hru_positions(gage_id, params):
    """Return ``(0-based HRU positions, upstream segment set)`` for a gage.

    ``tosegment``, ``hru_segment`` and ``poi_gage_segment`` are 1-based local
    indices. Positions index the ``nhru`` axis (same order as ``nhm_id``).
    """
    tosegment = np.asarray(params["tosegment"]).astype(int)
    hru_segment = np.asarray(params["hru_segment"]).astype(int)
    poi_gage_segment = np.asarray(params["poi_gage_segment"]).astype(int)
    poi_gage_id = [str(x) for x in np.asarray(params["poi_gage_id"])]
    if str(gage_id) not in poi_gage_id:
        raise KeyError(f"gage {gage_id} not in poi_gage_id")
    start_seg = int(poi_gage_segment[poi_gage_id.index(str(gage_id))])
    up_segs = upstream_segments(start_seg, build_child_map(tosegment))
    positions = [h for h in range(len(hru_segment)) if int(hru_segment[h]) in up_segs]
    return positions, up_segs


# --------------------------------------------------------------------------- #
# Aggregation to a gage
# --------------------------------------------------------------------------- #
def parse_key_and_tail(group: str, name: str):
    """Return ``(time_key, tail_id)`` for an obs name.

    ``tail_id`` is the HRU nhm_id (HRU groups) or the gage id (streamflow
    groups); ``time_key`` is the group's natural time coordinate as a string.
    """
    body = name[len(group) + 1:] if name.startswith(group + ":") else None
    if body is None:
        # 5-day names carry an EFC code before the time: streamflow_5day_3_1:1994_10_28:14134000
        m = re.match(r"^streamflow_5day[\w\-]*:(.+)$", name)
        body = m.group(1) if m else None
    if body is None:
        return None, None
    parts = body.split(":")
    return ":".join(parts[:-1]), parts[-1]


def time_key_to_x(group: str, key: str):
    """Convert a group's time key string to a plot x value."""
    if group in ("actet_mean_mon", "soil_moist_mean_mon", "streamflow_mean_mon"):
        return int(key)                                   # calendar month 1-12
    if group in ("recharge_ann", "soil_moist_ann"):
        return int(key)                                   # year
    if group in ("runoff_mon", "streamflow_mon"):
        y, m = key.split("_")                             # YYYY_MM
        return pd.Timestamp(int(y), int(m), 1)
    if group == "swe_monthly" or group.startswith("streamflow_5day"):
        y, m, d = key.split("_")                          # YYYY_MM_DD
        return pd.Timestamp(int(y), int(m), int(d))
    return key


def _aggregate(frame: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Mask no-data, then mean over names sharing an x. Returns x x realization."""
    sub = frame[meta["obsnme"].values]
    sub = sub.where(sub > SENTINEL)
    long = sub.T.copy()
    long["x"] = meta.set_index("obsnme").loc[long.index, "x"].values
    return long.groupby("x").mean(numeric_only=True)


def aggregate_group_for_gage(td: TargetData, group: str, names_in_group,
                             contrib_nhm, is_hru: bool):
    """Return ``(sim_df, obs_ens_df)``, each indexed by x (time) per realization.

    HRU groups are the MEAN over the contributing HRUs that have an obs;
    streamflow groups are the direct series (one name per x). Returns
    ``(None, None)`` when nothing matches.
    """
    recs = []
    for nm in names_in_group:
        key, tail = parse_key_and_tail(group, nm)
        if key is None:
            continue
        recs.append((nm, time_key_to_x(group, key), tail))
    if not recs:
        return None, None
    meta = pd.DataFrame(recs, columns=["obsnme", "x", "tail"])
    if is_hru:
        keep = meta["tail"].astype(int).isin({int(h) for h in contrib_nhm})
        meta = meta[keep]
    if meta.empty:
        return None, None
    return _aggregate(td.sim, meta), _aggregate(td.obs_ens, meta)


def obs_base_and_whisker(obs_ens_df: pd.DataFrame) -> pd.DataFrame:
    """Frame indexed by x with ``base`` and the 5th/95th percentiles (``p05``/``p95``)
    taken across obs+noise realizations. ``base`` falls back to the median when
    the ensemble has no ``base`` member."""
    out = pd.DataFrame(index=obs_ens_df.index)
    out["p05"] = obs_ens_df.quantile(0.05, axis=1)
    out["p95"] = obs_ens_df.quantile(0.95, axis=1)
    out["base"] = (obs_ens_df["base"] if "base" in obs_ens_df.columns
                   else obs_ens_df.median(axis=1))
    return out


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def build_group_figure(gage, group, sim_df, obs_ens_df, realizations,
                       x_title=None, y_title=None) -> go.Figure:
    """Observed (base + 5-95% whisker) and simulated markers for one group."""
    fig = go.Figure()

    ow = obs_base_and_whisker(obs_ens_df).dropna(subset=["base"]).sort_index()
    if not ow.empty:
        fig.add_trace(go.Scatter(
            x=ow.index, y=ow["base"].values, mode="markers",
            name="observed (base \u00b1 5-95%)", legendgroup="obs",
            marker=dict(color="#b2182b", size=6, symbol="circle"),
            error_y=dict(
                type="data", symmetric=False,
                array=(ow["p95"] - ow["base"]).clip(lower=0).values,
                arrayminus=(ow["base"] - ow["p05"]).clip(lower=0).values,
                color="rgba(178,24,43,0.6)", thickness=1.2, width=3),
        ))

    _add_sim_traces(fig, sim_df, realizations)

    fig.update_layout(
        title=f"{group} &mdash; gage {gage}  (obs vs sim)",
        xaxis_title=x_title if x_title is not None else X_TITLE.get(group, "time"),
        yaxis_title=y_title if y_title is not None else Y_TITLE.get(group, group),
        height=560, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0),
        margin=dict(t=80, r=30, l=80, b=50), hovermode="x unified",
    )
    return fig


def _add_sim_traces(fig: go.Figure, sim_df: pd.DataFrame, realizations) -> None:
    """Simulated markers: faint random members first, bold starting/base on top."""
    order = ([r for r in realizations if r not in BOLD]
             + [r for r in realizations if r in BOLD])
    for r in order:
        if r not in sim_df.columns:
            continue
        s = sim_df[r].dropna().sort_index()
        style = BOLD_STYLE[r] if r in BOLD else FAINT_SIM
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="markers",
            name=f"sim {r}" if r in BOLD else None,
            legendgroup=f"sim_{r}", showlegend=(r in BOLD),
            marker=dict(**style)))


def build_fiveday_figure(gage, sim_df, obs_ens_df, x_group, realizations) -> go.Figure:
    """Combined 5-day streamflow plot: every signature group on one time axis.

    ``x_group`` maps each x (date) to its observation group. Observed points
    (base value with a 5-95% whisker) are colored by group and get one legend
    entry per group; the simulated series are neutral and span every date.
    """
    fig = go.Figure()
    ow = obs_base_and_whisker(obs_ens_df).dropna(subset=["base"]).sort_index()
    ow["group"] = pd.Series(x_group).reindex(ow.index).values

    present = [g for g in ow["group"].dropna().unique()]
    known = [g for g in FIVEDAY_COLORS if g in present]
    others = sorted(g for g in present if g not in FIVEDAY_COLORS)
    for i, g in enumerate(known + others):
        sub = ow[ow["group"] == g]
        color = FIVEDAY_COLORS.get(g) or _FALLBACK_COLORS[i % len(_FALLBACK_COLORS)]
        rgb = tuple(int(color[k:k + 2], 16) for k in (1, 3, 5))
        fig.add_trace(go.Scatter(
            x=sub.index, y=sub["base"].values, mode="markers",
            name=f"observed {g.replace('streamflow_5day_', '')} (base \u00b1 5-95%)",
            legendgroup=f"obs_{g}",
            marker=dict(color=color, size=6, symbol="circle"),
            error_y=dict(
                type="data", symmetric=False,
                array=(sub["p95"] - sub["base"]).clip(lower=0).values,
                arrayminus=(sub["base"] - sub["p05"]).clip(lower=0).values,
                color=f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.55)",
                thickness=1.2, width=3),
        ))

    _add_sim_traces(fig, sim_df, realizations)

    fig.update_layout(
        title=f"5-day streamflow &mdash; gage {gage}  (obs vs sim; observed colored by signature group)",
        xaxis_title="date", yaxis_title="streamflow (cfs)",
        height=560, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0),
        margin=dict(t=80, r=30, l=80, b=50), hovermode="x unified",
    )
    return fig


def calibration_streamflow_gages(td: TargetData) -> set:
    """Gage ids that have at least one streamflow calibration target."""
    names = td.obgnme[td.obgnme.isin(STREAMFLOW_GROUPS)].index
    return {n.split(":")[-1] for n in names}


def select_gages(td: TargetData, poi_gage_id, gage_set: str = "all-poi",
                 gages=None) -> list:
    """Choose which gages to plot.

    ``gages`` (explicit list) wins. Otherwise ``gage_set`` is ``"all-poi"``
    (every model POI gage; those without a streamflow target still get
    HRU-target plots) or ``"streamflow-targets"`` (only gages with a
    streamflow calibration target).
    """
    poi = [str(g) for g in poi_gage_id]
    if gages:
        return [str(g) for g in gages]
    if gage_set == "streamflow-targets":
        cal = calibration_streamflow_gages(td)
        return sorted(g for g in poi if g in cal)
    if gage_set == "all-poi":
        return sorted(poi)
    raise ValueError(f"gage_set must be 'all-poi' or 'streamflow-targets', got {gage_set!r}")


def build_gage_figures(td: TargetData, gage, params, nhm_id) -> dict:
    """All figures for one gage, as ``{plot key: Figure}``.

    Keys are the HRU / monthly-streamflow group names, plus ``streamflow_5day``
    for the combined 5-day plot.
    """
    pos, _ = contributing_hru_positions(gage, params)
    contrib_nhm = [int(nhm_id[p]) for p in pos]
    figs = {}

    groups = [g for g in td.obgnme.unique()
              if g not in SKIP_GROUPS
              and (g in HRU_GROUPS or g in STREAMFLOW_MONTHLY_GROUPS)]
    for group in groups:
        is_hru = group in HRU_GROUPS
        names = td.obgnme[td.obgnme == group].index.tolist()
        if not is_hru:
            names = [n for n in names if n.split(":")[-1] == str(gage)]
            if not names:
                continue
        sim_df, obs_df = aggregate_group_for_gage(td, group, names, contrib_nhm, is_hru)
        if sim_df is None or sim_df.dropna(how="all").empty:
            continue
        figs[group] = build_group_figure(gage, group, sim_df, obs_df, td.realizations)

    # All 5-day signature groups for this gage, together in one plot.
    sub_groups = [g for g in td.obgnme.unique()
                  if g.startswith("streamflow_5day") and g not in SKIP_GROUPS]
    pool = [n for n in td.obgnme[td.obgnme.isin(sub_groups)].index
            if n.split(":")[-1] == str(gage)]
    if pool:
        sim_df, obs_df = aggregate_group_for_gage(
            td, "streamflow_5day", pool, contrib_nhm, is_hru=False)
        if sim_df is not None and not sim_df.dropna(how="all").empty:
            # each (gage, date) has exactly one name, so x -> group is unambiguous
            x_group = {}
            for nm in pool:
                key, _ = parse_key_and_tail("streamflow_5day", nm)
                if key is not None:
                    x_group[time_key_to_x("streamflow_5day", key)] = td.obgnme[nm]
            figs[FIVEDAY_KEY] = build_fiveday_figure(
                gage, sim_df, obs_df, x_group, td.realizations)
    return figs


def plot_calibration_evaluation(td: TargetData, params, out_dir, gages) -> dict:
    """Write one HTML per gage per target group. Returns ``{gage: [paths]}``.

    Layout: ``<out_dir>/<gage>/calib_eval_<key>_<gage>.html``.
    """
    out_dir = pl.Path(out_dir)
    nhm_id = [int(x) for x in np.asarray(params["nhm_id"])]
    written = {}
    for gage in gages:
        gage_dir = out_dir / str(gage)
        gage_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for key, fig in build_gage_figures(td, gage, params, nhm_id).items():
            p = gage_dir / f"calib_eval_{key}_{gage}.html"
            fig.write_html(str(p), include_plotlyjs="cdn")
            paths.append(p)
        written[str(gage)] = paths
    return written
