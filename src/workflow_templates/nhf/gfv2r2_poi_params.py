# %% [markdown]
# # GFv2r2 CONUS — POI (streamgage) parameters to standalone CSVs
#
# This workflow builds the point-of-interest (POI) streamgage parameters for
# the gfv2r2 CONUS fabric and writes one standalone `$id,<param>` CSV per
# parameter into the fabric `param_source_files` folder.
#
# | Parameter | Dim | Source | Notes |
# |-----------|-----|--------|-------|
# | `poi_gage_id` | npoigages | `poi_data.hl_link` | USGS station id; **string** (leading zeros matter) |
# | `poi_gage_segment` | npoigages | `poi_data.segment_id` | segment the gage sits on |
# | `poi_type` | npoigages | constant `1` | PRMS streamgage POI type |
#
# ## Which POIs
#
# The gfv2r2 geopackage `poi_data` layer holds every hydrologic location
# (HUC12 outlets, confluences, dams, terminals, ...), tagged by `hl_reference`.
# Only the rows with `hl_reference == "type_gages"` are streamgages, and for
# those rows `hl_link` is the gage id. PRMS `poi_*` parameters are dimensioned
# by `npoigages` — the gages — so this workflow keeps only the `type_gages`
# rows.
#
# A gage is dropped if its `segment_id` is not present in the fabric
# `nsegment` network (it cannot be routed), and duplicate gage ids are reduced
# to their first occurrence. The kept gages are sorted by gage id and indexed
# 1..N.
#
# This is the full-CONUS gage inventory from the fabric. Curating it for a
# specific model domain (data-availability filtering, supplemental gages) is a
# later, per-subbasin step.

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

GAGE_REFERENCE = "type_gages"

con.print(f"source_gpkg: [cyan]{source_gpkg}[/]")
con.print(f"out_dir:     [cyan]{out_dir}[/]")


# %%
def write_param_csv(series: pd.Series, param: str, ids) -> pl.Path:
    """Write ``$id,<param>`` with a 1..N index. Skips if the file exists."""
    path = out_dir / f"{param}.csv"
    if path.exists():
        con.print(f"[yellow]skip[/] {param}.csv already exists")
        return None
    df = pd.DataFrame({"$id": np.asarray(ids), param: np.asarray(series)})
    df.to_csv(path, index=False)
    return path


# %% [markdown]
# ## Load gage POIs and the segment network
#
# `hl_link` is read as a string so gage ids keep their leading zeros.

# %%
poi = gpd.read_file(source_gpkg, layer="poi_data")
poi["hl_link"] = poi["hl_link"].astype(str)
con.print(f"Loaded [green]{len(poi)}[/] POI rows")

gages = poi[poi["hl_reference"] == GAGE_REFERENCE].copy()
con.print(f"Streamgage POIs (hl_reference == {GAGE_REFERENCE!r}): {len(gages)}")

seg_gdf = gpd.read_file(source_gpkg, layer="nsegment")
seg_ids = set(seg_gdf["seg_id"].astype(int))

# %% [markdown]
# ## Filter, dedupe, and order
#
# Drop gages whose segment is not in the network, drop duplicate gage ids, and
# sort by gage id for a stable 1..N ordering.

# %%
gages["segment_id"] = gages["segment_id"].astype(int)

in_network = gages["segment_id"].isin(seg_ids)
con.print(f"Gages on a valid segment: {int(in_network.sum())} "
          f"(dropping {int((~in_network).sum())} off-network)")
gages = gages[in_network]

n_before = len(gages)
gages = gages.drop_duplicates(subset="hl_link", keep="first")
con.print(f"Unique gage ids: {len(gages)} (dropped {n_before - len(gages)} duplicates)")

gages = gages.sort_values("hl_link").reset_index(drop=True)
ids = range(1, len(gages) + 1)
con.print(f"[bold]npoigages = {len(gages)}[/]")

# %% [markdown]
# ## Write the three POI parameter files

# %%
write_param_csv(gages["hl_link"], "poi_gage_id", ids)
con.print(f"[green]wrote[/] poi_gage_id.csv  (e.g. {gages['hl_link'].iloc[0]!r})")

write_param_csv(gages["segment_id"].astype(int), "poi_gage_segment", ids)
con.print(
    f"[green]wrote[/] poi_gage_segment.csv  "
    f"(segment range {gages['segment_id'].min()} .. {gages['segment_id'].max()})"
)

write_param_csv(np.ones(len(gages), dtype=int), "poi_type", ids)
con.print(f"[green]wrote[/] poi_type.csv  (all = 1)")

# %% [markdown]
# ## Summary

# %%
con.print(f"\n[bold]{len(gages)} gage POIs[/] written to:")
con.print(f"  [cyan]{out_dir}[/]")
con.print(["poi_gage_id", "poi_gage_segment", "poi_type"])
