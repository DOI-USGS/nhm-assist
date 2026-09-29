# %% [markdown]
# # GFv2r2 CONUS — computed segment parameters (per-VPU overlay)
#
# This workflow computes the segment-dimensioned PRMS parameters that are
# *derived by transfer* from the NHDPlus reference flowlines and the
# BANKFULL_CONUS dataset, and writes one standalone `$id,<param>` CSV per
# parameter into the fabric `param_source_files` folder.
#
# | Parameter | Method |
# |-----------|--------|
# | `seg_slope` | Length-weighted mean of overlapping ref-flowline slopes; waterbody handling |
# | `mann_n` | `0.1 * seg_slope ** 0.18` |
# | `seg_width` | Length-weighted mean of BANKFULL_WIDTH via COMID |
# | `seg_depth` | Length-weighted mean of BANKFULL_DEPTH via COMID |
# | `x_coef` | 0.2 default; 0.0 for waterbody and outlet segments |
# | `segment_type` | 0=segment, 1=headwater, 2=lake, 5=outbound |
#
# The identity/geometry segment parameters (`nhm_seg`, `tosegment`,
# `seg_length`, `seg_lat`, `seg_lon`) are produced by
# `gfv2r2_segment_identity_params`; this workflow reads `tosegment` from the
# geopackage for the outlet/headwater logic and does not rewrite those files.
#
# ## Why per-VPU
#
# At CONUS scale the reference-flowline overlay against ~2.67M national
# flowlines is memory-heavy and gives no progress feedback as one monolithic
# operation. Processing one VPU at a time bounds peak memory to a single
# region's flowlines, prints progress per VPU, and matches how the fabric is
# already partitioned (the `vpu` column). The method is identical to a single
# pass — only the iteration is chunked.
#
# Adapted from the OHM `create_segment_parameters` notebook.
#
# Parameter definitions from pyPRMS metadata and: Regan, R.S., Markstrom, S.L.,
# LaFontaine, J.H., and Norton, P.A., 2025, PRMS software release v6.0.0,
# https://doi.org/10.5066/P97032NH.

# %%
import pathlib as pl
import time

import geopandas as gpd
import numpy as np
import pandas as pd
from rich import pretty
from rich.console import Console

pretty.install()
con = Console()

# %% [markdown]
# ## Paths and constants

# %%
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]
source_gpkg = root_dir / "data_dependencies" / "gfv2r2" / "gfv2r2.gpkg"

ref_flowline_path = pl.Path(r"D:\reference_flowline.gpkg")
bankfull_path = pl.Path(r"D:\BANKFULL_CONUS\BANKFULL_CONUS.txt")
waterbodies_path = (
    root_dir
    / "nhf_assist"
    / "data_dependencies"
    / "main_waterbodies_conus"
    / "main_waterbodies.shp"
)

out_dir = pl.Path(
    r"D:\nhm-workspace\GF2v2_conus\fabrics\gf2v2_conus\param_source_files"
)
out_dir.mkdir(parents=True, exist_ok=True)

CRS_PROJ = "EPSG:5070"
BUFFER_M = 50.0            # segment buffer to catch co-linear ref flowlines
MIN_OVERLAP_FRAC = 0.01    # ref match must cover >=1% of the segment length
SLOPE_FILL = -9998         # reference-flowline slope fill value to drop
WATERBODY_SLOPE = 0.00001  # ref-flowline slope flagged inside a waterbody

# PRMS valid ranges (from metadata) used to clamp results.
SEG_SLOPE_MIN, SEG_SLOPE_MAX = 1e-7, 2.0
MANN_N_MIN, MANN_N_MAX = 0.001, 0.15
SEG_WIDTH_MIN, SEG_WIDTH_MAX, SEG_WIDTH_DEF = 0.18, 40000.0, 15.0
SEG_DEPTH_MIN, SEG_DEPTH_MAX, SEG_DEPTH_DEF = 0.03, 250.0, 1.0

con.print(f"source_gpkg: [cyan]{source_gpkg}[/]")
con.print(f"out_dir:     [cyan]{out_dir}[/]")


# %%
def write_param_csv(series: pd.Series, param: str, ids) -> pl.Path:
    """Write ``$id,<param>`` keyed on seg_id, sorted ascending. Skips if exists."""
    path = out_dir / f"{param}.csv"
    if path.exists():
        con.print(f"[yellow]skip[/] {param}.csv already exists")
        return None
    df = pd.DataFrame({"$id": np.asarray(ids).astype(int), param: np.asarray(series)})
    df = df.sort_values("$id").reset_index(drop=True)
    df.to_csv(path, index=False)
    return path


# %% [markdown]
# ## Load segments and the BANKFULL table
#
# BANKFULL is a plain COMID lookup, small enough to hold whole.

# %%
seg_gdf = gpd.read_file(source_gpkg, layer="nsegment")
seg_gdf["seg_id"] = seg_gdf["seg_id"].astype(int)
seg_proj_all = seg_gdf.to_crs(CRS_PROJ)
con.print(f"Loaded [green]{len(seg_gdf)}[/] segments, CRS {seg_gdf.crs}")

bankfull_df = pd.read_csv(bankfull_path).replace(-9999.0, np.nan)
bankfull_df["COMID"] = bankfull_df["COMID"].astype(int)
bankfull_lookup = bankfull_df[["COMID", "BANKFULL_WIDTH", "BANKFULL_DEPTH"]]
con.print(f"Loaded [green]{len(bankfull_df)}[/] BANKFULL records")

vpus = sorted(seg_gdf["vpu"].dropna().unique())
con.print(f"VPUs to process: {len(vpus)} -> {vpus}")

# %% [markdown]
# ## Per-VPU overlay
#
# For each VPU: read only that region's reference flowlines (by bounding box),
# spatially join them to buffered segments, compute each match's overlap length
# (vectorized), drop tributaries (<1% overlap) and slope fill values, then
# accumulate the length-weighted slope numerator/denominator and bankfull
# numerator/denominator per segment. Waterbody-flagged ref slopes
# (``0.00001``) are tracked so a mostly-waterbody segment can be set flat.


# %%
def overlay_one_vpu(seg_vpu_proj: gpd.GeoDataFrame) -> pd.DataFrame:
    """Return per-segment overlay aggregates for one VPU's segments."""
    bbox = tuple(seg_vpu_proj.to_crs(4326).total_bounds)
    ref = gpd.read_file(ref_flowline_path, layer="reference_flowlines", bbox=bbox)
    if len(ref) == 0:
        return pd.DataFrame()
    ref = ref.to_crs(CRS_PROJ)[["COMID", "slope", "geometry"]].copy()
    ref["COMID"] = ref["COMID"].astype(int)

    segb = seg_vpu_proj[["seg_id", "geometry"]].copy()
    segb["seg_geom"] = seg_vpu_proj.geometry
    segb["geometry"] = seg_vpu_proj.geometry.buffer(BUFFER_M)

    joined = gpd.sjoin(
        ref, segb[["seg_id", "seg_geom", "geometry"]],
        how="inner", predicate="intersects",
    ).drop(columns="index_right")
    if len(joined) == 0:
        return pd.DataFrame()

    rg = gpd.GeoSeries(joined.geometry.values, crs=CRS_PROJ)
    sg = gpd.GeoSeries(joined["seg_geom"].values, crs=CRS_PROJ).buffer(BUFFER_M)
    joined["overlap"] = rg.intersection(sg).length.values

    seg_len = pd.Series(
        seg_vpu_proj.geometry.length.values, index=seg_vpu_proj["seg_id"].values
    )
    joined["seg_len"] = joined["seg_id"].map(seg_len)
    joined = joined[joined["overlap"] >= MIN_OVERLAP_FRAC * joined["seg_len"]]
    joined = joined[joined["slope"] != SLOPE_FILL].copy()
    if len(joined) == 0:
        return pd.DataFrame()

    # Slope aggregates (length-weighted) + waterbody-slope tracking.
    joined["w_slope"] = joined["slope"] * joined["overlap"]
    joined["wb_ov"] = (joined["slope"] == WATERBODY_SLOPE) * joined["overlap"]

    # Bankfull aggregates (length-weighted), only where bankfull exists.
    jb = joined.merge(bankfull_lookup, on="COMID", how="left")
    jb["w_width"] = jb["BANKFULL_WIDTH"] * jb["overlap"]
    jb["w_depth"] = jb["BANKFULL_DEPTH"] * jb["overlap"]

    agg = joined.groupby("seg_id").agg(
        sum_ov=("overlap", "sum"),
        sum_w_slope=("w_slope", "sum"),
        wb_ov=("wb_ov", "sum"),
        n_ref=("COMID", "count"),
    )
    bf_agg = jb.dropna(subset=["BANKFULL_WIDTH", "BANKFULL_DEPTH"]).groupby("seg_id").agg(
        bf_ov=("overlap", "sum"),
        sum_w_width=("w_width", "sum"),
        sum_w_depth=("w_depth", "sum"),
    )
    return agg.join(bf_agg, how="left")


# %%
# The per-VPU overlay is the ~15-minute step. Cache its aggregates so the
# cheaper post-processing (waterbody flag, NN fill, clamp, topology) can be
# re-run without repeating it. Delete the cache file to force recomputation.
overlay_cache = out_dir / "_overlay_aggregates.parquet"

if overlay_cache.exists():
    overlay = pd.read_parquet(overlay_cache)
    con.print(f"Loaded cached overlay aggregates for {len(overlay)} segments")
else:
    t0 = time.time()
    parts = []
    for i, vpu in enumerate(vpus, 1):
        seg_vpu = seg_proj_all[seg_proj_all["vpu"] == vpu]
        part = overlay_one_vpu(seg_vpu)
        parts.append(part)
        con.print(
            f"  [{i:>2}/{len(vpus)}] VPU {vpu:<4} "
            f"segs={len(seg_vpu):>6} matched={len(part):>6} "
            f"elapsed={time.time() - t0:5.0f}s"
        )

    overlay = pd.concat([p for p in parts if len(p)], axis=0)
    # A segment can appear in more than one VPU bbox; sum the aggregates.
    overlay = overlay.groupby(level=0).sum(min_count=1)
    overlay.to_parquet(overlay_cache)
    con.print(
        f"Overlay complete for {len(overlay)} segments in {time.time() - t0:.0f}s "
        f"(cached to {overlay_cache.name})"
    )

# %% [markdown]
# ## Assemble per-segment results
#
# Build a full frame indexed by every seg_id, then fill slope, width, depth.

# %%
result = pd.DataFrame(index=seg_gdf["seg_id"].values)
result.index.name = "seg_id"

result["seg_slope"] = overlay["sum_w_slope"] / overlay["sum_ov"]
# Segments mostly overlapping waterbody-flagged flowlines -> flat.
wb_frac_slope = (overlay["wb_ov"] / overlay["sum_ov"]).reindex(result.index)
result.loc[wb_frac_slope > 0.5, "seg_slope"] = WATERBODY_SLOPE

result["seg_width"] = overlay["sum_w_width"] / overlay["bf_ov"]
result["seg_depth"] = overlay["sum_w_depth"] / overlay["bf_ov"]

# %% [markdown]
# ## Waterbody polygons
#
# Flag segments with >50% of length inside a lake/reservoir polygon and force
# them flat. Done once, globally.

# %%
# Unioning ~450k CONUS waterbody polygons into one geometry does not scale
# (it hangs). Instead, use a pairwise intersection overlay: sjoin finds the
# (segment, waterbody) pairs that actually touch, and we clip each such segment
# only against the waterbodies it intersects, then sum the clipped length per
# segment. Work is bounded to segments that actually overlap water.
# Segment lines with a clean RangeIndex; seg_id is a plain column. Using a
# non-seg_id index avoids sjoin's reset_index colliding with a seg_id column.
seg_lines = seg_proj_all[["seg_id", "geometry"]].reset_index(drop=True)

# Only keep waterbody polygons that touch a segment (bounds the work), and give
# them a clean positional index we can reference from the join result.
wb_gdf = gpd.read_file(waterbodies_path).to_crs(CRS_PROJ)[["geometry"]]
wb_touch = gpd.sjoin(
    wb_gdf.reset_index(drop=True),
    seg_lines[["geometry"]],
    how="inner",
    predicate="intersects",
)
wb_gdf = wb_gdf.loc[wb_touch.index.unique()].reset_index(drop=True)
con.print(f"Waterbody polygons touching any segment: {len(wb_gdf)}")

# Pairs of (segment row, waterbody row) that intersect.
pairs = gpd.sjoin(
    seg_lines[["geometry"]], wb_gdf, how="inner", predicate="intersects"
)
pairs["seg_id"] = seg_lines["seg_id"].to_numpy()[pairs.index.to_numpy()]
con.print(f"Segment-waterbody intersection pairs: {len(pairs)}")

if len(pairs) > 0:
    # Clip each intersecting segment against the union of just the waterbodies
    # it touches (small per-segment unions, not one national union).
    wb_by_seg = pairs.groupby("seg_id")["index_right"].apply(list)
    seg_geom_by_id = seg_lines.set_index("seg_id")["geometry"]
    wb_geom = wb_gdf["geometry"]
    inside_frac = {}
    for sid, wb_idx in wb_by_seg.items():
        line = seg_geom_by_id.loc[sid]
        local_wb = wb_geom.iloc[wb_idx].union_all()
        inside_frac[sid] = line.intersection(local_wb).length / line.length
    wb_frac_poly = pd.Series(inside_frac)
else:
    wb_frac_poly = pd.Series(dtype=float)

in_waterbody = (wb_frac_poly > 0.5).reindex(result.index).fillna(False)
result["in_waterbody"] = in_waterbody
result.loc[in_waterbody, "seg_slope"] = WATERBODY_SLOPE
con.print(f"Segments >50% inside a waterbody polygon: {int(in_waterbody.sum())}")

# %% [markdown]
# ## Nearest-neighbor fill for unmatched segments
#
# Segments with no usable ref overlap take the nearest ref flowline's value
# (slope from any non-fill flowline; bankfull from any flowline with bankfull).

# %%
# seg_id -> segment geometry, for building midpoints of missing segments.
seg_geom_lookup = seg_proj_all.set_index("seg_id")["geometry"]


def nn_fill(missing_ids, ref_cols_gdf, value_cols):
    """Nearest-neighbor lookup of value_cols for the missing segment ids.

    seg_id is carried positionally (not as a column or index) through the join
    to avoid geopandas' reset_index colliding with a seg_id column/index.
    """
    missing_ids = list(missing_ids)
    mids = seg_geom_lookup.loc[missing_ids].interpolate(0.5, normalized=True)
    pts = gpd.GeoDataFrame(geometry=mids.values, crs=CRS_PROJ).reset_index(drop=True)
    right = ref_cols_gdf[value_cols + ["geometry"]].reset_index(drop=True)

    nn = gpd.sjoin_nearest(pts, right, how="left")
    # nn's index is pts' positional index; map back to seg_id positionally.
    nn = nn[~nn.index.duplicated(keep="first")]
    out = pd.DataFrame(index=missing_ids)
    for c in value_cols:
        vals = pd.Series(index=range(len(missing_ids)), dtype="float64")
        vals.loc[nn.index] = nn[c].values
        out[c] = vals.values
    return out


# Domain-wide ref flowlines for the fills (bbox = whole segment set).
domain_bbox = tuple(seg_gdf.to_crs(4326).total_bounds)
ref_all = gpd.read_file(
    ref_flowline_path, layer="reference_flowlines", bbox=domain_bbox
).to_crs(CRS_PROJ)
ref_all["COMID"] = ref_all["COMID"].astype(int)

missing_slope = result.index[result["seg_slope"].isna()]
con.print(f"Segments needing slope NN-fill: {len(missing_slope)}")
if len(missing_slope) > 0:
    ref_slope = ref_all[ref_all["slope"] != SLOPE_FILL][["slope", "geometry"]]
    filled = nn_fill(missing_slope, ref_slope, ["slope"])
    result.loc[filled.index, "seg_slope"] = filled["slope"].values

missing_bf = result.index[result["seg_width"].isna()]
con.print(f"Segments needing bankfull NN-fill: {len(missing_bf)}")
if len(missing_bf) > 0:
    ref_bf = ref_all.merge(bankfull_lookup, on="COMID", how="inner").dropna(
        subset=["BANKFULL_WIDTH", "BANKFULL_DEPTH"]
    )[["BANKFULL_WIDTH", "BANKFULL_DEPTH", "geometry"]]
    filled = nn_fill(missing_bf, ref_bf, ["BANKFULL_WIDTH", "BANKFULL_DEPTH"])
    result.loc[filled.index, "seg_width"] = filled["BANKFULL_WIDTH"].values
    result.loc[filled.index, "seg_depth"] = filled["BANKFULL_DEPTH"].values

# %% [markdown]
# ## Clamp to PRMS ranges and derive `mann_n`

# %%
result["seg_slope"] = result["seg_slope"].clip(SEG_SLOPE_MIN, SEG_SLOPE_MAX)
result["mann_n"] = (0.1 * result["seg_slope"] ** 0.18).clip(MANN_N_MIN, MANN_N_MAX)
result["seg_width"] = result["seg_width"].fillna(SEG_WIDTH_DEF).clip(
    SEG_WIDTH_MIN, SEG_WIDTH_MAX
)
result["seg_depth"] = result["seg_depth"].fillna(SEG_DEPTH_DEF).clip(
    SEG_DEPTH_MIN, SEG_DEPTH_MAX
)

# %% [markdown]
# ## `x_coef` and `segment_type` from topology
#
# Uses `tosegment` (NaN outlet -> 0) and the waterbody flag.

# %%
tosegment = seg_gdf.set_index("seg_id")["to_segment"].fillna(0).astype(int)
result["tosegment"] = tosegment.reindex(result.index).fillna(0).astype(int)

result["x_coef"] = 0.2
result.loc[result["in_waterbody"], "x_coef"] = 0.0
result.loc[result["tosegment"] == 0, "x_coef"] = 0.0

receives_flow = set(tosegment.values) - {0}
result["segment_type"] = 0
result.loc[~result.index.isin(receives_flow), "segment_type"] = 1  # headwater
result.loc[result["tosegment"] == 0, "segment_type"] = 5           # outbound
result.loc[result["in_waterbody"], "segment_type"] = 2             # lake

# %% [markdown]
# ## Write the six parameter files

# %%
ids = pd.Series(result.index)
write_param_csv(result["seg_slope"], "seg_slope", ids)
write_param_csv(result["mann_n"], "mann_n", ids)
write_param_csv(result["seg_width"], "seg_width", ids)
write_param_csv(result["seg_depth"], "seg_depth", ids)
write_param_csv(result["x_coef"], "x_coef", ids)
write_param_csv(result["segment_type"].astype(int), "segment_type", ids)

con.print(
    f"\nseg_slope range {result['seg_slope'].min():.7f} - {result['seg_slope'].max():.4f}"
)
con.print(f"mann_n range {result['mann_n'].min():.4f} - {result['mann_n'].max():.4f}")
con.print(
    f"seg_width range {result['seg_width'].min():.2f} - {result['seg_width'].max():.2f} m"
)
con.print(
    f"seg_depth range {result['seg_depth'].min():.3f} - {result['seg_depth'].max():.3f} m"
)
con.print(
    f"x_coef: {int((result['x_coef'] == 0.2).sum())} at 0.2, "
    f"{int((result['x_coef'] == 0.0).sum())} at 0.0"
)
con.print(f"segment_type counts: {result['segment_type'].value_counts().to_dict()}")

# %% [markdown]
# ## Summary

# %%
con.print("\n[bold]Computed segment parameters written to:[/]")
con.print(f"  [cyan]{out_dir}[/]")
con.print(["seg_slope", "mann_n", "seg_width", "seg_depth", "x_coef", "segment_type"])
