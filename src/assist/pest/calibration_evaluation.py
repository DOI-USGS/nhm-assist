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
      simulated ensemble, for the simulated 5-95% band and the change-in-KGE metric.
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
    # obs-name order. Drives the simulated 5-95% band and the change-in-KGE metric.
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


# --------------------------------------------------------------------------- #
# Change-in-KGE metric (5-day streamflow, continuous monthly series)
# --------------------------------------------------------------------------- #
# The 5-day points are averaged to one value per month-year (Oct 1980, Nov
# 1980, ...). A month-year is kept only if it has at least
# DKGE_MIN_POINTS_PER_MONTH valid 5-day points (a month holds about 6), and a
# series is scored only if at least DKGE_MIN_MONTHS month-years are kept.
DKGE_MIN_POINTS_PER_MONTH = 3
DKGE_MIN_MONTHS = 12
DKGE_ALTERNATIVE = "two-sided"   # Wilcoxon alternative: two-sided | greater | less
KGE_COMPONENTS = ["KGE", "r", "alpha", "beta"]


def kge_components(obs, sim) -> dict:
    """Gupta et al. (2009) Kling-Gupta efficiency and its three components.

    ``KGE = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2)`` with ``r`` the
    Pearson correlation, ``alpha = std(sim)/std(obs)`` and
    ``beta = mean(sim)/mean(obs)``. Only points finite in BOTH series are used.
    Every value is NaN when fewer than 3 points remain or when the observed
    mean, or either standard deviation, is zero.
    """
    nan = {k: float("nan") for k in KGE_COMPONENTS}
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    ok = np.isfinite(obs) & np.isfinite(sim)
    obs, sim = obs[ok], sim[ok]
    if obs.size < 3:
        return nan
    mo, ms = obs.mean(), sim.mean()
    so, ss = obs.std(), sim.std()
    if mo == 0 or so == 0 or ss == 0:
        return nan
    r = float(np.corrcoef(obs, sim)[0, 1])
    alpha, beta = float(ss / so), float(ms / mo)
    kge = float(1.0 - np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2))
    return {"KGE": kge, "r": r, "alpha": alpha, "beta": beta}


def kge_2009(obs, sim) -> float:
    """Gupta et al. (2009) KGE only; see :func:`kge_components`."""
    return kge_components(obs, sim)["KGE"]


def pbias_pct(obs, sim) -> float:
    """Percent bias, ``100 * sum(obs - sim) / sum(obs)``, on the points finite
    in both series. Same sign convention as ``hydroeval.pbias`` (used in the
    streamflow statistics table of notebook 6): **positive means the model
    under-predicts** (simulated volume too low), negative means it
    over-predicts. NaN when fewer than 3 points remain or the observed sum is
    zero."""
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    ok = np.isfinite(obs) & np.isfinite(sim)
    obs, sim = obs[ok], sim[ok]
    if obs.size < 3 or obs.sum() == 0:
        return float("nan")
    return float(100.0 * (obs - sim).sum() / obs.sum())


def _empty_dkge() -> dict:
    nan = float("nan")
    empty = pd.Series(dtype=float)
    return {"dkge": empty, "kge_final": empty, "kge_prior_base": nan,
            "median_dkge": nan, "base_dkge": nan, "base_kge_final": nan,
            "base_kge_prior": nan, "base_percentile": nan,
            "pbias_final": empty, "pbias_prior": empty, "median_pbias": nan,
            "base_pbias_final": nan, "base_pbias_prior": nan,
            "n_members": 0, "n_months": 0,
            "components_base": pd.DataFrame(index=KGE_COMPONENTS,
                                            columns=["prior", "final"], dtype=float),
            "monthly_base": pd.DataFrame(columns=["obs", "prior", "final", "n_points"])}


def _set_pbias(out: dict, bf: pd.Series, bp: pd.Series) -> None:
    """Store per-member PBIAS (final, and the prior base on each member's
    points) and the base realization's values in a result dict."""
    ids = [i for i in bf.index if i != "base"]
    out["pbias_final"] = bf.loc[ids]
    out["pbias_prior"] = bp.loc[ids]
    ens = bf.loc[ids].dropna()
    out["median_pbias"] = float(ens.median()) if len(ens) else float("nan")
    if "base" in bf.index:
        out["base_pbias_final"] = float(bf["base"])
        out["base_pbias_prior"] = float(bp["base"])


def delta_kge(obs_ens_df: pd.DataFrame, sim_ens_df: pd.DataFrame,
              prior_base: pd.Series,
              min_points_per_month: int = DKGE_MIN_POINTS_PER_MONTH,
              min_months: int = DKGE_MIN_MONTHS) -> dict:
    """Change in monthly KGE (final minus prior base) for a gage's 5-day streamflow.

    Inputs are the gage-aggregated 5-day series indexed by date. ``obs_ens_df``
    and ``sim_ens_df`` have realizations as columns (the observed reference is
    its ``base`` column, or the median if there is none); ``prior_base`` is the
    iteration-0 ``base`` simulation (the ``starting`` column of the gage's sim
    frame), the single pre-calibration model every change is measured from.

    The score is the **continuous monthly KGE**, computed separately for each
    final-ensemble member:

    1. keep the 5-day dates where the observation, the member and the prior
       base are all finite, so the member and the prior are scored on exactly
       the same points;
    2. average those points to one value per month-year (observed, member and
       prior alike), dropping month-years with fewer than
       ``min_points_per_month`` points;
    3. line the monthly means up in time (one series across all the
       calibration years) and compute one 2009 KGE (:func:`kge_components`) for
       the member and one for the prior base against the observed series;
    4. ``dkge = KGE(member) - KGE(prior base)``.

    A member with fewer than ``min_months`` month-years gets NaN. Positive
    ``dkge`` means calibration improved the fit. The ``base`` realization's
    ``base_dkge`` is ``KGE(final base) - KGE(prior base)``; it is NOT part of the
    ensemble distribution, and ``base_percentile`` is the percent of the other
    members whose ``dkge`` is at or below it.

    Returns a dict: ``dkge`` / ``kge_final`` (Series by member, base excluded),
    ``kge_prior_base``, ``median_dkge`` (over members), ``base_dkge``,
    ``base_kge_final``, ``base_kge_prior``, ``base_percentile`` (0-100),
    ``n_members``, ``n_months`` (month-years scored for the base),
    ``pbias_final`` / ``pbias_prior`` (Series by member: PBIAS of the member
    and of the prior base on that member's monthly series, see
    :func:`pbias_pct`), ``median_pbias``, ``base_pbias_final``,
    ``base_pbias_prior``, ``components_base`` (``KGE``/``r``/``alpha``/``beta`` x ``prior``/``final``
    for the base) and ``monthly_base`` (the base's scored monthly series:
    ``obs``, ``prior``, ``final``, ``n_points``, indexed by month start).
    """
    out = _empty_dkge()
    if (obs_ens_df is None or sim_ens_df is None or prior_base is None
            or obs_ens_df.empty or sim_ens_df.empty or len(prior_base) == 0):
        return out
    obs = (obs_ens_df["base"] if "base" in obs_ens_df.columns
           else obs_ens_df.median(axis=1)).dropna()
    prior = prior_base.dropna()
    dates = obs.index.intersection(sim_ens_df.index).intersection(prior.index).sort_values()
    if len(dates) == 0:
        return out
    members = list(sim_ens_df.columns)
    o = obs.loc[dates].to_numpy(dtype=float)
    p = prior.loc[dates].to_numpy(dtype=float)
    f = sim_ens_df.loc[dates, members].to_numpy(dtype=float)

    # Step 1: one validity mask per member (obs, member and prior all finite).
    ok = np.isfinite(f) & np.isfinite(o)[:, None] & np.isfinite(p)[:, None]
    month_year = pd.DatetimeIndex(dates).to_period("M")

    # Step 2: monthly means of the masked points, and the points per month-year.
    def _monthly(values):
        masked = pd.DataFrame(np.where(ok, values, np.nan), index=dates, columns=members)
        return masked.groupby(month_year).mean()

    n_pts = pd.DataFrame(ok.astype(int), index=dates, columns=members).groupby(month_year).sum()
    keep = n_pts >= int(min_points_per_month)
    o_m = _monthly(np.repeat(o[:, None], len(members), axis=1)).where(keep)
    p_m = _monthly(np.repeat(p[:, None], len(members), axis=1)).where(keep)
    f_m = _monthly(f).where(keep)
    n_months = keep.sum(axis=0)

    # Step 3: one KGE per member and one for the prior base on the same months.
    # PBIAS is computed on the same monthly series alongside it.
    kf, kp, comp, bf, bp = {}, {}, {}, {}, {}
    for m in members:
        if n_months[m] < int(min_months):
            kf[m] = kp[m] = bf[m] = bp[m] = float("nan")
            continue
        cf = kge_components(o_m[m], f_m[m])
        cp = kge_components(o_m[m], p_m[m])
        kf[m], kp[m] = cf["KGE"], cp["KGE"]
        bf[m], bp[m] = pbias_pct(o_m[m], f_m[m]), pbias_pct(o_m[m], p_m[m])
        if m == "base":
            comp = {"prior": cp, "final": cf}
    kf, kp = pd.Series(kf, dtype=float), pd.Series(kp, dtype=float)
    _set_pbias(out, pd.Series(bf, dtype=float), pd.Series(bp, dtype=float))

    # Step 4: change from the prior base.
    dk = kf - kp
    ens_ids = [i for i in dk.index if i != "base"]
    ens = dk.loc[ens_ids].dropna()

    out["dkge"] = dk.loc[ens_ids]
    out["kge_final"] = kf.loc[ens_ids]
    out["median_dkge"] = float(ens.median()) if len(ens) else float("nan")
    out["n_members"] = int(len(ens))
    if "base" in dk.index and np.isfinite(dk["base"]):
        out["base_dkge"] = float(dk["base"])
        out["base_kge_final"] = float(kf["base"])
        out["base_kge_prior"] = float(kp["base"])
        out["kge_prior_base"] = float(kp["base"])
        out["n_months"] = int(n_months["base"])
        out["components_base"] = pd.DataFrame(comp).reindex(KGE_COMPONENTS)
        mb = pd.DataFrame({"obs": o_m["base"], "prior": p_m["base"],
                           "final": f_m["base"], "n_points": n_pts["base"]})
        mb = mb[keep["base"]]
        mb.index = mb.index.to_timestamp()
        mb.index.name = "month"
        out["monthly_base"] = mb
        if len(ens):
            out["base_percentile"] = float((ens <= dk["base"]).mean() * 100.0)
    return out


def dkge_wilcoxon(per_gage: pd.DataFrame, alternative: str = DKGE_ALTERNATIVE) -> dict:
    """Wilcoxon signed-rank test across gages on the per-gage median ``dkge``.

    ``per_gage`` needs a ``median_dkge`` column (one row per gage). Tests
    whether the median change differs from zero (``alternative="greater"`` to
    test for improvement only). Returns ``n_gages``, ``n_improved`` (gages with
    a positive median), ``median_of_medians``, ``statistic``, ``p_value`` and
    ``alternative``; the test fields are NaN when it cannot be run (no gages, or
    every median exactly zero).
    """
    from scipy.stats import wilcoxon

    x = per_gage["median_dkge"].dropna() if "median_dkge" in per_gage else pd.Series(dtype=float)
    out = {"n_gages": int(len(x)), "n_improved": int((x > 0).sum()),
           "median_of_medians": float(x.median()) if len(x) else float("nan"),
           "statistic": float("nan"), "p_value": float("nan"),
           "alternative": alternative}
    if len(x) == 0 or (x == 0).all():
        return out
    res = wilcoxon(x.to_numpy(), alternative=alternative)
    out["statistic"] = float(res.statistic)
    out["p_value"] = float(res.pvalue)
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
def _stamp_box(fig: go.Figure, text: str, xref: str = "paper", yref: str = "paper") -> None:
    """Small text box in the top-left of the plot (or of one subplot, via
    ``xref="x2 domain"`` / ``yref="y2 domain"``)."""
    fig.add_annotation(
        xref=xref, yref=yref, x=0.01, y=0.99, xanchor="left", yanchor="top",
        showarrow=False, align="left",
        bordercolor="rgba(80,80,80,0.6)", borderwidth=1, borderpad=4,
        bgcolor="rgba(255,255,255,0.75)", font=dict(size=11), text=text,
    )


def _add_dkge_annotation(fig: go.Figure, res: dict, xref: str = "paper",
                         yref: str = "paper") -> None:
    """Stamp the monthly change-in-KGE result for one gage (calibrated panel):
    the base realization's change, where it falls in the ensemble's change
    distribution, and the ensemble median."""
    if not res or not np.isfinite(res.get("base_dkge", float("nan"))):
        return
    pct = res["base_percentile"]
    _stamp_box(fig, (
        f"monthly &Delta;KGE (final &minus; prior)<br>"
        f"base: {res['base_dkge']:+.2f} "
        f"(KGE {res['base_kge_prior']:.2f} &rarr; {res['base_kge_final']:.2f})<br>"
        f"base at {pct:.0f}th percentile of ensemble<br>"
        f"ensemble median: {res['median_dkge']:+.2f}<br>"
        f"<span style='color:#888'>{res['n_members']} members, "
        f"{res['n_months']} month-years</span>"),
        xref=xref, yref=yref)


def _add_prior_kge_annotation(fig: go.Figure, res: dict, xref: str, yref: str) -> None:
    """Stamp the base realization's prior monthly KGE on the prior panel."""
    if not res or not np.isfinite(res.get("base_kge_prior", float("nan"))):
        return
    _stamp_box(fig, f"monthly KGE, base: {res['base_kge_prior']:.2f}",
               xref=xref, yref=yref)


def build_group_figure(gage, group, sim_df, obs_ens_df, realizations,
                       sim_ens_df=None, x_title=None, y_title=None) -> go.Figure:
    """Observed band (black base line+dots, p05/p95 lines, gray fill) and the
    simulated red lines + 5-95% band for one group. Everything breaks at the
    calibration-year gaps. ``realizations`` is accepted for signature
    compatibility but no longer used (random members were dropped)."""
    fig = go.Figure()
    add_observed_band(fig, obs_base_and_band(obs_ens_df), group,
                      legend_label="observed (base; 5-95% band)")
    add_sim_traces(fig, sim_df, group, sim_ens_df)

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
    """Traces for ONE 5-day streamflow panel (no layout, no metric box).

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
                         iteration=None, dkge=None) -> go.Figure:
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
    ``dkge`` (the :func:`delta_kge` result for this gage) stamps the prior
    panel with the base's prior KGE and the calibrated panel with the change in
    KGE and where the base falls in the ensemble. ``realizations`` is accepted
    for signature compatibility but no longer used.
    """
    calibrated = _fiveday_panel(sim_df, obs_ens_df, x_group, sim_ens_df)
    final_label = "calibrated" + (f" (iteration {iteration})" if iteration is not None else "")

    if sim_ens_prior_df is None or sim_ens_prior_df.empty:
        fig = calibrated
        _add_dkge_annotation(fig, dkge)
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

    _add_prior_kge_annotation(fig, dkge, xref="x domain", yref="y domain")
    _add_dkge_annotation(fig, dkge, xref="x2 domain", yref="y2 domain")

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

    Shared by :func:`build_gage_figures` and :func:`collect_dkge_metrics` so
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


def build_dkge_figure(gage, res: dict) -> go.Figure:
    """Per-gage change-in-KGE figure (two panels).

    Left: histogram of the final-ensemble members' ``dkge`` (continuous monthly
    KGE of the member minus that of the prior base), with lines at zero (no
    change), the ensemble median, and the ``base`` realization, labelled with
    the percentile the base falls at. Right: the base's KGE and its three
    components (``r``, ``alpha``, ``beta``), prior vs final; 1 is perfect for
    all four, so the bars show which component calibration moved.
    """
    fig = make_subplots(rows=1, cols=2, column_widths=[0.6, 0.4],
                        subplot_titles=("ensemble change in monthly KGE",
                                        "base: KGE and its components"))
    d = res["dkge"].dropna()
    fig.add_trace(go.Histogram(x=d.values, nbinsx=30, name="ensemble members",
                               marker_color="rgba(214,39,40,0.45)"), row=1, col=1)
    # vertical reference lines span the histogram's real count range
    counts, _ = np.histogram(d.values, bins=30) if len(d) else (np.array([1]), None)
    ymax = float(counts.max()) * 1.25
    for v, label, color, dash in (
            (0.0, "no change", "gray", "dot"),
            (res["median_dkge"], f"ensemble median {res['median_dkge']:+.2f}", "#1f77b4", "dash"),
            (res["base_dkge"],
             f"base {res['base_dkge']:+.2f} ({res['base_percentile']:.0f}th pct)",
             "black", "solid")):
        if not np.isfinite(v):
            continue
        fig.add_trace(go.Scatter(x=[v, v], y=[0, ymax], mode="lines", name=label,
                                 line=dict(color=color, width=2.5, dash=dash)),
                      row=1, col=1)
    fig.update_yaxes(title_text="members", row=1, col=1)
    fig.update_xaxes(title_text="&Delta;KGE (member final &minus; prior base)", row=1, col=1)
    cb = res["components_base"]
    if cb.notna().any().any():
        labels = ["KGE", "r", "&alpha; (std ratio)", "&beta; (mean ratio)"]
        for col, name, color in (("prior", "prior base", "rgba(80,80,80,0.6)"),
                                 ("final", "final base", "#d62728")):
            fig.add_trace(go.Bar(x=labels, y=cb[col].values, name=name,
                                 marker_color=color,
                                 text=[f"{v:.2f}" for v in cb[col].values],
                                 textposition="outside"), row=1, col=2)
        fig.add_hline(y=1.0, line=dict(color="gray", dash="dot"), row=1, col=2)
        fig.update_yaxes(title_text="value (1 = perfect)", row=1, col=2)
    fig.update_layout(
        title=(f"Change in monthly KGE &mdash; gage {gage}  "
               f"({res['n_members']} members, {res['n_months']} month-years scored)"),
        height=460, template="plotly_white", barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.1, x=0),
        margin=dict(t=110, r=30, l=70, b=60))
    return fig


def build_gage_figures(td: TargetData, gage, params, nhm_id,
                       min_points_per_month: int = DKGE_MIN_POINTS_PER_MONTH,
                       min_months: int = DKGE_MIN_MONTHS) -> dict:
    """All figures for one gage, as ``{plot key: Figure}``.

    Keys are the HRU / monthly-streamflow group names, plus ``streamflow_5day``
    for the combined 5-day plot and ``dkge_5day`` for the change-in-KGE figure
    (only when the gage has 5-day targets and a scorable change in KGE).
    """
    figs = {}
    for key, sim_df, obs_df, sim_ens_df, x_group, prior_ens_df in iter_gage_plot_data(
            td, gage, params, nhm_id):
        if key == FIVEDAY_KEY:
            res = _gage_dkge(sim_df, obs_df, sim_ens_df, min_points_per_month, min_months)
            figs[key] = build_fiveday_figure(
                gage, sim_df, obs_df, x_group, td.realizations,
                sim_ens_df=sim_ens_df, sim_ens_prior_df=prior_ens_df,
                iteration=td.final_iteration, dkge=res)
            if np.isfinite(res["base_dkge"]):
                figs["dkge_5day"] = build_dkge_figure(gage, res)
        else:
            figs[key] = build_group_figure(
                gage, key, sim_df, obs_df, td.realizations, sim_ens_df=sim_ens_df)
    return figs


# --------------------------------------------------------------------------- #
# High- and low-flow buckets (scored on the 5-day points directly)
# --------------------------------------------------------------------------- #
# The 5-day signature groups split into two buckets by the same substring
# patterns used for the phi-factor re-weighting: "_low" (low + ex_low) and
# "scnd" (the pulse/small/large ascending and descending signatures). Each
# bucket is a subset of dates scattered through the year, so it is scored on
# its 5-day points directly; monthly means of a subset would not be real
# monthly flows. A bucket needs DKGE_MIN_POINTS_BUCKET valid points.
DKGE_BUCKETS = [
    ("streamflow_5day_high", "scnd", "high flows"),
    ("streamflow_5day_low", "_low", "low flows"),
]
DKGE_MIN_POINTS_BUCKET = 30
DKGE_ALL_GROUP = FIVEDAY_KEY
DKGE_GROUP_LABELS = {DKGE_ALL_GROUP: "all flows (monthly)",
                     **{g: lab for g, _pat, lab in DKGE_BUCKETS}}


def delta_kge_points(obs_ens_df: pd.DataFrame, sim_ens_df: pd.DataFrame,
                     prior_base: pd.Series, dates=None,
                     min_points: int = DKGE_MIN_POINTS_BUCKET) -> dict:
    """Change in KGE (final minus prior base) scored on 5-day points directly.

    Same inputs and outputs as :func:`delta_kge`, restricted to ``dates`` (a
    flow bucket), but with no monthly averaging: for each realization the KGE
    is computed on the 5-day points where the observation, the realization and
    the prior base are all finite, and the prior base is scored on exactly
    those points. A realization with fewer than ``min_points`` points gets NaN.
    ``n_points`` is the number of points scored for the base; ``n_months`` is
    0 and ``monthly_base`` is empty.
    """
    out = _empty_dkge()
    out["n_points"] = 0
    if (obs_ens_df is None or sim_ens_df is None or prior_base is None
            or obs_ens_df.empty or sim_ens_df.empty or len(prior_base) == 0):
        return out
    obs = (obs_ens_df["base"] if "base" in obs_ens_df.columns
           else obs_ens_df.median(axis=1)).dropna()
    prior = prior_base.dropna()
    common = obs.index.intersection(sim_ens_df.index).intersection(prior.index)
    if dates is not None:
        common = common.intersection(pd.Index(dates))
    common = common.sort_values()
    if len(common) == 0:
        return out
    o = obs.loc[common].to_numpy(dtype=float)
    p = prior.loc[common].to_numpy(dtype=float)
    fin = sim_ens_df.loc[common]

    kf, kp, comp, n_base, bf, bp = {}, {}, {}, 0, {}, {}
    for m in fin.columns:
        s = fin[m].to_numpy(dtype=float)
        ok = np.isfinite(o) & np.isfinite(s) & np.isfinite(p)
        if ok.sum() < int(min_points):
            kf[m] = kp[m] = bf[m] = bp[m] = float("nan")
            continue
        cf = kge_components(o[ok], s[ok])
        cp = kge_components(o[ok], p[ok])
        kf[m], kp[m] = cf["KGE"], cp["KGE"]
        bf[m], bp[m] = pbias_pct(o[ok], s[ok]), pbias_pct(o[ok], p[ok])
        if m == "base":
            comp, n_base = {"prior": cp, "final": cf}, int(ok.sum())
    kf, kp = pd.Series(kf, dtype=float), pd.Series(kp, dtype=float)
    _set_pbias(out, pd.Series(bf, dtype=float), pd.Series(bp, dtype=float))
    dk = kf - kp
    ens_ids = [i for i in dk.index if i != "base"]
    ens = dk.loc[ens_ids].dropna()

    out["dkge"] = dk.loc[ens_ids]
    out["kge_final"] = kf.loc[ens_ids]
    out["median_dkge"] = float(ens.median()) if len(ens) else float("nan")
    out["n_members"] = int(len(ens))
    if "base" in dk.index and np.isfinite(dk["base"]):
        out["base_dkge"] = float(dk["base"])
        out["base_kge_final"] = float(kf["base"])
        out["base_kge_prior"] = float(kp["base"])
        out["kge_prior_base"] = float(kp["base"])
        out["n_points"] = n_base
        out["components_base"] = pd.DataFrame(comp).reindex(KGE_COMPONENTS)
        if len(ens):
            out["base_percentile"] = float((ens <= dk["base"]).mean() * 100.0)
    return out


def _gage_dkge(sim_df, obs_ens_df, sim_ens_df, min_points_per_month, min_months,
               x_group=None, min_points_bucket: int = DKGE_MIN_POINTS_BUCKET) -> dict:
    """:func:`delta_kge` for one gage, using the iteration-0 ``starting`` base
    as the prior. With ``x_group`` (date -> 5-day signature group) the result
    also carries ``buckets``: ``{bucket group: delta_kge_points result}`` for
    the high- and low-flow buckets. Empty result when the gage has no
    ``starting`` series."""
    prior = sim_df["starting"] if "starting" in sim_df.columns else None
    res = delta_kge(obs_ens_df, sim_ens_df, prior,
                    min_points_per_month=min_points_per_month,
                    min_months=min_months)
    mb = res["monthly_base"]
    res["n_points"] = int(mb["n_points"].sum()) if not mb.empty else 0
    res["buckets"] = {}
    if x_group:
        xg = pd.Series(x_group)
        for group, pattern, _label in DKGE_BUCKETS:
            dates = xg[xg.str.contains(pattern, na=False)].index
            res["buckets"][group] = delta_kge_points(
                obs_ens_df, sim_ens_df, prior, dates=dates,
                min_points=min_points_bucket)
    return res


DKGE_CSV = "dkge_metrics.csv"
DKGE_WILCOXON_CSV = "dkge_wilcoxon.csv"
DKGE_SUMMARY_HTML = "calib_eval_dkge_summary.html"
DKGE_COLUMNS = ["gage", "group", "method", "n_months", "n_points", "n_members",
                "kge_prior_base", "kge_final_base", "base_dkge", "median_dkge",
                "dkge_p05", "dkge_p95", "base_percentile",
                "pbias_prior_base", "pbias_final_base", "median_pbias",
                "pbias_p05", "pbias_p95"]


def _dkge_row(gage, group, method, res) -> dict:
    d = res["dkge"].dropna()
    pb = res.get("pbias_final", pd.Series(dtype=float)).dropna()
    return {
        "gage": str(gage), "group": group, "method": method,
        "n_months": res["n_months"], "n_points": res.get("n_points", 0),
        "n_members": res["n_members"],
        "kge_prior_base": res["base_kge_prior"],
        "kge_final_base": res["base_kge_final"],
        "base_dkge": res["base_dkge"], "median_dkge": res["median_dkge"],
        "dkge_p05": float(d.quantile(0.05)) if len(d) else np.nan,
        "dkge_p95": float(d.quantile(0.95)) if len(d) else np.nan,
        "base_percentile": res["base_percentile"],
        "pbias_prior_base": res.get("base_pbias_prior", np.nan),
        "pbias_final_base": res.get("base_pbias_final", np.nan),
        "median_pbias": res.get("median_pbias", np.nan),
        "pbias_p05": float(pb.quantile(0.05)) if len(pb) else np.nan,
        "pbias_p95": float(pb.quantile(0.95)) if len(pb) else np.nan,
    }


def collect_dkge_metrics(td: TargetData, params, gages,
                         min_points_per_month: int = DKGE_MIN_POINTS_PER_MONTH,
                         min_months: int = DKGE_MIN_MONTHS,
                         alternative: str = DKGE_ALTERNATIVE,
                         min_points_bucket: int = DKGE_MIN_POINTS_BUCKET):
    """Change-in-KGE for every gage that has 5-day streamflow targets.

    Returns ``(table, wilcoxon, results)``:

    * ``table`` -- up to three rows per gage: ``streamflow_5day`` (all flows,
      continuous monthly KGE), ``streamflow_5day_high`` and
      ``streamflow_5day_low`` (the flow buckets, KGE on the 5-day points).
      Columns: ``method``, ``n_months`` (month-years, all-flows row),
      ``n_points`` (5-day points scored for the base), ensemble size, the
      base's prior and final KGE, ``base_dkge``, the ensemble ``median_dkge``
      and its 5th/95th percentiles, and ``base_percentile``.
    * ``wilcoxon`` -- one row per group: :func:`dkge_wilcoxon` of the per-gage
      ``median_dkge`` for that group.
    * ``results`` -- ``{gage: delta_kge result dict}`` for the all-flows score,
      each with a ``buckets`` entry holding the two bucket results.
    """
    nhm_id = [int(x) for x in np.asarray(params["nhm_id"])]
    rows, results = [], {}
    for gage in gages:
        for key, sim_df, obs_df, sim_ens_df, x_group, _prior in iter_gage_plot_data(
                td, gage, params, nhm_id):
            if key != FIVEDAY_KEY:
                continue
            res = _gage_dkge(sim_df, obs_df, sim_ens_df, min_points_per_month,
                             min_months, x_group=x_group,
                             min_points_bucket=min_points_bucket)
            results[str(gage)] = res
            rows.append(_dkge_row(gage, DKGE_ALL_GROUP, "monthly mean series", res))
            for group, _pat, _lab in DKGE_BUCKETS:
                if group in res["buckets"]:
                    rows.append(_dkge_row(gage, group, "5-day points",
                                          res["buckets"][group]))
    table = pd.DataFrame(rows, columns=DKGE_COLUMNS)
    num = [c for c in DKGE_COLUMNS if c not in ("gage", "group", "method")]
    table[num] = table[num].astype(float).round(3)
    groups = [DKGE_ALL_GROUP] + [g for g, _p, _l in DKGE_BUCKETS]
    wil = pd.DataFrame([{"group": g, **dkge_wilcoxon(table[table["group"] == g],
                                                     alternative=alternative)}
                        for g in groups])
    return table, wil, results


def _group_result(results: dict, gage: str, group: str) -> dict:
    res = results.get(gage, {})
    return res if group == DKGE_ALL_GROUP else res.get("buckets", {}).get(group, {})


DKGE_COMBINED_LABEL = "all gages (mean)"


def combined_dkge(table: pd.DataFrame, results: dict, group: str) -> dict:
    """Change in KGE averaged over all gages, for one group.

    For each ensemble member, the mean of that member's ``dkge`` over the gages
    where it was scored; a member is the same parameter set at every gage, so
    this is the member's average change across the domain. The base's value is
    the mean of the gages' ``base_dkge``, and ``base_percentile`` is the percent
    of members whose mean is at or below it. Every gage counts equally,
    whatever its size or record length.

    Returns ``dkge`` (Series by member), ``median_dkge``, ``base_dkge``,
    ``base_percentile``, ``n_gages`` (gages with a base score) and
    ``n_members``.
    """
    sub = table[(table["group"] == group)].dropna(subset=["base_dkge"])
    per_gage = {g: _group_result(results, g, group).get("dkge", pd.Series(dtype=float))
                for g in sub["gage"]}
    per_gage = {g: s for g, s in per_gage.items() if len(s.dropna())}
    nan = float("nan")
    out = {"dkge": pd.Series(dtype=float), "median_dkge": nan, "base_dkge": nan,
           "base_percentile": nan, "n_gages": int(len(sub)), "n_members": 0}
    if sub.empty:
        return out
    out["base_dkge"] = float(sub["base_dkge"].mean())
    if per_gage:
        m = pd.DataFrame(per_gage).mean(axis=1, skipna=True).dropna()
        out["dkge"] = m
        out["n_members"] = int(len(m))
        if len(m):
            out["median_dkge"] = float(m.median())
            out["base_percentile"] = float((m <= out["base_dkge"]).mean() * 100.0)
    return out


def build_dkge_summary_figure(table: pd.DataFrame, results: dict,
                              wilcoxon: pd.DataFrame) -> go.Figure:
    """Across-gage view in three panels: all flows (continuous monthly KGE),
    high flows and low flows (KGE on the 5-day points of each bucket). Each
    panel has one box per gage of the ensemble members' change, the ``base``
    realization as a black diamond, a line at zero, and that group's Wilcoxon
    result on the per-gage median change in its subplot title. Gages are in
    the same order in every panel (by the all-flows median change).

    The bottom row of each panel, ``all gages (mean)``, is
    :func:`combined_dkge`: a box of each member's change averaged over the
    gages, with the base's averaged change as a black diamond."""
    groups = [DKGE_ALL_GROUP] + [g for g, _p, _l in DKGE_BUCKETS]
    wil = wilcoxon.set_index("group")
    allg = table[table["group"] == DKGE_ALL_GROUP]
    order = allg.sort_values("median_dkge", na_position="first")["gage"].tolist()
    # Plotly draws the first category at the bottom of a category axis.
    y_order = [DKGE_COMBINED_LABEL] + order

    def _title(g):
        w = wil.loc[g] if g in wil.index else None
        if w is None or not w["n_gages"]:
            return f"{DKGE_GROUP_LABELS[g]}<br><sup>no gages scored</sup>"
        ptxt = f"{w['p_value']:.3g}" if np.isfinite(w["p_value"]) else "n/a"
        return (f"{DKGE_GROUP_LABELS[g]}<br><sup>Wilcoxon p = {ptxt}, "
                f"{int(w['n_improved'])} of {int(w['n_gages'])} gages improved</sup>")

    fig = make_subplots(rows=1, cols=len(groups), shared_yaxes=True,
                        horizontal_spacing=0.04,
                        subplot_titles=[_title(g) for g in groups])
    for c, group in enumerate(groups, start=1):
        sub = table[table["group"] == group].set_index("gage")
        for g in order:
            d = _group_result(results, g, group).get("dkge", pd.Series(dtype=float)).dropna()
            if len(d):
                fig.add_trace(go.Box(x=d.values, y=[g] * len(d), orientation="h",
                                     name=g, boxpoints=False,
                                     marker_color="rgba(214,39,40,0.7)",
                                     showlegend=False), row=1, col=c)
        b = sub.reindex(order).dropna(subset=["base_dkge"])
        if not b.empty:
            fig.add_trace(go.Scatter(
                x=b["base_dkge"].values, y=b.index.tolist(), mode="markers",
                name="base realization", legendgroup="base", showlegend=(c == 1),
                marker=dict(color="black", symbol="diamond", size=9),
                customdata=np.stack([b["base_percentile"].values,
                                     b["kge_prior_base"].values,
                                     b["kge_final_base"].values], axis=1),
                hovertemplate=("base %{x:+.2f} (%{customdata[0]:.0f}th pct)<br>"
                               "KGE %{customdata[1]:.2f} &rarr; %{customdata[2]:.2f}"
                               "<extra>%{y}</extra>")), row=1, col=c)
        # Combined row: each member's change averaged over all gages.
        cmb = combined_dkge(table, results, group)
        if len(cmb["dkge"]):
            fig.add_trace(go.Box(x=cmb["dkge"].values,
                                 y=[DKGE_COMBINED_LABEL] * len(cmb["dkge"]),
                                 orientation="h", name=DKGE_COMBINED_LABEL,
                                 boxpoints=False, marker_color="rgba(31,119,180,0.8)",
                                 showlegend=False), row=1, col=c)
        if np.isfinite(cmb["base_dkge"]):
            fig.add_trace(go.Scatter(
                x=[cmb["base_dkge"]], y=[DKGE_COMBINED_LABEL], mode="markers",
                name="base realization", legendgroup="base", showlegend=False,
                marker=dict(color="black", symbol="diamond", size=11,
                            line=dict(color="white", width=1)),
                customdata=[[cmb["base_percentile"], cmb["n_gages"], cmb["median_dkge"]]],
                hovertemplate=("mean over %{customdata[1]} gages: base %{x:+.2f} "
                               "(%{customdata[0]:.0f}th pct)<br>ensemble median "
                               "%{customdata[2]:+.2f}<extra>all gages</extra>")),
                row=1, col=c)
        fig.add_vline(x=0, line=dict(color="gray", dash="dot"), row=1, col=c)
        fig.update_xaxes(title_text="&Delta;KGE (final &minus; prior base)", row=1, col=c)
    fig.update_yaxes(type="category", categoryorder="array", categoryarray=y_order)
    fig.update_yaxes(title_text="gage", row=1, col=1)
    # thin rule separating the combined row from the per-gage rows
    if order:
        fig.add_hline(y=0.5, line=dict(color="rgba(80,80,80,0.5)", width=1))
    fig.update_layout(
        title=("Change in KGE across gages (box = ensemble, diamond = base; "
               "blue row = mean over all gages)<br>"
               "<sup>all flows: KGE on the continuous monthly series; high/low "
               "flows: KGE on the 5-day points of each bucket</sup>"),
        height=max(460, 40 * len(y_order) + 240), template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.12, x=0),
        margin=dict(t=160, r=30, l=90, b=60))
    return fig


def plot_calibration_evaluation(td: TargetData, params, out_dir, gages,
                                min_points_per_month: int = DKGE_MIN_POINTS_PER_MONTH,
                                min_months: int = DKGE_MIN_MONTHS,
                                alternative: str = DKGE_ALTERNATIVE,
                                min_points_bucket: int = DKGE_MIN_POINTS_BUCKET) -> dict:
    """Write one HTML per gage per plot, plus the change-in-KGE tables.

    Layout: ``<out_dir>/<gage>/calib_eval_<key>_<gage>.html`` (``key`` includes
    ``dkge_5day`` where scorable), ``<out_dir>/dkge_metrics.csv`` (per gage and
    group), ``<out_dir>/dkge_wilcoxon.csv`` (one row per group),
    ``<out_dir>/dkge_members.csv`` (every realization's change, for
    comparing runs), ``<out_dir>/dkge_settings.json`` and
    ``<out_dir>/calib_eval_dkge_summary.html``. Returns ``{gage: [paths]}`` (the
    per-gage HTML paths only).
    """
    out_dir = pl.Path(out_dir)
    nhm_id = [int(x) for x in np.asarray(params["nhm_id"])]
    written = {}
    for gage in gages:
        gage_dir = out_dir / str(gage)
        gage_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        figs = build_gage_figures(td, gage, params, nhm_id,
                                  min_points_per_month=min_points_per_month,
                                  min_months=min_months)
        for key, fig in figs.items():
            p = gage_dir / f"calib_eval_{key}_{gage}.html"
            fig.write_html(str(p), include_plotlyjs="cdn")
            paths.append(p)
        written[str(gage)] = paths
    table, wilcoxon, results = collect_dkge_metrics(
        td, params, gages, min_points_per_month=min_points_per_month,
        min_months=min_months, alternative=alternative,
        min_points_bucket=min_points_bucket)
    write_dkge_outputs(out_dir, table, wilcoxon, results, dkge_settings(
        min_points_per_month, min_months, min_points_bucket, alternative,
        td.final_iteration))
    if table["median_dkge"].notna().any():
        build_dkge_summary_figure(table, results, wilcoxon).write_html(
            str(out_dir / DKGE_SUMMARY_HTML), include_plotlyjs="cdn")
    return written


DKGE_MEMBERS_CSV = "dkge_members.csv"
DKGE_SETTINGS_JSON = "dkge_settings.json"


def dkge_settings(min_points_per_month=DKGE_MIN_POINTS_PER_MONTH,
                  min_months=DKGE_MIN_MONTHS,
                  min_points_bucket=DKGE_MIN_POINTS_BUCKET,
                  alternative=DKGE_ALTERNATIVE, final_iteration=None) -> dict:
    """The settings a change-in-KGE result was computed with, so a later
    comparison can tell whether two runs were scored the same way."""
    return {"min_points_per_month": int(min_points_per_month),
            "min_months": int(min_months),
            "min_points_bucket": int(min_points_bucket),
            "alternative": str(alternative),
            "final_iteration": None if final_iteration is None else int(final_iteration)}


def dkge_members_long(results: dict) -> pd.DataFrame:
    """Every realization's change in KGE, long format: ``gage``, ``group``,
    ``realization``, ``dkge``, ``pbias`` (the realization's final PBIAS) and
    ``pbias_prior`` (the prior base's PBIAS on the same points; for the base
    row, the prior base's own). The ``base`` realization is included as its own
    row (it is kept out of the ensemble distribution elsewhere, so readers
    filter on ``realization != "base"``)."""
    frames = []
    groups = [DKGE_ALL_GROUP] + [g for g, _p, _l in DKGE_BUCKETS]
    for gage in results:
        for group in groups:
            res = _group_result(results, gage, group)
            if not res:
                continue
            d = res.get("dkge", pd.Series(dtype=float)).dropna()
            pf = res.get("pbias_final", pd.Series(dtype=float))
            pp = res.get("pbias_prior", pd.Series(dtype=float))
            rows = pd.DataFrame({"gage": str(gage), "group": group,
                                 "realization": d.index.astype(str), "dkge": d.values,
                                 "pbias": pf.reindex(d.index).values,
                                 "pbias_prior": pp.reindex(d.index).values})
            if np.isfinite(res.get("base_dkge", float("nan"))):
                rows = pd.concat([rows, pd.DataFrame([{
                    "gage": str(gage), "group": group, "realization": "base",
                    "dkge": res["base_dkge"],
                    "pbias": res.get("base_pbias_final", np.nan),
                    "pbias_prior": res.get("base_pbias_prior", np.nan)}])],
                    ignore_index=True)
            frames.append(rows)
    cols = ["gage", "group", "realization", "dkge", "pbias", "pbias_prior"]
    return pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)


def write_dkge_outputs(out_dir, table, wilcoxon, results, settings: dict) -> None:
    """Write the change-in-KGE tables: ``dkge_metrics.csv``,
    ``dkge_wilcoxon.csv``, ``dkge_members.csv`` (every realization) and
    ``dkge_settings.json``."""
    import json

    out_dir = pl.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / DKGE_CSV, index=False)
    wilcoxon.to_csv(out_dir / DKGE_WILCOXON_CSV, index=False)
    dkge_members_long(results).to_csv(out_dir / DKGE_MEMBERS_CSV, index=False)
    (out_dir / DKGE_SETTINGS_JSON).write_text(json.dumps(settings, indent=2), encoding="utf-8")
