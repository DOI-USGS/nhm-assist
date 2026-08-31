"""Shared assist utilities for the nhm and nhf workflows.

Unified from src/assist/nhm/nhm_assist_utilities.py and
src/assist/nhf/nhm_assist_utilities_v2.py. See
docs/superpowers/specs/2026-08-30-helper-unification-design.md.
"""
from __future__ import annotations

import os
import pathlib as pl

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly
import plotly.express as px
import yaml
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

# All 14 keys both baselines wrapped in pl.Path(). Omitting any of these leaves a
# raw str in the config, and consumers doing `config["out_dir"] / "x.nc"` raise
# TypeError. Verified against both baselines at 27f7144.
_PATH_KEYS = (
    "Folium_maps_dir",
    "model_dir",
    "param_filename",
    "gages_file",
    "default_gages_file",
    "output_netcdf_filename",
    "waterdata_gages_file",
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

    # Fold the retired NWIS key names onto their WaterData equivalents.
    for old_key, new_key in CONFIG_KEY_ALIASES.items():
        if old_key in raw and new_key not in raw:
            raw[new_key] = raw.pop(old_key)

    config: dict = dict(raw)
    for key in _PATH_KEYS:
        value = raw.get(key)
        config[key] = pl.Path(value) if value is not None else None

    config.setdefault("resource_gages_file", None)
    return config


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
