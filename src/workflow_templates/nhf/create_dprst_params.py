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
# # Create Depression Storage Parameters
#
# ## Summary
#
# This notebook creates depression storage (dprst) parameter CSV files for the
# OHM v2 domain from source data provided by Rich MacDonald.
#
# ## Parameters produced
#
# | Parameter | Description | Units |
# |-----------|-------------|-------|
# | `dprst_depth_avg` | Average depth of surface depressions | inches |
# | `dprst_frac` | Fraction of HRU area that is surface depressions | decimal |
# | `hru_percent_imperv` | Fraction of HRU area that is impervious | decimal |
# | `sro_to_dprst_imperv` | Fraction of impervious surface runoff that flows to depressions | decimal |
# | `sro_to_dprst_perv` | Fraction of pervious surface runoff that flows to depressions | decimal |
#
# ## Source data
#
# All source files are in:
# `params_from_Rich_7_25_26/`
#
# ## Workflow steps
# 1. Read each source CSV
# 2. Rename `hru_id` to `$id` to match paramdb format
# 3. Write each parameter as a two-column CSV (`$id`, parameter_value) to `created_hru_params/`

# %%
import pandas as pd
import numpy as np
import pathlib as pl

# %% [markdown]
# ## Define paths

# %%
source_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\params_from_Rich_7_25_26"
)
out_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files"
)
out_dir.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# ## Read source data and write parameter CSVs

# %%
# Define source files and their parameter column names
param_files = {
    "nhm_dprst_depth_avg_params.csv": "dprst_depth_avg",
    "nhm_dprst_frac_params.csv": "dprst_frac",
    "nhm_hru_percent_imperv_params.csv": "hru_percent_imperv",
    "nhm_sro_to_dprst_imperv_params.csv": "sro_to_dprst_imperv",
    "nhm_sro_to_dprst_perv_params.csv": "sro_to_dprst_perv",
}

for source_file, param_name in param_files.items():
    df = pd.read_csv(source_dir / source_file)

    # Create output with $id and parameter value only
    out_df = pd.DataFrame({
        "$id": df["hru_id"],
        param_name: df[param_name],
    })

    out_path = out_dir / f"{param_name}.csv"
    out_df.to_csv(out_path, index=False)

    print(f"Wrote {param_name}.csv: {len(out_df)} rows, "
          f"range: {out_df[param_name].min():.6f} - {out_df[param_name].max():.6f}")

# %% [markdown]
# ## Compare new values to existing values in param_source_files

# %%
old_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files"
)

print("=" * 80)
print("Comparison: new values (params_from_Rich_7_25_26) vs old (param_source_files)")
print("=" * 80)

for source_file, param_name in param_files.items():
    old_file = old_dir / f"{param_name}.csv"
    new_file = out_dir / f"{param_name}.csv"

    if not old_file.exists():
        print(f"\n  {param_name}: no existing file in param_source_files (new parameter)")
        continue

    old_df = pd.read_csv(old_file)
    new_df = pd.read_csv(new_file)

    old_vals = old_df[param_name].values
    new_vals = new_df[param_name].values

    diff = new_vals - old_vals
    n_changed = (np.abs(diff) > 1e-8).sum()
    n_total = len(diff)

    print(f"\n  {param_name}:")
    print(f"    Old range: {old_vals.min():.6f} - {old_vals.max():.6f}")
    print(f"    New range: {new_vals.min():.6f} - {new_vals.max():.6f}")
    print(f"    HRUs changed: {n_changed} of {n_total} ({100*n_changed/n_total:.1f}%)")
    if n_changed > 0:
        print(f"    Max absolute diff: {np.abs(diff).max():.6f}")
        print(f"    Mean absolute diff (changed only): {np.abs(diff[np.abs(diff) > 1e-8]).mean():.6f}")

# %% [markdown]
# ## Full comparison: all parameters in params_from_Rich_7_25_26 vs param_source_files
#
# Scans all CSV files in the source directory, identifies the parameter column(s),
# and compares to matching files in param_source_files. Only shows parameters
# that have a matching file in param_source_files.

# %%
print("=" * 80)
print("Full scan: params in params_from_Rich_7_25_26 with matches in param_source_files")
print("=" * 80)

source_csvs = sorted(source_dir.glob("*.csv"))
# Skip files that are not relevant to this comparison
skip_files = {"nhm_lulc_nhm_v11_params.csv"}
source_csvs = [f for f in source_csvs if f.name not in skip_files]
print(f"Scanned {len(source_csvs)} CSV files in params_from_Rich_7_25_26\n")

# Skip non-parameter columns (identifiers, provenance, metadata)
skip_cols = {"hru_id", "$id", "hru_id_nhm", "seg_id", "segment_id"}
provenance_keywords = {"provenance", "source", "status", "class", "kind",
                       "assign", "similarity", "n_seasons", "n_peak", "peak_swe"}

# Also skip parameters already written earlier in this notebook
already_written = set(param_files.values())

matched_count = 0

for csv_file in source_csvs:
    df = pd.read_csv(csv_file)

    provenance_cols = {c for c in df.columns
                       if any(kw in c.lower() for kw in provenance_keywords)}
    param_cols = [c for c in df.columns if c not in skip_cols and c not in provenance_cols]

    for param_name in param_cols:
        if param_name in already_written:
            continue

        old_file = old_dir / f"{param_name}.csv"

        if not old_file.exists():
            continue

        try:
            old_df = pd.read_csv(old_file)
            if param_name not in old_df.columns:
                continue

            new_vals = df[param_name].values
            old_vals = old_df[param_name].values

            if len(new_vals) != len(old_vals):
                print(f"  {param_name:<25} from: {csv_file.name}")
                print(f"    LENGTH MISMATCH (new={len(new_vals)}, old={len(old_vals)})")
                matched_count += 1
                continue

            diff = new_vals - old_vals
            n_changed = (np.abs(diff) > 1e-8).sum()
            n_total = len(diff)

            status = "CHANGED" if n_changed > 0 else "SAME"
            print(f"  {param_name:<25} [{status}]  from: {csv_file.name}")
            print(f"    old range: [{old_vals.min():.6f}, {old_vals.max():.6f}]")
            print(f"    new range: [{new_vals.min():.6f}, {new_vals.max():.6f}]")
            if n_changed > 0:
                print(f"    HRUs changed: {n_changed} of {n_total} ({100*n_changed/n_total:.1f}%)")
                print(f"    Max abs diff: {np.abs(diff).max():.6f}")
            print()
            matched_count += 1

        except Exception as e:
            print(f"  {param_name} ({csv_file.name}): error — {e}")

print(f"Total parameters with matches in param_source_files: {matched_count}")

# %%
