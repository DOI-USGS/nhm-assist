# %%
import os
import sys
import pathlib as pl
import warnings
import pandas as pd
import xarray as xr
import numpy as np
import shutil
import datetime

import jupyter_black

jupyter_black.load()
import io

from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

from rich.console import Console
from rich import pretty

warnings.filterwarnings("ignore")
pretty.install()
con = Console()


# One template set serves every workflow, so the root cannot be hardcoded the
# way the per-workflow copies did (`resolve_repo_root() / "nhf_assist"`). The
# workflow is inferred from where this notebook runs: nhm and pest use the repo
# root, nhf uses <repo>/nhf_assist. Built on resolve_repo_root, so it honours
# PIXI_PROJECT_ROOT and works for non-editable installs too.
from assist.workspace.bridge import resolve_workflow_root

root_dir = resolve_workflow_root(cwd=os.getcwd())

from assist.workspace.bridge import resolve_project_notebook_context
from assist.workspace.service import get_active_model_root

project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
if project_context:
    active_model_root = get_active_model_root(
        project_context["workspace_root"], project_context["project_root"].name
    )
    config_root = active_model_root / "config"
else:
    active_model_root = None
    config_root = root_dir

print(root_dir)

from assist.common.assist_utilities import (
    load_subdomain_config,
)

config = load_subdomain_config(config_root)
# con.print(config)


import pyemu
import platform

if "Windows" in platform.system():
    exe_name = "pestpp-ies.exe"
else:
    exe_name = "pestpp-ies"

######################################################################################

interrupt_notebook = False
import matplotlib.pyplot as plt

plt.rcParams["pdf.fonttype"] = 42


# %%
if not (config["model_dir"] / "pestpp_ies").exists():
    (config["model_dir"] / "pestpp_ies").mkdir()
pestpp_model_dir = config["model_dir"] / "pestpp_ies"

# %% [markdown]
# # Modify the PEST++ IES Observation-plus-Noise Ensemble
#
# This notebook follows `05_Re-weighting_obs.ipynb`. The obs+noise ensemble is
# one realization per row of synthetic observation values: each is the "true"
# observation value perturbed by noise drawn from the observation
# weights/standard deviations. PEST++ IES does not leave that ensemble on disk
# after the `noptmax=0` verification run, so we regenerate it here with pyemu
# from the re-weighted control file, exactly as PEST++ builds it internally.
#
# Here we:
# 1. Generate the obs+noise ensemble as a pandas DataFrame with pyemu
#    (`ObservationEnsemble.from_gaussian_draw`) from `prior_mc_reweight.pst`.
# 2. Modify that ensemble (the section below is where we will make our edits).
# 3. Write the modified ensemble back out as a binary `.jcb` file using pyemu.
# 4. Build the prior parameter ensemble, with truncated-normal draws for
#    `hru_deplcrv`, `snarea_thresh` and `rad_trncf` so their prior members do
#    not pile up on the bounds, and write it as a `.jcb` file
#    (`ies_parameter_ensemble`).
# 5. Update the PEST++ control file so that the IES noise ensemble points at
#    the modified `.jcb` file (`ies_observation_ensemble`).
#
# **Why `.jcb`?** `.jcb` is pyemu/PEST++'s binary ensemble format. It is far
# smaller and faster to read than the equivalent CSV for large ensembles, and
# PEST++ IES reads it directly for the observation (obs+noise) ensemble.

# %% [markdown]
# ## Load the Control File
# Load the re-weighted control file written by `05_Re-weighting_obs.ipynb`.

# %%
pst = pyemu.Pst(os.path.join(pestpp_model_dir, "prior_mc_reweight.pst"))

# %% [markdown]
# ## Build the Observation-plus-Noise Ensemble
# PEST++ IES does not leave the obs+noise ensemble on disk after the
# `noptmax=0` verification run from the previous notebook, so we generate it
# here the same way PEST++ does internally: a Gaussian draw around each
# observation value, with the noise covariance built from the (re-weighted)
# observation weights in `prior_mc_reweight.pst`.
#
# - `cov=None` -> pyemu builds the noise covariance from the non-zero
#   observation weights (`Cov.from_observation_data`, which treats the noise
#   standard deviation as the inverse of the weight).
# - `num_reals` matches the IES realization count set in the control file.
# - `fill=True` keeps every observation as a column (zero-weighted obs are
#   filled with their control-file `obsval`), so the exported `.jcb` lines up
#   one-to-one with `pst.observation_data`.
#
# The result is a pyemu `ObservationEnsemble`, which is a pandas DataFrame
# subclass: rows are realization names, columns are observation names.

# %%
num_reals = int(pst.pestpp_options.get("ies_num_reals", 500))
print(f"generating obs+noise ensemble with num_reals = {num_reals}")

# Draw one extra realization: add_base() replaces the last realization with the
# unperturbed control-file obsvals, so we draw num_reals + 1 noisy reals and let
# add_base() consume one. That keeps num_reals noisy realizations plus the base.
obs_noise_ens = pyemu.ObservationEnsemble.from_gaussian_draw(
    pst=pst,
    cov=None,
    num_reals=num_reals + 1,
    fill=True,
)

# Add the "base" realization: the true observation values with no noise. pyemu
# appends it as the last row, named "base".
obs_noise_ens.add_base()

# Put base first so it is the first row of the ensemble, then work with the
# underlying DataFrame for the modification rules below.
obs_noise = obs_noise_ens._df.copy()
base_first = ["base"] + [i for i in obs_noise.index if i != "base"]
obs_noise = obs_noise.loc[base_first]
print(f"obs+noise ensemble: {obs_noise.shape[0]} reals x {obs_noise.shape[1]} obs")
print(f"first realization: {obs_noise.index[0]!r} (the unperturbed base)")
obs_noise.head()

# %% [markdown]
# ## Modify the Ensemble
# Make our modifications to `obs_noise` here. The DataFrame is indexed by
# realization name (rows) with one column per observation. Any edits made to
# this frame flow through to the exported `.jcb` and into the IES run.
#
# Modification rules are applied to a working copy. Columns (observations) that
# a rule protects are left exactly as they were in the original ensemble.

# %%
obs_noise_modified = obs_noise.copy()

# %% [markdown]
# ### Rule 1: protect "mean_mon" and "streamflow_nodata" observations
# Two sets of columns are held fixed:
# - any observation whose name contains "mean_mon", and
# - the `streamflow_nodata` group (zero-weight placeholder observations that
#   should not be perturbed).
#
# We build a boolean mask of the columns eligible for modification; every later
# rule operates only on `modifiable_cols` so these columns pass through
# untouched.

# %%
obs_group_by_col = pst.observation_data["obgnme"].reindex(obs_noise_modified.columns)
protect_mask = obs_noise_modified.columns.str.contains("mean_mon") | (
    obs_group_by_col.values == "streamflow_nodata"
)
modifiable_cols = obs_noise_modified.columns[~protect_mask]

print(f"protected (mean_mon + streamflow_nodata) columns: {int(protect_mask.sum())}")
print(f"modifiable columns:                               {len(modifiable_cols)}")

# %% [markdown]
# ### Rule 2: never modify the "base" realization (the first row)
# The first row is the `base` realization: the unperturbed true observation
# values. It is held fixed across every column so the base always carries the
# control-file `obsval`s. We exclude it from the modifiable rows; later rules
# operate on `modifiable_rows` x `modifiable_cols`, so the base passes through
# untouched for all observations (including the `mean_mon` columns already
# protected by Rule 1).

# %%
protected_row = obs_noise_modified.index[0]
assert (
    protected_row == "base"
), f"expected base realization first, got {protected_row!r}"
modifiable_rows = obs_noise_modified.index[1:]

print(f"protected row (held fixed): {protected_row!r}")
print(f"modifiable rows:            {len(modifiable_rows)}")

# %% [markdown]
# #### Observation groups available to modify
# Map the modifiable observation columns back to their observation groups
# (`obgnme` in the control file) and list the distinct groups, with the count
# of modifiable observations in each. These are the groups the rules below can
# touch; any group that appears only among the protected `mean_mon`
# observations will not be listed.

# %%
obs_groups = pst.observation_data["obgnme"]
modifiable_groups = obs_groups.reindex(modifiable_cols).value_counts().sort_index()
print("Observation groups available to modify (obs count per group):")
print(modifiable_groups.to_string())

# State explicitly which groups are NOT being modified (protected by Rule 1):
# every group present in the ensemble that has no modifiable observations.
all_groups = set(obs_groups.reindex(obs_noise_modified.columns).dropna().unique())
protected_groups = sorted(all_groups - set(modifiable_groups.index))
print(f"\nObservation groups NOT being modified (protected): {protected_groups}")

# %% [markdown]
# ### Rule 3: resample noise per subgroup from each group's standard deviation
#
# For every modifiable observation, replace its per-realization value with a
# fresh noise draw scaled by the observation group's standard deviation:
#
# 1. Read the per-group standard deviations from
#    `ancillary/Observation_standard_deviation.csv` (the `noise_percent`
#    column is the fractional SD for that group).
# 2. For each **subgroup**, draw one sample vector of length `num_reals` from a
#    normal distribution with mean 0 and that group's SD, truncated to
#    +/- 2 SD. One draw per subgroup, shared by every observation in it and
#    applied positionally across the `num_reals` modifiable realizations.
# 3. Set `value = base_value + (base_value * sample_value)`, where `base_value`
#    is the unperturbed observation value (the `base` realization / control-file
#    `obsval`).
#
# **Subgrouping:** within each observation group, observations are aggregated
# into subgroups by the trailing id in the observation name (`...:<id>`):
# - groups whose name contains "streamflow" -> subgroup by **gage_id**,
# - all other groups -> subgroup by **HRU id**.
#
# The protected columns (Rule 1: `mean_mon` and `streamflow_nodata`) and the
# `base` row (Rule 2) are never written.

# %% [markdown]
# #### Read the per-group standard deviations

# %%
sd_path = pestpp_model_dir / "ancillary" / "Observation_standard_deviation.csv"
assert sd_path.exists(), f"missing SD table: {sd_path}"

sd_table = pd.read_csv(sd_path)
# The obsgroup column carries trailing/leading whitespace in the source file.
sd_table["obsgroup"] = sd_table["obsgroup"].str.strip()
group_sd = sd_table.set_index("obsgroup")["noise_percent"].astype(float)
print("per-group standard deviations (noise_percent):")
print(group_sd.to_string())

# Every modifiable group must have an SD entry.
missing_sd = sorted(set(modifiable_groups.index) - set(group_sd.index))
assert not missing_sd, f"groups missing from SD table: {missing_sd}"

# %% [markdown]
# #### Derive the subgroup key for every modifiable observation
# The subgroup key is `(obgnme, trailing-id)`. The trailing id is the last
# colon-delimited field of the observation name: a gage_id for streamflow
# groups, an HRU id otherwise. We only need keys for the modifiable columns.

# %%
obs_meta = pd.DataFrame(index=modifiable_cols)
obs_meta["obgnme"] = pst.observation_data["obgnme"].reindex(modifiable_cols)
# Trailing id: text after the final ":".
obs_meta["sub_id"] = modifiable_cols.str.rsplit(":", n=1).str[-1]
obs_meta["subgroup"] = list(zip(obs_meta["obgnme"], obs_meta["sub_id"]))
obs_meta["sd"] = obs_meta["obgnme"].map(group_sd)

print(f"modifiable observations: {len(obs_meta)}")
print(f"distinct subgroups:      {obs_meta['subgroup'].nunique()}")

# %% [markdown]
# #### Draw one truncated-normal sample per subgroup and apply it
# Each subgroup draws a single vector of length `num_reals` from `N(0, sd)`
# truncated to +/- 2 SD (`scipy.stats.truncnorm`, where the truncation bounds
# a, b are in standard-normal units, so +/-2). That vector is the fractional
# perturbation applied to every observation in the subgroup, positionally
# across the `num_reals` modifiable realizations. The new value is
# `base_value + base_value * sample`.
#
# `base_value` is taken from the `base` row (== control-file `obsval`), so the
# perturbation is always relative to the unperturbed truth regardless of the
# noise the generation step put in these cells.

# %%
from scipy.stats import truncnorm

# Reproducible draws for this rule.
rng = np.random.default_rng(seed=12345)

n_mod_reals = len(modifiable_rows)  # == num_reals

# Base (unperturbed) value per modifiable observation.
base_values = obs_noise_modified.loc["base", modifiable_cols].astype(float)

# Build the fractional-perturbation matrix: rows = modifiable realizations,
# cols = modifiable observations. All observations in a subgroup share one draw.
pert = pd.DataFrame(
    0.0,
    index=modifiable_rows,
    columns=modifiable_cols,
    dtype=float,
)

for subgroup, members in obs_meta.groupby("subgroup", sort=False):
    sd = float(members["sd"].iloc[0])
    # One draw per realization for this subgroup, truncated to +/- 2 SD.
    sample = truncnorm.rvs(
        a=-2.0,
        b=2.0,
        loc=0.0,
        scale=sd,
        size=n_mod_reals,
        random_state=rng,
    )
    # Broadcast the per-realization sample across every member observation.
    pert.loc[:, members.index] = sample[:, None]

# value = base + base * sample, applied only to modifiable rows/cols.
new_block = base_values.values[None, :] * (1.0 + pert.values)
obs_noise_modified.loc[modifiable_rows, modifiable_cols] = new_block

print("applied subgroup noise to modifiable rows/cols")
print(
    f"  modifiable block: {len(modifiable_rows)} reals x "
    f"{len(modifiable_cols)} obs across {obs_meta['subgroup'].nunique()} subgroups"
)
# Sanity: base row and mean_mon columns are untouched by this rule.
assert obs_noise_modified.loc["base", modifiable_cols].equals(base_values)

# %% [markdown]
# ## Export the Modified Ensemble as a `.jcb` File
# Wrap the modified DataFrame in a pyemu `ObservationEnsemble` (tied to `pst`
# so observation ordering/metadata is validated) and write it to binary `.jcb`.

# %%
obs_noise_jcb = pestpp_model_dir / "prior_reweight_obs+noise_mod.jcb"

obs_ensemble = pyemu.ObservationEnsemble(
    pst=pst,
    df=obs_noise_modified,
)
obs_ensemble.to_binary(str(obs_noise_jcb))
print(f"wrote modified obs+noise ensemble: {obs_noise_jcb}")

# %% [markdown]
# ## Prior Parameter Ensemble: Truncated-Normal Draws
#
# **Why.** When PEST++ IES draws the prior itself, it draws a Gaussian around
# each parameter's starting value (`parval1`) and **clips** any value outside
# the bounds back onto the bound. Where a starting value sits close to a bound,
# a large share of the prior members pile up exactly on that bound:
#
# - `hru_deplcrv` (snow depletion curve index, bounds 0.5 to 9.5, rounded to a
#   curve by the forward run): many HRUs start on curve 9 (or 2), only 0.5 from
#   a bound, so with the default spread about 41% of their members land on 9.5
#   or 0.5 and all become that end curve.
# - `snarea_thresh` and `rad_trncf`: notebook 02b gives them uneven bounds
#   (`snarea_thresh` 0.5 to 1.2 x `parval1`; `rad_trncf` 0.8 to 1.5 x `parval1`)
#   so calibration can melt late-melting HRUs out. The prior is centred on
#   `parval1`, so the near bound collects the draws: on the SandyRiver beta3
#   prior 20% of `snarea_thresh` values sat on its upper bound and 8% of
#   `rad_trncf` values on its lower bound.
#
# **What this section does.** It builds the prior parameter ensemble here and
# passes it to PEST++ IES with `ies_parameter_ensemble`:
#
# - Every parameter not listed in `TRUNCNORM_PARAMS` is drawn the way PEST++
#   IES draws it internally: a Gaussian around `parval1` in the parameter's
#   transformed space, with a standard deviation of
#   (upper bound - lower bound) / `par_sigma_range` (4 unless the control file
#   sets it), clipped to the bounds. Their prior is unchanged.
# - Each type in `TRUNCNORM_PARAMS` is redrawn from a **truncated normal**: the
#   same centre and spread, in the same transformed space (log10 for
#   log-transformed parameters, linear otherwise), but any value outside the
#   bounds is **redrawn** instead of clipped. Nothing piles up on a bound and
#   each HRU stays centred on its starting value. With uneven bounds the draw
#   is still centred on `parval1`, so more members fall on the wide side; that
#   is the intended effect of widening that side.
# - The `base` realization keeps every parameter at `parval1`.
# - Realization names and order match the obs+noise ensemble above exactly
#   (`base` first), so PEST++ pairs parameter and noise realizations one to one.
#
# **Settings.** `TRUNCNORM_PARAMS` maps each parameter type to `None` (the
# default spread above) or a standard deviation in the transformed units
# (curves for `hru_deplcrv`, log10 units for the log-transformed ones). Remove a
# type from the dict to give it the plain PEST++ draw. `PAR_ENSEMBLE_SEED`
# makes the draw reproducible. Set `TRUNCATED_PRIOR = False` to skip this
# section and let PEST++ draw the prior itself. The ensemble file is
# `prior_par_ens_truncnorm.jcb` (earlier versions wrote
# `prior_par_ens_deplcrv_truncnorm.jcb`; an old copy in the run folder is not
# used once the control file is rewritten below).

# %%
TRUNCATED_PRIOR = True
TRUNCNORM_PARAMS = {
    "hru_deplcrv": None,  # SD in curves; None -> (parubnd - parlbnd) / par_sigma_range
    "snarea_thresh": None,  # SD in log10 units when log-transformed
    "rad_trncf": None,
}
PAR_ENSEMBLE_SEED = 20261117

par_ens_jcb = pestpp_model_dir / "prior_par_ens_truncnorm.jcb"

if TRUNCATED_PRIOR:
    pars = pst.parameter_data
    sigma_range = float(pst.pestpp_options.get("par_sigma_range", 4.0))
    rng = np.random.default_rng(PAR_ENSEMBLE_SEED)
    np.random.seed(PAR_ENSEMBLE_SEED)  # pyemu's Gaussian draw uses numpy's global RNG

    # 1. Every parameter, drawn as PEST++ IES would (transformed space, clipped to
    #    bounds). One extra realization is consumed by add_base(), as for the
    #    obs+noise ensemble above.
    cov = pyemu.Cov.from_parameter_data(pst, sigma_range=sigma_range)
    par_ens = pyemu.ParameterEnsemble.from_gaussian_draw(
        pst=pst, cov=cov, num_reals=num_reals + 1
    )
    par_ens.enforce()
    par_ens.add_base()
    par_df = par_ens._df.copy()
    draw_rows = [r for r in par_df.index if r != "base"]

    # 2. Truncated-normal redraw for the listed types (redraw out-of-bounds values).
    for ptype, sd_override in TRUNCNORM_PARAMS.items():
        sel = pars.loc[pars.parnme.str.startswith(ptype + ":")]
        if sel.empty:
            print(f"{ptype}: not in the control file, skipped")
            continue
        names = sel.parnme.to_list()
        is_log = (sel.partrans == "log").to_numpy()

        def to_t(x):
            """Natural -> transformed (log10 where log-transformed)."""
            x = np.asarray(x, dtype=float)
            return np.where(is_log, np.log10(np.where(is_log, x, 1.0)), x)

        lo = to_t(sel.parlbnd)
        hi = to_t(sel.parubnd)
        mu = to_t(sel.parval1)
        sd = (
            (hi - lo) / sigma_range
            if sd_override is None
            else np.full(len(sel), float(sd_override))
        )
        fixed = ~(hi > lo)  # zero-width bounds: keep parval1
        lo_b, hi_b = np.broadcast_to(lo, (len(draw_rows), len(sel))), np.broadcast_to(
            hi, (len(draw_rows), len(sel))
        )
        mu_b, sd_b = np.broadcast_to(mu, lo_b.shape), np.broadcast_to(sd, lo_b.shape)
        vals = rng.normal(mu_b, sd_b)
        out = ((vals < lo_b) | (vals > hi_b)) & ~fixed[None, :]
        for _ in range(1000):  # rejection sampling: redraw only out-of-bounds values
            if not out.any():
                break
            vals[out] = rng.normal(mu_b[out], sd_b[out])
            out = ((vals < lo_b) | (vals > hi_b)) & ~fixed[None, :]
        vals = np.clip(vals, lo_b, hi_b)  # only reached if 1000 rounds were not enough
        vals[:, fixed] = mu[fixed]
        nat = np.where(is_log[None, :], 10.0**vals, vals)
        par_df.loc[draw_rows, names] = nat
        par_df.loc["base", names] = sel.parval1.to_numpy(float)

        # Report.
        at_bound = (np.isclose(vals, lo_b) | np.isclose(vals, hi_b))[:, ~fixed]
        shift = np.median(
            (vals - mu_b)[:, ~fixed] / np.where(sd_b > 0, sd_b, 1.0)[:, ~fixed]
        )
        print(
            f"{ptype}: {len(sel)} parameters ({'log10' if is_log.all() else 'linear' if not is_log.any() else 'mixed'}"
            f" space) | values exactly on a bound: {100 * at_bound.mean():.2f}% | "
            f"median draw - parval1: {shift:+.2f} SD"
        )
        if ptype == "hru_deplcrv":
            n_curves = int(round(sel.parubnd.max() - 0.5))  # bounds 0.5 to n + 0.5
            curve = np.clip(np.rint(nat), 1, n_curves).astype(int)
            shares = [100 * (curve == c).mean() for c in range(1, n_curves + 1)]
            print(
                "  share of prior members on each curve: "
                + "  ".join(
                    f"{c}: {s:4.1f}%" for c, s in zip(range(1, n_curves + 1), shares)
                )
            )

    # 3. Same realization names and order as the obs+noise ensemble; write .jcb.
    # Match by name as text (pyemu may label realizations with ints or strings).
    par_df.index = par_df.index.map(str)
    obs_names = list(obs_noise_modified.index.map(str))
    missing = sorted(set(obs_names) - set(par_df.index))
    assert (
        not missing
    ), f"realizations in the obs+noise ensemble but not drawn here: {missing[:5]}"
    par_df = par_df.loc[obs_names]
    par_df.index = obs_noise_modified.index
    assert list(par_df.index) == list(obs_noise_modified.index)
    assert list(par_df.columns) == list(pst.parameter_data.parnme)
    pyemu.ParameterEnsemble(pst=pst, df=par_df).to_binary(str(par_ens_jcb))
    pst.pestpp_options["ies_parameter_ensemble"] = par_ens_jcb.name
    print(
        f"wrote prior parameter ensemble: {par_ens_jcb} ({par_df.shape[0]} reals x {par_df.shape[1]} pars)"
    )
else:
    pst.pestpp_options.pop("ies_parameter_ensemble", None)
    print(
        "TRUNCATED_PRIOR is False: PEST++ IES will draw the prior parameter ensemble itself."
    )

# %% [markdown]
# ## Point the Control File at the Modified `.jcb`
# Set the IES observation (obs+noise) ensemble to the modified file and write a
# new control file. `ies_no_noise` must stay `False` so PEST++ uses the
# supplied ensemble rather than regenerating noise internally.

# %%
pst.control_data.noptmax = 0
pst.pestpp_options["ies_observation_ensemble"] = obs_noise_jcb.name
pst.pestpp_options["ies_no_noise"] = False
pst.write(
    os.path.join(pestpp_model_dir, "prior_mc_reweight_obs+noise_mod.pst"), version=2
)
print("wrote control file: prior_mc_reweight_obs+noise_mod.pst")
print(f"ies_observation_ensemble = {pst.pestpp_options['ies_observation_ensemble']}")

# %%
pyemu.os_utils.run(
    "pestpp-ies.exe prior_mc_reweight_obs+noise_mod.pst", cwd=pestpp_model_dir
)

# %%
pst.control_data.noptmax = 3  # set to 3 so its ready for HW run
pst.write(
    os.path.join(pestpp_model_dir, "prior_mc_reweight_obs+noise_mod.pst"), version=2
)
