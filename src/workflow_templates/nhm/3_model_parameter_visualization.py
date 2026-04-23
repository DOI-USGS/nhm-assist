# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.6
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import sys
import pathlib as pl

#sys.path.append("../")

from ipywidgets import widgets
from IPython.display import display

from pyPRMS.metadata.metadata import MetaData
from pyPRMS import ParameterFile

import warnings
from rich.console import Console

# from rich import pretty
warnings.filterwarnings("ignore")
import jupyter_black

# pretty.install()
con = Console()
jupyter_black.load()

import pathlib as pl
import os
root_folder = "nhm-assist"
root_dir = pl.Path(os.getcwd().rsplit(root_folder, 1)[0] + root_folder)
sys.path.append(str(root_dir))

from nhm_helpers.nhm_hydrofabric import make_hf_map_elements
from nhm_helpers.map_template import make_par_map
from nhm_helpers.nhm_assist_utilities import make_plots_par_vals, load_subdomain_config

config = load_subdomain_config(root_dir)

# %% [markdown]
# ## Introduction
# The purpose of this notebook is create a map of HRU parameter values for a selected parameter. Parameters options are user-specified in [Notebook 0](.\0_workspace_setup.ipynb). Additionally, plots showing HRU parameter values for gage catchments are created and embedded in the parameter map. If a parameter is dimensioned by nmonth, the user must choose to visualize a specific month or the mean monthly value. Mapping HRU parameter values can quickly show spatial patterns or biases in calibrated parameter values in the subdomain. Observed variability in parameter values can be helpful in understanding variability observed in mapped model output values ([notebook 5_hru_output_visualization.ipynb](./5_hru_output_visualization.ipynb)). Maps produced are saved for use outside of notebooks as .html files in `./"subdomain model"/notebook_output/html_maps`.
#
# The cell below reads the NHM subdomain model hydrofabric elements for mapping purposes using `make_hf_map_elements()` and writes general NHM subdomain model run and hydrofabric information.

# %%
# Load domain hydrofabic elements
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

# %% [markdown]
# ## Build HRU parameter plots
# The following cell creates HTML plots for all parameters listed in notebook [0_workspace_setup.ipynb](./0_workspace_setup.ipynb) for all HRUs in gage catchments. Plots are saved as .txt files in `.\"subdomain folder"\notebook_output\Folium_maps`. These files (plots) are embedded in the interactive parameter map created below for each gage, see "Make interactive map of selected parameter values in the NHM subdomain".

# %%
make_plots_par_vals(
    poi_df=poi_df,
    hru_gdf=hru_gdf,
    param_filename=config["param_filename"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
    Folium_maps_dir=config["Folium_maps_dir"],
)

# %% [markdown]
# ## Select a parameter to display
# <font size=4>&#x270D;<font color='green'>**Enter Information:**</font> **Run the cell below. In the resulting drop-down box, select a parameter**.

# %%
cal_hru_params = config["nhru_params"] + config["nhru_nmonths_params"]
par_sel = cal_hru_params[4]
# sel_flag = False

v = widgets.Dropdown(
    options=cal_hru_params,
    value=par_sel,
    description="Select a parameter to view in plots:",
)


def on_change(change):
    global par_sel, sel_flag
    if change["type"] == "change" and change["name"] == "value":
        par_sel = v.value
        # sel_flag = True


v.observe(on_change)
display(v)

# %% [markdown]
# &#x1F6D1;Once a parameter is selected above, <font color='green'>**select this cell**</font>, then go to the Jupyter toolbar and select <font color='green'>**Run > Run Selected Cell and All Below**</font>.

# %% [markdown]
# <!-- &#x270D;<font color='green'>**Enter Information:**</font> **Run the cell below.** <br> If a dropdown box is displayed, the selected parameter (above) is dimensioned by month. Select a month from the dropdown box to display. Default selection is "July". -->

# %%
prms_meta = MetaData().metadata
pdb = ParameterFile(config["param_filename"], metadata=prms_meta, verbose=False)

mo_num_dict = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}

mo_names = list(mo_num_dict.keys())

mo_name = "July"  # set default value
mo_sel = mo_num_dict[mo_name]

try:
    pdb.get(par_sel).dimensions["nmonths"].size

except KeyError:
    con.print(f"{par_sel} dimensioned by HRU only.", style="bold green")
    mo_sel = None

else:
    con.print(
        f"The selected parameter {par_sel} (above) is dimensioned by month. Select a month to display from the dropdown box (below). Once a selection is made, select the cell below. Then go to the Jupyter toolbar and select [bold][green]Run > Run Selected Cell and All Below[/bold][/green]. Default month is July.",
    )

    m = widgets.Dropdown(
        options=mo_names,
        value=mo_names[6],  # set default value
        description="Select a month to display on the map:",
    )

    def on_change(change):
        global mo_sel, mo_name, mo_num_dict
        if change["type"] == "change" and change["name"] == "value":
            mo_name = m.value
            mo_sel = mo_num_dict[mo_name]

    m.observe(on_change)

    display(m)

# %% [markdown]
# ## Make interactive map for the selected parameter
# The following cell creates a map that displays the selected parameter's values for HRUs in the NHM subdomain model. Additionally, plots of HRU values for gage catchments are embedded in the map, and are viewed by left-clicking on a gage icon. Discrete parameter values for each HRU and additional HRU information can be viewed by left-clicking on HRUs. Maps produced are saved for use outside of notebooks as .html files in `./"subdomain model"/notebook_output/html_maps`.

# %%
map_file = make_par_map(
    root_dir=root_dir,
    hru_gdf=hru_gdf,
    HW_basins=HW_basins,
    poi_df=poi_df,
    par_sel=par_sel,
    mo_sel=mo_sel,
    mo_name=mo_name,
    nhru_params=config["nhru_params"],
    Folium_maps_dir=config["Folium_maps_dir"],
    seg_gdf=seg_gdf,
    html_maps_dir=config["html_maps_dir"],
    param_filename=config["param_filename"],
    subdomain=config["subdomain"],
)

# %%
