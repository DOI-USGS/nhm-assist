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
# # Make Snow Parameters
#
# This notebook creates three snow depletion parameters required by PRMS/pywatershed
# for simulating the snow-covered area of each HRU during the snowmelt period.
#
# ## Parameters produced
#
# | Parameter | Dimension | Description |
# |-----------|-----------|-------------|
# | `snarea_curve` | ndepl × 11 | Snow area depletion curve values. Each curve consists of 11 values representing areal snow coverage (0.0 to 1.0) at normalized SWE increments from 0% to 100% of the threshold value, in 10% steps. Up to 10 curves may be defined to represent different depletion patterns across the domain. |
# | `hru_deplcrv` | nhru | Index number assigning each HRU to one of the snow area depletion curves defined in `snarea_curve`. |
# | `snarea_thresh` | nhru | Maximum threshold snowpack water equivalent (inches) below which the snow-covered-area depletion curve is applied. Above this threshold, the HRU is assumed 100% snow covered. Varies with elevation and climate. |
#
# ## How these parameters interact in the model
#
# During snowmelt, the PRMSSnow module computes snow-covered area (`snowcov_area`)
# for each HRU using the depletion curve assigned by `hru_deplcrv`. The ratio of
# current snowpack water equivalent to either the seasonal peak SWE or `snarea_thresh`
# (whichever is smaller) is used as the index into the 11-point depletion curve.
# The resulting fractional snow coverage controls the effective area over which
# snowmelt and sublimation are computed.
#
# ## Source data
#
# Snow depletion curve parameters are derived from subgrid analysis of snow
# variability using the coefficient of variation (CV) of SWE (Sexstone and others, 2020) for the Oregon Hydrologic Model domain. Source data found in:
# `params_from_Rich_7_25_26/nhm_snarea_curve_params.csv` (per-HRU assignments)
# and `params_from_Rich_7_25_26/nhm_snarea_curve_library.csv` (curve definitions).
#
# ## Workflow steps
# 1. Read source data containing per-HRU curve assignments and threshold values
# 2. Write `hru_deplcrv.csv` — the curve index for each HRU
# 3. Write `snarea_thresh.csv` — the SWE threshold for each HRU
# 4. Write `snarea_curve.csv` — the 11-point depletion curves (flattened)
#
# ## References
# - Markstrom, S.L., et al., 2015, PRMS-IV, the precipitation-runoff modeling
#   system, version 4: U.S. Geological Survey Techniques and Methods 6-B7.
# - Sexstone, G.A., et al., 2020, Runoff sensitivity to snow depletion curve
#   representation within a continental scale hydrologic model: Hydrological
#   Processes, v. 34, p. 2365–2380.

# %%
import pandas as pd
import numpy as np
import pathlib as pl
import geopandas as gpd

# %% [markdown]
# ## Define paths

# %%
v2_gpkg_path = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\GIS\model_layers.gpkg"
)
out_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files")
out_dir.mkdir(parents=True, exist_ok=True)

source_dir = pl.Path(r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\params_from_Rich_7_25_26")

# %% [markdown]
# ## Read snow curve source data

# %%
snow_df = pd.read_csv(source_dir / "nhm_snarea_curve_params.csv")
print(f"Loaded {len(snow_df)} rows, columns: {snow_df.columns.tolist()}")

# %% [markdown]
# ## Write hru_deplcrv.csv and snarea_thresh.csv

# %%
# hru_deplcrv
hru_deplcrv = pd.DataFrame({
    "$id": snow_df["hru_id"],
    "hru_deplcrv": snow_df["hru_deplcrv"],
})
hru_deplcrv.to_csv(out_dir / "hru_deplcrv.csv", index=False)
print(f"Wrote hru_deplcrv.csv: {len(hru_deplcrv)} rows")

# snarea_thresh
snarea_thresh = pd.DataFrame({
    "$id": snow_df["hru_id"],
    "snarea_thresh": snow_df["snarea_thresh"],
})
snarea_thresh.to_csv(out_dir / "snarea_thresh.csv", index=False)
print(f"Wrote snarea_thresh.csv: {len(snarea_thresh)} rows")

# %% [markdown]
# ## Write snarea_curve.csv from curve library
# The curve library has 9 curves, each with 11 values (snarea_curve_0 to snarea_curve_10).
# Output format: values listed sequentially — all 11 values for curve 1, then curve 2, etc.
# $id column is simply 1 through 99 (9 curves × 11 values).

# %%
curve_library = pd.read_csv(source_dir / "nhm_snarea_curve_library.csv")
print(f"Loaded {len(curve_library)} curves from nhm_snarea_curve_library.csv")

# Extract the curve value columns in order
curve_cols = [f"snarea_curve_{i}" for i in range(11)]

# Flatten: all values for curve 1, then curve 2, etc.
curve_values = []
for _, row in curve_library.iterrows():
    for col in curve_cols:
        curve_values.append(row[col])

snarea_curve_df = pd.DataFrame({
    "$id": np.arange(1, len(curve_values) + 1),
    "snarea_curve": curve_values,
})

snarea_curve_df.to_csv(out_dir / "snarea_curve.csv", index=False)
print(f"Wrote snarea_curve.csv: {len(snarea_curve_df)} rows ({len(curve_library)} curves × 11 values)")

# %%
