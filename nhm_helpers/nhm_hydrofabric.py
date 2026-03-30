import warnings
import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
from rich import pretty
from nhm_helpers.nhm_assist_utilities import (fetch_nwis_gage_info,
                                              make_HW_cal_level_files)
pretty.install()
warnings.filterwarnings("ignore")


def create_hru_gdf(
    *,
    root_dir,
    model_dir,
    GIS_format,
    param_filename,
    nhru_params,
    nhru_nmonths_params,
):
    """
    Creates hru gdf for selected hru parameters from the parameter file.
    Selected in notebook 0a.
    
    Note: Layer npoigages includes the poi gages that were included in the model and are limited.
    Since poi gages will be added to the model parameter file, we provide another method to retrieve poi metadata, such as
    latitude (lat) and longitude (lon), for poi gages listed in the parameter file that uses NWIS and a supplemental gage ref
    table for gages that do not occur in NWIS. Locations may NOT be located exactly on the NHM segment. The gages' assigned
    segment is displayed in the popup window when the gage icon is clicked.

    Parameters
    ----------
    NHM_dir : pathlib Path class
        Path to the NHM folder, e.g., notebook_dir / "data_dependencies/NHM_v1_1"
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    GIS_format : str
        String that specifies format of spatial data from subdomain model GIS folder; one of ".shp" or ".gpkg".
    param_filename : pathlib Path class
        Path to parameter file.        
    nhru_params : list
        Parameters dimensioned by HRU only.    
    nhru_nmonths_params : list
        Parameters dimensioned by HRU and month.

    Returns
    -------
    hru_gdf : geopandas GeoDataFrame
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    hru_text : str
        Information regarding HRUs displayed for user.
    hru_cal_level_txt : str
        Information regarding HRUs calibration levels displayed for user.
        
    """

    # List of bynhru parameters to retrieve for the Notebook interactive maps.
    hru_params = [
        "hru_lat",  # the latitude if the hru centroid
        "hru_lon",  # the longitude if the hru centroid
        "hru_area",
        "hru_segment_nhm",  # The nhm_id of the segment recieving flow from the HRU
    ]
    gdb_hru_params = hru_params + nhru_params + nhru_nmonths_params

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

    """
    Loading some pyPRMS helpers for parameter metadata: units, descriptions, etc.
    """
    prms_meta = MetaData().metadata  # loads metadata functions for pyPRMS
    pdb = ParameterFile(
        param_filename, metadata=prms_meta, verbose=False
    )  # loads parmaeterfile functions for pyPRMS

    if GIS_format == ".gpkg":
        hru_gdb = gpd.read_file(
            f"{model_dir}/GIS/model_layers.gpkg", layer="nhru"
        )  # Reads HRU file to Geopandas.

    if GIS_format == ".shp":
        hru_gdb = gpd.read_file(
            f"{model_dir}/GIS/model_nhru.shp"
        )  # Reads HRU file to Geopandas.
        hru_gdb = hru_gdb.set_index("nhm_id", drop=False).fillna(
            0
        )  # Set an index for HRU geodatabase.
        hru_gdb.index.name = "index"  # Index column must be renamed of the hru

    hru_gdb = hru_gdb.to_crs(crs)  # reprojects to the defined crs projection

    # Create a dataframe for parameter values
    first = True
    for vv in gdb_hru_params:
        if (
            first
        ):  # this creates the first iteration for the following iterations to concantonate to
            df = pdb.get_dataframe(vv)
            first = False
        else:
            df = pd.concat([df, pdb.get_dataframe(vv)], axis=1)  # , ignore_index=True)

    df.reset_index(inplace=True)
    df["model_idx"] = (
        df.index + 1
    )  #'model_idx' created here is the order of the parameters in the parameter file.
    # df

    # Join the HRU params values to the HRU geodatabase using Merge
    hru_gdb = pd.merge(df, hru_gdb, on="nhm_id")

    # Create a Goepandas GeoDataFrame for the HRU geodatabase
    hru_gdf = gpd.GeoDataFrame(hru_gdb, geometry="geometry")

    """
    NHM Calibration Levels for HRUs: (those hrus calibrated in byHW and byHWobs parts)

    HW basins were descritized using a drainage area maxiumum and minimum; HW HRUs, segments, outlet segment, and drainage area
    available.

    Gages used in byHWobs calibration, Part 3, for selected headwaters are also provided here.

    FILES AND TABLES IN THIS SECTION ARE CONUS COVERAGE and will be subsetted later.
    """

    #### READ table (.csv) of HRU calibration level file
    hru_cal_levels_df = pd.read_csv(f"{root_dir}/data_dependencies/NHM_v1_1/nhm_v1_1_HRU_cal_levels.csv").fillna(0)
    hru_cal_levels_df["hw_id"] = hru_cal_levels_df.hw_id.astype("int32")

    hru_gdf = hru_gdf.merge(hru_cal_levels_df, on="nhm_id")
    hru_gdf["hw_id"] = hru_gdf.hw_id.astype("int32")

    hru_text = f", and {len(hru_gdf.index)} [bold]HRUs[/bold]."
    hru_cal_level_txt = f'{hru_gdf[hru_gdf["level"] > 1]["level"].count()} HRUs are within HWs, and {hru_gdf[hru_gdf["level"] > 2]["level"].count()} are within HW calibrated with streamflow observations.'

    return hru_gdf, hru_text, hru_cal_level_txt


def create_segment_gdf(
    *,
    model_dir,
    GIS_format,
    param_filename,
):
    """
    Creates segment gdf for selected segment parameters from the parameter file.
    Selected in notebook 0a.

    Parameters
    ----------
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    GIS_format : str
        String that specifies format of spatial data from subdomain model GIS folder; one of ".shp" or ".gpkg".
    param_filename : pathlib Path class
        Path to parameter file. 

    Returns
    -------
    seg_gdf : geopandas GeoDataFrame
        Segments geodataframe from GIS data in subdomain and segment parameter values from parameter file.
    seg_txt : str
        Number of segments provided to user.
        
    """

    # List of parameters values to retrieve for the segments.
    seg_params = ["tosegment_nhm", "tosegment", "seg_length", "obsin_segment"]

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

    """
    Loading some pyPRMS helpers for parameter metadata: units, descriptions, etc.
    """
    prms_meta = MetaData().metadata  # loads metadata functions for pyPRMS
    pdb = ParameterFile(
        param_filename, metadata=prms_meta, verbose=False
    )  # loads parmaeterfile functions for pyPRMS

    if GIS_format == ".gpkg":
        seg_gdb = gpd.read_file(
            f"{model_dir}/GIS/model_layers.gpkg", layer="nsegment"
        ).fillna(
            0
        )  # Reads segemnt file to Geopandas.

    if GIS_format == ".shp":
        seg_gdb = gpd.read_file(f"{model_dir}/GIS/model_nsegment.shp").fillna(0)
        seg_gdb = seg_gdb.set_index(
            "nhm_seg", drop=False
        )  # Set an index for segment geodatabase(GIS)
        seg_gdb.index.name = "index"  # Index column must be renamed of the hru

    seg_gdb = seg_gdb.to_crs(crs)  # reprojects to the defined crs projection

    # Create a dataframe for parameter values
    first = True
    for vv in seg_params:
        if first:
            df = pdb.get_dataframe(vv)
            first = False
        else:
            df = pd.concat([df, pdb.get_dataframe(vv)], axis=1)  # , ignore_index=True)

    df.reset_index(inplace=True)
    df["model_idx"] = df.index + 1
    df.index.name = "index"  # Index column must be renamed

    # Join the HRU params values to the HRU geodatabase using Merge
    seg_gdb = pd.merge(df, seg_gdb, on="nhm_seg")

    # Create a Goepandas GeoDataFrame for the HRU geodatabase
    seg_gdf = gpd.GeoDataFrame(seg_gdb, geometry="geometry")

    seg_txt = f", {len(seg_gdf.index)} [bold]segments[/bold]"

    return seg_gdf, seg_txt


def create_poi_df(
    *,
    root_dir,
    model_dir,
    param_filename,
    control_file_name,
    hru_gdf,
    gages_file,
    default_gages_file,
    nwis_gage_nobs_min,
    seg_gdf,
):
    """
    Create dataframe containing gages listed in parameter file.

    Parameters
    ----------
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    param_filename : pathlib Path class
        Path to parameter file.
    control_file_name : pathlib Path class
        Path object to the control file.
    hru_gdf : geopandas GeoDataFrame
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    gages_file : pathlib Path class
        Path to file containing gage information from NWIS for the gages in the parameter file and user modified information.
    default_gages_file : pathlib Path class
        Path to file containing gage information from NWIS for the gages in the parameter file.
    nwis_gage_nobs_min : int
        Minimum number of days for NWIS gage to be considered as potential poi.

    Returns
    -------
    poi_df : pandas DataFrame
        Dataframe containing gages from the parameter file.

    """
    """
    Loading some pyPRMS helpers for parameter metadata: units, descriptions, etc.
    """
    prms_meta = MetaData().metadata  # loads metadata functions for pyPRMS
    pdb = ParameterFile(
        param_filename, metadata=prms_meta, verbose=False
    )  # loads parmaeterfile functions for pyPRMS

    """
    Create a dataframe of all POI-related parameters from the parameter file.
    """

    poi = pdb["poi_gage_id"].as_dataframe
    poi = poi.merge(
        pdb["poi_gage_segment"].as_dataframe, left_index=True, right_index=True
    )
    poi = poi.merge(pdb["poi_type"].as_dataframe, left_index=True, right_index=True)
    poi = poi.merge(
        pdb["nhm_seg"].as_dataframe, left_on="poi_gage_segment", right_index=True
    )

    poi.rename(columns={"poi_gage_id": "poi_id"}, inplace=True)

    """
    Create a dataframe for poi_gages from the parameter file with NWIS gage information data.

    """
    nwis_gage_info_aoi = fetch_nwis_gage_info(
        root_dir=root_dir,
        model_dir=model_dir,
        control_file_name=control_file_name,
        nwis_gage_nobs_min=nwis_gage_nobs_min,
        hru_gdf=hru_gdf,
        seg_gdf=seg_gdf,
    )

    poi = poi.merge(nwis_gage_info_aoi, left_on="poi_id", right_on="poi_id", how="left")
    poi_df = pd.DataFrame(poi)  # Creates a Pandas DataFrame

    """
    This reads in the csv file that has the gages used to calibrate the byHWobs part for CONUS.
    Read in format for station file columns needed (You may need to tailor this to the particular file.
    """
    col_names = [
        "poi_id",
        #'poi_name',
        "latitude",
        "longitude",
        #'drainage_area',
        #'drainage_area_contrib'
    ]
    col_types = [
        np.str_,
        # np.str_,
        float,
        float,
        # float,
        # float
    ]
    cols = dict(
        zip(col_names, col_types)
    )  # Creates a dictionary of column header and datatype called below.

    byHWobs_poi_df = pd.read_csv(
        root_dir / "data_dependencies/NHM_v1_1/nhm_v1_1_byhwobs_cal_gages.csv",
        sep="\t",
        dtype=cols,
    ).fillna(0)

    # Identify the byHWobs calibration gages in our current poi database (ammended in the model prams file to include more gages)
    poi_df["nhm_calib"] = "N"
    poi_df.loc[poi_df["poi_id"].isin(byHWobs_poi_df["poi_id"]), "nhm_calib"] = "Y"

    """
    Updates the poi_df with user altered metadata in the gages.csv file, if present, or the default_gages.csv file
    """

    if gages_file.exists():
        gages_df, gages_txt, gages_txt_nb2 = read_gages_file(
            model_dir=model_dir,
            poi_df=poi_df,
            gages_file=gages_file,
        )

        for idx, row in poi_df.iterrows():
            """
            Checks the gages_df for missing meta data and replace.
            """
            columns = ["latitude", "longitude", "poi_name", "poi_agency"]
            for item in columns:
                if pd.isnull(row[item]):
                    new_poi_id = row["poi_id"]
                    new_item = gages_df.loc[
                        gages_df.index == row["poi_id"], item
                    ].values[0]
                    poi_df.loc[idx, item] = new_item

    else:
        pass
    if default_gages_file.exists():
        gages_df, gages_txt, gages_txt_nb2 = read_gages_file(
            model_dir=model_dir,
            poi_df=poi_df,
            gages_file=gages_file,
        )

        for idx, row in poi_df.iterrows():
            """
            Checks the gages_df for missing meta data and replace.
            """
            columns = ["latitude", "longitude", "poi_name", "poi_agency"]
            for item in columns:
                if pd.isnull(row[item]):
                    new_poi_id = row["poi_id"]
                    new_item = gages_df.loc[
                        gages_df.index == row["poi_id"], item
                    ].values[0]
                    poi_df.loc[idx, item] = new_item

    else:
        pass

    return poi_df


def create_default_gages_file(
    *,
    root_dir,
    model_dir,
    control_file_name,
    nwis_gage_nobs_min,
    hru_gdf,
    poi_df,
    seg_gdf,
):

    nwis_gages_aoi = fetch_nwis_gage_info(
        root_dir=root_dir,
        model_dir=model_dir,
        control_file_name=control_file_name,
        nwis_gage_nobs_min=nwis_gage_nobs_min,
        hru_gdf=hru_gdf,
        seg_gdf=seg_gdf,
    )

    """
    Create default_gages.csv for your subdomain model.
    NHM-Assist notebooks will display gages using the default gages file (default_gages.csv), if a modified gages file (gages.csv) is lacking.
    By default, this file will be composed of:

        1) the gages listed in the parameter file (poi_gages), and
        2) all streamflow gages from NWIS in the subdomain model that have at least user-specified minimum number of obervations.

    Note: all metadata in the default gages file is from NWIS if the gage is found NWIS.
    Note: Time-series data for streamflow observations will be collected using this gage list and the time range in the control file.
    Note: Initially, all gages listed in the parameter file exist in NWIS.

    Parameters
    ----------
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    control_file_name : pathlib Path class
        Path object to the control file.
    nwis_gage_nobs_min : int
        Minimum number of days for NWIS gage to be considered as potential poi.
    hru_gdf : geopandas GeoDataFrame
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    poi_df : pandas DataFrame
        Dataframe containing gages from the parameter file.

    Returns
    -------
    default_gages_file : pathlib Path class
        Path to file containing gage information from NWIS for the gages in the parameter file.

    """
    """ Remove NWIS gages with no daily streamflow data after the st_date in the control file """
    nwis_cache_file = model_dir / "notebook_output_files" / "nc_files" / "nwis_cache.nc"
    with xr.open_dataset(nwis_cache_file) as NWIS_ds:
        NWIS_df = NWIS_ds.to_dataframe()
        NWIS_obs_list = list(NWIS_df.index.get_level_values(0).unique())
        # print(NWIS_obs_list)
        del NWIS_ds
    """ But we need to add gages without obs back in to the list, if they are in the param file """
    keep_list = list(set(NWIS_obs_list + poi_df.poi_id.to_list()))
    #print(keep_list)

    #_nwis_gages_aoi = nwis_gages_aoi.loc[nwis_gages_aoi["poi_id"].isin(keep_list)]


    """Read in additional non-nwis gages from the resource gage file. These are a list of user requested gages that may or may not be in the parameter file or the nwis gage file, and likely include non NWIS gages.
    """
    resource_gages_file = model_dir / "resource_gages.csv"

    #if len(drop_list) > 0:
    nan_list = [np.nan] * len(keep_list)
    default_gages_df = pd.DataFrame({'poi_id': keep_list,
                                     'poi_agency': nan_list,
                                     'poi_name': nan_list,
                                     'latitude': nan_list, 
                                     'longitude': nan_list,
                                     'drainage_area': nan_list,
                                     'drainage_area_contrib': nan_list}
                                                  )

    if resource_gages_file.exists():
        col_names = [
            "poi_id",
            "poi_agency",
            "poi_name",
            "latitude",
            "longitude",
            "drainage_area",
            "drainage_area_contrib",
        ]
        col_types = [np.str_, np.str_, np.str_, float, float, float, float]
        cols = dict(
            zip(col_names, col_types)
        )
        resource_gages_file_df = pd.read_csv(resource_gages_file, dtype=cols)

    else:    
        resource_gages_file_df = pd.DataFrame({'poi_id': [np.nan],
                                               'poi_agency': [np.nan],
                                               'poi_name': [np.nan],
                                               'latitude': [np.nan], 
                                               'longitude': [np.nan],
                                               'drainage_area': [np.nan],
                                               'drainage_area_contrib': [np.nan]}
                                                    )
        #print(resource_gages_file_df)

    for idx, row in default_gages_df.iterrows():
        columns = ["latitude", "longitude", "poi_name", "poi_agency"]
        check_list = nwis_gages_aoi["poi_id"].to_list()
        for item in columns:
            if pd.isnull(row[item]):
                new_poi_id = row["poi_id"]
                if new_poi_id in check_list:
                    new_item = nwis_gages_aoi.loc[
                        nwis_gages_aoi.poi_id == new_poi_id, item].values[0]
                    default_gages_df.loc[idx, item] = new_item

    for idx, row in default_gages_df.iterrows():
        columns = ["latitude", "longitude", "poi_name", "poi_agency"]
        check_list = resource_gages_file_df["poi_id"].to_list()
        #print(check_list)
        for item in columns:
            if pd.isnull(row[item]):
                new_poi_id = row["poi_id"]
                if new_poi_id in check_list:
                    new_item = resource_gages_file_df.loc[
                        resource_gages_file_df.poi_id == new_poi_id, item
                    ].values[0]
                    default_gages_df.loc[idx, item] = new_item
                else:
                    pass #print(f"Gage {new_poi_id} is not in the resource_gages.csv.")

    #drop from defualt missing data
    cols = ["latitude", "longitude", "poi_name", "poi_agency"]
    mask_missing = default_gages_df[cols].isnull().any(axis=1)

    for poi_id in default_gages_df.loc[mask_missing, "poi_id"]:
        print(
            f"Gage {poi_id} was dropped from the default_gages.csv "
            "due to missing metadata. Add to resource_gages_file.csv and rerun notebook."
        )

    missing_meta_df = default_gages_df.loc[mask_missing]
    default_gages_df = default_gages_df.loc[~mask_missing]

    resource_gages_file_df = pd.concat([resource_gages_file_df, missing_meta_df])

    #resource_gages_file_df.loc[resource_gages_file_df.index[: len(missing_meta_poi_ids)], "poi_id"] = missing_meta_poi_ids            

    default_gages_file = model_dir / "default_gages.csv"
    default_gages_df.to_csv(default_gages_file, index=False)
    resource_gages_file_df.to_csv(resource_gages_file, index=False)

    return default_gages_file


def read_gages_file(
    *,
    model_dir,
    poi_df,
    gages_file,
):
    """
    Read modified gages file.
    If there are gages in the parameter file that are not in NWIS (USGS gages), then latitude, longitude, and poi_name must be provided from another source,
    and appended to the "default_gages.csv" file. Once editing is complete, that file can be renamed "gages.csv"and will be used as the gages file.
    If NO gages.csv is made, the default_gages.csv will be used.

    Parameters
    ----------
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    poi_df : pandas DataFrame
        Dataframe containing gages from the parameter file.
    gages_file : pathlib Path class
        Path to file containing gage information from NWIS for the gages in the parameter file.
        
    Returns
    -------
    gages_df : pandas DataFrame
        Represents data pertaining to subdomain gages in parameter file, NWIS, and others.
    gages_txt : str
        Informational feedback printed in notebooks.
    gages_txt_nb2 : str
        Informational feedback printed in notebooks.
        
    """

    default_gages_file = model_dir / "default_gages.csv"

    # Read in station file columns needed (You may need to tailor this to the particular file.
    col_names = [
        "poi_id",
        "poi_agency",
        "poi_name",
        "latitude",
        "longitude",
        "drainage_area",
        "drainage_area_contrib",
    ]
    col_types = [np.str_, np.str_, np.str_, float, float, float, float]
    cols = dict(
        zip(col_names, col_types)
    )  # Creates a dictionary of column header and datatype called below.

    if gages_file.exists():

        gages_df = pd.read_csv(gages_file, dtype=cols)

        # Make poi_id the index
        # gages_df["poi_id"] = gages_df.poi_id.astype(str)
        gages_df.set_index("poi_id", inplace=True)

        gages_agencies_txt = ", ".join(
            f"{item}" for item in list(set(gages_df.poi_agency))
        )
        pois_agencies_txt = ", ".join(
            f"{item}" for item in list(set(poi_df.poi_agency))
        )

        gages_txt_nb2 = f"NHM-Assist notebook 2_Model_Hydrofabric_Visualization.ipynb will display {len(gages_df)} [bold]gages managed by {gages_agencies_txt}[/bold] from the [bold]modified gages file (gages.csv)[/bold]."
        gages_txt = f"The parameter file contains {len(poi_df.index)} [bold]gages[/bold] managed by {pois_agencies_txt}"

        """
        Checks the gages_df for missing meta data.
        """
        columns = ["latitude", "longitude", "poi_name", "poi_agency"]
        for item in columns:
            if pd.isnull(gages_df[item]).values.any():
                subset = gages_df.loc[pd.isnull(gages_df[item])]
                gages_txt_nb2 += f" The gages.csv is missing {item} data for {len(subset)} gages. Add missing data to the file and rename gages.csv."
            else:
                pass
    else:
        gages_df = pd.read_csv(default_gages_file, dtype=cols)

        # Make poi_id the index
        gages_df.set_index("poi_id", inplace=True)

        gages_agencies_txt = ", ".join(
            f"{item}" for item in list(set(gages_df.poi_agency))
        )
        pois_agencies_txt = ", ".join(
            f"{item}" for item in list(set(poi_df.poi_agency))
        )

        gages_txt_nb2 = f"NHM-Assist notebook 2_Model_Hydrofabric_Visualization.ipynb will display [bold]{len(gages_df)} gages managed by {gages_agencies_txt}[/bold] from the [bold]default gages file (default_gages.csv)[/bold]."
        gages_txt = f"The parameter file contains {len(poi_df.index)} [bold]gages[/bold] managed by {pois_agencies_txt}"

        """
        Checks the gages_df for missing meta data.
        """
        columns = ["latitude", "longitude", "poi_name", "poi_agency"]
        gages_txt_nb2 = " All gages have required metadata in the default_gages.csv."
        for item in columns:
            if pd.isnull(gages_df[item]).values.any():
                gages_txt_nb2 = " Gages in the default_gages.csv are missing metadata. Add missing data to the file and rename to gages.csv before running NHM-Assist notebook 2_Model_Hydrofabric_Visualization.ipynb."
                # subset = gages_df.loc[pd.isnull(gages_df[item])]
                # items_list += f"{item},"
                # subset_txt += f"{subset},"
                # gages_txt_nb2 += f" The default_gages.csv is missing {item} data for {len(subset)} gages. Add missing data to the file and rename gages.csv."
            else:
                pass

    return gages_df, gages_txt, gages_txt_nb2


def make_hf_map_elements(
    *,
    root_dir,
    model_dir,
    GIS_format,
    param_filename,
    control_file_name,
    nwis_gages_file,
    gages_file,
    default_gages_file,
    nhru_params,
    nhru_nmonths_params,
    nwis_gage_nobs_min,
):
    """
    Packages all elements required for the hydrofabric map.

    Parameters
    ----------
    NHM_dir : pathlib Path class
        Path to the NHM folder, e.g., notebook_dir / "data_dependencies/NHM_v1_1"
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    GIS_format : str
        String that specifies format of spatial data from subdomain model GIS folder; one of ".shp" or ".gpkg".
    param_filename : pathlib Path class
        Path to parameter file.
    control_file_name : pathlib Path class
        Path object to the control file.
    nwis_gages_file : pathlib Path class
        Path to NWIS data, e.g., model_dir / "NWISgages.csv"
    gages_file : pathlib Path class
        Path to file containing gage information from NWIS for the gages in the parameter file.
    default_gages_file : pathlib Path class
        Path to file containing gage information from NWIS for the gages in the parameter file.
    nhru_params : list
        Parameters dimensioned by HRU only.   
    nhru_nmonths_params : list
        Parameters dimensioned by HRU and month.
    nwis_gage_nobs_min : int
        Minimum number of days for NWIS gage to be considered as potential poi.
    
    Returns
    -------
    hru_gdf : geopandas GeoDataFrame
        HRU geodataframe from GIS data in subdomain.
    hru_txt : str
        Informational feedback printed in notebooks.   
    hru_cal_level_txt : str
        Informational feedback printed in notebooks.
    seg_gdf : geopandas GeoDataFrame
        Segments geodataframe from GIS data in subdomain and segment parameter values from parameter file.
    seg_txt : str
        Informational feedback printed in notebooks.
    nwis_gages_aoi : Pandas DataFrame()
        Pandas DataFrame() containing gages from NWIS in the subdomain.
    poi_df : pandas DataFrame
        Dataframe containing gages from the parameter file.
    gages_df : pandas DataFrame
        Represents data pertaining to subdomain gages in parameter file, NWIS, and others.
    gages_txt : str
        Informational feedback printed in notebooks.
    gages_txt_nb2 : str
        Informational feedback printed in notebooks.
    HW_basins_gdf : geopandas GeoDataFrame
        NHM headwaters basins geopandas GeoDataFrame used to display caliration level of HRUs on map.
    HW_basins : geopandas polyline dataset
        Polyline file that was made using HW_basins_gdf.boundary
    
    """
    hru_gdf, hru_txt, hru_cal_level_txt = create_hru_gdf(
        root_dir=root_dir,
        model_dir=model_dir,
        GIS_format=GIS_format,
        param_filename=param_filename,
        nhru_params=nhru_params,
        nhru_nmonths_params=nhru_nmonths_params,
    )

    seg_gdf, seg_txt = create_segment_gdf(
        model_dir=model_dir,
        GIS_format=GIS_format,
        param_filename=param_filename,
    )

    poi_df = create_poi_df(
        root_dir=root_dir,
        model_dir=model_dir,
        param_filename=param_filename,
        control_file_name=control_file_name,
        hru_gdf=hru_gdf,
        gages_file=gages_file,
        default_gages_file=default_gages_file,
        nwis_gage_nobs_min=nwis_gage_nobs_min,
        seg_gdf=seg_gdf,
    )
    nwis_gages_aoi = fetch_nwis_gage_info(
        root_dir=root_dir,
        model_dir=model_dir,
        control_file_name=control_file_name,
        nwis_gage_nobs_min=nwis_gage_nobs_min,
        hru_gdf=hru_gdf,
        seg_gdf=seg_gdf,
    )

    gages_df, gages_txt, gages_txt_nb2 = read_gages_file(
        model_dir=model_dir,
        poi_df=poi_df,
        gages_file=gages_file,
    )

    HW_basins_gdf, HW_basins = make_HW_cal_level_files(hru_gdf)

    return (
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
    )
