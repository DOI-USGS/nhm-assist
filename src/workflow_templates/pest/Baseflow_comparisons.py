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
import shutil
import pywatershed as pws
import xarray as xr
import numpy as np
import datetime

from contextlib import redirect_stdout
import io

f = io.StringIO()
with redirect_stdout(f):
    import pywatershed as pws

# Find and set the "nhm-assist" root directory
# Find the repo root via pixi's PIXI_PROJECT_ROOT (set by any `pixi run`), with a
# fallback to the package location — works for editable and non-editable installs.
from assist.workspace.bridge import resolve_repo_root

root_dir = resolve_repo_root()

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

from dotenv import load_dotenv

# Use home directory for Nebari, otherwise use repo root_dir
if "NEBARI_CONDA_STORE_SERVER_SERVICE_HOST" in os.environ:
    dotenv_path = pl.Path.home() / ".env"
else:
    dotenv_path = root_dir / ".env"

load_dotenv(dotenv_path=dotenv_path)

###########################################################################


from assist.common.assist_utilities import load_subdomain_config
from assist.common import efc

config = load_subdomain_config(root_dir)

# Standard pest calibration workspace path.
pestpp_dir = root_dir / "pestpp_ies_calibration"

# %% [markdown]
# # Baseflow comparisons
#
# Compare baseflow between model runs and/or observations for the PEST++ IES
# calibration workflow.
#
# The **baseline** is the daily baseflow-separation product
# (`Release_daily_predictions.csv`). We read it, reshape to be indexed by time
# with one column per streamgage id, and plot three stacked, interactive
# timeseries for a selected gage (styled after the common "06" notebook). Other
# simulated datasets will be layered onto these plots later.

# %% [markdown]
# ## Read the daily baseflow predictions (baseline)
#
# The file lives at `<nhm-workspace>/baseflow_data/Release_daily_predictions.csv`.
# Rather than hardcode a drive letter, anchor on the `nhm-workspace` directory
# found by walking up from this notebook's working directory, then descend into
# `baseflow_data`. This mirrors the workspace-relative path strategy used in the
# nhf workflows.

# %%
# Locate the nhm-workspace root from the notebook cwd (no hardcoded drive).
cwd = pl.Path(os.getcwd())
workspace_dir = next(p for p in [cwd, *cwd.parents] if p.name == "nhm-workspace")

baseflow_data_dir = workspace_dir / "baseflow_data"
baseflow_csv = baseflow_data_dir / "Release_daily_predictions.csv"
print("baseflow_csv:", baseflow_csv)

# Long-format columns: SITEID, date, Q, Predicted_SC, Predicted_BF,
# RO_endmember, GW_endmember. Keep SITEID as a string (gage ids can have
# leading zeros) and parse dates.
baseflow_long = pd.read_csv(
    baseflow_csv,
    dtype={"SITEID": str},
    parse_dates=["date"],
)
print("rows:", len(baseflow_long), " gages:", baseflow_long["SITEID"].nunique())
baseflow_long.head()

# %% [markdown]
# ## Reshape: indexed by time, one column per streamgage id
#
# Pivot the long table into a wide, time-indexed structure. Because there are
# several value columns per gage, use a MultiIndex on the columns
# `(variable, SITEID)`, so `baseflow_wide["Predicted_BF"]` is a time x gage
# table (and likewise for the other variables).

# %%
value_cols = ["Q", "Predicted_SC", "Predicted_BF", "RO_endmember", "GW_endmember"]

baseflow_wide = baseflow_long.pivot_table(
    index="date",
    columns="SITEID",
    values=value_cols,
)
baseflow_wide = baseflow_wide.sort_index()
# baseflow_wide.columns is a MultiIndex: level 0 = variable, level 1 = SITEID.
gage_ids = sorted(baseflow_long["SITEID"].unique())
print("time range:", baseflow_wide.index.min(), "to", baseflow_wide.index.max())
print("n gages:", len(gage_ids))
baseflow_wide.head()

# %% [markdown]
# ## Interactive stacked timeseries for a selected gage
#
# Three stacked panels sharing the x-axis (styled after the common "06"
# notebook): predicted baseflow, total streamflow (Q), and the runoff/groundwater
# end-members. A dropdown selects the gage. This is the baseline; simulated
# datasets will be added as extra traces to these panels later.

# %%
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import ipywidgets as widgets
from IPython.display import display

# Which variable goes in each stacked panel, with a display title.
panel_specs = [
    ("Predicted_BF", "Predicted baseflow"),
    ("Q", "Total streamflow (Q)"),
    ("RO_endmember", "Runoff / groundwater end-members"),
]


def make_baseflow_figure(site_id):
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=[title for _, title in panel_specs],
    )

    # Panel 1: predicted baseflow
    fig.add_trace(
        go.Scatter(
            x=baseflow_wide.index,
            y=baseflow_wide["Predicted_BF"][site_id],
            mode="lines",
            name="Predicted baseflow",
            line=dict(color="deepskyblue", width=2),
        ),
        row=1,
        col=1,
    )

    # Panel 2: total streamflow Q
    fig.add_trace(
        go.Scatter(
            x=baseflow_wide.index,
            y=baseflow_wide["Q"][site_id],
            mode="lines",
            name="Q (total)",
            line=dict(color="black", width=1),
        ),
        row=2,
        col=1,
    )

    # Panel 3: runoff and groundwater end-members
    fig.add_trace(
        go.Scatter(
            x=baseflow_wide.index,
            y=baseflow_wide["RO_endmember"][site_id],
            mode="lines",
            name="Runoff end-member",
            line=dict(color="darkorange", width=1),
        ),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=baseflow_wide.index,
            y=baseflow_wide["GW_endmember"][site_id],
            mode="lines",
            name="Groundwater end-member",
            line=dict(color="seagreen", width=1),
        ),
        row=3,
        col=1,
    )

    fig.update_layout(
        title_text=f"Baseflow baseline — gage {site_id}",
        width=900,
        height=750,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.12, xanchor="right", x=1.0),
        font=dict(family="Arial", size=13, color="black"),
        paper_bgcolor="linen",
        plot_bgcolor="white",
    )
    fig.update_xaxes(
        showline=True,
        linewidth=2,
        linecolor="black",
        gridcolor="lightgrey",
        ticks="inside",
        tickwidth=2,
        tickcolor="black",
        ticklen=8,
    )
    fig.update_yaxes(
        showline=True,
        linewidth=2,
        linecolor="black",
        gridcolor="lightgrey",
        ticks="inside",
        tickwidth=2,
        tickcolor="black",
        ticklen=8,
    )
    fig.update_layout(
        hoverlabel=dict(bgcolor="linen", font_size=12, font_family="Rockwell")
    )
    return fig


gage_dd = widgets.Dropdown(
    options=gage_ids,
    value=gage_ids[0],
    description="Gage:",
)
plot_out = widgets.Output()


def _refresh(site_id):
    with plot_out:
        plot_out.clear_output(wait=True)
        make_baseflow_figure(site_id).show()


def _on_change(change):
    if change["name"] == "value" and change["new"] is not None:
        _refresh(change["new"])


gage_dd.observe(_on_change, names="value")
_refresh(gage_dd.value)
display(widgets.VBox([gage_dd, plot_out]))
