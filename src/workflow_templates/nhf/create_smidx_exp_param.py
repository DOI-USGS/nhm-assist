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
    r"D:\nhm-workspace\GF2v2_conus\models\FlamingGorge\outputs\runtime\param_source_files"
)
climate_dir = pl.Path(
    r"D:\nhm-workspace\GF2v2_conus\models\FlamingGorge\outputs\runtime"
)
out_dir = pl.Path(
    r"D:\nhm-workspace\GF2v2_conus\models\FlamingGorge\outputs\runtime\param_source_files"
)
param_file = pl.Path(
    r"D:\nhm-workspace\GF2v2_conus\models\FlamingGorge\outputs\runtime\myparam.param"
)
out_dir.mkdir(parents=True, exist_ok=True)

# Decide the input source up front: if the per-HRU input CSVs are absent, the
# PRMS parameter file is the source. In that case the workflow reads inputs from
# param_file and writes the computed smidx_exp straight back into param_file
# instead of to a CSV.
use_param_file = not (param_source_dir / "carea_max.csv").exists()

_pdb = None  # ParameterFile handle; loaded when param_file is the input source
if use_param_file:
    from pyPRMS import ParameterFile
    from pyPRMS.metadata.metadata import MetaData
    print(f"Input source: parameter file ({param_file})")
    _pdb = ParameterFile(param_file, metadata=MetaData().metadata, verbose=False)
else:
    print(f"Input source: CSVs in {param_source_dir}")


# %% [markdown]
# ## Step 1: Read source parameters

# %%
# Read each input parameter from its per-parameter CSV when present, otherwise
# from the PRMS parameter file (loaded as _pdb in the paths cell). The "$id"
# column is only produced in CSV mode; it is used solely to label the output
# CSV rows, so it stays None when the param file is the source.
def load_param(name):
    """Return an input parameter as an array: from <name>.csv if present, else param_file."""
    global _pdb
    csv_path = param_source_dir / f"{name}.csv"
    if csv_path.exists():
        print(f"  {name}: from {csv_path.name}")
        return pd.read_csv(csv_path)[name].values

    if _pdb is None:
        from pyPRMS import ParameterFile
        from pyPRMS.metadata.metadata import MetaData
        print(f"  loading param file: {param_file}")
        _pdb = ParameterFile(param_file, metadata=MetaData().metadata, verbose=False)
    print(f"  {name}: from param file")
    return np.asarray(_pdb.get(name).data)


# "$id" labels for the output CSV; only available when carea_max comes from CSV.
smidx_exp_ids = None
if not use_param_file:
    smidx_exp_ids = pd.read_csv(param_source_dir / "carea_max.csv")["$id"]

carea_max = load_param("carea_max")
smidx_coef = load_param("smidx_coef")
soil_moist_max = load_param("soil_moist_max")

print(f"carea_max: {len(carea_max)} HRUs, range: {carea_max.min():.6f} - {carea_max.max():.6f}")
print(f"smidx_coef: {len(smidx_coef)} HRUs, range: {smidx_coef.min():.6f} - {smidx_coef.max():.6f}")
print(f"soil_moist_max: {len(soil_moist_max)} HRUs, range: {soil_moist_max.min():.6f} - {soil_moist_max.max():.6f}")

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
# soil_moist_max was read in Step 1 (from CSV or the param file).
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
# carea_max and smidx_coef were read in Step 1 (from CSV or the param file).
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
# ## Step 7: Write smidx_exp
#
# When the inputs came from CSVs, write `smidx_exp.csv`. When the parameter file
# was the input source, write `smidx_exp` straight back into it instead. The
# DataFrame is built in both modes so the comparison and histogram cells below
# work regardless of source.

# %%
# "$id" labels: from the input CSV when available, else a 1..N range.
smidx_exp_ids = smidx_exp_ids if smidx_exp_ids is not None else range(1, len(smidx_exp) + 1)
smidx_exp_df = pd.DataFrame({
    "$id": smidx_exp_ids,
    "smidx_exp": smidx_exp,
})

if use_param_file:
    _pdb.get("smidx_exp").data = smidx_exp
    _pdb.write_parameter_file(str(param_file))
    print(f"Updated smidx_exp in parameter file: {param_file}")
else:
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
