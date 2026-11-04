# %% [markdown]
# # Build calibrated PRMS `.param` files from PEST++ IES output
#
# A PEST++ IES run stores its calibrated parameters as a flat ensemble table
# (`<case>.<iteration>.par.csv`, one row per realization). This notebook turns
# chosen realizations back into classic PRMS `.param` files that pywatershed /
# PRMS can read, by calling the functions in
# `assist.pest.build_calibrated_paramfiles` (the same code the command-line
# tool uses).
#
# ## Output files (written to `out_dir`)
#
# | File | Realization |
# |---|---|
# | `myparam_base.param` | the `base` realization (when the ensemble has one) |
# | `myparam_lowest_nonbase.param` | lowest total phi, excluding `base` |
# | `myparam_lowest_runoff_mon.param` | lowest phi on the `phi_group` group (default `runoff_mon`), excluding `base` |
# | `myparam_lowest_streamflow.param` | lowest *summed* phi across every `phi_groups_prefix` group (default `streamflow_*`, the POI-gage groups), excluding `base`. All-zero groups such as `streamflow_nodata` are skipped automatically |
#
# ## Where the values come from (key policy)
#
# - **Non-calibrated parameters** take their values from the run's **own
#   `parameters.json`** in the run folder. That is the file the forward run
#   consumes, so these files match what the model actually ran.
# - The structural template `.param` is your model's
#   `inputs/source_data/myparam.param` (found from the model directory chosen
#   in the pixi setup). It supplies **only** pyPRMS structure, dimensions and
#   metadata, plus a safety check that it covers the same HRUs and segments as
#   the run. Its values are never used.
# - **Calibrated parameters** come from the chosen realization in
#   `<case>.<iteration>.par.csv`. HRU and segment tags in the column names are
#   looked up by `nhm_id` / `nhm_seg`, not by position.
# - The **final iteration** is used by default and is auto-detected. Runs do not
#   always reach iteration 3 (some stop at 2), so do not hard-code it.
# - Forward-run guardrail clips are *not* baked in; they re-apply at model run.
#
# ## How to use
#
# 1. Edit the parameters cell and run the notebook top to bottom.
# 2. Read the **Domain & run summary**. It tells you what the run is and
#    whether your model's template matches it.
# 3. The build still stops with an error if the template's `nhm_id` / `nhm_seg`
#    arrays do not match the run exactly.

# %% [markdown]
# ## Parameters (edit these)

# %%
# Folder holding the PEST++ IES output (*.pst, *.par.csv, *.phi.*.csv, parameters.json).
run_dir = r"D:\path\to\PEST_IES_output"

# Ensemble iteration to use. None = auto-detect the final iteration.
iteration = None

# Where to write the .param files. None = write into run_dir.
out_dir = None

# PEST++ case name. None = taken from the .pst file in run_dir.
case = None

# Observation group used for the "lowest_<group>" file. None = skip that file.
phi_group = "runoff_mon"

# Prefix of the groups summed for the "lowest_streamflow" file. None = skip it.
phi_groups_prefix = "streamflow_"

# Structural template .param. None = use the model directory you configured in
# the pixi setup: <model_dir>/inputs/source_data/myparam.param.
# Set a path here only to override that.
starting_param = None

# %% [markdown]
# ## Setup

# %%
import os
import pathlib as pl
import argparse
import json
import warnings

import numpy as np
import pandas as pd
from IPython.display import display
from rich.console import Console
from rich.table import Table

warnings.filterwarnings("ignore")
con = Console()

from pyPRMS import ParameterFile, MetaData
from assist.pest import build_calibrated_paramfiles as bcp
from assist.pest.build_calibrated_paramfiles import (
    build_param_files,
    detect_case,
    detect_final_iteration,
    pick_realizations,
    pick_realizations_by_group,
    pick_realizations_by_groups,
    resolve_groups,
)
from assist.workspace.bridge import resolve_project_notebook_context
from assist.workspace.service import get_active_model_root

run_dir = pl.Path(run_dir)
md = MetaData().metadata
if not run_dir.exists():
    raise FileNotFoundError(f"run_dir does not exist: {run_dir}")

# The model directory chosen in the pixi setup (the project's active model).
# It is found from the project this notebook sits in.
project_context = resolve_project_notebook_context(cwd=os.getcwd())
model_dir = None
if project_context:
    model_dir = get_active_model_root(
        project_context["workspace_root"], project_context["project_root"].name
    )

# Structural template: your override, or <model_dir>/inputs/source_data/myparam.param
if starting_param is not None:
    starting_param = pl.Path(starting_param)
    chosen_how = "set by you (starting_param)"
else:
    if model_dir is None:
        raise FileNotFoundError(
            "Could not find your nhm-assist project from where this notebook "
            f"runs ({os.getcwd()}), so the model directory is unknown. Set "
            "starting_param in the parameters cell to your model's "
            "inputs/source_data/myparam.param."
        )
    starting_param = model_dir / "inputs" / "source_data" / "myparam.param"
    chosen_how = f"from your configured model directory ({model_dir})"
if not starting_param.is_file():
    raise FileNotFoundError(
        f"Template .param not found. Expected: {starting_param}\n"
        "It comes from the model directory chosen in the pixi setup. To use a "
        "different file, set starting_param in the parameters cell."
    )

# %% [markdown]
# ## Domain & run summary
#
# What this run is, and which template will be used. Nothing here changes the
# build. It is information for you to check before files are written.

# %%
case = case or detect_case(run_dir)

# iterations that have an ensemble file
iters_found = sorted(
    int(p.name[len(case) + 1 : -len(".par.csv")])
    for p in run_dir.glob(f"{case}.*.par.csv")
    if p.name[len(case) + 1 : -len(".par.csv")].isdigit()
)
final_iteration = detect_final_iteration(run_dir, case)
iteration = final_iteration if iteration is None else int(iteration)
if iteration not in iters_found:
    raise SystemExit(f"iteration {iteration} not found; available: {iters_found}")

ens = bcp._load_ensemble(run_dir, case, iteration)
has_base = "base" in ens.index

# domain from the run's own parameters.json
with open(run_dir / "parameters.json") as f:
    pj = json.load(f)
run_id, run_seg = bcp._read_run_ids(run_dir)
n_poi = len(pj.get("poi_gage_id", []))

# calibrated parameters in the ensemble
cal_names = sorted({c.split(":")[0] for c in ens.columns})

# phi groups present at this iteration
g_table = bcp._read_group_table(run_dir, case, iteration)
avail_groups = [c for c in g_table.columns if c not in bcp._GROUP_META]
has_phi_group = (phi_group is None) or (phi_group in avail_groups)
sf_groups = [c for c in avail_groups if phi_groups_prefix and c.startswith(phi_groups_prefix)]
has_sf_groups = (phi_groups_prefix is None) or bool(sf_groups)

t = Table(title="Run summary", show_header=False)
t.add_column(style="bold")
t.add_column(overflow="fold")
t.add_row("Run folder", str(run_dir))
t.add_row("Case", case)
t.add_row("Iterations found", ", ".join(map(str, iters_found)))
t.add_row("Iteration used", f"{iteration}" + ("  (final)" if iteration == final_iteration else f"  (final is {final_iteration})"))
t.add_row("Realizations in ensemble", f"{len(ens)}")
t.add_row("'base' present", "yes" if has_base else "NO")
con.print(t)

t = Table(title="Domain (from the run's parameters.json)", show_header=False)
t.add_column(style="bold")
t.add_column()
t.add_row("HRUs", f"{len(run_id)}")
t.add_row("Segments", f"{len(run_seg)}")
t.add_row("nhm_id range", f"{run_id.min()} - {run_id.max()}")
t.add_row("nhm_seg range", f"{run_seg.min()} - {run_seg.max()}")
t.add_row("POI gages", f"{n_poi}")
con.print(t)

t = Table(title="Calibrated parameters (from the ensemble)", show_header=False)
t.add_column(style="bold")
t.add_column(overflow="fold")
t.add_row("Calibrated PRMS parameters", f"{len(cal_names)}")
t.add_row("Calibrated values per realization", f"{ens.shape[1]}")
t.add_row("Parameter names", ", ".join(cal_names))
con.print(t)

# %% [markdown]
# ### Structural template `.param`
#
# The template is your model's `inputs/source_data/myparam.param`, found from
# the model directory chosen in the pixi setup (override with `starting_param`).
# It is used **only** for pyPRMS structure (dimensions, metadata, parameter
# list) and for the safety check below. **No values are ever taken from it.**
# The check: its `nhm_id` and `nhm_seg` arrays must match the run's
# `parameters.json` exactly.

# %%
def compare_template(path):
    """Return (n_hru, n_seg, exact_match) for the template .param."""
    cid, cseg = bcp._param_ids(pl.Path(path), md)
    exact = bool(np.array_equal(cid, run_id) and np.array_equal(cseg, run_seg))
    return len(cid), len(cseg), exact


n_hru_t, n_seg_t, exact = compare_template(starting_param)
t = Table(title="Structural template", show_header=False)
t.add_column(style="bold")
t.add_column(overflow="fold")
t.add_row("Template used", str(starting_param))
t.add_row("How selected", chosen_how)
t.add_row("Template HRUs / segments", f"{n_hru_t} / {n_seg_t}")
t.add_row("Run HRUs / segments", f"{len(run_id)} / {len(run_seg)}")
t.add_row(
    "nhm_id AND nhm_seg match the run exactly",
    "[green]YES[/green]" if exact else "[bold red]NO - the build will stop[/bold red]",
)
con.print(t)
if not exact:
    con.print(
        "[bold red]The run folder's domain differs from your configured model.[/bold red] "
        "Check that run_dir and the configured model belong together, or set "
        "starting_param to the .param for this run's domain."
    )

# %% [markdown]
# ### Checks and warnings

# %%
warns = []
if iteration != 3:
    warns.append(
        f"Iteration used is {iteration}, not 3 (the usual). Fine if the run "
        f"stopped early (iterations found: {iters_found}); otherwise check it."
    )
if iteration != final_iteration:
    warns.append(f"You chose iteration {iteration} but the final iteration is {final_iteration}.")
if not has_base:
    warns.append("No 'base' realization in the ensemble; myparam_base.param will not be written.")
if phi_group is not None and phi_group not in avail_groups:
    warns.append(f"Phi group '{phi_group}' is missing. The lowest_{phi_group} file cannot be built.")
if phi_groups_prefix is not None and not sf_groups:
    warns.append(f"No phi groups start with '{phi_groups_prefix}'. The summed-streamflow file cannot be built.")

if warns:
    for w in warns:
        con.print(f"[bold yellow]WARNING:[/bold yellow] {w}")
else:
    con.print("[green]No warnings.[/green]")

# %% [markdown]
# ## Rankings preview
#
# Lowest-phi realizations at the chosen iteration. `base` is shown here when it
# ranks, but the non-base files below always take the lowest *non-base* member.

# %%
n_show = 10
tot = pick_realizations(run_dir, case, iteration, n=n_show)
print(f"{n_show} lowest TOTAL phi")
display(tot.rename("phi").to_frame())

if phi_group is not None and phi_group in avail_groups:
    grp = pick_realizations_by_group(run_dir, case, iteration, phi_group, n=n_show)
    print(f"{n_show} lowest '{phi_group}' phi")
    display(grp.rename("phi").to_frame())

if phi_groups_prefix is not None and sf_groups:
    sf_used = resolve_groups(run_dir, case, iteration, prefix=phi_groups_prefix)
    print(f"Summed-group ranking uses {len(sf_used)} groups: {', '.join(sf_used)}")
    sf = pick_realizations_by_groups(run_dir, case, iteration, sf_used, n=n_show)
    print(f"{n_show} lowest SUMMED '{phi_groups_prefix}*' phi")
    display(sf.rename("phi").to_frame())

# %% [markdown]
# ## Build the `.param` files
#
# Realizations are chosen with the same selection logic as the command-line
# tool, so file names are identical. The domain check inside `build_param_files`
# still stops the build if the template does not match.

# %%
sel = argparse.Namespace(
    reals=None,
    best=None,
    phi_group=phi_group,
    phi_groups=None,
    phi_groups_prefix=phi_groups_prefix,
    phi_groups_label=None,
)
targets = bcp._resolve_targets(sel, run_dir, case, iteration)
con.print("Targets (realization -> file):")
for rid, fname in targets:
    con.print(f"  {rid} -> {fname}")

out_path_dir = pl.Path(out_dir) if out_dir else run_dir
written = build_param_files(
    targets,
    run_dir=run_dir,
    starting_param=starting_param,
    case=case,
    iteration=iteration,
    out_dir=out_path_dir,
)

# %% [markdown]
# ## Post-build verification
#
# Each written file is re-read and compared against its sources: calibrated
# values against the ensemble row, every other parameter against the run's
# `parameters.json`.

# %%
# Tolerance: pyPRMS stores float32 and writes a fixed number of decimals, so
# tiny parameters (e.g. jh_coef, smidx_coef ~1e-3) differ from the float64
# ensemble value by ~5e-8. An absolute tolerance of 1e-6 absorbs that and
# still catches a wrong value or a misplaced slot.
RTOL, ATOL = 1e-4, 1e-6
run_ds = bcp._run_param_dataset(run_dir)
rows = []
for (rid, fname), path in zip(targets, written):
    pf = ParameterFile(str(path), metadata=md)
    hru_pos = {v: i for i, v in enumerate(np.asarray(pf.get("nhm_id").data).astype(int))}
    seg_pos = {v: i for i, v in enumerate(np.asarray(pf.get("nhm_seg").data).astype(int))}
    vals = ens.loc[rid].astype(float)

    # calibrated values vs ensemble
    cal_bad = 0
    for name, v in vals.items():
        parts = name.split(":")
        arr = np.asarray(pf.get(parts[0]).data)
        if len(parts) == 2 and parts[1].startswith("seg_"):
            got = arr[seg_pos[int(parts[1].split("_")[1])]]
        elif len(parts) == 3:
            got = arr[hru_pos[int(parts[1].split("_")[1])], int(parts[2].split("_")[1]) - 1]
        else:
            got = arr[hru_pos[int(parts[1].split("_")[1])]]
        if not np.isclose(float(got), v, rtol=RTOL, atol=ATOL):
            cal_bad += 1

    # non-calibrated parameters vs parameters.json
    names = list(pf.parameters.keys())
    n_json = n_json_bad = n_not_in_json = 0
    for name in names:
        if name in cal_names:
            continue
        if name not in run_ds:
            n_not_in_json += 1
            continue
        a = np.asarray(pf.get(name).data)
        b = np.asarray(run_ds[name].values)
        if b.shape != a.shape and b.T.shape == a.shape:
            b = b.T
        if b.shape != a.shape and b.size == a.size:
            b = b.reshape(a.shape)
        n_json += 1
        try:
            same = np.allclose(a.astype(float), b.astype(float), rtol=RTOL, atol=ATOL, equal_nan=True)
        except (TypeError, ValueError):
            same = np.array_equal(a, b)
        n_json_bad += 0 if same else 1

    rows.append(
        {
            "file": path.name,
            "realization": rid,
            "parameters": len(names),
            "calibrated values mismatching ensemble": cal_bad,
            "non-calibrated params checked vs json": n_json,
            "non-calibrated mismatching json": n_json_bad,
            "not in json (template value kept)": n_not_in_json,
            "HRUs": len(hru_pos),
            "segments": len(seg_pos),
        }
    )

check = pd.DataFrame(rows).set_index("file")
display(check)
ok = (
    (check["calibrated values mismatching ensemble"] == 0).all()
    and (check["non-calibrated mismatching json"] == 0).all()
)
con.print(
    f"[green]All checks passed.[/green] Files are in {out_path_dir}"
    if ok
    else "[bold red]Some values do not match; see the table above.[/bold red]"
)
