# %% [markdown]
# # HRU runoff bias check
#
# Compares the **streamflow gage observations** with the **sum of the monthly
# HRU runoff targets** (`hru_streamflow_monthly.nc`) over every HRU that
# contributes to each gage, then shows the bias month by month, per gage.
#
# **Inputs (all already produced by earlier notebooks):**
# - `hru_streamflow_monthly.nc` in `pestpp_ies/observation_data/`, as written by
#   `00_Subset_NHM_baselines_gfv2` (`ensemble_mean`, `lower_bound`, `upper_bound`
#   on `hru_id`). The older `00_Subset_NHM_baselines` layout is not supported.
# - `sf_efc.nc` daily gage discharge (notebook 1, `1_create_streamflow_observations`).
# - `myparam_pest_parval1.param` for the stream network (`tosegment`, `hru_segment`,
#   `poi_gage_segment`, `poi_gage_id`, `nhm_id`).
#
# **Units.** Both quantities are in cfs. The gage value is the mean of the daily
# discharge in each month. The HRU target is a monthly average daily rate in cfs
# per HRU, so summing over HRUs gives cfs. No unit conversion is applied.
#
# **Difference** = HRU runoff sum minus gage observation. Positive = the targets
# are higher than the gage; negative = the targets are low (the case the optional
# bias correction at the end of this notebook is meant to correct).
# `implied_factor` in the tables is the multiplier on the HRU sum that would
# remove the volume bias at each gage (gage total / HRU-sum total).
#
# **Nested gages.** Each gage uses *all* HRUs upstream of it, including HRUs that
# also drain to upstream gages. Gages are cumulative, not independent.

# %%
import os
import warnings

import numpy as np
import pandas as pd
import xarray as xr
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import io
from contextlib import redirect_stdout

with redirect_stdout(io.StringIO()):
    import pywatershed as pws

from rich.console import Console
from rich import pretty

warnings.filterwarnings("ignore")
pretty.install()
con = Console()

from assist.workspace.bridge import (
    resolve_workflow_root,
    resolve_project_notebook_context,
)
from assist.workspace.service import get_active_model_root
from assist.common.assist_utilities import load_subdomain_config
from assist.pest import runoff_bias_check as rbc

root_dir = resolve_workflow_root(cwd=os.getcwd())
project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
if project_context:
    active_model_root = get_active_model_root(
        project_context["workspace_root"], project_context["project_root"].name
    )
    config_root = active_model_root / "config"
else:
    active_model_root = None
    config_root = root_dir

config = load_subdomain_config(config_root)

# %% [markdown]
# ## Settings
# Edit these and re-run from here.
#
# | Setting | Default | Meaning |
# |---|---|---|
# | `RUNOFF_FACTOR` | `1.0` | Multiplier on the HRU runoff sum. `1.0` compares the raw targets, which shows the bias. Set `1.83` to see the targets as written by `01_Prepare_observations_gfv2`. |
# | `RUNOFF_VARIABLE` | `ensemble_mean` | Which variable of `hru_streamflow_monthly.nc` to sum. |
# | `SHOW_BOUNDS` | `True` | Also sum `lower_bound` / `upper_bound` (if in the file) and draw them as a band. |
# | `MIN_VALID_DAY_FRACTION` | `0.8` | A gage month needs at least this share of days with data, else it is left out. |
# | `MIN_HRU_COVERAGE` | `1.0` | Share of a gage's contributing HRUs that must have a target. `1.0` skips gages with any contributing HRU outside the target file. Lower it to keep them (the sum then undercounts). |
# | `GAGES` | `None` | `None` = every gage with observations. Or a list of gage ids. |
#
# **Suggested correction factor** (section near the end; uses the calibration gages only,
# always against the raw targets, whatever `RUNOFF_FACTOR` is):
#
# | Setting | Default | Meaning |
# |---|---|---|
# | `CAL_GAGES` | `None` | `None` = gages with `ohm_cal == "yes"` in `metadata/npoigages_cal_list_<subdomain>.xlsx`, the list notebook 01 uses. Or a list of gage ids. |
# | `MIN_MONTHS_PER_GAGE` | `12` | A calibration gage needs at least this many compared months. 12 is one full seasonal cycle; one year is a weak basis, so raise it (24 or more) if you have the record. |
# | `MAX_MONTHLY_CV` | `0.30` | A calendar month gets its own factor only when the gage-to-gage spread (std / mean of the per-gage factors) is at most this. Other months use the annual factor. |
# | `MIN_GAGES_FOR_MONTHLY` | `3` | Fewest gages needed before a calendar month can have its own factor. |
# | `CURRENT_FACTOR` | `1.83` | A fixed single factor scored alongside the new ones (1.83 was the value formerly hardcoded in `01_Prepare_observations_gfv2`, which no longer applies it). |
# | `MIN_LOO_IMPROVEMENT` | `0.10` | The monthly factors are suggested only if they cut the held-out error (normalized RMSE) by at least this share against the single factor. |
#
# **Applying the correction** (last section before the tables are saved):
#
# | Setting | Default | Meaning |
# |---|---|---|
# | `APPLY_BIAS_CORRECTION` | `False` | `True` writes `adj_mean`, `adj_lower` and `adj_upper` into `hru_streamflow_monthly.nc`, using the monthly factors from the calibration gages. `False` removes any existing `adj_*` variables. Re-run `01_Prepare_observations_gfv2` afterwards. |

# %%
RUNOFF_FACTOR = 1.0
RUNOFF_VARIABLE = "ensemble_mean"
SHOW_BOUNDS = True
MIN_VALID_DAY_FRACTION = 0.8
MIN_HRU_COVERAGE = 1.0
GAGES = None

CAL_GAGES = None
MIN_MONTHS_PER_GAGE = 12
MAX_MONTHLY_CV = 0.30
MIN_GAGES_FOR_MONTHLY = 3
CURRENT_FACTOR = 1.83
MIN_LOO_IMPROVEMENT = 0.10

APPLY_BIAS_CORRECTION = True

# %% [markdown]
# ## Load gage observations, HRU runoff targets and stream network

# %%
obsdir = config["model_dir"] / "pestpp_ies" / "observation_data"
runoff_ds = xr.open_dataset(obsdir / "hru_streamflow_monthly.nc")
runoff_ds.load()
if RUNOFF_VARIABLE not in runoff_ds or "hru_id" not in runoff_ds.dims:
    raise KeyError(
        f"{RUNOFF_VARIABLE!r} on an 'hru_id' dimension was not found in "
        f"hru_streamflow_monthly.nc (variables: {list(runoff_ds.data_vars)}, "
        f"dims: {list(runoff_ds.dims)}). This template expects the file written by "
        "00_Subset_NHM_baselines_gfv2 (ensemble_mean / lower_bound / upper_bound on "
        "hru_id). The older 00_Subset_NHM_baselines writes runoff_mwbm / runoff_min / "
        "runoff_max on nhru and is not supported."
    )
print(runoff_ds[RUNOFF_VARIABLE].attrs.get("units"), runoff_ds[RUNOFF_VARIABLE].dims)

sf_ds = xr.open_dataset(config["nc_files_dir"] / "sf_efc.nc")
discharge = sf_ds["discharge"]
print("discharge units:", discharge.attrs.get("units"))

params = pws.parameters.PrmsParameters.load(
    config["model_dir"] / "myparam_pest_parval1.param"
).parameters

# %%
gage_monthly = rbc.gage_monthly_cfs(discharge, MIN_VALID_DAY_FRACTION)
# Gages with observations: at least one valid month.
gages_with_obs = [g for g in gage_monthly.columns if gage_monthly[g].notna().any()]
if GAGES is not None:
    gages_with_obs = [g for g in gages_with_obs if g in {str(x).strip() for x in GAGES}]
con.print(f"{len(gages_with_obs)} gages with observations")

# %% [markdown]
# ## Sum HRU runoff over each gage's contributing HRUs
# The coverage table lists, per gage, how many contributing HRUs have a target.
# Gages with contributing HRUs outside the target file are handled per
# `MIN_HRU_COVERAGE`. Gages missing from the parameter file are reported and skipped.

# %%
hru_sum, coverage = rbc.hru_sum_by_gage(
    runoff_ds[RUNOFF_VARIABLE], gages_with_obs, params, MIN_HRU_COVERAGE
)
coverage

# %%
bounds_sum = {}
if SHOW_BOUNDS:
    for b in ("lower_bound", "upper_bound"):
        if b in runoff_ds:
            bounds_sum[b], _ = rbc.hru_sum_by_gage(
                runoff_ds[b], gages_with_obs, params, MIN_HRU_COVERAGE
            )
        else:
            con.print(f"[yellow]{b} is not in hru_streamflow_monthly.nc; no band drawn.[/yellow]")
    if len(bounds_sum) == 2:
        con.print("Summed lower_bound / upper_bound found; drawn as a band.")

# %%
comp = rbc.build_comparison(gage_monthly, hru_sum, RUNOFF_FACTOR)
coverage = rbc.add_comparison_status(coverage, comp)
not_compared = coverage[coverage["n_compared_months"] == 0]
settings = rbc.settings_summary(
    RUNOFF_FACTOR=RUNOFF_FACTOR,
    RUNOFF_VARIABLE=RUNOFF_VARIABLE,
    SHOW_BOUNDS=SHOW_BOUNDS,
    MIN_VALID_DAY_FRACTION=MIN_VALID_DAY_FRACTION,
    MIN_HRU_COVERAGE=MIN_HRU_COVERAGE,
    GAGES="all gages with observations" if GAGES is None else list(GAGES),
    CAL_GAGES="ohm_cal == yes in the calibration list" if CAL_GAGES is None else list(CAL_GAGES),
    MIN_MONTHS_PER_GAGE=MIN_MONTHS_PER_GAGE,
    MAX_MONTHLY_CV=MAX_MONTHLY_CV,
    MIN_GAGES_FOR_MONTHLY=MIN_GAGES_FOR_MONTHLY,
    CURRENT_FACTOR=CURRENT_FACTOR,
    MIN_LOO_IMPROVEMENT=MIN_LOO_IMPROVEMENT,
    APPLY_BIAS_CORRECTION=APPLY_BIAS_CORRECTION,
    n_gages_with_obs=len(gages_with_obs),
    n_gages_compared=comp["poi_gage_id"].nunique(),
    n_compared_months=len(comp),
)
print(settings.to_string(index=False))
if len(not_compared):
    con.print(f"[yellow]{len(not_compared)} gage(s) with observations are NOT in the outputs:[/yellow]")
    print(not_compared[["poi_gage_id", "status"]].to_string(index=False))
coverage

# %% [markdown]
# ## Overall bias per gage
# `pbias_pct` = 100 x sum(HRU sum - gage) / sum(gage). Negative = targets low.

# %%
overall = rbc.overall_bias(comp)
overall.round(3)

# %% [markdown]
# ## Bias by calendar month, per gage
# Mean difference (cfs) and percent bias for each gage and calendar month.

# %%
by_month = rbc.monthly_bias(comp)
by_month.round(3)

# %%
if not by_month.empty:
    piv = by_month["pbias_pct"].unstack("month")
    piv.columns = [rbc.MONTH_LABELS[m - 1] for m in piv.columns]
    fig = go.Figure(
        go.Heatmap(
            z=piv.values, x=list(piv.columns), y=list(piv.index),
            colorscale="RdBu", zmid=0, colorbar=dict(title="pbias %"),
        )
    )
    fig.update_layout(
        title="Percent bias by calendar month (HRU runoff sum vs gage)",
        height=max(350, 22 * len(piv) + 150), yaxis=dict(type="category"),
    )
    fig.show()

# %% [markdown]
# ## Time series per gage
# Top panel: gage observation (black) and summed HRU runoff target (red; band
# is the summed lower/upper bound when available). Bottom panel: difference,
# HRU sum minus gage.

# %%
for g in comp["poi_gage_id"].unique():
    d = comp[comp["poi_gage_id"] == g].set_index("time")
    # Reindex to a regular monthly axis so gaps break the lines.
    idx = pd.date_range(d.index.min(), d.index.max(), freq="MS")
    d = d.reindex(idx)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35],
        vertical_spacing=0.06,
    )
    if "lower_bound" in bounds_sum and "upper_bound" in bounds_sum:
        lo = bounds_sum["lower_bound"].get(g)
        hi = bounds_sum["upper_bound"].get(g)
        if lo is not None and hi is not None:
            lo = lo.reindex(idx) * RUNOFF_FACTOR
            hi = hi.reindex(idx) * RUNOFF_FACTOR
            fig.add_trace(go.Scatter(x=idx, y=hi, mode="lines", line=dict(width=0),
                                     showlegend=False), row=1, col=1)
            fig.add_trace(go.Scatter(x=idx, y=lo, mode="lines", line=dict(width=0),
                                     fill="tonexty", fillcolor="rgba(200,0,0,0.15)",
                                     name="HRU sum lower-upper"), row=1, col=1)
    fig.add_trace(go.Scatter(x=idx, y=d["gage_obs"], mode="lines+markers",
                             name="Gage observed", line=dict(color="black", width=1.5),
                             marker=dict(size=4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=idx, y=d["hru_sum"], mode="lines+markers",
                             name="Sum of HRU runoff target",
                             line=dict(color="firebrick", width=1.5),
                             marker=dict(size=4)), row=1, col=1)
    fig.add_trace(go.Bar(x=idx, y=d["diff"], name="HRU sum - gage",
                         marker_color=np.where(d["diff"].fillna(0) >= 0, "firebrick", "royalblue")),
                  row=2, col=1)
    fig.add_hline(y=0, line_width=1, line_color="gray", row=2, col=1)
    row = overall.loc[g]
    fig.update_layout(
        height=600, hovermode="x unified",
        title=(f"Gage {g}: mean diff {row['mean_diff_cfs']:.1f} cfs, "
               f"pbias {row['pbias_pct']:.0f}%, implied factor {row['implied_factor']:.2f} "
               f"(RUNOFF_FACTOR={RUNOFF_FACTOR}, n={int(row['n_months'])} months)"),
        legend=dict(orientation="h", y=-0.1),
    )
    fig.update_yaxes(title_text="Flow (cfs)", row=1, col=1)
    fig.update_yaxes(title_text="Difference (cfs)", row=2, col=1)
    fig.show()

# %% [markdown]
# ## Suggested correction factor (calibration gages)
# The sections above look at every gage. This one answers a narrower question:
# **what multiplier on the HRU runoff targets, applied across the whole basin, would
# remove the bias seen at the calibration gages?** Only the calibration gages are used
# (`ohm_cal == "yes"`), since those are the gages whose observations the calibration
# will see. It always compares against the **raw** targets, so the factors multiply the
# targets directly whatever `RUNOFF_FACTOR` is set to above.
#
# **Method**
# 1. Per gage, factor = total gage flow / total HRU-sum flow over its compared months.
# 2. **Single factor** = the median of the per-gage factors. Each gage counts once, so a
#    large downstream gage does not dominate and one odd gage does not move it.
# 3. **Monthly factors** = for each calendar month, the median across gages. A month is
#    only trusted when the gages agree (spread at most `MAX_MONTHLY_CV`); the other
#    months fall back to the single factor.
# 4. **Leave-one-gage-out check.** Each gage is held out in turn, the factors are fitted on
#    the rest, and the held-out gage is scored. This estimates how the correction does
#    on a gage it was not fitted to, which is what a basin-wide correction needs.
# 5. The monthly factors are suggested only if they beat the single factor in that check
#    by `MIN_LOO_IMPROVEMENT`. Otherwise the single factor is suggested.

# %%
# Always the RAW targets (factor 1.0), so the results are multipliers on the targets.
comp_raw = rbc.build_comparison(gage_monthly, hru_sum, 1.0)
cal_ids, cal_sheet = rbc.read_calibration_gages(
    config["model_dir"] / "metadata", config["subdomain"]
)
if CAL_GAGES is not None:
    cal_ids = [str(g).strip() for g in CAL_GAGES]
elif cal_ids is None:
    raise FileNotFoundError(
        "No npoigages_cal_list_<subdomain>.xlsx in "
        f"{config['model_dir'] / 'metadata'}. Put the calibration list there, or set "
        "CAL_GAGES to a list of gage ids in the Settings cell."
    )
if not cal_ids:
    raise ValueError("No calibration gages: no ohm_cal == 'yes' rows, and CAL_GAGES is empty.")

comp_cal, cal_report = rbc.select_calibration_gages(
    comp_raw, cal_ids, coverage, MIN_MONTHS_PER_GAGE
)
n_cal = comp_cal["poi_gage_id"].nunique()
con.print(f"{n_cal} of {len(cal_ids)} calibration gages can be used")
print(cal_report.to_string(index=False))
if n_cal == 0:
    raise ValueError("None of the calibration gages has enough compared months.")
if n_cal < 3:
    con.print(
        f"[yellow]Only {n_cal} calibration gage(s). The median is a weak summary and the "
        "leave-one-gage-out check needs 3.[/yellow]"
    )

# %% [markdown]
# ### Factor at each calibration gage
# `annual_factor` is the multiplier on the raw HRU runoff that would remove the volume
# bias at that gage. `gagesII` is the reference class from the calibration list, if given.

# %%
annual, monthly = rbc.gage_factors(comp_cal)
a_med, tab = rbc.basin_factors(annual, monthly, MAX_MONTHLY_CV, MIN_GAGES_FOR_MONTHLY)
loo_lo, loo_hi = rbc.leave_one_out_median_range(annual)

gage_tbl = pd.DataFrame(
    {"annual_factor": annual, "n_months": comp_cal.groupby("poi_gage_id").size()}
)
if cal_sheet is not None:
    _info = cal_sheet.drop_duplicates("poi_gage_id").set_index("poi_gage_id")
    for _col in ("poi_name", "gagesII"):
        if _col in _info.columns:
            gage_tbl[_col] = _info[_col].reindex(gage_tbl.index)
con.print(
    f"median {a_med:.2f}  mean {annual.mean():.2f}  range {annual.min():.2f} to "
    f"{annual.max():.2f}  (std/mean {annual.std(ddof=1) / annual.mean():.2f})"
    if n_cal > 1 else f"single gage factor {a_med:.2f}"
)
gage_tbl.round(2)

# %%
fig = go.Figure(go.Bar(x=list(annual.index), y=annual.values, name="Gage factor"))
fig.add_hline(y=a_med, line_color="black", annotation_text=f"median {a_med:.2f}")
fig.add_hline(y=CURRENT_FACTOR, line_dash="dash", line_color="firebrick",
              annotation_text=f"current {CURRENT_FACTOR}", annotation_position="bottom right")
fig.add_hline(y=1.0, line_width=1, line_color="gray")
fig.update_layout(
    title="Factor on the raw HRU runoff target needed to match each calibration gage",
    xaxis=dict(type="category", title="Gage"), yaxis_title="Factor (gage / HRU sum)",
    height=420,
)
fig.show()

# %% [markdown]
# ### Factor by calendar month
# Thin lines are single gages. The black line is the median across gages. Filled
# markers are months the gages agree on (spread at most `MAX_MONTHLY_CV`); open markers
# are months where they do not, and those months use the single factor.

# %%
fig = go.Figure()
for g in monthly.index:
    fig.add_trace(go.Scatter(x=rbc.MONTH_LABELS, y=monthly.loc[g].values, mode="lines",
                             name=str(g), line=dict(width=1), opacity=0.6))
fig.add_trace(go.Scatter(
    x=rbc.MONTH_LABELS, y=tab["median_factor"].values, mode="lines+markers",
    name="Median across gages", line=dict(color="black", width=3),
    marker=dict(size=10, color=np.where(tab["reliable"], "black", "white"),
                line=dict(color="black", width=2)),
))
fig.add_hline(y=a_med, line_color="black", line_dash="dot",
              annotation_text=f"single factor {a_med:.2f}")
fig.add_hline(y=CURRENT_FACTOR, line_dash="dash", line_color="firebrick",
              annotation_text=f"current {CURRENT_FACTOR}", annotation_position="bottom right")
fig.update_layout(
    title="Monthly factor at each calibration gage (open marker = gages disagree)",
    yaxis_title="Factor (gage / HRU sum)", height=480, hovermode="x unified",
)
fig.show()
tab.round(2)

# %% [markdown]
# ### Leave-one-gage-out check
# Each calibration gage is held out, the factors are fitted on the others, and the held-out
# gage is scored. `raw` is no correction, `current` is `CURRENT_FACTOR`, `annual` is the
# single factor, `monthly` is the monthly factors. `pbias_pct` should be near 0 and
# `nrmse` (RMS monthly error / mean gage flow) low. Gages are nested, so a held-out gage
# shares HRUs with the others and this is still a favorable test.

# %%
loo_gage, loo_summary = rbc.leave_one_gage_out(
    comp_cal, MAX_MONTHLY_CV, MIN_GAGES_FOR_MONTHLY, CURRENT_FACTOR
)
method = rbc.recommend_method(loo_summary, MIN_LOO_IMPROVEMENT)
if loo_summary.empty:
    con.print("[yellow]Fewer than 3 calibration gages: no leave-one-gage-out check.[/yellow]")
else:
    print("Held-out score, averaged over gages:")
    print(loo_summary.round(3).to_string())
    print("\nHeld-out percent bias by gage:")
    print(loo_gage.pivot(index="poi_gage_id", columns="method", values="pbias_pct").round(0).to_string())

# %% [markdown]
# ### Bias that is left after the single factor
# Median percent bias by calendar month after applying the single factor. Where this
# is far from 0 the correction is too strong (positive) or too weak (negative) for
# that season, even though the annual volume is right.

# %%
resid = rbc.monthly_pbias_after(comp_cal, a_med)
resid_cur = rbc.monthly_pbias_after(comp_cal, CURRENT_FACTOR)
left = pd.DataFrame(
    {f"after single factor {a_med:.2f}": resid.median(),
     f"after current {CURRENT_FACTOR}": resid_cur.median()}
).T
left.columns = rbc.MONTH_LABELS
left.round(0)

# %% [markdown]
# ### Suggested correction

# %%
suggest = tab[["n_gages", "median_factor", "min_factor", "max_factor", "cv", "reliable"]].copy()
suggest.insert(0, "month_name", rbc.MONTH_LABELS)
suggest["suggested_factor"] = tab["factor_monthly"] if method == "monthly" else a_med

_pct = lambda f: 100.0 * (f - 1.0)  # noqa: E731
con.rule("Suggested correction")
con.print(f"Calibration gages used: {n_cal} ({', '.join(map(str, annual.index))})")
con.print(
    f"Single factor: [bold]{a_med:.2f}[/bold] (raise the HRU runoff targets by "
    f"{_pct(a_med):.0f}%). Gage-to-gage range {annual.min():.2f} to {annual.max():.2f}; "
    + (f"dropping any one gage moves it between {loo_lo:.2f} and {loo_hi:.2f}." if n_cal >= 3 else "")
)
if not loo_summary.empty:
    con.print(
        "Held-out error (normalized RMSE): "
        + ", ".join(f"{m} {loo_summary.loc[m, 'mean_nrmse']:.2f}" for m in loo_summary.index)
    )
if method == "monthly":
    con.print("Method: [bold]monthly factors[/bold] (they beat the single factor in the held-out check).")
    n_rel = int(tab["reliable"].sum())
    if n_rel < 12:
        con.print(
            f"{n_rel} of 12 months have their own factor; "
            + ", ".join(rbc.MONTH_LABELS[m - 1] for m in tab.index[~tab["reliable"]])
            + " use the single factor."
        )
else:
    con.print("Method: [bold]single factor[/bold].")
    if not loo_summary.empty:
        con.print("Monthly factors did not improve the held-out error enough to be worth the added complexity.")
    con.print(
        "Applying the correction (below) still uses the monthly factors; this is "
        "the held-out result for comparison."
    )

print("\nMonthly factors applied when APPLY_BIAS_CORRECTION = True:")
print(
    tab["factor_monthly"]
    .rename(index=dict(zip(tab.index, rbc.MONTH_LABELS)))
    .round(3)
    .to_string()
)

_notes = []
if n_cal < 5:
    _notes.append(f"Only {n_cal} calibration gages: treat the number as approximate.")
_short = gage_tbl.index[gage_tbl["n_months"] < 24].tolist()
if _short:
    _notes.append(f"Gages with under 24 compared months (weak basis): {', '.join(map(str, _short))}.")
_dis = [rbc.MONTH_LABELS[m - 1] for m in tab.index[~tab["reliable"]]]
if _dis:
    _notes.append(f"No consistent factor in {', '.join(_dis)}: the gages disagree.")
if "gagesII" in gage_tbl.columns:
    _cls = gage_tbl["gagesII"].fillna("unclassified").value_counts().to_dict()
    _notes.append(f"Calibration gages by reference class: {_cls}.")
for n in _notes:
    con.print(f"  - {n}")
suggest.round(3)

# %% [markdown]
# ### Apply the monthly factors to the runoff targets (optional)
# With `APPLY_BIAS_CORRECTION = True` this writes three variables into
# `hru_streamflow_monthly.nc`, next to the originals:
#
# | New variable | Computed from |
# |---|---|
# | `adj_mean` | `ensemble_mean` x monthly factor |
# | `adj_lower` | `lower_bound` x monthly factor |
# | `adj_upper` | `upper_bound` x monthly factor |
#
# The factor for each time step is `factor_monthly` for its calendar month (months
# without a reliable factor use the single factor). The raw variables are never
# changed, so re-running this cell does not apply the correction twice. `ensemble_std`
# is not adjusted. With the flag `False`, any existing `adj_*` variables are removed so
# `01_Prepare_observations_gfv2` cannot pick up a stale correction.
#
# After changing the flag, **re-run `01_Prepare_observations_gfv2`**.

# %%
_runoff_path = obsdir / "hru_streamflow_monthly.nc"
_adj_sources = {
    "adj_mean": "ensemble_mean",
    "adj_lower": "lower_bound",
    "adj_upper": "upper_bound",
}
# Release the file handle opened earlier so the file can be replaced on Windows.
runoff_ds.close()
with xr.open_dataset(_runoff_path) as _src:
    _out = _src.load()
_stale = [v for v in _adj_sources if v in _out]
_out = _out.drop_vars(_stale)
_changed = bool(_stale)

if APPLY_BIAS_CORRECTION:
    _months = _out["time"].dt.month.values
    _factor = xr.DataArray(
        tab["factor_monthly"].loc[_months].to_numpy(),
        coords={"time": _out["time"]},
        dims="time",
    )
    _factors_jan_dec = tab["factor_monthly"].loc[range(1, 13)].to_numpy(dtype=float)
    _stamp = pd.Timestamp.now().isoformat(timespec="seconds")
    for _new, _old in _adj_sources.items():
        if _old not in _out:
            con.print(f"[yellow]{_old} is not in the file; {_new} was not written.[/yellow]")
            continue
        _out[_new] = (_out[_old] * _factor).astype(_out[_old].dtype)
        _out[_new].attrs = {
            **_out[_old].attrs,
            "long_name": f"{_old} multiplied by the monthly runoff bias factor",
            "bias_correction": "multiplicative, by calendar month",
            "bias_factors_jan_to_dec": _factors_jan_dec,
            "bias_factor_source": "hru_runoff_bias_check (calibration gages)",
            "bias_factor_created": _stamp,
        }
    _changed = True
    con.print(f"Wrote {[v for v in _adj_sources if v in _out]} to {_runoff_path.name}.")
else:
    con.print(
        "APPLY_BIAS_CORRECTION is False. "
        + (f"Removed {_stale} from {_runoff_path.name}." if _stale else "No change to the runoff file.")
    )

if _changed:
    _tmp = _runoff_path.with_name(_runoff_path.name + ".tmp")
    _out.to_netcdf(_tmp)
    _out.close()
    try:
        os.replace(_tmp, _runoff_path)
    except PermissionError as e:
        _tmp.unlink(missing_ok=True)
        raise PermissionError(
            f"{_runoff_path} is open in another process (for example the kernel of "
            "01_Prepare_observations_gfv2). Close or restart that kernel and re-run this cell."
        ) from e

# %% [markdown]
# ### Read this before using the factor
# - **Few gages, not independent.** The number comes from the calibration gages only,
#   and nested gages share HRUs. The range across gages and the leave-one-out range
#   describe how much the answer moves, not a confidence interval.
# - **The gages may not represent the basin.** If the calibration gages are mostly
#   reference (unregulated) headwater gages, the factor describes those. Regulated or
#   downstream gages can behave differently. To see whether the factor carries over,
#   compare the non-calibration gages in the per-gage sections above, with
#   `RUNOFF_FACTOR` set to the suggested value.
# - **One multiplier assumes the bias is proportional and the same everywhere.** A gage
#   integrates all its HRUs, so this check cannot say which HRUs are wrong, only the
#   average. Where the per-gage factors differ widely, a single factor is a compromise.
# - **The factor closes the gap to gage flow, whatever the cause.** Gage flow can include
#   water the HRU runoff target does not represent, and diversions, storage and
#   regulation change gage flow without the target being wrong. This check cannot tell
#   a biased target from a definition difference.
# - **It reflects the compared period only** (the months with both gage and target data),
#   so wet or dry years in that period affect it.
# - **Seasonal bias remains after a single factor.** See the table of left-over bias
#   above. Months marked as not consistent have no reliable seasonal factor.
# - **Applying it changes the calibration targets, not the model.** In
#   `01_Prepare_observations_gfv2` the `adj_mean` values replace `ensemble_mean` as the
#   observation values; the standard deviation written to `allobs_std.dat` is left
#   unadjusted, so the relative weights of the runoff observations change with it.
# - **Re-run this check** after changing the calibration gage list, the gage record, or
#   the target source, since all three change the factor.

# %% [markdown]
# ## Save tables
# Written next to the observation files.

# %%
out_dir = config["model_dir"] / "pestpp_ies" / "runoff_bias_check"
out_dir.mkdir(parents=True, exist_ok=True)
comp.to_csv(out_dir / "monthly_comparison.csv", index=False)
overall.to_csv(out_dir / "overall_bias_by_gage.csv")
by_month.to_csv(out_dir / "bias_by_calendar_month.csv")
coverage.to_csv(out_dir / "gage_hru_coverage.csv", index=False)
settings.to_csv(out_dir / "settings.csv", index=False)
suggest.to_csv(out_dir / "suggested_correction_factors.csv", index_label="month")
gage_tbl.to_csv(out_dir / "calibration_gage_factors.csv", index_label="poi_gage_id")
monthly.to_csv(out_dir / "calibration_gage_factors_by_month.csv", index_label="poi_gage_id")
cal_report.to_csv(out_dir / "calibration_gage_report.csv", index=False)
if not loo_gage.empty:
    loo_gage.to_csv(out_dir / "leave_one_gage_out.csv", index=False)
print("wrote tables to", out_dir)
