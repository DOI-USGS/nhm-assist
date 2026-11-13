# %% [markdown]
# # Calibration-evaluation plots from PEST++ IES output
#
# For every POI gage and every calibration-target group, this notebook plots
# **observed vs simulated** on the target's natural time axis, so you can see
# how well the calibrated ensemble reproduces what it was calibrated to. It
# reads the files PEST++ IES already wrote and **does not run the model**. The
# work is done by the functions in `assist.pest.calibration_evaluation`.
#
# ## What is plotted
#
# | Element | Meaning |
# |---|---|
# | thick black line + dots | **observed** `base` value |
# | gray band + thin black lines | observed 5th-95th percentile range across *all* obs+noise realizations |
# | red solid line | **sim** `base`: the final-iteration base |
# | red dashed line | **sim** `starting`: the iteration-0 base (pre-calibration) |
# | red band + thin red lines | sim 5th-95th percentile range across the final-iteration ensemble |
#
# Every element is a separate **legend entry you can click to toggle on and
# off** (double-click isolates one). The observed/sim base lines, percentile
# lines and bands all **break at the gaps** between calibration years, so
# nothing is drawn across the missing validation (even) water years. In the
# combined 5-day plot the observed base dots take a **different black marker
# shape for each signature group** (color is not used), and a **prior panel**
# (iteration 0, same style) is stacked above the calibrated one.
#
# ## Output files (written to `out_dir`)
#
# | File | Contents |
# |---|---|
# | `calib_eval_targets.nc` | the extracted sim and obs vectors, so the plots can be rebuilt without re-reading the ensembles |
# | `<gage>/calib_eval_<group>_<gage>.html` | one interactive plot per gage per target group |
# | `<gage>/calib_eval_dkge_5day_<gage>.html` | the change-in-KGE figure for a gage with 5-day targets |
# | `dkge_metrics.csv` | the change in continuous monthly KGE for every gage with 5-day targets |
# | `dkge_wilcoxon.csv` | the Wilcoxon signed-rank test on the per-gage median change |
# | `calib_eval_dkge_summary.html` | the change in KGE for all gages in one figure |
#
# The plot groups are `actet_mean_mon`, `recharge_ann`, `soil_moist_ann`,
# `soil_moist_mean_mon`, `runoff_mon`, `swe_monthly`, `streamflow_mon`,
# `streamflow_mean_mon`, and the combined `streamflow_5day` plot.
#
# ## Where the values come from (key policy)
#
# - **Simulated** values are the model-equivalents in `<case>.<iteration>.obs.csv`.
#   `starting` comes from iteration 0, everything else from the chosen iteration.
# - **Observed** values are the noise-sampled ensemble in `<case>.obs+noise.csv`.
#   Observations are aggregated to the gage *per realization first*, then the
#   base value and the 5th/95th percentiles are taken across realizations. The
#   targets are odd (calibration) water years only, so the line and band break
#   at every validation-year gap (detected from the spacing of the obs dates).
# - **Values are matched by observation name** from `<case>.obs_data.csv`, never
#   by position. The checks below confirm every name is present in both ensembles.
# - **HRU targets are averaged over the gage's contributing HRUs**: the HRUs on
#   the gage's own segment plus every segment upstream of it, found from the
#   run's own `parameters.json`. The same HRUs are used for sim and obs.
# - **Streamflow targets** already end in the gage id and are selected directly.
# - **5-day streamflow** is one combined plot per gage, so the 5-day record
#   reads as a continuous time series. Every `streamflow_5day_*` signature group
#   (low, ex_low, pulse, small, large; ascending and descending) is on the same
#   axis. **Observed base dots take a different black marker shape per signature
#   group** (no color); the base line, band and simulated series are the same
#   as every other plot and run across every date.
# - **The 5-day plot is a two-panel stack** sharing the x and y axes (zooming
#   one zooms both). The **bottom** panel is the calibrated plot described
#   above. The **top** panel is the **prior** in the same style: its red solid
#   line is the iteration-0 `base` and its red band is the 5th-95th percentile
#   range of the full **iteration-0 ensemble**. The observed series is the same
#   in both. The prior panel is stamped with the base realization's prior KGE
#   and the calibrated panel with the change in KGE (see "Change-in-KGE
#   metric" below), so the prior-to-calibrated change in fit reads straight
#   down the page. Archives written before this
#   change have no prior ensemble and still get the single calibrated panel;
#   re-run the extract cell to get the stack.
# - Values at or below -9990 (the PEST++ no-data fill) are masked, and the
#   zero-weight `streamflow_nodata` group is skipped.
# - The **final iteration** is auto-detected by default. Runs do not always
#   reach iteration 3, so do not hard-code it.
# - Gages **without a streamflow target** still get the HRU-target plots, built
#   from their contributing HRUs.
#
# ## How to use
#
# 1. Edit the parameters cell and run the notebook top to bottom.
# 2. Read the **Run summary** and **Checks and warnings**. The 5-day check
#    matters: a run made with an older `forward_run.py` has misaligned 5-day
#    simulated values, and those two plots should not be trusted.
# 3. Open the HTML files in `out_dir`, or use the preview cell at the end.

# %% [markdown]
# ## Parameters (edit these)

# %%
# Folder holding the PEST++ IES output (*.pst, *.obs.csv, *.obs_data.csv,
# *.obs+noise.csv, parameters.json).
run_dir = r"D:\path\to\PEST_IES_output"

# PEST++ case name. None = taken from the .pst file in run_dir.
case = None

# Ensemble iteration to use as the "final" one. None = auto-detect.
iteration = None

# Where to write the targets archive and the plots.
# None = <run_dir>/calibration_evaluation.
out_dir = None

# Number of random final-ensemble members to draw, and the seed that makes the
# draw reproducible.
n_random = 10
seed = 0

# Which gages to plot:
#   "all-poi"            every POI gage in the model
#   "streamflow-targets" only gages that had a streamflow calibration target
gage_set = "all-poi"

# Explicit list of gage ids, e.g. ["14138400", "14137002"]. None = use gage_set.
gages = None

# Gage to preview inline at the end. None = the first gage with a streamflow target.
preview_gage = None

# Change-in-KGE metric (5-day streamflow, continuous monthly KGE). The 5-day
# points are averaged to one value per month-year; a month-year is kept only if
# it has at least this many valid 5-day points (a full month holds about 6), and
# a gage is scored only if at least this many month-years are kept.
dkge_min_points_per_month = 3
dkge_min_months = 12
# Wilcoxon alternative across gages: "two-sided" (the median change differs from
# zero), or "greater" (the median change is positive, i.e. calibration helped).
dkge_alternative = "two-sided"
# High- and low-flow buckets are scored on their 5-day points directly; a bucket
# needs at least this many valid points at a gage to get a score.
dkge_min_points_bucket = 30

# %% [markdown]
# ## Setup

# %%
import pathlib as pl
import warnings

import numpy as np
import pandas as pd
from IPython.display import display
from rich.console import Console
from rich.table import Table

warnings.filterwarnings("ignore")
con = Console()

from assist.pest import calibration_evaluation as ce
from assist.pest.build_calibrated_paramfiles import detect_case, detect_final_iteration

run_dir = pl.Path(run_dir)
if not run_dir.exists():
    raise FileNotFoundError(f"run_dir does not exist: {run_dir}")

out_dir = pl.Path(out_dir) if out_dir else run_dir / "calibration_evaluation"

# %% [markdown]
# ## Run summary
#
# What this run is. Nothing here changes the build; it is information for you
# to check before anything is written.

# %%
case = case or detect_case(run_dir)

# iterations that have an obs ensemble
iters_found = sorted(
    int(p.name[len(case) + 1 : -len(".obs.csv")])
    for p in run_dir.glob(f"{case}.*.obs.csv")
    if p.name[len(case) + 1 : -len(".obs.csv")].isdigit()
)
if not iters_found:
    raise FileNotFoundError(f"No {case}.<iteration>.obs.csv files found in {run_dir}")

final_iteration = detect_final_iteration(run_dir, case)
iteration = final_iteration if iteration is None else int(iteration)
if iteration not in iters_found:
    raise SystemExit(f"iteration {iteration} not found; available: {iters_found}")

params = ce.load_run_parameters(run_dir)
nhm_id = [int(x) for x in np.asarray(params["nhm_id"])]
poi_gage_id = [str(x) for x in np.asarray(params["poi_gage_id"])]

obs_data = pd.read_csv(run_dir / f"{case}.obs_data.csv")
obs_data["obsnme"] = obs_data["obsnme"].astype(str)
obs_data["obgnme"] = obs_data["obgnme"].astype(str)
group_counts = obs_data.groupby("obgnme").size().sort_index()

sf_names = obs_data.loc[obs_data["obgnme"].isin(ce.STREAMFLOW_GROUPS), "obsnme"]
cal_gages = sorted({n.split(":")[-1] for n in sf_names} & set(poi_gage_id))

t = Table(title="Run summary", show_header=False)
t.add_column(style="bold")
t.add_column(overflow="fold")
t.add_row("Run folder", str(run_dir))
t.add_row("Case", case)
t.add_row("Iterations found", ", ".join(map(str, iters_found)))
t.add_row("Iteration used", f"{iteration}" + ("  (final)" if iteration == final_iteration else f"  (final is {final_iteration})"))
t.add_row("Observations", f"{len(obs_data)} in {group_counts.size} groups")
t.add_row("Output folder", str(out_dir))
con.print(t)

t = Table(title="Domain (from the run's parameters.json)", show_header=False)
t.add_column(style="bold")
t.add_column(overflow="fold")
t.add_row("HRUs", f"{len(nhm_id)}")
t.add_row("POI gages", f"{len(poi_gage_id)}")
t.add_row("Gages with a streamflow target", f"{len(cal_gages)}: {', '.join(cal_gages) or 'none'}")
con.print(t)

print("Observations per group")
display(group_counts.rename("n_obs").to_frame())

# %% [markdown]
# ### Checks and warnings
#
# - **Name matching.** Every name in `obs_data.csv` must be present in both the
#   simulated and the obs+noise ensemble. Anything missing would plot empty.
# - **5-day alignment.** Older `forward_run.py` files wrote the 5-day streamflow
#   values time-outer while labelling them gage-outer, so each simulated 5-day
#   value sat under the wrong gage/date and the simulated series oscillated
#   instead of tracking the observed one. The fixed script transposes the array
#   to `(poi_gages, time)` first. This check reads the run folder's own
#   `forward_run.py`.

# %%
names_check = ce.check_ensemble_names(run_dir, case, iteration)
five_day = ce.check_forward_run_5day(run_dir)

warns = []
if names_check["missing_in_sim"]:
    warns.append(f"{names_check['missing_in_sim']} observation names are missing from the simulated ensemble; they will plot empty.")
if names_check["missing_in_obs+noise"]:
    warns.append(f"{names_check['missing_in_obs+noise']} observation names are missing from the obs+noise ensemble; they will plot empty.")
if five_day == "missing_fix":
    warns.append(
        "forward_run.py has a streamflow_5day block WITHOUT the (poi_gages, time) transpose. "
        "This run's simulated 5-day values are misaligned, so the streamflow_5day "
        "plots are not trustworthy. Re-run the calibration with the fixed forward run."
    )
elif five_day == "no_forward_run":
    warns.append("No forward_run.py in the run folder, so 5-day alignment could not be checked.")
elif five_day == "no_5day_block":
    warns.append("forward_run.py has no streamflow_5day block; there are no 5-day plots to check.")
if iteration != 3:
    warns.append(
        f"Iteration used is {iteration}, not 3 (the usual). Fine if the run "
        f"stopped early (iterations found: {iters_found}); otherwise check it."
    )
if iteration != final_iteration:
    warns.append(f"You chose iteration {iteration} but the final iteration is {final_iteration}.")
if gages is None and gage_set == "streamflow-targets" and not cal_gages:
    warns.append("gage_set is 'streamflow-targets' but no gage has a streamflow target; nothing will be plotted.")

t = Table(title="Name matching", show_header=False)
t.add_column(style="bold")
t.add_column()
t.add_row("Observation names", f"{names_check['n_obs_names']}")
t.add_row("Missing from simulated ensemble", f"{names_check['missing_in_sim']}")
t.add_row("Missing from obs+noise ensemble", f"{names_check['missing_in_obs+noise']}")
t.add_row("forward_run.py 5-day alignment fix", {
    "ok": "[green]present[/green]",
    "missing_fix": "[bold red]MISSING[/bold red]",
}.get(five_day, five_day))
con.print(t)

if warns:
    for w in warns:
        con.print(f"[bold yellow]WARNING:[/bold yellow] {w}")
else:
    con.print("[green]No warnings.[/green]")

# %% [markdown]
# ## Realizations to evaluate
#
# `starting` is the iteration-0 `base`, `base` is the final-iteration `base`,
# and the rest are random members of the final ensemble. The draw is seeded, so
# the same `seed` always gives the same members.

# %%
plan = ce.choose_realizations(run_dir, case, iteration, n_random=n_random, seed=seed)
display(pd.DataFrame(plan, columns=["label", "parameter iteration", "realization"]).set_index("label"))

# %% [markdown]
# ## Extract the targets
#
# Reads the ensembles and writes `calib_eval_targets.nc` in `out_dir`. It keeps
# the `starting` and `base` realizations for the sim lines, the **full**
# obs+noise ensemble for the observed band, and the **full** final-iteration
# simulated ensemble for the sim band and the change-in-KGE metric. Writing
# both full ensembles makes the archive larger (a few hundred MB) but means the
# plots and metric never need to re-read the PEST csvs.

# %%
targets_path = ce.extract_targets(
    run_dir, case, iteration, plan, out_dir / ce.TARGETS_ARCHIVE
)
td = ce.load_targets(targets_path)
con.print(
    f"Wrote {targets_path}\n"
    f"  obs+noise realizations: {len(td.obs_ens)}   "
    f"sim ensemble realizations: {len(td.sim_ens)}   "
    f"observations: {td.sim.shape[1]}"
)

# %% [markdown]
# ## Build the plots
#
# One HTML per gage per target group, written to `<out_dir>/<gage>/`. HRU
# targets are the mean over each gage's contributing HRUs; streamflow targets
# are selected by gage id. The change-in-KGE tables and summary figure are also
# written to `<out_dir>`.

# %%
plot_gages = ce.select_gages(td, poi_gage_id, gage_set=gage_set, gages=gages)
written = ce.plot_calibration_evaluation(
    td, params, out_dir, plot_gages,
    min_points_per_month=dkge_min_points_per_month,
    min_months=dkge_min_months,
    alternative=dkge_alternative,
    min_points_bucket=dkge_min_points_bucket,
)

# %% [markdown]
# ## Change-in-KGE metric (5-day streamflow)
#
# One number per gage that says whether calibration improved the fit to the
# 5-day streamflow targets, plus where the **base** realization sits among the
# final ensemble. It uses only the odd (calibration) water years that are in
# the PEST++ files, so it measures **calibration improvement, not validation
# skill**. It is computed for all flows and, separately, for high and low flows
# (see below). Other target groups are not scored.
#
# ### The score: KGE on a continuous monthly series
#
# The Kling-Gupta efficiency (Gupta et al., 2009) compares a simulated series
# $S$ with an observed series $O$:
#
# $$\mathrm{KGE} = 1 - \sqrt{(r-1)^2 + (\alpha-1)^2 + (\beta-1)^2}$$
#
# | Component | Definition | Measures | Perfect |
# |---|---|---|---|
# | $r$ | Pearson correlation of $S$ and $O$ | timing and shape | 1 |
# | $\alpha$ | $\sigma_S / \sigma_O$ | variability (too flashy > 1, too flat < 1) | 1 |
# | $\beta$ | $\mu_S / \mu_O$ | volume bias (too wet > 1, too dry < 1) | 1 |
#
# KGE is 1 at best and has no lower limit. KGE > −0.41 means the simulation
# beats using the observed mean as a predictor (Knoben et al., 2019).
#
# ### How the value is calculated, step by step
#
# For one gage, and separately for every realization being scored:
#
# 1. **Collect the 5-day points.** Take every `streamflow_5day_*` target for the
#    gage (all signature groups together). The observed value is the observed
#    `base` (the noise-free observation), the simulated value is the
#    realization's model-equivalent from `<case>.<iteration>.obs.csv`, and the
#    prior value is the iteration-0 `base` from `<case>.0.obs.csv`.
# 2. **Keep matching points only.** A date is used only if the observed, the
#    simulated and the prior values are all present. The realization and the
#    prior are therefore always scored on exactly the same dates.
# 3. **Average to monthly values.** Group the dates by month-year (Oct 1980,
#    Nov 1980, ...) and average the 5-day values in each, for the observed,
#    simulated and prior series alike. A month-year with fewer than
#    `dkge_min_points_per_month` points is dropped (a full month holds about 6).
# 4. **Line the months up in time.** The monthly means form one series running
#    through all the calibration years. The even (validation) years are simply
#    absent; nothing is interpolated across them. A series with fewer than
#    `dkge_min_months` month-years gets no score.
# 5. **Score it.** Compute the KGE above twice on that series: simulated vs
#    observed, and prior vs observed.
# 6. **Take the change.** $\Delta\mathrm{KGE} = \mathrm{KGE}_{\text{realization}} - \mathrm{KGE}_{\text{prior base}}$.
#    Positive means the calibrated model fits the monthly hydrograph better
#    than the pre-calibration model did.
#
# This is the same kind of monthly KGE as the "Monthly" column of the
# streamflow statistics table in notebook 6, with two differences: notebook 6
# averages **daily** values over the gage's **whole record**, while this uses
# the **5-day targets** in the **calibration years only**. Expect the two to be
# close but not identical.
#
# ### From one gage to the ensemble and across gages
#
# - **`base_dkge`** is step 6 for the final `base` realization.
# - **Ensemble distribution.** Steps 1-6 are repeated for every other member of
#   the final ensemble, always against the same single prior base. The base is
#   *not* included in this distribution.
# - **`median_dkge`** is the median of that distribution, and **`dkge_p05`** /
#   **`dkge_p95`** are its 5th and 95th percentiles.
# - **`base_percentile`** is the percent of ensemble members whose
#   $\Delta\mathrm{KGE}$ is at or below the base's. Near 50, the base is a typical
#   member. Near 100, it improved more than almost every member.
# - **Wilcoxon signed-rank test (across gages).** Each gage contributes one
#   number, its `median_dkge`. The test asks whether those medians are centred
#   on zero. `dkge_alternative = "two-sided"` tests for any change, `"greater"`
#   for improvement only. `n_improved` counts gages with a positive median. With
#   few gages the test has little power, so read the per-gage values too.
#
# ### High-flow and low-flow scores
#
# The all-flows score above is driven mostly by high-flow months. Two more
# scores separate the flow regimes, using the EFC signature group of each
# 5-day target. The buckets use the same substring patterns as the phi-factor
# re-weighting:
#
# Each 5-day observation name carries a code `streamflow_5day_<efc>_<limb>`
# (see `assist.common.efc`). `<efc>` is the Environmental Flow Component:
# 1 large flood, 2 small flood, 3 high-flow pulse, 4 low flow, 5 extreme low
# flow. `<limb>` is the hydrograph position: 1 low flow, 2 ascending,
# 3 descending. For a 5-day bin, notebook 01 takes the most frequent daily
# value of each separately, and notebook 03 assigns the signature groups:
#
# | Bucket (`group`) | Signature groups (contain) | Codes |
# |---|---|---|
# | `streamflow_5day_high` | `scnd`: `large_ascnd`, `large_dscnd`, `small_ascnd`, `small_dscnd`, `pulse_ascnd`, `pulse_dscnd` | `1_2`, `1_3`, `2_2`, `2_3`, `3_2`, `3_3` |
# | `streamflow_5day_low` | `_low`: `low`, `ex_low` | `3_1`, `4_1`, `5_1` |
#
# `3_1` is a bin whose most frequent EFC class is a pulse but whose most
# frequent limb is low flow (a mixed bin). Notebook 03 deliberately puts it in
# `low`, by its limb. Buckets follow the **signature group**, so they always
# match the groups PEST++ was calibrated with. A code that notebook 03 does not
# map to one of these groups is counted in the all-flows score but in neither
# bucket.
#
# How a bucket's value is calculated, for one gage and one realization:
#
# 1. **Select the bucket's dates.** Take the gage's 5-day targets whose
#    signature group is in the bucket. Each 5-day date belongs to exactly one
#    signature group, so the two buckets never share a point.
# 2. **Keep matching points only**, exactly as in step 2 above: a date is used
#    only if the observed, simulated and prior values are all present.
# 3. **Score the 5-day points directly.** Compute the same KGE formula on the
#    bucket's 5-day values, for the realization and for the prior base. There
#    is **no monthly averaging** here. A bucket's dates are scattered through
#    the year (low flows mostly in late summer, pulses mostly in winter and
#    spring), so a monthly mean of only those points would not be a real
#    monthly flow. A bucket needs at least `dkge_min_points_bucket` points.
# 4. **Take the change**: $\Delta\mathrm{KGE} = \mathrm{KGE}_{\text{realization}} - \mathrm{KGE}_{\text{prior base}}$,
#    then the ensemble median, the percentiles and the base's percentile as for
#    the all-flows score. The Wilcoxon test is run separately for each bucket.
#
# A KGE inside one flow regime is harsher than the all-flows monthly KGE. The
# bucket covers a narrow range of flows, so a modest error moves $r$ and
# $\alpha$ a lot. Compare a bucket's prior and final values with each other,
# not with the all-flows number.
#
# ### Columns of the table below (`dkge_metrics.csv`)
#
# Up to three rows per gage, one per `group`: `streamflow_5day` (all flows),
# `streamflow_5day_high` and `streamflow_5day_low`.
#
# | Column | Meaning |
# |---|---|
# | `method` | `monthly mean series` (all flows) or `5-day points` (buckets) |
# | `n_months` | month-years scored for the base (all flows only; 0 for buckets) |
# | `n_points` | 5-day points scored for the base |
# | `n_members` | ensemble members with a score (base excluded) |
# | `kge_prior_base` | KGE of the iteration-0 `base` |
# | `kge_final_base` | KGE of the final `base` |
# | `base_dkge` | `kge_final_base − kge_prior_base` |
# | `median_dkge`, `dkge_p05`, `dkge_p95` | median and 5th/95th percentiles of the ensemble's change |
# | `base_percentile` | where `base_dkge` falls in the ensemble's change (0-100) |
# | `pbias_prior_base`, `pbias_final_base` | percent bias of the iteration-0 and final `base`, on the same points as the KGE |
# | `median_pbias`, `pbias_p05`, `pbias_p95` | median and 5th/95th percentiles of the ensemble's final PBIAS |
#
# PBIAS is $100 \times \sum (O - S) / \sum O$, the `hydroeval.pbias` convention
# used in notebook 6: positive means the model under-predicts, negative means it
# over-predicts. It is not plotted here; `compare_calibration_evaluation_plots`
# plots it. `dkge_members.csv` carries each realization's final PBIAS
# (`pbias`) and the prior base's on the same points (`pbias_prior`).
#
# `dkge_wilcoxon.csv` holds the across-gage test, one row per `group`:
# `n_gages`, `n_improved`, `median_of_medians`, `statistic`, `p_value`,
# `alternative`.
#
# ### Where it shows up
#
# - **5-day plot.** The prior panel shows the base's prior KGE. The calibrated
#   panel shows the base's change, its prior → final KGE, its percentile, and
#   the ensemble median (all flows).
# - **`calib_eval_dkge_5day_<gage>.html`.** Left: a histogram of the ensemble's
#   change with lines at zero, the ensemble median and the base. Right: the
#   base's KGE, $r$, $\alpha$ and $\beta$, prior vs final, so you can see which
#   component calibration moved (all flows).
# - **`calib_eval_dkge_summary.html`.** Three panels side by side: all flows,
#   high flows, low flows. Each has one box per gage of the ensemble's change,
#   the base as a black diamond, and that group's Wilcoxon result in the panel
#   title. Gages are in the same order in all three panels. The bottom row of
#   each panel, **`all gages (mean)`** (blue), is the combined score below.
#
# ### Combined score: the mean over all gages
#
# One number per group for the whole domain, drawn as the bottom row of each
# panel of `calib_eval_dkge_summary.html` and listed in the table after the
# Wilcoxon results. How it is calculated, for one group:
#
# 1. **Per gage.** Use the per-gage $\Delta\mathrm{KGE}$ already computed
#    above (all flows, high flows or low flows).
# 2. **Per member.** An ensemble member is the same parameter set at every
#    gage. For each member, average its $\Delta\mathrm{KGE}$ over the gages
#    where it was scored. This gives one domain-average change per member, and
#    the box shows the distribution of those averages.
# 3. **Base.** The diamond is the average of the gages' `base_dkge`.
#    `base_percentile` is the percent of members whose average is at or below
#    it, and `median_dkge` is the median of the members' averages.
#
# Every gage counts equally, whatever its drainage area or record length. Nested
# gages share upstream area, so a large basin with several gages carries more
# weight than its size alone would suggest. A plain mean is pulled by one gage
# with a very large change (common in the low-flow group), so read it next to the
# per-gage rows above it.
#
# ### Reading it
#
# - A change near zero at a gage that already fit well is not a failure; read
#   `kge_prior_base` and `kge_final_base` alongside it.
# - The all-flows score is driven mostly by high-flow months and says little
#   about late-summer low flows. Read the low-flow row for those.
# - The reference is the observed `base`, not a true value, and the ensemble is
#   the PEST++ IES posterior, so the spread of the change reflects posterior
#   parameter uncertainty, not sampling error.

# %%
dkge_table, dkge_wilcoxon, dkge_results = ce.collect_dkge_metrics(
    td, params, plot_gages,
    min_points_per_month=dkge_min_points_per_month,
    min_months=dkge_min_months,
    alternative=dkge_alternative,
    min_points_bucket=dkge_min_points_bucket,
)
display(dkge_table.set_index(["gage", "group"]))
print("Wilcoxon signed-rank test on the per-gage median change, per group")
display(dkge_wilcoxon.set_index("group"))

# Combined score: each member's change averaged over all gages (see above).
dkge_combined = pd.DataFrame([
    {"group": g, **{k: v for k, v in ce.combined_dkge(dkge_table, dkge_results, g).items()
                    if k != "dkge"}}
    for g in dkge_table["group"].unique()
]).set_index("group")
print("Change in KGE averaged over all gages, per group")
display(dkge_combined.round(3))

# %% [markdown]
# ### Worked example for one gage
#
# The intermediate values behind one gage's `base_dkge`, so the number can be
# checked by hand. The gage is `preview_gage` (or the first gage with a 5-day
# score). The first table is the scored monthly series from steps 3-4 (the
# first and last few month-years). The second is the KGE and its components
# from step 5. Recomputing KGE from the `r`, `alpha` and `beta` rows with the
# formula above reproduces the `KGE` row, and `final − prior` in that row is
# `base_dkge`.

# %%
scored = [g for g, r in dkge_results.items() if np.isfinite(r["base_dkge"])]
ex_gage = str(preview_gage) if preview_gage and str(preview_gage) in scored else (scored[0] if scored else None)
if ex_gage is None:
    con.print("[bold yellow]No gage has a 5-day change-in-KGE score; nothing to show.[/bold yellow]")
else:
    ex = dkge_results[ex_gage]
    mb = ex["monthly_base"]
    con.print(
        f"Gage {ex_gage}: {ex['n_months']} month-years scored, "
        f"{int(mb['n_points'].sum())} 5-day points, "
        f"{mb.index.min():%Y-%m} to {mb.index.max():%Y-%m}"
    )
    print("Monthly means used in the score (cfs), first and last 6 month-years")
    display(pd.concat([mb.head(6), mb.tail(6)]).round(2))
    cb = ex["components_base"].copy()
    cb["final − prior"] = cb["final"] - cb["prior"]
    print("KGE and its components for the base realization")
    display(cb.round(3))
    con.print(
        f"base_dkge = {ex['base_kge_final']:.3f} − ({ex['base_kge_prior']:.3f}) = "
        f"{ex['base_dkge']:+.3f};  ensemble median {ex['median_dkge']:+.3f};  "
        f"base at the {ex['base_percentile']:.0f}th percentile of {ex['n_members']} members"
    )

# %% [markdown]
# ## Verification
#
# Every planned gage should have produced plots, and every file should be
# non-empty. Gages with a streamflow target get the combined 5-day plot and the
# monthly streamflow plots on top of the HRU-target plots.

# %%
rows = []
for g in plot_gages:
    paths = written.get(str(g), [])
    rows.append(
        {
            "gage": g,
            "streamflow target": "yes" if g in cal_gages else "no",
            "plots": len(paths),
            "empty files": sum(1 for p in paths if p.stat().st_size == 0),
        }
    )
check = pd.DataFrame(rows).set_index("gage")
display(check)

# Plots from an earlier version of this workflow (for example the old separate
# low/high 5-day plots) are left alone but reported, so they are not mistaken
# for output of this run.
produced = {p for ps in written.values() for p in ps}
stale = sorted(
    p
    for g in plot_gages
    for p in (out_dir / str(g)).glob("calib_eval_*.html")
    if p not in produced
)
if stale:
    con.print(
        f"[bold yellow]WARNING:[/bold yellow] {len(stale)} calib_eval_*.html files in "
        f"{out_dir} were not written by this run (for example {stale[0].name}). They are "
        "left over from an earlier version. Delete them or use a fresh out_dir."
    )

n_plots = int(check["plots"].sum())
ok = n_plots > 0 and (check["plots"] > 0).all() and (check["empty files"] == 0).all()
con.print(
    f"[green]All checks passed.[/green] {n_plots} plots across {len(plot_gages)} gages, "
    f"plus {ce.DKGE_CSV}, are in {out_dir}"
    if ok
    else "[bold red]Some gages produced no plots or empty files; see the table above.[/bold red]"
)

# %% [markdown]
# ## Preview
#
# One gage inline. Pick another with `preview_gage` in the parameters cell, or
# open any of the HTML files above in a browser.

# %%
pg = str(preview_gage) if preview_gage else (cal_gages[0] if cal_gages else plot_gages[0])
figs = ce.build_gage_figures(td, pg, params, nhm_id)
con.print(f"Preview gage {pg}: {', '.join(figs)}")
for key in ("streamflow_5day", "streamflow_mon"):
    if key in figs:
        figs[key].show()
