# ---
# jupyter:
#   jupytext:
#     formats: nhf_assist/notebooks//ipynb,src/workflow_templates/nhf//py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.3
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Compute `smidx_exp` — Surface Runoff Soil Moisture Index Exponent
#
# ## Summary
#
# This notebook computes the `smidx_exp` parameter for each HRU using the method
# from the NHM v1.1 headwater (byHW) calibration workflow (`concatPARAM.f`, Markstrom).
#
# `smidx_exp` is the exponent in the PRMS surface runoff contributing area equation.
# Rather than being calibrated directly, it is **derived** from `carea_max`,
# `smidx_coef`, `soil_moist_max`, and `ppt_max` (maximum daily precipitation).
#
# ## PRMS Surface Runoff Equation
#
# In PRMS, the contributing area fraction for surface runoff is computed as:
#
# $$\text{contributing\_area} = \text{smidx\_coef} \times 10^{\text{smidx\_exp} \times \text{soil\_moisture\_index}}$$
#
# At the maximum soil moisture index (`smidx_max`), the contributing area should
# equal `carea_max`. Solving for `smidx_exp`:
#
# $$\text{smidx\_exp} = \left[\log_{10}\left(\frac{\text{carea\_max}}{\text{smidx\_coef}}\right)\right]^{1 / \text{smidx\_max}}$$
#
# ## Computing `smidx_max`
#
# In the byHW calibration workflow, `smidx_max` is NOT simply `soil_moist_max`.
# It is computed as:
#
# $$\text{smidx\_max} = 1.1 \times \text{soil\_moist\_max} + 0.5 \times \text{ppt\_max}$$
#
# Where:
# - `soil_moist_max` is the maximum soil moisture capacity for the HRU (inches),
#   inflated by 10% to account for the calibration range.
# - `ppt_max` is the maximum daily precipitation observed at the HRU (inches),
#   halved to represent a contribution to the soil moisture index.
#
# Per Markstrom: "use max soil_moist_max value so add 10% onto it
# (assuming we are using 10% range)"
#
# ## Original Fortran Implementation (byHW concatPARAM.f)
#
# ```fortran
# c now calculate smidx_max=soil_moist_max+(0.5*ppt_max)
#        do n=1,nhru
#         smidx_max(n)=(1.1*soil_moist_max(n))+(0.5*ppt_max(n))
#        end do
#
# c write out smidx_exp
#        do i=1,nhru
#          if(smidx(i).gt.carea(i))smidx(i)=0.99*carea(i)
#          Pnew=(log10(carea(i)/smidx(i)))**(1/smidx_max(i))
#          if(Pnew.gt.1.0)Pnew=1.0
#          write(20,31)Pnew
#        end do
# ```
#
# Key details from the Fortran code:
# 1. `smidx_max` = `1.1 * soil_moist_max + 0.5 * ppt_max` per HRU.
# 2. `smidx_coef` is constrained: if `smidx_coef > carea_max`, set to `0.99 * carea_max`.
#    This prevents a negative or undefined log value.
# 3. `smidx_coef` is NOT halved in this version (unlike the byHRU version).
# 4. `smidx_exp` is **clipped to a maximum of 1.0**.
# 5. All distributed parameters are bounded by `Pmin`/`Pmax` arrays.
#
# ## Allowable Range (from pyPRMS metadata)
#
# | Attribute | Value |
# |-----------|-------|
# | Minimum | 0.0 |
# | Maximum | 5.0 |
# | Default | 0.3 |
# | Units | 1.0/inch |
#
# Note: The Fortran code clips to 1.0, which is more restrictive than the
# metadata maximum of 5.0. We follow the Fortran code here.
#
# ## Parameters
#
# | Parameter | Source | Description |
# |-----------|--------|-------------|
# | `carea_max` | param_source_files | Maximum contributing area fraction (0–1) |
# | `smidx_coef` | param_source_files | Surface runoff coefficient |
# | `soil_moist_max` | param_source_files | Maximum soil moisture capacity (inches) |
# | `ppt_max` | gridmet_climate_drivers/prcp.nc | Maximum daily precipitation per HRU (inches) |
# | `smidx_exp` | **computed** | Derived exponent, clipped to [0.0, 1.0] |
#
# ## Workflow Steps
# 1. Read `carea_max`, `smidx_coef`, and `soil_moist_max` from param_source_files
# 2. Compute `ppt_max` per HRU from the precipitation climate driver (prcp.nc)
# 3. Compute `smidx_max = 1.1 * soil_moist_max + 0.5 * ppt_max`
# 4. Constrain `smidx_coef`: where `smidx_coef >= carea_max`, set to `0.99 * carea_max`
# 5. Compute `smidx_exp = log10(carea_max / smidx_coef) ^ (1 / smidx_max)`
# 6. Clip `smidx_exp` to [0.0, 1.0] (per Fortran code)
# 7. Write `smidx_exp.csv` to created_hru_params
#
# ## References
# - Markstrom, S.L., Regan, R.S., Hay, L.E., Viger, R.J., Webb, R.M.,
#   Payn, R.A., & LaFontaine, J.H. (2015). PRMS-IV, the precipitation-runoff
#   modeling system, version 4. U.S. Geological Survey Techniques and Methods, 6, B7.
# - NHM v1.1 calibration code: `byHW/src/concatPARAM.f`
#   (code.usgs.gov/wma/national-iwaas/nhm/nhm-software/nhm_v1x_calibration)

# %%
import pandas as pd
import numpy as np
import xarray as xr
import pathlib as pl

# %% [markdown]
# ## Define paths

# %%
param_source_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files"
)
climate_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\gridmet_climate_drivers"
)
out_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\created_hru_params"
)
out_dir.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## Step 1: Read source parameters

# %%
carea_max_df = pd.read_csv(param_source_dir / "carea_max.csv")
smidx_coef_df = pd.read_csv(param_source_dir / "smidx_coef.csv")
soil_moist_max_df = pd.read_csv(param_source_dir / "soil_moist_max.csv")

print(f"carea_max: {len(carea_max_df)} HRUs, range: {carea_max_df['carea_max'].min():.6f} - {carea_max_df['carea_max'].max():.6f}")
print(f"smidx_coef: {len(smidx_coef_df)} HRUs, range: {smidx_coef_df['smidx_coef'].min():.6f} - {smidx_coef_df['smidx_coef'].max():.6f}")
print(f"soil_moist_max: {len(soil_moist_max_df)} HRUs, range: {soil_moist_max_df['soil_moist_max'].min():.6f} - {soil_moist_max_df['soil_moist_max'].max():.6f}")

# %% [markdown]
# ## Step 2: Compute ppt_max per HRU
# Maximum daily precipitation observed at each HRU from the climate driver NetCDF.

# %%
prcp_file = climate_dir / "prcp.nc"
print(f"Reading precipitation data from: {prcp_file}")

ds_prcp = xr.open_dataset(prcp_file)
# Compute maximum daily precip per HRU (across all timesteps)
ppt_max = ds_prcp["prcp"].max(dim="time").values
ds_prcp.close()

print(f"ppt_max computed for {len(ppt_max)} HRUs")
print(f"  Range: {ppt_max.min():.4f} - {ppt_max.max():.4f} inches")

# %% [markdown]
# ## Step 3: Compute smidx_max
#
# Per the Fortran code (Markstrom):
# ```
# smidx_max = (1.1 * soil_moist_max) + (0.5 * ppt_max)
# ```
# The 1.1 multiplier adds 10% to soil_moist_max to account for the calibration
# range, and 0.5 * ppt_max represents the precipitation contribution to the
# soil moisture index.

# %%
soil_moist_max = soil_moist_max_df["soil_moist_max"].values
smidx_max = (1.1 * soil_moist_max) + (0.5 * ppt_max)

print(f"smidx_max computed for {len(smidx_max)} HRUs")
print(f"  Range: {smidx_max.min():.4f} - {smidx_max.max():.4f}")

# %% [markdown]
# ## Step 4: Constrain smidx_coef
#
# Per the Fortran code:
# ```fortran
# if(smidx(i).gt.carea(i)) smidx(i) = 0.99 * carea(i)
# ```
# `smidx_coef` must be less than `carea_max` to produce a valid (positive) log value.

# %%
carea_max = carea_max_df["carea_max"].values
smidx_coef = smidx_coef_df["smidx_coef"].values

# Floor smidx_coef at a small value to avoid division by zero
smidx_coef = np.where(smidx_coef == 0.0, 0.00000001, smidx_coef)

# Constrain: smidx_coef must be < carea_max
n_constrained = (smidx_coef >= carea_max).sum()
smidx_coef = np.where(smidx_coef >= carea_max, 0.99 * carea_max, smidx_coef)

print(f"smidx_coef constrained: {n_constrained} HRUs had smidx_coef >= carea_max (set to 0.99 * carea_max)")

# %% [markdown]
# ## Step 5: Compute smidx_exp
#
# ```
# smidx_exp = log10(carea_max / smidx_coef) ^ (1 / smidx_max)
# ```

# %%
ratio = carea_max / smidx_coef
smidx_exp = np.log10(ratio) ** (1.0 / smidx_max)

print(f"smidx_exp computed for {len(smidx_exp)} HRUs (before clipping)")
print(f"  Range: {np.nanmin(smidx_exp):.6f} - {np.nanmax(smidx_exp):.6f}")
print(f"  NaN count: {np.isnan(smidx_exp).sum()}")
print(f"  Inf count: {np.isinf(smidx_exp).sum()}")

# %% [markdown]
# ## Step 6: Clip to [0.0, 1.0] (OPTIONAL — currently disabled)
#
# The byHW calibration Fortran code clips smidx_exp at 1.0:
# ```fortran
# if(Pnew.gt.1.0) Pnew=1.0
# ```
# However, this clip was NOT used in the `concatPARAM.f` of the byHRU calibration
# step. The PRMS metadata allows values up to 5.0. This clip is commented out
# pending further evaluation.

# %%
n_above_1 = (smidx_exp > 1.0).sum()
n_below_0 = (smidx_exp < 0.0).sum()
n_above_5 = (smidx_exp > 5.0).sum()

print(f"Values > 1.0 (byHW would clip): {n_above_1}")
print(f"Values > 5.0 (exceeds PRMS maximum): {n_above_5}")
print(f"Values < 0.0: {n_below_0}")

# Clip is disabled — uncomment below to apply the byHW clip to 1.0
# smidx_exp = np.clip(smidx_exp, 0.0, 1.0)

print(f"\nFinal (no clip applied):")
print(f"  Range: {smidx_exp.min():.6f} - {smidx_exp.max():.6f}")
print(f"  Mean: {smidx_exp.mean():.6f}")

# %% [markdown]
# ## Step 7: Write smidx_exp.csv

# %%
smidx_exp_df = pd.DataFrame({
    "$id": carea_max_df["$id"],
    "smidx_exp": smidx_exp,
})

smidx_exp_df.to_csv(out_dir / "smidx_exp.csv", index=False)
print(f"Wrote smidx_exp.csv: {len(smidx_exp_df)} rows")
print(f"  Output: {out_dir / 'smidx_exp.csv'}")

# %% [markdown]
# ## Compare to existing smidx_exp (if available)

# %%
existing_file = param_source_dir / "smidx_exp.csv"
if existing_file.exists():
    existing_df = pd.read_csv(existing_file)
    diff = smidx_exp_df["smidx_exp"].values - existing_df["smidx_exp"].values
    print(f"Comparison to existing smidx_exp in param_source_files:")
    print(f"  Existing range: {existing_df['smidx_exp'].min():.6f} - {existing_df['smidx_exp'].max():.6f}")
    print(f"  Computed range: {smidx_exp_df['smidx_exp'].min():.6f} - {smidx_exp_df['smidx_exp'].max():.6f}")
    print(f"  Max absolute difference: {np.abs(diff).max():.6f}")
    print(f"  HRUs with difference > 0.001: {(np.abs(diff) > 0.001).sum()}")
else:
    print("No existing smidx_exp.csv found in param_source_files for comparison.")

# %% [markdown]
# ## Histogram of computed smidx_exp values

# %%
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(10, 5))
ax.hist(smidx_exp_df["smidx_exp"], bins=50, edgecolor="black", alpha=0.7)
ax.axvline(x=0.3, color="red", linestyle="--", label="Default (0.3)")
ax.axvline(x=1.0, color="orange", linestyle="--", label="Clip max (1.0)")
ax.set_xlabel("smidx_exp")
ax.set_ylabel("Number of HRUs")
ax.set_title("Distribution of computed smidx_exp values")
ax.legend()
plt.tight_layout()
plt.show()

# %%
