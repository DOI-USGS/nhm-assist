# %% [markdown]
# # GFv2r2 CONUS — Rich's parameters to standalone CSVs
#
# This workflow reads the raw Geospatial Fabric version 2 (release 2, "gfv2r2")
# parameter files that Rich produced and writes one standalone `.csv` per PRMS
# parameter, in the `$id,<param>` format used elsewhere in the fabric
# `param_source_files` folders.
#
# Rich's source `.csv` files carry many columns; most are statistics and
# diagnostics. Only the columns called out in his `Readme.txt` are parameter
# values. This notebook encodes that Readme as an explicit mapping so the
# selection is auditable, then extracts, renames, and writes each parameter.
#
# **Rich's parameters are the first step** in building the gf2v2 CONUS fabric;
# other parameter groups (segments, pois, defaults) are produced by separate
# workflows.
#
# Source of truth for the column selection is
# `data_dependencies/gfv2r2/Readme.txt`. Key points from it:
#
# - HRU id column is `nat_hru_id` (361,472 HRUs, one row per HRU, gaps filled).
# - Use only the listed columns; everything else is diagnostics.
# - `hru_elev` comes from the elevation file's `mean` column (renamed).
# - `hru_aspect` is the `hru_aspect` column, **not** `mean`.
# - `soil_type` comes from the soils file's `soils` column (renamed).
# - Land cover uses **one** of two files; we use `nhm_lulc_nhm_v11_params.csv`
#   because it is the only one that carries `rad_trncf`.

# %%
import os
import pathlib as pl
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from rich import pretty
from rich.console import Console

pretty.install()
con = Console()

try:
    import jupyter_black

    jupyter_black.load()
except Exception:
    pass

# %% [markdown]
# ## Directories
#
# `source_dir` is Rich's raw gfv2r2 delivery inside the nhm-assist repo.
# `out_dir` is the fabric `param_source_files` folder the standalone parameter
# CSVs are written to. Edit `out_dir` if the fabric lives elsewhere.

# %%
# Locate the nhm-assist repo root via the editable-installed `assist` package,
# which is robust to the checkout directory name and the current working dir.
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]

source_dir = root_dir / "data_dependencies" / "gfv2r2"

out_dir = pl.Path(
    r"D:\nhm-workspace\GF2v2_conus\fabrics\gf2v2_conus\param_source_files"
)
out_dir.mkdir(parents=True, exist_ok=True)

con.print(f"source_dir: [cyan]{source_dir}[/]")
con.print(f"out_dir:    [cyan]{out_dir}[/]")

# The HRU id column in every one of Rich's per-HRU files.
HRU_ID_COL = "nat_hru_id"

# %% [markdown]
# ## Output format
#
# Every standalone parameter file matches the fabric convention: a header line
# `$id,<param>`, then one row per HRU indexed 1..N. The index is the position
# (1..N) in Rich's file order, not `nat_hru_id` itself — this is the same
# 1..N model-local indexing the other `param_source_files` use.


# %%
def write_param_csv(series: pd.Series, param: str, out_dir: pl.Path) -> pl.Path:
    """Write a single parameter as ``$id,<param>`` with a 1..N index."""
    s = series.reset_index(drop=True).copy()
    s.index = range(1, len(s) + 1)  # 1..N model-local index
    path = out_dir / f"{param}.csv"
    with open(path, "w", newline="") as f:
        f.write(f"$id,{param}\n")
        s.to_csv(f, index=True, header=False)
    return path


def load_source(name: str) -> pd.DataFrame:
    """Read one of Rich's gfv2r2 source CSVs, sorted by HRU id."""
    df = pd.read_csv(source_dir / name)
    if HRU_ID_COL in df.columns:
        df = df.sort_values(HRU_ID_COL).reset_index(drop=True)
    return df


# %% [markdown]
# ## The Readme, encoded as a mapping
#
# `SIMPLE_PARAMS` maps each output parameter to `(source_file, source_column)`.
# Where the Readme says to rename a column (`mean` -> `hru_elev`,
# `soils` -> `soil_type`) the output parameter name and the source column
# differ; otherwise they are the same.

# %%
# Topography, soils/subsurface single-value params, runoff/depression storage,
# and land cover — each pulled by (file, column). The output filename is the
# dict key.
SIMPLE_PARAMS: dict[str, tuple[str, str]] = {
    # TOPOGRAPHY
    "hru_elev": ("nhm_elevation_params.csv", "mean"),  # rename mean -> hru_elev
    "hru_slope": ("nhm_slope_params.csv", "hru_slope"),
    "hru_aspect": ("nhm_aspect_params.csv", "hru_aspect"),  # NOT "mean"
    # SOILS AND SUBSURFACE
    "soil_type": ("nhm_soils_params.csv", "soils"),  # rename soils -> soil_type
    "soil_moist_max": ("nhm_soil_moist_max_params.csv", "soil_moist_max"),
    # RUNOFF AND DEPRESSION STORAGE
    "carea_max": ("nhm_carea_max_params.csv", "carea_max"),
    "smidx_coef": ("nhm_smidx_coef_params.csv", "smidx_coef"),
    "hru_percent_imperv": (
        "nhm_hru_percent_imperv_params.csv",
        "hru_percent_imperv",
    ),
    "dprst_frac": ("nhm_dprst_frac_params.csv", "dprst_frac"),
    "dprst_depth_avg": ("nhm_dprst_depth_avg_params.csv", "dprst_depth_avg"),
    "op_flow_thres": ("nhm_op_flow_thres_params.csv", "op_flow_thres"),
    "sro_to_dprst_perv": ("nhm_sro_to_dprst_perv_params.csv", "sro_to_dprst_perv"),
    "sro_to_dprst_imperv": (
        "nhm_sro_to_dprst_imperv_params.csv",
        "sro_to_dprst_imperv",
    ),
}

# Subsurface flux params that all live in one multi-column file. The Readme
# lists these seven columns from nhm_ssflux_params.csv.
SSFLUX_FILE = "nhm_ssflux_params.csv"
SSFLUX_PARAMS = [
    "soil2gw_max",
    "ssr2gw_rate",
    "fastcoef_lin",
    "slowcoef_lin",
    "gwflow_coef",
    "dprst_seep_rate_open",
    "dprst_flow_coef",
]

# Land cover: the Readme says use ONE of two files. We use the nhm_v11 file
# because it is the only one carrying rad_trncf. (The nalcms file provides the
# same set except rad_trncf, if that source is ever preferred instead.)
LULC_FILE = "nhm_lulc_nhm_v11_params.csv"
LULC_PARAMS = [
    "cov_type",
    "covden_sum",
    "covden_win",
    "snow_intcp",
    "srain_intcp",
    "wrain_intcp",
    "rad_trncf",
]

# %% [markdown]
# ## Write the single-column parameters
#
# Topography, soils, subsurface single values, runoff/depression storage.

# %%
written: list[str] = []

for param, (fname, col) in SIMPLE_PARAMS.items():
    df = load_source(fname)
    if col not in df.columns:
        con.print(f"[red]{param}[/]: column '{col}' not in {fname} — skipping")
        continue
    path = write_param_csv(df[col], param, out_dir)
    written.append(param)
    con.print(f"[green]wrote[/] {path.name}  ({len(df)} HRUs, from {fname}:{col})")

# %% [markdown]
# ## Write the subsurface-flux parameters
#
# All seven come from the single `nhm_ssflux_params.csv` file.

# %%
ssflux = load_source(SSFLUX_FILE)
for param in SSFLUX_PARAMS:
    if param not in ssflux.columns:
        con.print(f"[red]{param}[/]: not in {SSFLUX_FILE} — skipping")
        continue
    path = write_param_csv(ssflux[param], param, out_dir)
    written.append(param)
    con.print(f"[green]wrote[/] {path.name}  ({len(ssflux)} HRUs, from {SSFLUX_FILE})")

# %% [markdown]
# ## Write the land-cover parameters
#
# From the nhm_v11 LULC file (the one with `rad_trncf`).

# %%
lulc = load_source(LULC_FILE)
for param in LULC_PARAMS:
    if param not in lulc.columns:
        con.print(f"[red]{param}[/]: not in {LULC_FILE} — skipping")
        continue
    path = write_param_csv(lulc[param], param, out_dir)
    written.append(param)
    con.print(f"[green]wrote[/] {path.name}  ({len(lulc)} HRUs, from {LULC_FILE})")

# %% [markdown]
# ## Snow depletion
#
# `nhm_snarea_curve_params.csv` carries, per HRU: `hru_deplcrv` (an id 1..9),
# `snarea_thresh`, and the 11 curve points `snarea_curve_0..10` inline. Every
# HRU's inline points are exactly the row for its `hru_deplcrv` in
# `nhm_snarea_curve_library.csv`, so the curves themselves are stored once in
# the library.
#
# We write:
#
# - `hru_deplcrv.csv` — per-HRU depletion-curve id.
# - `snarea_thresh.csv` — per-HRU threshold.
# - `snarea_curve.csv` — the 9 library curves flattened to `9 * 11 = 99`
#   values, indexed 1..99. This is the PRMS `ndeplval` layout (curve `k`'s 11
#   points occupy flattened indices `(k-1)*11+1 .. k*11`), and matches how the
#   fabric stores `snarea_curve` elsewhere.

# %%
snarea = load_source("nhm_snarea_curve_params.csv")

write_param_csv(snarea["hru_deplcrv"].astype(int), "hru_deplcrv", out_dir)
written.append("hru_deplcrv")
con.print(f"[green]wrote[/] hru_deplcrv.csv  ({len(snarea)} HRUs)")

write_param_csv(snarea["snarea_thresh"], "snarea_thresh", out_dir)
written.append("snarea_thresh")
con.print(f"[green]wrote[/] snarea_thresh.csv  ({len(snarea)} HRUs)")

# Flatten the library's 9 curves (ordered by deplcrv_id) into one column.
library = pd.read_csv(source_dir / "nhm_snarea_curve_library.csv")
library = library.sort_values("deplcrv_id").reset_index(drop=True)
curve_cols = [f"snarea_curve_{i}" for i in range(11)]
flat = library[curve_cols].to_numpy().reshape(-1)  # row-major: curve by curve
write_param_csv(pd.Series(flat), "snarea_curve", out_dir)
written.append("snarea_curve")
con.print(
    f"[green]wrote[/] snarea_curve.csv  "
    f"({len(library)} curves x 11 = {len(flat)} values)"
)

# %% [markdown]
# ## Summary

# %%
con.print(f"\n[bold]{len(written)}[/] parameter files written to:")
con.print(f"  [cyan]{out_dir}[/]")
con.print(sorted(written))
