"""HRU-runoff bias check: gage observations vs summed HRU runoff targets.

For each gage with observations, the monthly gage flow is compared with the SUM
of the monthly HRU runoff targets (``hru_streamflow_monthly.nc``) over every HRU
that contributes to the gage (its own segment plus all upstream segments, the
same topology walk as :func:`assist.pest.calibration_evaluation.contributing_hru_positions`).

Units
-----
Both sides are cfs. ``sf_efc.nc`` ``discharge`` is daily mean cfs; the monthly
gage value is the mean of the valid days (an average daily rate for the month).
The HRU target is "monthly average daily rate in cfs" per HRU, so the sum over
HRUs is a flow in cfs and is directly comparable. No unit conversion is applied.

Nested gages
------------
Each gage uses ALL HRUs upstream of it, including HRUs that also drain to
upstream gages. Gages are therefore cumulative and not independent.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from assist.pest.calibration_evaluation import contributing_hru_positions

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def gage_monthly_cfs(discharge, min_valid_fraction: float = 0.8) -> pd.DataFrame:
    """Monthly mean daily discharge per gage (cfs), month-start index.

    ``discharge`` is a DataArray (poi_gage_id, time). A month is kept only when
    at least ``min_valid_fraction`` of its days have a value; otherwise NaN, so
    a partial month is never compared with a full-month HRU target.
    """
    df = discharge.to_pandas().T  # time x gage
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [str(c).strip() for c in df.columns]
    grp = df.groupby(df.index.to_period("M"))
    mean = grp.mean()
    frac = grp.count().div(mean.index.days_in_month, axis=0)
    mean = mean.where(frac >= min_valid_fraction)
    mean.index = mean.index.to_timestamp()
    mean.index.name = "time"
    return mean


def contributing_nhm_ids(gage_id, params) -> tuple[list, set]:
    """``(nhm_ids of HRUs upstream of the gage, upstream segment set)``."""
    positions, segs = contributing_hru_positions(gage_id, params)
    nhm = np.asarray(params["nhm_id"]).astype(int)
    return [int(nhm[p]) for p in positions], segs


def hru_sum_by_gage(runoff, gages, params, min_hru_coverage: float = 1.0):
    """Sum of the HRU runoff target over each gage's contributing HRUs.

    ``runoff`` is a DataArray (time, hru_id) in cfs. A gage is kept only when the
    share of its contributing HRUs that have a target is >= ``min_hru_coverage``.
    Months where any covered HRU is NaN give NaN (a partial sum is not a sum).

    Returns ``(sums, coverage)``: ``sums`` is time x gage; ``coverage`` has one row
    per requested gage (n_contributing_hrus, n_with_target, coverage, status).
    """
    have = set(int(h) for h in runoff["hru_id"].values)
    sums, rows = {}, []
    for g in gages:
        g = str(g).strip()
        try:
            ids, _ = contributing_nhm_ids(g, params)
        except KeyError:
            rows.append((g, 0, 0, np.nan, "gage not in parameter file poi_gage_id"))
            continue
        present = [h for h in ids if h in have]
        cov = len(present) / len(ids) if ids else np.nan
        if not present:
            status = "no contributing HRUs with a runoff target"
        elif cov < min_hru_coverage:
            status = f"skipped: HRU coverage {cov:.0%} < {min_hru_coverage:.0%}"
        else:
            status = "ok" if len(present) == len(ids) else "ok (partial HRU coverage)"
            s = runoff.sel(hru_id=present).sum("hru_id", skipna=False)
            sums[g] = pd.Series(s.values, index=pd.DatetimeIndex(s["time"].values))
        rows.append((g, len(ids), len(present), cov, status))
    coverage = pd.DataFrame(
        rows, columns=["poi_gage_id", "n_contributing_hrus", "n_with_target",
                       "hru_coverage", "status"]
    )
    out = pd.DataFrame(sums)
    if not out.empty:
        # HRU targets are stamped at month start; gage months are month start too.
        out.index = out.index.to_period("M").to_timestamp()
    out.index.name = "time"
    return out, coverage


def build_comparison(gage_obs: pd.DataFrame, hru_sum: pd.DataFrame,
                     runoff_factor: float = 1.0) -> pd.DataFrame:
    """Long table: time, poi_gage_id, gage_obs, hru_sum, diff (hru_sum - obs).

    Only months where both sides have a value are kept. ``runoff_factor``
    multiplies the HRU sum (1.0 = raw targets).
    """
    gages = [g for g in hru_sum.columns if g in gage_obs.columns]
    frames = []
    for g in gages:
        d = pd.DataFrame({"gage_obs": gage_obs[g], "hru_sum": hru_sum[g] * runoff_factor})
        d = d.dropna()
        d["diff"] = d["hru_sum"] - d["gage_obs"]
        d["poi_gage_id"] = g
        d.index.name = "time"
        frames.append(d.reset_index())
    if not frames:
        return pd.DataFrame(columns=["time", "poi_gage_id", "gage_obs", "hru_sum", "diff"])
    out = pd.concat(frames, ignore_index=True)
    return out[["time", "poi_gage_id", "gage_obs", "hru_sum", "diff"]]


def add_comparison_status(coverage: pd.DataFrame, comp: pd.DataFrame) -> pd.DataFrame:
    """Mark gages that passed the HRU-coverage step but have no compared month.

    Adds ``n_compared_months`` and rewrites ``status`` for such gages so every
    requested gage has a visible outcome.
    """
    cov = coverage.copy()
    counts = comp.groupby("poi_gage_id").size() if len(comp) else pd.Series(dtype=int)
    cov["n_compared_months"] = cov["poi_gage_id"].map(counts).fillna(0).astype(int)
    dropped = cov["status"].str.startswith("ok") & (cov["n_compared_months"] == 0)
    cov.loc[dropped, "status"] = "dropped: no month with both gage and target values"
    return cov


def settings_summary(**settings) -> pd.DataFrame:
    """Two-column table (setting, value) recording the choices behind an output."""
    return pd.DataFrame(
        {"setting": list(settings), "value": [str(v) for v in settings.values()]}
    )


def _bias_stats(d: pd.DataFrame) -> pd.Series:
    obs, hru = d["gage_obs"].sum(), d["hru_sum"].sum()
    return pd.Series({
        "n_months": len(d),
        "mean_obs_cfs": d["gage_obs"].mean(),
        "mean_hru_sum_cfs": d["hru_sum"].mean(),
        "mean_diff_cfs": d["diff"].mean(),
        "pbias_pct": 100.0 * d["diff"].sum() / obs if obs else np.nan,
        "hru_to_obs_ratio": hru / obs if obs else np.nan,
        # Multiplier on the HRU sum that would remove the volume bias.
        "implied_factor": obs / hru if hru else np.nan,
    })


def overall_bias(comp: pd.DataFrame) -> pd.DataFrame:
    """One row per gage over all compared months."""
    if comp.empty:
        return pd.DataFrame()
    out = comp.groupby("poi_gage_id").apply(_bias_stats, include_groups=False)
    first = comp.groupby("poi_gage_id")["time"].min().rename("first_month")
    last = comp.groupby("poi_gage_id")["time"].max().rename("last_month")
    return out.join(first).join(last)


def monthly_bias(comp: pd.DataFrame) -> pd.DataFrame:
    """One row per (gage, calendar month 1-12) with the same statistics."""
    if comp.empty:
        return pd.DataFrame()
    c = comp.assign(month=comp["time"].dt.month)
    return c.groupby(["poi_gage_id", "month"]).apply(_bias_stats, include_groups=False)


# ---------------------------------------------------------------------------
# Suggested basin-wide correction factor from the calibration gages
# ---------------------------------------------------------------------------
# A "factor" here is a multiplier on the raw HRU runoff target: gage total / HRU-sum
# total. Every function below works on a comparison built with runoff_factor=1.0.


def read_calibration_gages(metadata_dir, subdomain):
    """``(gage ids with ohm_cal == "yes", whole sheet)`` from the calibration list.

    Same file and flag that ``01_Prepare_observations_gfv2`` uses. Returns
    ``(None, None)`` when ``npoigages_cal_list_<subdomain>.xlsx`` (or ``.xls``) is
    not in ``metadata_dir``.
    """
    for ext in ("xlsx", "xls"):
        p = Path(metadata_dir) / f"npoigages_cal_list_{subdomain}.{ext}"
        if p.exists():
            df = pd.read_excel(p, dtype={"poi_gage_id": str})
            df["poi_gage_id"] = df["poi_gage_id"].str.strip()
            flag = df["ohm_cal"].astype(str).str.strip().str.lower()
            return df.loc[flag == "yes", "poi_gage_id"].tolist(), df
    return None, None


def select_calibration_gages(comp_raw: pd.DataFrame, cal_ids, coverage: pd.DataFrame,
                             min_months: int = 12):
    """Restrict a comparison to the calibration gages with enough months.

    Returns ``(comp_cal, report)``. ``report`` has one row per requested gage with
    its compared-month count and why it was used or left out, so no calibration
    gage disappears silently.
    """
    counts = comp_raw.groupby("poi_gage_id").size() if len(comp_raw) else pd.Series(dtype=int)
    rows = []
    for g in [str(x).strip() for x in cal_ids]:
        n = int(counts.get(g, 0))
        if n >= min_months:
            status = "used"
        elif n > 0:
            status = f"excluded: {n} compared months < MIN_MONTHS_PER_GAGE ({min_months})"
        else:
            r = coverage.loc[coverage["poi_gage_id"] == g, "status"] if len(coverage) else []
            status = r.iloc[0] if len(r) else "no gage observations in sf_efc.nc"
        rows.append((g, n, status))
    report = pd.DataFrame(rows, columns=["poi_gage_id", "n_months", "status"])
    keep = report.loc[report["status"] == "used", "poi_gage_id"]
    return comp_raw[comp_raw["poi_gage_id"].isin(keep)].copy(), report


def gage_factors(comp: pd.DataFrame):
    """Per-gage factors as ratios of sums (total gage / total HRU sum).

    Returns ``(annual, monthly)``: ``annual`` is a Series by gage over all compared
    months; ``monthly`` is gage x calendar month (columns 1-12, NaN where a gage
    has no month of that kind).
    """
    c = comp.assign(month=comp["time"].dt.month)
    g = c.groupby("poi_gage_id")[["gage_obs", "hru_sum"]].sum()
    annual = g["gage_obs"] / g["hru_sum"].where(g["hru_sum"] > 0)
    gm = c.groupby(["poi_gage_id", "month"])[["gage_obs", "hru_sum"]].sum()
    monthly = (gm["gage_obs"] / gm["hru_sum"].where(gm["hru_sum"] > 0)).unstack("month")
    return annual, monthly.reindex(columns=range(1, 13))


def basin_factors(annual: pd.Series, monthly: pd.DataFrame, max_cv: float = 0.30,
                  min_gages: int = 3):
    """Basin-wide factors from the per-gage factors.

    The annual factor is the MEDIAN of the per-gage annual factors, so every gage
    counts once (a large downstream gage does not dominate) and one odd gage does
    not move it. For each calendar month the factor is the median across gages.
    A month is ``reliable`` when at least ``min_gages`` gages have a value and their
    coefficient of variation (std/mean) is at most ``max_cv``. A month that is not
    reliable falls back to the annual factor in ``factor_monthly``.

    Returns ``(annual_factor, table)``; ``table`` is indexed by month 1-12.
    """
    a_med = float(annual.median())
    rows = []
    for m in range(1, 13):
        v = monthly[m].dropna() if m in monthly.columns else pd.Series(dtype=float)
        n = len(v)
        cv = float(v.std(ddof=1) / v.mean()) if n >= 2 and v.mean() > 0 else np.nan
        reliable = bool(n >= min_gages and np.isfinite(cv) and cv <= max_cv)
        med = float(v.median()) if n else np.nan
        rows.append({
            "month": m, "n_gages": n, "median_factor": med,
            "min_factor": float(v.min()) if n else np.nan,
            "max_factor": float(v.max()) if n else np.nan,
            "cv": cv, "reliable": reliable,
            "factor_monthly": med if reliable else a_med,
        })
    return a_med, pd.DataFrame(rows).set_index("month")


def _score(d: pd.DataFrame, factor) -> tuple[float, float]:
    """(pbias %, normalized RMSE) of ``hru_sum * factor`` against the gage.

    ``factor`` is a scalar or a Series indexed by calendar month 1-12.
    """
    f = d["time"].dt.month.map(factor) if isinstance(factor, pd.Series) else factor
    adj = d["hru_sum"] * f
    obs = d["gage_obs"]
    pbias = 100.0 * (adj - obs).sum() / obs.sum()
    nrmse = float(np.sqrt(((adj - obs) ** 2).mean()) / obs.mean())
    return float(pbias), nrmse


def leave_one_gage_out(comp: pd.DataFrame, max_cv: float = 0.30, min_gages: int = 3,
                       current_factor: float | None = None):
    """Out-of-sample check: fit on all gages but one, score on the one left out.

    Methods scored on the held-out gage: ``raw`` (1.0), ``current`` (a fixed
    ``current_factor``, e.g. the 1.83 in notebook 01), ``annual`` and ``monthly``
    (both fitted without that gage). Returns ``(per_gage, summary)``. Needs at
    least three gages; otherwise both are empty.

    Gages are nested (a downstream gage contains upstream HRUs), so the held-out
    gage is not fully independent of the others and this still flatters the fit.
    """
    gages = sorted(comp["poi_gage_id"].unique())
    if len(gages) < 3:
        return pd.DataFrame(), pd.DataFrame()
    rows = []
    for g in gages:
        train = comp[comp["poi_gage_id"] != g]
        test = comp[comp["poi_gage_id"] == g]
        annual, monthly = gage_factors(train)
        a_med, tab = basin_factors(annual, monthly, max_cv, min_gages)
        methods = {"raw": 1.0, "annual": a_med, "monthly": tab["factor_monthly"]}
        if current_factor is not None:
            methods["current"] = float(current_factor)
        for name, f in methods.items():
            pb, rm = _score(test, f)
            rows.append((g, name, pb, rm))
    per_gage = pd.DataFrame(rows, columns=["poi_gage_id", "method", "pbias_pct", "nrmse"])
    summary = (
        per_gage.assign(abs_pbias=per_gage["pbias_pct"].abs())
        .groupby("method")
        .agg(mean_abs_pbias=("abs_pbias", "mean"), mean_nrmse=("nrmse", "mean"))
    )
    return per_gage, summary


def leave_one_out_median_range(annual: pd.Series) -> tuple[float, float]:
    """Lowest and highest annual median when each gage is dropped in turn."""
    if len(annual) < 3:
        return float("nan"), float("nan")
    meds = [float(annual.drop(g).median()) for g in annual.index]
    return min(meds), max(meds)


def recommend_method(summary: pd.DataFrame, min_improvement: float = 0.10) -> str:
    """``"monthly"`` only when it beats ``annual`` by ``min_improvement`` in held-out NRMSE.

    Otherwise ``"annual"``, the simpler correction (also when there are too few
    gages to run the leave-one-out check).
    """
    if summary.empty or not {"annual", "monthly"} <= set(summary.index):
        return "annual"
    a = summary.loc["annual", "mean_nrmse"]
    m = summary.loc["monthly", "mean_nrmse"]
    return "monthly" if a > 0 and (a - m) / a >= min_improvement else "annual"


def monthly_pbias_after(comp: pd.DataFrame, factor) -> pd.DataFrame:
    """Percent bias by gage x calendar month after multiplying the HRU sum by ``factor``.

    ``factor`` is a scalar or a Series indexed by month 1-12. Shows the seasonal
    bias that a correction leaves behind.
    """
    f = comp["time"].dt.month.map(factor) if isinstance(factor, pd.Series) else factor
    c = comp.assign(month=comp["time"].dt.month, adj=comp["hru_sum"] * f)
    g = c.groupby(["poi_gage_id", "month"])[["adj", "gage_obs"]].sum()
    return (100.0 * (g["adj"] - g["gage_obs"]) / g["gage_obs"]).unstack("month").reindex(
        columns=range(1, 13)
    )
