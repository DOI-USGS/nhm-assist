# %%
# Environment sanity check -- run first, and read it if it prints anything.
#
# Python adds a per-user package directory (~/.local/lib/pythonX.Y/site-packages
# on macOS and Linux, %APPDATA%\Python\PythonXY\site-packages on Windows) to
# sys.path AHEAD of this environment's own packages. It is keyed by Python
# version, not by project, so a `pip install --user` run from any other project
# silently overrides the versions this project locked -- with no signal from
# pixi, from pixi.lock, or from `pixi list`.
#
# nhm-assist does not register a Jupyter kernel or pin one in notebook metadata:
# choosing an environment is yours to do in your IDE. This check is what tells
# you when that choice has been quietly undermined.
try:
    import site
    import sys
    import sysconfig
    from pathlib import Path

    def _top_level_names(directory):
        skip_suffixes = (".dist-info", ".egg-info", ".pth")
        return {
            entry.name.split(".")[0] if entry.is_file() else entry.name
            for entry in directory.iterdir()
            if not entry.name.startswith("_")
            and not entry.name.endswith(skip_suffixes)
        }

    _user_site = Path(site.getusersitepackages()) if site.ENABLE_USER_SITE else None
    _env_site = Path(sysconfig.get_paths()["purelib"])
    _paths = [str(Path(p)) for p in sys.path]

    if (
        _user_site is not None
        and _user_site.is_dir()
        and str(_user_site) in _paths
        and _paths.index(str(_user_site)) < _paths.index(str(_env_site))
    ):
        _shadowed = sorted(_top_level_names(_user_site) & _top_level_names(_env_site))
        if _shadowed:
            print("=" * 72)
            print("WARNING: packages outside this environment are overriding it.")
            print("")
            print(f"  shadowing:  {_user_site}")
            print(f"  shadowed:   {_env_site}")
            print(f"  {len(_shadowed)} package(s): {', '.join(_shadowed)}")
            print("")
            print("Versions you see may not be the versions pixi.lock specifies,")
            print("and `pixi list` will not show this because it reads the lock")
            print("file rather than sys.path.")
            print("")
            print("To fix, either launch Jupyter through pixi, or set")
            print("PYTHONNOUSERSITE to 1 in your IDE's kernel environment.")
            print("Check any one package with:")
            print("    import pandas; print(pandas.__version__, pandas.__file__)")
            print("=" * 72)
except Exception as _exc:  # never let a sanity check break the notebook
    print(f"(environment sanity check skipped: {_exc})")


# %%
import warnings
import pandas as pd
from pyPRMS.metadata.metadata import MetaData
from pyPRMS import ParameterFile
from contextlib import redirect_stdout
import io
f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws
from rich.console import Console
from rich import pretty
warnings.filterwarnings("ignore")
#import jupyter_black
pretty.install()
con = Console()
#jupyter_black.load()

import sys
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
    active_model_root = None
    config_root = root_dir
print(root_dir)
#pppo


# %% [markdown]
# ## Introduction
# The purpose of this notebook is to setup paths and directories for all nhm-assist notebooks using a provided or requested National Hydrologic Model (NHM) subdomain model (`model_dir`) **Note: all nhm-assist output files, maps, and plots are saved to the subdomain model folder.**
# A sample NHM subdomain model is provided in the nhm-assist `domain_data` folder for the Walla Walla subdomain.

# %% [markdown]
# ### A National Hydrologic Model (NHM) subdomain model
# A NHM subdomain model is extracted from the NHM domain (CONUS) using an automated workflow that generates a complete set of Precipitation Runoff Modeling System (PRMS) input files containing the data and parameters required for a NHM-PRMS model [Regan and others, 2018](https://pubs.usgs.gov/publication/tm6B9). A subdomain model includes everything the nhm-assist notebooks need — the geospatial fabric, GIS layers, parameter file, and control file — ready to run.

# %% [markdown]
# ### How to get a watershed model
# You need one complete NHM subdomain model to run these notebooks. There are three ways to acquire one:
#
# 1. **Use a ready-to-run example.** Two complete models are available and need no edits to their fabric or parameter files:
#    - **Walla_Walla** — bundled in the repository's `domain_data` folder; it is the default example these notebooks point at, with nothing to download.
#    - **willamette_river** — a larger example on the USGS [HyTEST](https://hytest-org.github.io/hytest/doc/About.html) OSN storage pod. From a miniforge prompt, `cd` to the cloned **nhm-assist** repository folder and run `python pull_domain.py --name=willamette_river`. This downloads the complete model into `domain_data/willamette_river`.
#
# 2. **Build your own from a shapefile.** To model your own area of interest, construct a complete model from the Geospatial Fabric v1.1: delineate the watershed fabric and GIS layers from your AOI shapefile with `nhf/Create_subbasin_model_NHM_v1`, build the parameter file from the v1.1 parameter geodatabase with `nhf/gf_params_parse_v1_1`, and generate the `prcp.nc`/`tmin.nc`/`tmax.nc` climate drivers with `nhf/Create_gridmet_climate_drivers`. The full step-by-step guide, `Building_a_Watershed_Model_from_GFv1.1.md`, is in the root of the nhm-assist repository.
#
# 3. **Request a new subdomain.** If you need a model for an area that is not one of the examples and you do not want to build it yourself, email pnorton@usgs.gov with one or more national model segments (nhm_seg) at your watershed outlet(s) — identified using GFv1.1.gdb — your name/email/organization, and a short summary of your application that **specifies using `pywatershed`**. Once received, unzip and place the model folder in the nhm-assist `domain_data` folder.

# %% [markdown]
# ## Workspace Setup
# These notebooks run from a **workspace project**. A workspace is a folder outside the cloned repository, created with `pixi run setup`, that holds one or more projects; each project holds its generated notebooks and one or more models, with one marked **active**. This notebook resolves its paths from the active model automatically — you do not set `model_dir` by hand. **All nhm-assist output files, maps, and plots are written under the active model's runtime folder** (`<workspace>/<project>/models/<model>/`), not back into the repository.
#
# ### Two locations supply the inputs these notebooks read:
#
# 1. The repository's **data_dependencies** folder — shared supporting files used by all projects:
#     - **[HUC2](https://www.sciencebase.gov/catalog/item/6407a507d34e76f5f75e39ec)**
#     - **NHM-V1_1*** not included in the NHM v1.1 data release [(Markstrom and others, 2024).](https://www.sciencebase.gov/catalog/item/626c0d67d34e76103cd2ce4a)
#
# 2. The active **model** folder in your project (`<workspace>/<project>/models/<model>/`), which holds the subdomain model:
#     - **control.default.bandit** (a control file)
#     - **myparam.param** (a parameter file)
#     - **sf_data.nc** (an optional streamflow observations file not used by nhm-assist)
#     - **cbh.nc** (an input data file)
#     - **GIS** folder containing
#         - **model_nhru.shp**
#         - **model_nsegment.shp**
#         - **model_npoigages.shp**
#         - and/or **model_layers.gpkg**
#
# >Note: These file names are detected or defaulted below; override the matching **Enter Information** cell only if your model uses different names.

# %% [markdown]
# ### nhm-assist creates additional files and folders under the active model folder. These include:
#
# - **default_gages.csv**
# - **NWISgages.csv**
#  - **tmin.nc**
# - **tmax.nc**
# - **prcp.nc**
# - **output** folder (model output)
# - **notebook_output_files** folder containing:
#     - **Folium_maps** folder
#     - **html_maps** folder
#     - **html_plots** folder
#     - **nc_files** folder
#
# **Note:** If subfolders do not exist, they will be created when needed.
#

# %% [markdown]
# ## **User Provided Information**
# <font size=4>The user must provide and/or review information in the cells following <font color='green'>&#x270D;**Enter Information:**</font> prompts. 

# %% [markdown]
# ### &#x270D; Enter Information: NHM model name (`subdomain`)
# **In the workspace workflow you do not need to edit this.** When this notebook runs inside a workspace project, `subdomain` is automatically overwritten with the project's **active model** name — the model you selected with `pixi run project-set-active-model` (or option 7 of `pixi run setup`). The notebook prints `Active model:` and `Runtime output:` below so you can confirm which model it resolved. The value typed in the next cell is used **only** in the legacy in-repo layout (no workspace project), where it names the model folder under `nhm-assist/domain_data/`.

# %%
subdomain = "Walla_Walla"

from assist.workspace.service import resolve_nhm_runtime_paths

# resolve_nhm_runtime_paths always reports the *repo* root, so trusting it
# outside workspace mode would point nhf's and pest's notebooks at the nhm
# workspace's config and model directory. Only consult it when a workspace
# project actually exists; otherwise derive everything from this workflow's
# own root, which reproduces the previous per-workflow behaviour exactly.
if project_context:
    runtime_paths = resolve_nhm_runtime_paths(
        subdomain,
        cwd=os.getcwd(),
        env=os.environ,
    )
    active_model_name = runtime_paths.get("active_model_name")
    if active_model_name:
        subdomain = active_model_name
    config_root = runtime_paths["config_root"]
    workspace_root = runtime_paths["workspace_root"]
    project_dir = runtime_paths["project_dir"]
    model_root = runtime_paths["model_root"]
    model_dir = runtime_paths["model_dir"]
else:
    active_model_name = None
    config_root = root_dir
    workspace_root = None
    project_dir = None
    model_root = None
    model_dir = root_dir / "domain_data" / subdomain
# Report the resolved workspace setup so you can confirm you are working in the
# project/model you intend (mirrors `pixi run setup` -> option 9).
con.print("")
con.print("[bold]Current setup[/bold]")
if project_context:
    con.print(f"  Workspace root: {workspace_root}")
    con.print(f"  Project:        {project_dir.name}")
    con.print(f"  Active model:   {active_model_name}")
    con.print(f"  Runtime output: {model_dir}")
else:
    con.print("  [yellow]Legacy in-repo mode (no workspace project detected).[/yellow]")
    con.print(f"  subdomain:      {subdomain}")
    con.print(f"  model_dir:      {model_dir}")

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **GIS file format**. </font><br>
# <font size = '3'>The default format is a geopackage (**.gpkg**) but other formats such as ESRI shape file (**.shp**) may have been provided.

# %%
# Detected from the model rather than assumed: most NHM subdomains ship a
# geopackage, but some (e.g. the v1.1 byHWobs Maine subdomain) ship only
# shapefiles, and the hydrofabric readers have a .shp branch that a hardcoded
# ".gpkg" never selects. Override on the next line if the detection is wrong.
if (model_dir / "GIS" / "model_layers.gpkg").exists():
    GIS_format = ".gpkg"
elif list((model_dir / "GIS").glob("model_nhru.shp")):
    GIS_format = ".shp"
else:
    GIS_format = ".gpkg"
# GIS_format = ".gpkg"

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **parameter file name**. </font><br>
# <font size = '3'> The default file name, **myparam.param**, is the name of the parameter file provided with NHM subdomain models. If another parameter file is desired or the name has been changed, modify `param_file` here:

# %%
param_file = "myparam.param"
# param_file = "myparam_addl_gages.param"
param_filename = model_dir / param_file

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **control file name**. </font><br>
# <font size = '3'> The default file name, **control.default.bandit** is the name of the control file provided with NHM subdomain models. If another control file is desired or the name has been changed, modify `control_file_name` here:

# %%
# Detected from the model, preferring the bandit-subset control file. Models
# differ: most ship control.default.bandit, but the v1.1 byHWobs New England
# subdomain ships control.bandit, and pywatershed raises rather than falling
# back. Override on the last line if a different control file is wanted.
control_file_name = next(
    (
        candidate
        for candidate in (
            "control.default.bandit",
            "control.bandit",
            "control.default",
        )
        if (model_dir / candidate).exists()
    ),
    "control.default.bandit",
)
#control_file_name = "control.bandit"

control = pws.Control.load_prms(
    model_dir / control_file_name, warn_unused_options=False
)

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **Minimum number of total streamflow observations (days) at a gage**.</font><br> 
# <font size = '3'> Notebook 2 displays additional WaterData gages NOT listed the parameter file. `waterdata_gage_nobs_min` is used to identify gages from WaterData that have a total number of daily stream observations >= `waterdata_gage_nobs_min`.

# %%
waterdata_gage_nobs_min = 365  # days

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **List of parameters**.</font><br>
# <font size = '3'> Notebook 3 visualizes parameter values from the parameter file. Type the parameters you wish to visualize in the list(s) below. To view complete lists of parameters, copy/paste the functions below into a code block. The default parameters in the list below represent parameters calibrated during calibration of the NHM version 1.1. Calibrated values from NHM v 1.1 are displayed in Notebook 3 ([Markstrom and others, 2024](https://www.sciencebase.gov/catalog/item/626c0d67d34e76103cd2ce4a)). More information about NHM parameters can be found in [Markstrom and others, 2015](https://water.usgs.gov/water-resources/software/PRMS/PRMS_tables_5.2.1.pdf)
# >
# ```
# from assist.common.assist_utilities import bynhru_parameter_list, bynmonth_bynhru_parameter_list, bynsegment_parameter_list
# bynhru_parameter_list(param_filename)
# bynmonth_bynhru_parameter_list(param_filename)
# bynsegment_parameter_list(param_filename)
# ```

# %%
# List(s) of NHM calibration parameters with different dimensions
nhru_params = [
    "carea_max",
    "emis_noppt",
    "fastcoef_lin",
    "freeh2o_cap",
    "gwflow_coef",
    "potet_sublim",
    "rad_trncf",
    "slowcoef_sq",
    "smidx_coef",
    "smidx_exp",
    "snowinfil_max",
    "soil2gw_max",
    "soil_moist_max",
    "soil_rechr_max_frac",
    "ssr2gw_exp",
    "ssr2gw_rate",
    "hru_slope",
    "hru_aspect",
]

nhru_nmonths_params = [
    "adjmix_rain",
    "cecn_coef",
    "jh_coef",
    "radmax",
    "rain_cbh_adj",
    "snow_cbh_adj",
    "tmax_allrain_offset",
    "tmax_allsnow",
    "tmax_cbh_adj",
    "tmin_cbh_adj",
]

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **List of output variables**.</font><br>
# <font size = '3'> Notebooks 5 and 6 visualize model output variables from the output file file. List the output variables desired to visualize. To find a list of additional variables for each process, use ".get_variables()". Examples are below.
#
# ```python
# pws.PRMSCanopy.get_variables()
# pws.PRMSSnow.get_variables()
# pws.PRMSRunoff.get_variables()
# pws.PRMSSoilzone.get_variables()
# pws.PRMSGroundwater.get_variables()
# pws.PRMSChannel.get_variables()
# pws.PRMSStarfit.get_variables()
# pws.meta.find_variables([pws.PRMSChannel.get_variables()[2]])
# ```

# %%
selected_output_variables = [
    "gwres_flow",
    "gwres_flow_vol",
    "gwres_sink",
    "gwres_stor",
    "gwres_stor_change",
    "hru_actet",
    "net_ppt",
    "net_rain",
    "net_snow",
    "pkwater_equiv",
    "recharge",
    "seg_outflow",
    "snowmelt",
    "sroff",
    "sroff_vol",
    "ssres_flow",
    "ssres_flow_vol",
    "ssres_stor",
    "unused_potet",
]

# %% [markdown]
# <font size= '4'> &#x270D;<font color='green'>**Enter Information:** </font> **Display output in calendar years (January 1st - December 31st) or water years (October 1st - September 30th)**.</font><br>
# <font size = '3'> Notebooks 5 and 6 visualize model output variables based upon calendar years or water years.
# <br>Default is water years set to **True**. Change to **False** if calendar years are preferred.

# %%
water_years = True

# %% [markdown]
# <font size = '3'>All needed information has been provided above. Run the cell below to create the needed objects, paths and directories for nhm-assist notebooks.
# You're <font size=5 color="red">**NOT FINISHED YET! SAVE YOUR NOTEBOOK**</font> <font size = '3'>to retain entered information!

# %%
# Establish paths and file names
gages_file = model_dir / "gages.csv"
default_gages_file = model_dir / "default_gages.csv"
resource_gages_file = model_dir / "metadata/resource_gages.csv"
waterdata_gages_file = model_dir / 'metadata/WaterDataGages.csv'
output_netcdf_filename = model_dir / "notebook_output_files/nc_files/sf_efc.nc"
NHM_dir = root_dir / "data_dependencies/NHM_v1_1"
prms_meta = MetaData().metadata
pdb = ParameterFile(param_filename, metadata=prms_meta, verbose=False)

# Fabric version is recorded once here so downstream notebooks don't each
# re-parse the parameter file. GFv2 parameter files carry a "GFv2" marker in
# their free-text header (e.g. "GFv2 derived"); GFv1.1 files (written by Bandit)
# do not. Only GFv2 can be positively identified from the header, so anything
# without that marker defaults to "1.1" -- which is also the correct default for
# the v1.1-only calibration-level map layers that consume this value.
fabric_version = "2.0" if any(
    "gfv2" in str(line).lower() for line in pdb.headers
) else "1.1"
print(f"Detected fabric_version: {fabric_version}")

# Create/verify Jupyter notebooks output folder and subfolders in the model directory.
out_dir = model_dir / "output"
out_dir.mkdir(parents=True, exist_ok=True)

notebook_output_dir = model_dir / "notebook_output_files"
notebook_output_dir.mkdir(parents=True, exist_ok=True)

Folium_maps_dir = notebook_output_dir / "Folium_maps"
Folium_maps_dir.mkdir(parents=True, exist_ok=True)

html_maps_dir = notebook_output_dir / "html_maps"
html_maps_dir.mkdir(parents=True, exist_ok=True)

html_plots_dir = notebook_output_dir / "html_plots"
html_plots_dir.mkdir(parents=True, exist_ok=True)

nc_files_dir = notebook_output_dir / "nc_files"
nc_files_dir.mkdir(parents=True, exist_ok=True)

# Print messages to display
workspace_txt = f"NHM model domain: [bold black]{subdomain}[/bold black], parameter file: [bold black]{param_file}[/bold black]\nSimulation and observation data range: {pd.to_datetime(str(control.start_time)).strftime('%m/%d/%Y')} - {pd.to_datetime(str(control.end_time)).strftime('%m/%d/%Y')} (from [bold]{control_file_name}[/bold])."

# %%
import yaml

dict_file = {
    "subdomain": subdomain,
    "model_dir": str(model_dir),
    "fabric_version": fabric_version,
    "GIS_format": GIS_format,
    "param_file": param_file,
    "param_filename": str(param_filename),
    "control_file_name": control_file_name,
    "waterdata_gage_nobs_min": waterdata_gage_nobs_min,
    "nhru_params": nhru_params,
    "nhru_nmonths_params": nhru_nmonths_params,
    "selected_output_variables": selected_output_variables,
    "water_years": water_years,
    "gages_file": str(model_dir / "gages.csv"),
    "default_gages_file": str(model_dir / "default_gages.csv"),
    "resource_gages_file": str(model_dir / "metadata/resource_gages.csv"),
    "waterdata_gages_file": str(waterdata_gages_file),
    "output_netcdf_filename": str(
        model_dir / "notebook_output_files/nc_files/sf_efc.nc"
    ),
    "NHM_dir": str(root_dir / "data_dependencies/NHM_v1_1"),
    "out_dir": str(model_dir / "output"),
    "notebook_output_dir": str(model_dir / "notebook_output_files"),
    "Folium_maps_dir": str(notebook_output_dir / "Folium_maps"),
    "html_maps_dir": str(notebook_output_dir / "html_maps"),
    "html_plots_dir": str(notebook_output_dir / "html_plots"),
    "nc_files_dir": str(notebook_output_dir / "nc_files"),
    "start_date" : str(control.start_time),# pd.to_datetime(str(control.start_time)).strftime("%m/%d/%Y")
    "end_date" : str(control.end_time),# pd.to_datetime(str(control.end_time)).strftime("%m/%d/%Y")
    "workspace_txt": f"NHM model domain: [bold black]{subdomain}[/bold black], parameter file: [bold black]{param_file}[/bold black]\nSimulation and observation data range: {pd.to_datetime(str(control.start_time)).strftime('%m/%d/%Y')} - {pd.to_datetime(str(control.end_time)).strftime('%m/%d/%Y')} (from [bold]{control_file_name}[/bold]).",
}

with open(config_root / "subdomain_config.yaml", "w") as file:
    documents = yaml.dump(dict_file, file)

# %%
