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
import os
import glob
import pandas as pd
import xarray as xr
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

import sys
import os
import warnings


# Find and set the "nhm-assist" root directory
# Find the repo root via pixi's PIXI_PROJECT_ROOT (set by any `pixi run`), with a
# fallback to the package location — works for editable and non-editable installs.
from assist.workspace.bridge import resolve_repo_root
root_dir = resolve_repo_root() / "nhf_assist"

from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config
config = load_subdomain_config(root_dir)

# %% jupyter={"source_hidden": true}
# Old one
# base_dir = r"..\data_dependencies\stats_pois_2018"
# # pattern: all .txt files in any subfolder of base_dir
# pattern = os.path.join(base_dir, "*", "*.txt")

# dfs = []

# for path in glob.glob(pattern):
#     fname = os.path.basename(path)              # e.g. 'output_170101010303.txt'
#     huc12 = os.path.splitext(fname)[0].split("_")[-1]  # '170101010303'

#     # read txt; your example shows tab-separated with header row
#     df = pd.read_csv(path, sep="\t")            # columns like 'date','NNDAR','MCDAR','OKDAR' [file:1]
#     df["huc12"] = huc12

#     # parse date and set index for later alignment
#     df["date"] = pd.to_datetime(df["date"])     # daily timestamps like '1980-10-01' [file:1]
#     df = df.set_index(["date", "huc12"])

#     dfs.append(df)

# # concatenate over all HUC-12s
# full_df = pd.concat(dfs).sort_index()

# # convert to xarray Dataset with dimensions time and huc12
# ds = full_df.to_xarray()  # dims: time (from 'date') and huc12, variables: NNDAR, MCDAR, OKDAR, etc. [file:1]

# # optional: rename 'date' dimension to 'time' if needed
# if "date" in ds.dims:
#     ds = ds.rename({"date": "time"})

# # write NetCDF
# out_path = r"nhf_assist\data_dependencies\stats_pois_2018\streamflow_stats.nc"
# ds.to_netcdf(out_path)

# %%

BASE_DIR = r"..\data_dependencies\stats_pois_2018"
OUT_PATH = os.path.join(BASE_DIR, "streamflow_stats.nc")

def read_file(path):
    """Read a single HUC-12 text file and return a labeled DataFrame."""
    fname = os.path.basename(path)
    huc12 = os.path.splitext(fname)[0].split("_")[-1]   # e.g. '170101010303'

    df = pd.read_csv(
        path,
        sep="\t",
        parse_dates=["date"],
        index_col="date",
        dtype=np.float32,    # half memory vs float64
        engine="c",          # fastest CSV parser
    )
    df.index.name = "time"
    df["huc12"] = huc12
    df = df.set_index("huc12", append=True)   # MultiIndex: (time, huc12)
    return df

def main():
    paths = glob.glob(os.path.join(BASE_DIR, "*", "*.txt"))
    if not paths:
        raise FileNotFoundError(f"No .txt files found under {BASE_DIR}")

    print(f"Found {len(paths)} files. Reading with threads…")

    # ── Threaded read (I/O-bound — GIL released during disk reads) ─────────
    dfs = [None] * len(paths)
    with ThreadPoolExecutor() as executor:            # <-- ThreadPoolExecutor
        futures = {executor.submit(read_file, p): i for i, p in enumerate(paths)}
        with tqdm(total=len(paths), unit="file", desc="Reading") as pbar:
            for future in as_completed(futures):
                dfs[futures[future]] = future.result()
                pbar.update(1)

    # ── Vectorized concat + sort ────────────────────────────────────────────
    print("Concatenating…")
    full_df = pd.concat(dfs)
    del dfs

    full_df.sort_index(inplace=True)

    # ── Convert to xarray and write NetCDF ─────────────────────────────────
    print("Converting to xarray Dataset…")
    ds = full_df.to_xarray()

    if "date" in ds.dims:
        ds = ds.rename({"date": "time"})

    ds.attrs["description"] = "Streamflow estimates indexed by time and HUC-12"
    ds.attrs["source_dir"]  = BASE_DIR

    print(f"Writing NetCDF to {OUT_PATH}…")
    ds.to_netcdf(OUT_PATH, engine="netcdf4")
    print("Done ✓")



# %%
# main()

# %%
import xarray as xr

ds = xr.open_dataset(r"..\data_dependencies\stats_pois_2018\streamflow_stats.nc")
print(ds)  # shows dimensions, variables, and metadata


# %%
import xarray as xr
import plotly.graph_objects as go
from plotly.subplots import make_subplots

poigage_id = "14048000"
huc12_id =  "170702040308"

def make_stats_streamflow_plots(*, gage_id, huc, model_domain):

    # Data paths
    huc_nc = r"..\data_dependencies\stats_pois_2018\streamflow_stats.nc"
    gage_nc = f"..\domain_data\{model_domain}\notebook_output_files\nc_files\sf_efc.nc"
    non_ref_nc = r"..\data_dependencies\non_ref_gages\non_ref_gages_stats.nc"
    ref_nc = r"..\data_dependencies\ref_gages\ref_gages_stats.nc"
    
    # Parameters
    start_date = "1980-01-01"
    
    # --- HUC-12 dataset ---
    if huc:
        ds_huc = xr.open_dataset(huc_nc)
        ds_huc_sel = ds_huc.sel(huc12=huc, time=slice(start_date, None))
    
    # --- non_ref_gages dataset ---
    try:
        ds_stat_flow = xr.open_dataset(non_ref_nc)
        ds_stat_flow_sel = ds_stat_flow.sel(poi_id=gage_id, time=slice(start_date, None))
    except KeyError:
        print("poigage_id not present in gages II non reference gage dataset.")
    
    # --- ref_gages dataset ---
    try:         
        ds_stat_flow = xr.open_dataset(ref_nc)
        ds_stat_flow_sel = ds_stat_flow.sel(poi_id=gage_id, time=slice(start_date, None))
    except KeyError:
        print("poigage_id not present in gages II reference gage dataset.")
    
    # --- Gage dataset ---
    ds_gage = xr.open_dataset(gage_nc)
    
    # Inspect once to find the variable name if needed:
    print(ds_gage)  # run once in a notebook to see vars and coords [web:21][web:22]
    
    # Replace 'gage_q' below with the actual variable containing the gage streamflow
    var_gage = "discharge"  # e.g. 'Q', 'streamflow', etc.
    
    # Select a single gage and same time interval
    ds_gage_sel = ds_gage.sel(poi_gage_id=gage_id, time=slice(start_date, None))
    
    # Align time axes (optional but safe; this will interpolate/trim to common times if needed)
    if len(ds_stat_flow_sel) != 0:
        ds_huc_sel, ds_gage_sel, ds_stat_flow_sel  = xr.align(ds_huc_sel, ds_gage_sel, ds_stat_flow_sel, join="inner")
        gage_exist = True
    else:
        ds_huc_sel, ds_gage_sel  = xr.align(ds_huc_sel, ds_gage_sel, join="inner")
        gage_exist = False

    #Update this for occasion that the sel gage is not in either dataset

    # Daily (as-is)
    da_huc_daily = ds_huc_sel[["NNDAR", "MCDAR", "OKDAR"]]
    da_gage_daily = ds_gage_sel[var_gage]
    #stat_target_list = ["NNDAR", "MCDAR", "OKDAR"]
    stat_target_list = ["NNQPPQ", "MCQPPQ"]
    if gage_exist:
        da_stat_flow_daily = ds_stat_flow_sel[stat_target_list]
    
    
    # Monthly (mean)
    da_huc_month = ds_huc_sel.resample(time="MS").mean()
    da_gage_month = da_gage_daily.resample(time="MS").mean()
    if gage_exist:
        da_stat_flow_month = da_stat_flow_daily.resample(time="MS").mean()
        
    
    # Annual (mean)
    da_huc_annual = ds_huc_sel.resample(time="AS").mean()
    da_gage_annual = da_gage_daily.resample(time="AS").mean()
    if gage_exist:
        da_stat_flow_annual = da_stat_flow_daily.resample(time="AS").mean()
    
    # Convert to DataFrames
    df_huc_daily = da_huc_daily.to_dataframe().reset_index()
    df_huc_month = da_huc_month[["NNDAR", "MCDAR", "OKDAR"]].to_dataframe().reset_index()
    df_huc_annual = da_huc_annual[["NNDAR", "MCDAR", "OKDAR"]].to_dataframe().reset_index()
    
    df_gage_daily = da_gage_daily.to_dataframe().reset_index()
    df_gage_month = da_gage_month.to_dataframe().reset_index()
    df_gage_annual = da_gage_annual.to_dataframe().reset_index()
    
    if gage_exist:
        df_stat_flow_daily = da_stat_flow_daily.to_dataframe().reset_index()
        df_stat_flow_month =  da_stat_flow_month[stat_target_list].to_dataframe().reset_index()
        df_stat_flow_annual = da_stat_flow_annual[stat_target_list].to_dataframe().reset_index()
        
    
    # Create subplots (3 rows, shared x-axis)
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=("Annual (mean)", "Monthly (mean)", "Daily"),
    )
    
    colors = {
        "NNDAR": "steelblue",
        "MCDAR": "darkorange",
        "OKDAR": "seagreen",
        "Gage": "crimson",
        "NNQPPQ": "steelblue", 
        "MCQPPQ": "darkorange",
    }
    
    
    def add_huc_lines(df_huc, row):
        for var in ["NNDAR", "MCDAR", "OKDAR"]:
            fig.add_trace(
                go.Scatter(
                    x=df_huc["time"],
                    y=df_huc[var],
                    mode="lines",
                    name=var if row == 1 else f"{var}-r{row}",
                    line=dict(color=colors[var]),
                    showlegend=(row == 1),  # legend only on top
                ),
                row=row,
                col=1,
            )
    
    
    def add_gage_line(df_gage, row):
        fig.add_trace(
            go.Scatter(
                x=df_gage["time"],
                y=df_gage[var_gage],
                mode="lines",
                name=f"Gage {gage_id}" if row == 1 else f"Gage {gage_id}-r{row}",
                line=dict(color=colors["Gage"], dash="dash"),
                showlegend=(row == 1),
            ),
            row=row,
            col=1,
        )
    
    def add_gagesII_lines(df_gagesII, row):
        for var in stat_target_list:
            fig.add_trace(
                go.Scatter(
                    x=df_gagesII["time"],
                    y=df_gagesII[var],
                    mode="lines",
                    name=var if row == 1 else f"{var}-r{row}",
                    line=dict(color=colors[var], dash="dash" ),
                    showlegend=(row == 1),  # legend only on top
                ),
                row=row,
                col=1,
            )
    
    # Annual
    add_huc_lines(df_huc_annual, row=1)
    add_gage_line(df_gage_annual, row=1)
    if gage_exist:
        add_gagesII_lines(df_stat_flow_annual, row=1)
    
    # Monthly
    add_huc_lines(df_huc_month, row=2)
    add_gage_line(df_gage_month, row=2)
    if gage_exist:
        add_gagesII_lines(df_stat_flow_month, row=2)
    
    # Daily
    add_huc_lines(df_huc_daily, row=3)
    add_gage_line(df_gage_daily, row=3)
    if gage_exist:
        add_gagesII_lines(df_stat_flow_daily, row=3)
    
    
    # Axis labels
    fig.update_yaxes(title_text="Annual", row=1, col=1)
    fig.update_yaxes(title_text="Monthly", row=2, col=1)
    fig.update_yaxes(title_text="Daily", row=3, col=1)
    fig.update_xaxes(title_text="Time", row=3, col=1)
    
    fig.update_layout(
        title=f"Streamflow for HUC12 {huc} and gage {gage_id} (annual, monthly, daily)",
        height=900,
        legend_title_text="Series",
    )
    
    # Range slider on the shared bottom x-axis
    fig.update_xaxes(
        rangeslider_visible=True,
        rangeselector=dict(
            buttons=[
                dict(count=1, label="1y", step="year", stepmode="backward"),
                dict(count=5, label="5y", step="year", stepmode="backward"),
                dict(count=10, label="10y", step="year", stepmode="backward"),
                dict(step="all", label="All"),
            ]
        ),
        row=3,
        col=1,
    )
    
    fig.show()
    
    ds_huc.close()
    ds_gage.close()
    ds_stat_flow.close()
    
    # After constructing fig with make_subplots and fig.show()
    out_html = f"..\data_dependencies\stats_pois_2018\huc12_timescales_{huc}_{gage_id}.html"
    
    
    fig.write_html(
        out_html,
        full_html=True,
        include_plotlyjs="inline",  # bundles plotly.js inside the HTML
    )


# %%
#Update this for occasion that the sel gage is not in either dataset

# Daily (as-is)
da_huc_daily = ds_huc_sel[["NNDAR", "MCDAR", "OKDAR"]]
da_gage_daily = ds_gage_sel[var_gage]
#stat_target_list = ["NNDAR", "MCDAR", "OKDAR"]
stat_target_list = ["NNQPPQ", "MCQPPQ"]
if gage_exist:
    da_stat_flow_daily = ds_stat_flow_sel[stat_target_list]


# Monthly (mean)
da_huc_month = ds_huc_sel.resample(time="MS").mean()
da_gage_month = da_gage_daily.resample(time="MS").mean()
if gage_exist:
    da_stat_flow_month = da_stat_flow_daily.resample(time="MS").mean()
    

# Annual (mean)
da_huc_annual = ds_huc_sel.resample(time="AS").mean()
da_gage_annual = da_gage_daily.resample(time="AS").mean()
if gage_exist:
    da_stat_flow_annual = da_stat_flow_daily.resample(time="AS").mean()

# Convert to DataFrames
df_huc_daily = da_huc_daily.to_dataframe().reset_index()
df_huc_month = da_huc_month[["NNDAR", "MCDAR", "OKDAR"]].to_dataframe().reset_index()
df_huc_annual = da_huc_annual[["NNDAR", "MCDAR", "OKDAR"]].to_dataframe().reset_index()

df_gage_daily = da_gage_daily.to_dataframe().reset_index()
df_gage_month = da_gage_month.to_dataframe().reset_index()
df_gage_annual = da_gage_annual.to_dataframe().reset_index()

if gage_exist:
    df_stat_flow_daily = da_stat_flow_daily.to_dataframe().reset_index()
    df_stat_flow_month =  da_stat_flow_month[stat_target_list].to_dataframe().reset_index()
    df_stat_flow_annual = da_stat_flow_annual[stat_target_list].to_dataframe().reset_index()


# %%

# %%
# Create subplots (3 rows, shared x-axis)
fig = make_subplots(
    rows=3,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    subplot_titles=("Annual (mean)", "Monthly (mean)", "Daily"),
)

colors = {
    "NNDAR": "steelblue",
    "MCDAR": "darkorange",
    "OKDAR": "seagreen",
    "Gage": "crimson",
    "NNQPPQ": "steelblue", 
    "MCQPPQ": "darkorange",
}


def add_huc_lines(df_huc, row):
    for var in ["NNDAR", "MCDAR", "OKDAR"]:
        fig.add_trace(
            go.Scatter(
                x=df_huc["time"],
                y=df_huc[var],
                mode="lines",
                name=var if row == 1 else f"{var}-r{row}",
                line=dict(color=colors[var]),
                showlegend=(row == 1),  # legend only on top
            ),
            row=row,
            col=1,
        )


def add_gage_line(df_gage, row):
    fig.add_trace(
        go.Scatter(
            x=df_gage["time"],
            y=df_gage[var_gage],
            mode="lines",
            name=f"Gage {gage_id}" if row == 1 else f"Gage {gage_id}-r{row}",
            line=dict(color=colors["Gage"], dash="dash"),
            showlegend=(row == 1),
        ),
        row=row,
        col=1,
    )

def add_gagesII_lines(df_gagesII, row):
    for var in stat_target_list:
        fig.add_trace(
            go.Scatter(
                x=df_gagesII["time"],
                y=df_gagesII[var],
                mode="lines",
                name=var if row == 1 else f"{var}-r{row}",
                line=dict(color=colors[var], dash="dash" ),
                showlegend=(row == 1),  # legend only on top
            ),
            row=row,
            col=1,
        )

# Annual
add_huc_lines(df_huc_annual, row=1)
add_gage_line(df_gage_annual, row=1)
if gage_exist:
    add_gagesII_lines(df_stat_flow_annual, row=1)

# Monthly
add_huc_lines(df_huc_month, row=2)
add_gage_line(df_gage_month, row=2)
if gage_exist:
    add_gagesII_lines(df_stat_flow_month, row=2)

# Daily
add_huc_lines(df_huc_daily, row=3)
add_gage_line(df_gage_daily, row=3)
if gage_exist:
    add_gagesII_lines(df_stat_flow_daily, row=3)


# Axis labels
fig.update_yaxes(title_text="Annual", row=1, col=1)
fig.update_yaxes(title_text="Monthly", row=2, col=1)
fig.update_yaxes(title_text="Daily", row=3, col=1)
fig.update_xaxes(title_text="Time", row=3, col=1)

fig.update_layout(
    title=f"Streamflow for HUC12 {huc} and gage {gage_id} (annual, monthly, daily)",
    height=900,
    legend_title_text="Series",
)

# Range slider on the shared bottom x-axis
fig.update_xaxes(
    rangeslider_visible=True,
    rangeselector=dict(
        buttons=[
            dict(count=1, label="1y", step="year", stepmode="backward"),
            dict(count=5, label="5y", step="year", stepmode="backward"),
            dict(count=10, label="10y", step="year", stepmode="backward"),
            dict(step="all", label="All"),
        ]
    ),
    row=3,
    col=1,
)

fig.show()

ds_huc.close()
ds_gage.close()
ds_stat_flow.close()

# After constructing fig with make_subplots and fig.show()
out_html = f"..\data_dependencies\stats_pois_2018\huc12_timescales_{huc}_{gage_id}.html"


fig.write_html(
    out_html,
    full_html=True,
    include_plotlyjs="inline",  # bundles plotly.js inside the HTML
)

# %%

# %%
# ds.sel(huc12="170101010303")

# %%
# ds.sel(huc12="170101010303", time=slice("1990-01-01", "1995-12-31"))

# %%
# import xarray as xr
# import plotly.express as px

# nc_path = r"..\data_dependencies\stats_pois_2018\streamflow_stats.nc"

# # Parameters
# huc = "170101010303"          # target HUC-12
# start_date = "1980-01-01"     # start of plot period

# # Open dataset
# ds = xr.open_dataset(nc_path)

# # 1) Subset by HUC and time (1980 → end of record)
# ds_sel = ds.sel(huc12=huc, time=slice(start_date, None))

# # 2) Resample to monthly mean values
# ds_mon = ds_sel.resample(time="MS").mean()   # "MS" = month start [web:28][web:32]

# # 3) Convert to tidy pandas DataFrame for Plotly
# #    Resulting df has columns: ['time', 'NNDAR', 'MCDAR', 'OKDAR']
# df = ds_mon[["NNDAR", "MCDAR", "OKDAR"]].to_dataframe().reset_index()

# # 4) Melt to long format: columns ['time', 'variable', 'value']
# df_long = df.melt(id_vars="time", value_vars=["NNDAR", "MCDAR", "OKDAR"],
#                   var_name="Series", value_name="Streamflow")

# # 5) Interactive line plot
# fig = px.line(
#     df_long,
#     x="time",
#     y="Streamflow",
#     color="Series",
#     title=f"Monthly streamflow (mean) for HUC12 {huc}, {start_date}–end of record",
# )

# # Add range slider and range selector buttons on the x-axis [web:45]
# fig.update_xaxes(
#     rangeslider_visible=True,
#     rangeselector=dict(
#         buttons=list([
#             dict(count=1, label="1y", step="year", stepmode="backward"),
#             dict(count=5, label="5y", step="year", stepmode="backward"),
#             dict(count=10, label="10y", step="year", stepmode="backward"),
#             dict(step="all", label="All")
#         ])
#     )
# )

# fig.update_yaxes(title="Streamflow (monthly mean)")
# fig.update_layout(legend_title_text="Series")

# fig.show()

# ds.close()

# %%
# Get the ref gages and non ref gages data
BASE_DIR = r"..\data_dependencies\non_ref_gages"
OUT_PATH = os.path.join(BASE_DIR, "non_ref_gages_stats.nc")

def read_file(path):
    """Read a single HUC-12 text file and return a labeled DataFrame."""
    fname = os.path.basename(path)
    poi_id = os.path.splitext(fname)[0].split("_")[-1]   # e.g. '170101010303'

    df = pd.read_csv(
        path,
        sep="\t",
        parse_dates=["date"],
        index_col="date",
        dtype=np.float32,    # half memory vs float64
        engine="c",          # fastest CSV parser
    )
    df.index.name = "time"
    df["poi_id"] = poi_id
    df = df.set_index("poi_id", append=True)   # MultiIndex: (time, huc12)
    return df

def main():
    paths = glob.glob(os.path.join(BASE_DIR, "*", "*.txt"))
    if not paths:
        raise FileNotFoundError(f"No .txt files found under {BASE_DIR}")

    print(f"Found {len(paths)} files. Reading with threads…")

    # ── Threaded read (I/O-bound — GIL released during disk reads) ─────────
    dfs = [None] * len(paths)
    with ThreadPoolExecutor() as executor:            # <-- ThreadPoolExecutor
        futures = {executor.submit(read_file, p): i for i, p in enumerate(paths)}
        with tqdm(total=len(paths), unit="file", desc="Reading") as pbar:
            for future in as_completed(futures):
                dfs[futures[future]] = future.result()
                pbar.update(1)

    # ── Vectorized concat + sort ────────────────────────────────────────────
    print("Concatenating…")
    full_df = pd.concat(dfs)
    del dfs

    full_df.sort_index(inplace=True)

    # ── Convert to xarray and write NetCDF ─────────────────────────────────
    print("Converting to xarray Dataset…")
    ds = full_df.to_xarray()

    if "date" in ds.dims:
        ds = ds.rename({"date": "time"})

    ds.attrs["description"] = "Streamflow estimates indexed by time and poi_id"
    ds.attrs["source_dir"]  = BASE_DIR

    print(f"Writing NetCDF to {OUT_PATH}…")
    ds.to_netcdf(OUT_PATH, engine="netcdf4")
    print("Done ✓")


# %%
main()

# %%
import xarray as xr
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def make_stats_streamflow_plots(
    *,
    gage_id: str | None = None,
    huc: str | None = None,
    model_domain: str,
) -> None:
    """
    Generate a multi-timescale streamflow comparison plot and save it as an HTML file.

    The function plots streamflow time series at daily, monthly, and annual
    resolutions. It gracefully handles cases where ``gage_id`` or ``huc`` are
    not supplied — only the data sources that are available will be plotted.

    Parameters
    ----------
    gage_id : str or None, optional
        USGS gauge identifier (e.g. ``"14048000"``). When provided, the function
        will (1) attempt to load the corresponding simulated discharge from the
        model output NetCDF (``sf_efc.nc``) and (2) search for observed
        statistics in both the reference-gage and non-reference-gage datasets.
        If *None*, gage-based traces are skipped entirely.
    huc : str or None, optional
        12-digit HUC-12 identifier (e.g. ``"170702040308"``). When provided,
        the HUC-12 streamflow statistics (``NNDAR``, ``MCDAR``, ``OKDAR``) are
        loaded from ``streamflow_stats.nc``. If *None*, HUC-12 traces are
        skipped entirely.
    model_domain : str
        Name of the model domain sub-directory. Used to construct the path to
        the gage NetCDF file:
        ``../domain_data/{model_domain}/notebook_output_files/nc_files/sf_efc.nc``.

    Returns
    -------
    None
        The figure is displayed interactively via ``fig.show()`` and written to:
        ``../data_dependencies/stats_pois_2018/huc12_timescales_{huc}_{gage_id}.html``

    Raises
    ------
    ValueError
        If neither ``gage_id`` nor ``huc`` is supplied, because there would be
        nothing to plot.

    Notes
    -----
    * Data are filtered to start from ``1980-01-01``.
    * Monthly and annual series are derived via ``resample(...).mean()``.
    * The GagesII statistics variables used are ``NNQPPQ`` and ``MCQPPQ``.
    * When both HUC-12 and gage data are present, the time axes are aligned
      with ``xr.align(..., join="inner")`` before resampling.
    * All opened ``xr.Dataset`` objects are closed before the function returns,
      even if an error occurs.

    Examples
    --------
    Plot with both a HUC-12 and a gage:

    >>> make_stats_streamflow_plots(
    ...     gage_id="14048000",
    ...     huc="170702040308",
    ...     model_domain="my_domain",
    ... )

    Plot with only a HUC-12 (no gage data):

    >>> make_stats_streamflow_plots(
    ...     huc="170702040308",
    ...     model_domain="my_domain",
    ... )

    Plot with only a gage (no HUC-12 data):

    >>> make_stats_streamflow_plots(
    ...     gage_id="14048000",
    ...     model_domain="my_domain",
    ... )
    """
    if gage_id is None and huc is None:
        raise ValueError("At least one of 'gage_id' or 'huc' must be provided.")

    # ------------------------------------------------------------------ paths
    huc_nc = r"..\data_dependencies\stats_pois_2018\streamflow_stats.nc"
    non_ref_nc = r"..\data_dependencies\non_ref_gages\non_ref_gages_stats.nc"
    ref_nc = r"..\data_dependencies\ref_gages\ref_gages_stats.nc"

    start_date = "1980-01-01"
    var_gage = "discharge"
    stat_target_list = ["NNQPPQ", "MCQPPQ"]

    colors = {
        "NNDAR": "steelblue",
        "MCDAR": "darkorange",
        "OKDAR": "seagreen",
        "Gage": "crimson",
        "NNQPPQ": "steelblue",
        "MCQPPQ": "darkorange",
    }

    # --------------------------------------------------------- open datasets
    ds_huc = None
    ds_gage = None
    ds_stat_flow = None

    try:
        # ---- HUC-12 ----
        ds_huc_sel = None
        if huc:
            ds_huc = xr.open_dataset(huc_nc)
            ds_huc_sel = ds_huc.sel(huc12=huc, time=slice(start_date, None))

        # ---- Simulated gage discharge ----
        ds_gage_sel = None
        if gage_id:
            gage_nc = (
                rf"..\domain_data\{model_domain}"
                r"\notebook_output_files\nc_files\sf_efc.nc"
            )
            ds_gage = xr.open_dataset(gage_nc)
            ds_gage_sel = ds_gage.sel(
                poi_gage_id=gage_id, time=slice(start_date, None)
            )

        # ---- GagesII statistics (non-ref first, then ref as fallback) ----
        ds_stat_flow_sel = None
        if gage_id:
            for nc_path, label in [
                (non_ref_nc, "non-reference"),
                (ref_nc, "reference"),
            ]:
                try:
                    _ds = xr.open_dataset(nc_path)
                    _sel = _ds.sel(poi_id=gage_id, time=slice(start_date, None))
                    # Keep the first dataset that actually contains this gage.
                    ds_stat_flow = _ds
                    ds_stat_flow_sel = _sel
                    break
                except KeyError:
                    print(
                        f"gage_id '{gage_id}' not found in GagesII {label} dataset."
                    )

        gage_exist = ds_stat_flow_sel is not None and len(ds_stat_flow_sel.time) > 0

        # -------------------------------------------------- align time axes
        # Build list of datasets that are actually present, then align them.
        present_datasets = []
        if ds_huc_sel is not None:
            present_datasets.append(ds_huc_sel)
        if ds_gage_sel is not None:
            present_datasets.append(ds_gage_sel)
        if gage_exist:
            present_datasets.append(ds_stat_flow_sel)

        if len(present_datasets) > 1:
            aligned = xr.align(*present_datasets, join="inner")
            idx = 0
            if ds_huc_sel is not None:
                ds_huc_sel = aligned[idx]; idx += 1
            if ds_gage_sel is not None:
                ds_gage_sel = aligned[idx]; idx += 1
            if gage_exist:
                ds_stat_flow_sel = aligned[idx]

        # ----------------------------------------------- resample to scales
        def _resample(da, freq):
            return da.resample(time=freq).mean()

        # HUC-12
        huc_vars = ["NNDAR", "MCDAR", "OKDAR"]
        if ds_huc_sel is not None:
            da_huc_daily = ds_huc_sel[huc_vars]
            da_huc_month = _resample(da_huc_daily, "MS")
            da_huc_annual = _resample(da_huc_daily, "AS")
            df_huc_daily = da_huc_daily.to_dataframe().reset_index()
            df_huc_month = da_huc_month.to_dataframe().reset_index()
            df_huc_annual = da_huc_annual.to_dataframe().reset_index()
        else:
            df_huc_daily = df_huc_month = df_huc_annual = None

        # Gage discharge
        if ds_gage_sel is not None:
            da_gage_daily = ds_gage_sel[var_gage]
            da_gage_month = _resample(da_gage_daily, "MS")
            da_gage_annual = _resample(da_gage_daily, "AS")
            df_gage_daily = da_gage_daily.to_dataframe().reset_index()
            df_gage_month = da_gage_month.to_dataframe().reset_index()
            df_gage_annual = da_gage_annual.to_dataframe().reset_index()
        else:
            df_gage_daily = df_gage_month = df_gage_annual = None

        # GagesII statistics
        if gage_exist:
            da_stat_flow_daily = ds_stat_flow_sel[stat_target_list]
            da_stat_flow_month = _resample(da_stat_flow_daily, "MS")
            da_stat_flow_annual = _resample(da_stat_flow_daily, "AS")
            df_stat_daily = da_stat_flow_daily.to_dataframe().reset_index()
            df_stat_month = da_stat_flow_month.to_dataframe().reset_index()
            df_stat_annual = da_stat_flow_annual.to_dataframe().reset_index()
        else:
            df_stat_daily = df_stat_month = df_stat_annual = None

        # --------------------------------------------------------- build figure
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=("Annual (mean)", "Monthly (mean)", "Daily"),
        )

        def add_huc_lines(df_huc, row):
            """Add NNDAR / MCDAR / OKDAR HUC-12 traces to *row*."""
            if df_huc is None:
                return
            for var in huc_vars:
                fig.add_trace(
                    go.Scatter(
                        x=df_huc["time"],
                        y=df_huc[var],
                        mode="lines",
                        name=var if row == 1 else f"{var}-r{row}",
                        line=dict(color=colors[var]),
                        showlegend=(row == 1),
                    ),
                    row=row,
                    col=1,
                )

        def add_gage_line(df_gage, row):
            """Add the simulated gage discharge trace to *row*."""
            if df_gage is None:
                return
            fig.add_trace(
                go.Scatter(
                    x=df_gage["time"],
                    y=df_gage[var_gage],
                    mode="lines",
                    name=f"Gage {gage_id}" if row == 1 else f"Gage {gage_id}-r{row}",
                    line=dict(color=colors["Gage"], dash="dash"),
                    showlegend=(row == 1),
                ),
                row=row,
                col=1,
            )

        def add_gagesII_lines(df_gagesII, row):
            """Add GagesII NNQPPQ / MCQPPQ statistical traces to *row*."""
            if df_gagesII is None:
                return
            for var in stat_target_list:
                fig.add_trace(
                    go.Scatter(
                        x=df_gagesII["time"],
                        y=df_gagesII[var],
                        mode="lines",
                        name=var if row == 1 else f"{var}-r{row}",
                        line=dict(color=colors[var], dash="dash"),
                        showlegend=(row == 1),
                    ),
                    row=row,
                    col=1,
                )

        # Annual (row 1)
        add_huc_lines(df_huc_annual, row=1)
        add_gage_line(df_gage_annual, row=1)
        add_gagesII_lines(df_stat_annual, row=1)

        # Monthly (row 2)
        add_huc_lines(df_huc_month, row=2)
        add_gage_line(df_gage_month, row=2)
        add_gagesII_lines(df_stat_month, row=2)

        # Daily (row 3)
        add_huc_lines(df_huc_daily, row=3)
        add_gage_line(df_gage_daily, row=3)
        add_gagesII_lines(df_stat_daily, row=3)

        # -------------------------------------------------------- formatting
        fig.update_yaxes(title_text="Annual", row=1, col=1)
        fig.update_yaxes(title_text="Monthly", row=2, col=1)
        fig.update_yaxes(title_text="Daily", row=3, col=1)
        fig.update_xaxes(title_text="Time", row=3, col=1)

        title_parts = []
        if huc:
            title_parts.append(f"HUC12 {huc}")
        if gage_id:
            title_parts.append(f"gage {gage_id}")

        fig.update_layout(
            title=f"Streamflow for {' and '.join(title_parts)} (annual, monthly, daily)",
            height=900,
            legend_title_text="Series",
        )

        fig.update_xaxes(
            rangeslider_visible=True,
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(count=5, label="5y", step="year", stepmode="backward"),
                    dict(count=10, label="10y", step="year", stepmode="backward"),
                    dict(step="all", label="All"),
                ]
            ),
            row=3,
            col=1,
        )

        fig.show()

        # ---------------------------------------------------------- save HTML
        huc_tag = huc if huc else "noHUC"
        gage_tag = gage_id if gage_id else "noGage"
        out_html = (
            rf"..\data_dependencies\stats_pois_2018"
            rf"\huc12_timescales_{huc_tag}_{gage_tag}.html"
        )
        fig.write_html(
            out_html,
            full_html=True,
            include_plotlyjs="inline",
        )

    finally:
        # Always close any datasets that were opened.
        for ds in (ds_huc, ds_gage, ds_stat_flow):
            if ds is not None:
                ds.close()


# %%
make_stats_streamflow_plots(
    gage_id = "10396000",
    huc = "171200030108",
    model_domain= "Malheur_Lake"#config['subdomain'],
)

# %%
