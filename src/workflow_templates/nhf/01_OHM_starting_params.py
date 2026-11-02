# %% [markdown]
# # OHM starting parameters
#
# Creates the starting parameters for the Oregon Recharge Model (OHM) from the
# derived modeling fabric. The fabric was built from GFv2 and the
# parameterization workflows developed by Rich McDonald, Parker Norton, and
# Adel Haj.
#
# ## Step 1: list parameters and copy them to the output root
#
# Lists the parameter CSVs in the `prms` folder and copies each one to the
# output root folder. The copies are identical to the `prms` files.

# %%
from pathlib import Path
import shutil

prms_dir = Path(r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21\param_source_files_2026_10_23\prms")
out_dir = Path(r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21\param_source_files_2026_10_23")

# %%
# List the parameters from the prms CSV file names.
param_csvs = sorted(prms_dir.glob("*.csv"))
print(f"{len(param_csvs)} parameters in prms:")
for csv_path in param_csvs:
    print(f"  {csv_path.stem}")

# %%
# Copy each prms CSV to the output root. Overwrites any existing copy with
# the same name, which is safe because the source is identical.
for csv_path in param_csvs:
    shutil.copy2(csv_path, out_dir / csv_path.name)
print(f"Copied {len(param_csvs)} files to {out_dir}")
