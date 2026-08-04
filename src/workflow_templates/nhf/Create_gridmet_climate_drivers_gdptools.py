# ---
# jupyter:
#   jupytext:
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
# # NHM Oregon Climate Data Processing and Analysis
#
# This notebook demonstrates the workflow for processing, aggregating, and analyzing daily climate data for the USGS National Hydrologic Model (NHM) in Oregon, Washington, and Idaho. It covers the following steps:
#
#
# - **Spatial Data Preparation:** Extracts Hydrologic Response Unit (HRU) polygons and state boundaries for the Pacific Northwest.
# - **Climate Data Integration:** Loads and harmonizes daily meteorological datasets from PRISM, Daymet, and GridMET, including variable renaming and unit conversion.
# - **Spatial Aggregation:** Uses area-weighted averaging to aggregate gridded climate data to HRU polygons, applying robust masking based on valid weights.
# - **Visualization:** Plots HRU coverage and daily temperature maps, overlaying state boundaries for context.
# - **Statistical Analysis:** Computes annual medians and totals, and compares climate products using bias, RMSE, and correlation metrics.
#
# This workflow supports reproducible, scalable climate data analysis for hydrologic modeling and regional climate comparison.

# %%

# --- Configuration ---
import sys
import os
from pathlib import Path
import pathlib as pl

# Find the repo root
import assist as _assist_pkg
root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2]

from assist.workspace.bridge import resolve_project_notebook_context
from assist.workspace.service import get_active_model_root

project_context = resolve_project_notebook_context(cwd=os.getcwd(), env=os.environ)
if project_context:
    active_model_root = get_active_model_root(
        project_context["workspace_root"], project_context["project_root"].name
    )
    config_root = active_model_root / "config"
else:
    config_root = root_dir

from assist.nhm.nhm_assist_utilities import load_subdomain_config
config = load_subdomain_config(config_root)

# --- Derived from config (no manual edits needed) ---
GPKG_PATH = config["model_dir"] / "GIS" / "child_nhf_domain.gpkg"
GPKG_LAYER = "nhru"
START_DATE = config["start_date"]
END_DATE = config["end_date"]
VARS = ["ppt", "tmin", "tmax"]

# Output goes directly to model domain folder (where notebook 4 expects forcing files)
WORK = config["model_dir"] / "gridmet_work"
OUT = config["model_dir"]
WORK.mkdir(parents=True, exist_ok=True)

print(f"Domain: {config['model_dir'].name}")
print(f"GPKG: {GPKG_PATH}")
print(f"Period: {START_DATE} to {END_DATE}")
print(f"Output: {OUT}")

# --- Manual override (uncomment to bypass config) ---
# GPKG_PATH = Path(r"D:\path\to\model_layers.gpkg")
# START_DATE = "1979-01-01"
# END_DATE = "2024-09-30"
# OUT = Path("./gridmet_output")


# %%
import dask
import dask.distributed

# Start a local Dask cluster
cluster = dask.distributed.LocalCluster()
client = dask.distributed.Client(cluster)

# %% [markdown]
# ## Context: Climate Data Loading and Preprocessing
#
# This section loads daily climate data from PRISM, Daymet, and GridMET NetCDF files, harmonizes variable names and units, and prepares datasets for analysis. It includes:
#
#
# - Renaming variables for consistency across sources
# - Converting temperature units from Kelvin to Celsius
# - Masking HRUs based on valid spatial weights
# - Ensuring time and HRU overlap for robust comparison
#
# These steps ensure that all datasets are aligned and ready for subsequent aggregation, visualization, and statistical analysis.

# %%

# --- Imports & helpers ---
import io, zipfile, time, math
import concurrent.futures as cf
import requests
import pandas as pd
import numpy as np
import geopandas as gpd
import xarray as xr
import rioxarray  # noqa
from shapely.geometry import box
from tqdm import tqdm

# ---------------- Geo helpers ----------------
def ensure_bbox_wgs84(gdf):
    if gdf.crs is None:
        raise ValueError("GeoPackage layer has no CRS; set it before use.")
    gdf_wgs = gdf.to_crs(4326)
    minx, miny, maxx, maxy = gdf_wgs.total_bounds
    # clamp to PRISM/Daymet bounds (optional)
    return float(minx), float(miny), float(maxx), float(maxy)

#def read_bbox_from_gpkg(gpkg_path: Path, layer: str):
#gdf = gpd.read_file(gpkg_path, layer=layer)
#    return ensure_bbox_wgs84(gdf), gdf

# ---------------- Xarray helpers ----------------
def normalize_coords(ds: xr.Dataset) -> xr.Dataset:
    rename = {}
    if "latitude" in ds.coords: rename["latitude"] = "lat"
    if "longitude" in ds.coords: rename["longitude"] = "lon"
    if "y" in ds.coords and "lat" not in ds.coords: rename["y"] = "lat"
    if "x" in ds.coords and "lon" not in ds.coords: rename["x"] = "lon"
    if rename:
        ds = ds.rename(rename)
    return ds

def subset_bbox_ds(ds: xr.Dataset, bbox):
    ds = normalize_coords(ds)
    if not {"lat","lon"} <= set(ds.coords):
        raise ValueError("Dataset lacks lon/lat coords after normalization.")
    minx, miny, maxx, maxy = bbox
    lat = ds["lat"]
    lon = ds["lon"]
    lat_slice = slice(miny, maxy) if (lat[0] < lat[-1]) else slice(maxy, miny)
    lon_slice = slice(minx, maxx) if (lon[0] < lon[-1]) else slice(maxx, minx)
    return ds.sel(lat=lat_slice, lon=lon_slice)

def add_time_if_missing(ds: xr.Dataset, tstamp: np.datetime64) -> xr.Dataset:
    if "time" not in ds.coords:
        ds = ds.expand_dims(time=[tstamp])
    return ds

# ---------------- Date helpers ----------------
def date_range(start, end):
    return pd.date_range(start, end, freq="D")

# ---------------- PRISM service helpers ----------------
# Docs: https://services.nacse.org/prism/data/get/<region>/<res>/<element>/<YYYYMMDD>?format=nc
# Returns a ZIP; you must unzip the embedded .nc
PRISM_BASE = "https://services.nacse.org/prism/data/get"

def prism_url(region: str, res: str, element: str, yyyymmdd: str) -> str:
    return f"{PRISM_BASE}/{region}/{res}/{element}/{yyyymmdd}?format=nc"

def prism_download_one(out_dir: Path, element: str, date_str: str, region="us", res="4km", tries=3, sleep=2):
    out_dir.mkdir(parents=True, exist_ok=True)
    url = prism_url(region, res, element, date_str)
    # We'll write the extracted .nc as PRISM_<element>_<date>.nc
    nc_path = out_dir / f"PRISM_{element}_{date_str}.nc"
    if nc_path.exists():
        return str(nc_path)
    last_err = None
    for k in range(tries):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                # The service returns a ZIP
                with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                    nc_members = [n for n in zf.namelist() if n.lower().endswith(".nc")]
                    if not nc_members:
                        raise RuntimeError(f"No .nc member in PRISM zip for {date_str}")
                    with zf.open(nc_members[0]) as src, open(nc_path, "wb") as dst:
                        dst.write(src.read())
            return str(nc_path)
        except Exception as e:
            last_err = e
            time.sleep(sleep * (k + 1))
    raise last_err

def prism_bulk_download(var: str, dates, base_dir: Path, res="4km", max_workers=6):
    out_dir = base_dir / var
    tasks = [(out_dir, var, d.strftime("%Y%m%d"), "us", res) for d in dates]
    out_paths = []
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(prism_download_one, *t) for t in tasks]
        for fut in tqdm(cf.as_completed(futures), total=len(futures), desc=f"PRISM dl {var}"):
            out_paths.append(fut.result())
    return sorted(out_paths)

# ---------------- Daymet NCSS helpers (optional) ----------------
# Use per-year NCSS subset and save to local .nc
def infer_daymet_region(bbox):
    minx, miny, maxx, maxy = bbox
    if (minx >= -161.5 and maxx <= -154.0 and miny >= 18.0 and maxy <= 23.8):
        return "hi"
    if (minx >= -69.0 and maxx <= -63.5 and miny >= 16.5 and maxy <= 20.5):
        return "pr"
    return "na"

def assemble_prism_consolidated(bbox, dates, var_files_map: dict, out_nc: Path, compress_level=4):
    """
    Build one NetCDF with dims (time, lat, lon) and data_vars ['ppt','tmin','tmax'] from
    locally downloaded PRISM daily .nc files. Ensures numeric dtype and clears CF encodings.
    """
    import numpy as np
    import xarray as xr

    def _main_numeric_var(ds, preferred):
        # Use the preferred var if present; otherwise pick the first numeric data_var.
        if preferred in ds.data_vars:
            return preferred
        for k, v in ds.data_vars.items():
            if np.issubdtype(v.dtype, np.number):
                return k
        # Fallback: just take the first key
        return list(ds.data_vars)[0]

    dsets = {}
    template_lat = None
    template_lon = None

    for var, files in var_files_map.items():
        ds_list = []
        for f, d in zip(files, dates):
            ds = xr.open_dataset(f, decode_cf=True, mask_and_scale=True)
            ds = subset_bbox_ds(ds, bbox)
            ds = add_time_if_missing(ds, np.datetime64(d.to_datetime64()))

            data_var = _main_numeric_var(ds, var)
            da = ds[data_var]

            # Make sure this is purely numeric and free of CF encoding baggage
            da.encoding.clear()          # drop scale_factor/add_offset/etc.
            if da.dtype.kind in ("O", "S", "U"):
                # If somehow string/bytes slipped in, try to coerce to float
                da = xr.apply_ufunc(lambda x: np.nan, da)  # wipe impossible data
            da = da.astype("float32")
            da = da.rename(var)          # standardize name to expected PRISM var

            ds_clean = da.to_dataset()
            ds_list.append(ds_clean)

            if template_lat is None:
                template_lat = ds_clean["lat"]
                template_lon = ds_clean["lon"]

        # Concat this variable through time and sort
        var_ds = xr.concat(ds_list, dim="time").sortby("time")
        # Reindex to template grid (in case of any slight differences)
        var_ds = var_ds.reindex(lat=template_lat, lon=template_lon, method=None)
        dsets[var] = var_ds

    # Merge variables
    merged = xr.merge([dsets[v] for v in dsets])

    # Compression only for numeric data vars
    enc = {}
    for k, da in merged.data_vars.items():
        if np.issubdtype(da.dtype, np.number):
            enc[k] = {"zlib": True, "complevel": compress_level}  # no dtype=... to avoid casts on non-numeric

    merged.attrs.update(dict(
        title=f"PRISM {PRISM_RES} daily consolidated (bbox subset)",
        source="PRISM NACSE web service (one grid per request)",
        variables=",".join(sorted(dsets)),
        Conventions="CF-1.8",
    ))
    merged.to_netcdf(out_nc, encoding=enc)
    return out_nc



# %%
def _open_daymet_zarr(zarr_path):
    import xarray as xr
    try:
        return xr.open_zarr(zarr_path, consolidated=True)
    except Exception:
        return xr.open_zarr(zarr_path, consolidated=False)



# %%

# --- 1) Read bbox from your GeoPackage layer ---
#bbox, nhru_gdf = read_bbox_from_gpkg(GPKG_PATH, GPKG_LAYER)
#bbox, nhru_gdf.crs
nhru_gdf = gpd.read_file(GPKG_PATH, layer=GPKG_LAYER)

# %%
len(nhru_gdf)

# %% [markdown]
# ## NHM_Oregon Fabric
# The current fabric needs some work.  The cell below sorts and dissolves by ID_FIELD so there is only a single geometry for each unique ID_FIELD value.

# %%
ID_FIELD = "hru_id"
nhru_gdf = nhru_gdf.sort_values(ID_FIELD).dissolve(by=ID_FIELD, as_index=False) 


# %%
nhru_gdf.hru_id

# %%
len(nhru_gdf)

# %%
nhru_gdf.plot()

# %% [markdown]
# ### Run `gdptools` to interpolate Gridmet

# %%
from gdptools import WeightGen, AggGen, UserCatData, ClimRCatData

# %%

# --- 4) gdptools aggregation to polygons ---
# You need a unique polygon id column in your nhru layer
ID_FIELD = "hru_id"

climater_cat = "https://github.com/mikejohnson51/climateR-catalogs/releases/download/June-2024/catalog.parquet"
cat = pd.read_parquet(climater_cat)
cat.head()

_id = 'gridmet'
# Create a dictionary of climateR-catalog values for each variable
tvars = ["tmmn", "tmmx", "pr"]
cat_params = [cat.query("id == @_id & variable == @_var").to_dict(orient="records")[0] for _var in tvars]

# FYI Alternative method for specify query
# cat_params = [cat.query(f"id == '{_id}' & variable == '{_var}'").to_dict(orient="records")[0] for _var in tvars]

cat_dict = dict(zip(tvars, cat_params))

# Output an example of the cat_param.json entry for "tmmn".
# print(cat_dict.get("tmmn"))

user_data = ClimRCatData(
    cat_dict=cat_dict,
    f_feature=nhru_gdf,
    id_feature=ID_FIELD,
    period=[START_DATE, END_DATE]
)

if not (OUT / "nhru_weights_gridmet.csv").exists():
    print("Calculating weights...")
    wght_gen = WeightGen(
        user_data=user_data,
        method="serial",
        output_file=str(OUT / "nhru_weights_gridmet.csv"),
        weight_gen_crs=5070
    )

    wghts = wght_gen.calculate_weights()

if not (OUT / "nhru_GRIDMET_daily.nc").exists():
    agg = AggGen(
        user_data=user_data,
        stat_method="mean",
        agg_engine="serial",
        agg_writer="netcdf",
        weights=str(OUT / "nhru_weights_gridmet.csv"),
        out_path=str(OUT),
        file_prefix="nhru_GRIDMET_daily",
    )
    ngdf, ds_out = agg.calculate_agg()

    str(OUT), list(ds_out.data_vars)

# %%
### Postprocess for pywatershed

# %%
pws_prcp_input_file = OUT /"prcp.nc"
pws_tmin_input_file = OUT / "tmin.nc"
pws_tmax_input_file = OUT / "tmax.nc"
nhmx_input_file = OUT / "nhru_GRIDMET_daily.nc"
input_file_path_list = [pws_prcp_input_file, pws_tmin_input_file, pws_tmax_input_file]

for input_file_path in input_file_path_list:
    if not input_file_path.exists():
        #con.print(
        #    "One or more of the pywatershed input files does not exist. All input file will be rewritten from the cbh.nc file."
        #)
        with xr.open_dataset(
            nhmx_input_file
        ) as input:  # This is the input file given with NHMx
            
            model_input = input.rename({"hru_id": "nhm_id"})
 
            model_input = model_input.rename_vars({"precipitation_amount": "prcp",
                                            "daily_minimum_temperature": "tmin",
                                            "daily_maximum_temperature": "tmax"}
                                           )
            
            prcp = getattr(model_input, "prcp")
            prcp = prcp/25.4
            prcp.attrs['long_name'] = 'Daily accumulated precipitation'
            prcp.attrs['units'] = 'inch'
            prcp.attrs['grid_mapping'] = "crs"
            prcp.coords['time'].attrs['standard_name'] = "time"
            prcp.coords['time'].attrs['long_name'] = "time"
            prcp.coords['nhm_id'].attrs['long_name'] = "Global model Hydrologic Response Unit ID (HRU)"
            
            tmin = getattr(model_input, "tmin")
            tmin = (tmin- 273.15) * (9.0/5.0) + 32.0
            tmin.attrs['long_name'] = 'Minimum daily air temperature'
            tmin.attrs['units'] = 'degree_Fahrenheit'
            tmin.attrs['grid_mapping'] = "crs"
            tmin.coords['time'].attrs['standard_name'] = "time"
            tmin.coords['time'].attrs['long_name'] = "time"
            tmin.coords['nhm_id'].attrs['long_name'] = "Global model Hydrologic Response Unit ID (HRU)"
            
            tmax = getattr(model_input, "tmax")
            tmax = (tmax- 273.15) * (9.0/5.0) + 32.0
            tmax.attrs['long_name'] = 'Maximum daily air temperature'
            tmax.attrs['units'] = 'degree_Fahrenheit'
            tmax.attrs['grid_mapping'] = "crs"
            tmax.coords['time'].attrs['standard_name'] = "time"
            tmax.coords['time'].attrs['long_name'] = "time"
            tmax.coords['nhm_id'].attrs['long_name'] = "Global model Hydrologic Response Unit ID (HRU)"
            
        prcp.to_netcdf(pws_prcp_input_file)
        tmin.to_netcdf(pws_tmin_input_file)
        tmax.to_netcdf(pws_tmax_input_file)
        
        #con.print(
        #    f"The pywatershed input file [bold]{pl.Path(input_file_path).stem}[/bold] was missing. All pywatershed input files were created in {config['model_dir']} from the cbh.nc file."
        #)
    else:
        pass
#con.print(
#    f"[bold][green]Optional:[/bold][/green] To recreate pywatershed input files in {config['model_dir']}, delete [bold]prcp.nc[/bold], [bold]tmin.nc[/bold], and [bold]tmax.nc[/bold] files and re-run this notebook."
#)

# %%
tmin


# %%
prcp[0, 700].values #-273.15

# %%
