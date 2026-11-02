# %% [markdown]
# # GFv2r2 CONUS — HRU identity & geometry parameters to standalone CSVs
#
# This workflow derives the HRU identity and geometry PRMS parameters directly
# from the gfv2r2 geopackage `nhru` layer and writes one standalone
# `$id,<param>` CSV per parameter into the fabric `param_source_files` folder.
#
# These are not model-fit values — they come straight from the fabric geometry
# and its national indexing:
#
# | Parameter | Source | Notes |
# |-----------|--------|-------|
# | `nhm_id` | `nat_hru_id` | The national HRU id; the fabric-wide HRU index |
# | `hru_segment` | `hru_segment` column | Downstream segment (0 = drains to ocean) |
# | `hru_area` | `hru_area` column | Geopackage is km^2; PRMS wants acres (x 247.105) |
# | `hru_lat` | polygon centroid | Latitude, degrees North (EPSG:4326) |
# | `hru_lon` | polygon centroid | Longitude, degrees East (EPSG:4326) |
# | `hru_type` | constant `1` | Not carried in the fabric; PRMS default (land) |
#
# The `nhru` layer is EPSG:5070 (a projected CRS in meters), so `hru_area` from
# the layer / geometry is in km^2 and centroids must be reprojected to
# geographic coordinates for `hru_lat`/`hru_lon`.
#
# Like the other gfv2r2 parameter workflows, this only fills gaps: any output
# CSV that already exists is left untouched.

# %%
import pathlib as pl

import geopandas as gpd
import numpy as np
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
source_gpkg = pl.Path(r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21\GIS\model_layers.gpkg")

out_dir = pl.Path(
    r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21\param_source_files_2026_10_23\hru_identity_params"
)
out_dir.mkdir(parents=True, exist_ok=True)

# km^2 -> acres. The geopackage hru_area (and EPSG:5070 geometry area) is in
# square kilometers; PRMS hru_area is in acres.
KM2_TO_ACRES = 247.105

con.print(f"source_gpkg: [cyan]{source_gpkg}[/]")
con.print(f"out_dir:     [cyan]{out_dir}[/]")


# %%
def write_param_csv(series: pd.Series, param: str, ids: pd.Series) -> pl.Path:
    """Write ``$id,<param>`` using nat_hru_id as the id, sorted ascending.

    Skips writing (and returns None) if the file already exists, so real
    values written by another workflow are never overwritten.
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
# ## Load the `nhru` layer

# %%
hru_gdf = gpd.read_file(source_gpkg, layer="nhru")
con.print(f"Loaded [green]{len(hru_gdf)}[/] HRUs, CRS {hru_gdf.crs}")
con.print(f"columns: {list(hru_gdf.columns)}")

ids = hru_gdf["hru_id"]

# %% [markdown]
# ## `nhm_id` — is the derrived model fabric unique hru_id identifier.
#
# At this time, the `nhm_id` has been set with the derrived modeling fabric to the global id of the OHM. IN the geopackage, 
# columns: ['nhm_id', 'hru_id', 'model_hru_idx']: have been set to the same values, the unique OMH hru_id.

# %%
write_param_csv(ids, "nhm_id", ids)
con.print(f"[green]wrote[/] nhm_id.csv  ({ids.min()}..{ids.max()})")

# %% [markdown]
# ## `hru_segment` — downstream segment
#
# The layer carries this directly. `0` means the HRU drains out of the domain
# (to the ocean); it is stored as a float in the layer and cast to int here.

# %%
hru_segment = hru_gdf["hru_segment"].fillna(0).astype(int)
write_param_csv(hru_segment, "hru_segment", ids)
con.print(
    f"[green]wrote[/] hru_segment.csv  "
    f"({int((hru_segment == 0).sum())} HRUs drain out of domain)"
)

# %% [markdown]
# ## `hru_segment_nhm` — NHM-global-index copy of `hru_segment`
#
# `hru_segment_nhm` is the NHM-wide-index version of `hru_segment`. OHM is a
# stand-alone derived fabric with no separate national indexing, so the NHM
# index equals the local index and this is a direct copy of `hru_segment`.

# %%
write_param_csv(hru_segment, "hru_segment_nhm", ids)
con.print("[green]wrote[/] hru_segment_nhm.csv  (copy of hru_segment)")

# %% [markdown]
# ## `hru_area` — HRU area in acres
#
# The geopackage value is in km^2; PRMS wants acres.

# %%
# Check against area values used in params calculations from Rich.
# Rich's nhm_ssflux_params.csv carries hru_area in square meters; the geopackage
# areasqkm is in km^2. Compare in a common unit (m^2), require the HRUs to line up
# by hru_id, and require every HRU to agree within 0.1%. If they do, adopt Rich's
# values (converted to acres) so the two workflows share one source of truth.
rich_area_path = pl.Path(
    r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21"
    r"\param_source_files_2026_10_23\merged\nhm_ssflux_params.csv"
)
rich_df = pd.read_csv(rich_area_path).sort_values("hru_id").reset_index(drop=True)

# ids must match the geopackage HRUs exactly (both ascending by hru_id)
gpkg_ids = ids.astype(int).sort_values().reset_index(drop=True)
if not gpkg_ids.equals(rich_df["hru_id"].astype(int)):
    raise ValueError(
        "HRU id mismatch between the geopackage and Rich's nhm_ssflux_params.csv: "
        "cannot align hru_area values by hru_id."
    )

# Compare in square meters
gpkg_area_m2 = (
    hru_gdf.set_index(hru_gdf["hru_id"].astype(int))["areasqkm"].astype(float) * 1e6
).sort_index()
rich_area_m2 = rich_df.set_index(rich_df["hru_id"].astype(int))["hru_area"].astype(float)

rel_diff = (rich_area_m2 - gpkg_area_m2).abs() / gpkg_area_m2.abs()
TOL = 0.001  # 0.1%
n_bad = int((rel_diff > TOL).sum())
if n_bad:
    worst = rel_diff.sort_values(ascending=False).head(5)
    raise ValueError(
        f"{n_bad} HRU(s) differ by more than {TOL:.1%} between the geopackage area "
        f"and Rich's values. Worst relative differences (hru_id: rel_diff):\n{worst.to_string()}"
    )

con.print(
    f"[green]area check passed[/] all {len(rich_area_m2)} HRUs match within "
    f"{TOL:.1%} and are aligned by hru_id; using Rich's hru_area values "
    f"(from {rich_area_path.name})."
)

# Adopt Rich's values, converted from m^2 to acres, in hru_id order
M2_TO_ACRES = 0.000247105
hru_area_acres = pd.Series(
    rich_area_m2.values * M2_TO_ACRES, index=hru_gdf.index
)

write_param_csv(hru_area_acres, "hru_area", ids)
con.print(
    f"[green]wrote[/] hru_area.csv  "
    f"(range {hru_area_acres.min():.2f} - {hru_area_acres.max():.2f} acres)"
)


# %% [markdown]
# ## `hru_lat` / `hru_lon` — HRU centroid coordinates
#
# Centroids are computed in the projected CRS (correct planar centroid) and
# then reprojected to geographic coordinates for latitude/longitude.

# %%
centroids = hru_gdf.geometry.centroid.to_crs(4326)
hru_lat = pd.Series(centroids.y.values, index=hru_gdf.index)
hru_lon = pd.Series(centroids.x.values, index=hru_gdf.index)

write_param_csv(hru_lat, "hru_lat", ids)
write_param_csv(hru_lon, "hru_lon", ids)
con.print(
    f"[green]wrote[/] hru_lat.csv  (range {hru_lat.min():.3f} - {hru_lat.max():.3f} N)"
)
con.print(
    f"[green]wrote[/] hru_lon.csv  (range {hru_lon.min():.3f} - {hru_lon.max():.3f} E)"
)

# %% [markdown]
# ## `hru_type` — HRU classification
#
# Not carried in the fabric. Default to `1` (land HRU), the PRMS default, for
# every HRU. A later workflow can reclassify lake/inactive HRUs if needed.

# %%
hru_type = pd.Series(np.ones(len(hru_gdf), dtype=int), index=hru_gdf.index)
write_param_csv(hru_type, "hru_type", ids)
con.print(f"[green]wrote[/] hru_type.csv  (all = 1)")

# %% [markdown]
# ## Summary

# %%
con.print("\n[bold]HRU identity/geometry parameters written to:[/]")
con.print(f"  [cyan]{out_dir}[/]")
con.print(["nhm_id", "hru_segment", "hru_segment_nhm", "hru_area", "hru_lat", "hru_lon", "hru_type"])

# %% [markdown]
# ## Write a provenance log
#
# Record every parameter CSV in the output directory with its creation time and
# the source data it was derived from. The log is written next to the parameter
# CSVs as `hru_identity_params_log.csv`, and also echoed to the console.

# %%
import datetime as _dt

# Source data (file path, or a description for values not read from a file) for
# each parameter this workflow produces.
param_sources = {
    "nhm_id": str(source_gpkg) + " (layer=nhru, column=hru_id)",
    "hru_segment": str(source_gpkg) + " (layer=nhru, column=hru_segment)",
    "hru_segment_nhm": "copy of hru_segment (NHM index == local index for OHM)",
    "hru_area": str(rich_area_path) + " (column=hru_area, m^2 -> acres)",
    "hru_lat": str(source_gpkg) + " (layer=nhru, polygon centroid -> EPSG:4326)",
    "hru_lon": str(source_gpkg) + " (layer=nhru, polygon centroid -> EPSG:4326)",
    "hru_type": "constant value 1 (PRMS land-HRU default; not from a file)",
}

log_path = out_dir / "hru_identity_params_log.csv"

log_rows = []
for csv_path in sorted(out_dir.glob("*.csv")):
    if csv_path.name == log_path.name:
        continue
    param = csv_path.stem
    # Creation time on Windows is st_ctime; fall back to modified time elsewhere.
    created = _dt.datetime.fromtimestamp(csv_path.stat().st_ctime)
    log_rows.append(
        {
            "parameter": param,
            "created": created.strftime("%Y-%m-%d %H:%M:%S"),
            "source_data": param_sources.get(param, "unknown (no recorded source)"),
            "file_path": str(csv_path),
        }
    )

log_df = pd.DataFrame(log_rows, columns=["parameter", "created", "source_data", "file_path"])
log_df.to_csv(log_path, index=False)

con.print(f"\n[bold]Provenance log written to:[/] [cyan]{log_path}[/]")
con.print(log_df)
