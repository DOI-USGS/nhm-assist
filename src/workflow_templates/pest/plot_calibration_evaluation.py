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
# | `overlap_metrics.csv` | the two overlap metrics for every gage x group |
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
#   in both, and each panel has its own overlap box, so the prior-to-calibrated
#   change in fit reads straight down the page. Archives written before this
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
# simulated ensemble for the sim band (and, later, the overlap metric). Writing
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
# are selected by gage id. An overlap-metrics summary CSV is also written to
# `<out_dir>/overlap_metrics.csv`.

# %%
plot_gages = ce.select_gages(td, poi_gage_id, gage_set=gage_set, gages=gages)
written = ce.plot_calibration_evaluation(td, params, out_dir, plot_gages)

# %% [markdown]
# ## Overlap-metric summary
#
# Two per gage-group overlap metrics, both measured against the **observed**
# noise ensemble's 5-95% band:
#
# - **`band_overlap_pct`** - the fraction of the *simulated* 5-95% band that
#   lies inside the observed band (metric *a*). This is an interval-vs-interval
#   measure: it only asks whether the two ranges occupy the same values, not how
#   the simulated members are distributed within their range.
# - **`member_overlap_pct`** - the fraction of individual *simulated* ensemble
#   members that fall inside the observed band (metric *d*). This is sensitive
#   to *where the mass of the simulated ensemble sits*, not just its outer edge.
#
# Both are also stamped on each plot, and the full table is written to
# `overlap_metrics.csv`. Higher is better for both: the simulated ensemble is
# reproducing the observed target within its own noise.
#
# The combined 5-day plot is broken out in the **table** into two rows,
# `streamflow_5day_low` (the low and ex_low signatures) and
# `streamflow_5day_high` (the pulse/small/large ascending and descending
# signatures), so low- and high-flow performance can be judged separately. The
# 5-day *plot* stays combined.
#
# ### Reading the two numbers together
#
# They usually agree closely. When they **diverge**, the gap is itself
# diagnostic, because it means the simulated ensemble is *lopsided* (skewed, or
# piled up against one edge of its own range) rather than spread evenly:
#
# - **`band_overlap` >> `member_overlap`** (band overlaps, but few members land
#   in range): the simulated range clips the observed band, but most
#   realizations cluster to one side - often just outside the observed band,
#   with only the tail of the ensemble reaching in. The model *can* produce
#   target-like values but typically does not. Read this as a weaker match than
#   the band number alone suggests; look at the plot to see which side the
#   simulated base/line sits on (a consistent high or low bias).
# - **`member_overlap` >= `band_overlap`** (members in range, narrower band
#   footprint): the bulk of the ensemble sits inside the observed band while the
#   simulated band's outer percentiles reach beyond it - a tighter, well-centered
#   ensemble with a few wide realizations. This is generally a *good* sign.
# - **Both low**: the simulated and observed ranges barely share values at all -
#   a structural miss (bias or wrong dynamics) for that target at that gage, not
#   just an ensemble-spread issue. Worth prioritizing when deciding what to
#   recalibrate.
# - **Both high**: the simulated ensemble both overlaps and is centered on the
#   observed band - the target is well reproduced.
#
# Also weigh `n_points`: a 90% overlap over 6 annual points is far weaker
# evidence than 90% over 72 monthly points. And remember these compare against
# the observed *noise* band, not a single true value - a model can score high by
# being appropriately uncertain, so pair the metric with the base line on the
# plot (the calibrated best estimate) when judging fit.

# %%
metrics = ce.collect_overlap_metrics(td, params, plot_gages)
# wide view: band overlap per gage x group (member overlap is in the CSV)
band_wide = metrics.pivot(index="gage", columns="group", values="band_overlap_pct")
print("band overlap % (gage x group); full detail in overlap_metrics.csv")
display(band_wide)
display(metrics)

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
    f"plus {ce.METRICS_CSV}, are in {out_dir}"
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
