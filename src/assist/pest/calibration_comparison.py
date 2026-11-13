"""Compare the change-in-KGE results of several PEST++ IES runs.

One run is the **source**; one or more others are listed as ``compare_to``.
Runs are only comparable when calibration started from the same place, so the
starting parameter values (``parval1``) of every ``compare_to`` run are checked
against the source first. A run whose starting values differ, in name or in
value, is reported and left out of every comparison.

For each run kept, the change in KGE (final minus prior base, see
:mod:`assist.pest.calibration_evaluation`) is read from that run's evaluation
outputs (``dkge_members.csv`` and friends, written by the
``plot_calibration_evaluation`` workflow). If a run has an evaluation archive
(``calib_eval_targets.nc``) but not these files, or they were computed with
different settings, the change is recomputed from the archive into the
comparison's own output folder; the run's folder is never written to. A run
with no archive has to be evaluated first.

Everything is read from files PEST++ IES and the evaluation already wrote; no
model is run.
"""
from __future__ import annotations

import json
import pathlib as pl
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from assist.pest import calibration_evaluation as ce
from assist.pest.build_calibrated_paramfiles import detect_case

EVAL_SUBDIR = "calibration_evaluation"
COMPARISON_SUBDIR = "calibration_comparison"
COMPARISON_HTML = "compare_dkge_summary.html"
COMPARISON_TABLE_CSV = "compare_dkge_by_gage.csv"
COMPARISON_TESTS_CSV = "compare_dkge_paired_tests.csv"
COMPARISON_COMBINED_CSV = "compare_dkge_all_gages.csv"
COMPARISON_CHECKS_CSV = "compare_run_checks.csv"
GROUPS = [ce.DKGE_ALL_GROUP] + [g for g, _p, _l in ce.DKGE_BUCKETS]
RUN_COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b",
              "#e377c2", "#17becf"]


# --------------------------------------------------------------------------- #
# Labels
# --------------------------------------------------------------------------- #
def run_labels(run_dirs, labels=None) -> list:
    """One unique label per run: from ``labels`` where given (list in run
    order, or ``{path: label}``), else the run folder's name. Duplicates get a
    ``_2``, ``_3`` ... suffix."""
    out, seen = [], {}
    for i, d in enumerate(run_dirs):
        lab = None
        if isinstance(labels, dict):
            lab = labels.get(str(d)) or labels.get(pl.Path(d).name)
        elif labels is not None and i < len(labels):
            lab = labels[i]
        lab = str(lab) if lab else pl.Path(d).name
        if lab in seen:
            seen[lab] += 1
            lab = f"{lab}_{seen[lab]}"
        else:
            seen[lab] = 1
        out.append(lab)
    return out


# --------------------------------------------------------------------------- #
# Comparability checks
# --------------------------------------------------------------------------- #
def read_starting_values(run_dir) -> tuple[pd.Series, str]:
    """Starting value (``parval1``) of every parameter, indexed by name, and
    the file it came from: the control file's ``<case>.par_data.csv``, else
    ``starting_par_vals.dat``."""
    run_dir = pl.Path(run_dir)
    case = detect_case(run_dir)
    p = run_dir / f"{case}.par_data.csv"
    if p.is_file():
        head = pd.read_csv(p, nrows=0)
        name_col = "parnme" if "parnme" in head.columns else head.columns[0]
        df = pd.read_csv(p, usecols=[name_col, "parval1"], low_memory=False)
        s = pd.Series(df["parval1"].astype(float).values, index=df[name_col].astype(str))
        return s, p.name
    p = run_dir / "starting_par_vals.dat"
    if p.is_file():
        df = pd.read_csv(p, sep=r"\s+")
        s = pd.Series(df["parval1"].astype(float).values, index=df["parname"].astype(str))
        return s, p.name
    raise FileNotFoundError(f"no {case}.par_data.csv or starting_par_vals.dat in {run_dir}")


def compare_series(ref: pd.Series, other: pd.Series, rtol: float = 1e-9,
                   atol: float = 1e-12) -> dict:
    """Name-by-name comparison of two value series: counts of names only in
    one side, of values that differ beyond ``rtol``/``atol``, the largest
    absolute difference, and up to five differing names."""
    ref = ref[~ref.index.duplicated()]
    other = other[~other.index.duplicated()]
    common = ref.index.intersection(other.index)
    a, b = ref.loc[common].to_numpy(float), other.loc[common].to_numpy(float)
    both_nan = np.isnan(a) & np.isnan(b)
    differ = ~(np.isclose(a, b, rtol=rtol, atol=atol) | both_nan)
    diff_names = list(common[differ][:5])
    return {
        "n_ref": int(len(ref)), "n_other": int(len(other)), "n_common": int(len(common)),
        "only_in_ref": int(len(ref.index.difference(other.index))),
        "only_in_other": int(len(other.index.difference(ref.index))),
        "n_differ": int(differ.sum()),
        "max_abs_diff": float(np.nanmax(np.abs(a - b))) if len(common) else float("nan"),
        "examples": diff_names,
    }


def read_fiveday_obs(run_dir) -> pd.Series:
    """Observed value (``obsval``) of every 5-day streamflow target, from the
    run's ``<case>.obs_data.csv``. These are the observed ``base`` values the
    change in KGE is scored against."""
    run_dir = pl.Path(run_dir)
    case = detect_case(run_dir)
    df = pd.read_csv(run_dir / f"{case}.obs_data.csv", usecols=["obsnme", "obsval"],
                     low_memory=False)
    df = df[df["obsnme"].astype(str).str.startswith("streamflow_5day")]
    return pd.Series(df["obsval"].astype(float).values, index=df["obsnme"].astype(str))


def check_runs(source_dir, compare_to, labels=None) -> pd.DataFrame:
    """Check every ``compare_to`` run against the source.

    **Starting values (decides inclusion).** The ``parval1`` of every
    parameter must match the source's, with the same parameter names. A run
    that fails, or whose starting values cannot be read, gets
    ``include = False``.

    **Observed 5-day values (warning only).** If the observed 5-day targets
    differ, the two runs' changes were scored against different observations,
    which is reported but does not exclude the run.

    Returns one row per run (source first): ``label``, ``run_dir``,
    ``role``, ``include``, ``starting_values`` and ``observed_5day``
    (``same`` / ``DIFFERENT`` / ``unreadable``), and ``message``.
    """
    source_dir = pl.Path(source_dir)
    dirs = [source_dir] + [pl.Path(d) for d in compare_to]
    labs = run_labels(dirs, labels)
    rows = []
    try:
        ref_par, ref_src = read_starting_values(source_dir)
    except Exception as exc:  # noqa: BLE001 - reported to the user
        raise SystemExit(f"cannot read the source run's starting values: {exc}")
    try:
        ref_obs = read_fiveday_obs(source_dir)
    except Exception:  # noqa: BLE001
        ref_obs = None
    rows.append({"label": labs[0], "run_dir": str(source_dir), "role": "source",
                 "include": True, "starting_values": f"reference ({len(ref_par)} parameters, {ref_src})",
                 "observed_5day": "reference" if ref_obs is not None else "unreadable",
                 "message": ""})
    for d, lab in zip(dirs[1:], labs[1:]):
        row = {"label": lab, "run_dir": str(d), "role": "compare_to", "include": False,
               "starting_values": "", "observed_5day": "", "message": ""}
        msgs = []
        if not d.is_dir():
            row.update(starting_values="unreadable",
                       message=f"folder not found: {d}. Not compared.")
            rows.append(row)
            continue
        try:
            par, _src = read_starting_values(d)
            c = compare_series(ref_par, par)
            if c["only_in_ref"] or c["only_in_other"] or c["n_differ"]:
                row["starting_values"] = "DIFFERENT"
                msgs.append(
                    f"Starting values differ from the source: {c['n_differ']} of "
                    f"{c['n_common']} shared parameters have a different parval1 "
                    f"(largest difference {c['max_abs_diff']:.3g}), "
                    f"{c['only_in_ref']} parameters are only in the source and "
                    f"{c['only_in_other']} only in this run"
                    + (f"; e.g. {', '.join(c['examples'])}" if c["examples"] else "")
                    + ". Not compared.")
            else:
                row["starting_values"] = "same"
                row["include"] = True
        except Exception as exc:  # noqa: BLE001 - reported to the user
            row["starting_values"] = "unreadable"
            msgs.append(f"Starting values could not be read ({exc}). Not compared.")
        try:
            obs = read_fiveday_obs(d)
            if ref_obs is None:
                row["observed_5day"] = "unreadable"
            else:
                c = compare_series(ref_obs, obs, rtol=1e-6, atol=1e-9)
                src_g = {n.split(":")[-1] for n in ref_obs.index}
                oth_g = {n.split(":")[-1] for n in obs.index}
                if c["n_differ"]:
                    row["observed_5day"] = "DIFFERENT"
                    msgs.append(
                        f"Observed 5-day values differ from the source at {c['n_differ']} "
                        f"of {c['n_common']} shared targets, so its change in KGE is "
                        f"scored against different observations.")
                elif c["only_in_ref"] or c["only_in_other"]:
                    row["observed_5day"] = "same values, different targets"
                    msgs.append(
                        f"Observed 5-day values match on the {c['n_common']} shared "
                        f"targets, but the target sets differ: {c['only_in_ref']} only "
                        f"in the source, {c['only_in_other']} only in this run "
                        f"(gages only in the source: {len(src_g - oth_g)}, only in this "
                        f"run: {len(oth_g - src_g)}). Gages scored in only one run are "
                        f"left out of the run-vs-source differences and the shared-gage "
                        f"mean.")
                else:
                    row["observed_5day"] = "same"
        except Exception:  # noqa: BLE001
            row["observed_5day"] = "unreadable"
        row["message"] = " ".join(msgs)
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Loading (or computing) each run's change in KGE
# --------------------------------------------------------------------------- #
@dataclass
class RunDKGE:
    """One run's change-in-KGE results."""

    label: str
    run_dir: pl.Path
    table: pd.DataFrame        # dkge_metrics.csv
    members: pd.DataFrame      # dkge_members.csv (long; includes base rows)
    wilcoxon: pd.DataFrame     # dkge_wilcoxon.csv
    settings: dict
    origin: str                # where the numbers came from
    notes: list = field(default_factory=list)


def _read_outputs(folder: pl.Path):
    table = pd.read_csv(folder / ce.DKGE_CSV, dtype={"gage": str})
    members = pd.read_csv(folder / ce.DKGE_MEMBERS_CSV,
                          dtype={"gage": str, "realization": str})
    wil = (pd.read_csv(folder / ce.DKGE_WILCOXON_CSV)
           if (folder / ce.DKGE_WILCOXON_CSV).is_file() else pd.DataFrame())
    return table, members, wil


def _settings_match(found: dict, wanted: dict) -> bool:
    keys = ("min_points_per_month", "min_months", "min_points_bucket")
    return all(found.get(k) == wanted.get(k) for k in keys)


def load_run_dkge(run_dir, label: str, settings: dict, work_dir,
                  eval_subdir: str = EVAL_SUBDIR) -> tuple[RunDKGE | None, str]:
    """A run's change-in-KGE results, and a one-line note of where they came
    from.

    1. If ``<run_dir>/<eval_subdir>`` holds ``dkge_members.csv``,
       ``dkge_metrics.csv`` and ``dkge_settings.json`` computed with the same
       ``settings``, they are used as they are.
    2. Otherwise, if that folder holds the evaluation archive
       (``calib_eval_targets.nc``), the change is recomputed from it and the
       tables are written to ``<work_dir>/<label>/`` (the run folder is not
       touched).
    3. Otherwise ``(None, reason)``: run ``plot_calibration_evaluation`` on
       that run first.
    """
    run_dir = pl.Path(run_dir)
    eval_dir = run_dir / eval_subdir
    needed = [ce.DKGE_CSV, ce.DKGE_MEMBERS_CSV, ce.DKGE_SETTINGS_JSON]
    found = None
    if all((eval_dir / f).is_file() for f in needed):
        found = json.loads((eval_dir / ce.DKGE_SETTINGS_JSON).read_text(encoding="utf-8"))
        if _settings_match(found, settings):
            table, members, wil = _read_outputs(eval_dir)
            if "pbias" in members.columns and "pbias_final_base" in table.columns:
                return (RunDKGE(label, run_dir, table, members, wil, found,
                                f"existing outputs in {eval_dir}"),
                        "used the existing evaluation outputs")
            found = None   # written before PBIAS was added: recompute below
    archive = eval_dir / ce.TARGETS_ARCHIVE
    if not archive.is_file():
        why = ("its evaluation outputs were computed with different settings"
               if found is not None else "it has no dkge_members.csv")
        return None, (f"{why} and there is no {ce.TARGETS_ARCHIVE} in {eval_dir} to "
                      f"recompute from. Run the plot_calibration_evaluation workflow on "
                      f"{run_dir} first.")
    td = ce.load_targets(archive)
    params = ce.load_run_parameters(run_dir)
    poi = [str(x) for x in np.asarray(params["poi_gage_id"])]
    gages = ce.select_gages(td, poi, gage_set="streamflow-targets")
    table, wil, results = ce.collect_dkge_metrics(
        td, params, gages,
        min_points_per_month=settings["min_points_per_month"],
        min_months=settings["min_months"],
        alternative=settings.get("alternative", ce.DKGE_ALTERNATIVE),
        min_points_bucket=settings["min_points_bucket"])
    used = ce.dkge_settings(settings["min_points_per_month"], settings["min_months"],
                            settings["min_points_bucket"],
                            settings.get("alternative", ce.DKGE_ALTERNATIVE),
                            td.final_iteration)
    out = pl.Path(work_dir) / label
    ce.write_dkge_outputs(out, table, wil, results, used)
    table, members, wil = _read_outputs(out)
    why = ("settings differed from this comparison's" if found is not None
           else "no dkge_members.csv yet")
    return (RunDKGE(label, run_dir, table, members, wil, used,
                    f"recomputed from {archive} into {out}"),
            f"recomputed from {ce.TARGETS_ARCHIVE} ({why}); tables written to {out}")


# --------------------------------------------------------------------------- #
# Comparison tables
# --------------------------------------------------------------------------- #
SHARED_LABEL = "shared gages (mean)"


def scored_gages(run: "RunDKGE", group: str) -> set:
    """Gages where the run's base realization has a change in KGE for ``group``."""
    m = run.members
    return set(m.loc[(m["group"] == group) & (m["realization"] == "base"), "gage"].astype(str))


def shared_gages(runs: list, group: str) -> list:
    """Gages scored for ``group`` in every run, sorted."""
    sets = [scored_gages(r, group) for r in runs]
    return sorted(set.intersection(*sets)) if sets else []


def combined_from_members(members: pd.DataFrame, group: str, gages=None,
                          value: str = "dkge") -> dict:
    """The all-gages mean for one group (same definition as
    :func:`assist.pest.calibration_evaluation.combined_dkge`): each member's
    ``value`` averaged over the gages where the base was scored, and the base's
    averaged over the same gages. With ``gages``, only those gages are
    averaged (used for the shared-gage mean, so runs are averaged over the same
    gages).

    ``value`` is ``"dkge"`` (change in KGE) or ``"pbias"`` (final PBIAS). Keys
    are ``<value>`` (Series by member), ``median_<value>``, ``base_<value>``,
    ``base_percentile``, ``n_gages`` and ``n_members``; for ``"pbias"`` also
    ``prior_pbias`` (the prior base's PBIAS averaged over the same gages) and
    ``base_abs_pbias`` / ``prior_abs_pbias`` (means of |PBIAS|, which do not
    let wet and dry gages cancel)."""
    m = members[members["group"] == group]
    if gages is not None:
        m = m[m["gage"].astype(str).isin({str(g) for g in gages})]
    brows = m[m["realization"] == "base"].set_index("gage")
    nan = float("nan")
    out = {value: pd.Series(dtype=float), f"median_{value}": nan, f"base_{value}": nan,
           "base_percentile": nan, "n_gages": int(len(brows)), "n_members": 0}
    if value == "pbias":
        out.update(prior_pbias=nan, base_abs_pbias=nan, prior_abs_pbias=nan)
    if brows.empty or value not in brows.columns:
        return out
    base = brows[value].dropna()
    out["n_gages"] = int(len(base))
    if base.empty:
        return out
    out[f"base_{value}"] = float(base.mean())
    if value == "pbias":
        pr = brows.loc[base.index, "pbias_prior"]
        out["prior_pbias"] = float(pr.mean())
        out["base_abs_pbias"] = float(base.abs().mean())
        out["prior_abs_pbias"] = float(pr.abs().mean())
    ens = m[(m["realization"] != "base") & m["gage"].isin(base.index)]
    if not ens.empty:
        per = ens.pivot_table(index="realization", columns="gage", values=value,
                              aggfunc="first").mean(axis=1, skipna=True).dropna()
        out[value] = per
        out["n_members"] = int(len(per))
        if len(per):
            out[f"median_{value}"] = float(per.median())
            out["base_percentile"] = float((per <= out[f"base_{value}"]).mean() * 100.0)
    return out


def comparison_by_gage(runs: list) -> pd.DataFrame:
    """Per gage and group, each run's base change, ensemble median and base
    percentile side by side, plus each compare run minus the source (the first
    run). Columns are ``<quantity> | <label>`` and ``diff <quantity> | <label>``.
    PBIAS columns (``pbias_final_base``, ``median_pbias``, ``pbias_prior_base``)
    are signed percent bias, positive = model under-predicts; their ``diff``
    is compare minus source of the signed value, and ``diff abs pbias`` is
    ``|compare| - |source|`` (negative = the compare run is less biased)."""
    keep = ["base_dkge", "median_dkge", "base_percentile", "kge_prior_base", "kge_final_base",
            "pbias_prior_base", "pbias_final_base", "median_pbias"]
    wide = None
    for r in runs:
        t = r.table.set_index(["gage", "group"]).reindex(columns=keep)
        t.columns = [f"{c} | {r.label}" for c in t.columns]
        wide = t if wide is None else wide.join(t, how="outer")
    src = runs[0].label
    for r in runs[1:]:
        for c in ("base_dkge", "median_dkge", "pbias_final_base"):
            wide[f"diff {c} | {r.label}"] = wide[f"{c} | {r.label}"] - wide[f"{c} | {src}"]
        wide[f"diff abs pbias_final_base | {r.label}"] = (
            wide[f"pbias_final_base | {r.label}"].abs() - wide[f"pbias_final_base | {src}"].abs())
    return wide.sort_index()


def comparison_combined(runs: list) -> pd.DataFrame:
    """The mean over gages per run and group, twice: over the gages scored in
    **every** run (``gage_set = "shared"``, the like-for-like comparison drawn
    in the figure) and over all the gages each run scored
    (``gage_set = "all scored"``, the run's own all-gages number)."""
    rows = []
    for g in GROUPS:
        shared = shared_gages(runs, g)
        for r in runs:
            for gage_set, gl in (("shared", shared), ("all scored", None)):
                c = combined_from_members(r.members, g, gages=gl)
                p = combined_from_members(r.members, g, gages=gl, value="pbias")
                rows.append({"run": r.label, "group": g, "gage_set": gage_set,
                             **{k: v for k, v in c.items() if k != "dkge"},
                             "base_pbias": p["base_pbias"], "median_pbias": p["median_pbias"],
                             "prior_pbias": p["prior_pbias"],
                             "base_abs_pbias": p["base_abs_pbias"],
                             "prior_abs_pbias": p["prior_abs_pbias"]})
    return pd.DataFrame(rows)


def paired_tests(runs: list, alternative: str = "two-sided") -> pd.DataFrame:
    """For each compare run and group, a Wilcoxon signed-rank test across the
    gages scored in both runs on ``median_dkge(compare) - median_dkge(source)``.
    ``n_better`` counts gages where the compare run's median change is higher.
    The test fields are NaN when it cannot be run (no shared gages, or every
    difference exactly zero)."""
    from scipy.stats import wilcoxon

    src = runs[0]
    rows = []
    for r in runs[1:]:
        for g in GROUPS:
            a = src.table[src.table["group"] == g].set_index("gage")["median_dkge"]
            b = r.table[r.table["group"] == g].set_index("gage")["median_dkge"]
            d = (b - a).dropna()
            row = {"compare": r.label, "source": src.label, "group": g,
                   "n_gages": int(len(d)), "n_better": int((d > 0).sum()),
                   "n_worse": int((d < 0).sum()),
                   "median_difference": float(d.median()) if len(d) else np.nan,
                   "statistic": np.nan, "p_value": np.nan, "alternative": alternative}
            if len(d) and not (d == 0).all():
                res = wilcoxon(d.to_numpy(), alternative=alternative)
                row["statistic"], row["p_value"] = float(res.statistic), float(res.pvalue)
            rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Figure
# --------------------------------------------------------------------------- #
def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


PBIAS_PRIOR_COLOR = "rgba(110,110,110,0.9)"


def gage_order(runs: list) -> list:
    """Gage order used by the comparison figures (bottom to top): the source
    run's all-flows median change in KGE, then gages the source did not score."""
    allg = runs[0].table[runs[0].table["group"] == ce.DKGE_ALL_GROUP]
    order = allg.sort_values("median_dkge", na_position="first")["gage"].astype(str).tolist()
    return order + sorted({str(g) for r in runs for g in r.table["gage"]} - set(order))


def _label_final_kge(fig, runs, rows, shared, pos) -> None:
    """Write each run's final KGE of the base realization as small text in a
    column at the right edge of every change-in-KGE panel, level with that
    run's box, in the run's colour. The ``shared gages (mean)`` row gets the
    mean final KGE over the shared gages. The x range of each panel is widened
    on the right to make room.

    A second KGE axis along the top is not possible: final KGE = prior KGE +
    change, and the prior KGE differs from gage to gage, so the same position
    on the change axis means a different KGE in every row."""
    for c, group in enumerate(GROUPS, start=1):
        vals = []
        for r in runs:
            m = r.members[r.members["group"] == group]["dkge"].dropna()
            vals.extend(m.tolist())
        if not vals:
            continue
        lo, hi = min(min(vals), 0.0), max(max(vals), 0.0)
        span = (hi - lo) or 1.0
        x_text = hi + 0.04 * span
        xs, ys, txt, col, hov = [], [], [], [], []
        for ri, r in enumerate(runs):
            color = RUN_COLORS[ri % len(RUN_COLORS)]
            t = r.table[r.table["group"] == group].set_index("gage")
            for row_i, gage in enumerate(rows):
                if gage == SHARED_LABEL:
                    g = [x for x in shared[group] if x in t.index]
                    kf = t.loc[g, "kge_final_base"].mean() if g else np.nan
                    kp = t.loc[g, "kge_prior_base"].mean() if g else np.nan
                    lab = f"KGE {kf:.2f} (mean)"
                else:
                    if gage not in t.index:
                        continue
                    kf, kp = t.loc[gage, "kge_final_base"], t.loc[gage, "kge_prior_base"]
                    lab = f"KGE {kf:.2f}"
                if not np.isfinite(kf):
                    continue
                xs.append(x_text); ys.append(pos(row_i, ri)); txt.append(lab); col.append(color)
                hov.append(f"{r.label}, {gage}<br>base KGE {kp:.2f} &rarr; {kf:.2f}")
        if xs:
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="text", text=txt, textposition="middle right",
                textfont=dict(size=9, color=col), hovertext=hov, hoverinfo="text",
                showlegend=False, name="final KGE of base"), row=1, col=c)
        fig.update_xaxes(range=[lo - 0.04 * span, hi + 0.42 * span], row=1, col=c)


def build_comparison_figure(runs: list, tests: pd.DataFrame = None) -> go.Figure:
    """Two rows of three panels (all, high and low flows).

    **Top row, change in KGE.** Each gage row holds one box per run, stacked
    and coloured by run, of the ensemble members' change in KGE, with that
    run's base realization as a diamond in the run's colour.

    **Bottom row, final PBIAS (%).** The same layout for each member's final
    percent bias, ``100 * sum(obs - sim) / sum(obs)`` on the same points as
    the KGE (positive = model under-predicts, negative = over-predicts). A gray
    open circle marks the **prior base** PBIAS, which is the same starting
    point for every run because the runs share their starting values; the
    distance from it to a run's diamond is how far calibration moved that
    run's bias. The line at 0 is no bias.

    In both rows the bottom row of each panel is each run's mean over the
    gages scored in every run (so all runs are averaged over the same gages).
    Gages are ordered by the source run's all-flows median change in KGE;
    gages the source did not score come last."""
    src = runs[0]
    order = gage_order(runs)
    rows = [SHARED_LABEL] + order                  # row 0 is drawn at the bottom
    shared = {g: shared_gages(runs, g) for g in GROUPS}
    k = len(runs)
    step = 0.8 / k
    width = step * 0.85

    def pos(row_i, run_i):
        return row_i - (run_i - (k - 1) / 2.0) * step   # first run on top in a row

    def _title(g):
        lab = f"{ce.DKGE_GROUP_LABELS[g]} ({len(shared[g])} shared gages)"
        if tests is None or tests.empty:
            return lab
        t = tests[tests["group"] == g]
        parts = []
        for _, x in t.iterrows():
            ptxt = f"{x['p_value']:.3g}" if np.isfinite(x["p_value"]) else "n/a"
            parts.append(f"{x['compare']}: better at {x['n_better']} of {x['n_gages']}, p = {ptxt}")
        return lab + ("<br><sup>" + "<br>".join(parts) + "</sup>" if parts else "")

    titles = ([f"&Delta;KGE &mdash; {_title(g)}" for g in GROUPS]
              + [f"final PBIAS (%) &mdash; {ce.DKGE_GROUP_LABELS[g]}" for g in GROUPS])
    fig = make_subplots(rows=2, cols=len(GROUPS), shared_yaxes=True,
                        horizontal_spacing=0.04, vertical_spacing=0.09,
                        subplot_titles=titles)
    has_pbias = all("pbias" in r.members.columns for r in runs)

    def draw(value, fig_row, fmt):
        for ri, run in enumerate(runs):
            color = RUN_COLORS[ri % len(RUN_COLORS)]
            mem = run.members
            for c, group in enumerate(GROUPS, start=1):
                m = mem[mem["group"] == group]
                ens = m[m["realization"] != "base"]
                base = m[m["realization"] == "base"].set_index("gage")[value]
                cmb = combined_from_members(mem, group, gages=shared[group], value=value)
                first_box = True
                for row_i, gage in enumerate(rows):
                    vals = (cmb[value].values if gage == SHARED_LABEL
                            else ens.loc[ens["gage"] == gage, value].dropna().values)
                    if not len(vals):
                        continue
                    fig.add_trace(go.Box(
                        x=vals, y=np.full(len(vals), pos(row_i, ri)), orientation="h",
                        width=width, boxpoints=False, name=run.label,
                        legendgroup=run.label,
                        showlegend=(fig_row == 1 and c == 1 and first_box),
                        marker_color=color, fillcolor=_rgba(color, 0.35),
                        line=dict(color=color, width=1.2),
                        hovertemplate=f"{run.label}<br>{gage}<extra></extra>"),
                        row=fig_row, col=c)
                    first_box = False
                bx, by, bt = [], [], []
                for row_i, gage in enumerate(rows):
                    v = cmb[f"base_{value}"] if gage == SHARED_LABEL else base.get(gage, np.nan)
                    if np.isfinite(v):
                        bx.append(v); by.append(pos(row_i, ri)); bt.append(gage)
                if bx:
                    fig.add_trace(go.Scatter(
                        x=bx, y=by, mode="markers", name=f"base, {run.label}",
                        legendgroup=run.label, showlegend=False, text=bt,
                        marker=dict(symbol="diamond", size=9, color=color,
                                    line=dict(color="black", width=1)),
                        hovertemplate=f"{run.label} base %{{x:{fmt}}}<extra>%{{text}}</extra>"),
                        row=fig_row, col=c)

    draw("dkge", 1, "+.2f")
    _label_final_kge(fig, runs, rows, shared, pos)
    if has_pbias:
        draw("pbias", 2, "+.1f")
        # prior base PBIAS: one gray marker per gage row (shared by all runs)
        for c, group in enumerate(GROUPS, start=1):
            px, py, pt = [], [], []
            for row_i, gage in enumerate(rows):
                if gage == SHARED_LABEL:
                    v = combined_from_members(src.members, group, gages=shared[group],
                                              value="pbias")["prior_pbias"]
                else:
                    v = np.nan
                    for r in runs:            # source first; fall back to any run
                        b = r.members[(r.members["group"] == group)
                                      & (r.members["realization"] == "base")
                                      & (r.members["gage"] == gage)]
                        if len(b) and np.isfinite(b["pbias_prior"].iloc[0]):
                            v = float(b["pbias_prior"].iloc[0]); break
                if np.isfinite(v):
                    px.append(v); py.append(row_i); pt.append(gage)
            if px:
                fig.add_trace(go.Scatter(
                    x=px, y=py, mode="markers", name="prior base (all runs)",
                    legendgroup="prior", showlegend=(c == 1), text=pt,
                    marker=dict(symbol="circle-open", size=12, color=PBIAS_PRIOR_COLOR,
                                line=dict(width=2)),
                    hovertemplate="prior base %{x:+.1f}%<extra>%{text}</extra>"),
                    row=2, col=c)
    for c in range(1, len(GROUPS) + 1):
        fig.add_vline(x=0, line=dict(color="gray", dash="dot"), row=1, col=c)
        fig.update_xaxes(title_text="&Delta;KGE (final &minus; prior base)", row=1, col=c)
        fig.add_vline(x=0, line=dict(color="black", width=1), row=2, col=c)
        fig.update_xaxes(title_text="PBIAS % (+ = model too low, &minus; = too high)",
                         row=2, col=c)
    fig.update_yaxes(tickmode="array", tickvals=list(range(len(rows))), ticktext=rows,
                     range=[-0.6, len(rows) - 0.4], zeroline=False)
    fig.update_yaxes(title_text="gage", col=1)
    # thin rules between gage rows, and a darker one above the shared-gages row
    for i in range(len(rows) - 1):
        fig.add_hline(y=i + 0.5, line=dict(color="rgba(80,80,80,0.5)" if i == 0
                                           else "rgba(160,160,160,0.25)", width=1))
    labels = ", ".join(r.label for r in runs)
    note = "" if has_pbias else " (PBIAS row empty: a run's tables predate PBIAS)"
    fig.update_layout(
        title=(f"Change in KGE and final PBIAS, compared across runs ({labels}){note}<br>"
               f"<sup>box = ensemble, diamond = base realization, one colour per run; "
               f"right-hand labels = final KGE of each run's base; "
               f"gray circle = prior base PBIAS; bottom row of each panel = mean over the "
               f"gages scored in every run; source run: {src.label}</sup>"),
        height=2 * max(520, 46 * len(rows) * max(1, k / 2) + 120) + 160,
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.04, x=0),
        margin=dict(t=200, r=30, l=110, b=60))
    return fig


def write_comparison(out_dir, runs: list, checks: pd.DataFrame,
                     alternative: str = "two-sided") -> dict:
    """Write the comparison figure and tables to ``out_dir``. Returns the
    tables and the paths written."""
    out_dir = pl.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_gage = comparison_by_gage(runs)
    combined = comparison_combined(runs)
    tests = paired_tests(runs, alternative=alternative) if len(runs) > 1 else pd.DataFrame()
    fig = build_comparison_figure(runs, tests)
    paths = {
        "figure": out_dir / COMPARISON_HTML,
        "by_gage": out_dir / COMPARISON_TABLE_CSV,
        "combined": out_dir / COMPARISON_COMBINED_CSV,
        "tests": out_dir / COMPARISON_TESTS_CSV,
        "checks": out_dir / COMPARISON_CHECKS_CSV,
    }
    fig.write_html(str(paths["figure"]), include_plotlyjs="cdn")
    by_gage.to_csv(paths["by_gage"])
    combined.to_csv(paths["combined"], index=False)
    tests.to_csv(paths["tests"], index=False)
    checks.to_csv(paths["checks"], index=False)
    return {"figure": fig, "by_gage": by_gage, "combined": combined, "tests": tests,
            "paths": paths}
