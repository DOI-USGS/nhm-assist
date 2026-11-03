# %% [markdown]
# # Create `tmax_cbh_adj` and `tmin_cbh_adj` Temperature-Bias Correction Parameters
#
# ## Summary
#
# This notebook computes per-HRU, per-month `tmax_cbh_adj` and `tmin_cbh_adj`
# additive temperature-bias correction parameters (degF) for the SandyRiver child
# model, from HRU elevation and a **measured monthly atmospheric lapse-rate
# deficit**, then writes them into a NEW renamed PRMS parameter file
# (`myparam_mod_tadj.param`) without touching the input `myparam.param`.
#
# These are **starting values** for a later re-calibration, produced the same
# way the sibling `create_smidx_exp_param` workflow produces child-model
# parameters. Freeing/estimating them in PEST is a separate follow-up: this
# notebook touches NO `.tpl`/`.pst`/control files or the `pestpp_ies` directory.
#
# ## Lapse rates in plain language
#
# A **lapse rate** is simply how fast air temperature drops as you climb to higher
# elevation. Hike up a mountain and it gets colder the higher you go; the lapse
# rate is the "degrees colder per 1000 m of climb." A **lapse curve** here is that
# same idea measured for each month of the year, because the rate is not constant
# — mountains cool off with height more steeply in some seasons than others.
#
# We have two versions of this curve:
#
# - **Observed** — from real weather stations (SNOTEL and GHCN) scattered across a
#   range of elevations in and around the basin. Plotting each station's winter
#   temperature against its elevation and drawing the best-fit line gives the
#   *real-world* rate at which it gets colder with height.
# - **Model** — the same calculation done on the model's GridMET temperature
#   forcing at each HRU. This is the rate the model *thinks* is happening.
#
# When the model's curve is **shallower** than the observed curve (it doesn't cool
# off fast enough with height), the model's high-elevation areas end up too warm.
# That warmth melts snow that should have stayed frozen and turns snow into rain,
# which throws off the water balance.
#
# **How we use the curves to build the adjustment:** for each month we take the
# difference between the two curves (observed minus model) — call it the
# *deficit*. The deficit tells us, per meter of elevation, how much too warm (or,
# occasionally, too cold) the model is. We then build a correction that is zero
# down in the valley (where the two agree, the "valley pin") and grows with
# elevation by exactly that deficit, so after the correction the model's
# temperature-vs-elevation behavior matches the observations. That per-HRU,
# per-month correction is what gets written into `tmax_cbh_adj` and
# `tmin_cbh_adj`. The sections below make this precise.
#
# ## What these parameters are and how pywatershed applies them
#
# `tmax_cbh_adj` and `tmin_cbh_adj` are additive, per-HRU, per-calendar-month
# adjustments (degrees Fahrenheit) applied to the climate-by-HRU (CBH)
# temperature forcing. pywatershed adds the month's value to the input
# temperature for each HRU:
#
# ```
# tmaxf(hru, day) = tmax_input(hru, day) + tmax_cbh_adj(hru, month(day))
# tminf(hru, day) = tmin_input(hru, day) + tmin_cbh_adj(hru, month(day))
# ```
#
# Both have shape `(nhru, 12)`. In the input file for SandyRiver they are
# currently all zeros.
#
# ## The problem (why an elevation-dependent lapse correction)
#
# The GridMET temperature forcing generally **under-lapses**: its effective
# temperature decrease with elevation is shallower than the observed atmospheric
# lapse in most months, so the forcing tends to be too warm at high elevation.
# Precipitation aloft that should fall as snow instead falls as rain, producing
# an SWE deficit. This is documented for this basin in two prior reports under
# `D:\test_hw_calibration_results\Sandy_beta4\`:
#
# - `snow_rain_partition_diagnosis.md` — warm bias aloft shifts the rain/snow
#   partition toward rain, driving the SWE deficit.
# - `gridmet_warm_bias_verification.md` — verifies the GridMET warm bias against
#   SNOTEL + GHCN-Daily station observations and quantifies the lapse.
#
# The fix repairs the lapse **per month**, relative to a low-elevation (valley)
# reference where the report found ~zero bias. The correction grows with
# elevation above that reference, in whichever direction each month's measured
# deficit dictates — cooling in months where the forcing under-lapses (too warm
# aloft), a small warming in months where it over-lapses (too cold aloft).
#
# ## Formula
#
# For each calendar month `m`:
#
# ```
# deficit_degC_per_km[m] = obs_lapse[m] - model_lapse[m]      # SIGN PRESERVED
# deficit_degF_per_m[m]  = deficit_degC_per_km[m] / 1000 * 1.8
# adj(hru, m) = -(deficit_degF_per_m[m]) * max(0.0, hru_elev[hru] - elev_ref)
# ```
#
# The adjustment is 0 at and below `elev_ref` and grows with height above it. Its
# **sign is the measured sign** of that month's deficit: a negative deficit
# (observed steeper / colder aloft) cools high HRUs; a positive deficit (model
# already too cold aloft) warms them slightly. The result is a genuine
# `(nhru, 12)` array that varies by month — not a single value broadcast across
# months, and not clamped to cooling only.
#
# ## Design decisions (cataloged)
#
# | # | Decision | Chosen | Rejected alternative | Rationale |
# |---|----------|--------|----------------------|-----------|
# | 1 | Formulation | **Lapse-deficit**: the per-HRU correction grows with height to repair the forcing's lapse toward the observed lapse. | Direct bias-vs-elevation slope (regress station warm bias on elevation). | The direct bias-vs-elevation signal is noisy (`winter_tmax_bias_raw` vs elevation r≈0.14). The absolute observed-temperature lapse is a clean, strong signal (monthly \|r\| ≈ 0.74-0.97), so correcting the *lapse* is far better constrained. |
# | 2 | tmax vs tmin split | **Separate per-variable deficits, each from its OWN independently-derived observed and model lapse.** | A single shared adjustment, or reusing the tmax lapse for tmin. | Both observed lapses are clean regressions. tmin uses its own observed monthly lapse and its own model monthly baseline, read from the monthly-lapse CSV; it is measured, not reused from tmax. |
# | 3 | Anchoring | **Valley-pin**: `elev_ref` = low-elevation reference where the report found ~zero bias; the correction is zero there and grows above it. | Basin-mean pivot (adjust relative to the basin-mean elevation). | Valley-pin matches the report literally (zero bias in the valley). It deliberately shifts basin-mean temperature, which will shift PET and snowmelt — an accepted, intended consequence of this choice, not a side effect to correct. |
# | 4 | Monthly variation | **Per-month, measured**: each month uses its own observed-minus-model lapse deficit, so the adjustment varies through the year and carries the deficit's sign. | A single winter (DJFM) value broadcast to all 12 months. | The warm-bias workflow now writes a per-month observed and model lapse (`gridmet_temp_bias_monthly_lapse.csv`), and per-month station coverage is adequate (34 stations in every month). Using the measured monthly curve keeps the correction consistent with the data rather than forcing a single annual value or one direction. |
# | 5 | Output | **New file** `myparam_mod_tadj.param`; input left untouched. | Overwriting `myparam.param` in place. | Preserve the original; mirror the write pattern of `create_smidx_exp_param` but to a renamed file so the baseline is never lost. |
#
# ## Numeric inputs and their sources
#
# - **Per-month observed and model lapses** (tmax and tmin) are read from
#   `gridmet_temp_bias_monthly_lapse.csv`
#   (`d:\nhm-assist\.agents\tasks\gridmet-warm-bias-verification\`), produced by
#   `verify_gridmet_temp_bias.py`. For each calendar month it holds the observed
#   station lapse (regression of station month-mean temperature on elevation,
#   stations with >= 30 days that month) and the model-driver lapse (per-HRU
#   model month-mean vs `hru_elev`), both in degC/km, over the WY2010-2021 window.
# - **Both lapses come from the SAME GridMET drivers this child model uses**
#   (`tmax.nc` / `tmin.nc` in the SandyRiver runtime dir), so the model baseline
#   is self-consistent with the forcing rather than a hard-coded constant. The
#   drivers were repulled fresh; the per-month model lapse is derived from them.
# - **Per-month deficit (observed − model)** carries its sign. The notebook
#   prints the full 12-month table of obs/model/deficit for tmax and tmin when it
#   runs, and the Step-5 sanity check confirms, for every month, that
#   `model_lapse[m] + deficit[m]` reproduces `obs_lapse[m]`.
# - **`elev_ref` (valley anchor)**: mean elevation of the low stations
#   (`elevation_m < 300`) from the warm-bias summary CSV ≈ **97.4 m**.
#
# ## References
#
# - `D:\test_hw_calibration_results\Sandy_beta4\gridmet_warm_bias_verification.md`
# - `D:\test_hw_calibration_results\Sandy_beta4\snow_rain_partition_diagnosis.md`
# - Markstrom, S.L., et al. (2015). PRMS-IV. U.S. Geological Survey Techniques
#   and Methods, 6, B7.

# %%
import numpy as np
import pandas as pd
import pathlib as pl
import matplotlib.pyplot as plt
import geopandas as gpd

from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData

# %% [markdown]
# ## Define paths

# %%
runtime_dir = pl.Path(
    r"D:\nhm-workspace\Oregon_Recharge\models\SandyRiver\outputs\runtime"
)
# INPUT param to READ (never written).
input_param = runtime_dir / "myparam.param"
# OUTPUT param to WRITE (new name; input preserved).
output_param = runtime_dir / "myparam_mod_tadj.param"
# Warm-bias artifacts live in a model-local subdirectory of the runtime dir,
# written by verify_gridmet_temp_bias.py (--out-dir defaults here). Everything
# for this model — the summary + monthly-lapse CSVs, the script's HTML, the
# station cache, and the map/diagnostic HTMLs this notebook saves — stays
# together under one folder, so the workflow is portable across models.
warm_bias_dir = runtime_dir / "gridmet_warm_bias"
# Winter station summary CSV (SNOTEL + GHCN-Daily) — used only for valley-pin elev_ref.
warm_bias_csv = warm_bias_dir / "gridmet_temp_bias_summary.csv"
# Per-month observed + model lapse table (12 rows) — drives the monthly curve.
monthly_lapse_csv = warm_bias_dir / "gridmet_temp_bias_monthly_lapse.csv"
# GIS geopackage (nhru layer) — used only for the HRU-count alignment assert.
gis_gpkg = runtime_dir / "GIS" / "model_layers.gpkg"
print(f"runtime_dir       : {runtime_dir}")
print(f"input_param       : {input_param}")
print(f"output_param      : {output_param}")
print(f"warm_bias_dir     : {warm_bias_dir}")
print(f"warm_bias_csv     : {warm_bias_csv}")
print(f"monthly_lapse_csv : {monthly_lapse_csv}")
print(f"gis_gpkg          : {gis_gpkg}")
assert input_param.exists(), f"input param not found: {input_param}"
assert warm_bias_csv.exists(), f"warm-bias CSV not found: {warm_bias_csv}"
assert monthly_lapse_csv.exists(), (
    f"monthly-lapse CSV not found: {monthly_lapse_csv}\n"
    "Run: pixi run python scripts/verify_gridmet_temp_bias.py"
)

# %% [markdown]
# ## Step 1: Load the input parameter file
#
# Load `myparam.param` with pyPRMS and read `hru_elev` (meters), `nhm_id`, and
# the existing `tmax_cbh_adj`/`tmin_cbh_adj` (both currently all-zero). The
# param file's own HRU dimension is the authority for array ordering and length;
# `hru_elev` from the param file is the per-HRU elevation used throughout.

# %%
pdb = ParameterFile(input_param, metadata=MetaData().metadata, verbose=False)

hru_elev = np.asarray(pdb.get("hru_elev").data, dtype=float)
nhm_id = np.asarray(pdb.get("nhm_id").data)
tmax0 = np.asarray(pdb.get("tmax_cbh_adj").data)
tmin0 = np.asarray(pdb.get("tmin_cbh_adj").data)
nhru = len(hru_elev)

print(f"nhru (from param file)   : {nhru}")
print(f"nhm_id shape             : {nhm_id.shape}")
print(f"hru_elev shape           : {hru_elev.shape} (meters)")
print(
    f"hru_elev min/median/max  : {hru_elev.min():.4f} / "
    f"{np.median(hru_elev):.4f} / {hru_elev.max():.4f} m"
)
print(f"tmax_cbh_adj shape       : {tmax0.shape}  all-zero: {bool((tmax0 == 0).all())}")
print(f"tmin_cbh_adj shape       : {tmin0.shape}  all-zero: {bool((tmin0 == 0).all())}")

assert tmax0.shape == (nhru, 12), f"tmax_cbh_adj shape {tmax0.shape} != {(nhru, 12)}"
assert tmin0.shape == (nhru, 12), f"tmin_cbh_adj shape {tmin0.shape} != {(nhru, 12)}"

# HRU alignment against the GIS geopackage. The param file's HRU dimension is
# the authority for ordering/length. gpd.read_file returns the nhru layer in the
# geopackage's stored order, which is NOT hru_id-sorted (and so does NOT match
# the param row order). Sort by hru_id so hru_gdf row i == param row i, then
# assert the nhm_id sequences agree — otherwise any positional use of hru_gdf
# (e.g. the map) would paint each HRU with another HRU's value.
hru_gdf = gpd.read_file(gis_gpkg, layer="nhru").sort_values("hru_id").reset_index(drop=True)
assert nhru == len(hru_gdf), (
    f"param file HRU count ({nhru}) != geopackage nhru count ({len(hru_gdf)})"
)
assert np.array_equal(nhm_id, hru_gdf["nhm_id"].to_numpy()), (
    "param nhm_id order does not match geopackage nhm_id order after sorting by "
    "hru_id; row-aligned use of hru_gdf would be wrong."
)
print(f"GIS nhru layer count     : {len(hru_gdf)} (matches param file, nhm_id aligned)")

# %% [markdown]
# ## Step 2: Read the per-month lapse deficits
#
# The adjustment is now built from a **measured monthly lapse curve**, not a
# single winter value. `verify_gridmet_temp_bias.py` writes
# `gridmet_temp_bias_monthly_lapse.csv` with, for each calendar month, the
# observed station lapse and the model-driver lapse (degC/km) for both tmax and
# tmin, derived from the SAME GridMET drivers this child model uses.
#
# For each month the **deficit** is `observed - model` (degC/km). We honor its
# **measured sign**: a negative deficit (observed steeper / colder aloft than the
# model) produces cooling with elevation; a positive deficit (model already too
# cold aloft that month) produces a small warming with elevation. This keeps the
# approach internally consistent — the correction is whatever the data says for
# that month, not forced to one direction.
#
# The deficit is converted to a per-meter adjustment slope in degF/m
# (`degC/km -> degC/m /1000 -> degF/m *1.8`), with sign preserved.

# %%
# Winter summary — used ONLY to pick the valley-pin reference elevation below.
df = pd.read_csv(warm_bias_csv)
d = df[df["n_days_winter"] >= 60].copy()
n_sta = len(d)

# Per-month lapse table (12 rows, month 1..12).
ml = pd.read_csv(monthly_lapse_csv).sort_values("month").reset_index(drop=True)
assert list(ml["month"]) == list(range(1, 13)), "monthly lapse CSV must have months 1..12"

# Per-month deficit (observed - model), degC/km, SIGN PRESERVED.
tmax_deficit_degC_per_km_m = (
    ml["obs_tmax_lapse_degC_per_km"] - ml["model_tmax_lapse_degC_per_km"]
).to_numpy(dtype=float)
tmin_deficit_degC_per_km_m = (
    ml["obs_tmin_lapse_degC_per_km"] - ml["model_tmin_lapse_degC_per_km"]
).to_numpy(dtype=float)

# Convert to a per-meter adjustment slope in degF/m, sign preserved:
#   degC/km -> degC/m (/1000) -> degF/m (*1.8).
# The adjustment applied below is -(deficit_slope) * height_above, so a
# negative deficit (obs colder aloft) cools and a positive deficit warms.
tmax_deficit_degF_per_m_m = (tmax_deficit_degC_per_km_m / 1000.0) * 1.8
tmin_deficit_degF_per_m_m = (tmin_deficit_degC_per_km_m / 1000.0) * 1.8

assert tmax_deficit_degF_per_m_m.shape == (12,)
assert tmin_deficit_degF_per_m_m.shape == (12,)

month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
print(f"Winter stations for valley-pin (n_days_winter >= 60): n = {n_sta}")
print("Per-month deficit (observed - model), sign preserved:")
print(f"  {'mon':>3} {'obs_tmax':>9} {'mod_tmax':>9} {'def_tmax':>9} | "
      f"{'obs_tmin':>9} {'mod_tmin':>9} {'def_tmin':>9}   (degC/km)")
for k in range(12):
    print(
        f"  {month_names[k]:>3} "
        f"{ml['obs_tmax_lapse_degC_per_km'][k]:>9.3f} "
        f"{ml['model_tmax_lapse_degC_per_km'][k]:>9.3f} "
        f"{tmax_deficit_degC_per_km_m[k]:>9.3f} | "
        f"{ml['obs_tmin_lapse_degC_per_km'][k]:>9.3f} "
        f"{ml['model_tmin_lapse_degC_per_km'][k]:>9.3f} "
        f"{tmin_deficit_degC_per_km_m[k]:>9.3f}"
    )
print(f"tmax deficit degF/m per month: "
      f"{[round(float(v), 6) for v in tmax_deficit_degF_per_m_m]}")
print(f"tmin deficit degF/m per month: "
      f"{[round(float(v), 6) for v in tmin_deficit_degF_per_m_m]}")

# %% [markdown]
# ## Step 3: Choose the valley reference elevation (`elev_ref`)
#
# Valley-pin anchoring: `elev_ref` is the elevation at and below which the
# correction is zero, growing above it. The **default** is the mean elevation of
# the low-elevation stations below `LOWLAND_CUTOFF_M` (300 m) — the valley band
# where the report found ~zero bias.
#
# `LOWLAND_CUTOFF_M` and `elev_ref` are exposed as explicit, editable values
# below. To help you decide whether to override the default, this cell also
# prints **informational suggestions** derived from the model's own stream
# network (independent of the stations): the outlet segments are the lowest
# points of the routing, so their HRU elevations characterize the valley floor.
# The suggestions do **not** change `elev_ref` — set it yourself if you want a
# different anchor. (Per-segment elevation is the mean `hru_elev` of the HRUs
# draining to each segment, via `hru_segment`; outlets are segments with
# `tosegment == 0`.)

# %%
# --- Editable knobs -------------------------------------------------------
LOWLAND_CUTOFF_M = 300.0          # station cutoff defining the "lowland" band
# Default elev_ref: mean elevation of low-elevation stations below the cutoff.
low = d[d["elevation_m"] < LOWLAND_CUTOFF_M]
elev_ref = float(low["elevation_m"].mean())
# To override, set elev_ref explicitly here, e.g.:
#   elev_ref = 95.0
# --------------------------------------------------------------------------

print(f"DEFAULT elev_ref = {elev_ref:.2f} m  "
      f"(mean of {len(low)} stations < {LOWLAND_CUTOFF_M:.0f} m; valley-pin anchor)")

# --- Informational suggestions from the model stream network -------------
# Outlet segments (tosegment == 0) are the lowest points of the routing. Their
# per-segment elevation = mean hru_elev of the HRUs draining to that segment.
hru_segment = np.asarray(pdb.get("hru_segment").data, dtype=int)   # 1..nseg (local)
tosegment = np.asarray(pdb.get("tosegment").data, dtype=int)       # len nseg, 0 = outlet
nseg = len(tosegment)

seg_elev = np.full(nseg, np.nan)
for s in range(1, nseg + 1):
    m = hru_segment == s
    if m.any():
        seg_elev[s - 1] = hru_elev[m].mean()

outlet_ids = [s for s in range(1, nseg + 1) if tosegment[s - 1] == 0]
outlet_elevs = [seg_elev[s - 1] for s in outlet_ids]

print()
print("Informational suggestions (do NOT change elev_ref unless you edit it):")
print(f"  number of outlet segments (tosegment==0): {len(outlet_ids)}")
for s, e in zip(outlet_ids, outlet_elevs):
    print(f"    outlet segment {s}: mean HRU elev = {e:.1f} m")
if outlet_elevs:
    print(f"  mean of outlet-segment elevations : {np.nanmean(outlet_elevs):.1f} m")
    print(f"  min  of outlet-segment elevations : {np.nanmin(outlet_elevs):.1f} m")
print(f"  (for reference: station default = {elev_ref:.1f} m; "
      f"basin hru_elev min = {hru_elev.min():.1f} m, median = "
      f"{np.median(hru_elev):.1f} m)")
print()
print(f"USING elev_ref = {elev_ref:.2f} m")

# %% [markdown]
# ## Step 4: Compute the per-HRU, per-month adjustments
#
# For each month m: `adj[:, m] = -(deficit_slope_degF_per_m[m]) * max(0, hru_elev - elev_ref)`.
#
# The adjustment is zero at/below `elev_ref` and grows (in whichever direction the
# month's deficit dictates) with height above it. Months with a negative deficit
# cool high HRUs; months with a positive deficit warm them slightly. The result is
# a genuine `(nhru, 12)` array that varies by month — no longer broadcast from a
# single value.

# %%
height_above = np.maximum(0.0, hru_elev - elev_ref)  # (nhru,)

# Per-month adjustment: outer product of height_above (nhru,) with the negated
# per-month deficit slope (12,). Sign preserved — cooling or warming per month.
tmax_adj = -np.outer(height_above, tmax_deficit_degF_per_m_m)  # (nhru, 12)
tmin_adj = -np.outer(height_above, tmin_deficit_degF_per_m_m)  # (nhru, 12)

assert tmax_adj.shape == (nhru, 12), f"tmax_adj shape {tmax_adj.shape}"
assert tmin_adj.shape == (nhru, 12), f"tmin_adj shape {tmin_adj.shape}"
# Valley HRUs (at/below elev_ref) are unchanged in every month.
valley = height_above == 0.0
assert np.allclose(tmax_adj[valley, :], 0.0), "valley HRUs must have zero tmax adj"
assert np.allclose(tmin_adj[valley, :], 0.0), "valley HRUs must have zero tmin adj"

i_lo = int(np.argmin(hru_elev))
i_hi = int(np.argmax(hru_elev))
i_med = int(np.argsort(hru_elev)[len(hru_elev) // 2])

print("TMAX adjustment (degF) — per-month range and sample HRUs:")
print(f"  overall min/mean/max : {tmax_adj.min():.4f} / "
      f"{tmax_adj.mean():.4f} / {tmax_adj.max():.4f}")
print(f"  highest HRU (elev {hru_elev[i_hi]:.1f} m) by month: "
      f"{[round(float(v), 3) for v in tmax_adj[i_hi]]}")
print("TMIN adjustment (degF) — per-month range and sample HRUs:")
print(f"  overall min/mean/max : {tmin_adj.min():.4f} / "
      f"{tmin_adj.mean():.4f} / {tmin_adj.max():.4f}")
print(f"  highest HRU (elev {hru_elev[i_hi]:.1f} m) by month: "
      f"{[round(float(v), 3) for v in tmin_adj[i_hi]]}")
print(f"  lowest  HRU (elev {hru_elev[i_lo]:.1f} m): all-zero = "
      f"{bool(np.allclose(tmax_adj[i_lo], 0) and np.allclose(tmin_adj[i_lo], 0))}")

# %% [markdown]
# ## Step 5: Sanity check (required) — recompute the corrected effective lapse
#
# Pure array arithmetic (no pywatershed run). For every month, regress the
# computed adjustment on `hru_elev` over the HRUs above `elev_ref`: the slope must
# equal `-(deficit_slope_degF_per_m[m])`. Adding each month's deficit to that
# month's model lapse must reproduce that month's observed lapse. Asserts fail
# loudly if the math drifts.

# %%
above = hru_elev > elev_ref

print("Per-month sanity check (slope of adj vs elev above elev_ref, "
      "and corrected effective lapse):")
print(f"  {'mon':>3} {'tmax_slope':>11} {'expect':>11} | "
      f"{'tmax_eff_after':>14} {'obs_tmax':>9}")
for k in range(12):
    s_tx = float(np.polyfit(hru_elev[above], tmax_adj[above, k], 1)[0])
    assert np.isclose(s_tx, -tmax_deficit_degF_per_m_m[k], atol=1e-9), (
        f"month {k + 1} tmax adj slope {s_tx:.8f} != "
        f"{-tmax_deficit_degF_per_m_m[k]:.8f}"
    )
    s_tn = float(np.polyfit(hru_elev[above], tmin_adj[above, k], 1)[0])
    assert np.isclose(s_tn, -tmin_deficit_degF_per_m_m[k], atol=1e-9), (
        f"month {k + 1} tmin adj slope {s_tn:.8f} != "
        f"{-tmin_deficit_degF_per_m_m[k]:.8f}"
    )
    # corrected effective lapse = model + deficit == observed (by construction)
    tmax_eff_after = (
        ml["model_tmax_lapse_degC_per_km"][k] + tmax_deficit_degC_per_km_m[k]
    )
    assert np.isclose(tmax_eff_after, ml["obs_tmax_lapse_degC_per_km"][k], atol=1e-6)
    tmin_eff_after = (
        ml["model_tmin_lapse_degC_per_km"][k] + tmin_deficit_degC_per_km_m[k]
    )
    assert np.isclose(tmin_eff_after, ml["obs_tmin_lapse_degC_per_km"][k], atol=1e-6)
    print(f"  {month_names[k]:>3} {s_tx:>11.6f} "
          f"{-tmax_deficit_degF_per_m_m[k]:>11.6f} | "
          f"{tmax_eff_after:>14.3f} {ml['obs_tmax_lapse_degC_per_km'][k]:>9.3f}")
print("Sanity check passed: per-month corrected lapse matches the observed lapse.")

# %% [markdown]
# ## Step 6: Write the new parameter file
#
# Assign the computed `(nhru, 12)` arrays onto the loaded parameter object and
# write to the NEW `myparam_mod_tadj.param`. The input `myparam.param` is NEVER
# written.

# %%
pdb.get("tmax_cbh_adj").data = tmax_adj
pdb.get("tmin_cbh_adj").data = tmin_adj
pdb.write_parameter_file(str(output_param))

print(f"Wrote new parameter file: {output_param}")
print(f"  exists: {output_param.exists()}")

# %% [markdown]
# ## Comparison: reload the output, verify it, and confirm the input is untouched
#
# Reload the output param fresh and confirm the written `tmax_cbh_adj`/
# `tmin_cbh_adj` match the computed arrays. Reload the input param read-only and
# confirm its `tmax_cbh_adj`/`tmin_cbh_adj` are still all-zero.

# %%
pdb_out = ParameterFile(output_param, metadata=MetaData().metadata, verbose=False)
tmax_out = np.asarray(pdb_out.get("tmax_cbh_adj").data)
tmin_out = np.asarray(pdb_out.get("tmin_cbh_adj").data)

pdb_in = ParameterFile(input_param, metadata=MetaData().metadata, verbose=False)
tmax_in = np.asarray(pdb_in.get("tmax_cbh_adj").data)
tmin_in = np.asarray(pdb_in.get("tmin_cbh_adj").data)

# The PRMS param-file writer round-trips floats at ~1e-7; with the small
# signed monthly values that is just below np.allclose's default atol, so
# compare with an explicit atol=1e-5 degF (far finer than any meaningful
# temperature precision).
_ATOL = 1e-5
print("Output param read-back:")
print(f"  tmax_cbh_adj shape {tmax_out.shape}, matches computed: {np.allclose(tmax_out, tmax_adj, atol=_ATOL)}")
print(f"  tmin_cbh_adj shape {tmin_out.shape}, matches computed: {np.allclose(tmin_out, tmin_adj, atol=_ATOL)}")
print(f"  tmax max abs diff vs computed: {np.abs(tmax_out - tmax_adj).max():.3e}")
print(f"  tmin max abs diff vs computed: {np.abs(tmin_out - tmin_adj).max():.3e}")
print(f"  tmax range: {tmax_out.min():.4f} .. {tmax_out.max():.4f} degF")
print(f"  tmin range: {tmin_out.min():.4f} .. {tmin_out.max():.4f} degF")
print("Input param (read-only) still all-zero:")
print(f"  tmax_cbh_adj all-zero: {bool((tmax_in == 0).all())}")
print(f"  tmin_cbh_adj all-zero: {bool((tmin_in == 0).all())}")

assert np.allclose(tmax_out, tmax_adj, atol=_ATOL), "output tmax_cbh_adj != computed"
assert np.allclose(tmin_out, tmin_adj, atol=_ATOL), "output tmin_cbh_adj != computed"
assert (tmax_in == 0).all() and (tmin_in == 0).all(), "input param was modified!"
print("Comparison passed: output matches, input untouched.")

# %% [markdown]
# ## Histogram of per-HRU adjustments
#
# All `(nhru, 12)` adjustment values for tmax and tmin. With a signed monthly
# deficit the distribution spans both cooling (negative) and warming (positive)
# months, so the spread around zero reflects the measured monthly variation.

# %%
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

for ax, adj, label in (
    (axes[0], tmax_adj, "tmax_cbh_adj"),
    (axes[1], tmin_adj, "tmin_cbh_adj"),
):
    flat = adj.ravel()
    ax.hist(flat, bins=50, edgecolor="black", alpha=0.7)
    ax.axvline(x=0.0, color="black", linestyle="-", linewidth=1, label="0 (no change)")
    ax.axvline(
        x=float(flat.mean()),
        color="red",
        linestyle="--",
        label=f"mean ({flat.mean():.3f})",
    )
    ax.set_xlabel(f"{label} (degF)")
    ax.set_ylabel("Count (nhru x 12 months)")
    ax.set_title(f"{label} — all HRUs x months (signed, valley-pin)")
    ax.legend()

plt.tight_layout()
plt.show()

# %% [markdown]
# ## Diagnostic: monthly adjustment curves by elevation band
#
# Interactive Plotly figure, a 3x2 grid of panels. **Rows** are elevation bands —
# high (top), moderate (middle), low (bottom). **Columns** are the variable —
# `tmin_cbh_adj` on the left, `tmax_cbh_adj` on the right. Each panel plots the
# Jan-Dec adjustment time series for the same 5 HRUs sampled from that band, so
# the left/right pair shows how tmin and tmax behave at the same locations. Hover
# for per-month values; click legend entries to toggle HRUs. HRUs at or below the
# valley-pin `elev_ref` have a flat-zero curve by construction (no adjustment),
# expected in the low row. Saved as a standalone interactive HTML next to the
# output parameter file.

# %%
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Sample 5 HRUs from each of three elevation bands (thirds of the sorted
# hru_elev range), spread evenly across each band for reproducibility. Build a
# 3x2 grid: rows = bands (high/moderate/low), columns = variable (tmin, tmax).
order = np.argsort(hru_elev)          # ascending by elevation
n = len(order)
third = n // 3
bands = [
    ("High elevation", order[2 * third:][::-1]),   # highest first
    ("Moderate elevation", order[third:2 * third]),
    ("Low elevation", order[:third]),
]
variables = [("tmin_cbh_adj", tmin_adj), ("tmax_cbh_adj", tmax_adj)]
palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]

fig = make_subplots(
    rows=3, cols=2, shared_xaxes=True,
    horizontal_spacing=0.08, vertical_spacing=0.07,
    subplot_titles=[
        f"{v} — {b[0]} ({hru_elev[b[1]].min():.0f}-{hru_elev[b[1]].max():.0f} m)"
        for b in bands for v in ("tmin_cbh_adj", "tmax_cbh_adj")
    ],
)

for r, (title, idx_band) in enumerate(bands, start=1):
    picks = idx_band[np.linspace(0, len(idx_band) - 1, 5).round().astype(int)]
    for c, (vname, arr) in enumerate(variables, start=1):
        for color, i in zip(palette, picks):
            name = f"nhm_id {int(nhm_id[i])} ({hru_elev[i]:.0f} m)"
            fig.add_trace(
                go.Scatter(
                    x=month_names, y=np.round(arr[i], 4),
                    mode="lines+markers", name=name,
                    legendgroup=name, showlegend=(r == 1 and c == 1),
                    line=dict(color=color),
                    hovertemplate=f"{vname}<br>{name}<br>%{{x}}: %{{y:.3f}} degF<extra></extra>",
                ),
                row=r, col=c,
            )
        fig.add_hline(y=0.0, line=dict(color="black", width=1), row=r, col=c)

for r in range(1, 4):
    fig.update_yaxes(title_text="adjustment (degF)", row=r, col=1)
fig.update_layout(
    height=950, width=1150,
    title_text=(f"Monthly adjustment by elevation band "
                f"(valley-pin elev_ref = {elev_ref:.0f} m; "
                f"same 5 HRUs per row in both columns)"),
    legend_title_text="sampled HRU (per row)",
    template="plotly_white",
)

diag_html = warm_bias_dir / "tmax_tmin_cbh_adj_elevation_bands.html"
fig.write_html(str(diag_html))
print(f"Saved interactive diagnostic to: {diag_html}")
fig.show()

# %% [markdown]
# ## Map: `tmax_cbh_adj` and `tmin_cbh_adj` by month
#
# Interactive folium map with a **month selector**. All 24 param-month layers sit in a single exclusive radio group, so exactly
# one parameter and month is displayed at a time — the selected radio entry names
# what is on the map. Switch entries to see how the signed adjustment varies. January is shown by default. The base map offers USGS Hydro Cached (default) and OpenTopoMap, toggleable like the other OHM maps. Values
# are the adjustment in degF (negative = cooling with elevation, positive =
# warming); valley HRUs are ~0 in every month. A standalone HTML copy is also
# saved next to the output param.

# %%
import folium
from folium.plugins import GroupedLayerControl
from branca.colormap import LinearColormap

# HRU geometry (nhru layer). The adjustment arrays are in PARAM row order, so
# join them onto the geometry BY nhm_id rather than by row position: build an
# nhm_id-indexed lookup from the param-order nhm_id vector and map each month's
# column through it. (hru_gdf is already hru_id-sorted and nhm_id-aligned to the
# param order in Step 1, but mapping by nhm_id is correct regardless of order.)
map_gdf = hru_gdf[["nhm_id", "geometry"]].copy().to_crs(epsg=4326)
bounds = map_gdf.total_bounds
center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]

# Base layers matching the other OHM maps (05_solar_rad, 06_smidex): USGS Hydro
# Cached (default) + OpenTopoMap, both toggleable. tiles=None so neither is
# implicit.
m = folium.Map(location=center, zoom_start=9, tiles=None)
folium.TileLayer(
    tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSHydroCached/MapServer/tile/{z}/{y}/{x}",
    attr="USGS The National Map: Hydrography (NHD)",
    name="USGS Hydro Cached",
    overlay=False,
    control=True,
).add_to(m)
folium.TileLayer(
    tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attr="OpenTopoMap",
    name="OpenTopoMap",
    overlay=False,
    control=True,
    show=False,
).add_to(m)

# One shared diverging color scale per parameter, symmetric about 0 so warming
# and cooling read correctly (blue = cooling, red = warming).
def _symmetric_cmap(arr, caption):
    a = float(np.nanmax(np.abs(arr)))
    a = a if a > 0 else 1e-6
    return LinearColormap(
        colors=["blue", "cyan", "white", "orange", "red"],
        vmin=-a, vmax=a, caption=caption,
    )

cmap_tmax = _symmetric_cmap(tmax_adj, "tmax_cbh_adj (degF)")
cmap_tmin = _symmetric_cmap(tmin_adj, "tmin_cbh_adj (degF)")
cmap_tmax.add_to(m)
cmap_tmin.add_to(m)

# All 24 data layers (2 params x 12 months) go into ONE exclusive radio
# group, so exactly one param+month is displayed at a time.
data_layers = []
_first = True
for arr, cmap, pname in (
    (tmax_adj, cmap_tmax, "tmax_cbh_adj"),
    (tmin_adj, cmap_tmin, "tmin_cbh_adj"),
):
    for k in range(12):
        gdf = map_gdf.copy()
        # nhm_id -> month-k adjustment, from the param-order arrays.
        lookup = dict(zip(nhm_id, np.round(arr[:, k], 4)))
        gdf[pname] = gdf["nhm_id"].map(lookup)
        layer = folium.GeoJson(
            gdf[["nhm_id", pname, "geometry"]].to_json(),
            name=f"{pname} — {month_names[k]}",
            style_function=(
                lambda f, _cmap=cmap, _p=pname: {
                    "fillColor": _cmap(f["properties"][_p])
                    if f["properties"][_p] is not None else "gray",
                    "color": "black", "weight": 0.2, "fillOpacity": 0.7,
                }
            ),
            tooltip=folium.GeoJsonTooltip(fields=["nhm_id", pname]),
            show=_first,  # only the first layer (tmax Jan) on at startup
            overlay=False,
        )
        layer.add_to(m)
        data_layers.append(layer)
        _first = False

# Base-layer toggle (USGS Hydro Cached / OpenTopoMap). The grouped controls
# below handle the per-month overlays.
folium.LayerControl(collapsed=False).add_to(m)

# Single exclusive radio group over all param-month layers: one active layer
# at a time, so the selected radio entry is exactly what is on the map.
GroupedLayerControl(
    groups={"parameter — month": data_layers},
    exclusive_groups=True, collapsed=False,
).add_to(m)

map_html = warm_bias_dir / "tmax_tmin_cbh_adj_monthly_map.html"
m.save(str(map_html))
print(f"Saved monthly map to: {map_html}")
m
