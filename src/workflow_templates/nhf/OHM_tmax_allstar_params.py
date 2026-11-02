# %% [markdown]
# # Create tmax_allsnow and tmax_allrain_offset Parameters
#
# ## Summary
# This notebook computes the `tmax_allsnow` and `tmax_allrain_offset` parameters
# for the OHM v2 domain. These parameters define the temperature thresholds at which
# precipitation falls as all-snow or all-rain, used by PRMS/pywatershed for
# precipitation partitioning.
#
# ## Original Method (NHM v1.1)
# Developed by Parker Norton (nhm_v1.1_workflows/tmax_allstar):
# - **Source data**: ERA5 reanalysis, hourly, 0.25° (~25km) resolution
# - **Period**: 2007–2019 (13 years)
# - **Method**: Mask 2m temperature by precipitation type (snow: ptype=5, rain: ptype=1),
#   clip to physical bounds, compute mean monthly values, area-weight to HRUs
# - **Grid-to-HRU weights**: Polygon intersection of ERA5 grid cells with GFv1.1 HRUs
# - **Processing tools**: Shell scripts (CDO/NCO) + Python
#
# ## Updated Method (OHM v2)
# This notebook adapts the workflow with two key improvements:
#
# | Aspect | Original (v1.1) | Updated (v2) |
# |--------|----------------|--------------|
# | Source data | ERA5 (25km) | **HRRR (3km)** |
# | Period | 2007–2019 | **2014-09 to 2025-09** (~11 water years) |
# | Temporal resolution | Hourly | Hourly |
# | Precip type field | ERA5 `ptype` (values 0-8) | HRRR `CSNOW`/`CRAIN` (binary flags) |
# | Grid-to-HRU weights | Polygon intersection | **Point-in-polygon** (3km grid fine enough) |
# | Processing | Shell + Python | **Pure Python (xarray + Herbie)** |
# | Geospatial fabric | GFv1.1 | **OHM v2 GeoPackage** |
#
# ## Rationale for HRRR
# - ERA5's 25km resolution produces visible grid-like artifacts in the parameters
# - HRRR's 3km resolution better resolves the physiography (elevation, aspect)
#   that drives snow/rain temperature thresholds
# - HRRR covers CONUS with hourly data from 2014-present
#
# ## Workflow Steps
# 1. Download ERA5 data (for comparison baseline)
# 2. Process ERA5: mask by ptype, monthly means, grid-to-HRU weights
# 3. Download HRRR data (via standalone script `run_hrrr_download_s3.py`)
# 4. Process HRRR: load cache, compute monthly means, grid-to-HRU weights
# 5. Compare ERA5 vs HRRR vs NHM v1.1 visually
# 6. Write final parameters using HRRR-derived values
#
# ## References
# - Norton, P.A., ERA5 tmax_allstar workflow, nhm_v1.1_workflows GitLab repository
# - Regan, R.S., et al., 2025, PRMS v6.0.0, USGS Software Release, https://doi.org/10.5066/P97032NH
# - HRRR archive: NOAA/AWS Open Data, https://noaa-hrrr-bdp-pds.s3.amazonaws.com

# %%
import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
import pathlib as pl
from shapely.geometry import Polygon

import sys
import os

# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhf_assist", 1)[0] + "nhf_assist")
sys.path.append(str(root_dir))

# %% [markdown]
# ## Configuration

# %%
# === PATHS ===
v2_gpkg_path = pl.Path(r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21\GIS\model_layers.gpkg")
land_sea_mask = pl.Path(r"D:\nhm-assist\data_dependencies\nhm_v1.1_workflows-master\tmax_allstar\land_sea_mask_upk.nc")
era5_data_dir = pl.Path(r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21\ERA5_data")  # Where downloaded ERA5 files will be stored
output_dir = pl.Path(r"D:\nhm-workspace\Oregon_Recharge\fabrics\OHM_2026_02_21\param_source_files_2026_10_23\tmax_allstar_params")
output_dir.mkdir(parents=True, exist_ok=True)

# === PARAMETERS ===
start_year = 2007
end_year = 2019
grid_spacing = 0.25  # ERA5 grid spacing in degrees

hru_gdf = gpd.read_file(v2_gpkg_path, layer="nhru")
nhru = len(hru_gdf)


# %% [markdown]
# ## Write function

# %%
def write_param_csv(filepath, param_name, data):
    """Write parameter in paramdb CSV format ($id, values by month)."""
    nhru, nmonths = data.shape
    rows = []
    # Flatten in Fortran order (column-major): all HRUs for month 1, then month 2, etc.
    flat = data.ravel(order="F")
    for i, val in enumerate(flat):
        rows.append({"$id": i + 1, param_name: val})
    pd.DataFrame(rows).to_csv(filepath, index=False)
    print(f"Wrote {filepath.name}: {len(rows)} rows")

# %% [markdown]
# ## Download HRRR data
# HRRR offers a higher-resolution dataset to match the higher spatial resolution of the Hydrofabric version 2. HRRR hourly data will be downloaded for the same domain, the grid-to-HRU area weights and tmax_allsnow/tmax_allrain_offset are computed.
#
# HRRR uses `CSNOW:surface` (1=snow) and `CRAIN:surface` (1=rain) flags with `TMP:2 m above ground` (in K).
#
# Requires: `pip install herbie-data cfgrib eccodes`
# HRRR available: 2014-present (hourly, 3km CONUS)
#
#

# %%
from herbie import Herbie
from datetime import datetime
from datetime import datetime as dt

# Configuration
hrrr_start_date = "2014-10-01"
hrrr_end_date = "2025-06-30"


# %% [markdown]
# ### Step H1: Download and process HRRR hourly data for all days
# Process each day's 24 hours, mask t2m by snow/rain flags,
# accumulate monthly means across the full period.

# %%
# This cell should be uncommented if you need to download the HRRR data; note the download took ~60 hours using HERBIE
# This downloads the full CONUS HRRR grid (~1799 x 1059 at 3km) for every hour.
# from assist.nhf.make_pws_params import fetch_hrrr_ptype_data
#
# hrrr_cache_file = era5_data_dir / "hrrr_processed_cache.npz"
# hrrr_result = fetch_hrrr_ptype_data(hrrr_start_date, hrrr_end_date, hrrr_cache_file)

# %% [markdown]
# ### Steps H2–H3: Compute HRRR monthly climatology and grid-to-HRU weights
# Physical constraints used in this step were set by Parker Norton based on the PRMS literature and experience with PRMS precipitation partitioning. The gap between 274.4 and 274.65 K (0.25 K) ensures the snow and rain temperature ranges don't overlap.
#
# 271.04 K = -2.11°C (28.1°F) — coldest reasonable "all-snow" threshold
# 274.4 K = 1.25°C (34.3°F) — warmest "all-snow" threshold (just above freezing)
# 274.65 K = 1.5°C (34.7°F) — coldest "all-rain" threshold (just above the snow max)
# 276.48 K = 3.33°C (38.0°F) — warmest "all-rain" threshold

# %%
from assist.nhf.make_pws_params import process_hrrr_climatology_and_weights

hrrr_cache_file = era5_data_dir / "hrrr_processed_cache.npz"
hrrr_ymon_snow, hrrr_ymon_rain, hrrr_weights = process_hrrr_climatology_and_weights(
    hrrr_cache_file, v2_gpkg_path
)

# %% [markdown]
# ### Step H4: Apply weights — compute HRRR area-weighted tmax per HRU per month

# %%
nhru_hrrr = len(hru_gdf)

# Default fill values for HRUs with no valid observations for a given month.
# From the original v1.1 workflow (process_era5_tmax_allstar.py, nan= argument).
# - snow_nan_default: 273.15 K (0°C, 32°F) — freezing point; a physically
#   intuitive midpoint within the snow clip range [271.04, 274.4 K].
# - rain_nan_default: 274.65 K (1.5°C, 34.7°F) — the lower bound of the rain
#   clip range [274.65, 276.48 K]; most conservative "all-rain" assumption.
snow_nan_default = 273.15  # K
rain_nan_default = 274.65  # K

hrrr_allsnow = np.full((nhru_hrrr, 12), snow_nan_default)
hrrr_allrain = np.full((nhru_hrrr, 12), rain_nan_default)

hrrr_hru_groups = hrrr_weights.groupby("model_hru_idx")

for month_idx in range(12):
    snow_flat = hrrr_ymon_snow[month_idx].flatten()
    rain_flat = hrrr_ymon_rain[month_idx].flatten()

    for hru_id, group in hrrr_hru_groups:
        grid_ids = group["grid_id"].values
        wgts = group["weight"].values

        # Snow
        vals = snow_flat[grid_ids]
        valid = (vals > 0) & ~np.isnan(vals)
        if valid.sum() > 0:
            hrrr_allsnow[int(hru_id) - 1, month_idx] = np.average(vals[valid], weights=wgts[valid])

        # Rain
        vals = rain_flat[grid_ids]
        valid = (vals > 0) & ~np.isnan(vals)
        if valid.sum() > 0:
            hrrr_allrain[int(hru_id) - 1, month_idx] = np.average(vals[valid], weights=wgts[valid])

# Convert to Fahrenheit
hrrr_allsnow_f = (hrrr_allsnow - 273.15) * 1.8 + 32.0
hrrr_allrain_f = (hrrr_allrain - 273.15) * 1.8 + 32.0
hrrr_allrain_offset = hrrr_allrain_f - hrrr_allsnow_f

# Report proportion of HRUs that retained default values (no valid observations)
snow_default_frac = (hrrr_allsnow == snow_nan_default).sum() / hrrr_allsnow.size
rain_default_frac = (hrrr_allrain == rain_nan_default).sum() / hrrr_allrain.size
print(f"HRU-months using default (no obs): snow={snow_default_frac:.2%}, rain={rain_default_frac:.2%}")

print(f"HRRR tmax_allsnow range: {np.nanmin(hrrr_allsnow_f):.2f} - {np.nanmax(hrrr_allsnow_f):.2f} °F")
print(f"HRRR tmax_allrain_offset range: {np.nanmin(hrrr_allrain_offset):.2f} - {np.nanmax(hrrr_allrain_offset):.2f} °F")

# %% [markdown]
# ### Write final parameters using HRRR-derived values
# The HRRR-derived values better represent the physiography of the landscape
# compared to ERA5, which shows grid-like artifacts from the coarser resolution.
# Overwriting the ERA5 output files with HRRR results.

# %%
# Compute HRRR allrain_offset
hrrr_allrain_offset_final = hrrr_allrain_f - hrrr_allsnow_f

print("Writing HRRR-derived parameters (replacing ERA5 output):")
print(f"  tmax_allsnow range: {np.nanmin(hrrr_allsnow_f):.2f} - {np.nanmax(hrrr_allsnow_f):.2f} °F")
print(f"  tmax_allrain_offset range: {np.nanmin(hrrr_allrain_offset_final):.2f} - {np.nanmax(hrrr_allrain_offset_final):.2f} °F")

write_param_csv(output_dir / "tmax_allsnow.csv", "tmax_allsnow", hrrr_allsnow_f)
write_param_csv(output_dir / "tmax_allrain_offset.csv", "tmax_allrain_offset", hrrr_allrain_offset_final)

print(f"\nFinal parameters written to {output_dir}")
print("Source: HRRR 3km (2014-09 to 2026-09)")

# %% [markdown]
# ## Maps: verify tmax_allsnow and tmax_allrain_offset over the HRU domain
#
# One interactive map per parameter, with each of the 12 months as a layer you
# can toggle on and off, over the `hru_gdf` domain. Common basemaps (USGS Hydro
# Cached and OpenTopoMap) are included. Values are read back from the CSVs just
# written to the output directory, so the maps verify what was saved to disk.
# Each map is saved to the output directory as a standalone HTML and opened in a
# web browser (the embedded GeoJSON for the full HRU domain is large enough to
# crash the editor's inline renderer).

# %%
import folium
import webbrowser
from branca.colormap import LinearColormap

_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def make_tmax_param_map(param_name, data, hru_geoms_4326):
    """Build a folium map of a monthly (nhru x 12) parameter over the HRUs.

    The HRU geometry is embedded once; each HRU carries a precomputed fill color
    per month as a property, and a dropdown recolors the single layer by month.
    This keeps the HTML small (one geometry copy instead of twelve). ``data``
    rows align with ``hru_geoms_4326`` rows (both ordered by model_hru_idx=1..N).
    """
    gdf = hru_geoms_4326.copy().reset_index(drop=True)

    # Shared colormap across all months for comparability.
    vmin = float(np.nanmin(data))
    vmax = float(np.nanmax(data))
    cmap = LinearColormap(
        colors=["blue", "cyan", "yellow", "orange", "red"],
        vmin=vmin,
        vmax=vmax,
        caption=f"{param_name} (°F)",
    )

    # Precompute a hex color per HRU per month, plus the raw value for tooltips.
    for m in range(12):
        month = _MONTHS[m]
        vals = data[:, m]
        gdf[f"val_{month}"] = np.round(vals, 3)
        gdf[f"color_{month}"] = [
            cmap(v) if v is not None and not np.isnan(v) else "#808080" for v in vals
        ]

    bounds = gdf.total_bounds
    center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]

    fmap = folium.Map(location=center, zoom_start=7, tiles=None)

    # Base layers
    folium.TileLayer(
        tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSHydroCached/MapServer/tile/{z}/{y}/{x}",
        attr="USGS The National Map: Hydrography (NHD)",
        name="USGS Hydro Cached",
        overlay=False,
        control=True,
    ).add_to(fmap)
    folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="OpenTopoMap",
        name="OpenTopoMap",
        overlay=False,
        control=True,
        show=False,
    ).add_to(fmap)

    # Single GeoJson layer; initial style uses January's color. The dropdown
    # (below) swaps each feature's fill to the selected month's stored color.
    gj = folium.GeoJson(
        gdf.to_json(),
        name=f"{param_name} (by month)",
        style_function=lambda f: {
            "fillColor": f["properties"]["color_Jan"],
            "color": "none",
            "fillOpacity": 0.7,
            "weight": 0,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["model_hru_idx"] + [f"val_{mo}" for mo in _MONTHS],
            aliases=["HRU"] + _MONTHS,
        ),
    ).add_to(fmap)

    cmap.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)

    # Month dropdown (HTML only) placed over the map.
    options_html = "".join(f'<option value="{mo}">{mo}</option>' for mo in _MONTHS)
    control_html = f"""
    <div id="monthControl"
         style="position: fixed; top: 10px; left: 60px; z-index: 9999;
                background: white; padding: 6px 10px; border: 1px solid #999;
                border-radius: 4px; font-family: sans-serif; font-size: 14px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3);">
      <label for="monthSelect"><b>{param_name}</b> month:&nbsp;</label>
      <select id="monthSelect">{options_html}</select>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(control_html))

    # Recolor logic added to the MAP's own script scope so it runs after the map
    # and its GeoJson layer are created. We reference the map by its generated
    # name and locate the target layer by a feature property (color_Jan) rather
    # than the GeoJson variable name, which is more robust across folium versions.
    map_name = fmap.get_name()
    restyle_js = f"""
        window.addEventListener("load", function() {{
            var map = {map_name};
            function findLayer() {{
                var found = null;
                map.eachLayer(function(layer) {{
                    if (found) return;
                    if (layer.eachLayer) {{
                        layer.eachLayer(function(sub) {{
                            if (found) return;
                            if (sub.feature && sub.feature.properties
                                && "color_Jan" in sub.feature.properties) {{
                                found = layer;
                            }}
                        }});
                    }}
                }});
                return found;
            }}
            function restyle(gjLayer, month) {{
                gjLayer.eachLayer(function(l) {{
                    if (!l.feature) return;
                    l.setStyle({{
                        fillColor: l.feature.properties["color_" + month],
                        color: "none",
                        fillOpacity: 0.7,
                        weight: 0
                    }});
                }});
            }}
            var sel = document.getElementById("monthSelect");
            var gjLayer = findLayer();
            if (sel && gjLayer) {{
                sel.addEventListener("change", function() {{ restyle(gjLayer, this.value); }});
                restyle(gjLayer, sel.value);  // initial draw matches dropdown
            }}
        }});
    """
    fmap.get_root().script.add_child(folium.Element(restyle_js))

    out_html = output_dir / f"{param_name}_map.html"
    fmap.save(str(out_html))
    print(f"Saved {param_name} map to: {out_html}")
    webbrowser.open(out_html.as_uri(), new=2)
    return out_html


def read_param_csv_to_grid(filepath, param_name, nhru):
    """Read a paramdb CSV back into an (nhru x 12) array.

    ``write_param_csv`` flattens in Fortran (column-major) order — all HRUs for
    month 1, then month 2, etc. — so reshape with order="F" to recover the
    per-HRU, per-month grid. Rows then align with model_hru_idx = 1..N.
    """
    df = pd.read_csv(filepath).sort_values("$id").reset_index(drop=True)
    return df[param_name].to_numpy().reshape((nhru, 12), order="F")


# Reproject + simplify the HRU geometry once, reused for both maps. The OHM
# domain has ~16.8k HRUs; simplifying keeps the embedded GeoJSON (and the HTML)
# a manageable size for the browser.
hru_map_base = hru_gdf[["model_hru_idx", "geometry"]].to_crs(epsg=4326).copy()
hru_map_base["geometry"] = hru_map_base.geometry.simplify(0.001, preserve_topology=True)

# Read the values back from the written CSVs so the maps verify what was
# actually saved to disk, not the in-memory arrays.
allsnow_grid = read_param_csv_to_grid(
    output_dir / "tmax_allsnow.csv", "tmax_allsnow", nhru
)
allrain_offset_grid = read_param_csv_to_grid(
    output_dir / "tmax_allrain_offset.csv", "tmax_allrain_offset", nhru
)

make_tmax_param_map("tmax_allsnow", allsnow_grid, hru_map_base)
make_tmax_param_map("tmax_allrain_offset", allrain_offset_grid, hru_map_base)
