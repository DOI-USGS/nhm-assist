# %% [markdown]
# # Compare calibration evaluations across PEST++ IES runs
#
# Puts the **change in KGE** of several PEST++ IES runs side by side, gage by
# gage, so you can see which run improved the 5-day streamflow fit more. One run
# is the **source** (`run_dir`); the others are listed in `compare_to`. It reads
# files that PEST++ IES and the `plot_calibration_evaluation` workflow already
# wrote and **does not run the model**. The work is done by the functions in
# `assist.pest.calibration_comparison`.
#
# ## Runs must start from the same parameter values
#
# The change in KGE is measured from each run's own prior base (its
# iteration-0 `base`, which is its starting parameter values, `parval1`). Two
# runs' changes are only comparable when they start from the same place. So,
# **before anything else**, the starting value of every parameter in each
# `compare_to` run is checked against the source, by parameter name:
#
# - **Same names and same values:** the run is compared.
# - **Any parameter missing, added or with a different `parval1`:** a message
#   says what differs and **the run is left out** of every table and plot.
#
# The starting values are read from the run's control file
# (`<case>.par_data.csv`), or from `starting_par_vals.dat` if that is missing.
#
# A second check is a **warning only**: whether the observed 5-day targets
# (`obsval` in `<case>.obs_data.csv`) are the same. If they differ, each run's
# change was scored against different observations, so read the comparison with
# that in mind.
#
# ## Each run must have been evaluated
#
# Every run is expected to have been through the `plot_calibration_evaluation`
# workflow, whose outputs are in `<run>/calibration_evaluation/`
# (`eval_subdir`). For each run:
#
# 1. If that folder has `dkge_members.csv`, `dkge_metrics.csv` and
#    `dkge_settings.json` computed with the same settings as below, they are
#    used as they are.
# 2. Otherwise, if it has the evaluation archive `calib_eval_targets.nc`, the
#    change in KGE is **recomputed from the archive**. This happens for runs
#    evaluated before `dkge_members.csv` existed, or with different settings.
#    The recomputed tables go to `<out_dir>/runs/<label>/`; the run's own
#    folder is **not** written to.
# 3. Otherwise the run is left out, with a message to run the
#    `plot_calibration_evaluation` workflow on it first.
#
# ## Output files (written to `out_dir`)
#
# | File | Contents |
# |---|---|
# | `compare_dkge_summary.html` | the comparison figure: change in KGE (top row) and final PBIAS (bottom row) for all, high and low flows, one box per run in every gage row |
# | `compare_dkge_by_gage.csv` | per gage and group, each run's base change, ensemble median and percentile, and each run minus the source |
# | `compare_dkge_all_gages.csv` | the mean over gages, per run and group, over the shared gages and over all the gages each run scored |
# | `compare_dkge_paired_tests.csv` | per compare run and group, a paired Wilcoxon test against the source across gages |
# | `compare_run_checks.csv` | the starting-value and observation checks for every run |
# | `compare_targets_summary.html`, `compare_targets_*.csv` | the same comparison for the other calibration targets (see "Other calibration targets" below) |
# | `runs/<label>/` | change-in-KGE tables recomputed from an archive, where that was needed |
#
# ## How to use
#
# 1. Run the `plot_calibration_evaluation` workflow on every run you want to
#    compare (at least the extract step, so `calib_eval_targets.nc` exists).
# 2. Edit the parameters cell and run this notebook top to bottom.
# 3. Read the **Checks** table first. Any run marked `include = False` is not in
#    the results below it.

# %% [markdown]
# ## Parameters (edit these)

# %%
# The source run: a folder holding the PEST++ IES output (*.pst,
# *.par_data.csv, *.obs_data.csv, parameters.json) and its
# calibration_evaluation/ folder.
run_dir = r"D:\path\to\PEST_IES_output"

# One or more runs to compare with the source. Each must have the same starting
# parameter values as the source, or it is left out.
compare_to = [
    r"D:\path\to\another\PEST_IES_output",
]

# Labels for the plots and tables, in the order [run_dir, *compare_to].
# None = each run's folder name.
labels = None

# Where to write the comparison. None = <run_dir>/calibration_comparison.
out_dir = None

# Name of the evaluation folder inside each run (as written by
# plot_calibration_evaluation).
eval_subdir = "calibration_evaluation"

# Change-in-KGE settings. These must match what each run was evaluated with, or
# that run's change is recomputed from its archive. The defaults are the
# plot_calibration_evaluation defaults.
dkge_min_points_per_month = 3
dkge_min_months = 12
dkge_min_points_bucket = 30

# Paired Wilcoxon test across gages, compare run vs source: "two-sided" (the
# runs differ), or "greater" (the compare run improved more than the source).
compare_alternative = "two-sided"

# %% [markdown]
# ## Setup

# %%
import pathlib as pl
import warnings

import pandas as pd
from IPython.display import display
from rich.console import Console

warnings.filterwarnings("ignore")
con = Console()

from assist.pest import calibration_comparison as ccmp
from assist.pest import calibration_evaluation as ce
from assist.pest import calibration_target_comparison as ccmp_targets

run_dir = pl.Path(run_dir)
if not run_dir.exists():
    raise FileNotFoundError(f"run_dir does not exist: {run_dir}")
compare_to = [pl.Path(p) for p in (compare_to or [])]
if not compare_to:
    raise SystemExit("compare_to is empty: list at least one run to compare with the source.")
out_dir = pl.Path(out_dir) if out_dir else run_dir / ccmp.COMPARISON_SUBDIR
settings = ce.dkge_settings(
    dkge_min_points_per_month, dkge_min_months, dkge_min_points_bucket, compare_alternative
)

# %% [markdown]
# ## Checks
#
# One row per run, the source first.
#
# - **`starting_values`**: `same` means every parameter has the same `parval1`
#   as the source. `DIFFERENT` or `unreadable` means the run is **not
#   compared** (`include = False`); the message says what differs.
# - **`observed_5day`** (warning only; the run is still compared):
#   - `same`: the observed 5-day targets match the source's exactly.
#   - `same values, different targets`: every target the two runs share has
#     the same value, but one run has targets the other does not, usually
#     because the runs were calibrated to different gages. Gages scored in
#     only one run are left out of the run-vs-source differences and of the
#     shared-gage mean.
#   - `DIFFERENT`: some shared targets have different values, so the runs'
#     changes in KGE were scored against different observations.

# %%
checks = ccmp.check_runs(run_dir, compare_to, labels=labels)
display(checks.set_index("label")[["role", "include", "starting_values", "observed_5day"]])

for _, row in checks.iterrows():
    if row["role"] == "source":
        continue
    if not row["include"]:
        con.print(f"[bold red]NOT COMPARED[/bold red] {row['label']}: {row['message']}")
    elif row["message"]:
        con.print(f"[bold yellow]WARNING[/bold yellow] {row['label']}: {row['message']}")
    else:
        con.print(f"[green]OK[/green] {row['label']}: same starting values and observed 5-day targets.")

kept = checks[checks["include"]]
if len(kept) < 2:
    raise SystemExit(
        "No compare_to run has the same starting values as the source, so there is "
        "nothing to compare. See the messages above."
    )

# %% [markdown]
# ## Load each run's change in KGE
#
# Uses each run's existing evaluation outputs where they match the settings
# above, and otherwise recomputes from its `calib_eval_targets.nc` (see the top
# of the notebook). Recomputing reads the archive and the run's
# `parameters.json`, so it takes about a minute per run.

# %%
runs = []
for _, row in kept.iterrows():
    res, note = ccmp.load_run_dkge(
        row["run_dir"], row["label"], settings, out_dir / "runs", eval_subdir=eval_subdir
    )
    if res is None:
        if row["role"] == "source":
            raise SystemExit(f"The source run cannot be loaded: {note}")
        con.print(f"[bold red]NOT COMPARED[/bold red] {row['label']}: {note}")
        checks.loc[checks["label"] == row["label"], ["include", "message"]] = [False, note]
        continue
    con.print(f"{row['label']}: {note}")
    runs.append(res)

if len(runs) < 2:
    raise SystemExit("Fewer than two runs could be loaded, so there is nothing to compare.")

for r in runs[1:]:
    if r.settings.get("final_iteration") != runs[0].settings.get("final_iteration"):
        con.print(
            f"[yellow]Note:[/yellow] {r.label} was evaluated at iteration "
            f"{r.settings.get('final_iteration')}, the source at "
            f"{runs[0].settings.get('final_iteration')}."
        )

# %% [markdown]
# ## Compare
#
# ### How the comparison is built
#
# Nothing is recomputed here beyond averaging; each run's numbers are the same
# ones its own evaluation reports.
#
# 1. **Per run, per gage.** Each run's change in KGE, `base_dkge`
#    $= \mathrm{KGE}_{\text{final base}} - \mathrm{KGE}_{\text{prior base}}$, and
#    the same change for every member of its final ensemble. The three groups
#    are the same as in the evaluation: all flows (KGE on the continuous monthly
#    series) and high and low flows (KGE on the 5-day points of each bucket).
#    Because the runs share starting values, they share the prior base, so the
#    difference between two runs' changes is the difference between their
#    final fits.
# 2. **Mean over gages.** For each run, each member's change averaged over a
#    set of gages, and the base's change averaged over the same gages. It is
#    computed for two gage sets, listed in `compare_dkge_all_gages.csv` as
#    `gage_set`:
#    - **`shared`**: only the gages scored in **every** run, for that group.
#      All runs are averaged over the same gages, so this is the like-for-like
#      comparison. It is the bottom row of every panel, `shared gages (mean)`,
#      and each panel title gives the number of shared gages.
#    - **`all scored`**: every gage that run scored. This matches the
#      `all gages (mean)` row of that run's own evaluation, but runs calibrated
#      to different gages are averaged over different gages, so do not compare
#      these across runs.
# 3. **Run minus source.** In `compare_dkge_by_gage.csv`, the `diff base_dkge`
#    and `diff median_dkge` columns are compare run minus source, per gage.
#    Positive means the compare run improved more.
# 4. **Paired test.** For each compare run and group, a Wilcoxon signed-rank
#    test across the gages scored in both runs, on the difference in
#    `median_dkge`. `n_better` and `n_worse` count gages where the compare run's
#    median change is higher or lower. With few gages the test has little power,
#    and nested gages are not independent, so read the counts too.
#
# ### Percent bias (bottom row of the figure)
#
# The bottom three panels show each run's **final PBIAS**, the volume bias
# after calibration, for the same three groups and on exactly the same points
# as the change in KGE above:
#
# $$\mathrm{PBIAS} = 100 \times \frac{\sum (O - S)}{\sum O}$$
#
# with $O$ the observed `base` values and $S$ the simulated values. This is the
# same convention as the streamflow statistics table in notebook 6
# (`hydroeval.pbias`): **positive means the model under-predicts** (too little
# water), **negative means it over-predicts** (too much), and 0 is no bias. For
# all flows it is computed on the monthly-mean series used for the KGE, so each
# month-year counts equally; for high and low flows it is computed on the 5-day
# points of the bucket.
#
# The final value is plotted rather than a change, because PBIAS has a sign: a
# gage that moves from −20 % to +20 % has a change of +40 but is no less
# biased. Instead, a **gray open circle** marks the **prior base** PBIAS. It is
# the same for every run, because the runs share their starting values, so the
# distance from the circle to a run's diamond is how far calibration moved that
# run's bias, and which side of 0 it ended on.
#
# The bottom (`shared gages (mean)`) row averages the signed PBIAS over the
# shared gages, so a wet gage and a dry gage can cancel. The mean of |PBIAS|,
# which does not cancel, is in `compare_dkge_all_gages.csv` (`base_abs_pbias`,
# `prior_abs_pbias`). In `compare_dkge_by_gage.csv`, `diff pbias_final_base` is
# the signed difference (compare − source) and `diff abs pbias_final_base` is
# |compare| − |source|: negative means the compare run is less biased at that
# gage.
#
# ### Reading the figure
#
# - Each gage row has one box per run, in the run's colour, stacked in the order
#   of the legend (source on top). A box is that run's ensemble; the diamond in
#   the same colour is that run's base.
# - Gages are ordered by the source run's all-flows median change in KGE, in
#   both rows.
# - Top row: a box to the right of another means that run improved that gage's
#   KGE more. The small labels in a column at the right edge of each panel are
#   the **final KGE of each run's base realization**, level with that run's box
#   and in its colour (hover for prior → final). On the `shared gages (mean)`
#   row it is the mean final KGE over the shared gages. The labels are text, not
#   a second axis: final KGE = prior KGE + change, and the prior KGE differs from
#   gage to gage, so no single KGE scale fits every row.
# - Bottom row: a box closer to the 0 line means that run's volume bias is
#   smaller; compare it with the gray prior circle to see the direction of the
#   change.

# %%
result = ccmp.write_comparison(out_dir, runs, checks, alternative=compare_alternative)

print("Mean over gages, per run and group (compare runs on the 'shared' rows)")
display(result["combined"].set_index(["group", "gage_set", "run"]).round(3))

if not result["tests"].empty:
    print("Paired Wilcoxon test across gages, compare run vs source")
    display(result["tests"].set_index(["compare", "group"]).round(4))

print("Per gage: base change and ensemble median for each run, and run minus source")
cols = [c for c in result["by_gage"].columns
        if c.startswith(("base_dkge", "median_dkge", "pbias_prior_base", "pbias_final_base", "diff"))]
display(result["by_gage"][cols].round(3))

con.print(f"[green]Wrote[/green] {', '.join(p.name for p in result['paths'].values())} to {out_dir}")

# %% [markdown]
# ## Comparison figure

# %%
result["figure"].show()

# %% [markdown]
# ## Other calibration targets
#
# The same comparison for every other calibration target group: monthly and
# mean-monthly streamflow, and the HRU targets (runoff, actual ET, SWE,
# recharge and soil moisture). There is no high/low-flow split here; that only
# applies to the 5-day streamflow. These targets are scored on their **final
# fit**, not on a change, with one statistic per target group.
#
# ### Statistic per target group
#
# | Target group | Values | Statistic |
# |---|---|---|
# | `streamflow_mon`, `streamflow_mean_mon` | gage streamflow, cfs | PBIAS (%) |
# | `runoff_mon` | HRU runoff, cfs | PBIAS (%) |
# | `actet_mean_mon` | actual ET, in/day | PBIAS (%) |
# | `swe_monthly` | SWE, inches | PBIAS (%) |
# | `recharge_ann`, `soil_moist_ann`, `soil_moist_mean_mon` | normalized 0-1 within each HRU | mean error |
#
# - **PBIAS** $= 100 \times \sum (O - S) / \sum O$, the same convention as above
#   and as notebook 6: **positive means the model is too low**, negative too
#   high. For SWE the summer zeros add nothing to either sum, so it is
#   effectively the bias over the snow months.
# - **Mean error** $= \overline{S - O}$, in normalized units: **positive means the
#   model is too high**, e.g. +0.08 is 8 % of the HRU's range above the target.
#   These targets are min-max scaled within each HRU (and, for the
#   mean-monthly soil moisture, within each calendar month), so a percent bias
#   would not be a volume bias; the mean error says where the simulated series
#   sits within its own range instead. **Note the opposite sign to PBIAS.**
#
# ### How a value is calculated, for one run, gage and target group
#
# 1. **Aggregate to the gage**, exactly as in the `plot_calibration_evaluation`
#    plots. For an HRU target, take the **mean over the gage's contributing
#    HRUs** (the HRUs on the gage's own segment and every segment upstream of
#    it) at each time step, for the observed values and for every simulated
#    realization alike. Each HRU counts equally, whatever its area. The monthly
#    streamflow targets are the gage's own series.
# 2. **Pick the observed reference**: the obs+noise ensemble's `base`
#    realization, which is the control-file observation value.
# 3. **Keep matching points only**: a time step is used only where the
#    observed value, the realization and the prior base are all present, so the
#    realization and the prior are scored on the same points. At least 3 points
#    are needed.
# 4. **Score**: the statistic above for the realization (`value`) and for the
#    prior base (`prior_value`) on those points.
#
# This is repeated for every realization of the final ensemble (the boxes) and
# for the `base` realization (the diamonds). The gray open circle is the prior
# base, the same for every run because the runs share their starting values.
# The bottom row of each panel is the mean over the gages that every run
# scored; `compare_targets_all_gages.csv` also gives the means of the absolute
# values (`base_abs`, `prior_abs`), which do not let opposite biases cancel.
#
# PBIAS is at most +100 % (a simulated value of zero) but has no lower limit, so
# one run that grossly over-predicts at one gage would squash every other box.
# When any value falls below −300 %, a PBIAS panel's axis is cut at −300 % and
# each base value beyond the cut is drawn as a **left-pointing triangle** at the
# edge in the run's colour; hover shows the true value, and the tables have it.
#
# The gages are every gage any run has 5-day streamflow targets at, in the same
# order as the change-in-KGE figure. The HRU targets exist at every HRU in both
# runs, so they are scored at all of these gages, even where a run had no
# streamflow target; the monthly streamflow targets only where the run had them.
#
# ### Output files (also in `out_dir`)
#
# | File | Contents |
# |---|---|
# | `compare_targets_summary.html` | the figure: PBIAS panels (top) and mean-error panels (bottom), one box per run in every gage row |
# | `compare_targets_by_gage.csv` | per gage, group and run: base and prior values, ensemble median and 5th/95th percentiles, points scored |
# | `compare_targets_all_gages.csv` | the shared-gage mean per run and group, signed and absolute |
# | `runs/<label>/target_metrics_members.csv` | every realization's value, reused on the next run if the archive has not changed |
#
# Computing the values reads each run's `calib_eval_targets.nc` and
# `parameters.json`, about a minute per run the first time.

# %%
targets = ccmp_targets.write_target_comparison(
    out_dir, runs, ccmp.gage_order(runs), eval_subdir=eval_subdir, log=con.print
)
print("Shared-gage mean per group and run (PBIAS %: + = too low; mean error: + = too high)")
display(targets["all_gages"].set_index(["group", "run"]).round(3))
print("Per gage: base and prior values for each run")
display(
    targets["by_gage"]
    .pivot_table(index=["group", "gage"], columns="run", values=["prior_value", "base_value"])
    .round(3)
)
con.print(f"[green]Wrote[/green] {', '.join(p.name for p in targets['paths'].values())} to {out_dir}")

# %%
targets["figure"].show()
