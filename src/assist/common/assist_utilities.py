"""Shared assist utilities for the nhm and nhf workflows.

Unified from src/assist/nhm/nhm_assist_utilities.py and
src/assist/nhf/nhm_assist_utilities_v2.py. See
docs/superpowers/specs/2026-08-30-helper-unification-design.md.
"""

import glob
import os
import pathlib as pl

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly
import plotly.express as px
import pywatershed as pws
import yaml
from dataretrieval import waterdata
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
from rich.console import Console

from assist.common.helpers import hrus_by_poi

con = Console()

# nhm used the NWIS spelling; nhf renamed to WaterData. Accept both, canonical
# form is the WaterData spelling.
CONFIG_KEY_ALIASES: dict[str, str] = {
    "nwis_gages_file": "waterdata_gages_file",
    "nwis_gage_nobs_min": "waterdata_gage_nobs_min",
}

# Every key some consumer reads. Derived by parsing all config[...] and
# config.get(...) reads under src/: 28 keys, none read defensively, so a missing
# one is a broken workspace rather than a soft default. Both pre-unification
# baselines subscripted each of these directly.
REQUIRED_CONFIG_KEYS = frozenset({
    "Folium_maps_dir", "GIS_format", "NHM_dir", "control_file_name",
    "default_gages_file", "end_date", "gages_file", "html_maps_dir",
    "html_plots_dir", "model_dir", "nc_files_dir", "nhru_nmonths_params",
    "nhru_params", "notebook_output_dir", "out_dir", "output_netcdf_filename",
    "param_file", "param_filename", "selected_output_variables", "start_date",
    "subdomain", "water_years", "waterdata_gage_nobs_min",
    "waterdata_gages_file", "workspace_txt",
})

# Present only in nhf-shaped configs; nhm-shaped ones legitimately omit it.
OPTIONAL_CONFIG_KEYS = frozenset({"resource_gages_file"})

# All 14 keys both baselines wrapped in pl.Path(). Omitting any of these leaves a
# raw str in the config, and consumers doing `config["out_dir"] / "x.nc"` raise
# TypeError. Verified against both baselines at 27f7144.
# `nwis_gages_file` is the legacy alias of `waterdata_gages_file` (see
# CONFIG_KEY_ALIASES); it is wrapped here too so a config carrying both
# spellings doesn't leave the legacy one as a raw str.
_PATH_KEYS = (
    "Folium_maps_dir",
    "model_dir",
    "param_filename",
    "gages_file",
    "default_gages_file",
    "output_netcdf_filename",
    "waterdata_gages_file",
    "nwis_gages_file",
    "resource_gages_file",
    "NHM_dir",
    "out_dir",
    "notebook_output_dir",
    "html_maps_dir",
    "html_plots_dir",
    "nc_files_dir",
)


def load_subdomain_config(root_dir: pl.Path) -> dict:
    """Load `subdomain_config.yaml`, accepting either the NWIS or WaterData schema."""
    config_path = pl.Path(root_dir) / "subdomain_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            "Missing subdomain config at "
            f"{config_path}. Set the active model for the project, then run "
            "0_workspace_setup.ipynb first from the same project notebook "
            "directory before running later notebooks."
        )

    with open(config_path) as handle:
        raw = yaml.load(handle, Loader=yaml.FullLoader)

    # Fold the retired NWIS key names onto their WaterData equivalents, and back
    # -fill the other direction too, so BOTH spellings are always present no
    # matter which schema the yaml was written in. Copy, don't move: an
    # nhm-written config must keep resolving `nwis_*` for its own templates.
    # The WaterData spelling is canonical when a config somehow carries both.
    for old_key, new_key in CONFIG_KEY_ALIASES.items():
        if old_key in raw and new_key not in raw:
            raw[new_key] = raw[old_key]
        elif new_key in raw and old_key not in raw:
            raw[old_key] = raw[new_key]

    missing = sorted(REQUIRED_CONFIG_KEYS - set(raw))
    if missing:
        raise KeyError(
            f"{config_path} is missing required key(s): {', '.join(missing)}. "
            "Re-run 0_workspace_setup.ipynb for this model to regenerate it."
        )

    config: dict = dict(raw)
    for key in _PATH_KEYS:
        value = raw.get(key)
        config[key] = pl.Path(value) if value is not None else None

    # Both baselines normalized these to %m/%d/%Y; templates delegate the
    # formatting to this loader (see nhm/0_workspace_setup.py, etc.). Guard
    # against configs lacking the keys, and against a value already in this
    # format (pd.to_datetime parses both forms, so re-normalizing is a no-op).
    for key in ("start_date", "end_date"):
        value = raw.get(key)
        if value is not None:
            config[key] = pd.to_datetime(value).strftime("%m/%d/%Y")

    config.setdefault("resource_gages_file", None)
    return config


def bynhru_parameter_list(param_filename):
    """
    Reads the parameter file and creates a list of parameters that are dimensioned by nhru.

    Parameters
    ----------
    param_filename : pathlib Path class 
        Path to parameter file. 
            
    Returns
    -------
    bynhru_params : [str]
        List of the parameters in the paramter file that are dimensioned by nhru.
    """
    pardat = pws.parameters.PrmsParameters.load(param_filename)
    bynhru_params = []
    for par in list(pardat.parameters.keys()):
        kk = list(pws.meta.parameters[par]["dims"])
        if kk == ["nhru"]:
            bynhru_params.append(par)
        else:
            pass
    return bynhru_params


def bynmonth_bynhru_parameter_list(param_filename):
    """
    Reads the parameter file and creates a list of parameters that are dimensioned by nhru and nmonths.

    Parameters
    ----------
    param_filename : pathlib Path class 
        Path to parameter file. 
            
    Returns
    -------
    bynhru_params : [str]
        List of the parameters in the paramter file that are dimensioned by nhru and nmonths.
    """
    pardat = pws.parameters.PrmsParameters.load(param_filename)
    bynmonth_bynhru_params = []
    for par in list(pardat.parameters.keys()):
        kk = list(pws.meta.parameters[par]["dims"])
        if kk == ["nmonth", "nhru"]:
            bynmonth_bynhru_params.append(par)
        else:
            pass
    return bynmonth_bynhru_params


def bynsegment_parameter_list(param_filename):
    """
    Reads the parameter file and creates a list of parameters that are dimensioned by nsegment.

    Parameters
    ----------
    param_filename : pathlib Path class 
        Path to parameter file. 
            
    Returns
    -------
    bynhru_params : [str]
        List of the parameters in the paramter file that are dimensioned by nsegment.
    """
    pardat = pws.parameters.PrmsParameters.load(param_filename)
    bynsegment_params = []
    for par in list(pardat.parameters.keys()):
        kk = list(pws.meta.parameters[par]["dims"])
        if kk == ["nsegment"]:
            bynsegment_params.append(par)
        else:
            pass
    return bynsegment_params


def delete_notebook_output_files(
    *,
    notebook_output_dir: pl.Path,
    model_dir: pl.Path,
) -> None:
    """Clear prior notebook output so a rerun starts clean."""
    notebook_output_dir = pl.Path(notebook_output_dir)
    model_dir = pl.Path(model_dir)

    subfolders = ["Folium_maps", "html_maps", "html_plots", "nc_files"]
    deleted_by_subfolder: dict[str, int] = {}
    for subfolder in subfolders:
        folder_path = notebook_output_dir / subfolder
        if not folder_path.exists():
            continue
        count = 0
        for file_name in os.listdir(folder_path):
            file_path = folder_path / file_name
            if file_path.is_file():
                os.remove(file_path)
                count += 1
        if count:
            deleted_by_subfolder[subfolder] = count

    deleted_model_files = 0
    files = [
        "default_gages.csv",
        "append_gages_to_param_file.csv",
        "default_gages_file.csv",
        "NWISgages.csv",
        "WaterDataGages.csv",
    ]
    for file_name in files:
        target = model_dir / file_name
        if target.exists():
            os.remove(target)
            deleted_model_files += 1

    metadata_files = ["WaterDataGages.csv"]
    for file_name in metadata_files:
        target = model_dir / "metadata" / file_name
        if target.exists():
            os.remove(target)
            deleted_model_files += 1

    total = sum(deleted_by_subfolder.values()) + deleted_model_files
    if total == 0:
        print("No prior notebook output files to delete.")
    else:
        print(f"Deleted {total} prior notebook output file(s).")

def make_plots_par_vals(
    *,
    poi_df,
    hru_gdf,
    param_filename,
    nhru_params,
    nhru_nmonths_params,
    Folium_maps_dir,
):
    """
    Builds plots parameter value plots for hrus in all gaged catchments and saves them as html text files to be brought into maps later as pop-ups. This function takes a long time to run, >20 minutes.
    
    Parameters
    ----------
    poi_df : pandas DataFrame()
        Pandas DataFrame() containing gages from the parameter file.
    hru_gdf : geopandas GeoDataFrame
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    param_filename : pathlib Path class 
        Path to parameter file.
    nhru_params:  list of string values
        List of selected parameters dimensioned by nhru.
    nhru_nmonths_params : list of string values
        List of selected parameters dimensioned by nhru and nmonths.
    Folium_maps_dir : pathlib Path class
        Path to folder containing the html plots for all parameters listed for all HRUs in gage catchments. 
    """
    
    cal_hru_params = nhru_params + nhru_nmonths_params

    """First, group HRUs to the downstream gagepoi that they contribute flow.
    """
    poi_list = poi_df["poi_gage_id"].values.tolist()

    """Make a dictionary of pois and the list of HRUs in the contributing area for each poi.
    """
    prms_meta = MetaData().metadata  # loads metadata functions for pyPRMS
    pdb = ParameterFile(
        param_filename, metadata=prms_meta, verbose=False
    )  # loads parmaeterfile functions for pyPRMS

    hru_poi_dict = hrus_by_poi(pdb, poi_list)  # Helper function from pyPRMS

    """Sort the dictionary: this is important for the reverse dictionary (next step) to accurately give a poi_group
    to hrus that contribute to a downstream-gage.
    """
    sorted_items = sorted(
        hru_poi_dict.items(), key=lambda item: -len(item[1])
    )  # the - reverses the sorting order
    hru_poi_dict = dict(sorted_items[:])

    reversed_hru_poi_dict = {
        val: key for key in hru_poi_dict for val in hru_poi_dict[key]
    }

    # assigns poi_group value to all hrus #Keep for later application
    hru_gdf["poi_group"] = hru_gdf["nhm_id"].astype(int).map(reversed_hru_poi_dict)

    """Builds plots, takes  20 minutes to build all param plots for all pois
    """

    for idx, par in enumerate(cal_hru_params):
        try:
            pdb.get(par).dimensions["nmonths"].size

        except KeyError:
            # print(f"Checking for {par} dimensioned by nhru.")

            for idx, poi_gage_id in enumerate(poi_list):
                par_plot_file = Folium_maps_dir / f"{par}_{poi_gage_id}.txt"
                if par_plot_file.exists():
                    pass
                    # print(
                    #     f"{par}_{poi_gage_id}.txt exists. To recreate the plot, remove the file from Folium_maps_dir"
                    # )
                    # print(par_plot_file)
                else:

                    ##%%time = par
                    # Preporcessing: pulling only the selected param values for the HRUs related to the selected POI to plot.
                    output_var_sel_plot_df = hru_gdf[
                        hru_gdf["nhm_id"].astype(int).isin(hru_poi_dict[poi_gage_id])
                    ]
                    output_var_sel_plot_df = output_var_sel_plot_df.sort_values(
                        ["hru_area"], ascending=True
                    )
                    output_var_sel_plot_df.hru_area = (
                        output_var_sel_plot_df.hru_area.round()
                    )

                    x_axis_var = "hru_area"  # we broke this out separately to quickly generate new plots based on a different variable for the x-axis
                    fig = px.scatter(
                        output_var_sel_plot_df,
                        x=x_axis_var,
                        y=par,
                        # markers = True,
                        custom_data="nhm_id",
                        color="poi_group",
                        labels={"poi_group": "Downstream POI"},
                    )

                    fig.update_layout(
                        title=dict(
                            text=f"{par} for HRUs in {poi_gage_id} catchment",
                            font=dict(size=18),
                            automargin=True,
                            yref="paper",
                        ),
                        width=500,
                        height=300,
                        showlegend=True,
                        font=dict(
                            family="Arial", size=10, color="#7f7f7f"
                        ),  # font color
                        paper_bgcolor="linen",
                        plot_bgcolor="white",
                    )

                    fig.update_yaxes(title_text=f'{par}, {pdb.get(par).meta["units"]}')
                    fig.update_xaxes(
                        title_text=f'{x_axis_var}, {pdb.get(x_axis_var).meta["units"]}'
                    )

                    fig.update_xaxes(
                        ticks="inside", tickwidth=2, tickcolor="black", ticklen=10
                    )
                    fig.update_yaxes(
                        ticks="inside", tickwidth=2, tickcolor="black", ticklen=10
                    )

                    fig.update_xaxes(
                        showline=True,
                        linewidth=2,
                        linecolor="black",
                        showgrid=False,
                        # gridcolor='lightgrey',
                    )
                    fig.update_yaxes(
                        showline=True,
                        linewidth=2,
                        linecolor="black",
                        showgrid=False,
                        # gridcolor='lightgrey',
                    )

                    # fig.update_xaxes(type='category')
                    fig.update_xaxes(autorange=True)

                    fig.update_traces(
                        hovertemplate="<br>".join(
                            [
                                "parameter value: %{y}",
                                "nhu area: %{x}",
                                "hru: %{customdata[0]}",
                            ]
                        )
                    )

                    fig.update_layout(hovermode="closest")
                    fig.update_layout(
                        hoverlabel=dict(
                            bgcolor="linen", font_size=13, font_family="Rockwell"
                        )
                    )

                    # Creating the html code for the plotly plot
                    text_div = plotly.offline.plot(
                        fig, include_plotlyjs=False, output_type="div"
                    )

                    # Saving the plot as txt file with the html code
                    # idx = 1
                    with open(Folium_maps_dir / f"{par}_{poi_gage_id}.txt", "w") as f:
                        f.write(text_div)

                    # fig.show()

        else:
            # print(f"Checking for {par} dimensioned by nhru and nmonths")

            for idx, poi_gage_id in enumerate(poi_list):

                par_plot_file = Folium_maps_dir / f"{par}_{poi_gage_id}.txt"
                if par_plot_file.exists():
                    pass
                    
                else:
                    # Reshapes the monthly data for plotting: assigns a "month" number
                    first = True
                    for vv in range(1, 13):
                        if first:
                            zz = f"{par}_{str(vv)}"
                            df = hru_gdf[["nhm_id", zz]]
                            df["month"] = vv
                            df[par] = df[zz]
                            df.drop(columns=zz, inplace=True)
                            first = False
                        else:
                            zz = f"{par}_{str(vv)}"
                            df2 = hru_gdf[["nhm_id", zz]]
                            df2["month"] = vv
                            df2[par] = df2[zz]
                            df2.drop(columns=zz, inplace=True)

                            df = pd.concat([df, df2], ignore_index=True)

                    nhru_params_nmonths_sel_df = df.copy()
                    ############################################################################################
                    nhru_params_nmonths_sel_plot_df = nhru_params_nmonths_sel_df[
                        nhru_params_nmonths_sel_df["nhm_id"].isin(hru_poi_dict[poi_gage_id])
                    ]
                    # nhru_params_nmonths_sel_plot_df = nhru_params_nmonths_sel_df[nhru_params_nmonths_sel_df['poi_group'] == poi_gage_id]

                    fig = px.line(
                        nhru_params_nmonths_sel_plot_df,
                        x="month",
                        y=par,
                        markers=True,
                        custom_data=nhru_params_nmonths_sel_plot_df[["nhm_id"]],
                        color="nhm_id",
                        labels={"nhm_id": "HRU"},
                    )

                    fig.update_layout(
                        title_text=f"{par} for HRUs in {poi_gage_id} catchment",
                        width=500,
                        height=300,
                        showlegend=True,
                        # legend=dict(orientation="h",yanchor="bottom",y=1.02, xanchor="right", x=1),
                        font=dict(
                            family="Arial", size=10, color="#7f7f7f"
                        ),  # font color
                        paper_bgcolor="linen",
                        plot_bgcolor="white",
                    )

                    fig.update_yaxes(title_text=f"{par}, units")
                    fig.update_xaxes(title_text="Months")

                    fig.update_xaxes(
                        ticks="inside", tickwidth=2, tickcolor="black", ticklen=10
                    )
                    fig.update_yaxes(
                        ticks="inside", tickwidth=2, tickcolor="black", ticklen=10
                    )

                    fig.update_xaxes(
                        showline=True,
                        linewidth=2,
                        linecolor="black",
                        gridcolor="lightgrey",
                    )
                    fig.update_yaxes(
                        showline=True,
                        linewidth=2,
                        linecolor="black",
                        gridcolor="lightgrey",
                    )

                    fig.update_xaxes(autorange=True)

                    fig.update_traces(
                        hovertemplate="<br>".join(
                            [
                                "{parameter: %{y}",
                                "month: %{x}",
                                "hru: %{customdata[0]}",
                            ]
                        )
                    )

                    fig.update_layout(hovermode="closest")
                    fig.update_layout(
                        hoverlabel=dict(
                            bgcolor="linen", font_size=13, font_family="Rockwell"
                        )
                    )

                    # Creating the html code for the plotly plot
                    text_div = plotly.offline.plot(
                        fig, include_plotlyjs=False, output_type="div"
                    )

                    # Saving the plot as txt file with the html code
                    with open(Folium_maps_dir / f"{par}_{poi_gage_id}.txt", "w") as f:
                        f.write(text_div)

def create_append_gages_to_param_file(
    *,
    gages_df,
    seg_gdf,
    poi_df,
    model_dir,
):
    """
    Make an editable .csv file from the gages_df, so that users can append new poigage (dimensioned) parameters to
    the myparam.param file, and returns a pandas DataFrame of the written .csv.

    First, a geopandas GeoDataFrame is made for the gages_df using the lat/lon from the gages_df (NWIS or user supplied).
    Projection is set to crs=4326 and may introduce some spatial innaccuracy for older gages.

    Requires nhm-shaped input: `seg_gdf` must carry `nhm_seg` and `model_idx`.
    Not usable from the nhf workflow (a GFv2 `seg_gdf`) until the hydrofabric
    concern settles segment-column naming; calling it there raises `KeyError`.
    """
    gages_gdf = gpd.GeoDataFrame(
        gages_df,
        geometry=gpd.points_from_xy(gages_df.longitude, gages_df.latitude),
        crs=4326,
    )
    """ Gages_gdf (points_gdf) and seg_gdf (lines_gdf) projections changed for geo distance calculation. """
    _points_gdf = gages_gdf.to_crs("ESRI:102039")
    _lines_gdf = seg_gdf.to_crs("ESRI:102039")

    _poi_max_distance = 1000  # spatial units of projections, meters for ESRI:102039

    """ A spatial join for the nearest segment to a gage yields a likely candidate poi_gage_segment for each poi_gage_id 
        and the distance from the gage to the segment. """
    append_gages_to_param_file_df = gpd.sjoin_nearest(
        _points_gdf,
        _lines_gdf,
        max_distance=_poi_max_distance,
        distance_col="distance",
        how="left",
    )
    """ Cleanup """
    append_gages_to_param_file_df = append_gages_to_param_file_df[
        gages_df.columns.to_list() + ["nhm_seg", "model_idx", "distance"]
    ]
    append_gages_to_param_file_df = append_gages_to_param_file_df[
        ["nhm_seg", "poi_name", "poi_agency", "distance"]
    ].reset_index(drop=False)
    """ Set an attribute "in_param_file" to show user which gages in the gages_df are in the myparam.param file. """
    append_gages_to_param_file_df["in_param_file"] = "no"
    param_file_gages = poi_df.poi_gage_id.to_list()
    append_gages_to_param_file_df.loc[
        append_gages_to_param_file_df["poi_gage_id"].isin(param_file_gages),
        "in_param_file",
    ] = "yes"

    yes_list = list(append_gages_to_param_file_df.loc[append_gages_to_param_file_df['in_param_file'] == 'yes', 'nhm_seg'])
    no_list = list(append_gages_to_param_file_df.loc[append_gages_to_param_file_df['in_param_file'] == 'no', 'nhm_seg'])
    yes_only_list = list(set(yes_list) - set(no_list))
    print(yes_only_list)

    append_gages_to_param_file_df_new = append_gages_to_param_file_df[~append_gages_to_param_file_df.nhm_seg.isin(yes_only_list)]
    append_gages_to_param_file_df_new.sort_values(by=['nhm_seg', 'in_param_file'], ascending=[True, True], inplace=True)
    """ Write new param file to the subdomain model directory. """
    append_gages_to_param_file_df_new.to_csv(
        model_dir / "append_gages_to_param_file.csv", index=False
    )

def make_myparam_addl_gages_param_file(
    *,
    model_dir,
    param_filename,
):
    """Add the gages from `append_gages_to_param_file.csv` to the parameter file.

    Requires nhm-shaped input: reads a `nhm_seg` column out of that csv and maps
    it through the parameter file's `nhm_seg` index. Not usable from the nhf
    workflow (a GFv2 `seg_gdf`/`segment_id` naming) until the hydrofabric
    concern settles segment-column naming; calling it there raises `ValueError`
    or `KeyError` depending on which csv shape it is handed.
    """
    prms_meta = MetaData().metadata
    pdb = ParameterFile(param_filename, metadata=prms_meta, verbose=False)
    
    """Read back in the modified gages to add file"""
    col_names = [
        "poi_gage_id",
        "nhm_seg",
    ]
    col_types = [
        np.str_,
        "Int32",
    ]
    cols = dict(zip(col_names, col_types))

    addl_gages_df = pd.read_csv(
        model_dir / "append_gages_to_param_file.csv",
        dtype=cols,
        usecols=[
            "poi_gage_id",
            "nhm_seg",
        ],
    )
    addl_gages_df.dropna(how= 'all', inplace=True)
    nhm_seg_to_idx1 = {kk: vv + 1 for kk, vv in pdb.get("nhm_seg").index_map.items()}

    addl_gages_df["poi_gage_segment"] = addl_gages_df["nhm_seg"].map(nhm_seg_to_idx1)

    addl_gages = dict(
        zip(
            addl_gages_df["poi_gage_id"].to_list(),
            addl_gages_df["poi_gage_segment"].to_list(),
        )
    )

    pdb.add_poi(addl_gages)
    new_par_file = model_dir / "myparam_addl_gages.param"
    if new_par_file.exists():
        con.print(f"The new parameter file {new_par_file.name} already exists and will NOT be overwritten. Please rename that file and rerun this cell.")
    else:
        pdb.write_parameter_file(model_dir / "myparam_addl_gages.param")
        os.remove(model_dir / "append_gages_to_param_file.csv")
        del pdb
        con.print("New paramter file `myparam_addl_gages.param` created in the model directory.")

    return

def make_obs_plot_files(*, start_date, end_date, gages_df, xr_streamflow, Folium_maps_dir, max_workers=8):
    """This function makes plots and saved with as html.txt files to be embedded in the hf_map
    by notebook 2_model_hydrofabric_visualization.ipynb used to evaluate ti gages shown in the
    map have desirable lengths of record to include the gage as a poi in the parameter file.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tqdm.auto import tqdm

    def _make_single_plot(cpoi):
        obs_plot_file = Folium_maps_dir / f"{cpoi}_streamflow_obs.txt"
        if obs_plot_file.exists():
            return f"{cpoi}_streamflow_obs.txt file exists."

        ds_sub = xr_streamflow.sel(poi_gage_id=cpoi, time=slice(start_date, end_date))
        ds_sub_df = ds_sub.to_dataframe()
        ds_sub_df.reset_index(inplace=True, drop=False)

        fig = px.line(
            ds_sub_df,
            x="time",
            y="discharge",
            markers=False,
            labels={
                "discharge": "Discharge",
                "time": "Date",
            },
        )

        fig.update_layout(
            title_text=f"{cpoi} daily streamflow observations",
            width=500,
            height=300,
            showlegend=True,
            font=dict(family="Arial", size=10, color="#7f7f7f"),
            paper_bgcolor="linen",
            plot_bgcolor="white",
        )

        fig.update_yaxes(title_text="Discharge, cfs")
        fig.update_xaxes(title_text="Date")

        fig.update_xaxes(ticks="inside", tickwidth=2, tickcolor="black", ticklen=10)
        fig.update_yaxes(ticks="inside", tickwidth=2, tickcolor="black", ticklen=10)

        fig.update_xaxes(
            showline=True,
            linewidth=2,
            linecolor="black",
            gridcolor="lightgrey",
        )
        fig.update_yaxes(
            showline=True,
            linewidth=2,
            linecolor="black",
            gridcolor="lightgrey",
        )

        fig.update_xaxes(autorange=True)

        text_div = plotly.offline.plot(
            fig, include_plotlyjs=False, output_type="div"
        )

        with open(obs_plot_file, "w") as f:
            f.write(text_div)

        return f"{cpoi} plot created."

    poi_list = gages_df.index.tolist()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_make_single_plot, cpoi): cpoi for cpoi in poi_list}
        with tqdm(total=len(poi_list), desc="Generating obs plots") as pbar:
            for future in as_completed(futures):
                future.result()
                pbar.update(1)


def find_missing_gage_info(root_dir, dest_dir, gages_list, resource_file_path):
    """
     
    This is used to find metadata needed for gages in the list provided.

    First, metadata is sought for in the resource (supplemental) gages file (if one exists).
    Second, location data specifically is sought for in the usgs_nldi_gages database,
    Third, metadata is sought for in USGS WaterData database.

    """
    npoigages_data_dir = root_dir / "data_dependencies/"

    dest_dir.mkdir(parents=True, exist_ok=True)
        
    nan_list = [np.nan] * len(gages_list)  # Initialize empty list
    gages_df = pd.DataFrame(
        {
            "poi_gage_id": gages_list,
            "poi_agency": nan_list,
            "poi_name": nan_list,
            "latitude": nan_list,
            "longitude": nan_list,
            "drainage_area": nan_list,
            "drainage_area_contrib": nan_list,
        }
    )  # Initialize empty datafame

    # Check for resource (supplemental) file, if present, append information to gages_df
    if resource_file_path.exists():
        col_names_1 = [
            "poi_gage_id",
            "poi_agency",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
        ]
        col_types_1 = [np.str_, np.str_, np.str_, float, float, float, float]
        cols = dict(zip(col_names_1, col_types_1))
        resource_df = pd.read_csv(resource_file_path, dtype=cols)

        gages_lacking_info_list = []
        gages_found_info_list = []
        check_list = resource_df["poi_gage_id"].to_list()

        if len(check_list) > 0:
            # print(
            #     f"Searching {resource_file_path} for meta data."
            # )
            for idx, row in gages_df.iterrows():
                columns = ["latitude", "longitude", "poi_name", "poi_agency"]
                item_lacking_list = []
                item_found_list = []
                for item in columns:
                    if pd.isnull(row[item]):
                        item_lacking_list.append(item)
                        gages_lacking_info_list.append(row["poi_gage_id"])
                        new_poi_id = row["poi_gage_id"]
                        if new_poi_id in check_list:
                            gages_found_info_list.append(row["poi_gage_id"])
                            item_found_list.append(item)
                            new_item = resource_df.loc[
                                resource_df.poi_gage_id == new_poi_id, item
                            ].values[0]
                            gages_df.loc[idx, item] = new_item
                        else:
                            pass

            lacking_info_list = list(set(gages_lacking_info_list))
            gages_found_info_list = list(set(gages_found_info_list))
            still_lacking_info_list = [
                x for x in lacking_info_list if x not in gages_found_info_list
            ]

            print(
                f"{len(gages_found_info_list)} of {len(gages_list)} gages found metadata in {resource_file_path}",
            )
        else:
            pass

    else:
        print(f"No gage meta data resource file provided at {resource_file_path}.",
             )

    ''' 
    Mask for items still missing metadata
    '''
    
    cols = ["latitude", "longitude", "poi_name", "poi_agency"]
    mask_missing = gages_df[cols].isnull().any(axis=1)
    missing_meta_df = gages_df.loc[mask_missing]

    nldi_geojson_path = npoigages_data_dir / "usgs_nldi_gages.geojson"

    if not missing_meta_df.empty and nldi_geojson_path.exists():
        """
        First, Check the NLDI json for missing data in the dependencies folder.
        These data are said to have the most acurate location information, so stop there first.
        """
        print(f"{len(missing_meta_df)} gages missing metadata. Searching NLDI database.")
        ##### Check NLDI database for missing gage info
        file_path = nldi_geojson_path
        nldi_gdf = gpd.read_file(file_path)  # or .geojson
    
        # Split on the first '-' and create new columns
        nldi_gdf[["poi_agency", "poi_gage_id"]] = (
            nldi_gdf["id"]
            .astype("string")  # keeps NaN as <NA>
            .str.strip()
            .str.split("-", n=1, expand=True)  # split on the first dash only
        )
        try:
            nldi_gdf.to_file(
                npoigages_data_dir / "usgs_nldi_gages.gpkg",
                driver="GPKG",
            )
        except OSError:
            # data_dependencies/ may be read-only on shared filesystems.
            # The cache is an optimization; carry on with the in-memory frame.
            pass
    
        nldi_gdf = nldi_gdf[["poi_agency", "name", "poi_gage_id", "geometry"]]
        nldi_gdf.rename(
            columns={
                "name": "poi_name",
            },
            inplace=True,
        )
        nldi_gdf["latitude"] = nldi_gdf.geometry.y
        nldi_gdf["longitude"] = nldi_gdf.geometry.x
        nldi_gdf["drainage_area"] = np.nan
        nldi_gdf["drainage_area_contrib"] = np.nan
    
        nldi_gdf = nldi_gdf[
            [
                "poi_gage_id",
                "poi_agency",
                "poi_name",
                "latitude",
                "longitude",
                "drainage_area",
                "drainage_area_contrib",
                "geometry",
            ]
        ]
    
        gages_lacking_info_list = []
        gages_found_info_list = []
        check_list = nldi_gdf["poi_gage_id"].to_list()
    
        for idx, row in gages_df.loc[mask_missing].iterrows():
            columns = ["latitude", "longitude", "poi_name", "poi_agency"]
            item_lacking_list = []
            item_found_list = []
            for item in columns:
                if pd.isnull(row[item]):
                    item_lacking_list.append(item)
                    gages_lacking_info_list.append(row["poi_gage_id"])
                    new_poi_id = row["poi_gage_id"]
                    if new_poi_id in check_list:
                        gages_found_info_list.append(row["poi_gage_id"])
                        item_found_list.append(item)
                        new_item = nldi_gdf.loc[
                            nldi_gdf.poi_gage_id == new_poi_id, item
                        ].values[0]
                        gages_df.loc[idx, item] = new_item
                    else:
                        pass
    
        lacking_info_list = list(set(gages_lacking_info_list))
        gages_found_info_list = list(set(gages_found_info_list))
        still_lacking_info_list = [
            x for x in lacking_info_list if x not in gages_found_info_list
        ]
    
        print(
            f"Metadata for {len(gages_found_info_list)} gages found in NLDI database.csv",
            # f"{len(list(set(still_lacking_info_list)))} of {len(gages_df)} are still lacking gage info.",
        )
    elif not missing_meta_df.empty:
        # non-fatal: the NLDI extract is an optional local data dependency that is
        # absent on air-gapped deployments and on fresh clones (data_dependencies/
        # is not tracked). The WaterData lookup below covers these gages.
        print(
            f"NLDI database not found at {nldi_geojson_path}; "
            f"seeking {len(missing_meta_df)} gages in USGS WaterData instead."
        )
    
    ''' 
    Mask for items still missing metadata
    '''
    cols = ["latitude", "longitude", "poi_name", "poi_agency"]
    mask_missing = gages_df[cols].isnull().any(axis=1)
    missing_meta_df = gages_df.loc[mask_missing]

    if not missing_meta_df.empty:
        print(f"{len(missing_meta_df)} gages missing metadata. Searching USGS WaterData database.")
        # Get monitoring location information from USGS WaterData
        """Now, get the site infomation for the new list
                used the chunk format from the example: 
                https://github.com/DOI-USGS/dataretrieval-python/blob/dc9b614f646b2656c17acc77c0161762053afaf6/demos/WaterData_demo.ipynb
        """
        chunk_size = 100
        site_list = gages_df.loc[mask_missing]["poi_gage_id"].unique().tolist()
    
        chunks = [
            site_list[i : i + chunk_size] for i in range(0, len(site_list), chunk_size)
        ]
        domain_locations = pd.DataFrame()
    
        for site_group in chunks:
            try:
                chunk_data, _ = waterdata.get_monitoring_locations(
                    monitoring_location_number=site_group,
                    site_type_code="ST",
                    properties=[
                        "monitoring_location_id",
                        "geometry",
                        "agency_code",
                        "agency_name",
                        "monitoring_location_number",
                        "monitoring_location_name",
                        "state_name",
                        "drainage_area",
                        "contributing_drainage_area",
                    ],
                )
                if not chunk_data.empty:
                    domain_locations = pd.concat([domain_locations, chunk_data])
                else:
                    print("No info in WaterData.")
    
            except Exception as e:
                print(f"Chunk failed: {e}")
        if not domain_locations.empty:
            domain_locations["latitude"] = (
                domain_locations.geometry.y
            )  # need this for the notebooks
            domain_locations["longitude"] = (
                domain_locations.geometry.x
            )  # need this for the notebooks
    
            waterdata_gage_info = None
            waterdata_gage_info = (
                domain_locations.set_index(
                    "monitoring_location_number", drop=False
                ).set_crs("EPSG:4326")
                # .to_crs(crs)
            )
    
            field_map = {
                "agency_code": "poi_agency",
                "monitoring_location_number": "poi_gage_id",
                "monitoring_location_name": "poi_name",
                "geometry": "geometry",
                "latitude": "latitude",
                "longitude": "longitude",
                "drainage_area": "drainage_area",
                "contributing_drainage_area": "drainage_area_contrib",
            }
            include_cols = list(field_map.keys())
    
            waterdata_gage_info = waterdata_gage_info.loc[:, include_cols]
            waterdata_gage_info.rename(columns=field_map, inplace=True)
            waterdata_gage_info.set_index("poi_gage_id", inplace=True)
            waterdata_gage_info = waterdata_gage_info.sort_index()
            waterdata_gage_info.reset_index(inplace=True)
    
            gages_lacking_info_list = []
            gages_found_info_list = []
            check_list = waterdata_gage_info["poi_gage_id"].to_list()
    
            for idx, row in gages_df.loc[mask_missing].iterrows():
                columns = [
                    "latitude",
                    "longitude",
                    "poi_name",
                    "poi_agency",
                    "drainage_area",
                    "drainage_area_contrib",
                ]
                item_lacking_list = []
                item_found_list = []
                for item in columns:
                    if pd.isnull(row[item]):
                        item_lacking_list.append(item)
                        gages_lacking_info_list.append(row["poi_gage_id"])
                        new_poi_id = row["poi_gage_id"]
                        if new_poi_id in check_list:
                            gages_found_info_list.append(row["poi_gage_id"])
                            item_found_list.append(item)
                            new_item = waterdata_gage_info.loc[
                                waterdata_gage_info.poi_gage_id == new_poi_id, item
                            ].values[0]
                            gages_df.loc[idx, item] = new_item
                        else:
                            pass
    
            lacking_info_list = list(set(gages_lacking_info_list))
            gages_found_info_list = list(set(gages_found_info_list))
            still_lacking_info_list = [
                x for x in lacking_info_list if x not in gages_found_info_list
            ]
    
            print(
                f"{len(gages_found_info_list)} gages of {len(gages_df.loc[mask_missing])}found metadata in USGS WaterData database.",
                # f"{len(list(set(still_lacking_info_list)))} of {len(gages_df)} are still lacking gage info.",
            )
        else:
            pass
            # print("Gage metadata not found in USGS WaterData database.")
        # Have to make code for if exists, check for, and then append so we don't overwrite


    #drop from defualt missing data
    cols = ["latitude", "longitude", "poi_name", "poi_agency"]
    mask_missing = gages_df[cols].isnull().any(axis=1)
    missing_meta_df = gages_df.loc[mask_missing]

    if not missing_meta_df.empty:
        _list = list(set(gages_df.loc[mask_missing]["poi_gage_id"]))
        print(
            f"Gage(s) {_list} lacks metadata. Add metadata to metadata/resource_gages.csv and rerun notebook."
        )
    else:
        print("All gages have required metadata.")
        
    if resource_file_path.exists():
        if not missing_meta_df.empty:
            resource_df = pd.concat([resource_df, missing_meta_df])
        else:
            pass
    else:
        resource_df = gages_df
        resource_df.to_csv(resource_file_path, index=False)
        
    # cols = ["latitude", "longitude", "poi_name", "poi_agency"]
    # gages_missing_info_df = gages_df.loc[gages_df[cols].isna().any(axis=1)]
    # print(
    #     f"{len(gages_missing_info_df)} gages lacking metadata will be appended to the npoigages_info_supplemental.csv",
    #     "User must complete needed information and rerun this notebook.",
    # )

    # if info_supplement_path.exists():
    #     existing_resource_df = info_supplement_df.copy()
    #     gages_missing_info_df = pd.concat(
    #         [existing_resource_df, gages_missing_info_df], ignore_index=True
    #     )
    #     gages_missing_info_df.to_csv(info_supplement_path, index=False)
    # else:
    # if not gages_missing_info_df.empty:
    #     gages_missing_info_df.to_csv(info_supplement_path, index=False)
    #     print(f"Gages are missing metadata. Metadata for gages in poigages_info_supplemental.csv must be found and added to the poigages_info.csv file before continuing the workflow.")
    # else:
    #     print(
    #         "All gages in the gage list provided have all required metadata.",
    #         f"see gage meta data file at {dest_dir}/npoigages_info.csv",
    #     )

    #gages_df.to_csv(dest_dir / f"{info_file_name}.csv", index=False)

    return gages_df


def _load_nldi_cached(
    geojson_path: pl.Path,
    gpkg_path: pl.Path,
) -> "gpd.GeoDataFrame":
    """Load the NLDI gage table, regenerating the .gpkg cache when stale."""
    use_cache = (
        gpkg_path.exists()
        and geojson_path.exists()
        and gpkg_path.stat().st_mtime >= geojson_path.stat().st_mtime
    )

    if use_cache:
        gdf = gpd.read_file(gpkg_path)
        return gdf

    gdf = gpd.read_file(geojson_path)
    gdf[["poi_agency", "poi_gage_id"]] = (
        gdf["id"]
        .astype("string")
        .str.strip()
        .str.split("-", n=1, expand=True)
    )
    gdf["poi_name"] = gdf.get("name")
    gdf["latitude"] = gdf.geometry.y
    gdf["longitude"] = gdf.geometry.x

    try:
        gdf.to_file(gpkg_path, driver="GPKG")
    except OSError:
        # data_dependencies/ may be read-only on shared filesystems.
        # Fall through to in-memory result.
        pass

    return gdf


def _translate_waterdata_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map WaterData response columns to NHM's POI schema."""
    rename = {
        "monitoring_location_id": "poi_gage_id",
        "monitoring_location_name": "poi_name",
        "agency_code": "poi_agency",
    }
    translated = df.rename(columns=rename).copy()
    if "poi_gage_id" in translated.columns:
        translated["poi_gage_id"] = (
            translated["poi_gage_id"].astype(str).str.replace("USGS-", "", regex=False)
        )
        translated = translated.set_index("poi_gage_id")
    for col in ["latitude", "longitude", "poi_name", "poi_agency"]:
        if col not in translated.columns:
            translated[col] = pd.NA
    return translated[["latitude", "longitude", "poi_name", "poi_agency"]]


def create_append_gages_to_param_file_v2(
    *,
    gages_df,
    seg_gdf,
    poi_df,
    model_dir,
):
    """
    Make an editable .csv file from the gages_df, so that users can append new poigage (dimensioned) parameters to
    the myparam.param file, and returns a pandas DataFrame of the written .csv.

    First, a geopandas GeoDataFrame is made for the gages_df using the lat/lon from the gages_df (WaterData or user supplied).
    Projection is set to crs=4326 and may introduce some spatial innaccuracy for older gages.
    """
    gages_gdf = gpd.GeoDataFrame(
        gages_df,
        geometry=gpd.points_from_xy(gages_df.longitude, gages_df.latitude),
        crs=4326,
    )
    """ Gages_gdf (points_gdf) and seg_gdf (lines_gdf) projections changed for geo distance calculation. """
    _points_gdf = gages_gdf.to_crs("ESRI:102039")
    _lines_gdf = seg_gdf.to_crs("ESRI:102039")

    _poi_max_distance = 1000  # spatial units of projections, meters for ESRI:102039

    """ A spatial join for the nearest segment to a gage yields a likely candidate poi_gage_segment for each poi_gage_id 
        and the distance from the gage to the segment. """
    append_gages_to_param_file_df = gpd.sjoin_nearest(
        _points_gdf,
        _lines_gdf,
        max_distance=_poi_max_distance,
        distance_col="distance",
        how="left",
    )
    """ Cleanup """
    append_gages_to_param_file_df = append_gages_to_param_file_df[
        gages_df.columns.to_list() + ["segment_id", "distance"]
    ]
    append_gages_to_param_file_df = append_gages_to_param_file_df[
        ["segment_id", "poi_name", "poi_agency", "distance"]
    ].reset_index(drop=False)
    append_gages_to_param_file_df.rename(
        columns={"poi_gage_id": "poi_gage_id"},
        inplace=True,
    )
    """ Set an attribute "in_param_file" to show user which gages in the gages_df are in the myparam.param file. """
    append_gages_to_param_file_df["in_param_file"] = "no"
    param_file_gages = poi_df.poi_gage_id.to_list()
    append_gages_to_param_file_df.loc[
        append_gages_to_param_file_df["poi_gage_id"].isin(param_file_gages),
        "in_param_file",
    ] = "yes"

    yes_list = list(append_gages_to_param_file_df.loc[append_gages_to_param_file_df['in_param_file'] == 'yes', 'segment_id'])
    no_list = list(append_gages_to_param_file_df.loc[append_gages_to_param_file_df['in_param_file'] == 'no', 'segment_id'])
    yes_only_list = list(set(yes_list) - set(no_list))
    print(yes_only_list)

    append_gages_to_param_file_df_new = append_gages_to_param_file_df[~append_gages_to_param_file_df.segment_id.isin(yes_only_list)]
    append_gages_to_param_file_df_new.sort_values(by=['segment_id', 'in_param_file'], ascending=[True, True], inplace=True)
    """ Write new param file to the subdomain model directory. """
    append_gages_to_param_file_df_new.to_csv(
        model_dir / "append_gages_to_param_file.csv", index=False
    )


def fetch_FMI_npoigages_info(root_dir, model_dir, gages_df):
    fmi_gages_child_info_file_path = model_dir / "metadata" / "fmi_gages_info.csv"

    if fmi_gages_child_info_file_path.exists():
        col_names = [
            "poi_agency",
            "poi_gage_id",
            "storage_index",
            "use_index",
            "flow_management_index",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
        ]
        col_types = [
            np.str_,
            np.str_,
            np.int_,
            np.int_,
            np.int_,
            np.str_,
            float,
            float,
            float,
            float,
        ]
        cols = dict(
            zip(col_names, col_types)
        )  # Creates a dictionary of column header and datatype called below.

        fmi_gages_child = pd.read_csv(
            fmi_gages_child_info_file_path,
            dtype=cols,
        )
        
    else:

        #### READ FMI table (.csv) for selected gages
        fmi_df_file = root_dir / "data_dependencies" / "TableA2_FlowManagementIndex.csv"

        if not fmi_df_file.exists():
            # Neither the per-model cache nor the source FMI table is available,
            # so there are no flow-management gages to report. Mirrors the skip
            # in 2_model_hydrofabric_visualization_FMI.py rather than raising.
            print(
                f"  [SKIP] neither {fmi_gages_child_info_file_path.name} nor "
                f"{fmi_df_file.name} found for this model \u2014 skipping FMI gages."
            )
            return pd.DataFrame(
                columns=[
                    "poi_agency",
                    "poi_gage_id",
                    "storage_index",
                    "use_index",
                    "flow_management_index",
                    "poi_name",
                    "latitude",
                    "longitude",
                    "drainage_area",
                    "drainage_area_contrib",
                ]
            )
        
        cols = {"gageid": np.str_,
                "name": np.str_,
                "comid": np.int_,
                "area_mi2": float,
                "oregon": np.str_,
                "owrd_adminbasin_nbr": np.int_,
                "q0001_annual_cfs": float,
                "q0001c_jun_cfs": float,
                "q0001c_jul_cfs": float,
                "q0001c_aug_cfs": float,
                "unitq_cfsmi2": float,
                "q0001c_summer_cfs": float,
                "dams_n": np.int_,
                "pou_acres": float,
                "nonag_npixel": np.int_,
                "ag_npixel": np.int_,
                "nid_norm_storage_acft": float,
                "sw_withdrawal_acft": float,
                "ag_pct": float,
                "nid_storage_annual_pct": float,
                "sw_withdrawal_summer_pct": float,
                "sw_withdrawal_annual_pct": float,
                "storage_index": np.int_,
                "use_index": np.int_,
                "flow_management_index": np.int_,
               }
        
        # Creates a dictionary of column header and datatype called below.
        
        fmi_df = pd.read_csv(
            fmi_df_file,
            dtype=cols,
            usecols=[
                "gageid",
                "storage_index",
                "use_index",
                "flow_management_index",
            ],
        )
        fmi_gages_child = fmi_df.merge(
            gages_df, left_on="gageid", right_on="poi_gage_id", how="inner"
        )
        fmi_gages_child.drop(columns={"gageid"}, inplace=True)
        
        print(f"There are {len(fmi_gages_child)} Flow Management Gages in the model domain.")
        
        fmi_gages_child.to_csv(fmi_gages_child_info_file_path, index=False)
    
    return fmi_gages_child


def fetch_non_ref_npoigages_info(root_dir, model_dir, hru_gdf):

    non_ref_npoigages_info_file_path = model_dir / "metadata" / "non_ref_npoigages_info.csv"

    if non_ref_npoigages_info_file_path.exists():
        col_names = [
            "poi_agency",
            "poi_gage_id",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
        ]
        col_types = [
            np.str_,
            np.str_,
            np.str_,
            float,
            float,
            float,
            float,
        ]
        cols = dict(
            zip(col_names, col_types)
        )  # Creates a dictionary of column header and datatype called below.

        df_clipped = pd.read_csv(
            non_ref_npoigages_info_file_path,
            dtype=cols,
            usecols=[
                "poi_agency",
                "poi_gage_id",
                "poi_name",
                "latitude",
                "longitude",
                "drainage_area",
                "drainage_area_contrib",
            ],
        )

        # Make a geodataframe from the info df
        gdf_clipped= gpd.GeoDataFrame(
            df_clipped,
            geometry=gpd.points_from_xy(
                df_clipped["longitude"],
                df_clipped["latitude"],
            ),
            crs="EPSG:4326",  # WGS84 lat/lon
        )
        
    else:
        # list your three directories here (relative or absolute)
        dirs = [
            root_dir / "data_dependencies" / "non_ref_gages" / "region17",
            root_dir / "data_dependencies" / "non_ref_gages" / "region16",
            root_dir / "data_dependencies" / "non_ref_gages" / "region18",
        ]
    
        # collect all matching files from the three directories
        files = []
        for d in dirs:
            # adjust pattern if needed, e.g. "*.txt" or "output_*.txt"
            files.extend(glob.glob(os.path.join(d, "output_*.txt")))
    
        # extract the numeric part after "_" and before ".txt"
        monitoring_station_number_list = []
        for f in files:
            base = os.path.basename(f)  # e.g. "output_10396000.txt"
            num_str = base.split("_")[1].split(".")[0]  # "10396000"
            monitoring_station_number_list.append(
                (num_str)
            )  # or keep as string if you prefer
    
        all_non_ref_npoigages_info = find_missing_gage_info(
            root_dir,
            root_dir / "data_dependencies" / "non_ref_gages",
            monitoring_station_number_list,
            root_dir / "hydrofabric_domain_data/OHM_2026_02_21/npoigages_data/resource_gages.csv",
        )
    
        # Make a geodataframe from the info df
        gdf = gpd.GeoDataFrame(
            all_non_ref_npoigages_info,
            geometry=gpd.points_from_xy(
                all_non_ref_npoigages_info["longitude"],
                all_non_ref_npoigages_info["latitude"],
            ),
            crs="EPSG:4326",  # WGS84 lat/lon
        )
    
        # make sure CRS is projected (meters/feet) to add buffer distances in real units
        hru_proj = hru_gdf.to_crs("EPSG:3857")  # example projected CRS
        gdf_proj = gdf.to_crs(hru_proj.crs)
    
        # create a buffer around the mask, 1000 meters, to get gages that may be downstream from outlet segments
        hru_buffered = hru_proj.buffer(1000)
    
        # clip using the buffered mask to the model domain
        gdf_clipped = gpd.clip(gdf_proj, hru_buffered)
    
        # (optional) go back to original CRS and drop the "geometry" column
        gdf_clipped = gdf_clipped.to_crs(hru_gdf.crs)
        gdf_clipped.drop(columns={"geometry"}, inplace=True)
    
        non_ref_npoigages_info_file_path = model_dir / "metadata" / "non_ref_npoigages_info.csv"
        gdf_clipped.to_csv(non_ref_npoigages_info_file_path, index=False)

    return gdf_clipped


def fetch_ref_npoigages_info(root_dir, model_dir, hru_gdf):
    #Consider (Eddie) instead of using hru_gdf, just using a merge with the npoi_gages

    ref_npoigages_info_file_path = model_dir / "metadata" / "ref_npoigages_info.csv"

    if ref_npoigages_info_file_path.exists():
        col_names = [
            "poi_agency",
            "poi_gage_id",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
        ]
        col_types = [
            np.str_,
            np.str_,
            np.str_,
            float,
            float,
            float,
            float,
        ]
        cols = dict(
            zip(col_names, col_types)
        )  # Creates a dictionary of column header and datatype called below.

        df_clipped = pd.read_csv(
            ref_npoigages_info_file_path,
            dtype=cols,
            usecols=[
                "poi_agency",
                "poi_gage_id",
                "poi_name",
                "latitude",
                "longitude",
                "drainage_area",
                "drainage_area_contrib",
            ],
        )

        # Make a geodataframe from the info df
        gdf_clipped= gpd.GeoDataFrame(
            df_clipped,
            geometry=gpd.points_from_xy(
                df_clipped["longitude"],
                df_clipped["latitude"],
            ),
            crs="EPSG:4326",  # WGS84 lat/lon
        )
    else:
        
        # list your three directories here (relative or absolute)
        dirs = [
            root_dir / "data_dependencies" / "ref_gages" / "region17",
            root_dir / "data_dependencies" / "ref_gages" / "region16",
            root_dir / "data_dependencies" / "ref_gages" / "region18",
        ]
    
        # collect all matching files from the three directories
        files = []
        for d in dirs:
            # adjust pattern if needed, e.g. "*.txt" or "output_*.txt"
            files.extend(glob.glob(os.path.join(d, "output_*.txt")))
    
        # extract the numeric part after "_" and before ".txt"
        monitoring_station_number_list = []
        for f in files:
            base = os.path.basename(f)  # e.g. "output_10396000.txt"
            num_str = base.split("_")[1].split(".")[0]  # "10396000"
            monitoring_station_number_list.append(
                (num_str)
            )  # or keep as string if you prefer
    
        all_ref_npoigages_info = find_missing_gage_info(
            root_dir,
            root_dir / "data_dependencies" / "ref_gages",
            monitoring_station_number_list,
            root_dir / "hydrofabric_domain_data/OHM_2026_02_21/npoigages_data/resource_gages.csv",
        )
    
        # Make a geodataframe from the info df
        gdf = gpd.GeoDataFrame(
            all_ref_npoigages_info,
            geometry=gpd.points_from_xy(
                all_ref_npoigages_info["longitude"], all_ref_npoigages_info["latitude"]
            ),
            crs="EPSG:4326",  # WGS84 lat/lon
        )
    
        # make sure CRS is projected (meters/feet) to add buffer distances in real units
        hru_proj = hru_gdf.to_crs("EPSG:3857")  # example projected CRS
        gdf_proj = gdf.to_crs(hru_proj.crs)
    
        # create a buffer around hru_gdf (domain), 1000 meters, to get gages that intersect domain
        # note: in the future, we may want to just use the seg_gdf for this to exclude gages in the domain not on the flow network
        hru_buffered = hru_proj.buffer(1000)
    
        # clip using the buffered mask to the model domain
        gdf_clipped = gpd.clip(gdf_proj, hru_buffered)
    
        # (optional) go back to original CRS and drop the "geometry" column
        gdf_clipped = gdf_clipped.to_crs(hru_gdf.crs)
        gdf_clipped.drop(columns={"geometry"}, inplace=True)
    
        ref_npoigages_info_file_path = model_dir / "metadata" / "ref_npoigages_info.csv"
        gdf_clipped.to_csv(ref_npoigages_info_file_path, index=False)

    return gdf_clipped


def fetch_waterdata_gage_info(
    *,
    root_dir,
    model_dir,
    control_file_name,
    waterdata_gage_nobs_min,
    hru_gdf,
    seg_gdf,
):
    """
    This function creates a pandas DataFrame of information for all gages in the model domain that
    are in USGS WaterData database that have mean daily discharge data from the start date to the end date listed in the control file,
    and that are within 1 kilometer of the provided stream network.

    Parameters
    ----------
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    control_file_name : pathlib Path class
        Path object to the control file.
    waterdata_gage_nobs_min : int
        Minimum number of days for waterdata gage to be considered as potential poi.
    hru_gdf : geopandas GeoDataFrame()
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    seg_gdf : geopandas GeoDataFrame()
        segments geopandas.GeoDataFrame() from GIS data in subdomain.

    Returns
    -------
    waterdata_gage_info_aoi : pandas DataFrame()
        DataFrame containing gage information for gages found in waterdata.
    """

    waterdata_gages_file = model_dir / "metadata/WaterDataGages.csv"
    control = pws.Control.load_prms(
        pl.Path(model_dir / control_file_name, warn_unused_options=False)
    )

    """
    Projections are ascribed geometry from the HRUs geodatabase (GIS).
    The NHM uses the NAD 1983 USGS Contiguous USA Albers projection EPSG# 102039.
    The geometry units of this projection are not useful for many notebook packages.
    The geodatabases are reprojected to World Geodetic System 1984.

    Options:
        crs = 3857, WGS 84 / Pseudo-Mercator - Spherical Mercator, Google Maps, OpenStreetMap, Bing, ArcGIS, ESRI.
        *crs = 4326, WGS 84 - WGS84 - World Geodetic System 1984, used in GPS
    """
    crs = 4326

    # Make a list of the state abbreviations the subdomain intersects for waterdata queries
    aoi_bb = hru_gdf.total_bounds.tolist()

    """
    Use caution if start and end dates may be modified here. 
    If gages are present in the param file, recommend adding metadata in the gage_resource.csv
    """

    st_date = "1900-01-01"# pd.to_datetime(str(control.start_time)).strftime("%Y-%m-%d")
    en_date = pd.to_datetime(str(control.end_time)).strftime("%Y-%m-%d")

    if waterdata_gages_file.exists():
        col_names = [
            "poi_agency",
            "poi_gage_id",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
        ]
        col_types = [
            np.str_,
            np.str_,
            np.str_,
            float,
            float,
            float,
            float,
        ]
        cols = dict(
            zip(col_names, col_types)
        )  # Creates a dictionary of column header and datatype called below.

        waterdata_gage_info_aoi = pd.read_csv(
            waterdata_gages_file,
            dtype=cols,
            usecols=[
                "poi_agency",
                "poi_gage_id",
                "poi_name",
                "latitude",
                "longitude",
                "drainage_area",
                "drainage_area_contrib",
            ],
        )
    else:
        domain_discharge, _ = waterdata.get_time_series_metadata(
            bbox=aoi_bb,
            parameter_code="00060",
            statistic_id="00003",
            begin=f"../{en_date}",
            end=f"{st_date}/..",
        )

        """Drop gages that are more than 1000m from a NHM segment
        """

        # DataFrames
        #print(domain_discharge.crs)
        points_gdf = domain_discharge.set_crs("EPSG:4326").to_crs(crs=3857)
        lines_gdf = seg_gdf.to_crs(crs=3857)  # change proj to get practical linear unit

        # Step 1: Calculate minimum distance from each point to the nearest line
        def nearest_line_distance(point):
            return lines_gdf.geometry.distance(point).min()

        # Apply the distance calculation to points
        points_gdf["distance_to_line"] = points_gdf.geometry.apply(
            nearest_line_distance
        )

        # Step 2: Filter points that are within 1000 meters of the nearest line
        filtered_points_gdf = points_gdf[points_gdf["distance_to_line"] <= 1000]

        # Drop the distance column if no longer needed
        filtered_points_gdf = filtered_points_gdf.drop(columns="distance_to_line")
        
        domain_discharge = filtered_points_gdf.copy().to_crs(crs)

        """Now, get the site infomation for the new list
            used the chunk format from the example: 
            https://github.com/DOI-USGS/dataretrieval-python/blob/dc9b614f646b2656c17acc77c0161762053afaf6/demos/WaterData_demo.ipynb
        """
        chunk_size = 100
        site_list = domain_discharge["monitoring_location_id"].unique().tolist()
        chunks = [
            site_list[i : i + chunk_size] for i in range(0, len(site_list), chunk_size)
        ]
        domain_locations = pd.DataFrame()
        for site_group in chunks:
            try:
                chunk_data, _ = waterdata.get_monitoring_locations(
                    monitoring_location_id=site_group,
                    site_type_code="ST",
                    properties=[
                        "monitoring_location_id",
                        "geometry",
                        "agency_code",
                        "agency_name",
                        "monitoring_location_number",
                        "monitoring_location_name",
                        "state_name",
                        "drainage_area",
                        "contributing_drainage_area",
                    ],
                )
                if not chunk_data.empty:
                    domain_locations = pd.concat([domain_locations, chunk_data])
            except Exception as e:
                print(f"Chunk failed: {e}")

        domain_locations["latitude"] = (
            domain_locations.geometry.y
        )  # need this for the notebooks
        domain_locations["longitude"] = (
            domain_locations.geometry.x
        )  # need this for the notebooks

        waterdata_gage_info_aoi = (
            domain_locations.set_index("monitoring_location_number", drop=False)
            .set_crs("EPSG:4326")
            .to_crs(crs)
        )

        field_map = {
            "agency_code": "poi_agency",
            "monitoring_location_number": "poi_gage_id",
            "monitoring_location_name": "poi_name",
            "latitude": "latitude",
            "longitude": "longitude",
            "drainage_area": "drainage_area",
            "contributing_drainage_area": "drainage_area_contrib",
        }
        include_cols = list(field_map.keys())

        waterdata_gage_info_aoi = waterdata_gage_info_aoi.loc[:, include_cols]
        waterdata_gage_info_aoi.rename(columns=field_map, inplace=True)
        waterdata_gage_info_aoi.set_index("poi_gage_id", inplace=True)
        waterdata_gage_info_aoi = waterdata_gage_info_aoi.sort_index()
        waterdata_gage_info_aoi.reset_index(inplace=True)



    return waterdata_gage_info_aoi


def make_HW_cal_level_files(hru_gdf):
    """
    Creates a DataFrame that assigns NHM calibration levels (1 : byHRU, 2 : byHW or 3 : byHWobs), and a polyline file to plot boundaries of HWs and includes HW information.

    Parameters
    ----------
    hru_gdf : geopandas GeoDataFrame()
        HRU geopandas.GeoDataFrame() from GIS data in subdomain. 
            
    Returns
    -------
    HW_basins_gdf : geopandas GeoDataFrame
        NHM headwaters basins geopandas GeoDataFrame used to display caliration level of HRUs on map.
    HW_basins : geopandas polyline dataset
        Polyline file that was made using HW_basins_gdf.boundary
    """
    
    crs = 4326
    byHW_basins_gdf = hru_gdf.loc[hru_gdf["byHW"] == 1]
    HW_basins_gdf = byHW_basins_gdf.dissolve(by="hw_id").to_crs(crs)
    HW_basins_gdf.reset_index(inplace=True, drop=False)
    HW_basins = HW_basins_gdf.boundary

    return HW_basins_gdf, HW_basins
