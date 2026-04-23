import warnings
import base64
import pathlib as pl
import branca.colormap as cm
import folium
import jupyter_black
import matplotlib as mplib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from folium import plugins
from folium.features import DivIcon
from folium.plugins import FloatImage, MarkerCluster, MeasureControl
from folium.utilities import Element
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
from rich import pretty
from rich.console import Console
from nhm_helpers.nhm_output_visualization import (
    create_streamflow_obs_datasets, create_sum_seg_var_dataarrays,
    create_sum_var_annual_gdf)
from nhm_helpers.output_plots import calculate_monthly_kge_in_poi_df
import subprocess
import os
import webbrowser

pretty.install()
con = Console()
jupyter_black.load()
warnings.filterwarnings("ignore")

crs = 4326

import pathlib as pl
import os
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")

admin_basin_style = lambda x: {
    "fillColor": "#00000000",
    #'fill_opacity' : .8,
    "color": "black",
    "weight": 2,
}

transparent = lambda x: {
    "fillColor": "#00000000",
    "color": "#00000000",
    "weight": 4,
}

style_function_hru_map = lambda x: {
    "opacity": 1,
    "fillColor": "#00000000",  #'goldenrod',
    "color": "black",
    "weight": 0.25,
}
highlight_function_hru_map = lambda x: {
    "opacity": 0.5,
    "color": "gray",
    "fillColor": "gray",
    "weight": 3,
}

cal_style_function = lambda feature: {
    "fillColor": (
        "gray"
        if feature["properties"]["level"] == 1
        else "yellow" if feature["properties"]["level"] == 2 else "green"
    ),
    "color": "#00000000",
    "weight": 1.5,
    # "dashArray": "5, 5",
}

hw_basin_style = lambda x: {
    "fillColor": "#00000000",
    #'fill_opacity' : .8,
    "color": "brown",
    "weight": 1.5,
    # "dashArray": "5, 5",
}

popup_hru = folium.GeoJsonPopup(
    fields=["nhm_id", "hru_segment_nhm"],
    aliases=["nhm_id", " flows to segment"],
    labels=True,
    localize=False,
    style=(
        "font-size: 16px;"
    ),  # Note that this tooltip style sets the style for all tool_tips.
    # background-color: #F0EFEF;border: 2px solid black;font-family: arial; padding: 10px; background-color: #F0EFEF;
)

tooltip_hru = folium.GeoJsonTooltip(
    fields=["nhm_id", "hru_segment_nhm"],
    aliases=["nhm_id", " flows to segment"],
    labels=True,
    # style=("background-color: #F0EFEF;border: 2px solid black;font-family: arial; font-size: 16px; padding: 10px;"),# Note that this tooltip style sets the style for all tool_tips.
)

style_function_seg_map = lambda x: {
    "opacity": 1,
    "color": "#217de7",
    "weight": 2,
}

highlight_function_seg_map = lambda x: {
    "opacity": 0.5,
    "color": "black",
    "weight": 3,
}

popup_seg = folium.GeoJsonPopup(
    fields=["nhm_seg", "tosegment_nhm"],
    aliases=["segment", "flows to segment"],
    labels=True,
    localize=False,
)

tooltip_seg = folium.GeoJsonTooltip(
    fields=["nhm_seg", "tosegment_nhm"],
    aliases=["segment", "flows to segment"],
    labels=True,
)

def is_wsl():
    """
    Check if the code is running in Windows Subsystem for Linux (WSL).

    Returns
    -------
    bool
        True if running in WSL, False otherwise.
    """

    try:
        with open('/proc/version', 'r') as f:
            return 'microsoft' in f.read().lower()
    except FileNotFoundError:
        return False

def make_webbrowser_map(map_file):
    """
    Open a map file in a web browser.
    
    If running in Nebari, print the URL to open the map.
    If running in WSL, convert the path to a Windows path before opening it.

    Parameters
    ----------
    map_file : str or pathlib.Path
        Path to the map file to be opened.

    Returns
    -------
    None
        This function does not return anything.
    """

    # create string of map file path
    map_file_str = f"{map_file}"
    
    # if running in Nebari, print url to open map, else use webbrowser to have map popup directly
    if "NEBARI_CONDA_STORE_SERVER_SERVICE_HOST" in os.environ:
        full_url = (
            f"https://nebari.chs.usgs.gov/user/{os.environ['JUPYTERHUB_USER']}/files/"
            + map_file_str
        )
    
        print(f"Open your map: {full_url}")
    # otherwise, use mapbrowser to open file
    else:
        # if working in WSL, you have to convert the path for it to work
        if is_wsl():
            # Convert to Windows path
            windows_path = (
                subprocess.check_output(["wslpath", "-w", map_file_str]).decode().strip()
            )
            map_file_str = f"file:///{windows_path}"
        webbrowser.open(map_file_str, new=2)


def folium_map_elements(hru_gdf, poi_df, poi_id_sel):
    """
    Set approximate latitude, longitude and zoom level for subdomain is calculated for starting point of folium.map plot window.

    Parameters
    ----------
    hru_gdf : geopandas GeoDataFrame()
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    poi_df : pandas DataFrame()
        First parameter; Pandas DataFrame() containing gages from the parameter file.
    poi_id_sel : string
        Gage id of selected gage.

    Returns
    -------
    pfile_lat : float
        The mean value of HRU latitudes (hru_lat) found in the parameter file.
    pfile_lon : float
        The mean value of HRU longitude (hru_lon) found in the parameter file.
    zoom : int
        The zoom level for folium maps.
    cluster_zoom : int
        The zoom (out) level at which gage markers are clustered on the folium maps.
    """
    
    if poi_id_sel:
        poi_lookup = poi_id_sel
        pfile_lat = poi_df.loc[poi_df.poi_id == poi_lookup, "latitude"].values[0]
        pfile_lon = poi_df.loc[poi_df.poi_id == poi_lookup, "longitude"].values[0]
        zoom = 12
        cluster_zoom = 8
    else:
        pfile_lat = hru_gdf["hru_lat"].mean()
        pfile_lon = hru_gdf["hru_lon"].mean()
        zoom = 8
        cluster_zoom = 8

    return pfile_lat, pfile_lon, zoom, cluster_zoom


def folium_map_tiles():
    """
    Set up a background tiles (maps) for folium maps
    This can be tricky with syntax but if you go to this link you will find resources that have options beyond the few defualt options in
    folium leaflet, http://leaflet-extras.github.io/leaflet-providers/preview/
    These tiles will also work in the minimap, but can get glitchy if the same tile var is used in the minimap and the main map child object.

    Parameters
    ----------
    None

    Returns
    -------
    USGSHydroCached_layer : folium tile layer
        The background for the folium maps that displays all streams and waterbodies with labels.
    USGStopo_layer : folium tile layer
        The background for the folium maps that USGS topography.
    Esri_WorldImagery : folium tile layer
        The background for the folium maps that displays areal imagery.
    OpenTopoMap : folium tile layer
        The background for the folium maps that displays topography. An alternative to USGS topography.
    
    """

    USGSHydroCached_layer = folium.TileLayer(
        tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSHydroCached/MapServer/tile/{z}/{y}/{x}",
        attr="USGSHydroCached",
        # zoom_start=zoom,
        name="USGSHydroCached",
    )

    USGStopo_layer = folium.TileLayer(
        tiles="https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        attr="USGS_topo",
        # zoom_start=zoom,
        name="USGS Topography",
        show=False,
    )

    Esri_WorldImagery = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
        name="Esri_imagery",
        show=False,
    )

    OpenTopoMap = folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr='Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
        name="OpenTopoMap",
        show=False,
    )

    return USGSHydroCached_layer, USGStopo_layer, Esri_WorldImagery, OpenTopoMap


def create_minimap():
    """
    Set up inset map. This requires folium plugins. (from folium import plugins)

    Parameters
    ----------
    None

    Returns
    -------
    minimap : a folium map object
        A small inset map that shows regional-scale thumbnail map to help locate the NHM subdomain model.
    
    """

    minimap = plugins.MiniMap(
        tile_layer="OpenStreetMap",
        # attr = 'USGS_topo',
        position="topleft",
        # zoom_level_offset=- 4,
        height=200,
        width=200,
        collapsed_height=25,
        collapsed_width=25,
        zoom_level_fixed=5,
        toggle_display=True,
        # collapsed = True
    )
    return minimap


def create_hru_map(hru_gdf):
    """
    Creates a folium.map object from the hru_gdf.

    Parameters
    ----------
    hru_gdf : geopandas GeoDataFrame
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.

    Returns
    -------
    hru_map : a folium map object
        HRU foium.map object created to display HRU boundaries and parameter/variable values.

    """

    hru_map = folium.GeoJson(
        hru_gdf,
        style_function=style_function_hru_map,
        highlight_function=highlight_function_hru_map,
        name="NHM HRUs",
        # tooltip=tooltip_hru,
        popup=popup_hru,
    )
    return hru_map


def create_hru_label(hru_gdf, cluster_zoom):

    """
    Creates a folium.map object marker_cluster_label_hru to display HRU labels on the folium map.
    
    Parameters
    ----------
    hru_gdf : geopandas GeoDataFrame
        First parameter; HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    cluster_zoom: int
        Second parameter; The zoom (out) level at whcih gages get clustered on the folium maps.

    Returns
    -------
    marker_cluster_label_hru: folium.map object created using MarkerCluster()

    """

    marker_cluster_label_hru = MarkerCluster(
        name="All HRU labels",
        overlay=True,
        control=True,
        show=False,  # False will not draw the child upon opening the map, but have it to draw in the Layer control.
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
        z_index_offset=4005,
    )

    for idx, row in hru_gdf.iterrows():
        text = f'{row["nhm_id"]}'
        label_lat = row["hru_lat"]
        label_lon = row["hru_lon"]
        marker_label = folium.map.Marker(
            [label_lat, label_lon],
            z_index_offset=4008,
            icon=DivIcon(
                icon_size=(150, 36),
                icon_anchor=(0, 0),
                html='<div style="font-family: verdona; font-size: 10pt; font-weight: bold; color: black; text-shadow: 1px 1px 2px white;">%s</div>'
                % text,
            ),
        ).add_to(marker_cluster_label_hru)
    return marker_cluster_label_hru


def create_segment_map_show(seg_gdf):
    """
    Creates a folium.map object to display segment lines and selected parameter values from the parameter file. This object is inteded to be visible.
    
    Parameters
    ----------
    seg_gdf : geopandas GeoDataFrame
        Segments geopandas.GeoDataFrame() from GIS data in subdomain.

    Returns
    -------
    seg_map_show : a folium map object
        Segments foium.map object created to display segment lines and selected parameter values.
    """
    seg_map_show = folium.GeoJson(
        seg_gdf,
        style_function=style_function_seg_map,
        highlight_function=highlight_function_seg_map,  # lambda feature: {"fillcolor": "white", "color": "white"},
        name="NHM Segments",
        popup=popup_seg,
    )
    return seg_map_show


def create_segment_map_hide(seg_gdf):
    """
    Creates a folium.map object to display parameter values associated with segment lines in a pop-up window. This object is inteded to be invisible, only showing the pop-up values.
    
    Parameters
    ----------
    seg_gdf : geopandas GeoDataFrame
        Segments geopandas.GeoDataFrame() from GIS data in subdomain.

    Returns
    -------
    seg_map_hide : a folium map object
        Segments foium.map object created to display parameter values associated segment lines and selected parameter values.
    """
    
    seg_map_hide = folium.GeoJson(
        seg_gdf,
        style_function=style_function_seg_map,
        # highlight_function=highlight_function_seg_map,  # lambda feature: {"fillcolor": "white", "color": "white"},
        name="NHM Segments",
        # tooltip=tooltip_seg,
        # popup=popup_seg,
    )
    return seg_map_hide


def create_poi_marker_cluster(
    poi_df,
    cluster_zoom,
):
    """
    Creates a folium.map marker cluster object for pois(gages) and for lables, so that these two groups can be displayed and hidden in the map from the interactive legend. These are gages found in the parameter file.
    
    Parameters
    ----------
    poi_df : pandas DataFrame()
        First parameter; Pandas DataFrame() containing gages from the parameter file.
    cluster_zoom: int
        Second parameter; The zoom (out) level at whcih gages get clustered on the folium maps.
        

    Returns
    -------
    poi_marker_cluster: a folium MarkerCluster() object
        Gages from the parameter file.
    poi_marker_cluster_label: a folium MarkerCluster() object
        Gage id as labels for gages from the parameter file.
    """

    # add POI marker cluster child items for the map
    poi_marker_cluster = MarkerCluster(
        name="Model gage",
        overlay=True,
        control=True,
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
    )
    poi_marker_cluster_label = MarkerCluster(
        name="Model gage ID",
        overlay=True,
        control=True,
        show=False,  # False will not draw the child upon opening the map, but have it to draw in the Layer control.
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
    )
    ##add POI markers and labels using row df.interowss loop
    for idx, row in poi_df.iterrows():
        text = f'{row["poi_id"]}'
        label_lat = row["latitude"]  # -0.01
        label_lon = row["longitude"]

        marker_label = folium.map.Marker(
            [label_lat, label_lon],
            icon=DivIcon(
                icon_size=(10, 10),  # (150,36),
                icon_anchor=(0, 0),
                html='<div style="font-size: 12pt; font-weight: bold">%s</div>' % text,
            ),
        ).add_to(poi_marker_cluster_label)

        marker = folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            name=row["poi_id"],
            popup=folium.Popup(
                f'<font size="3px">{row["poi_id"]} ({row["poi_agency"]})<br>{row["poi_name"]}<br> on <b>segment </b>{row["nhm_seg"]}</font>',
                max_width=280,
                max_height=2000,
            ),
            radius=3,
            weight=2,
            color="black",
            fill=True,
            fill_color="Black",
            fill_opacity=1.0,
        ).add_to(poi_marker_cluster)

    return poi_marker_cluster, poi_marker_cluster_label


def create_non_poi_marker_cluster(
    poi_df,
    nwis_gages_aoi,
    gages_df,
    cluster_zoom: pd.DataFrame,
) -> tuple[folium.plugins.MarkerCluster, folium.plugins.MarkerCluster]:

    """
    Creates a folium.map marker cluster object for pois(gages) and for gage id lables, so that these two groups can be displayed and hidden in the map from the interactive legend. These gages are gages NOT in the parameter file.
    
    Parameters
    ----------
    poi_df : pandas DataFrame()
        Pandas DataFrame() containing gages from the parameter file.
    nwis_gages_aoi : Pandas DataFrame()
        Pandas DataFrame() containing gages from NWIS in the subdomain.
    gages_df : pandas DataFrame() 
        Represents data pertaining to subdomain gages in parameter file, NWIS, and others. 
    cluster_zoom : int
        Second parameter; The zoom (out) level at whcih gages get clustered on the folium maps.
        
    Returns
    -------
    non_poi_marker_cluster : a folium MarkerCluster() object
        Gages in the subdomain NOT in the parameter file.
    non_poi_marker_cluster_label : a folium MarkerCluster() object
        Gage id as labels for gages in the subdomain NOT in the parameter file.
    """

    # add non-poi gages marker cluster child items for the map
    non_poi_marker_cluster = MarkerCluster(
        name="Prospective gage",
        overlay=True,
        control=True,
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
    )
    non_poi_marker_cluster_label = MarkerCluster(
        name="Prospective gage ID",
        overlay=True,
        control=True,
        show=False,  # False will not draw the child upon opening the map, but have it to draw in the Layer control.
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
    )

    ##add Non-poi gage markers and labels using row df.interowss loop
    gages_list = gages_df.index.to_list()
    additional_gages = list(set(gages_list) - set(poi_df.poi_id))

    for idx, row in nwis_gages_aoi.iterrows():
        if row["poi_id"] in additional_gages:

            text = f'{row["poi_id"]}'
            label_lat = row["latitude"]  # -0.01
            label_lon = row["longitude"]

            marker_label = folium.map.Marker(
                [label_lat, label_lon],
                icon=DivIcon(
                    icon_size=(10, 10),  # (150,36),
                    icon_anchor=(0, 0),
                    html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                    % text,
                ),
            ).add_to(non_poi_marker_cluster_label)

            marker = folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                name=row["poi_id"],
                popup=folium.Popup(
                    f'<font size="3px">{row["poi_id"]} ({row["poi_agency"]})<br>{row["poi_name"]}<br></font>',
                    max_width=280,
                    max_height=2000,
                ),
                radius=3,
                weight=2,
                color="gray",
                fill=True,
                fill_color="Gray",
                fill_opacity=1.0,
            ).add_to(non_poi_marker_cluster)
        else:
            pass

    return non_poi_marker_cluster, non_poi_marker_cluster_label


def create_nhru_par_map(
    param_filename,
    hru_gdf,
    par_sel,
    mo_sel,
    mo_name,
    nhru_params,
    Folium_maps_dir,
):
    """
    Creates a folium.map object to display a selected parameter value for HRUs in the subdomain with custom value bar.

    Parameters
    ----------
    param_filename : pathlib Path class 
        Path to parameter file. 
    hru_gdf : geopandas GeoDataFrame
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    par_sel: string
        Selected parameter to display on the map.
    mo_sel: integer
        Selected month for selected parameter to display on the map if the parameter is dimensioned by month.
    mo_name: string
        Name of selected month for selected parameter to display on the map if the parameter is dimensioned by month.
    nhru_params: list of string values
        List of selected parameters dimensioned by HRU.
    Folium_maps_dir: pathlib Path class
        Path to a folder being used as temp file storage. All files written here will be deleted. 
    

    Returns
    -------
    hru_map: a folium map object
        HRU foium.map object created to display HRU boundaries and parameter/variable values.
    val_bar_image: folium.map FloatImage() object
        Custom value bar tailored to the range of selected parameter/variable values.
    value_min: float
        Minimum value in the selected parameter/variable value range.
    value_max: float
        Maximum value in the selected parameter/variable value range.
    same_value: float, None
        Used to record if selected parameter/variable values are the same value for all HRU's (value = float) or if they are differnt values (None)
    color_bar: Boolean
        If all selected parameter/variable values are the same, no color bar is made (False).
    
    """
    
    cp_style_function = lambda feature: {
        "fillColor": linear(par_sel_color_dict[feature["id"]]),
        "color": "black",
        "weight": 0.25,
        # "dashArray": "5, 5",
        "fillOpacity": 0.3,
    }

    prms_meta = MetaData().metadata  # loads metadata functions for pyPRMS
    pdb = ParameterFile(
        param_filename, metadata=prms_meta, verbose=False
    )  # loads parmaeterfile functions for pyPRMS

    if par_sel in nhru_params:

        mo_sel = None  # set to none, this is not a monthly param
        hru_gdf_copy = hru_gdf.copy()
        hru_gdf_copy["nhm_id"] = hru_gdf_copy["nhm_id"].astype(str)
        hru_gdf_copy["hru_segment_nhm"] = hru_gdf_copy["hru_segment_nhm"].astype(str)

        hru_gdf_copy.set_index("nhm_id", inplace=True, drop=False)

        par_subset_df = hru_gdf.loc[:, ["nhm_id", par_sel]]
        par_subset_df["nhm_id"] = par_subset_df["nhm_id"].astype(str)
        par_subset_df.rename(columns={f"{par_sel}": "par_value"}, inplace=True)
        par_subset_df["par_value"] = np.round(par_subset_df["par_value"], 4)
        par_subset_df.set_index("nhm_id", inplace=True, drop=False)

        value_min = np.round(par_subset_df["par_value"].min(), 8)
        value_max = np.round(par_subset_df["par_value"].max(), 8)

        if value_min == value_max:
            same_value = value_min
            value_min = value_min - 0.001
            value_max = value_min + 0.001
            color_bar = False
        else:
            color_bar = True
            same_value = None

        par_sel_color_dict = pd.Series(
            par_subset_df.par_value.values, index=par_subset_df.nhm_id
        ).to_dict()

        # Making par_bins
        sdv = par_subset_df["par_value"].std()
        mean = par_subset_df["par_value"].mean()

        par_bins = [
            value_min,
            np.round(value_min + (0.25 * (mean - value_min)), 5),
            np.round(value_min + (0.50 * (mean - value_min)), 5),
            np.round(value_min + (0.75 * (mean - value_min)), 5),
            np.round(mean, 3),
            np.round(value_max - (0.75 * (value_max - mean)), 5),
            np.round(value_max - (0.50 * (value_max - mean)), 5),
            np.round(value_max - (0.25 * (value_max - mean)), 5),
            value_max,
        ]

        linear = cm.StepColormap(
            colors=[
                "#8B0000",
                "#AC4800",
                "#CD9100",
                "#EEDA00",
                "#DADA13",
                "#91913B",
                "#484863",
                "#00008B",
            ],
            index=par_bins,
            vmin=0.00,
            vmax=0.05,
            caption="Total Standard deviation at the point[mm]",
            # tick_labels= ('0.01', '0.02', '0.03', '0.04')
        )

        #################################################

        if not color_bar:
            fig = None  # fig, ax = plt.subplots(figsize=(18, 0.5))
            val_bar_image = None

        else:
            fig, ax = plt.subplots(figsize=(6, 0.75))
            fig.patch.set_linewidth(0.5)
            fig.patch.set_edgecolor("black")
            fig.subplots_adjust(bottom=0.65)

            cmap = mplib.colors.ListedColormap(
                [
                    "#8B0000",
                    "#AC4800",
                    "#CD9100",
                    "#EEDA00",
                    "#DADA13",
                    "#91913B",
                    "#484863",
                    "#00008B",
                ]
            )
            cmap.set_over("0.25")
            cmap.set_under("0.75")

            bounds = par_bins
            norm = mplib.colors.BoundaryNorm(bounds, cmap.N)

            cb2 = mplib.colorbar.ColorbarBase(
                ax,
                cmap=cmap,
                norm=norm,
                boundaries=[0] + bounds + [13],
                extend=None,
                ticks=bounds,
                spacing="uniform",
                orientation="horizontal",
                alpha=0.45,
            )
            cb2.set_label(
                f'Discrete {par_sel} intervals, {pdb.get(par_sel).meta["units"]}'
            )

            val_bar_file = pl.Path(Folium_maps_dir / "val_bar.png").resolve()
            fig.savefig(
                val_bar_file,
                format="png",
            )
            plt.close(fig)

            with open(val_bar_file, "rb") as lf:
                # open in binary mode, read bytes, encode, decode obtained bytes as utf-8 string
                b64_content = base64.b64encode(lf.read()).decode("utf-8")
                del lf

            val_bar_image = FloatImage(
                image="data:image/png;base64,{}".format(b64_content),
                bottom=1,
                left=14,
                style="position:fixed; width:6in; height:0.75in;",
            )
            del val_bar_file
            
        popup_hru = folium.GeoJsonPopup(
            fields=["nhm_id", "hru_segment_nhm", par_sel],
            aliases=["hru", " flows to segment", f"{par_sel}"],
            labels=True,
            localize=True,
            style=(
                "font-size: 16px;"
            ),  # Note that this tooltip style sets the style for all tool_tips.
            # background-color: #F0EFEF;border: 2px solid black;font-family: arial; padding: 10px; background-color: #F0EFEF;
        )
        hru_map = folium.GeoJson(
            hru_gdf_copy,
            style_function=cp_style_function,  # style_function_hru_map,
            highlight_function=highlight_function_hru_map,
            name="NHM HRUs",
            popup=popup_hru,
            z_index_offset=40002,
        )

        
    else:
        # mo_sel = '5'
        par_mo_sel = f"{par_sel}_{mo_sel}"
        value_min = hru_gdf[par_mo_sel].min()
        value_max = hru_gdf[par_mo_sel].max()

        hru_gdf_copy = hru_gdf.copy()
        hru_gdf_copy["nhm_id"] = hru_gdf_copy["nhm_id"].astype(str)
        hru_gdf_copy["hru_segment_nhm"] = hru_gdf_copy["hru_segment_nhm"].astype(str)

        hru_gdf_copy.set_index("nhm_id", inplace=True, drop=False)

        par_subset_df = hru_gdf.loc[:, ["nhm_id", par_mo_sel]]
        par_subset_df["nhm_id"] = par_subset_df["nhm_id"].astype(str)
        par_subset_df.rename(columns={f"{par_mo_sel}": "par_value"}, inplace=True)

        value_min = np.round(par_subset_df["par_value"].min(), 8)
        value_max = np.round(par_subset_df["par_value"].max(), 8)

        if value_min == value_max:
            same_value = value_min
            value_min = value_min - 0.001
            value_max = value_min + 0.001
            color_bar = False
        else:
            color_bar = True
            same_value = None

        par_sel_color_dict = pd.Series(
            par_subset_df.par_value.values, index=par_subset_df.nhm_id
        ).to_dict()

        # Making par_bins
        sdv = par_subset_df["par_value"].std()
        mean = par_subset_df["par_value"].mean()

        par_bins = [
            value_min,
            np.round(value_min + (0.25 * (mean - value_min)), 5),
            np.round(value_min + (0.50 * (mean - value_min)), 5),
            np.round(value_min + (0.75 * (mean - value_min)), 5),
            np.round(mean, 3),
            np.round(value_max - (0.75 * (value_max - mean)), 5),
            np.round(value_max - (0.50 * (value_max - mean)), 5),
            np.round(value_max - (0.25 * (value_max - mean)), 5),
            value_max,
        ]

        linear = cm.StepColormap(
            colors=[
                "#8B0000",
                "#AC4800",
                "#CD9100",
                "#EEDA00",
                "#DADA13",
                "#91913B",
                "#484863",
                "#00008B",
            ],
            index=par_bins,
            vmin=0.00,
            vmax=0.05,
            caption="Total Standard deviation at the point[mm]",
            # tick_labels= ('0.01', '0.02', '0.03', '0.04')
        )
        #################################################
        if not color_bar:
            fig = None  # fig, ax = plt.subplots(figsize=(6, 0.75))
            val_bar_image = None
        else:
            fig, ax = plt.subplots(figsize=(6, 0.75))
            fig.patch.set_linewidth(0.5)
            fig.patch.set_edgecolor("black")
            fig.subplots_adjust(
                bottom=0.65
            )  # This moves the axis of the cb closer to the top

            cmap = mplib.colors.ListedColormap(
                [
                    "#8B0000",
                    "#AC4800",
                    "#CD9100",
                    "#EEDA00",
                    "#DADA13",
                    "#91913B",
                    "#484863",
                    "#00008B",
                ]
            )
            cmap.set_over("0.25")
            cmap.set_under("0.75")

            bounds = par_bins
            norm = mplib.colors.BoundaryNorm(bounds, cmap.N)
            cb2 = mplib.colorbar.ColorbarBase(
                ax,
                cmap=cmap,
                norm=norm,
                boundaries=[0] + bounds + [13],
                extend=None,
                ticks=bounds,
                spacing="uniform",
                orientation="horizontal",
                alpha=0.45,
            )
            cb2.set_label(
                f'Discrete {par_sel} intervals, {pdb.get(par_sel).meta["units"]}'
            )  # {pdb.get(par_sel).units}

            # fig.set_facecolor("lightgray")

            val_bar_file = pl.Path(Folium_maps_dir / "val_bar.png").resolve()
            fig.savefig(val_bar_file, format="png")
            plt.close(fig)

            with open(val_bar_file, "rb") as lf:
                # open in binary mode, read bytes, encode, decode obtained bytes as utf-8 string
                b64_content = base64.b64encode(lf.read()).decode("utf-8")
                del lf

            val_bar_image = FloatImage(
                image="data:image/png;base64,{}".format(b64_content),
                bottom=1,
                left=14,
                style="position:fixed;",
            )
            del val_bar_file
        
        popup_hru = folium.GeoJsonPopup(
            fields=["nhm_id", "hru_segment_nhm", par_mo_sel],
            aliases=["hru", " flows to segment", f"{par_sel} for {mo_name}"],
            labels=True,
            localize=False,
            style=(
                "font-size: 16px;"
            ),  # Note that this tooltip style sets the style for all tool_tips.
            # background-color: #F0EFEF;border: 2px solid black;font-family: arial; padding: 10px; background-color: #F0EFEF;
        )
        hru_map = folium.GeoJson(
            hru_gdf_copy,
            style_function=cp_style_function,  # style_function_hru_map,
            highlight_function=highlight_function_hru_map,
            name="NHM HRUs",
            popup=popup_hru,
            z_index_offset=40002,
        )
        
    return hru_map, val_bar_image, value_min, value_max, same_value, color_bar


def create_poi_paramplot_marker_cluster(
    poi_df,
    Folium_maps_dir,
    cluster_zoom,
    par_sel,
):

    """
    Creates a folium.map marker cluster object for pois(gages) and for gage id lables. Includes imbedded maps as pop-ups for the markers. Two groups can be displayed and hidden in the map from the interactive legend. These gages are in the parameter file.
    
    Parameters
    ----------
    poi_df : pandas DataFrame()
        Pandas DataFrame() containing gages from the parameter file.
    Folium_maps_dir : pathlib Path class
        Path to folder containing the html plots for all parameters listed for all HRUs in gage catchments. 
    cluster_zoom : int
        Second parameter; The zoom (out) level at whcih gages get clustered on the folium maps.
    par_sel : string
        Selected parameter to display on the map.
            
    Returns
    -------
    marker_cluster : a folium MarkerCluster() object
        Gages in the parameter file.
    marker_cluster_label_poi : a folium MarkerCluster() object
        Gage id as labels.
    """
    
    marker_cluster = MarkerCluster(
        name="All the POIs",
        overlay=True,
        control=True,
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
        z_index_offset=5000,
    )
    marker_cluster_label_poi = MarkerCluster(
        name="All the POI labels",
        overlay=True,
        control=True,
        show=False,  # False will not draw the child upon opening the map, but have it to draw in the Layer control.
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
        z_index_offset=4004,
    )

    for idx, row in poi_df.iterrows():
        poi_id = row["poi_id"]
        # Read ploty plot of each poi
        with open(Folium_maps_dir / f"{par_sel}_{poi_id}.txt", "r") as f:
            div_txt = f.read()

        # Create html code to insert the plotly plot to the folium pop up
        html = (
            """
        <html>
        <head>
             <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        </head>
        <body>
             <!-- Output from the Python script above: -->"""
            + div_txt
            + """</body>
        </html>"""
        )

        # Add the Plots to the popup
        iframe = folium.IFrame(
            html=html,
            width=525,
            height=325,
        )
        # popup = folium.Popup(iframe, max_width=3250,parse_html=True)

        marker = folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            name=row["poi_id"],
            popup=folium.Popup(
                iframe,
                # max_width=500,
                # max_height=300,
                parse_html=True,
            ),
            radius=3,
            weight=2,
            color="black",
            fill=True,
            fill_color="Black",
            fill_opacity=1.0,
            draggable=True,
            z_index_offset=4006,
        ).add_to(marker_cluster)

        # marker_cluster.add_child(marker)
        text = f'{row["poi_id"]}'
        label_lat = row["latitude"] - 0.01
        label_lon = row["longitude"]

        marker_label = folium.map.Marker(
            [label_lat, label_lon],
            z_index_offset=4007,
            icon=DivIcon(
                icon_size=(150, 36),
                icon_anchor=(0, 0),
                html='<div style="font-size: 12pt; font-weight: bold">%s</div>' % text,
            ),
        ).add_to(marker_cluster_label_poi)

    return marker_cluster, marker_cluster_label_poi


def create_annual_output_var_map(
    gdf_output_var_annual,
    output_var_sel,
    sel_year,
    var_units,
    Folium_maps_dir,
):

    """
    Creates a folium.map that displays the output values for a selected variable and year.
    
    Parameters
    ----------
    gdf_output_var_annual : Geopandas GeoDataFrame()
        GeoDataFrame containing annual values for the selected output variable.
    output_var_sel: string
        Selected variable to display on the map.
    sel_year: int
        Selected year to view in the map.
    var_units: string
        Units for the mapped variable.
    Folium_maps_dir: pathlib Path class
        Path to a folder being used as temp file storage. All files written here will be deleted.
    
                
    Returns
    -------
    hru_map: a folium map object
        HRU foium.map object created to display HRU boundaries and parameter/variable values.
    val_bar_image: folium.map FloatImage() object
        Custom value bar tailored to the range of selected parameter/variable values.
    value_min: float
        Minimum value in the selected parameter/variable value range.
    value_max: float
        Maximum value in the selected parameter/variable value range.
    same_value: float, None
        Used to record if selected parameter/variable values are the same value for all HRU's (value = float) or if they are differnt values (None)
    color_bar: Boolean
        If all selected parameter/variable values are the same, no color bar is made (False).
    """
    

    cp_style_function = lambda feature: {
        "fillColor": linear(var_sel_color_dict[feature["id"]]),
        "color": "black",
        "weight": 0.25,
        # "dashArray": "5, 5",
        "fillOpacity": 0.3,
    }

    hru_gdf_copy = gdf_output_var_annual.copy().reset_index(drop=True).to_crs(crs)
    hru_gdf_copy["nhm_id"] = hru_gdf_copy["nhm_id"].astype(str)
    hru_gdf_copy.set_index("nhm_id", inplace=True, drop=False)

    var_subset_df = gdf_output_var_annual.loc[:, ["nhm_id", str(sel_year)]]
    var_subset_df["nhm_id"] = var_subset_df["nhm_id"].astype(str)
    var_subset_df.rename(columns={f"{sel_year}": "var_value"}, inplace=True)
    var_subset_df["var_value"] = np.round(var_subset_df["var_value"], 4)
    var_subset_df.set_index("nhm_id", inplace=True, drop=False)

    value_min = np.round(var_subset_df["var_value"].min(), 8)
    value_max = np.round(var_subset_df["var_value"].max(), 8)

    if value_min == value_max:
        same_value = value_min
        value_min = value_min - 0.001
        value_max = value_min + 0.001
        color_bar = False
    else:
        color_bar = True
        same_value = None

    var_sel_color_dict = pd.Series(
        var_subset_df.var_value.values, index=var_subset_df.nhm_id
    ).to_dict()

    # Making par_bins
    sdv = var_subset_df["var_value"].std()
    mean = var_subset_df["var_value"].mean()

    var_bins = [
        value_min,
        np.round(value_min + (0.25 * (mean - value_min)), 5),
        np.round(value_min + (0.50 * (mean - value_min)), 5),
        np.round(value_min + (0.75 * (mean - value_min)), 5),
        np.round(mean, 3),
        np.round(value_max - (0.75 * (value_max - mean)), 5),
        np.round(value_max - (0.50 * (value_max - mean)), 5),
        np.round(value_max - (0.25 * (value_max - mean)), 5),
        value_max,
    ]

    #################################################

    if not color_bar:
        fig = None  # fig, ax = plt.subplots(figsize=(6, 0.75))
        val_bar_image = None
    else:
        fig, ax = plt.subplots(figsize=(6, 0.75))
        fig.patch.set_linewidth(0.5)
        fig.patch.set_edgecolor("black")
        fig.subplots_adjust(
            bottom=0.65
        )  # This moves the axis of the cb closer to the top

        cmap = mplib.colors.ListedColormap(
            [
                "#8B0000",
                "#AC4800",
                "#CD9100",
                "#EEDA00",
                "#DADA13",
                "#91913B",
                "#484863",
                "#00008B",
            ]
        )
        cmap.set_over("0.25")
        cmap.set_under("0.75")

        bounds = var_bins
        norm = mplib.colors.BoundaryNorm(bounds, cmap.N)

        cb2 = mplib.colorbar.ColorbarBase(
            ax,
            cmap=cmap,
            norm=norm,
            boundaries=[0] + bounds + [13],
            extend=None,
            ticks=bounds,
            spacing="uniform",
            orientation="horizontal",
            alpha=0.45,
        )
        cb2.set_label(
            f"Discrete {sel_year} {output_var_sel} intervals, {var_units}"
        )  # , {pdb.get(output_var_sel).units}')

        # fig.set_facecolor("lightgray")

        val_bar_file = pl.Path(Folium_maps_dir / "val_bar.png").resolve()
        fig.savefig(
            val_bar_file,
            format="png",
        )
        plt.close(fig)

        with open(val_bar_file, "rb") as lf:
            # open in binary mode, read bytes, encode, decode obtained bytes as utf-8 string
            b64_content = base64.b64encode(lf.read()).decode("utf-8")
            del lf

        val_bar_image = FloatImage(
            image="data:image/png;base64,{}".format(b64_content),
            bottom=1,
            left=14,
            style="position:fixed; width:6in; height:0.75in;",
        )
        del val_bar_file

    #######################################################

    linear = cm.StepColormap(
        colors=[
            "#8B0000",
            "#AC4800",
            "#CD9100",
            "#EEDA00",
            "#DADA13",
            "#91913B",
            "#484863",
            "#00008B",
        ],
        index=var_bins,
        vmin=0.00,
        vmax=0.05,
        caption="Total Standard deviation at the point[mm]",
        # tick_labels= ('0.01', '0.02', '0.03', '0.04')
    )
    popup_hru = folium.GeoJsonPopup(
        fields=["nhm_id", str(sel_year)],
        aliases=["nhm_id", f"{output_var_sel}, {var_units}"],
        labels=True,
        localize=True,
        style=(
            "font-size: 16px;"
        ),  # Note that this tooltip style sets the style for all tool_tips.
        # background-color: #F0EFEF;border: 2px solid black;font-family: arial; padding: 10px; background-color: #F0EFEF;
    )

    hru_map = folium.GeoJson(
        hru_gdf_copy,
        style_function=cp_style_function,  # style_function_hru_map,
        highlight_function=highlight_function_hru_map,
        name="NHM HRUs",
        popup=popup_hru,
        z_index_offset=40002,
    )

    return hru_map, val_bar_image, value_min, value_max, same_value, color_bar


def create_streamflow_poi_markers(
    poi_df,
):

    """
    Creates a folium.map marker cluster object for pois(gages) and for gage id lables. Two groups can be displayed and hidden in the map from the interactive legend. These gages are in the parameter file.
    
    Parameters
    ----------
    poi_df : pandas DataFrame()
        Pandas DataFrame() containing gages from the parameter file.
            
    Returns
    -------
    marker_cluster : a folium MarkerCluster() object
        Gages in the parameter file.
    marker_cluster_label_poi : a folium MarkerCluster() object
        Gage id as labels.
    """
    
    marker_cluster = folium.FeatureGroup(
        name="All the POIs",
        overlay=True,
        control=True,
        icon_create_function=None,
        z_index_offset=5000,
    )

    marker_cluster_label_poi = folium.FeatureGroup(
        name="All the POI labels",
        overlay=True,
        control=True,
        show=False,  # False will not draw the child upon opening the map, but have it to draw in the Layer control.
        icon_create_function=None,
        z_index_offset=4004,
    )

    for idx, row in poi_df.iterrows():
        poi_id = row["poi_id"]

        if row["nhm_calib"] == "Y":  # Do this for all the gages used in calibration
            if row["kge"] >= 0.7:

                marker = folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    name=row["poi_id"],
                    popup=folium.Popup(
                        f'Gage <b>{row["poi_id"]}</b>, {row["poi_name"]}<br>',
                        max_width=150,
                        max_height=70,
                    ),
                    radius=5,
                    weight=2,
                    color="Black",
                    fill=True,
                    fill_color="Green",
                    fill_opacity=1.0,
                    draggable=True,
                    lazy=True,
                    z_index_offset=4006,
                ).add_to(marker_cluster)

                text = f'{row["poi_id"]}'
                label_lat = row["latitude"]  # -0.005
                label_lon = row["longitude"]

                marker_label = folium.map.Marker(
                    [label_lat, label_lon],
                    z_index_offset=4007,
                    icon=DivIcon(
                        icon_size=(150, 36),
                        icon_anchor=(0, 0),
                        html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                        % text,
                    ),
                ).add_to(marker_cluster_label_poi)
            if (row["kge"] < 0.7) & (row["kge"] >= 0.5):

                marker = folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    name=row["poi_id"],
                    popup=folium.Popup(
                        f'Gage <b>{row["poi_id"]}</b>, {row["poi_name"]}<br>',
                        max_width=150,
                        max_height=70,
                    ),
                    radius=5,
                    weight=2,
                    color="Black",
                    fill=True,
                    fill_color="Yellow",
                    fill_opacity=1.0,
                    draggable=True,
                    lazy=True,
                    z_index_offset=4006,
                ).add_to(marker_cluster)

                # marker_cluster.add_child(marker)
                text = f'{row["poi_id"]}'
                label_lat = row["latitude"]  # -0.005
                label_lon = row["longitude"]

                marker_label = folium.map.Marker(
                    [label_lat, label_lon],
                    z_index_offset=4007,
                    icon=DivIcon(
                        icon_size=(150, 36),
                        icon_anchor=(0, 0),
                        html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                        % text,
                    ),
                ).add_to(marker_cluster_label_poi)
            if row["kge"] < 0.5:

                marker = folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    name=row["poi_id"],
                    popup=folium.Popup(
                        f'Gage <b>{row["poi_id"]}</b>, {row["poi_name"]}<br>',
                        max_width=150,
                        max_height=70,
                    ),
                    radius=5,
                    weight=2,
                    color="Black",
                    fill=True,
                    fill_color="Red",
                    fill_opacity=1.0,
                    draggable=True,
                    lazy=True,
                    z_index_offset=4006,
                ).add_to(marker_cluster)

                # marker_cluster.add_child(marker)
                text = f'{row["poi_id"]}'
                label_lat = row["latitude"]  # -0.005
                label_lon = row["longitude"]

                marker_label = folium.map.Marker(
                    [label_lat, label_lon],
                    z_index_offset=4007,
                    icon=DivIcon(
                        icon_size=(150, 36),
                        icon_anchor=(0, 0),
                        html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                        % text,
                    ),
                ).add_to(marker_cluster_label_poi)
        ################################################

        ###########
        if row["nhm_calib"] == "N":
            if row["kge"] >= 0.7:

                marker = folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    name=row["poi_id"],
                    popup=folium.Popup(
                        f'Gage <b>{row["poi_id"]}</b>, {row["poi_name"]}<br>',
                        max_width=150,
                        max_height=70,
                    ),
                    radius=5,
                    weight=2,
                    color=None,
                    fill=True,
                    fill_color="Green",
                    fill_opacity=1.0,
                    draggable=True,
                    lazy=True,
                    z_index_offset=4006,
                ).add_to(marker_cluster)

                # marker_cluster.add_child(marker)
                text = f'{row["poi_id"]}'
                label_lat = row["latitude"]  # -0.005
                label_lon = row["longitude"]

                marker_label = folium.map.Marker(
                    [label_lat, label_lon],
                    z_index_offset=4007,
                    icon=DivIcon(
                        icon_size=(150, 36),
                        icon_anchor=(0, 0),
                        html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                        % text,
                    ),
                ).add_to(marker_cluster_label_poi)
            if (row["kge"] < 0.7) & (row["kge"] >= 0.5):

                marker = folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    name=row["poi_id"],
                    popup=folium.Popup(
                        f'Gage <b>{row["poi_id"]}</b>, {row["poi_name"]}<br>',
                        max_width=150,
                        max_height=70,
                    ),
                    radius=5,
                    weight=2,
                    color=None,
                    fill=True,
                    fill_color="Yellow",
                    fill_opacity=1.0,
                    draggable=True,
                    lazy=True,
                    z_index_offset=4006,
                ).add_to(marker_cluster)

                # marker_cluster.add_child(marker)
                text = f'{row["poi_id"]}'
                label_lat = row["latitude"]  # -0.005
                label_lon = row["longitude"]

                marker_label = folium.map.Marker(
                    [label_lat, label_lon],
                    z_index_offset=4007,
                    icon=DivIcon(
                        icon_size=(150, 36),
                        icon_anchor=(0, 0),
                        html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                        % text,
                    ),
                ).add_to(marker_cluster_label_poi)
            if row["kge"] < 0.5:

                marker = folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    name=row["poi_id"],
                    popup=folium.Popup(
                        f'Gage <b>{row["poi_id"]}</b>, {row["poi_name"]}<br>',
                        max_width=150,
                        max_height=70,
                    ),
                    radius=5,
                    weight=2,
                    color=None,
                    fill=True,
                    fill_color="Red",
                    fill_opacity=1.0,
                    draggable=True,
                    lazy=True,
                    z_index_offset=4006,
                ).add_to(marker_cluster)

                # marker_cluster.add_child(marker)
                text = f'{row["poi_id"]}'
                label_lat = row["latitude"]  # -0.005
                label_lon = row["longitude"]

                marker_label = folium.map.Marker(
                    [label_lat, label_lon],
                    z_index_offset=4007,
                    icon=DivIcon(
                        icon_size=(150, 36),
                        icon_anchor=(0, 0),
                        html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                        % text,
                    ),
                ).add_to(marker_cluster_label_poi)
            if np.isnan(row["kge"]):

                marker = folium.CircleMarker(
                    location=[row["latitude"], row["longitude"]],
                    name=row["poi_id"],
                    popup=folium.Popup(
                        f'Gage <b>{row["poi_id"]}</b>, {row["poi_name"]}<br> Gage has less than 2yrs of observations.',
                        max_width=150,
                        max_height=70,
                    ),
                    radius=2,
                    weight=2,
                    color="Black",
                    fill=True,
                    fill_color="Black",
                    fill_opacity=1.0,
                    draggable=True,
                    lazy=True,
                    z_index_offset=4006,
                ).add_to(marker_cluster)

                # marker_cluster.add_child(marker)
                text = f'{row["poi_id"]}'
                label_lat = row["latitude"]  # -0.005
                label_lon = row["longitude"]

                marker_label = folium.map.Marker(
                    [label_lat, label_lon],
                    z_index_offset=4007,
                    icon=DivIcon(
                        icon_size=(150, 36),
                        icon_anchor=(0, 0),
                        html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                        % text,
                    ),
                ).add_to(marker_cluster_label_poi)

    return marker_cluster, marker_cluster_label_poi


def make_hf_map(
    *,
    root_dir,
    hru_gdf,
    HW_basins_gdf,
    HW_basins,
    poi_df,
    poi_id_sel,
    seg_gdf,
    nwis_gages_aoi,
    gages_df,
    html_maps_dir,
    Folium_maps_dir,
    param_filename,
    subdomain,
):
    """
    Creates interactive folium.map of all hydrofabric folium.map objects.

    Parameters
    ----------
    hru_gdf : geopandas GeoDataFrame 
        HRU geodataframe from GIS data in subdomain. 
    HW_basins_gdf : geopandas GeoDataFrame
        NHM headwaters basins geopandas GeoDataFrame used to display caliration level of HRUs on map.
    HW_basins : geopandas polyline dataset
        Polyline file that was made using HW_basins_gdf.boundary
    poi_df : pandas DataFrame
        Pandas DataFrame containing gages from the parameter file.
    poi_id_sel : string
        Gage id of selected gage.
    seg_gdf : geopandas GeoDataFrame
        Segments geodataframe from GIS data in subdomain and segment parameter values from parameter file.
    nwis_gages_aoi : Pandas DataFrame
        Pandas DataFrame containing gages from NWIS in the subdomain.
    gages_df : pandas DataFrame
        Pandas DataFrame containing gages from the default.csv or gages.csv (whichever is in use).
    html_maps_dir : pathlib Path class 
        Path where html maps are exported.
    param_filename : pathlib Path class 
        Path to parameter file. 
    subdomain : string 
        NHM subdomain name. 
            
    Returns
    -------
    map_file : folium.map of HF elements
    """
    
    # Make dataframe of the parameter file using pyPRMS
    prms_meta = MetaData().metadata
    pdb = ParameterFile(param_filename, metadata=prms_meta, verbose=False)

    pfile_lat, pfile_lon, zoom, cluster_zoom = folium_map_elements(
        hru_gdf, poi_df, poi_id_sel
    )
    USGSHydroCached_layer, USGStopo_layer, Esri_WorldImagery, OpenTopoMap = (
        folium_map_tiles()
    )
    minimap = create_minimap()

    ################################################
 
    hru_map = create_hru_map(hru_gdf)
    seg_map_show = create_segment_map_show(seg_gdf)

    poi_marker_cluster, poi_marker_cluster_label = create_poi_obs_marker_cluster(
        poi_df, cluster_zoom, Folium_maps_dir
    )

    non_poi_marker_cluster, non_poi_marker_cluster_label = (
        create_non_poi_obs_marker_cluster(poi_df, nwis_gages_aoi, gages_df, Folium_maps_dir, param_filename, cluster_zoom)
    )

    m2 = folium.Map()
    m2 = folium.Map(
        location=[pfile_lat, pfile_lon],
        tiles=USGSHydroCached_layer,
        zoom_start=zoom,
        width="100%",
        height="100%",
        control_scale=True,
    )

    USGStopo_layer.add_to(m2)
    OpenTopoMap.add_to(m2)
    Esri_WorldImagery.add_to(m2)

    # Add widgets
    m2.add_child(minimap)
    m2.add_child(MeasureControl(position="bottomright"))

    hru_cal_map = folium.GeoJson(
        HW_basins_gdf,  # hru_gdf_map,
        style_function=cal_style_function,
        # highlight_function = highlight_function_hru_map,
        name="HRU cal level",
        z_index_offset=40002,
    ).add_to(m2)

    hru_map.add_to(m2)
    hw_basins_map = folium.GeoJson(
        HW_basins, style_function=hw_basin_style, name="HW basin boundary"
    ).add_to(m2)
    seg_map_show.add_to(m2)

    poi_marker_cluster.add_to(m2)
    poi_marker_cluster_label.add_to(m2)

    non_poi_marker_cluster.add_to(m2)
    non_poi_marker_cluster_label.add_to(m2)

    plugins.Fullscreen(position="topleft").add_to(m2)
    folium.LayerControl(collapsed=True, position="bottomright").add_to(m2)

    ##add Non-poi gage markers and labels using row df.interowss loop
    gages_list = gages_df.index.to_list()
    additional_gages = list(set(gages_list) - set(poi_df.poi_id))

    explan_txt = f"HRUs: {pdb.dimensions.get('nhru').meta['size']}, segments: {pdb.dimensions.get('nsegment').meta['size']},<br>gages: {pdb.dimensions.get('npoigages').meta['size']}, Potential gages: {len(additional_gages)}"
    title_html = f"<h1 style='position:absolute;z-index:100000;font-size: 28px;left:26vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '><strong>The NHM {subdomain} model: hydrofabric elements</strong><br><h1 style='position:absolute;z-index:100000;font-size: 20px;left:31vw;right:5vw; top:4vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '> {explan_txt}</h1>"

    #add custom legend
    legend_file = pl.Path(root_dir / "data_dependencies/map_custom_explanations/nb_2.png").resolve()
    with open(legend_file, "rb") as lf:
        # open in binary mode, read bytes, encode, decode obtained bytes as utf-8 string
        b64_content = base64.b64encode(lf.read()).decode("utf-8")
        del lf
    legend_image = FloatImage(
        image="data:image/png;base64,{}".format(b64_content),
        bottom=15,
        left=1,
        style="position:fixed; width:3.042in; height:1.349in;",
    )
    m2.add_child(legend_image)
    
    m2.get_root().html.add_child(Element(title_html))

    map_file = f"{html_maps_dir}/hydrofabric_map.html"
    m2.save(map_file)

    make_webbrowser_map(map_file)

    return map_file


def make_par_map(
    *,
    root_dir,
    hru_gdf,
    HW_basins,
    poi_df,
    par_sel,
    mo_sel,
    mo_name,
    nhru_params,
    Folium_maps_dir,
    seg_gdf,
    html_maps_dir,
    param_filename,
    subdomain,
):

    """
    Creates a map that displays the selected parameter's values for HRUs in the NHM subdomain model. 

    Parameters
    ----------
    hru_gdf: geopandas GeoDataFrame 
        HRU geodataframe from GIS data in subdomain. 
    HW_basins: geopandas polyline dataset
        Polyline file that was made using HW_basins_gdf.boundary.
    poi_df : pandas DataFrame
        Pandas DataFrame containing gages from the parameter file.
    par_sel: string
         Selected parameter name.
    mo_sel: int
        Selected month
    mo_name: string
        Name of selected month
    nhru_params: list of string values
        List of selected parameters dimensioned by HRU.
    Folium_maps_dir: pathlib Path class
        Path to a folder being used as temp file storage. All files written here will be deleted.
    seg_gdf: geopandas GeoDataFrame
        Segments geodataframe from GIS data in subdomain and segment parameter values from parameter file.
    html_maps_dir: pathlib Path class 
        Path where html maps are exported.
    param_filename: pathlib Path class 
        Path to parameter file.
    subdomain : string 
        NHM subdomain name. 
            
    Returns
    -------
    map_file: folium.map
        Folium.map that displays the selected parameter's values for HRUs in the NHM subdomain model.    
    """
    
    prms_meta = MetaData().metadata
    pdb = ParameterFile(param_filename, metadata=prms_meta, verbose=False)
    m3 = folium.Map()

    pfile_lat, pfile_lon, zoom, cluster_zoom = folium_map_elements(hru_gdf, poi_df, "")
    USGSHydroCached_layer, USGStopo_layer, Esri_WorldImagery, OpenTopoMap = (
        folium_map_tiles()
    )
    minimap = create_minimap()

    m3 = folium.Map(
        location=[pfile_lat, pfile_lon],
        # width=1000, height=600,
        tiles=USGSHydroCached_layer,
        zoom_start=zoom,
        control_scale=True,
    )

    USGStopo_layer.add_to(m3)
    OpenTopoMap.add_to(m3)
    Esri_WorldImagery.add_to(m3)

    # Add widgets
    m3.add_child(minimap)
    m3.add_child(MeasureControl(position="bottomright"))

    hru_map, val_bar_image, value_min, value_max, same_value, color_bar = (
        create_nhru_par_map(
            param_filename,
            hru_gdf,
            par_sel,
            mo_sel,
            mo_name,
            nhru_params,
            Folium_maps_dir,
        )
    )
    # fig.show()
    marker_cluster_label_hru = create_hru_label(hru_gdf, cluster_zoom)
    marker_cluster, marker_cluster_label_poi = create_poi_paramplot_marker_cluster(
        poi_df,
        Folium_maps_dir,
        cluster_zoom,
        par_sel,
    )

    hru_map.add_to(m3)

    hw_basins_map = folium.GeoJson(
        HW_basins, style_function=hw_basin_style, name="HW basin boundary"
    ).add_to(m3)

    marker_cluster_label_hru.add_to(m3)

    seg_map = create_segment_map_show(seg_gdf)
    seg_map.add_to(m3)
    marker_cluster.add_to(m3)
    marker_cluster_label_poi.add_to(m3)

    plugins.Fullscreen(position="topleft").add_to(m3)
    folium.LayerControl(collapsed=True, position="bottomright", autoZIndex=True).add_to(
        m3
    )

    if not color_bar:
        scale_bar_txt = f"All {par_sel} values are {same_value} in the model domain. No value scale bar rendered."
        fig = None  # fig, ax = plt.subplots(figsize=(18, 0.5))
    else:
        scale_bar_txt = f"Values for {par_sel} range from {value_min:.2f} to {value_max:.2f} {pdb.get(par_sel).meta['units']} in the model domain."

    if mo_sel is None:
        mo_txt = " "
        map_file = f"{html_maps_dir}/{par_sel}_map.html"
    else:
        mo_txt = f"{mo_name} "
        map_file = f"{html_maps_dir}/{par_sel}_{mo_name}_map.html"

    title_html = f"<h1 style='position:absolute;z-index:100000;font-size: 28px;left:26vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '><strong>The NHM {subdomain} model: {mo_txt}{par_sel}</strong><br><h1 style='position:absolute;z-index:100000;font-size: 20px;left:31vw;right:5vw; top:4vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '> {pdb.get(par_sel).meta['help']}. {scale_bar_txt}</h1>"

    #add custom legend
    legend_file = pl.Path(root_dir/"data_dependencies/map_custom_explanations/nb_5.png").resolve()
    with open(legend_file, "rb") as lf:
        # open in binary mode, read bytes, encode, decode obtained bytes as utf-8 string
        b64_content = base64.b64encode(lf.read()).decode("utf-8")
        del lf
    legend_image = FloatImage(
        image="data:image/png;base64,{}".format(b64_content),
        bottom=15,
        left=1,
        style="position:fixed; width:2.116in; height:1in;",
    )
    m3.add_child(legend_image)
    m3.get_root().html.add_child(Element(title_html))

    m3.add_child(val_bar_image)

    m3.save(map_file)

    make_webbrowser_map(map_file)

    return map_file


def make_var_map(
    *,
    root_dir,
    out_dir,
    output_var_sel,
    plot_start_date,
    plot_end_date,
    water_years,
    hru_gdf,
    poi_df,
    poi_id_sel,
    seg_gdf,
    html_maps_dir,
    year_list,
    sel_year,
    Folium_maps_dir,
    HW_basins,
    subdomain,
):

    """
    Makes folium.map of selected variable's values for HRUs in the NHM subdomain.

    Parameters
    ----------
    out_dir : pathlib Path class 
        Path where model output data are stored, e.g., model_dir / "output". 
    output_var_sel : string
        Selected variable to display on the map.
    plot_start_date : string 
        First date to plot. 
    plot_end_date : string 
        Last date to plot. 
    water_years : list 
        Water years to plot. 
    hru_gdf : geopandas GeoDataFrame 
        HRU geodataframe from GIS data in subdomain. 
    poi_df : pandas DataFrame
        Pandas DataFrame containing gages from the parameter file.
    poi_id_sel : string
        Gage id of selected gage
    seg_gdf : geopandas GeoDataFrame
        Segments geodataframe from GIS data in subdomain and segment parameter values from parameter file.
    html_maps_dir : pathlib Path class 
        Path where html maps are exported.
    year_list : [int]
        List of years for annual values for the variable.
    sel_year : int
        Selected year   
    Folium_maps_dir : pathlib Path class
        Path to a folder being used as temp file storage. All files written here will be deleted.
    HW_basins : geopandas polyline dataset
        Polyline file that was made using HW_basins_gdf.boundary.
    subdomain : string 
        NHM subdomain name. 
              
    Returns
    -------
    map_file : folium.map
        Folium.map that displays the selected variable's values for HRUs in the NHM subdomain model.    
    """
    
    # Create a geoDataFrame of the output variable's annual values to map
    gdf_output_var_annual, value_min, value_max, var_units, var_desc = (
        create_sum_var_annual_gdf(
            out_dir,
            output_var_sel,
            plot_start_date,
            plot_end_date,
            water_years,
            hru_gdf,
            year_list,
        )
    )

    # Load standard map settings and elements
    pfile_lat, pfile_lon, zoom, cluster_zoom = folium_map_elements(
        hru_gdf, poi_df, poi_id_sel
    )
    USGSHydroCached_layer, USGStopo_layer, Esri_WorldImagery, OpenTopoMap = (
        folium_map_tiles()
    )
    minimap = create_minimap()

    # Clear map if previously created
    m3 = folium.Map()

    # Create map
    m3 = folium.Map(
        location=[pfile_lat, pfile_lon],
        # width=1000, height=600,
        tiles=USGSHydroCached_layer,
        zoom_start=zoom,
        control_scale=True,
    )

    # Add layers to the map
    USGStopo_layer.add_to(m3)
    OpenTopoMap.add_to(m3)
    Esri_WorldImagery.add_to(m3)

    # Add widgets
    m3.add_child(minimap)
    m3.add_child(MeasureControl(position="bottomright"))

    # Create/Add scale bar and hru map object
    hru_map, val_bar_image, value_min, value_max, same_value, color_bar = (
        create_annual_output_var_map(
            gdf_output_var_annual,
            output_var_sel,
            sel_year,
            var_units,
            Folium_maps_dir,
        )
    )
    hru_map.add_to(m3)

    hw_basins_map = folium.GeoJson(
        HW_basins, style_function=hw_basin_style, name="HW basin boundary"
    ).add_to(m3)

    # Create/Add hru labels
    marker_cluster_label_hru = create_hru_label(hru_gdf, cluster_zoom)
    marker_cluster_label_hru.add_to(m3)

    # Create/Add segment map
    seg_map = create_segment_map_hide(seg_gdf)
    seg_map.add_to(m3)

    # Create/Add pois
    poi_marker_cluster, poi_marker_cluster_label = create_poi_marker_cluster(
        poi_df, cluster_zoom
    )
    poi_marker_cluster.add_to(m3)
    poi_marker_cluster_label.add_to(m3)

    plugins.Fullscreen(position="topleft").add_to(m3)
    folium.LayerControl(collapsed=True, position="bottomright", autoZIndex=True).add_to(
        m3
    )

    if not color_bar:
        scale_bar_txt = f"All {output_var_sel} values are {same_value} in the model domain. No value scale bar rendered."
        fig = None  # fig, ax = plt.subplots(figsize=(18, 0.5))
    else:
        scale_bar_txt = f"Values for {output_var_sel} range from {value_min} to {value_max} {var_units} in the model domain."

    title_html = f"<h1 style='position:absolute;z-index:100000;font-size: 28px;left:26vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '><strong>The NHM {subdomain} model: {sel_year} {output_var_sel}</strong><br><h1 style='position:absolute;z-index:100000;font-size: 20px;left:31vw;right:5vw; top:4vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '> {var_desc}. {scale_bar_txt}</h1>"
    
    #add custom legend
    legend_file = pl.Path(root_dir / "data_dependencies/map_custom_explanations/nb_5.png").resolve()
    with open(legend_file, "rb") as lf:
        # open in binary mode, read bytes, encode, decode obtained bytes as utf-8 string
        b64_content = base64.b64encode(lf.read()).decode("utf-8")
        del lf
    legend_image = FloatImage(
        image="data:image/png;base64,{}".format(b64_content),
        bottom=15,
        left=1,
        style="position:fixed; width:2.116in; height:1in;",
    )
    m3.add_child(legend_image)
    
    m3.get_root().html.add_child(Element(title_html))

    m3.add_child(val_bar_image)

    map_file = f"{html_maps_dir}/{output_var_sel}_{sel_year}_map.html"
    m3.save(map_file)

    make_webbrowser_map(map_file)

    return #map_file


def make_streamflow_map(
    *,
    root_dir,
    out_dir,
    plot_start_date,
    plot_end_date,
    water_years,
    hru_gdf,
    poi_df,
    poi_id_sel,
    seg_gdf,
    html_maps_dir,
    subdomain,
    HW_basins_gdf,
    HW_basins,
    output_netcdf_filename,
):
    """
    Creates a map of the NHM subdomain model hydrofabric elements and displays monthly Kling-Gupta efficiency (KGE) values for parameter file gages.

    Parameters
    ----------
    out_dir : pathlib Path class 
        Path where model output data are stored, e.g., model_dir / "output".
    plot_start_date: string 
        First date to plot. 
    plot_end_date: string 
        Last date to plot.   
    water_years: list 
        Water years to plot. 
    hru_gdf: geopandas GeoDataFrame 
        HRU geodataframe from GIS data in subdomain. 
    poi_df : pandas DataFrame
        Pandas DataFrame containing gages from the parameter file.
    poi_id_sel: string
        Gage id of selected gage
    seg_gdf: geopandas GeoDataFrame
        Segments geodataframe from GIS data in subdomain and segment parameter values from parameter file.
    html_maps_dir: pathlib Path class 
        Path where html maps are exported.
    subdomain: string 
        NHM subdomain name.  
    HW_basins_gdf: geopandas GeoDataFrame
        NHM headwaters basins geopandas GeoDataFrame used to display caliration level of HRUs on map.
    HW_basins: geopandas polyline dataset
        Polyline file that was made using HW_basins_gdf.boundary.
    output_netcdf_filename: pathlib Path class 
        The output netCDF filename for cachefile, e.g., model_dir / "notebook_output_files/nc_files/sf_efc.nc" 
            
    Returns
    -------
    map_file: folium.map
        Folium.map that displays monthly Kling-Gupta efficiency (KGE) values for parameter file gages.    
    """

    # for this function, output_var_sel will always be seg_outflow. Set it and forget it!
    output_var_sel = "seg_outflow"

    #### Compute KGE for all gages to color the icon on the map
    # Read in simulated flows

    var_daily, sum_var_monthly, sum_var_annual, var_units, var_desc = (
        create_sum_seg_var_dataarrays(
            out_dir,
            output_var_sel,
            plot_start_date,
            plot_end_date,
            water_years,
        )
    )

    # Read in observed flows
    # Note that the model start and stop times in the control file should be the same as the observation start and stop times.
    poi_name_df, obs, obs_efc, obs_annual = create_streamflow_obs_datasets(
        output_netcdf_filename,
        plot_start_date,
        plot_end_date,
        water_years,
    )

    # Add monthly KGE to poi_df
    poi_df = calculate_monthly_kge_in_poi_df(
        obs,
        var_daily,
        poi_df,
    )

    # Load standard map settings
    pfile_lat, pfile_lon, zoom, cluster_zoom = folium_map_elements(
        hru_gdf, poi_df, poi_id_sel
    )

    USGSHydroCached_layer, USGStopo_layer, Esri_WorldImagery, OpenTopoMap = (
        folium_map_tiles()
    )

    minimap = create_minimap()

    # Clear map if previously created
    m = folium.Map()

    # Create map
    m = folium.Map(
        location=[pfile_lat, pfile_lon],
        # width=1000, height=600,
        tiles=USGSHydroCached_layer,
        zoom_start=zoom,
        control_scale=True,
    )

    # Add base map layers
    USGStopo_layer.add_to(m)
    OpenTopoMap.add_to(m)
    Esri_WorldImagery.add_to(m)

    # Add widgets
    m.add_child(minimap)
    m.add_child(MeasureControl(position="bottomright"))

    # Create and add hru calibration levels (colors)
    hru_cal_map = folium.GeoJson(
        HW_basins_gdf,  # hru_gdf_map,
        style_function=cal_style_function,
        # highlight_function = highlight_function_hru_map,
        name="HRU cal level",
        z_index_offset=40002,
    ).add_to(m)

    # Create and add hru boundaries and data
    hru_gdf["hw_id_str"] = hru_gdf.hw_id.astype(str)
    hru_map = create_hru_map(hru_gdf)
    tooltip_hru = folium.GeoJsonPopup(
        fields=["hw_id_str"], aliases=["Headwater id"], labels=True
    )
    hru_map.add_child(tooltip_hru)
    hru_map.add_to(m)

    # Create and add headwater basin boundaries
    hw_basins_map = folium.GeoJson(
        HW_basins, style_function=hw_basin_style, name="HW basin boundary"
    ).add_to(m)

    # Create/Add segment map
    seg_map = create_segment_map_hide(seg_gdf)
    seg_map.add_to(m)

    # create and add POI marker clusters (marker and label)
    marker_cluster, marker_cluster_label_poi = create_streamflow_poi_markers(
        poi_df,
    )
    marker_cluster.add_to(m)
    marker_cluster_label_poi.add_to(m)

    plugins.Fullscreen(position="topleft").add_to(m)
    folium.LayerControl(collapsed=True, position="bottomright", autoZIndex=True).add_to(
        m
    )

    title_html = f"<h1 style='position:absolute;z-index:100000;font-size: 28px;left:26vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '><strong>The NHM {subdomain} model: streamflow evaluation, Kling-Gupta efficiency (KGE)</strong><br><h1 style='position:absolute;z-index:100000;font-size: 20px;left:31vw;right:5vw; top:4vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '></h1>"


    #add custom legend
    legend_file = pl.Path(root_dir/"data_dependencies/map_custom_explanations/nb_6.png").resolve()
    with open(legend_file, "rb") as lf:
        # open in binary mode, read bytes, encode, decode obtained bytes as utf-8 string
        b64_content = base64.b64encode(lf.read()).decode("utf-8")
        del lf
    legend_image = FloatImage(
        image="data:image/png;base64,{}".format(b64_content),
        bottom=10,
        left=1,
        style="position:fixed; width:3.042in; height:2in;",
    )
    m.add_child(legend_image)
    
    m.get_root().html.add_child(Element(title_html))

    map_file = html_maps_dir / "streamflow_map.html"
    m.save(map_file)

    make_webbrowser_map(map_file)
    
    return #map_file

def create_poi_obs_marker_cluster(
    poi_df,
    cluster_zoom,
    Folium_maps_dir,
):
    """
    Creates a folium.map marker cluster object for pois(gages) and for lables, so that these two groups can be displayed and hidden in the map from the interactive legend. These are gages found in the parameter file.
    
    Parameters
    ----------
    poi_df : pandas DataFrame()
        First parameter; Pandas DataFrame() containing gages from the parameter file.
    cluster_zoom: int
        Second parameter; The zoom (out) level at whcih gages get clustered on the folium maps.
        

    Returns
    -------
    poi_marker_cluster: a folium MarkerCluster() object
        Gages from the parameter file.
    poi_marker_cluster_label: a folium MarkerCluster() object
        Gage id as labels for gages from the parameter file.
    """

    # add POI marker cluster child items for the map
    poi_marker_cluster = MarkerCluster(
        name="Model gage",
        overlay=True,
        control=True,
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
    )
    poi_marker_cluster_label = MarkerCluster(
        name="Model gage ID",
        overlay=True,
        control=True,
        show=False,  # False will not draw the child upon opening the map, but have it to draw in the Layer control.
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
    )
    ##add POI markers and labels using row df.interowss loop
    for idx, row in poi_df.iterrows():

##############        #####
        #for idx, row in poi_df.iterrows():
        poi_id = row["poi_id"]
        obs_plot_file = Folium_maps_dir / f"{poi_id}_streamflow_obs.txt"
        # Read ploty plot of each poi
        with open(obs_plot_file, "r") as f:
            div_txt = f.read()
    
        # Create html code to insert the plotly plot to the folium pop up
        html = (
            """
        <html>
        <head>
             <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        </head>
        <body>
             <!-- Output from the Python script above: -->"""
            + div_txt
            + """</body>
        </html>"""
        )
    
        # Add the Plots to the popup
        iframe = folium.IFrame(
            html=html,
            width=525,
            height=325,
        )
        # popup = folium.Popup(iframe, max_width=3250,parse_html=True)

##############
        
        text = f'{row["poi_id"]}'
        label_lat = row["latitude"]  # -0.01
        label_lon = row["longitude"]

        marker_label = folium.map.Marker(
            [label_lat, label_lon],
            icon=DivIcon(
                icon_size=(10, 10),  # (150,36),
                icon_anchor=(0, 0),
                html='<div style="font-size: 12pt; font-weight: bold">%s</div>' % text,
            ),
        ).add_to(poi_marker_cluster_label)

        marker = folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            name=row["poi_id"],
            popup=folium.Popup(
                iframe,
                # max_width=500,
                # max_height=300,
                parse_html=True,
            ),
            tooltip= f'<font size="3px">{row["poi_id"]} ({row["poi_agency"]}) on segment: {row["nhm_seg"]}<br>{row["poi_name"]}<br></font>',
            # popup=folium.Popup(
            #     f'<font size="3px">{row["poi_id"]} ({row["poi_agency"]})<br>{row["poi_name"]}<br> on <b>segment </b>{row["nhm_seg"]}</font>',
            #     max_width=280,
            #     max_height=2000,
            # ),
            radius=3,
            weight=2,
            color="black",
            fill=True,
            fill_color="Black",
            fill_opacity=1.0,
        ).add_to(poi_marker_cluster)

    return poi_marker_cluster, poi_marker_cluster_label

def create_non_poi_obs_marker_cluster(
    poi_df,
    nwis_gages_aoi,
    gages_df,
    Folium_maps_dir,
    param_filename,
    cluster_zoom: pd.DataFrame,
) -> tuple[folium.plugins.MarkerCluster, folium.plugins.MarkerCluster]:

    """
    Creates a folium.map marker cluster object for pois(gages) and for gage id lables, so that these two groups can be displayed and hidden in the map from the interactive legend. These gages are gages NOT in the parameter file.
    
    Parameters
    ----------
    poi_df : pandas DataFrame()
        Pandas DataFrame() containing gages from the parameter file.
    nwis_gages_aoi : Pandas DataFrame()
        Pandas DataFrame() containing gages from NWIS in the subdomain.
    gages_df : pandas DataFrame() 
        Represents data pertaining to subdomain gages in parameter file, NWIS, and others. 
    cluster_zoom : int
        Second parameter; The zoom (out) level at whcih gages get clustered on the folium maps.
        
    Returns
    -------
    non_poi_marker_cluster : a folium MarkerCluster() object
        Gages in the subdomain NOT in the parameter file.
    non_poi_marker_cluster_label : a folium MarkerCluster() object
        Gage id as labels for gages in the subdomain NOT in the parameter file.
    """

    # add non-poi gages marker cluster child items for the map
    non_poi_marker_cluster = MarkerCluster(
        name="Prospective gage",
        overlay=True,
        control=True,
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
    )
    non_poi_marker_cluster_label = MarkerCluster(
        name="Prospective gage ID",
        overlay=True,
        control=True,
        show=False,  # False will not draw the child upon opening the map, but have it to draw in the Layer control.
        icon_create_function=None,
        disableClusteringAtZoom=cluster_zoom,
    )

    ##add Non-poi gage markers and labels using row df.interowss loop
    gages_list = gages_df.index.to_list()
    additional_gages = list(set(gages_list) - set(poi_df.poi_id))
    gages_df.reset_index(inplace=True, drop=False)

    for idx, row in gages_df.iterrows():
        if row["poi_id"] in additional_gages:
#########
            poi_id = row["poi_id"]
            obs_plot_file = Folium_maps_dir / f"{poi_id}_streamflow_obs.txt"
            # Read ploty plot of each poi
            with open(obs_plot_file, "r") as f:
                div_txt = f.read()
        
            # Create html code to insert the plotly plot to the folium pop up
            html = (
                """
            <html>
            <head>
                 <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
            </head>
            <body>
                 <!-- Output from the Python script above: -->"""
                + div_txt
                + """</body>
            </html>"""
            )
        
            # Add the Plots to the popup
            iframe = folium.IFrame(
                html=html,
                width=525,
                height=325,
            )
            # popup = folium.Popup(iframe, max_width=3250,parse_html=True)
    ######

            text = f'{row["poi_id"]}'
            label_lat = row["latitude"]  # -0.01
            label_lon = row["longitude"]

            marker_label = folium.map.Marker(
                [label_lat, label_lon],
                icon=DivIcon(
                    icon_size=(10, 10),  # (150,36),
                    icon_anchor=(0, 0),
                    html='<div style="font-size: 12pt; font-weight: bold">%s</div>'
                    % text,
                ),
            ).add_to(non_poi_marker_cluster_label)

            marker = folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                name=row["poi_id"],
                popup=folium.Popup(
                iframe,
                # max_width=500,
                # max_height=300,
                parse_html=True,
                ),
                # popup=folium.Popup(
                #     f'<font size="3px">{row["poi_id"]} ({row["poi_agency"]})<br>{row["poi_name"]}<br></font>',
                #     max_width=280,
                #     max_height=2000,
                # ),
                tooltip= f'<font size="3px">{row["poi_id"]} ({row["poi_agency"]}--Not in {param_filename.name})<br>{row["poi_name"]}<br></font>',
                radius=3,
                weight=2,
                color="gray",
                fill=True,
                fill_color="Gray",
                fill_opacity=1.0,
            ).add_to(non_poi_marker_cluster)
        else:
            pass

    return non_poi_marker_cluster, non_poi_marker_cluster_label
