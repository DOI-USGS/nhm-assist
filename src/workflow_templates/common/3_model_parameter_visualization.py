# %%
import sys

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

import os
# One template set serves every workflow, so the root cannot be hardcoded the
# way the per-workflow copies did (`resolve_repo_root() / "nhf_assist"`). The
# workflow is inferred from where this notebook runs: nhm and pest use the repo
# root, nhf uses <repo>/nhf_assist. Built on resolve_repo_root, so it honours
# PIXI_PROJECT_ROOT and works for non-editable installs too.
from assist.workspace.bridge import resolve_workflow_root
root_dir = resolve_workflow_root(cwd=os.getcwd())

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

from assist.common.hydrofabric import make_hf_map_elements
from assist.common.map_template import make_par_map
from assist.common.assist_utilities import make_plots_par_vals, load_subdomain_config

config = load_subdomain_config(config_root)

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
    waterdata_gages_file=config["waterdata_gages_file"],
    gages_file=config["gages_file"],
    resource_gages_file=config["resource_gages_file"],
    default_gages_file=config["default_gages_file"],
    nhru_params=config["nhru_params"],
    nhru_nmonths_params=config["nhru_nmonths_params"],
    waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
    fabric_version=config["fabric_version"],
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
# ## Make interactive map for the selected parameter
# <font size=4>&#x270D;<font color='green'>**Enter Information:**</font> **Run the cell below. Select a parameter (and a month, if the parameter is dimensioned by month), then click Generate Map.**</font><br>
# <font size=3>The month drop-down box is only active for parameters dimensioned by month; the default month is July. The map displays the selected parameter's values for HRUs in the NHM subdomain model. Plots of HRU values for gage catchments are embedded in the map, and are viewed by left-clicking on a gage icon. Discrete parameter values for each HRU and additional HRU information can be viewed by left-clicking on HRUs. The selections can be changed and additional maps created. Maps are saved for use outside of notebooks as .html files in `./"subdomain model"/notebook_output/html_maps`.

# %%
import calendar
import assist.common.display_controls as dc

prms_meta = MetaData().metadata
pdb = ParameterFile(config["param_filename"], metadata=prms_meta, verbose=False)

cal_hru_params = config["nhru_params"] + config["nhru_nmonths_params"]
style = {"description_width": "initial"}

par_dd = widgets.Dropdown(
    options=cal_hru_params,
    value=cal_hru_params[4],
    description="Select a parameter:",
    style=style,
    layout=widgets.Layout(width="400px"),
)

mo_dd = widgets.Dropdown(
    options=list(calendar.month_name[1:]),
    value="July",
    description="Select a month (monthly parameters only):",
    style=style,
    layout=widgets.Layout(width="400px"),
)


def is_monthly(par):
    try:
        pdb.get(par).dimensions["nmonths"].size
    except KeyError:
        return False
    return True


def update_month_dd(change=None):
    mo_dd.disabled = not is_monthly(par_dd.value)


par_dd.observe(update_month_dd, names="value")
update_month_dd()

btn_map = widgets.Button(
    description="Generate Map",
    button_style="primary",
)

dc.root_dir = root_dir
dc.hru_gdf = hru_gdf
dc.HW_basins = HW_basins
dc.poi_df = poi_df
dc.seg_gdf = seg_gdf
dc.nhru_params = config["nhru_params"]
dc.Folium_maps_dir = config["Folium_maps_dir"]
dc.html_maps_dir = config["html_maps_dir"]
dc.param_filename = config["param_filename"]
dc.subdomain = config["subdomain"]
dc.par_dd = par_dd
dc.mo_dd = mo_dd

par_map_out = widgets.Output()
dc.par_map_out = par_map_out
btn_map.on_click(dc.on_par_map_clicked)
display(widgets.VBox([par_dd, mo_dd, btn_map, par_map_out]))

# %%
