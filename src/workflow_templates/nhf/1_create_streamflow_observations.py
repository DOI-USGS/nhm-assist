# ---
# jupyter:
#   jupytext:
#     formats: nhf_assist/notebooks///ipynb,src/workflow_templates/nhf///py:percent
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

# %%
import sys
import os
import pathlib as pl
import warnings

warnings.filterwarnings("ignore")
from rich.console import Console

con = Console()
from rich import pretty

pretty.install()
import jupyter_black

jupyter_black.load()

import pandas as pd

# import pathlib as pl
from pyPRMS.metadata.metadata import MetaData
from pyPRMS import ParameterFile
from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

# Find and set the "nhm-assist" root directory
# Find the repo root via the editable-installed `assist` package — robust
# against sibling clones, cwd quirks, and arbitrary checkout directory names.
import assist as _assist_pkg
root_dir = pl.Path(_assist_pkg.__file__).resolve().parents[2] / "nhf_assist"

from dotenv import load_dotenv

load_dotenv(
    dotenv_path=root_dir / ".env"
)  # this will load the environment variables from the .env file


# Changed path here
from assist.nhf.sf_data_retrieval_v2_1 import (
    # create_waterdata_sf_df,
    create_waterdata_sf_df,
    create_OR_sf_df,
    create_ecy_sf_df,
    create_sf_efc_df,
)
from assist.nhf.nhm_hydrofabric_v2 import (
    create_hru_gdf,
    create_segment_gdf,
    create_poi_df,
    create_default_gages_file,
    read_gages_file,
)
from assist.nhf.efc import plot_efc
from assist.nhf.nhm_assist_utilities_v2 import (
    make_obs_plot_files,
    delete_notebook_output_files,
    load_subdomain_config,
)

config = load_subdomain_config(root_dir)


# %%
delete_notebook_output_files(
    notebook_output_dir=config["notebook_output_dir"], model_dir=config["model_dir"]
)

# %% [markdown]
# # Introduction

# %% [markdown]
# Critical in the evaluation of the NHM simulated flows is the comparison to observed flows. This notebook retrieves available streamflow observations from WaterData and two state agencies, the Oregon Water Resources Department (OWRD) and the Washington Department of Ecology (ECY), combines these data sets into one daily streamflow observations file with streamflow gage information and metadata, and writes the database out as a netCDF file (`sf_efc.nc`) to be used in Notebook "6_streamflow_output_visualization" and other notebooks in NHM-Assist. Included in the `sf_efc.nc` are Environmental Flow Components (EFC) for daily flows using a python workflow (also in this notebook) as described by [Risley and others, 2010](https://pubs.usgs.gov/sir/2010/5016/pdf/sir20105016.pdf). 
#
# This notebook also writes a default gages file (`default_gages.csv`) that includes gage information for gages in the parameter file and other WaterData gages that have data for the simulation period in the domain. A complete database of streamflow gages and observations in the model domain is necessary to evaluate the NHM and identify other gages that could be included in a model recalibration to improve the model performance.
#
# Three facts about streamflow observations and the NHM must be reviewed.
# - Streamflow observations are NOT used when running PRMS or `pywatershed`. These data are meant for comparison of simulated output only.
# - The NHM DOES use streamflow observations from WaterData in the model calibration workflow (not the streamflow file).
# - Limited streamflow gage information is stored in the parameter file.
#
# The parameter file has few parameters associated with gages (dimensioned by npoigages):
# - poi_gage_id, the agency identification number
# - poi_gage_segment, model segment identification number (nhm_seg) on which the gage falls (1 gage/segment only),
# - poi_type, historically used, but not currently used.
#
# It is important to note that the gages in the parameter file are NOT a complete set of gages in the model domain, and were NOT all used to calibrate the model.
#
# The cell below reads the NHM subdomain model hydrofabric elements for mapping HRUs and gages.

# %%
hru_gdf, hru_text = create_hru_gdf(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
)

seg_gdf, seg_txt = create_segment_gdf(
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
)

poi_df = create_poi_df(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    param_filename=config["param_filename"],
    control_file_name=config["control_file_name"],
    hru_gdf=hru_gdf,
    gages_file=config["gages_file"],
    resource_gages_file=config["resource_gages_file"],
    default_gages_file=config["default_gages_file"],
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
    seg_gdf=seg_gdf,
)

# %%
len(hru_gdf)

# %% [markdown]
# # Retrieve all WaterData gage information and streamflow observations.
# This function pulls time series data for all WaterData gages in the domain, and then filters data to the simulation period (`waterdata_gages_cache.nc`), and creates `WaterDataGages.csv`. Both the time series data file and the NWISgages.csv contain all site information for gages with a period of record greater than the user specified threshold (`waterdata_gage_nobs_min`, set in [notebook 0](./0_Workspace_setup.ipynb)) within the simulation period **AND** ALL gages in the parameter file regardless of a period of record less than the specified threshold.

# %%
waterdata_df = create_waterdata_sf_df(
    root_dir=root_dir,
    control_file_name=config["control_file_name"],
    model_dir=config["model_dir"],
    output_netcdf_filename=config["output_netcdf_filename"],
    hru_gdf=hru_gdf,
    poi_df=poi_df,
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
    seg_gdf=seg_gdf,
)

# %% [markdown]
# ## Make the default gages file (default_gages.csv)
# The `default_gages.csv` contains gages from:
#     -the parameter file (`poi_df`)
#     -any other USGS WaterData gages having streamflow data from 1980-2026 present in the domain (`waterdata_gages_cache.nc`). 
#     
# The gages in the `default_gages.csv` are represented in the variable `gages_df`. The `default_gages.csv` may be missing metadata if not found in the `resourece_gages.csv`, or the NLDI and USGS WaterData databases. If this is the case, an error will be displayed below. The gage numbers for gages missing metadata will be added to the resource_file, the file must be manually updated, and this notebook must be re-run. 
#
# Note: If the user wants to add a gage to the default gages file to be displayed in the notebooks (wihtout adding the gage to the model parameter file), the user can add the gage and its metadata and save the file as `gages.csv`. When the notebook is rerun, then the `gages_df` will me made using the `gages.csv` and NOT `default_gages.csv`.

# %%
default_gages_file = create_default_gages_file(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    control_file_name=config["control_file_name"],
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
    hru_gdf=hru_gdf,
    poi_df=poi_df,
    seg_gdf=seg_gdf,
)

# %%
gages_df, gages_txt, gages_txt_nb2 = read_gages_file(
    model_dir=config["model_dir"],
    poi_df=poi_df,
    gages_file=config["gages_file"],
)

con.print(
    f"\n{gages_txt}",
    f"\n{gages_txt_nb2}",
)

# %% [markdown]
# #  NHM subdomains within Oregon and Washington: retrieve state collected daily streamflow data
# This section was developed to integrate state collected records of streamflow for NHM subdomain models related to hydrological investigations in the states of Washington and Oregon. This section must still be run if your subdomain model lies outside those state boundaries. Ultimately future software updates will incorporate additional state databases. 
#
# Cells in this section use gages listed in the `gages_df` (created from gages listed in the `default_gages.csv`, or the updated version, `gages.csv`). This will be useful later for the user when adding gages to the subdomain model, or for model validation/calibration. Also, the `gages.csv` can be used to record gages that cannot be in the parameter file, such as the case where multiple gages cannot be associated with the same segment in the parameter file. Additional gages in the domain that cannot be in listed in the parameter file may appended to the `default_gages.csv` and therefore included in the `gages_df` and `sf_efc.nc`.
#
# The first cell below will retrieve available daily streamflow data from [Oregon Water Resources Department (OWRD)](https://apps.wrd.state.or.us/apps/sw/hydro_near_real_time/)
#
# The second cell below will retrieve available daily streamflow data from [Washington Department of Ecology (ECY)](https://waecy.maps.arcgis.com/apps/Viewer/index.html?appid=832e254169e640fba6e117780e137e7b)

# %%
owrd_df = create_OR_sf_df(
    root_dir=root_dir,
    control_file_name=config["control_file_name"],
    model_dir=config["model_dir"],
    output_netcdf_filename=config["output_netcdf_filename"],
    hru_gdf=hru_gdf,
    gages_df=gages_df,
)

# %%
ecy_df = create_ecy_sf_df(
    root_dir=root_dir,
    control_file_name=config["control_file_name"],
    model_dir=config["model_dir"],
    output_netcdf_filename=config["output_netcdf_filename"],
    hru_gdf=hru_gdf,
    gages_df=gages_df,
)

# %% [markdown]
# ## Bureau of Reclamation Hydromet — Unregulated Flow (QU)
#
# Reads the reviewed BOR QU domain file (`BOR_QU_domain_review.csv`) produced
# by the BOR mapping notebook. Stations marked `good=1` use `nearest_poi_id`,
# stations marked `good=2` use `alt_poi_id`. Composite poi_gage_id format:
# `<usgs_poi_id>-<CBTT>`, agency = `BOR-QU`.
#
# Daily QU data is read from the local cache (`data_dependencies/bor_qu_cache/individual/`)
# and integrated into `sf_efc.nc` alongside USGS/OWRD/ECY observations.

# %%
# Look for the reviewed BOR domain file
bor_review_file = (
    root_dir
    / "hydrofabric_domain_data"
    / "OHM_2026_02_21"
    / "npoigages_data"
    / "BOR_QU_domain_review.csv"
)
bor_qu_cache_dir = root_dir / "data_dependencies" / "bor_qu_cache" / "individual"
bor_qu_streamflow_df = pd.DataFrame()

if bor_review_file.exists():
    bor_review = pd.read_csv(bor_review_file)
    # Drop empty rows and filter to good > 0
    bor_review = bor_review.dropna(subset=["cbtt"])
    bor_review["good"] = (
        pd.to_numeric(bor_review["good"], errors="coerce").fillna(0).astype(int)
    )
    bor_active = bor_review[bor_review["good"] > 0].copy()

    # Determine which poi_id to use
    bor_active["use_poi_id"] = bor_active.apply(
        lambda r: (
            str(int(float(r["alt_poi_id"])))
            if r["good"] == 2 and pd.notna(r.get("alt_poi_id"))
            else str(int(float(r["nearest_poi_id"])))
        ),
        axis=1,
    )
    bor_active["poi_gage_id"] = bor_active["use_poi_id"] + "-" + bor_active["cbtt"]
    bor_active["poi_agency"] = "BOR-QU"

    print(f"BOR-QU stations to retrieve: {len(bor_active)}")
    print(bor_active[["cbtt", "poi_gage_id", "name"]].to_string(index=False))

    # Filter to child domain using HRU bounding geometry
    import geopandas as gpd

    bor_gdf = gpd.GeoDataFrame(
        bor_active,
        geometry=gpd.points_from_xy(bor_active["longitude"], bor_active["latitude"]),
        crs="EPSG:4326",
    )
    bor_gdf = bor_gdf.to_crs(hru_gdf.crs)
    bor_clipped = gpd.clip(bor_gdf, hru_gdf.dissolve())
    bor_active = bor_active[bor_active["cbtt"].isin(bor_clipped["cbtt"])].copy()

    if len(bor_active) == 0:
        print("  No BOR-QU gages intersect the child domain.")
    else:
        print(f"  BOR-QU stations in child domain: {len(bor_active)}")
        print(bor_active[["cbtt", "poi_gage_id", "name"]].to_string(index=False))

        # Parse model period for time filtering
        control = pws.Control.load_prms(
            pl.Path(config["model_dir"] / config["control_file_name"]),
            warn_unused_options=False,
        )
        start_date = pd.to_datetime(str(control.start_time))
        end_date = pd.to_datetime(str(control.end_time))

        # Read QU data from local cache
        all_bor_data = []
        for _, row in bor_active.iterrows():
            station = row["cbtt"]
            cache_file = bor_qu_cache_dir / f"{station}.csv"
            if cache_file.exists():
                df_tmp = pd.read_csv(cache_file, parse_dates=["date"])
                # Filter to model period
                df_tmp = df_tmp[
                    (df_tmp["date"] >= start_date) & (df_tmp["date"] <= end_date)
                ]
                if len(df_tmp) > 0:
                    df_tmp = df_tmp.rename(
                        columns={
                            "station": "station_nbr",
                            "date": "record_date",
                            "qu_cfs": "discharge",
                        }
                    )
                    df_tmp["station_nbr"] = station
                    all_bor_data.append(df_tmp)
                    print(f"  {station}: {len(df_tmp)} days (from cache)")
            else:
                print(f"  {station}: ⚠ No cache file found at {cache_file}")

        if all_bor_data:
            bor_raw = pd.concat(all_bor_data, ignore_index=True)
        else:
            bor_raw = pd.DataFrame(columns=["station_nbr", "record_date", "discharge"])
            print("  No BOR QU data found in cache.")

        # Reshape BOR data to match waterdata_df/owrd_df/ecy_df format
        # Expected: MultiIndex (poi_gage_id, time) with column 'discharge'
        if not bor_raw.empty:
            # Map CBTT -> composite poi_gage_id
            cbtt_to_poi = bor_active.set_index("cbtt")["poi_gage_id"].to_dict()
            bor_raw["poi_gage_id"] = bor_raw["station_nbr"].map(cbtt_to_poi)
            bor_raw = bor_raw.dropna(subset=["poi_gage_id"])

            bor_qu_streamflow_df = bor_raw.rename(columns={"record_date": "time"})[
                ["poi_gage_id", "time", "discharge"]
            ].copy()
            bor_qu_streamflow_df = bor_qu_streamflow_df.set_index(
                ["poi_gage_id", "time"]
            )

            print(
                f"\n  BOR-QU streamflow: {len(bor_qu_streamflow_df)} records, "
                f"{bor_qu_streamflow_df.index.get_level_values('poi_gage_id').nunique()} stations"
            )

        # Add BOR stations to gages_df
        bor_gages_info = bor_active[
            ["poi_gage_id", "poi_agency", "name", "latitude", "longitude"]
        ].copy()
        bor_gages_info = bor_gages_info.rename(columns={"name": "poi_name"})
        bor_gages_info["drainage_area"] = pd.NA
        bor_gages_info["drainage_area_contrib"] = pd.NA
        # gages_df is indexed by poi_gage_id (see read_gages_file); match that
        # convention so downstream xr_streamflow.sel(poi_gage_id=...) works.
        bor_gages_info = bor_gages_info.set_index("poi_gage_id")
        gages_df = pd.concat([gages_df, bor_gages_info])
        gages_df = gages_df[~gages_df.index.duplicated(keep="first")]
        print(f"  gages_df now has {len(gages_df)} entries (including BOR-QU)")

        # Persist the BOR-QU gages so downstream notebooks (e.g. notebook 2's
        # hydrofabric map) see them. read_gages_file rebuilds gages_df from the
        # gages CSV, so BOR rows must be written back or they won't appear.
        # Prefer the user-editable gages.csv if present, else default_gages.csv.
        import pathlib as _pl

        _gages_file = _pl.Path(config["gages_file"])
        _default_gages_file = _pl.Path(config["default_gages_file"])
        _target_gages_file = (
            _gages_file if _gages_file.exists() else _default_gages_file
        )

        _gages_out = pd.read_csv(_target_gages_file, dtype={"poi_gage_id": str})
        _bor_out = bor_gages_info.reset_index()[
            [
                "poi_gage_id",
                "poi_agency",
                "poi_name",
                "latitude",
                "longitude",
                "drainage_area",
                "drainage_area_contrib",
            ]
        ]
        _gages_out = pd.concat([_gages_out, _bor_out], ignore_index=True)
        _gages_out = _gages_out.drop_duplicates(subset="poi_gage_id", keep="last")
        _gages_out.to_csv(_target_gages_file, index=False)
        print(
            f"  Wrote {len(_bor_out)} BOR-QU gage(s) to {_target_gages_file.name} "
            f"({len(_gages_out)} total rows)"
        )

else:
    print("No BOR_QU_domain_review.csv found — skipping BOR Hydromet retrieval.")

# %% [markdown]
# # Create streamflow observations file with appended EFC values (sf_efc.nc)
# The following cell creates the efc classification codes for the WaterData daily streamflow data, and daily streamflow data if collected from Washington or Oregon the data as an encoded netCDf file formatted to match the `sf.nc` file created during the NHM subdomain model extraction routine.
#
# EFCs include extreme low flows (1), low flows(2), high-flow pulses(3), small floods (4; 2-year events), and large floods (5; 10-year events). 

# %%
xr_streamflow = create_sf_efc_df(
    output_netcdf_filename=config["output_netcdf_filename"],
    owrd_df=owrd_df,
    ecy_df=ecy_df,
    waterdata_df=waterdata_df,
    gages_df=gages_df,
    bor_df=bor_qu_streamflow_df,
)

# %%
xr_streamflow

# %% [markdown]
# # Check streamflow observations file: plot discharge and efc information for a selected gage.
# The cell below plots data from the `sf_efc.nc` for diagnostic purposes using the start and end dates listed in the control file.

# %%
# Find the first gage that has data in the simulation period
cpoi_id = None
for _gid in xr_streamflow.poi_gage_id.values:
    _sub = xr_streamflow.sel(poi_gage_id=_gid, time=slice(config["start_date"], config["end_date"]))
    if _sub["discharge"].notnull().any():
        cpoi_id = _gid
        break

if cpoi_id is None:
    cpoi_id = xr_streamflow.poi_gage_id.values[0]
    print(f"No gage with data found in the simulation period. Defaulting to: {cpoi_id}")
else:
    print(
        f"Daily streamflow with EFC classifications for gage: {cpoi_id}; Some gages may show no data because some gages in the parameter file have data outside the simulation period."
    )

# control = pws.Control.load_prms(
#     model_dir / control_file_name, warn_unused_options=False
# )

start_date = config[
    "start_date"
]  # pd.to_datetime(str(control.start_time)).strftime("%m/%d/%Y")
end_date = config[
    "end_date"
]  # pd.to_datetime(str(control.end_time)).strftime("%m/%d/%Y")
ds_sub = xr_streamflow.sel(poi_gage_id=cpoi_id, time=slice(start_date, end_date))
ds_sub = ds_sub.to_dataframe()
flow_col = "discharge"
if not os.environ.get("NHM_BATCH_MODE"):
    plot_efc(ds_sub, flow_col)

# %% [markdown]
# # Create daily streamflow observation plots
# #### The cell below creates plots of daily streamflow observations and saves the plots as html.txt files for all gages listed in the `gages_df`.

# %%
make_obs_plot_files(
    start_date=config["start_date"],
    end_date=config["end_date"],
    gages_df=gages_df,
    xr_streamflow=xr_streamflow,
    Folium_maps_dir=config["Folium_maps_dir"],
)

# %%
