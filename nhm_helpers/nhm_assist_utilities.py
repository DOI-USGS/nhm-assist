import pathlib as pl
import warnings
import dataretrieval.nwis as nwis
from dataretrieval import waterdata
import geopandas as gpd
import numpy as np
import os
import pandas as pd
import plotly
import plotly.express as px
import plotly.subplots
# from contextlib import redirect_stdout
# import io
# f = io.StringIO()
# with redirect_stdout(f):
import pywatershed as pws
from shapely.geometry import Point, LineString
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
from rich import pretty
from rich.console import Console
import glob
from nhm_helpers.nhm_helpers import hrus_by_poi
import yaml

pretty.install()
con = Console()

warnings.filterwarnings("ignore")

# List of bynhru parameters to retrieve for the Notebook interactive maps.
hru_params = [
    "hru_lat",  # the latitude if the hru centroid
    "hru_lon",  # the longitude if the hru centroid
    "hru_area",
    "hru_segment_nhm",  # The nhm_id of the segment recieving flow from the HRU
]


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


# Reads/Creates NWIS stations file if not already created
def fetch_nwis_gage_info(
    *,
    root_dir,
    model_dir,
    control_file_name,
    nwis_gage_nobs_min,
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
    nwis_gage_nobs_min : int
        Minimum number of days for NWIS gage to be considered as potential poi.
    hru_gdf : geopandas GeoDataFrame()
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    seg_gdf : geopandas GeoDataFrame()
        segments geopandas.GeoDataFrame() from GIS data in subdomain.

    Returns
    -------
    nwis_gage_info_aoi : pandas DataFrame()
        DataFrame containing gage information for gages found in NWIS.
    """

    nwis_gages_file = model_dir / "NWISgages.csv"
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

    # Make a list of the state abbreviations the subdomain intersects for NWIS queries
    states_gdf = gpd.read_file(
        root_dir / "data_dependencies/US_states/tl_2017_us_state.shp"
    ).to_crs(crs)
    states_name = list(gpd.clip(states_gdf, hru_gdf).loc[:]["NAME"].values)

    """
    Use caution if start and end dates may be modified here. 
    If gages are present in the param file, recommend adding metadata in the gage_resource.csv
    """

    st_date = "1900-01-01"# pd.to_datetime(str(control.start_time)).strftime("%Y-%m-%d")
    en_date = pd.to_datetime(str(control.end_time)).strftime("%Y-%m-%d")

    if nwis_gages_file.exists():
        col_names = [
            "poi_agency",
            "poi_id",
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

        nwis_gage_info_aoi = pd.read_csv(
            nwis_gages_file,
            dtype=cols,
            usecols=[
                "poi_agency",
                "poi_id",
                "poi_name",
                "latitude",
                "longitude",
                "drainage_area",
                "drainage_area_contrib",
            ],
        )
    else:
        aoi_bb = hru_gdf.total_bounds
        domain_discharge, _ = waterdata.get_time_series_metadata(
            # state_name=states_name,
            bbox = aoi_bb.tolist(),
            parameter_code="00060",
            statistic_id="00003",
            # begin=f"../{en_date}",
            # end=f"{st_date}/..",
        )

        """Drop gages that are more than 1000m from a NHM segment
        """

        # DataFrames
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
                    site_type_code=["ST", "ST-TS"], # may need to specify more streamflow site types here??
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

        nwis_gage_info_aoi = (
            domain_locations.set_index("monitoring_location_number", drop=False)
            .set_crs("EPSG:4326")
            .to_crs(crs)
        )

        field_map = {
            "agency_code": "poi_agency",
            "monitoring_location_number": "poi_id",
            "monitoring_location_name": "poi_name",
            "latitude": "latitude",
            "longitude": "longitude",
            "drainage_area": "drainage_area",
            "contributing_drainage_area": "drainage_area_contrib",
        }
        include_cols = list(field_map.keys())

        nwis_gage_info_aoi = nwis_gage_info_aoi.loc[:, include_cols]
        nwis_gage_info_aoi.rename(columns=field_map, inplace=True)
        nwis_gage_info_aoi.set_index("poi_id", inplace=True)
        nwis_gage_info_aoi = nwis_gage_info_aoi.sort_index()
        nwis_gage_info_aoi.reset_index(inplace=True)

    return nwis_gage_info_aoi


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
    poi_list = poi_df["poi_id"].values.tolist()

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

            for idx, poi_id in enumerate(poi_list):
                par_plot_file = Folium_maps_dir / f"{par}_{poi_id}.txt"
                if par_plot_file.exists():
                    pass
                    # print(
                    #     f"{par}_{poi_id}.txt exists. To recreate the plot, remove the file from Folium_maps_dir"
                    # )
                    # print(par_plot_file)
                else:

                    ##%%time = par
                    # Preporcessing: pulling only the selected param values for the HRUs related to the selected POI to plot.
                    output_var_sel_plot_df = hru_gdf[
                        hru_gdf["nhm_id"].astype(int).isin(hru_poi_dict[poi_id])
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
                            text=f"{par} for HRUs in {poi_id} catchment",
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
                    with open(Folium_maps_dir / f"{par}_{poi_id}.txt", "w") as f:
                        f.write(text_div)

                    # fig.show()

        else:
            # print(f"Checking for {par} dimensioned by nhru and nmonths")

            for idx, poi_id in enumerate(poi_list):

                par_plot_file = Folium_maps_dir / f"{par}_{poi_id}.txt"
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
                        nhru_params_nmonths_sel_df["nhm_id"].isin(hru_poi_dict[poi_id])
                    ]
                    # nhru_params_nmonths_sel_plot_df = nhru_params_nmonths_sel_df[nhru_params_nmonths_sel_df['poi_group'] == poi_id]

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
                        title_text=f"{par} for HRUs in {poi_id} catchment",
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
                    with open(Folium_maps_dir / f"{par}_{poi_id}.txt", "w") as f:
                        f.write(text_div)


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

def make_obs_plot_files(*, start_date, end_date, gages_df, xr_streamflow, Folium_maps_dir):
    """This function makes plots and saved with as html.txt files to be embedded in the hf_map
    by notebook 2_model_hydrofabric_visualization.ipynb used to evaluate ti gages shown in the
    map have desirable lengths of record to include the gage as a poi in the parameter file.
    """

    # start_date = pd.to_datetime(str(control.start_time)).strftime("%m/%d/%Y")
    # end_date = pd.to_datetime(str(control.end_time)).strftime("%m/%d/%Y")

    for cpoi in gages_df.index:
        obs_plot_file = Folium_maps_dir / f"{cpoi}_streamflow_obs.txt"
        if obs_plot_file.exists():
            con.print(
                f"{cpoi}_streamflow_obs.txt file exists. To make a new plot, delete the existing plot and rerun this cell."
            )
        else:
            ds_sub = xr_streamflow.sel(poi_id=cpoi, time=slice(start_date, end_date))
            ds_sub_df = ds_sub.to_dataframe()
            # ds_sub_df.dropna(subset=["discharge"], inplace=True)
            ds_sub_df.reset_index(inplace=True, drop=False)
            # print(ds_sub_df)

            fig = px.line(
                ds_sub_df,
                x="time",
                y="discharge",
                markers=False,
                # custom_data=nhru_params_nmonths_sel_plot_df[["nhm_id"]],
                # color="nhm_id",
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
                # legend=dict(orientation="h",yanchor="bottom",y=1.02, xanchor="right", x=1),
                font=dict(family="Arial", size=10, color="#7f7f7f"),  # font color
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

            # fig.show()

            # Creating the html code for the plotly plot
            text_div = plotly.offline.plot(
                fig, include_plotlyjs=False, output_type="div"
            )

            # Saving the plot as txt file with the html code
            with open(obs_plot_file, "w") as f:
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
    append_gages_to_param_file_df.rename(
        columns={"poi_id": "poi_gage_id"},
        inplace=True,
    )
    """ Set an attribute "in_param_file" to show user which gages in the gages_df are in the myparam.param file. """
    append_gages_to_param_file_df["in_param_file"] = "no"
    param_file_gages = poi_df.poi_id.to_list()
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

def delete_notebook_output_files(
    *,
    notebook_output_dir,
    model_dir,
):
    """ """

    subfolders = ['Folium_maps', 'html_maps', 'html_plots', 'nc_files']
    for subfolder in subfolders:
        folder_path = notebook_output_dir / subfolder   
        for file_name in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file_name)
            if os.path.isfile(file_path):  # Ensure it's a file
                os.remove(file_path)
                print(f"Deleted: {file_path}")

        
        # path = r"{notebook_output_dir}\{subfolder}"
        # files = glob.glob(path)
        # for f in files:
        #     os.remove(f)
    
    files =['default_gages.csv', 'NWISgages.csv', 'append_gages_to_param_file.csv', 'default_gages_file.csv']
    for file in files:
        if (model_dir / file).exists():
            os.remove(model_dir / file)
    return

# def load_subdomain_config(root_dir):
#     """ """
#     with open(root_dir / "subdomain_config.yaml") as file:
#         pp = yaml.load(file, Loader=yaml.FullLoader)

#     Folium_maps_dir = pl.Path(pp["Folium_maps_dir"])
#     model_dir = pl.Path(pp["model_dir"])
#     param_filename = pl.Path(pp["param_filename"])
#     gages_file = pl.Path(pp["gages_file"])
#     default_gages_file = pl.Path(pp["default_gages_file"])
#     nwis_gages_file = pl.Path(pp["nwis_gages_file"])
#     output_netcdf_filename = pl.Path(pp["output_netcdf_filename"])
#     NHM_dir = pl.Path(pp["NHM_dir"])
#     out_dir = pl.Path(pp["out_dir"])
#     notebook_output_dir = pl.Path(pp["notebook_output_dir"])
#     Folium_maps_dir = pl.Path(pp["Folium_maps_dir"])
#     html_maps_dir = pl.Path(pp["html_maps_dir"])
#     html_plots_dir = pl.Path(pp["html_plots_dir"])
#     nc_files_dir = pl.Path(pp["nc_files_dir"])
#     subdomain = pp["subdomain"]
#     GIS_format = pp["GIS_format"]
#     param_file = pp["param_file"]
#     control_file_name = pp["control_file_name"]
#     nwis_gage_nobs_min = pp["nwis_gage_nobs_min"]
#     nhru_nmonths_params = pp["nhru_nmonths_params"]
#     nhru_params = pp["nhru_params"]
#     selected_output_variables = pp["selected_output_variables"]
#     water_years = pp["water_years"]
#     workspace_txt = pp["workspace_txt"]

#     return (
#         Folium_maps_dir,
#         model_dir,
#         param_filename,
#         gages_file,
#         default_gages_file,
#         nwis_gages_file,
#         output_netcdf_filename,
#         NHM_dir,
#         out_dir,
#         notebook_output_dir,
#         Folium_maps_dir,
#         html_maps_dir,
#         html_plots_dir,
#         nc_files_dir,
#         subdomain,
#         GIS_format,
#         param_file,
#         control_file_name,
#         nwis_gage_nobs_min,
#         nhru_nmonths_params,
#         nhru_params,
#         selected_output_variables,
#         water_years,
#         workspace_txt,
#     )

def load_subdomain_config(root_dir):
    """Loads subdomain config and returns a dictionary of processed keys/values."""
    with open(root_dir / "subdomain_config.yaml") as file:
        pp = yaml.load(file, Loader=yaml.FullLoader)

    # Map YAML keys to their processed Python values
    config = {
        "Folium_maps_dir": pl.Path(pp["Folium_maps_dir"]),
        "model_dir": pl.Path(pp["model_dir"]),
        "param_filename": pl.Path(pp["param_filename"]),
        "gages_file": pl.Path(pp["gages_file"]),
        "default_gages_file": pl.Path(pp["default_gages_file"]),
        "nwis_gages_file": pl.Path(pp["nwis_gages_file"]),
        "output_netcdf_filename": pl.Path(pp["output_netcdf_filename"]),
        "NHM_dir": pl.Path(pp["NHM_dir"]),
        "out_dir": pl.Path(pp["out_dir"]),
        "notebook_output_dir": pl.Path(pp["notebook_output_dir"]),
        "html_maps_dir": pl.Path(pp["html_maps_dir"]),
        "html_plots_dir": pl.Path(pp["html_plots_dir"]),
        "nc_files_dir": pl.Path(pp["nc_files_dir"]),
        "subdomain": pp["subdomain"],
        "GIS_format": pp["GIS_format"],
        "param_file": pp["param_file"],
        "control_file_name": pp["control_file_name"],
        "nwis_gage_nobs_min": pp["nwis_gage_nobs_min"],
        "nhru_nmonths_params": pp["nhru_nmonths_params"],
        "nhru_params": pp["nhru_params"],
        "selected_output_variables": pp["selected_output_variables"],
        "water_years": pp["water_years"],
        "start_date" : pd.to_datetime(pp["start_date"]).strftime("%m/%d/%Y"),
        "end_date" : pd.to_datetime(pp["end_date"]).strftime("%m/%d/%Y"),
        "workspace_txt": pp["workspace_txt"],
    }
    return config
