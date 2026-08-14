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
# # Parameter Updates from Rich MacDonald
#
# This notebook compares parameter values in `params_from_Rich_7_25_26/` against
# the existing values in `param_source_files/`. It identifies which parameters
# have changed and summarizes the differences.

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
old_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files"
)

# %% [markdown]
# ## Compare all parameters in params_from_Rich_7_25_26 vs param_source_files
#
# Scans all CSV files in the source directory, identifies the parameter column(s),
# and compares to matching files in param_source_files. Only shows parameters
# that have a matching file in param_source_files.

# %% jupyter={"source_hidden": true}
print("=" * 80)
print("Full scan: params in params_from_Rich_7_25_26 with matches in param_source_files")
print("=" * 80)

source_csvs = sorted(source_dir.glob("*.csv"))
# Skip files that are not relevant to this comparison
skip_files = {
    "nhm_lulc_nhm_v11_params.csv",
    "nhm_snarea_curve_validation.csv",
    "nhm_snarea_curve_params.csv",
    "nhm_snarea_curve_library.csv",
}
source_csvs = [f for f in source_csvs if f.name not in skip_files]
print(f"Scanned {len(source_csvs)} CSV files in params_from_Rich_7_25_26\n")

# Skip non-parameter columns (identifiers, provenance, metadata)
skip_cols = {"hru_id", "$id", "hru_id_nhm", "seg_id", "segment_id"}
provenance_keywords = {"provenance", "source", "status", "class", "kind",
                       "assign", "similarity", "n_seasons", "n_peak", "peak_swe"}

matched_count = 0

for csv_file in source_csvs:
    df = pd.read_csv(csv_file)

    provenance_cols = {c for c in df.columns
                       if any(kw in c.lower() for kw in provenance_keywords)}
    param_cols = [c for c in df.columns if c not in skip_cols and c not in provenance_cols]

    for param_name in param_cols:
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

# %% [markdown]
# ## Write updated parameter CSVs to param_source_files
#
# For each parameter identified as CHANGED above, write the new values from
# params_from_Rich_7_25_26 to param_source_files/ in the standard format ($id, param_value).
#
# ### Parameter-to-column mapping
#
# | Parameter | Source file | Column used |
# |-----------|-------------|-------------|
# | `carea_max` | nhm_carea_max_params.csv | `carea_max` |
# | `dprst_depth_avg` | nhm_dprst_depth_avg_params.csv | `dprst_depth_avg` |
# | `dprst_frac` | nhm_dprst_frac_params.csv | `dprst_frac` |
# | `cov_type` | nhm_lulc_nalcms_params.csv | `cov_type` |
# | `srain_intcp` | nhm_lulc_nalcms_params.csv | `srain_intcp` |
# | `wrain_intcp` | nhm_lulc_nalcms_params.csv | `wrain_intcp` |
# | `snow_intcp` | nhm_lulc_nalcms_params.csv | `snow_intcp` |
# | `covden_sum` | nhm_lulc_nalcms_params.csv | `covden_sum` |
# | `covden_win` | nhm_lulc_nalcms_params.csv | `covden_win` |
# | `hru_slope` | nhm_slope_params.csv | `hru_slope` |
# | `smidx_coef` | nhm_smidx_coef_params.csv | `smidx_coef` |
# | `soil_moist_max` | nhm_soil_moist_max_params.csv | `soil_moist_max` |
# | `sro_to_dprst_imperv` | nhm_sro_to_dprst_imperv_params.csv | `sro_to_dprst_imperv` |
# | `sro_to_dprst_perv` | nhm_sro_to_dprst_perv_params.csv | `sro_to_dprst_perv` |
# | `hru_area` | nhm_ssflux_params.csv | `hru_area` |
# | `soil2gw_max` | nhm_ssflux_params.csv | `soil2gw_max` |
# | `ssr2gw_rate` | nhm_ssflux_params.csv | `ssr2gw_rate` |
# | `fastcoef_lin` | nhm_ssflux_params.csv | `fastcoef_lin` |
# | `slowcoef_lin` | nhm_ssflux_params.csv | `slowcoef_lin` |
# | `gwflow_coef` | nhm_ssflux_params.csv | `gwflow_coef` |
# | `dprst_seep_rate_open` | nhm_ssflux_params.csv | `dprst_seep_rate_open` |
# | `dprst_flow_coef` | nhm_ssflux_params.csv | `dprst_flow_coef` |
# | `hru_aspect` | nhm_aspect_params.csv | `mean` |
#
# Note: `hru_aspect` uses the `mean` column (zonal mean of aspect values).
# All other parameters use a column with the same name as the parameter.

# %%
out_dir = pl.Path(
    r"D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\param_source_files"
)

# List of changed parameters and their source files
changed_params = [
    ("carea_max", "nhm_carea_max_params.csv"),
    ("dprst_depth_avg", "nhm_dprst_depth_avg_params.csv"),
    ("dprst_frac", "nhm_dprst_frac_params.csv"),
    ("cov_type", "nhm_lulc_nalcms_params.csv"),
    ("srain_intcp", "nhm_lulc_nalcms_params.csv"),
    ("wrain_intcp", "nhm_lulc_nalcms_params.csv"),
    ("snow_intcp", "nhm_lulc_nalcms_params.csv"),
    ("covden_sum", "nhm_lulc_nalcms_params.csv"),
    ("covden_win", "nhm_lulc_nalcms_params.csv"),
    ("hru_slope", "nhm_slope_params.csv"),
    ("smidx_coef", "nhm_smidx_coef_params.csv"),
    ("soil_moist_max", "nhm_soil_moist_max_params.csv"),
    ("sro_to_dprst_imperv", "nhm_sro_to_dprst_imperv_params.csv"),
    ("sro_to_dprst_perv", "nhm_sro_to_dprst_perv_params.csv"),
    ("hru_area", "nhm_ssflux_params.csv"),
    ("soil2gw_max", "nhm_ssflux_params.csv"),
    ("ssr2gw_rate", "nhm_ssflux_params.csv"),
    ("fastcoef_lin", "nhm_ssflux_params.csv"),
    ("slowcoef_lin", "nhm_ssflux_params.csv"),
    ("gwflow_coef", "nhm_ssflux_params.csv"),
    ("dprst_seep_rate_open", "nhm_ssflux_params.csv"),
    ("dprst_flow_coef", "nhm_ssflux_params.csv"),
]

print(f"Writing {len(changed_params)} updated parameters to {out_dir}\n")

for param_name, source_file in changed_params:
    df = pd.read_csv(source_dir / source_file)

    values = df[param_name]

    # hru_area in the source CSV is in square meters; PRMS expects acres
    if param_name == "hru_area":
        values = values / 4046.8564

    out_df = pd.DataFrame({
        "$id": df["hru_id"],
        param_name: values,
    })

    out_path = out_dir / f"{param_name}.csv"
    out_df.to_csv(out_path, index=False)

    print(f"  Wrote {param_name}.csv ({len(out_df)} rows) from {source_file}")

# hru_aspect: uses the "mean" column from nhm_aspect_params.csv
aspect_df = pd.read_csv(source_dir / "nhm_aspect_params.csv")
aspect_out = pd.DataFrame({
    "$id": aspect_df["hru_id"],
    "hru_aspect": aspect_df["mean"],
})
aspect_out.to_csv(out_dir / "hru_aspect.csv", index=False)
print(f"  Wrote hru_aspect.csv ({len(aspect_out)} rows) from nhm_aspect_params.csv (mean column)")

print(f"\nDone. {len(changed_params) + 1} parameter files updated.")

# %%
