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
source_gpkg = root_dir / "data_dependencies" / "gfv2r2" / "gfv2r2.gpkg"

out_dir = pl.Path(
    r"D:\nhm-workspace\GF2v2_conus\fabrics\gf2v2_conus\param_source_files"
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

ids = hru_gdf["nat_hru_id"]

# %% [markdown]
# ## `nhm_id` — the national HRU id
#
# `nhm_id` is simply `nat_hru_id`.

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
# ## `hru_area` — HRU area in acres
#
# The geopackage value is in km^2; PRMS wants acres.

# %%
hru_area_acres = hru_gdf["hru_area"].astype(float) * KM2_TO_ACRES
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
con.print(["nhm_id", "hru_segment", "hru_area", "hru_lat", "hru_lon", "hru_type"])
