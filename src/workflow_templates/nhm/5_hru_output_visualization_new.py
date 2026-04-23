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
from ipywidgets import widgets
from IPython.display import display

from pyPRMS.metadata.metadata import MetaData
from pyPRMS import ParameterFile

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
from ipywidgets import widgets
from IPython.display import display
from nhm_helpers.map_template import make_var_map
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements
from nhm_helpers.nhm_output_visualization import retrieve_hru_output_info
from ipywidgets import VBox
from nhm_helpers.output_plots import plot_colors
from nhm_helpers.output_plots import (
    var_colors_dict,
    leg_only_dict,
    make_plot_var_for_hrus_in_poi_basin,
    oopla,
)
from nhm_helpers.nhm_assist_utilities import load_subdomain_config

config = load_subdomain_config(root_dir)
poi_id_sel = None

# %% [markdown]
# ## Introduction
# This notebook maps the selected HRU output variable's values and displays in a new browser tab. The list of output variables are user-specified (`selected_output_variables` in [notebook 0](.\0_Workspace_setup.ipynb)). A gage id can be selected and two plots created. The first plot will show a time-series of all HRU values in the selected gage's catchment. The second plot will show a time-series of all HRU output variables averaged for the selected gage's catchment. Both plots will be displayed in a new browser tab. Additionally, maps and plots produced are saved for use outside of notebooks as .html files in the `html_maps` and `html_plots` folders in the `notebook_output` folder.
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
# <font size=4> &#x270D;<font color='green'>**Enter Information:**</font> **Run the cell below. In the resulting drop-down boxes, select an HRU **output variable** and a **year** value to display in the map. You may also select a gage plots (optional). &#x270D;<font color='green'>**</font><br>
# <font size = '3'> The default is set to **recharge**, **mean_annual** with no gage selected, and the map will zoom to the model extent. If a gage number is selected here, the map will zoom to that location. Plots will also be rendered for the selected gage. If no gage is selected (default), the first gage listed in the parameter file will be used. All drop-down box selections can be changed and additional maps and plots will be created. Maps will be displayed and exported (HTML files) to `<NHM subdomain model folder>/notebook_output_files/html_maps`. Plots will be displayed and exported (HTML files) to `<NHM subdomain model folder>/notebook_output_files/html_plots`.

# %% [markdown]
# ## Interactive NHM Output Explorer
#
# This single, combined cell provides a fully interactive environment for exploring National Hydrologic Model (NHM) outputs. It includes:
#
# 1. **Average Flux Plot for Gage Catchment**  
#    - Plots average fluxes (cubic feet/sec) of **all** NHM output variables for the selected gage catchment at **annual**, **monthly**, and **daily** time steps.  
#    - Variables can be added or removed on-the-fly via the legend.  
#    - Interactive controls in the upper-right corner allow zooming, panning, and saving the figure.  
#
# 2. **Cumulative Time-Series for Selected Variable**  
#    - Displays cumulative values of the **currently selected** output variable for the chosen POI basin, also at annual, monthly, and daily resolutions.  
#    - Compares total basin flux against individual HRU contributions.  
#    - Fully interactive with save/download widgets.  
#
# 3. **Folium Map of HRU Values**  
#    - Renders an interactive map showing **annual** values of the selected variable for every HRU in the NHM subdomain.  
#    - Left-click on any HRU polygon to inspect its variable value and metadata.  
#
# **Output Files**  
# - All **plots** are saved as `.html` files in  
#   ``"./<subdomain model>/notebook_output/html_plots"``  
# - All **maps** are saved as `.html` files in  
#   ``"./<subdomain model>/notebook_output/html_maps"``  
#

# %%
# %matplotlib inline
import ipywidgets as widgets
from ipywidgets import HBox, VBox, Button
from IPython.display import display, IFrame, clear_output
import nhm_helpers.display_controls as dc

style_var = {"description_width": "initial"}
layout = widgets.Layout(width="25%")


v = widgets.Dropdown(
    options=output_var_list,
    value=output_var_list[8],
    description="Output variable:",
    layout=layout,
    style=style_var,
)

# Year selector
years = year_list.copy() + ["mean_annual"]
yr = widgets.Dropdown(
    options=years,
    value=years[-1],
    description="Time step (year):",
    layout=layout,
    style=style_var,
)

# Gage combobox
v2 = widgets.Combobox(
    options=poi_df.poi_id.tolist(),
    placeholder="(optional) Enter gage id",
    description="Zoom to gage:",
    ensure_option=True,
    disabled=False,
    layout=layout,
    style=style_var,
)


# Checkboxes for plot types
cb_map = widgets.Checkbox(value=False, description="Include Map")
cb_summary = widgets.Checkbox(value=False, description="Include Summary TS")
cb_flux = widgets.Checkbox(value=False, description="Include Flux TS")
plot_checks = HBox([cb_map, cb_summary, cb_flux])

# Generate button
btn_generate = Button(description="Show Plots", button_style="primary")

# Output areas
out_map = widgets.Output()
out_summary = widgets.Output()
out_flux = widgets.Output()

dc.v = v
dc.yr = yr
dc.v2 = v2
dc.cb_map = cb_map
dc.cb_summary = cb_summary
dc.cb_flux = cb_flux
dc.plot_checks = plot_checks
dc.btn_generate = btn_generate
dc.out_map = out_map
dc.out_summary = out_summary
dc.out_flux = out_flux
dc.root_dir = root_dir
dc.poi_df = poi_df
dc.out_dir = config["out_dir"]
dc.plot_start_date = plot_start_date
# dc.poi_id = poi_id
dc.plot_end_date = plot_end_date
dc.water_years = config["water_years"]
dc.hru_gdf = hru_gdf
dc.seg_gdf = seg_gdf
dc.html_maps_dir = config["html_maps_dir"]
dc.year_list = year_list
dc.Folium_maps_dir = config["Folium_maps_dir"]
dc.HW_basins = HW_basins
dc.subdomain = config["subdomain"]
dc.param_filename = config["param_filename"]
dc.output_var_list = output_var_list
dc.html_plots_dir = config["html_plots_dir"]
btn_generate.on_click(dc.on_generate_clicked)

display(VBox([v, yr, v2, plot_checks, btn_generate, out_map, out_summary, out_flux]))

# %%
