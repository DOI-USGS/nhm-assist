# %% [markdown]
# # GFv2r2 CONUS — default-valued parameters to standalone CSVs
#
# Many PRMS parameters are not derived from the fabric at all: they start as a
# single default value applied uniformly across their dimension, and are only
# later changed by calibration or a targeted workflow. This notebook writes one
# standalone `.csv` per such parameter, filled with its pyPRMS metadata default,
# in the same `$id,<param>` format the other `param_source_files` use.
#
# **This step only fills gaps.** Any parameter whose CSV already exists in the
# output folder is left untouched — so Rich's derived HRU parameters (and
# anything a later workflow has already written) are never overwritten.
#
# The authoritative default value, datatype, and dimension for every parameter
# come from `pyPRMS`'s bundled metadata (`MetaData().metadata['parameters']`),
# the same source the other fabric-building workflows use.
#
# ## What counts as "default-valued" here
#
# A parameter is written by this notebook when **all** of the following hold:
#
# - It belongs to the NHM parameter set. pyPRMS knows about hundreds of
#   parameters spanning modules this fabric does not use (glacier storage,
#   cascade routing, alternate temperature/precip distribution methods, map
#   output, and so on). Writing flat defaults for all of them would pollute the
#   fabric with parameters the NHM configuration never asks for. We bound the
#   output to the parameter set of a reference NHM fabric — the OHM
#   `param_source_files` folder — so only NHM parameters are ever written.
# - Its dimension is one of `['nhru']`, `['nhru', 'nmonths']`, or `['one']`.
#   These are the parameters whose default is a single scalar broadcast across
#   the whole dimension. (Segment- and poi-dimensioned parameters, and the
#   things derived from geometry, come from other workflows.)
# - It is not in `EXCLUDE` below — parameters that are dimensioned this way but
#   are genuinely computed elsewhere (HRU identity/geometry, solar tables).
# - Its output CSV does not already exist.

# %%
import pathlib as pl

import numpy as np
import pandas as pd
import pyogrio
from pyPRMS.metadata.metadata import MetaData
from rich import pretty
from rich.console import Console

pretty.install()
con = Console()

# %% [markdown]
# ## Directories and dimensions
#
# `nhru` is read straight from the gfv2r2 geopackage so the notebook is
# self-contained and never depends on another parameter file already existing.
# `nmonths` is always 12.

# %%
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]
source_gpkg = root_dir / "data_dependencies" / "gfv2r2" / "gfv2r2.gpkg"

out_dir = pl.Path(
    r"D:\nhm-workspace\GF2v2_conus\fabrics\gf2v2_conus\param_source_files"
)
out_dir.mkdir(parents=True, exist_ok=True)

# Reference NHM fabric whose parameter set bounds what this notebook may write.
# Only parameter names that appear here are considered part of the NHM set.
reference_param_dir = pl.Path(
    r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21\param_source_files"
)

N_HRU = int(pyogrio.read_info(source_gpkg, layer="nhru")["features"])
N_SEG = int(pyogrio.read_info(source_gpkg, layer="nsegment")["features"])
N_MONTHS = 12

con.print(f"nhru:     [cyan]{N_HRU}[/]  (from {source_gpkg.name})")
con.print(f"nsegment: [cyan]{N_SEG}[/]  (from {source_gpkg.name})")
con.print(f"out_dir:  [cyan]{out_dir}[/]")

# %% [markdown]
# ## Dimension sizing
#
# The `$id` index in these files is just a 1..N label with no meaning; only the
# number of rows matters, and it equals the product of the dimension sizes.

# %%
DIM_SIZES = {
    "nhru": N_HRU,
    "nsegment": N_SEG,
    "nmonths": N_MONTHS,
    "one": 1,
}


def dimension_size(dims: list[str]) -> int:
    size = 1
    for d in dims:
        size *= DIM_SIZES[d]
    return size


# Dimension combinations we treat as "constant default" here. Anything else
# (npoigages, ndeplval, ...) belongs to a different workflow. `nsegment` is
# included: some segment parameters (K_coef, obsin/obsout_segment,
# segment_flow_init) are pure constants and belong here, while the computed
# ones (seg_slope, mann_n, ...) are listed in EXCLUDE below.
DEFAULTABLE_DIMS = {
    ("nhru",),
    ("nhru", "nmonths"),
    ("nsegment",),
    ("one",),
}

# Parameters that happen to carry one of the defaultable dimensions but are
# NOT constant defaults — they are computed by other workflows. Never emit a
# flat default for these.
EXCLUDE = {
    # HRU identity / geometry (from the geopackage / identity workflow)
    "nhm_id",
    "hru_area",
    "hru_lat",
    "hru_lon",
    "hru_segment",
    "hru_type",
    # segment identity / geometry (from the segment identity workflow)
    "nhm_seg",
    "tosegment",
    "seg_length",
    "seg_lat",
    "seg_lon",
    # computed segment parameters (from the segment overlay workflow)
    "seg_slope",
    "mann_n",
    "seg_width",
    "seg_depth",
    "x_coef",
    "segment_type",
    # solar radiation tables (computed by the solar-rad workflow)
    "soltab_horad_potsw",
    "soltab_potsw",
    "soltab_potsw_cbh",
}

# %% [markdown]
# ## Select the parameters to write
#
# Start from every parameter pyPRMS knows about, keep the defaultable
# dimensions, drop the explicit exclusions, and drop anything already on disk.

# %%
meta = MetaData(verbose=False).metadata["parameters"]

# The NHM parameter set, taken from the reference fabric's file names.
nhm_param_set = {p.stem for p in reference_param_dir.glob("*.csv")}
con.print(
    f"reference NHM parameter set: [cyan]{len(nhm_param_set)}[/] parameters "
    f"({reference_param_dir.name})"
)

candidates = []
for name, info in meta.items():
    if name not in nhm_param_set:
        continue  # not part of the NHM parameter set — skip
    dims = tuple(info.get("dimensions", []))
    if dims not in DEFAULTABLE_DIMS:
        continue
    if name in EXCLUDE:
        continue
    candidates.append(name)
candidates.sort()

already_present = {p.stem for p in out_dir.glob("*.csv")}
to_write = [c for c in candidates if c not in already_present]
skipped_existing = [c for c in candidates if c in already_present]

con.print(
    f"{len(candidates)} defaultable parameters; "
    f"[yellow]{len(skipped_existing)}[/] already present (skipped), "
    f"[green]{len(to_write)}[/] to write."
)
con.print(f"skipped (already present): {sorted(skipped_existing)}")

# %% [markdown]
# ## Write one constant-default CSV per missing parameter
#
# Integer-typed parameters (`int32`) are written without a decimal point;
# float parameters keep their default as-is. The default is broadcast across
# every row of the parameter's dimension.


# %%
def write_default_csv(name: str, info: dict) -> tuple[pl.Path, int]:
    dims = list(info.get("dimensions", []))
    n = dimension_size(dims)
    default = info.get("default")
    datatype = info.get("datatype", "")

    if "int" in str(datatype):
        value = int(default)
    else:
        value = float(default)

    series = pd.Series(np.full(n, value))
    if "int" in str(datatype):
        series = series.astype(int)
    series.index = range(1, n + 1)  # 1..N label

    path = out_dir / f"{name}.csv"
    with open(path, "w", newline="") as f:
        f.write(f"$id,{name}\n")
        series.to_csv(f, index=True, header=False)
    return path, n


written = []
for name in to_write:
    info = meta[name]
    path, n = write_default_csv(name, info)
    dims = tuple(info.get("dimensions", []))
    written.append(name)
    con.print(
        f"[green]wrote[/] {path.name:24s} "
        f"({n:>9d} rows, dims={dims}, default={info.get('default')})"
    )

# %% [markdown]
# ## Summary

# %%
con.print(f"\n[bold]{len(written)}[/] default-parameter files written to:")
con.print(f"  [cyan]{out_dir}[/]")
con.print(sorted(written))
