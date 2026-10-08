# %% [markdown]
# # GFv2r2 CONUS — segment identity & geometry parameters to standalone CSVs
#
# This workflow derives the segment identity and geometry PRMS parameters
# directly from the gfv2r2 geopackage `nsegment` layer and writes one standalone
# `$id,<param>` CSV per parameter into the fabric `param_source_files` folder.
#
# These come straight from the fabric — no reference-flowline transfer is
# needed, so unlike the computed segment parameters (`seg_slope`, `mann_n`,
# `seg_width`, `seg_depth`, `x_coef`, `segment_type`) they run at full CONUS
# scale immediately.
#
# | Parameter | Source | Notes |
# |-----------|--------|-------|
# | `nhm_seg` | `seg_id` | The national segment id; the fabric-wide index |
# | `tosegment` | `to_segment` | Downstream segment; NaN (outlet) -> 0 |
# | `seg_length` | `lengthkm` | km -> meters; clamped to the PRMS floor of 1.0 m |
# | `seg_lat` | line centroid | Latitude, degrees North (EPSG:4326) |
# | `seg_lon` | line centroid | Longitude, degrees East (EPSG:4326) |
#
# The `nsegment` layer is EPSG:5070 (projected, meters), so centroids are taken
# in the projected CRS and reprojected to geographic coordinates for lat/lon.
#
# Like the other gfv2r2 parameter workflows, this only fills gaps: any output
# CSV that already exists is left untouched.

# %%
import pathlib as pl

import geopandas as gpd
import pandas as pd
from rich import pretty
from rich.console import Console

pretty.install()
con = Console()

# %% [markdown]
# ## Paths

# %%
import assist as _assist_pkg

root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]
source_gpkg = root_dir / "data_dependencies" / "gfv2r2" / "gfv2r2.gpkg"

out_dir = pl.Path(
    r"D:\nhm-workspace\GF2v2_conus\fabrics\gf2v2_conus\param_source_files"
)
out_dir.mkdir(parents=True, exist_ok=True)

# PRMS seg_length floor (meters). A few fabric segments have ~0 length; PRMS
# requires seg_length >= 1.0.
SEG_LENGTH_MIN_M = 1.0

# The PRMS metadata "maximum" for seg_length is 100 km. A handful of real
# fabric segments are longer. We do NOT clamp the high end (see the report
# after the seg_length write for why); this threshold only drives that report.
SEG_LENGTH_REPORT_M = 100_000.0

con.print(f"source_gpkg: [cyan]{source_gpkg}[/]")
con.print(f"out_dir:     [cyan]{out_dir}[/]")


# %%
def write_param_csv(series: pd.Series, param: str, ids: pd.Series) -> pl.Path:
    """Write ``$id,<param>`` using seg_id as the id, sorted ascending.

    Skips writing if the file already exists, so real values written by another
    workflow are never overwritten.
    """
    path = out_dir / f"{param}.csv"
    if path.exists():
        con.print(f"[yellow]skip[/] {param}.csv already exists")
        return None
    df = pd.DataFrame({"$id": ids.astype(int).values, param: series.values})
    df = df.sort_values("$id").reset_index(drop=True)
    df.to_csv(path, index=False)
    return path


# %% [markdown]
# ## Load the `nsegment` layer

# %%
seg_gdf = gpd.read_file(source_gpkg, layer="nsegment")
con.print(f"Loaded [green]{len(seg_gdf)}[/] segments, CRS {seg_gdf.crs}")
con.print(f"columns: {list(seg_gdf.columns)}")

seg_ids = seg_gdf["seg_id"].astype(int)

# Centroids in geographic coordinates, computed once (used for the long-segment
# report below and for seg_lat/seg_lon).
centroids = seg_gdf.geometry.centroid.to_crs(4326)
seg_gdf["_lat"] = centroids.y.values
seg_gdf["_lon"] = centroids.x.values

# How many segments flow into each segment (incoming count), from to_segment.
incoming_count = seg_gdf["to_segment"].dropna().astype(int).value_counts()

# %% [markdown]
# ## `nhm_seg` — the national segment id
#
# `nhm_seg` is simply `seg_id`.

# %%
write_param_csv(seg_ids, "nhm_seg", seg_ids)
con.print(f"[green]wrote[/] nhm_seg.csv  ({seg_ids.min()}..{seg_ids.max()})")

# %% [markdown]
# ## `tosegment` — downstream segment
#
# Outlets are NaN in the geopackage. Convert to `0` (the PRMS outlet sentinel).

# %%
tosegment = seg_gdf["to_segment"].fillna(0).astype(int)
write_param_csv(tosegment, "tosegment", seg_ids)
con.print(
    f"[green]wrote[/] tosegment.csv  "
    f"({int((tosegment == 0).sum())} outlets, to_segment NaN -> 0)"
)

# %% [markdown]
# ## `seg_length` — segment length in meters
#
# From `lengthkm` (km -> m), clamped to the PRMS minimum of 1.0 m.

# %%
seg_length_m = (seg_gdf["lengthkm"].astype(float) * 1000.0).clip(lower=SEG_LENGTH_MIN_M)
n_clamped = int((seg_gdf["lengthkm"].astype(float) * 1000.0 < SEG_LENGTH_MIN_M).sum())
write_param_csv(seg_length_m, "seg_length", seg_ids)
con.print(
    f"[green]wrote[/] seg_length.csv  "
    f"(range {seg_length_m.min():.2f} - {seg_length_m.max():.2f} m; "
    f"{n_clamped} clamped to {SEG_LENGTH_MIN_M} m)"
)

# %% [markdown]
# ### Report: segments longer than the PRMS metadata maximum
#
# The PRMS metadata lists a `seg_length` maximum of 100 km. A small number of
# real fabric segments exceed it, and they are **left at their true length,
# not clamped**. Clamping the high end would misstate the routing travel time
# for a segment, and it would do so for reaches that do not warrant it: these
# long segments sit in flat, low-relief terrain (the High Plains and Nebraska
# Sand Hills) or in engineered/coastal systems (South Florida canals, the
# Imperial Valley, the Louisiana and Houston coasts), where the fabric produces
# long single reaches precisely because there is little topographic branching.
# Consistent with that, almost all of them are headwaters carrying no upstream
# inflow, so clamping would have little routing benefit and would corrupt a
# real geometric length.

# %%
long_mask = (seg_gdf["lengthkm"].astype(float) * 1000.0) > SEG_LENGTH_REPORT_M
long_segs = seg_gdf.loc[long_mask].copy()
long_segs["len_km"] = long_segs["lengthkm"].astype(float)
long_segs["n_incoming"] = (
    long_segs["seg_id"].map(incoming_count).fillna(0).astype(int)
)
long_segs["to_seg"] = long_segs["to_segment"].fillna(0).astype(int)
long_segs = long_segs.sort_values("len_km", ascending=False)

n_long = len(long_segs)
n_headwater = int((long_segs["n_incoming"] == 0).sum())
con.print(
    f"\n[bold yellow]{n_long}[/] segment(s) exceed the PRMS seg_length maximum "
    f"of {SEG_LENGTH_REPORT_M / 1000:.0f} km - left UNCLAMPED at true length."
)
con.print(
    f"  {n_headwater} of {n_long} are headwaters (no segments flow into them); "
    f"total incoming across all: {int(long_segs['n_incoming'].sum())}."
)
con.print("  These sit in low-relief / engineered terrain where the fabric")
con.print("  produces long single reaches; clamping is intentionally avoided.")
con.print("\n  [bold]Long segments (seg_id | VPU | length km | #incoming | to_seg | lat, lon):[/]")
for _, r in long_segs.iterrows():
    con.print(
        f"    {int(r['seg_id']):>7d} | VPU {str(r['vpu']):<3} | "
        f"{r['len_km']:7.1f} km | in={int(r['n_incoming'])} | "
        f"to={int(r['to_seg']):>7d} | {r['_lat']:.3f} N, {r['_lon']:.3f} E"
    )

# %% [markdown]
# ## `seg_lat` / `seg_lon` — segment centroid coordinates
#
# The geographic centroid of each segment line (computed once, up front, in the
# projected CRS then reprojected to EPSG:4326).

# %%
seg_lat = seg_gdf["_lat"]
seg_lon = seg_gdf["_lon"]

write_param_csv(seg_lat, "seg_lat", seg_ids)
write_param_csv(seg_lon, "seg_lon", seg_ids)
con.print(
    f"[green]wrote[/] seg_lat.csv  (range {seg_lat.min():.3f} - {seg_lat.max():.3f} N)"
)
con.print(
    f"[green]wrote[/] seg_lon.csv  (range {seg_lon.min():.3f} - {seg_lon.max():.3f} E)"
)

# %% [markdown]
# ## Summary

# %%
con.print("\n[bold]Segment identity/geometry parameters written to:[/]")
con.print(f"  [cyan]{out_dir}[/]")
con.print(["nhm_seg", "tosegment", "seg_length", "seg_lat", "seg_lon"])
