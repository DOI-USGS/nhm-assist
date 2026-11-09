"""Calibration-evaluation plots for a PEST++ IES run: observed vs simulated.

For every POI gage and every calibration-target group, this module draws the
observed value against the simulated value on the target's natural time axis.
The simulated side shows:

* ``starting`` -- the iteration-0 ``base`` (pre-calibration), as a red dashed line
* ``base``     -- the final-iteration ``base``, as a red solid line
* the final-iteration ensemble 5th-95th percentile range, as thin red lines
  with a translucent red fill

Everything is read from files PEST++ IES already wrote; **no model is run**.

Data sources (all in the run folder)
------------------------------------
``<case>.obs_data.csv``      observation names and their groups
``<case>.<iter>.obs.csv``    simulated model-equivalent of every observation
``<case>.obs+noise.csv``     the noise-sampled observation ensemble
``parameters.json``          stream-network topology (to find upstream HRUs)

Observed display
----------------
Observed values are drawn as the ``base`` realization's value (thick black line
with dots), with the 5th and 95th percentiles across **all** obs+noise
realizations as thin lines and a gray fill between them. Observations are
aggregated to the gage *per realization first*, then the percentiles are taken
across realizations. The calibration targets cover odd (calibration) water
years only, so the line, the percentile lines and the gray band break at every
validation-year gap instead of drawing across the missing years.

Aggregation to gages
--------------------
Target names end in either an HRU ``nhm_id`` (HRU targets) or a gage id
(streamflow targets). For HRU targets the contributing HRUs of a gage are its
own segment plus every segment upstream of it, and the plotted value is the
**mean** over those HRUs per time key (applied identically to sim and obs).
Streamflow targets are selected directly by gage id.

The ``streamflow_5day_*`` signature groups are drawn together in ONE plot per
gage, so the 5-day record reads as a continuous time series. The observed base
dots use a distinct black marker shape per signature group (low, ex_low, pulse,
small, large; ascending and descending); the base line, bands and simulated
series are the same as every other group.

The combined 5-day plot is a two-panel STACK sharing the x and y axes: the top
panel is the PRIOR (iteration-0 base as the solid red line, iteration-0
ensemble 5-95% range as the red band) and the bottom panel is the calibrated
plot described above. The observed series is the same in both.

Each element (observed base, observed band, sim starting, sim base, sim band)
is its own legend entry, so it can be toggled on and off from the legend.

Values at or below ``SENTINEL`` (-9990, the PEST++ no-data fill) are masked.
"""
from __future__ import annotations

import pathlib as pl
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import xarray as xr
from plotly.subplots import make_subplots

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
# (output key below). Observed points use a distinct black MARKER SHAPE per
# signature group (no color coding); the base line, percentile lines, and
# simulated series are the same as every other group.
FIVEDAY_KEY = "streamflow_5day"
FIVEDAY_MARKERS = {
    "streamflow_5day_low": "circle",
    "streamflow_5day_ex_low": "square",
    "streamflow_5day_pulse_ascnd": "triangle-up",
    "streamflow_5day_pulse_dscnd": "triangle-down",
    "streamflow_5day_small_ascnd": "diamond",
    "streamflow_5day_small_dscnd": "diamond-open",
    "streamflow_5day_large_ascnd": "star-triangle-up",
    "streamflow_5day_large_dscnd": "star-triangle-down",
}
_FALLBACK_MARKERS = ["cross", "x", "star", "hexagram", "pentagon"]
# Every streamflow group; used to tell which gages had a streamflow target.
STREAMFLOW_GROUPS = STREAMFLOW_MONTHLY_GROUPS | {
    "streamflow_5day_low", "streamflow_5day_ex_low",
    "streamflow_5day_pulse_ascnd", "streamflow_5day_pulse_dscnd",
    "streamflow_5day_small_ascnd", "streamflow_5day_small_dscnd",
    "streamflow_5day_large_ascnd", "streamflow_5day_large_dscnd",
}
SKIP_GROUPS = {"streamflow_nodata"}

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

    Variables:

    * ``sim`` and ``obs`` (realization x obsnme) for the planned realizations.
      Only ``starting`` (iteration-0 base) and ``base`` (final-iteration base)
      are used by the plots now, but the random members are kept for reference.
    * ``obs_ensemble`` (obs_realization x obsnme) -- the full obs+noise ensemble,
      for the observed 5-95% band.
    * ``sim_ensemble`` (sim_realization x obsnme) -- the full FINAL-iteration
      simulated ensemble, for the simulated 5-95% band and the overlap metric.
    * ``sim_ensemble_prior`` (sim_prior_realization x obsnme_5day) -- the full
      ITERATION-0 (prior) simulated ensemble, restricted to the
      ``streamflow_5day_*`` observations. It drives the top (prior) panel of the
      stacked 5-day plot; it is limited to those names to keep the archive small.
    * ``obgnme`` (obsnme) -- each name's observation group.
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
    # Full FINAL-iteration simulated ensemble (all realizations), aligned to the
    # obs-name order. Drives the simulated 5-95% band and the overlap metric.
    sim_full = sim_by_iter[iteration].reindex(columns=names)
    # Prior (iteration-0) ensemble, 5-day streamflow names only.
    five_day_names = [n for n in names
                      if obgnme[n].startswith("streamflow_5day")
                      and obgnme[n] not in SKIP_GROUPS]
    sim_prior = sim_by_iter[0].reindex(columns=five_day_names)
    ds = xr.Dataset(
        {
            "sim": (("realization", "obsnme"), np.array(sim_rows, dtype=float)),
            "obs": (("realization", "obsnme"), np.array(obs_rows, dtype=float)),
            "obs_ensemble": (("obs_realization", "obsnme"),
                             obs_full.values.astype(float)),
            "sim_ensemble": (("sim_realization", "obsnme"),
                             sim_full.values.astype(float)),
            "sim_ensemble_prior": (("sim_prior_realization", "obsnme_5day"),
                                   sim_prior.values.astype(float)),
            "obgnme": (("obsnme",), obgnme.reindex(names).values),
        },
        coords={
            "realization": labels,
            "obs_realization": [str(i) for i in obs_full.index],
            "sim_realization": [str(i) for i in sim_full.index],
            "sim_prior_realization": [str(i) for i in sim_prior.index],
            "obsnme": names,
            "obsnme_5day": five_day_names,
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

    sim: pd.DataFrame          # realization x obsnme (starting, base, random)
    obs_ens: pd.DataFrame      # obs_realization x obsnme (full obs+noise ensemble)
    sim_ens: pd.DataFrame      # sim_realization x obsnme (full final-iter sim ensemble)
    obgnme: pd.Series          # obsnme -> observation group
    realizations: list         # evaluation realization labels, in plot order
    # iteration-0 (prior) sim ensemble, 5-day streamflow names only; empty for
    # archives written before the stacked prior/calibrated 5-day plot existed.
    sim_ens_prior: pd.DataFrame = field(default_factory=pd.DataFrame)
    final_iteration: int = None  # iteration the archive was extracted for


def load_targets(path) -> TargetData:
    """Load an archive written by :func:`extract_targets`."""
    with xr.open_dataset(path) as ds:
        sim = ds["sim"].to_pandas()
        sim.columns = [str(c) for c in sim.columns]
        obs_ens = ds["obs_ensemble"].to_pandas()
        obs_ens.columns = [str(c) for c in obs_ens.columns]
        obs_ens.index = [str(i) for i in obs_ens.index]
        # sim_ensemble was added later; tolerate older archives without it.
        if "sim_ensemble" in ds:
            sim_ens = ds["sim_ensemble"].to_pandas()
            sim_ens.columns = [str(c) for c in sim_ens.columns]
            sim_ens.index = [str(i) for i in sim_ens.index]
        else:
            sim_ens = pd.DataFrame(columns=sim.columns)
        # likewise the prior (iteration-0) 5-day ensemble
        if "sim_ensemble_prior" in ds:
            sim_ens_prior = ds["sim_ensemble_prior"].to_pandas()
            sim_ens_prior.columns = [str(c) for c in sim_ens_prior.columns]
            sim_ens_prior.index = [str(i) for i in sim_ens_prior.index]
        else:
            sim_ens_prior = pd.DataFrame()
        obgnme = pd.Series(
            ds["obgnme"].values.astype(str),
            index=[str(n) for n in ds["obsnme"].values],
        )
        realizations = [str(r) for r in ds["realization"].values]
        final_iteration = (int(ds.attrs["final_iteration"])
                           if "final_iteration" in ds.attrs else None)
    return TargetData(sim=sim, obs_ens=obs_ens, sim_ens=sim_ens, obgnme=obgnme,
                      realizations=realizations, sim_ens_prior=sim_ens_prior,
                      final_iteration=final_iteration)


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


def _group_meta(group: str, names_in_group, contrib_nhm, is_hru: bool):
    """``obsnme / x / tail`` table for the names of one group at one gage (HRU
    groups filtered to the contributing HRUs), or ``None`` if nothing matches."""
    recs = []
    for nm in names_in_group:
        key, tail = parse_key_and_tail(group, nm)
        if key is None:
            continue
        recs.append((nm, time_key_to_x(group, key), tail))
    if not recs:
        return None
    meta = pd.DataFrame(recs, columns=["obsnme", "x", "tail"])
    if is_hru:
        keep = meta["tail"].astype(int).isin({int(h) for h in contrib_nhm})
        meta = meta[keep]
    return None if meta.empty else meta


def aggregate_group_for_gage(td: TargetData, group: str, names_in_group,
                             contrib_nhm, is_hru: bool):
    """Return ``(sim_df, obs_ens_df, sim_ens_df)``, each indexed by x (time).

    ``sim_df`` columns are the named realizations (``starting``/``base``/...);
    ``obs_ens_df`` and ``sim_ens_df`` columns are the full obs+noise and
    final-iteration simulated ensembles. HRU groups are the MEAN over the
    contributing HRUs that have an obs; streamflow groups are the direct series
    (one name per x). Returns ``(None, None, None)`` when nothing matches.
    """
    meta = _group_meta(group, names_in_group, contrib_nhm, is_hru)
    if meta is None:
        return None, None, None
    sim_ens_df = _aggregate(td.sim_ens, meta) if not td.sim_ens.empty else None
    return _aggregate(td.sim, meta), _aggregate(td.obs_ens, meta), sim_ens_df


def aggregate_prior_ensemble(td: TargetData, group: str, names_in_group,
                             contrib_nhm, is_hru: bool):
    """The iteration-0 (prior) simulated ensemble aggregated exactly like the
    final one in :func:`aggregate_group_for_gage` (same names, same x). Returns
    ``None`` when the archive has no prior ensemble or it lacks these names
    (e.g. an archive written before the stacked 5-day plot existed)."""
    if td.sim_ens_prior is None or td.sim_ens_prior.empty:
        return None
    meta = _group_meta(group, names_in_group, contrib_nhm, is_hru)
    if meta is None or not set(meta["obsnme"]).issubset(td.sim_ens_prior.columns):
        return None
    return _aggregate(td.sim_ens_prior, meta)


def obs_base_and_band(obs_ens_df: pd.DataFrame) -> pd.DataFrame:
    """Frame indexed by x with ``base`` and the 5th/95th percentiles (``p05``/``p95``)
    taken across obs+noise realizations. ``base`` falls back to the median when
    the ensemble has no ``base`` member."""
    out = pd.DataFrame(index=obs_ens_df.index)
    out["p05"] = obs_ens_df.quantile(0.05, axis=1)
    out["p95"] = obs_ens_df.quantile(0.95, axis=1)
    out["base"] = (obs_ens_df["base"] if "base" in obs_ens_df.columns
                   else obs_ens_df.median(axis=1))
    return out


def overlap_metrics(obs_ens_df: pd.DataFrame, sim_ens_df: pd.DataFrame) -> dict:
    """Two per-group observed-vs-simulated overlap metrics, each a mean over the
    group's valid points (points where both the observed and simulated 5-95%
    bands are defined).

    Both use the observed 5-95% band ``[obs_p05, obs_p95]`` as the reference.

    * ``band_overlap`` -- metric (a): the fraction of the SIMULATED 5-95% band
      that lies inside the observed band,
      ``len([sim_p05,sim_p95] ∩ [obs_p05,obs_p95]) / len([sim_p05,sim_p95])``.
    * ``member_overlap`` -- metric (d): the fraction of individual simulated
      ensemble members whose value falls inside the observed band, averaged
      over members then over points.

    Inputs are the gage-aggregated ensembles indexed by x (time); columns are
    realizations. Returns ``{"band_overlap": float|nan, "member_overlap":
    float|nan, "n_points": int}`` with the two fractions as percentages (0-100).
    """
    out = {"band_overlap": float("nan"), "member_overlap": float("nan"), "n_points": 0}
    if obs_ens_df is None or sim_ens_df is None or obs_ens_df.empty or sim_ens_df.empty:
        return out
    # align on common x (time) points
    common = obs_ens_df.index.intersection(sim_ens_df.index)
    if len(common) == 0:
        return out
    o = obs_ens_df.loc[common]
    s = sim_ens_df.loc[common]
    o_p05 = o.quantile(0.05, axis=1)
    o_p95 = o.quantile(0.95, axis=1)
    s_p05 = s.quantile(0.05, axis=1)
    s_p95 = s.quantile(0.95, axis=1)

    # valid points: both bands finite and positive-width observed band
    valid = (o_p05.notna() & o_p95.notna() & s_p05.notna() & s_p95.notna()
             & (o_p95 > o_p05) & (s_p95 >= s_p05))
    if not valid.any():
        return out
    o_lo, o_hi = o_p05[valid], o_p95[valid]
    s_lo, s_hi = s_p05[valid], s_p95[valid]

    # (a) fraction of the sim band inside the obs band
    inter = (np.minimum(o_hi, s_hi) - np.maximum(o_lo, s_lo)).clip(lower=0)
    sim_w = (s_hi - s_lo)
    # where the sim band has zero width, it either sits inside (1) or outside (0)
    band_frac = np.where(sim_w > 0, inter / sim_w.where(sim_w > 0, other=np.nan),
                         ((s_lo >= o_lo) & (s_lo <= o_hi)).astype(float))
    band_frac = pd.Series(band_frac, index=o_lo.index)

    # (d) fraction of sim members inside the obs band, per point
    sim_vals = s.loc[valid]
    inside = sim_vals.ge(o_lo, axis=0) & sim_vals.le(o_hi, axis=0)
    member_frac = inside.mean(axis=1)  # over members, per point

    out["band_overlap"] = float(band_frac.mean() * 100.0)
    out["member_overlap"] = float(member_frac.mean() * 100.0)
    out["n_points"] = int(valid.sum())
    return out


def _gap_breaks(index, group: str) -> np.ndarray:
    """Boolean mask over ``index`` marking the first point of a new segment.

    Calibration targets cover odd (calibration) water years only, so there is a
    hole wherever two consecutive observations are more than one natural step
    apart (the validation-year gaps). Marking those points lets the base line,
    the percentile lines, and the gray band break across the gap instead of
    drawing a straight segment over the missing years. The mean-monthly
    climatology groups (1-12) and the annual groups have no internal gap step,
    so they never break.
    """
    idx = list(index)
    breaks = np.zeros(len(idx), dtype=bool)
    if len(idx) < 2:
        return breaks
    # Integer x (month climatology, year labels): a step > 1 is a gap. For the
    # 1-12 climatology there is no meaningful gap, but a >1 jump there is still
    # harmless to break on; annual labels are 2 apart (odd years) so they would
    # all break -- which is correct, each annual point stands alone.
    if group in ("actet_mean_mon", "soil_moist_mean_mon", "streamflow_mean_mon"):
        return breaks  # dense 1..12 climatology: never break
    if group in ("recharge_ann", "soil_moist_ann"):
        step = 1  # consecutive calendar years; odd-only -> every point breaks
    elif group in ("runoff_mon", "streamflow_mon"):
        step = pd.Timedelta(days=32)          # one month (slack for 28-31 day months)
    elif group == "swe_monthly":
        step = pd.Timedelta(days=32)
    elif group.startswith("streamflow_5day"):
        step = pd.Timedelta(days=6)           # one 5-day bin (slack of 1 day)
    else:
        return breaks
    for i in range(1, len(idx)):
        if isinstance(step, pd.Timedelta):
            gap = (pd.Timestamp(idx[i]) - pd.Timestamp(idx[i - 1])) > step
        else:
            gap = (idx[i] - idx[i - 1]) > step
        breaks[i] = bool(gap)
    return breaks


def _segments(frame: pd.DataFrame, group: str):
    """Yield contiguous (no-gap) sub-frames of ``frame`` (indexed by x, sorted)."""
    frame = frame.sort_index()
    breaks = _gap_breaks(frame.index, group)
    start = 0
    for i in range(1, len(frame) + 1):
        if i == len(frame) or breaks[i]:
            yield frame.iloc[start:i]
            start = i


def _point_halfwidth(group: str, xs):
    """Half-width (in x units) of the shaded rectangle drawn at an isolated
    point. Annual groups use integer year x (half-width ~0.35 yr); dated groups
    use a timedelta sized to the group's bin so rectangles stay legible but do
    not overlap neighbours."""
    if group in ("recharge_ann", "soil_moist_ann",
                 "actet_mean_mon", "soil_moist_mean_mon", "streamflow_mean_mon"):
        return 0.35  # integer x (year or month)
    if group.startswith("streamflow_5day"):
        return pd.Timedelta(days=2)
    return pd.Timedelta(days=12)  # monthly groups


def _add_point_rectangles(fig, pts: pd.DataFrame, lo_col: str, hi_col: str,
                          group: str, fillcolor: str, linecolor: str,
                          legendgroup: str, name: str, showlegend: bool) -> bool:
    """Draw a filled rectangle from ``lo_col`` to ``hi_col`` at each isolated
    point, so the 5-95% range reads as a shaded bar (and observed vs sim
    rectangles visibly overlap). Returns True if anything was drawn.

    All rectangles share one trace (NaN-separated polygons) so they collapse to
    a single legend entry / toggle, matching the band legend groups.
    """
    pts = pts[pts[[lo_col, hi_col]].notna().all(axis=1)]
    if pts.empty:
        return False
    hw = _point_halfwidth(group, list(pts.index))
    xs, ys = [], []
    for x, row in pts.iterrows():
        x0, x1 = x - hw, x + hw
        lo, hi = row[lo_col], row[hi_col]
        xs += [x0, x1, x1, x0, x0, None]       # close each rect; None breaks to next
        ys += [lo, lo, hi, hi, lo, None]
    fig.add_trace(go.Scatter(
        x=xs, y=ys, fill="toself", fillcolor=fillcolor,
        mode="lines", line=dict(width=0, color=linecolor),
        hoverinfo="skip", legendgroup=legendgroup, name=name,
        showlegend=showlegend))
    return True


def add_observed_band(fig: go.Figure, ow: pd.DataFrame, group: str,
                      marker_symbol: str = "circle", legend_label: str = "observed",
                      show_band_legend: bool = True, draw_dots: bool = True) -> None:
    """Draw the observed display: thick black base line + dots, thin p05/p95
    lines, and a gray fill between them, all broken at calibration-year gaps.

    ``ow`` is indexed by x with columns ``base``, ``p05``, ``p95``. The gray
    band and all three lines break wherever :func:`_gap_breaks` finds a hole, so
    nothing is drawn across the missing validation years. Markers use
    ``marker_symbol`` (black), which the 5-day plot varies per signature group.
    """
    ow = ow.dropna(subset=["base"]).sort_index()
    if ow.empty:
        return
    band_shown = False
    singles = []  # isolated points get a vertical p05-p95 whisker instead of a band
    for seg in _segments(ow, group):
        # A line or a filled band needs at least two points. Isolated
        # single-point calibration blocks (one bin flanked by gaps) would
        # otherwise emit a degenerate zero-width polygon / stray sliver -- the
        # artifact. Each is drawn as a vertical whisker below so the 5-95% range
        # still shows; the base value shows via the dots trace.
        if len(seg) < 2:
            singles.append(seg.iloc[0])
            continue
        x = list(seg.index)
        b = seg[seg[["p05", "p95"]].notna().all(axis=1)]
        # gray 5-95% band (fill between p95 going out and p05 coming back)
        if len(b) >= 2:
            fig.add_trace(go.Scatter(
                x=list(b.index) + list(b.index)[::-1],
                y=list(b["p95"].values) + list(b["p05"].values)[::-1],
                fill="toself", fillcolor="rgba(130,130,130,0.25)",
                # mode='lines' (no markers) so the legend swatch is a line/fill
                # patch, not a dot; the color keeps the swatch gray instead of
                # Plotly's default color cycle.
                mode="lines", line=dict(width=0, color="rgba(130,130,130,0.6)"),
                hoverinfo="skip",
                legendgroup="obs_band", name="observed 5-95% range",
                showlegend=(show_band_legend and not band_shown)))
            band_shown = True
        # thin percentile lines
        for col in ("p05", "p95"):
            fig.add_trace(go.Scatter(
                x=x, y=seg[col].values, mode="lines",
                line=dict(color="rgba(80,80,80,0.9)", width=0.8),
                legendgroup="obs_band", showlegend=False, hoverinfo="skip"))
        # thick black base line
        fig.add_trace(go.Scatter(
            x=x, y=seg["base"].values, mode="lines",
            line=dict(color="black", width=2.4),
            legendgroup="obs_base", showlegend=False, hoverinfo="skip"))
    # Isolated points (e.g. the annual groups) can't form a band, so draw a
    # shaded p05-p95 rectangle at each. Gray to match the band theme; it shares
    # the obs_band legend group so one legend toggle controls band + rectangles.
    sdf = pd.DataFrame(singles)
    if not sdf.empty and _add_point_rectangles(
            fig, sdf, "p05", "p95", group,
            fillcolor="rgba(130,130,130,0.25)", linecolor="rgba(130,130,130,0.6)",
            legendgroup="obs_band", name="observed 5-95% range",
            showlegend=(show_band_legend and not band_shown)):
        band_shown = True
    # base dots (one trace over all segments; gaps need no break for markers).
    # The 5-day plot draws its own per-signature-group shape dots instead, so it
    # passes draw_dots=False.
    if draw_dots:
        fig.add_trace(go.Scatter(
            x=list(ow.index), y=ow["base"].values, mode="markers",
            name=legend_label, legendgroup="obs_base",
            marker=dict(color="black", size=6, symbol=marker_symbol)))


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def _add_overlap_annotation(fig: go.Figure, obs_ens_df, sim_ens_df,
                            xref: str = "paper", yref: str = "paper") -> dict:
    """Compute the two overlap metrics and stamp them in a box in the top-left
    of the plot (or of one subplot, via ``xref="x2 domain"`` / ``yref="y2 domain"``).
    Returns the metrics dict (also for callers that tabulate)."""
    m = overlap_metrics(obs_ens_df, sim_ens_df)
    if m["n_points"] == 0 or not np.isfinite(m["band_overlap"]):
        return m
    fig.add_annotation(
        xref=xref, yref=yref, x=0.01, y=0.99, xanchor="left", yanchor="top",
        showarrow=False, align="left",
        bordercolor="rgba(80,80,80,0.6)", borderwidth=1, borderpad=4,
        bgcolor="rgba(255,255,255,0.75)", font=dict(size=11),
        text=(f"5-95% band overlap: {m['band_overlap']:.0f}%<br>"
              f"ensemble member overlap: {m['member_overlap']:.0f}%<br>"
              f"<span style='color:#888'>n = {m['n_points']} points</span>"),
    )
    return m


def build_group_figure(gage, group, sim_df, obs_ens_df, realizations,
                       sim_ens_df=None, x_title=None, y_title=None) -> go.Figure:
    """Observed band (black base line+dots, p05/p95 lines, gray fill) and the
    simulated red lines + 5-95% band for one group. Everything breaks at the
    calibration-year gaps. An overlap-metric box is stamped top-left.
    ``realizations`` is accepted for signature compatibility but no longer used
    (random members were dropped)."""
    fig = go.Figure()
    add_observed_band(fig, obs_base_and_band(obs_ens_df), group,
                      legend_label="observed (base; 5-95% band)")
    add_sim_traces(fig, sim_df, group, sim_ens_df)
    _add_overlap_annotation(fig, obs_ens_df, sim_ens_df)

    fig.update_layout(
        title=f"{group} &mdash; gage {gage}  (obs vs sim)",
        xaxis_title=x_title if x_title is not None else X_TITLE.get(group, "time"),
        yaxis_title=y_title if y_title is not None else Y_TITLE.get(group, group),
        height=560, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0),
        margin=dict(t=80, r=30, l=80, b=50), hovermode="x unified",
    )
    return fig


def add_sim_traces(fig: go.Figure, sim_df: pd.DataFrame, group: str,
                   sim_ens_df: pd.DataFrame = None) -> None:
    """Simulated display, in red, broken at calibration gaps:

    * ``starting`` (iteration-0 base) as a dashed line,
    * ``base`` (final-iteration base) as a solid line,
    * the final-iteration ensemble 5th/95th percentiles as thin lines with a
      translucent red fill between them.

    Each is a separate legend entry so it can be toggled on and off.
    """
    # simulated 5-95% band from the final-iteration ensemble
    if sim_ens_df is not None and not sim_ens_df.empty:
        sb = pd.DataFrame(index=sim_ens_df.index)
        sb["p05"] = sim_ens_df.quantile(0.05, axis=1)
        sb["p95"] = sim_ens_df.quantile(0.95, axis=1)
        sb["mid"] = (sb["p05"] + sb["p95"]) / 2.0
        sb = sb.dropna(how="all").sort_index()
        band_shown = False
        sim_singles = []  # isolated points -> vertical whisker
        for seg in _segments(sb, group):
            b = seg[seg[["p05", "p95"]].notna().all(axis=1)]
            if len(b) < 2:  # need >=2 points for a filled band / line
                if len(b) == 1:
                    sim_singles.append(b.iloc[0])
                continue
            fig.add_trace(go.Scatter(
                x=list(b.index) + list(b.index)[::-1],
                y=list(b["p95"].values) + list(b["p05"].values)[::-1],
                fill="toself", fillcolor="rgba(214,39,40,0.18)",
                # mode='lines' (no markers) so the legend swatch is a line/fill
                # patch, not a dot; the color keeps the swatch red instead of
                # Plotly's default color cycle.
                mode="lines", line=dict(width=0, color="rgba(214,39,40,0.6)"),
                hoverinfo="skip",
                legendgroup="sim_band", name="sim 5-95% range",
                showlegend=not band_shown))
            band_shown = True
            for col in ("p05", "p95"):
                fig.add_trace(go.Scatter(
                    x=list(b.index), y=b[col].values, mode="lines",
                    line=dict(color="rgba(214,39,40,0.7)", width=0.8),
                    legendgroup="sim_band", showlegend=False, hoverinfo="skip"))

        # Isolated points (e.g. annual groups) get a shaded p05-p95 rectangle,
        # red to match the sim band theme, sharing the sim_band legend group.
        # Drawn slightly narrower than the observed rectangle so an overlapping
        # pair stays distinguishable where sim and obs ranges coincide.
        ssdf = pd.DataFrame(sim_singles)
        if not ssdf.empty and _add_point_rectangles(
                fig, ssdf, "p05", "p95", group,
                fillcolor="rgba(214,39,40,0.22)", linecolor="rgba(214,39,40,0.6)",
                legendgroup="sim_band", name="sim 5-95% range",
                showlegend=not band_shown):
            band_shown = True

    # base (solid) and starting (dashed) red lines, broken at gaps. A single
    # isolated point (e.g. the annual groups, whose odd-year points are each
    # 2 years apart and so always stand alone) can't be a line, so it is drawn
    # as a marker instead -- otherwise the sim value would be invisible.
    marker_symbol = {"base": "circle", "starting": "circle-open"}
    for label, dash, width in (("base", "solid", 2.2), ("starting", "dash", 1.8)):
        if label not in sim_df.columns:
            continue
        s = sim_df[[label]].dropna().rename(columns={label: "v"}).sort_index()
        shown = False
        singletons = []
        for seg in _segments(s, group):
            if len(seg) < 2:
                singletons.append((seg.index[0], seg["v"].iloc[0]))
                continue
            fig.add_trace(go.Scatter(
                x=list(seg.index), y=seg["v"].values, mode="lines",
                name=f"sim {label}", legendgroup=f"sim_{label}",
                showlegend=not shown,
                line=dict(color="#d62728", width=width, dash=dash)))
            shown = True
        if singletons:
            xs, ys = zip(*singletons)
            fig.add_trace(go.Scatter(
                x=list(xs), y=list(ys), mode="markers",
                name=f"sim {label}", legendgroup=f"sim_{label}",
                showlegend=not shown,
                marker=dict(color="#d62728", size=6,
                            symbol=marker_symbol[label])))


def _fiveday_panel(sim_df, obs_ens_df, x_group, sim_ens_df=None) -> go.Figure:
    """Traces for ONE 5-day streamflow panel (no layout, no overlap box).

    The observed base line, 5-95% band and percentile lines span the whole
    record (one continuous observed series, broken only at calibration-year
    gaps). The base DOTS use a distinct black marker shape per signature group
    (``x_group`` maps each x/date to its group), so the signatures are
    distinguishable without color. The simulated red lines and 5-95% band are
    the same as every other plot.
    """
    fig = go.Figure()
    ow = obs_base_and_band(obs_ens_df).dropna(subset=["base"]).sort_index()

    # Band + base/percentile lines across the full record; the per-group shape
    # dots below replace the single base-dot trace, so draw_dots=False here.
    add_observed_band(fig, ow, "streamflow_5day", draw_dots=False)

    # Overlay per-group base dots with distinct black marker shapes.
    grp = pd.Series(x_group)
    ow = ow.assign(group=grp.reindex(ow.index).values)
    present = [g for g in ow["group"].dropna().unique()]
    known = [g for g in FIVEDAY_MARKERS if g in present]
    others = sorted(g for g in present if g not in FIVEDAY_MARKERS)
    for i, g in enumerate(known + others):
        sub = ow[ow["group"] == g]
        symbol = FIVEDAY_MARKERS.get(g) or _FALLBACK_MARKERS[i % len(_FALLBACK_MARKERS)]
        fig.add_trace(go.Scatter(
            x=sub.index, y=sub["base"].values, mode="markers",
            name=f"observed {g.replace('streamflow_5day_', '')}",
            legendgroup=f"obs_{g}",
            marker=dict(color="black", size=7, symbol=symbol)))

    add_sim_traces(fig, sim_df, "streamflow_5day", sim_ens_df)
    return fig


def build_fiveday_figure(gage, sim_df, obs_ens_df, x_group, realizations,
                         sim_ens_df=None, sim_ens_prior_df=None,
                         iteration=None) -> go.Figure:
    """Combined 5-day streamflow plot: every signature group on one time axis.

    With ``sim_ens_prior_df`` (the iteration-0 ensemble aggregated to this gage)
    the figure is a STACK of two panels sharing the x and y axes:

    * top    -- the PRIOR: same style as the bottom, but the simulated solid
      line is the iteration-0 ``base`` (``sim_df["starting"]``) and the red band
      is the iteration-0 ensemble 5-95% range;
    * bottom -- the CALIBRATED plot (final-iteration ``base``, the dashed
      ``starting`` line, and the final-iteration ensemble band).

    The observed series is identical in both panels. Without
    ``sim_ens_prior_df`` (an older archive) only the calibrated plot is drawn.
    Each panel carries its own overlap-metric box. ``realizations`` is accepted
    for signature compatibility but no longer used.
    """
    calibrated = _fiveday_panel(sim_df, obs_ens_df, x_group, sim_ens_df)
    final_label = "calibrated" + (f" (iteration {iteration})" if iteration is not None else "")

    if sim_ens_prior_df is None or sim_ens_prior_df.empty:
        fig = calibrated
        _add_overlap_annotation(fig, obs_ens_df, sim_ens_df)
        fig.update_layout(
            title=f"5-day streamflow &mdash; gage {gage}  "
                  f"(obs vs sim; observed marker shape = signature group)",
            xaxis_title="date", yaxis_title="streamflow (cfs)",
            height=560, template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0),
            margin=dict(t=80, r=30, l=80, b=50), hovermode="x unified",
        )
        return fig

    # Prior panel: its "base" is the iteration-0 base, drawn solid like the
    # calibrated base. The dashed "starting" line would just repeat it, so it is
    # dropped here.
    prior_sim = (sim_df[["starting"]].rename(columns={"starting": "base"})
                 if "starting" in sim_df.columns
                 else sim_df.iloc[:, :0])
    prior = _fiveday_panel(prior_sim, obs_ens_df, x_group, sim_ens_prior_df)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.07,
        subplot_titles=("prior (iteration 0)", final_label),
    )
    for tr in prior.data:
        # Observed traces share legend groups with the lower panel so toggling
        # one legend entry hides it in both. Simulated traces get their own
        # group and no legend entry: their meaning differs between panels
        # ("sim base" below is the calibrated base), and the panel titles say
        # which is which.
        lg = tr.legendgroup or ""
        if lg.startswith("sim_"):
            tr.legendgroup = lg + "_prior"
        tr.showlegend = False
        fig.add_trace(tr, row=1, col=1)
    for tr in calibrated.data:
        fig.add_trace(tr, row=2, col=1)

    _add_overlap_annotation(fig, obs_ens_df, sim_ens_prior_df,
                            xref="x domain", yref="y domain")
    _add_overlap_annotation(fig, obs_ens_df, sim_ens_df,
                            xref="x2 domain", yref="y2 domain")

    fig.update_layout(
        title=f"5-day streamflow &mdash; gage {gage}  "
              f"(obs vs sim, prior above / calibrated below; "
              f"observed marker shape = signature group)",
        height=980, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0),
        margin=dict(t=100, r=30, l=80, b=50), hovermode="x unified",
    )
    fig.update_yaxes(title_text="streamflow (cfs)", row=1, col=1)
    # Same y scale in both panels (zooming one zooms the other), so the prior
    # and calibrated fits can be compared directly against the same observations.
    fig.update_yaxes(title_text="streamflow (cfs)", matches="y", row=2, col=1)
    fig.update_xaxes(title_text="date", row=2, col=1)
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


def iter_gage_plot_data(td: TargetData, gage, params, nhm_id):
    """Yield ``(plot_key, sim_df, obs_ens_df, sim_ens_df, x_group, prior_ens_df)``
    for each plot of one gage. ``x_group`` and ``prior_ens_df`` (the iteration-0
    ensemble) are only set for the 5-day plot (else None).

    Shared by :func:`build_gage_figures` and :func:`collect_overlap_metrics` so
    the group/pool selection and aggregation live in one place.
    """
    pos, _ = contributing_hru_positions(gage, params)
    contrib_nhm = [int(nhm_id[p]) for p in pos]

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
        sim_df, obs_df, sim_ens_df = aggregate_group_for_gage(
            td, group, names, contrib_nhm, is_hru)
        if sim_df is None or sim_df.dropna(how="all").empty:
            continue
        yield group, sim_df, obs_df, sim_ens_df, None, None

    # All 5-day signature groups for this gage, together in one plot.
    sub_groups = [g for g in td.obgnme.unique()
                  if g.startswith("streamflow_5day") and g not in SKIP_GROUPS]
    pool = [n for n in td.obgnme[td.obgnme.isin(sub_groups)].index
            if n.split(":")[-1] == str(gage)]
    if pool:
        sim_df, obs_df, sim_ens_df = aggregate_group_for_gage(
            td, "streamflow_5day", pool, contrib_nhm, is_hru=False)
        if sim_df is not None and not sim_df.dropna(how="all").empty:
            # each (gage, date) has exactly one name, so x -> group is unambiguous
            x_group = {}
            for nm in pool:
                key, _ = parse_key_and_tail("streamflow_5day", nm)
                if key is not None:
                    x_group[time_key_to_x("streamflow_5day", key)] = td.obgnme[nm]
            prior_ens_df = aggregate_prior_ensemble(
                td, "streamflow_5day", pool, contrib_nhm, is_hru=False)
            yield FIVEDAY_KEY, sim_df, obs_df, sim_ens_df, x_group, prior_ens_df


def build_gage_figures(td: TargetData, gage, params, nhm_id) -> dict:
    """All figures for one gage, as ``{plot key: Figure}``.

    Keys are the HRU / monthly-streamflow group names, plus ``streamflow_5day``
    for the combined 5-day plot.
    """
    figs = {}
    for key, sim_df, obs_df, sim_ens_df, x_group, prior_ens_df in iter_gage_plot_data(
            td, gage, params, nhm_id):
        if key == FIVEDAY_KEY:
            figs[key] = build_fiveday_figure(
                gage, sim_df, obs_df, x_group, td.realizations,
                sim_ens_df=sim_ens_df, sim_ens_prior_df=prior_ens_df,
                iteration=td.final_iteration)
        else:
            figs[key] = build_group_figure(
                gage, key, sim_df, obs_df, td.realizations, sim_ens_df=sim_ens_df)
    return figs


# The combined 5-day plot is broken out in the metrics TABLE into low- and
# high-flow rows, matching the phi-factor substring patterns used to re-weight
# them: "_low" (low + ex_low) vs "scnd" (the pulse/small/large ascending and
# descending signatures). The on-plot figure stays combined.
FIVEDAY_TABLE_BUCKETS = [
    ("streamflow_5day_low", "_low"),
    ("streamflow_5day_high", "scnd"),
]


def _metric_row(gage, group, obs_ens_df, sim_ens_df):
    m = overlap_metrics(obs_ens_df, sim_ens_df)
    return {
        "gage": str(gage), "group": group, "n_points": m["n_points"],
        "band_overlap_pct": round(m["band_overlap"], 1)
        if np.isfinite(m["band_overlap"]) else np.nan,
        "member_overlap_pct": round(m["member_overlap"], 1)
        if np.isfinite(m["member_overlap"]) else np.nan,
    }


def collect_overlap_metrics(td: TargetData, params, gages) -> pd.DataFrame:
    """Overlap metrics for every gage x plot group, as a tidy DataFrame.

    Columns: ``gage``, ``group``, ``n_points``, ``band_overlap_pct`` (metric a),
    ``member_overlap_pct`` (metric d). One row per gage x group that has data.
    The combined 5-day plot is split here into ``streamflow_5day_low`` and
    ``streamflow_5day_high`` rows (the plot itself stays combined).
    """
    nhm_id = [int(x) for x in np.asarray(params["nhm_id"])]
    rows = []
    for gage in gages:
        for key, _sim, obs_ens_df, sim_ens_df, x_group, _prior in iter_gage_plot_data(
                td, gage, params, nhm_id):
            if key == FIVEDAY_KEY and x_group:
                # split the aggregated ensembles by date into low / high buckets
                xg = pd.Series(x_group)  # x (date) -> signature obgnme
                for row_group, pattern in FIVEDAY_TABLE_BUCKETS:
                    xs = xg[xg.str.contains(pattern, na=False)].index
                    o = obs_ens_df.loc[obs_ens_df.index.intersection(xs)]
                    s = (sim_ens_df.loc[sim_ens_df.index.intersection(xs)]
                         if sim_ens_df is not None else None)
                    if o.empty:
                        continue
                    rows.append(_metric_row(gage, row_group, o, s))
            else:
                rows.append(_metric_row(gage, key, obs_ens_df, sim_ens_df))
    return pd.DataFrame(rows, columns=[
        "gage", "group", "n_points", "band_overlap_pct", "member_overlap_pct"])


METRICS_CSV = "overlap_metrics.csv"


def plot_calibration_evaluation(td: TargetData, params, out_dir, gages) -> dict:
    """Write one HTML per gage per target group, plus an overlap-metrics CSV.

    Layout: ``<out_dir>/<gage>/calib_eval_<key>_<gage>.html`` and
    ``<out_dir>/overlap_metrics.csv``. Returns ``{gage: [paths]}`` (the per-gage
    HTML paths; the CSV path is ``out_dir / METRICS_CSV``).
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
    # Overlap-metrics summary table across all gages x groups.
    metrics = collect_overlap_metrics(td, params, gages)
    metrics.to_csv(out_dir / METRICS_CSV, index=False)
    return written
