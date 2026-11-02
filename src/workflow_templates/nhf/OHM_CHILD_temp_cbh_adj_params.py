# %% [markdown]
# # Create `tmax_cbh_adj` and `tmin_cbh_adj` Temperature-Bias Correction Parameters
#
# ## Summary
#
# This notebook computes per-HRU `tmax_cbh_adj` and `tmin_cbh_adj` additive
# temperature-bias correction parameters (degF) for the SandyRiver child model,
# from HRU elevation and a measured atmospheric lapse-rate deficit, then writes
# them into a NEW renamed PRMS parameter file
# (`myparam_mod_tadj.param`) without touching the input `myparam.param`.
#
# These are **starting values** for a later re-calibration, produced the same
# way the sibling `create_smidx_exp_param` workflow produces child-model
# parameters. Freeing/estimating them in PEST is a separate follow-up: this
# notebook touches NO `.tpl`/`.pst`/control files or the `pestpp_ies` directory.
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
# ## The problem (why a cooling correction aloft)
#
# The GridMET temperature forcing **under-lapses**: its effective temperature
# decrease with elevation is far shallower than the observed atmospheric lapse,
# so the forcing is too warm at high elevation. Precipitation aloft that should
# fall as snow instead falls as rain, producing an SWE deficit. This is
# documented for this basin in two prior reports under
# `D:\test_hw_calibration_results\Sandy_beta4\`:
#
# - `snow_rain_partition_diagnosis.md` — warm bias aloft shifts the rain/snow
#   partition toward rain, driving the SWE deficit.
# - `gridmet_warm_bias_verification.md` — verifies the GridMET winter warm bias
#   against SNOTEL + GHCN-Daily station observations and quantifies the lapse.
#
# The fix: cool the forcing by an amount that **grows with elevation** above a
# low-elevation (valley) reference where the report found ~zero bias, repairing
# the too-shallow lapse rate. The correction is never positive (never warms).
#
# ## Formula
#
# ```
# adj(hru) = -(deficit_degF_per_m) * max(0.0, hru_elev[hru] - elev_ref)
# ```
#
# with `deficit_degF_per_m > 0`, so `adj <= 0` everywhere (cooling), equal to 0
# at and below `elev_ref`. The same per-HRU value is broadcast to all 12 months.
#
# ## Design decisions (cataloged — all five are final for this task)
#
# | # | Decision | Chosen | Rejected alternative | Rationale |
# |---|----------|--------|----------------------|-----------|
# | 1 | Formulation | **Lapse-deficit**: cooling grows with height to repair the forcing's too-shallow lapse. | Direct bias-vs-elevation slope (regress station warm bias on elevation). | The direct bias-vs-elevation signal is noisy (`winter_tmax_bias_raw` vs elevation r≈0.14). The absolute observed-temperature lapse is a clean, strong signal (r=-0.925), so correcting the *lapse* is far better constrained. |
# | 2 | tmax vs tmin split | **Separate per-variable deficits, each from its OWN independently-derived observed and model lapse.** | A single shared adjustment, or reusing the tmax lapse for tmin. | Both observed lapses are clean regressions. tmin now uses its **own** observed lapse — a regression of `obs_winter_tmin` on station elevation (`n_days_winter >= 60`) from the warm-bias summary CSV = **-4.51 degC/km** (r = -0.916, n = 34) — and its **own** model baseline (model-effective tmin lapse **-1.20 degC/km**, r = -0.294). **Supersedes** the earlier approximation that reused the tmax observed lapse, which was forced only by the then-missing `obs_winter_tmin` column; `verify_gridmet_temp_bias.py` now writes that column, so tmin precision is measured, not fabricated. |
# | 3 | Anchoring | **Valley-pin**: `elev_ref` = low-elevation reference where the report found ~zero bias; cool everything above it, never warm. | Basin-mean pivot (warm below the mean, cool above it). | Valley-pin matches the report literally (zero bias in the valley). It deliberately **lowers basin-mean temperature**, which will shift PET and snowmelt — an accepted, intended consequence of this choice, not a side effect to correct. |
# | 4 | Monthly variation | **All months identical**: one value per HRU broadcast to all 12 columns. | Per-month adjustment. | A single bias adjustment per HRU for all months, by request; the lapse deficit used here is a winter (DJFM) quantity applied uniformly. |
# | 5 | Output | **New file** `myparam_mod_tadj.param`; input left untouched. | Overwriting `myparam.param` in place. | Preserve the original; mirror the write pattern of `create_smidx_exp_param` but to a renamed file so the baseline is never lost. |
#
# ## Exact numeric inputs and their sources
#
# - **Observed tmax winter lapse**: regress `obs_winter_tmax` on `elevation_m`
#   for stations with `n_days_winter >= 60` (SNOTEL + GHCN-Daily) in the
#   warm-bias CSV
#   (`d:\nhm-assist\.agents\tasks\gridmet-warm-bias-verification\gridmet_temp_bias_summary.csv`).
#   Slope ≈ **-0.008979 degF/m** = **-4.99 degC/km**, r = **-0.925**, n = **34**.
# - **Model effective winter tmax lapse**: **-1.34 degC/km** (r = -0.285), a
#   documented constant from `verify_gridmet_temp_bias.py` (winter-mean model
#   tmax vs `hru_elev`, 162 HRUs; not re-derived in this notebook).
# - **Lapse deficit tmax (observed − model)**: -4.99 − (-1.34) = **-3.65 degC/km**,
#   i.e. the forcing is ~3.65 degC/km too shallow. As a cooling-per-meter:
#   `(3.65/1000) * 1.8` ≈ **0.00657 degF/m**.
# - **Observed tmin winter lapse**: regress `obs_winter_tmin` on `elevation_m`
#   (same stations, `n_days_winter >= 60`) in the warm-bias CSV. Slope
#   ≈ **-0.008121 degF/m** = **-4.51 degC/km**, r = **-0.916**, n = **34**.
#   Derived independently here (no longer reused from tmax).
# - **Model effective winter tmin lapse**: **-1.20 degC/km** (r = -0.294), a
#   documented constant from `verify_gridmet_temp_bias.py` (winter-mean model
#   tmin vs `hru_elev`, 162 HRUs).
# - **Lapse deficit tmin (observed − model)**: -4.51 − (-1.20) = **-3.31 degC/km**.
#   As a cooling-per-meter: `(3.31/1000) * 1.8` ≈ **0.00596 degF/m**.
# - **`elev_ref` (valley anchor)**: **mean elevation of the 15 low stations
#   (`elevation_m < 300`) = 97.43 m**. The basin minimum `hru_elev` is ~0 m.
#
# ## References
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
# Warm-bias station summary CSV (SNOTEL + GHCN-Daily).
warm_bias_csv = pl.Path(
    r"d:\nhm-assist\.agents\tasks\gridmet-warm-bias-verification\gridmet_temp_bias_summary.csv"
)
# GIS geopackage (nhru layer) — used only for the HRU-count alignment assert.
gis_gpkg = runtime_dir / "GIS" / "model_layers.gpkg"

print(f"runtime_dir  : {runtime_dir}")
print(f"input_param  : {input_param}")
print(f"output_param : {output_param}")
print(f"warm_bias_csv: {warm_bias_csv}")
print(f"gis_gpkg     : {gis_gpkg}")

assert input_param.exists(), f"input param not found: {input_param}"
assert warm_bias_csv.exists(), f"warm-bias CSV not found: {warm_bias_csv}"

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

# HRU-count alignment check against the GIS geopackage (the param file's HRU
# dimension remains the authority for ordering/length; this only guards against
# a domain mismatch, mirroring create_tmax_allstar_params.py).
hru_gdf = gpd.read_file(gis_gpkg, layer="nhru")
assert nhru == len(hru_gdf), (
    f"param file HRU count ({nhru}) != geopackage nhru count ({len(hru_gdf)})"
)
print(f"GIS nhru layer count     : {len(hru_gdf)} (matches param file)")

# %% [markdown]
# ## Step 2: Derive the lapse deficits from the warm-bias CSV
#
# Re-run the observed-tmax lapse regression in-notebook so the numbers are not
# taken on faith: regress `obs_winter_tmax` on `elevation_m` over stations with
# `n_days_winter >= 60`. Convert degF/m to degC/km for display, subtract the
# documented model lapse to get the deficit, and convert the deficit back to a
# cooling-per-meter in degF/m.
#
# **tmin:** the observed tmin lapse is now derived **independently** by
# regressing `obs_winter_tmin` on `elevation_m` over the same stations
# (`n_days_winter >= 60`), mirroring the tmax regression. The warm-bias script
# (`verify_gridmet_temp_bias.py`) now writes the `obs_winter_tmin` column, so
# the earlier reuse-of-tmax approximation is no longer needed. The model tmin
# lapse baseline is the model-effective tmin lapse printed by that same script.

# %%
df = pd.read_csv(warm_bias_csv)
d = df[df["n_days_winter"] >= 60].copy()
n_sta = len(d)

x = d["elevation_m"].to_numpy(dtype=float)
y_tmax = d["obs_winter_tmax"].to_numpy(dtype=float)
y_tmin = d["obs_winter_tmin"].to_numpy(dtype=float)

# Observed tmax lapse: slope of obs winter tmax (degF) vs elevation (m).
obs_tmax_lapse_degF_per_m = float(np.polyfit(x, y_tmax, 1)[0])
r_tmax = float(np.corrcoef(x, y_tmax)[0, 1])

# Observed tmin lapse: slope of obs winter tmin (degF) vs elevation (m).
# Derived INDEPENDENTLY here (same stations, same n_days_winter >= 60 filter)
# from the obs_winter_tmin column the warm-bias script now produces — it is no
# longer reused from tmax.
obs_tmin_lapse_degF_per_m = float(np.polyfit(x, y_tmin, 1)[0])
r_tmin = float(np.corrcoef(x, y_tmin)[0, 1])

# degC/km for display: degF/m -> degC/m (/1.8) -> degC/km (*1000).
obs_tmax_lapse_degC_per_km = obs_tmax_lapse_degF_per_m / 1.8 * 1000.0
tmin_obs_lapse_degC_per_km = obs_tmin_lapse_degF_per_m / 1.8 * 1000.0

# Documented model effective winter lapse per variable, from the warm-bias
# verification script's HEADLINE NUMBERS block (winter-mean model tmax/tmin vs
# hru_elev over 162 HRUs). These are taken as documented constants rather than
# re-derived here (the model NetCDF drivers are read by that script, not this
# notebook).
model_tmax_lapse_degC_per_km = -1.34  # degC/km, r = -0.285 (verify_gridmet_temp_bias.py)
model_tmin_lapse_degC_per_km = -1.20  # degC/km, r = -0.294 (verify_gridmet_temp_bias.py)

# Deficit = observed - model (negative => observed lapse steeper/colder aloft).
tmax_deficit_degC_per_km = obs_tmax_lapse_degC_per_km - model_tmax_lapse_degC_per_km
# Cooling-per-meter magnitude in degF/m (applied as a NEGATIVE adjustment).
tmax_deficit_degF_per_m = (abs(tmax_deficit_degC_per_km) / 1000.0) * 1.8

# tmin uses its OWN independently-derived observed lapse and its OWN model
# baseline — no longer a reuse of tmax.
tmin_deficit_degC_per_km = tmin_obs_lapse_degC_per_km - model_tmin_lapse_degC_per_km
tmin_deficit_degF_per_m = (abs(tmin_deficit_degC_per_km) / 1000.0) * 1.8

print(f"Stations used (n_days_winter >= 60): n = {n_sta}")
print("--- TMAX ---")
print(
    f"  observed lapse: {obs_tmax_lapse_degF_per_m:.6f} degF/m "
    f"({obs_tmax_lapse_degC_per_km:.3f} degC/km), r = {r_tmax:.3f}, n = {n_sta}"
)
print(f"  model lapse   : {model_tmax_lapse_degC_per_km:.3f} degC/km (verify_gridmet_temp_bias.py)")
print(
    f"  deficit       : {tmax_deficit_degC_per_km:.3f} degC/km "
    f"=> {tmax_deficit_degF_per_m:.6f} degF/m cooling-per-meter"
)
print("--- TMIN (independent obs-tmin lapse from obs_winter_tmin vs elevation) ---")
print(
    f"  observed lapse: {obs_tmin_lapse_degF_per_m:.6f} degF/m "
    f"({tmin_obs_lapse_degC_per_km:.3f} degC/km), r = {r_tmin:.3f}, n = {n_sta}"
)
print(f"  model lapse   : {model_tmin_lapse_degC_per_km:.3f} degC/km (verify_gridmet_temp_bias.py)")
print(
    f"  deficit       : {tmin_deficit_degC_per_km:.3f} degC/km "
    f"=> {tmin_deficit_degF_per_m:.6f} degF/m cooling-per-meter"
)

# %% [markdown]
# ## Step 3: Choose the valley reference elevation (`elev_ref`)
#
# Valley-pin anchoring: `elev_ref` is the mean elevation of the low-elevation
# stations (`elevation_m < 300 m`) — the valley band where the report found
# ~zero bias. The correction is zero at and below this elevation and grows
# (cooling) above it.

# %%
low = d[d["elevation_m"] < 300]
elev_ref = float(low["elevation_m"].mean())
print(f"Low-elevation stations (< 300 m): n = {len(low)}")
print(f"elev_ref = {elev_ref:.4f} m")
print("  rationale: mean elevation of low-elevation stations (< 300 m) —")
print("  the valley band where the report found ~zero bias (valley-pin anchor).")

# %% [markdown]
# ## Step 4: Compute the per-HRU adjustments
#
# `adj(hru) = -(deficit_degF_per_m) * max(0, hru_elev - elev_ref)`, broadcast
# identically to all 12 months. Cooling grows with height above `elev_ref`;
# valley HRUs get ~0; no HRU is warmed.

# %%
height_above = np.maximum(0.0, hru_elev - elev_ref)

tmax_adj_1d = -tmax_deficit_degF_per_m * height_above
tmin_adj_1d = -tmin_deficit_degF_per_m * height_above

# Broadcast to (nhru, 12) — every month identical (Decision 4).
tmax_adj = np.repeat(tmax_adj_1d[:, None], 12, axis=1)
tmin_adj = np.repeat(tmin_adj_1d[:, None], 12, axis=1)

assert tmax_adj.shape == (nhru, 12), f"tmax_adj shape {tmax_adj.shape}"
assert tmin_adj.shape == (nhru, 12), f"tmin_adj shape {tmin_adj.shape}"
assert np.allclose(tmax_adj, tmax_adj[:, [0]]), "tmax_adj months not identical"
assert np.allclose(tmin_adj, tmin_adj[:, [0]]), "tmin_adj months not identical"
# Cooling only — nothing warms.
assert (tmax_adj <= 1e-9).all(), "tmax_adj has positive (warming) values"
assert (tmin_adj <= 1e-9).all(), "tmin_adj has positive (warming) values"

i_lo = int(np.argmin(hru_elev))
i_hi = int(np.argmax(hru_elev))
i_med = int(np.argsort(hru_elev)[len(hru_elev) // 2])

print("TMAX adjustment (degF), per-HRU 1-D:")
print(
    f"  min/mean/max : {tmax_adj_1d.min():.4f} / "
    f"{tmax_adj_1d.mean():.4f} / {tmax_adj_1d.max():.4f}"
)
print(f"  lowest  HRU (elev {hru_elev[i_lo]:.1f} m): {tmax_adj_1d[i_lo]:.4f}")
print(f"  median  HRU (elev {hru_elev[i_med]:.1f} m): {tmax_adj_1d[i_med]:.4f}")
print(f"  highest HRU (elev {hru_elev[i_hi]:.1f} m): {tmax_adj_1d[i_hi]:.4f}")
print("TMIN adjustment (degF), per-HRU 1-D:")
print(
    f"  min/mean/max : {tmin_adj_1d.min():.4f} / "
    f"{tmin_adj_1d.mean():.4f} / {tmin_adj_1d.max():.4f}"
)
print(f"  lowest  HRU (elev {hru_elev[i_lo]:.1f} m): {tmin_adj_1d[i_lo]:.4f}")
print(f"  median  HRU (elev {hru_elev[i_med]:.1f} m): {tmin_adj_1d[i_med]:.4f}")
print(f"  highest HRU (elev {hru_elev[i_hi]:.1f} m): {tmin_adj_1d[i_hi]:.4f}")

# %% [markdown]
# ## Step 5: Sanity check (required) — recompute the corrected effective lapse
#
# Pure array arithmetic (no pywatershed run). Regress the computed adjustment on
# `hru_elev` over the HRUs above `elev_ref`: the slope must equal
# `-deficit_degF_per_m`. Adding the deficit to the model lapse must move the
# effective lapse from ~-1.34 degC/km toward the observed ~-4.99 degC/km. Asserts
# fail loudly if the math drifts.

# %%
above = hru_elev > elev_ref

# tmax: slope of the adjustment vs elevation above elev_ref.
slope_tmax = float(np.polyfit(hru_elev[above], tmax_adj_1d[above], 1)[0])
assert np.isclose(slope_tmax, -tmax_deficit_degF_per_m, atol=1e-9), (
    f"tmax adj slope {slope_tmax:.8f} != -deficit {-tmax_deficit_degF_per_m:.8f}"
)
# tmin: same check.
slope_tmin = float(np.polyfit(hru_elev[above], tmin_adj_1d[above], 1)[0])
assert np.isclose(slope_tmin, -tmin_deficit_degF_per_m, atol=1e-9), (
    f"tmin adj slope {slope_tmin:.8f} != -deficit {-tmin_deficit_degF_per_m:.8f}"
)

# Effective lapse before/after applying the correction (degC/km). The adjustment
# cools with height, so the corrected effective lapse is model + deficit. Each
# variable uses its own model baseline.
tmax_eff_before = model_tmax_lapse_degC_per_km
tmax_eff_after = model_tmax_lapse_degC_per_km + tmax_deficit_degC_per_km
tmin_eff_before = model_tmin_lapse_degC_per_km
tmin_eff_after = model_tmin_lapse_degC_per_km + tmin_deficit_degC_per_km

print("Adjustment-vs-elevation slope (HRUs above elev_ref):")
print(f"  tmax slope = {slope_tmax:.8f} degF/m (expected {-tmax_deficit_degF_per_m:.8f})")
print(f"  tmin slope = {slope_tmin:.8f} degF/m (expected {-tmin_deficit_degF_per_m:.8f})")
print("Effective winter lapse (degC/km), before -> after correction:")
print(
    f"  tmax: {tmax_eff_before:.3f} -> {tmax_eff_after:.3f} "
    f"(observed target {obs_tmax_lapse_degC_per_km:.3f})"
)
print(
    f"  tmin: {tmin_eff_before:.3f} -> {tmin_eff_after:.3f} "
    f"(observed target {tmin_obs_lapse_degC_per_km:.3f})"
)
assert np.isclose(tmax_eff_after, obs_tmax_lapse_degC_per_km, atol=1e-6), (
    "corrected tmax lapse does not reach the observed lapse"
)
assert np.isclose(tmin_eff_after, tmin_obs_lapse_degC_per_km, atol=1e-6), (
    "corrected tmin lapse does not reach the observed lapse"
)
print("Sanity check passed: corrected lapse matches the observed lapse.")

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

print("Output param read-back:")
print(f"  tmax_cbh_adj shape {tmax_out.shape}, matches computed: {np.allclose(tmax_out, tmax_adj)}")
print(f"  tmin_cbh_adj shape {tmin_out.shape}, matches computed: {np.allclose(tmin_out, tmin_adj)}")
print(f"  tmax max abs diff vs computed: {np.abs(tmax_out - tmax_adj).max():.3e}")
print(f"  tmin max abs diff vs computed: {np.abs(tmin_out - tmin_adj).max():.3e}")
print(f"  tmax range: {tmax_out.min():.4f} .. {tmax_out.max():.4f} degF")
print(f"  tmin range: {tmin_out.min():.4f} .. {tmin_out.max():.4f} degF")
print("Input param (read-only) still all-zero:")
print(f"  tmax_cbh_adj all-zero: {bool((tmax_in == 0).all())}")
print(f"  tmin_cbh_adj all-zero: {bool((tmin_in == 0).all())}")

assert np.allclose(tmax_out, tmax_adj), "output tmax_cbh_adj != computed"
assert np.allclose(tmin_out, tmin_adj), "output tmin_cbh_adj != computed"
assert (tmax_in == 0).all() and (tmin_in == 0).all(), "input param was modified!"
print("Comparison passed: output matches, input untouched.")

# %% [markdown]
# ## Histogram of per-HRU adjustments
#
# One value per HRU (all months identical) for tmax and tmin, with vertical
# lines at 0 and at the mean adjustment.

# %%
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

for ax, adj_1d, label in (
    (axes[0], tmax_adj[:, 0], "tmax_cbh_adj"),
    (axes[1], tmin_adj[:, 0], "tmin_cbh_adj"),
):
    ax.hist(adj_1d, bins=40, edgecolor="black", alpha=0.7)
    ax.axvline(x=0.0, color="black", linestyle="-", linewidth=1, label="0 (no change)")
    ax.axvline(
        x=float(adj_1d.mean()),
        color="red",
        linestyle="--",
        label=f"mean ({adj_1d.mean():.3f})",
    )
    ax.set_xlabel(f"{label} (degF)")
    ax.set_ylabel("Number of HRUs")
    ax.set_title(f"Per-HRU {label} (valley-pin, cooling only)")
    ax.legend()

plt.tight_layout()
plt.show()

# %%
