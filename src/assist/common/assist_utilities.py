"""Shared assist utilities for the nhm and nhf workflows.

Unified from src/assist/nhm/nhm_assist_utilities.py and
src/assist/nhf/nhm_assist_utilities_v2.py. See
docs/superpowers/specs/2026-08-30-helper-unification-design.md.
"""

import os
import pathlib as pl

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly
import plotly.express as px
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

    if not missing_meta_df.empty:
        """
        First, Check the NLDI json for missing data in the dependencies folder.
        These data are said to have the most acurate location information, so stop there first.
        """
        print(f"{len(missing_meta_df)} gages missing metadata. Searching NLDI database.")
        ##### Check NLDI database for missing gage info
        file_path = npoigages_data_dir / "usgs_nldi_gages.geojson"
        nldi_gdf = gpd.read_file(file_path)  # or .geojson
    
        # Split on the first '-' and create new columns
        nldi_gdf[["poi_agency", "poi_gage_id"]] = (
            nldi_gdf["id"]
            .astype("string")  # keeps NaN as <NA>
            .str.strip()
            .str.split("-", n=1, expand=True)  # split on the first dash only
        )
        nldi_gdf.to_file(
            npoigages_data_dir / "usgs_nldi_gages.gpkg",
            driver="GPKG",
        )
    
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


def _find_missing_gage_metadata(
    *,
    gage_ids: list[str],
    poi_df: pd.DataFrame,
    resource_file_path: pl.Path,
    root_dir: pl.Path,
    nldi_geojson_path: pl.Path | None = None,
) -> pd.DataFrame:
    """Look up metadata for gages missing from the resource file.

    Returns a DataFrame indexed by poi_gage_id with columns latitude, longitude,
    poi_name, poi_agency. Queries NLDI (local geojson) and WaterData
    (network) only for gages not already covered.

    Network failures log a warning and return whatever was successfully
    fetched; the caller is responsible for any rows still missing metadata.
    """
    METADATA_COLS = ["latitude", "longitude", "poi_name", "poi_agency"]
    empty = pd.DataFrame(columns=METADATA_COLS)
    empty.index.name = "poi_gage_id"
    if not gage_ids:
        return empty

    pending = list(dict.fromkeys(gage_ids))

    if resource_file_path.exists():
        try:
            resource_df = pd.read_csv(
                resource_file_path,
                dtype={"poi_gage_id": str},
            )
        except (FileNotFoundError, pd.errors.EmptyDataError):
            resource_df = None
        if resource_df is not None and "poi_gage_id" in resource_df.columns:
            covered = set(resource_df["poi_gage_id"].astype(str).tolist())
            pending = [g for g in pending if g not in covered]

    if not pending:
        return empty

    if nldi_geojson_path is None:
        nldi_geojson_path = (
            root_dir / "data_dependencies" / "usgs_nldi_gages.geojson"
        )
    nldi_gpkg_path = nldi_geojson_path.with_suffix(".gpkg")

    found_frames: list[pd.DataFrame] = []

    try:
        nldi_gdf = _load_nldi_cached(nldi_geojson_path, nldi_gpkg_path)
        nldi_lookup = (
            nldi_gdf.set_index("poi_gage_id")[METADATA_COLS]
            if "poi_gage_id" in nldi_gdf.columns
            else pd.DataFrame(columns=METADATA_COLS)
        )
        hits = [g for g in pending if g in nldi_lookup.index]
        if hits:
            found_frames.append(nldi_lookup.loc[hits])
            pending = [g for g in pending if g not in nldi_lookup.index]
    except Exception as exc:
        # non-fatal: NLDI may be unavailable on air-gapped deployments
        print(
            f"WARNING: could not reach NLDI ({exc}); "
            f"{len(pending)} gages may lack metadata."
        )

    if pending:
        try:
            chunk_size = 100
            wd_frames = []
            for i in range(0, len(pending), chunk_size):
                chunk_ids = pending[i : i + chunk_size]
                location_ids = [f"USGS-{g}" for g in chunk_ids]
                wd_df, _ = waterdata.get_monitoring_locations(
                    monitoring_location_id=location_ids,
                )
                if wd_df is not None and not wd_df.empty:
                    wd_frames.append(wd_df)
            if wd_frames:
                combined = pd.concat(wd_frames, ignore_index=True)
                translated = _translate_waterdata_columns(combined)
                hits = [g for g in pending if g in translated.index]
                if hits:
                    found_frames.append(translated.loc[hits])
        except Exception as exc:
            # non-fatal: WaterData may be unavailable
            print(
                f"WARNING: could not reach WaterData ({exc}); "
                f"{len(pending)} gages may lack metadata."
            )

    return pd.concat(found_frames) if found_frames else empty
