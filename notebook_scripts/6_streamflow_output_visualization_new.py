# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.17.0
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
# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))

# %%
from nhm_helpers.output_plots import create_streamflow_plot
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements
from nhm_helpers.map_template import make_streamflow_map
from nhm_helpers.nhm_output_visualization import retrieve_hru_output_info
from ipywidgets import widgets
from IPython.display import display

from nhm_helpers.nhm_assist_utilities import load_subdomain_config

config = load_subdomain_config(root_dir)

poi_id_sel = None
crs = 4326

# %% [markdown]
# ## Introduction
# The purpose of this notebook is to assist in the evaluation of NHM subdomain model simulated streamflow. First, the notebook creates a map of gage locations color coded by Kling-Gupta efficiency (KGE; [2009](https://www.sciencedirect.com/science/article/abs/pii/S0022169409004843)) value. Gage locations are overlays in a map of NHM headwater basins (HWs) that are color coded to calibration type: yellow indicates HWs calibrated with statistical streamflow targets at the HW outlet; green indicates HWs that were further calibrated with streamflow observations at selected gage locations.
# Next, a gage may be selected and a plot created that shows a time-series of simulated and observed streamflow at daily, monthly, and annual time steps. A flow exceedance curve and table of summary statistics is also provided in the plot for streamflow evaluation purposes. Additionally, maps and plots produced are saved for use outside of notebooks as HTML files in the `html_maps` and `html_plots` folders in the `notebook_output` folder.
#
# The cell below reads the NHM subdomain model hydrofabric elements for mapping purposes using `make_hf_map_elements()`, retrieves `pywatershed` output file information for mapping and plotting using `retrieve_hru_output_info()`, and writes general NHM subdomain model run and hydrofabric information.

# %%
(
    hru_gdf,
    hru_txt,
    hru_cal_level_txt,
    seg_gdf,
    seg_txt,
    nwis_gages_aoi,
    poi_df,
    gages_df,
    gages_txt,
    gages_txt_nb2,
    HW_basins_gdf,
    HW_basins,
) = make_hf_map_elements(
    root_dir=root_dir,
    model_dir=config["model_dir"],
    GIS_format=config["GIS_format"],
    param_filename=config["param_filename"],
    control_file_name=config["control_file_name"],
    nwis_gages_file=config["nwis_gages_file"],
    gages_file=config["gages_file"],
    default_gages_file=config["default_gages_file"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
    nwis_gage_nobs_min=config["nwis_gage_nobs_min"],
)
con.print(
    f"{config['workspace_txt']}\n",
    f"\n{gages_txt}{seg_txt}{hru_txt}",
    f"\n     {hru_cal_level_txt}\n",
    f"\n{gages_txt_nb2}",
)

# Retrieve pywatershed output file information for mapping and plotting
plot_start_date, plot_end_date, year_list, output_var_list = retrieve_hru_output_info(
    out_dir=config["out_dir"],
    water_years=config["water_years"],
)

# %% [markdown]
# ## Create an interactive map to evaluate streamflow at gages (pois)
# The following cell creates a map of the NHM subdomain model hydrofabric elements and displays monthly Kling-Gupta efficiency (KGE) values for parameter file gages as red (KGE<0.5), yellow (0.5<=KGE<0.7), and green (KGE>=0.7). The map is interactive, made with [folium](https://python-visualization.github.io/folium/v0.18.0/index.html) (see [README](./README.md) for basic map interactive functionality). Use the mouse to left-click on gage icons and display the gage id and gage name. Use the mouse to left-click on HRUs to display the headwater basin (HW) id. HW groupings of HRUs are important when interpreting parameter values and output variables. HRU parameters were grouped by HW and adjusted using a scaling factor during the byHW and byHWobs parts of NHM calibration ([Hay and others, 2023](https://pubs.usgs.gov/tm/06/b10/tm6b10.pdf)). During the byHW calibration part, statistical flow targets at HW outlets were used, and during the subsequent byHWobs part, streamflow obervations were used for selected HWs.

# %%
map_file = make_streamflow_map(
    root_dir=root_dir,
    out_dir=config["out_dir"],
    plot_start_date=plot_start_date,
    plot_end_date=plot_end_date,
    water_years=config["water_years"],
    hru_gdf=hru_gdf,
    poi_df=poi_df,
    poi_id_sel=poi_id_sel,
    seg_gdf=seg_gdf,
    html_maps_dir=config["html_maps_dir"],
    subdomain=config["subdomain"],
    HW_basins_gdf=HW_basins_gdf,
    HW_basins=HW_basins,
    output_netcdf_filename=config["output_netcdf_filename"],
)

# %% [markdown]
# ## Make an interactive plot of simulated and observed streamflow and table of streamflow statistics for selected gage
# This plot is interactive, and made with [plotly](https://plotly.com/) (see [README](./README.md) for basic plot interactive functionality), and shows subplots of simulated and observed streamflow at daily, monthly, and annual timesteps for the selected gage. Note: the date that appears in popup window when hovering over plotted data reflects the last day of the timestep displayed in the plot. A flow exceedance curve and table of summary statistics is also provided in the plot for streamflow evaluation purposes. 

# %% [markdown]
# ## Select a gage to evaluate simulated and observed streamflow time-series and streamflow statistics
# <font size=4> &#x270D;<font color='green'>**Enter Information:**</font> **Run the cell below. In the resulting drop-down box, select a gage. A plot will be created to evaluate observed and simulated streamflow at the selected gage.** </font><br>
# <font size=3> If no gage is selected (default), the first gage listed in the parameter file will be used. The drop-down box selection can be changed and additional plots will be displayed and exported (html files) to<br> `<NHM subdomain model folder>/notebook_output_files/html_plots`.

# %%
# %matplotlib inline
import ipywidgets as widgets
from IPython.display import display, clear_output, IFrame
import nhm_helpers.display_controls as dc

gage_txt = widgets.Text(
    description="Streamgage ID:",
    placeholder="(optional) Enter gage id",
    layout=widgets.Layout(width="40%"),
    style={"description_width": "initial"},
)

btn_plot = widgets.Button(
    description="Generate Plot",
    button_style="primary",
)

btn_map = widgets.Button(
    description="Generate Map",
    button_style="primary",
)

dc.root_dir = root_dir
dc.gage_txt = gage_txt
dc.btn_plot = btn_plot
dc.btn_map = btn_map
dc.plot_start_date = plot_start_date
dc.plot_end_date = plot_end_date
dc.water_years = config["water_years"]
dc.html_plots_dir = config["html_plots_dir"]
dc.subdomain = config["subdomain"]
dc.output_netcdf_filename = config["output_netcdf_filename"]
dc.out_dir = config["out_dir"]
dc.hru_gdf = hru_gdf
dc.seg_gdf = seg_gdf
dc.poi_df = poi_df
dc.html_maps_dir = config["html_maps_dir"]
dc.HW_basins_gdf = HW_basins_gdf
dc.HW_basins = HW_basins


controls = widgets.HBox([gage_txt, btn_plot, btn_map])

plot_out = widgets.Output()
map_out = widgets.Output()
dc.plot_out = plot_out
dc.map_out = map_out
btn_plot.on_click(dc.on_plot_clicked)
btn_map.on_click(dc.on_map_clicked)
display(widgets.VBox([controls, plot_out, map_out]))

# %%

# %%
