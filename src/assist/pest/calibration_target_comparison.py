"""Compare the non-5-day calibration targets of several PEST++ IES runs.

Companion to :mod:`assist.pest.calibration_comparison` (which compares the
5-day streamflow change in KGE). For every gage and every other calibration
target group, each run's **final** fit is scored with one statistic, on the
target's values aggregated to the gage exactly as the evaluation plots
aggregate them (:func:`assist.pest.calibration_evaluation.iter_gage_plot_data`):

* HRU targets are the **mean over the gage's contributing HRUs** (the HRUs on
  the gage's segment and every segment upstream of it), per time step;
* the monthly streamflow targets are the gage's own series.

Statistics (``value``; the prior base is scored on exactly the same points):

* **PBIAS (%)** for targets in physical units -- ``streamflow_mon``,
  ``streamflow_mean_mon``, ``runoff_mon``, ``actet_mean_mon``,
  ``swe_monthly``: ``100 * sum(obs - sim) / sum(obs)`` (positive = model too
  low), see :func:`assist.pest.calibration_evaluation.pbias_pct`;
* **mean error** for the targets normalized 0-1 per HRU -- ``recharge_ann``,
  ``soil_moist_ann``, ``soil_moist_mean_mon``: ``mean(sim - obs)`` in
  normalized units (positive = model too high). A percent bias is not a volume
  bias for a min-max-normalized series, so it is not used there.

The observed reference is the obs+noise ensemble's ``base`` realization (the
control-file observation values). Everything is read from each run's
evaluation archive (``calib_eval_targets.nc``) and ``parameters.json``; no
model is run.
"""
from __future__ import annotations

import json
import pathlib as pl

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from assist.pest import calibration_evaluation as ce
from assist.pest.calibration_comparison import RUN_COLORS, _rgba

PBIAS_GROUPS = ["streamflow_mon", "streamflow_mean_mon", "runoff_mon",
                "actet_mean_mon", "swe_monthly"]
ME_GROUPS = ["recharge_ann", "soil_moist_ann", "soil_moist_mean_mon"]
TARGET_GROUPS = PBIAS_GROUPS + ME_GROUPS
TARGET_LABELS = {
    "streamflow_mon": "monthly streamflow",
    "streamflow_mean_mon": "mean-monthly streamflow",
    "runoff_mon": "HRU runoff, monthly",
    "actet_mean_mon": "actual ET, mean-monthly",
    "swe_monthly": "SWE, monthly",
    "recharge_ann": "recharge, annual (normalized)",
    "soil_moist_ann": "soil moisture, annual (normalized)",
    "soil_moist_mean_mon": "soil moisture, mean-monthly (normalized)",
}
STAT_OF = {**{g: "pbias" for g in PBIAS_GROUPS}, **{g: "mean_error" for g in ME_GROUPS}}
STAT_LABEL = {"pbias": "PBIAS % (+ = model too low)",
              "mean_error": "mean error, sim &minus; obs (normalized; + = model too high)"}
MIN_POINTS = 3
SHARED_LABEL = "shared gages (mean)"
TARGETS_HTML = "compare_targets_summary.html"
TARGETS_BY_GAGE_CSV = "compare_targets_by_gage.csv"
TARGETS_ALL_GAGES_CSV = "compare_targets_all_gages.csv"
TARGETS_MEMBERS_CSV = "target_metrics_members.csv"
TARGETS_CACHE_JSON = "target_metrics_source.json"


def mean_error(obs, sim) -> float:
    """``mean(sim - obs)`` on the points finite in both; NaN with fewer than
    3 points."""
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    ok = np.isfinite(obs) & np.isfinite(sim)
    if ok.sum() < MIN_POINTS:
        return float("nan")
    return float((sim[ok] - obs[ok]).mean())


def _stat(group):
    return ce.pbias_pct if STAT_OF[group] == "pbias" else mean_error


def score_group(obs: pd.Series, sim_ens: pd.DataFrame, prior: pd.Series, group: str) -> pd.DataFrame:
    """One row per realization: the final statistic (``value``), the prior
    base's statistic on the same points (``prior_value``) and the number of
    points (``n_points``)."""
    fn = _stat(group)
    idx = obs.dropna().index.intersection(sim_ens.index).intersection(prior.dropna().index)
    o = obs.loc[idx].to_numpy(float)
    p = prior.loc[idx].to_numpy(float)
    rows = []
    for m in sim_ens.columns:
        s = sim_ens.loc[idx, m].to_numpy(float)
        ok = np.isfinite(o) & np.isfinite(s) & np.isfinite(p)
        n = int(ok.sum())
        v = fn(o[ok], s[ok]) if n >= MIN_POINTS else np.nan
        pv = fn(o[ok], p[ok]) if n >= MIN_POINTS else np.nan
        rows.append({"realization": str(m), "value": v, "prior_value": pv, "n_points": n})
    return pd.DataFrame(rows)


def compute_target_metrics(run_dir, gages, eval_subdir: str = "calibration_evaluation") -> pd.DataFrame:
    """Every realization's final statistic for every gage and target group of
    one run, long format: ``gage``, ``group``, ``stat``, ``realization``,
    ``value``, ``prior_value``, ``n_points``. Gages that are not POI gages in
    the run are skipped; a gage without a given target group (e.g. no
    monthly streamflow target) simply has no rows for it."""
    run_dir = pl.Path(run_dir)
    td = ce.load_targets(run_dir / eval_subdir / ce.TARGETS_ARCHIVE)
    params = ce.load_run_parameters(run_dir)
    nhm_id = [int(x) for x in np.asarray(params["nhm_id"])]
    poi = {str(x) for x in np.asarray(params["poi_gage_id"])}
    frames = []
    for gage in gages:
        if str(gage) not in poi:
            continue
        for key, sim_df, obs_df, sim_ens_df, _xg, _pr in ce.iter_gage_plot_data(
                td, str(gage), params, nhm_id):
            if key not in TARGET_GROUPS or sim_ens_df is None or sim_ens_df.empty:
                continue
            if "starting" not in sim_df.columns:
                continue
            obs = obs_df["base"] if "base" in obs_df.columns else obs_df.median(axis=1)
            sc = score_group(obs, sim_ens_df, sim_df["starting"], key)
            sc.insert(0, "stat", STAT_OF[key])
            sc.insert(0, "group", key)
            sc.insert(0, "gage", str(gage))
            frames.append(sc)
    cols = ["gage", "group", "stat", "realization", "value", "prior_value", "n_points"]
    return pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)


def load_target_metrics(run_dir, label: str, gages, work_dir,
                        eval_subdir: str = "calibration_evaluation") -> tuple[pd.DataFrame, str]:
    """A run's target metrics, from ``<work_dir>/<label>/`` when they were
    computed from the same archive for the same gages, otherwise computed from
    the archive (about a minute) and saved there. Returns ``(table, note)``."""
    run_dir = pl.Path(run_dir)
    archive = run_dir / eval_subdir / ce.TARGETS_ARCHIVE
    if not archive.is_file():
        raise FileNotFoundError(f"no {ce.TARGETS_ARCHIVE} in {run_dir / eval_subdir}")
    st = archive.stat()
    key = {"archive": str(archive), "size": st.st_size, "mtime": st.st_mtime,
           "gages": sorted(str(g) for g in gages), "min_points": MIN_POINTS}
    out = pl.Path(work_dir) / label
    cache = out / TARGETS_CACHE_JSON
    if cache.is_file() and (out / TARGETS_MEMBERS_CSV).is_file():
        if json.loads(cache.read_text(encoding="utf-8")) == key:
            df = pd.read_csv(out / TARGETS_MEMBERS_CSV, dtype={"gage": str, "realization": str})
            return df, f"used saved target metrics in {out}"
    df = compute_target_metrics(run_dir, gages, eval_subdir=eval_subdir)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / TARGETS_MEMBERS_CSV, index=False)
    cache.write_text(json.dumps(key, indent=2), encoding="utf-8")
    return df, f"computed from {archive}; saved to {out}"


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def summarize_by_gage(metrics: dict) -> pd.DataFrame:
    """Per gage, group and run: the base's final and prior statistic, the
    ensemble median and 5th/95th percentiles, and the points scored.
    ``metrics`` is ``{label: long table}``."""
    rows = []
    for lab, df in metrics.items():
        for (g, grp), d in df.groupby(["gage", "group"]):
            ens = d[d["realization"] != "base"]["value"].dropna()
            b = d[d["realization"] == "base"]
            rows.append({
                "gage": g, "group": grp, "stat": STAT_OF[grp], "run": lab,
                "base_value": float(b["value"].iloc[0]) if len(b) else np.nan,
                "prior_value": float(b["prior_value"].iloc[0]) if len(b) else np.nan,
                "median_value": float(ens.median()) if len(ens) else np.nan,
                "p05": float(ens.quantile(.05)) if len(ens) else np.nan,
                "p95": float(ens.quantile(.95)) if len(ens) else np.nan,
                "n_points": int(b["n_points"].iloc[0]) if len(b) else 0,
                "n_members": int(len(ens)),
            })
    return pd.DataFrame(rows)


def shared_target_gages(metrics: dict, group: str) -> list:
    """Gages where every run's base has a value for ``group``."""
    sets = []
    for df in metrics.values():
        b = df[(df["group"] == group) & (df["realization"] == "base")].dropna(subset=["value"])
        sets.append(set(b["gage"]))
    return sorted(set.intersection(*sets)) if sets else []


def combined(df: pd.DataFrame, group: str, gages) -> dict:
    """Mean over ``gages`` for one run and group: each member's statistic
    averaged over the gages, the base's and the prior base's averages, and the
    means of the absolute values (which do not let opposite biases cancel)."""
    d = df[(df["group"] == group) & (df["gage"].isin(set(gages)))]
    b = d[d["realization"] == "base"].dropna(subset=["value"])
    nan = float("nan")
    out = {"values": pd.Series(dtype=float), "base_value": nan, "prior_value": nan,
           "median_value": nan, "base_abs": nan, "prior_abs": nan,
           "n_gages": int(len(b)), "n_members": 0}
    if b.empty:
        return out
    out.update(base_value=float(b["value"].mean()), prior_value=float(b["prior_value"].mean()),
               base_abs=float(b["value"].abs().mean()), prior_abs=float(b["prior_value"].abs().mean()))
    ens = d[d["realization"] != "base"]
    if not ens.empty:
        per = ens.pivot_table(index="realization", columns="gage", values="value",
                              aggfunc="first").mean(axis=1, skipna=True).dropna()
        out.update(values=per, median_value=float(per.median()) if len(per) else nan,
                   n_members=int(len(per)))
    return out


def summarize_all_gages(metrics: dict) -> pd.DataFrame:
    """The shared-gage mean per run and group (see :func:`combined`)."""
    rows = []
    for grp in TARGET_GROUPS:
        sh = shared_target_gages(metrics, grp)
        for lab, df in metrics.items():
            c = combined(df, grp, sh)
            rows.append({"group": grp, "stat": STAT_OF[grp], "run": lab,
                         **{k: v for k, v in c.items() if k != "values"}})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Figure
# --------------------------------------------------------------------------- #
PBIAS_AXIS_MIN = -300.0   # PBIAS has no lower limit; the axis is cut here


def _clip_pbias_axis(fig, metrics, group, rows, pos, labels, fr, fc) -> None:
    """PBIAS is at most +100 but has no lower limit, so one run that grossly
    over-predicts at one gage would squash every other box against the right
    edge. If any value falls below :data:`PBIAS_AXIS_MIN`, cut the axis there
    and mark each base value beyond the cut with a left-pointing triangle at
    the edge (hover gives the true value)."""
    vals = np.concatenate([metrics[l].loc[metrics[l]["group"] == group, ["value", "prior_value"]]
                           .to_numpy().ravel() for l in labels])
    vals = vals[np.isfinite(vals)]
    if not len(vals) or vals.min() >= PBIAS_AXIS_MIN:
        return
    hi = max(float(vals.max()), 0.0)
    fig.update_xaxes(range=[PBIAS_AXIS_MIN * 1.05, hi + 0.05 * (hi - PBIAS_AXIS_MIN)],
                     row=fr, col=fc)
    for ri, lab in enumerate(labels):
        b = metrics[lab]
        b = b[(b["group"] == group) & (b["realization"] == "base")].set_index("gage")["value"]
        ys, txt = [], []
        for row_i, gage in enumerate(rows):
            v = b.get(gage, np.nan)
            if np.isfinite(v) and v < PBIAS_AXIS_MIN:
                ys.append(pos(row_i, ri)); txt.append(f"{gage}: base {v:,.0f}%")
        if ys:
            fig.add_trace(go.Scatter(
                x=[PBIAS_AXIS_MIN * 1.02] * len(ys), y=ys, mode="markers", text=txt,
                marker=dict(symbol="triangle-left", size=11,
                            color=RUN_COLORS[ri % len(RUN_COLORS)],
                            line=dict(color="black", width=1)),
                name=f"off scale, {lab}", legendgroup=lab, showlegend=False,
                hovertemplate=f"{lab} %{{text}} (off scale)<extra></extra>"), row=fr, col=fc)
def build_target_figure(metrics: dict, order: list) -> go.Figure:
    """Two rows of panels: PBIAS for the targets in physical units (top) and
    mean error for the normalized targets (bottom), one panel per target
    group. Each gage row has one box per run (ensemble), that run's base as a
    diamond, and a gray open circle for the prior base. The bottom row of each
    panel is the mean over the gages that every run scored. ``order`` is the
    gage order (bottom to top), normally the one used by the change-in-KGE
    figure."""
    labels = list(metrics)
    allg = sorted({g for df in metrics.values() for g in df["gage"]})
    order = [g for g in order if g in allg] + [g for g in allg if g not in order]
    rows = [SHARED_LABEL] + order
    k = len(labels)
    step = 0.8 / k
    width = step * 0.85
    pos = lambda row_i, run_i: row_i - (run_i - (k - 1) / 2.0) * step
    ncol = max(len(PBIAS_GROUPS), len(ME_GROUPS))
    layout = {g: (1, i + 1) for i, g in enumerate(PBIAS_GROUPS)}
    layout.update({g: (2, i + 1) for i, g in enumerate(ME_GROUPS)})
    shared = {g: shared_target_gages(metrics, g) for g in TARGET_GROUPS}
    titles = [""] * (2 * ncol)
    for g, (r, c) in layout.items():
        titles[(r - 1) * ncol + (c - 1)] = f"{TARGET_LABELS[g]}<br><sup>{len(shared[g])} shared gages</sup>"
    fig = make_subplots(rows=2, cols=ncol, shared_yaxes=True, horizontal_spacing=0.03,
                        vertical_spacing=0.1, subplot_titles=titles)
    fmt = {"pbias": "+.1f", "mean_error": "+.3f"}
    for group, (fr, fc) in layout.items():
        stat = STAT_OF[group]
        for ri, lab in enumerate(labels):
            color = RUN_COLORS[ri % len(RUN_COLORS)]
            df = metrics[lab]
            d = df[df["group"] == group]
            ens = d[d["realization"] != "base"]
            base = d[d["realization"] == "base"].set_index("gage")["value"]
            cmb = combined(df, group, shared[group])
            first = True
            bx, by, bt = [], [], []
            for row_i, gage in enumerate(rows):
                vals = (cmb["values"].values if gage == SHARED_LABEL
                        else ens.loc[ens["gage"] == gage, "value"].dropna().values)
                if len(vals):
                    fig.add_trace(go.Box(
                        x=vals, y=np.full(len(vals), pos(row_i, ri)), orientation="h",
                        width=width, boxpoints=False, name=lab, legendgroup=lab,
                        showlegend=(fr == 1 and fc == 1 and first), marker_color=color,
                        fillcolor=_rgba(color, 0.35), line=dict(color=color, width=1.2),
                        hovertemplate=f"{lab}<br>{gage}<extra></extra>"), row=fr, col=fc)
                    first = False
                v = cmb["base_value"] if gage == SHARED_LABEL else base.get(gage, np.nan)
                if np.isfinite(v):
                    bx.append(v); by.append(pos(row_i, ri)); bt.append(gage)
            if bx:
                fig.add_trace(go.Scatter(
                    x=bx, y=by, mode="markers", name=f"base, {lab}", legendgroup=lab,
                    showlegend=False, text=bt,
                    marker=dict(symbol="diamond", size=9, color=color,
                                line=dict(color="black", width=1)),
                    hovertemplate=f"{lab} base %{{x:{fmt[stat]}}}<extra>%{{text}}</extra>"),
                    row=fr, col=fc)
        # prior base, one gray circle per gage row (the runs share it)
        px, py, pt = [], [], []
        for row_i, gage in enumerate(rows):
            if gage == SHARED_LABEL:
                v = combined(metrics[labels[0]], group, shared[group])["prior_value"]
            else:
                v = np.nan
                for lab in labels:
                    b = metrics[lab]
                    b = b[(b["group"] == group) & (b["gage"] == gage) & (b["realization"] == "base")]
                    if len(b) and np.isfinite(b["prior_value"].iloc[0]):
                        v = float(b["prior_value"].iloc[0]); break
            if np.isfinite(v):
                px.append(v); py.append(row_i); pt.append(gage)
        if px:
            fig.add_trace(go.Scatter(
                x=px, y=py, mode="markers", name="prior base (all runs)", legendgroup="prior",
                showlegend=(fr == 1 and fc == 1), text=pt,
                marker=dict(symbol="circle-open", size=12, color="rgba(110,110,110,0.9)",
                            line=dict(width=2)),
                hovertemplate=f"prior base %{{x:{fmt[stat]}}}<extra>%{{text}}</extra>"),
                row=fr, col=fc)
        fig.add_vline(x=0, line=dict(color="black", width=1), row=fr, col=fc)
        fig.update_xaxes(title_text=STAT_LABEL[stat], title_font=dict(size=10), row=fr, col=fc)
        if stat == "pbias":
            _clip_pbias_axis(fig, metrics, group, rows, pos, labels, fr, fc)
    fig.update_yaxes(tickmode="array", tickvals=list(range(len(rows))), ticktext=rows,
                     range=[-0.6, len(rows) - 0.4], zeroline=False)
    fig.update_yaxes(title_text="gage", col=1)
    for i in range(len(rows) - 1):
        fig.add_hline(y=i + 0.5, line=dict(color="rgba(80,80,80,0.5)" if i == 0
                                           else "rgba(160,160,160,0.25)", width=1))
    fig.update_layout(
        title=(f"Final fit to the other calibration targets, compared across runs "
               f"({', '.join(labels)})<br><sup>top: PBIAS (%), + = model too low; bottom: "
               f"mean error in normalized units, + = model too high. Box = ensemble, "
               f"diamond = base, gray circle = prior base; HRU targets are averaged over "
               f"each gage's contributing HRUs; bottom row of each panel = mean over the "
               f"gages scored in every run</sup>"),
        height=2 * max(480, 40 * len(rows) * max(1, k / 2) + 100) + 180,
        width=max(1500, 300 * ncol), template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.05, x=0),
        margin=dict(t=190, r=30, l=110, b=60))
    return fig


def write_target_comparison(out_dir, runs, order, eval_subdir: str = "calibration_evaluation",
                            log=print) -> dict:
    """Compute (or reuse) every run's target metrics and write the figure and
    tables to ``out_dir``. ``runs`` are the loaded runs from
    :func:`assist.pest.calibration_comparison.load_run_dkge` (source first);
    the gages are every gage any of them scored for 5-day streamflow."""
    out_dir = pl.Path(out_dir)
    gages = sorted({str(g) for r in runs for g in r.table["gage"]})
    metrics = {}
    for r in runs:
        df, note = load_target_metrics(r.run_dir, r.label, gages, out_dir / "runs",
                                       eval_subdir=eval_subdir)
        log(f"{r.label}: {note}")
        metrics[r.label] = df
    by_gage = summarize_by_gage(metrics)
    allg = summarize_all_gages(metrics)
    fig = build_target_figure(metrics, order)
    paths = {"figure": out_dir / TARGETS_HTML, "by_gage": out_dir / TARGETS_BY_GAGE_CSV,
             "all_gages": out_dir / TARGETS_ALL_GAGES_CSV}
    fig.write_html(str(paths["figure"]), include_plotlyjs="cdn")
    by_gage.to_csv(paths["by_gage"], index=False)
    allg.to_csv(paths["all_gages"], index=False)
    return {"figure": fig, "metrics": metrics, "by_gage": by_gage, "all_gages": allg,
            "paths": paths}
