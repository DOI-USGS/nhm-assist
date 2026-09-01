"""Shared hydrofabric helpers for the nhm and nhf workflows.

Unified from src/assist/nhm/nhm_hydrofabric.py and
src/assist/nhf/nhm_hydrofabric_v2.py. See
docs/superpowers/specs/2026-08-30-helper-unification-design.md.

Implementations come from the nhf side, which already tolerates both the GFv1.1
and GFv2 geopackage column layouts; the nhm versions assume GFv1.1 columns and
cannot read a GFv2 model.
"""
import numpy as np
import pandas as pd

import geopandas as gpd
import xarray as xr
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData
from assist.common.assist_utilities import find_missing_gage_info, fetch_waterdata_gage_info


def read_gages_file(
    *,
    model_dir,
    poi_df,
    gages_file,
):
    """
    Read modified gages file.
    If there are gages in the parameter file that are not in WaterData (USGS gages), then latitude, longitude, and poi_name must be provided from another source,
    and appended to the "default_gages.csv" file. Once editing is complete, that file can be renamed "gages.csv"and will be used as the gages file.
    If NO gages.csv is made, the default_gages.csv will be used.

    Parameters
    ----------
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    poi_df : pandas DataFrame
        Dataframe containing gages from the parameter file.
    gages_file : pathlib Path class
        Path to file containing gage information from WaterData for the gages in the parameter file.
        
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
        "poi_gage_id",
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

        # Make poi_gage_id the index
        # gages_df["poi_gage_id"] = gages_df.poi_gage_id.astype(str)
        gages_df.set_index("poi_gage_id", inplace=True)

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

        # Make poi_gage_id the index
        gages_df.set_index("poi_gage_id", inplace=True)

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
    latitude (lat) and longitude (lon), for poi gages listed in the parameter file that uses WaterData and a supplemental gage ref
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
        # "hru_segment_nhm",  # The nhm_id of the segment recieving flow from the HRU
        "hru_segment",  # The segment_id of the segment recieving flow from the HRU
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
        hru_gdb = hru_gdb.set_index("nhm_id", drop=False).fillna(
            0
        )  # Set an index for HRU geodatabase.
        hru_gdb.index.name = "index"  # Index column must be renamed of the hru

    if GIS_format == ".shp":
        hru_gdb = gpd.read_file(
            f"{model_dir}/GIS/model_nhru.shp"
        )  # Reads HRU file to Geopandas.
        hru_gdb = hru_gdb.set_index("nhm_id", drop=False).fillna(
            0
        )  # Set an index for HRU geodatabase.
        hru_gdb.index.name = "index"  # Index column must be renamed of the hru

    hru_gdb = hru_gdb.to_crs(crs)  # reprojects to the defined crs projection
    print(hru_gdb.columns)

    # If the GIS file doesn't have 'hru_id', fall back to 'model_idx' or 'model_hru_idx'
    # (v1.1 uses 'model_idx' or 'model_hru_idx' where v2 uses 'hru_id' — they are the same value)
    if "hru_id" not in hru_gdb.columns:
        if "model_idx" in hru_gdb.columns:
            hru_gdb["hru_id"] = hru_gdb["model_idx"]
        elif "model_hru_idx" in hru_gdb.columns:
            hru_gdb["hru_id"] = hru_gdb["model_hru_idx"]
   
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
   
    # df
    # df["model_idx"] = (
    #     df.index + 1
    # )  #'model_idx' created here is the order of the parameters in the parameter file.

    df["hru_id"] = (
        df.index + 1
    )  #'model_idx' created here is the order of the parameters in the parameter file.
    print(df.columns)
    #Pre merge check
    df_by_nhm_id = df.set_index("nhm_id", drop=False).fillna(
            0
        )  # Set an index for HRU geodatabase.
    if df_by_nhm_id["hru_id"].equals(hru_gdb["hru_id"]):
        print("GIS nhm_id matches order found in myparam.param")
        df.drop(columns=["hru_id"], inplace=True)
    else:
        print("STOP! GIS nhm_id order is not the same as the order found in myparam.param!")
        diff = df_by_nhm_id.loc[~same, ["hru_id"]].join(
            hru_gdb.loc[~same, ["hru_id"]],
            lsuffix="_df_by_nhm_id",
            rsuffix="_hru_gdb"
        )
        print(diff)
    
    # Join the HRU params values to the HRU geodatabase using Merge
    # Drop columns from the param dataframe that already exist in the GIS
    # to avoid _x/_y suffixing during the merge (merge key 'nhm_id' excluded)
    overlap_cols = [c for c in df.columns if c in hru_gdb.columns and c != "nhm_id"]
    if overlap_cols:
        print(f"  Dropping overlapping columns from param df before merge: {overlap_cols}")
        df.drop(columns=overlap_cols, inplace=True)

    hru_gdb = pd.merge(df, hru_gdb, on="nhm_id")
    #hru_gdb = pd.merge(df, hru_gdb, left_on="hru_id", right_on="model_hru_idx")

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
    # hru_cal_levels_df = pd.read_csv(f"{root_dir}/data_dependencies/NHM_v1_1/nhm_v1_1_HRU_cal_levels.csv").fillna(0)
    # hru_cal_levels_df["hw_id"] = hru_cal_levels_df.hw_id.astype("int32")

    # hru_gdf = hru_gdf.merge(hru_cal_levels_df, on="nhm_id")
    # hru_gdf["hw_id"] = hru_gdf.hw_id.astype("int32")

    hru_text = f", and {len(hru_gdf.index)} [bold]HRUs[/bold]."
    # hru_cal_level_txt = f'{hru_gdf[hru_gdf["level"] > 1]["level"].count()} HRUs are within HWs, and {hru_gdf[hru_gdf["level"] > 2]["level"].count()} are within HW calibrated with streamflow observations.'

    return hru_gdf, hru_text


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
    # seg_params = ["tosegment_nhm", "tosegment", "seg_length", "obsin_segment"]
    seg_params = ["tosegment", "seg_length", "obsin_segment"]
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

        # Normalize column names across hydrofabric versions:
        # v2 uses 'nhm_seg_id' where v1.1 uses 'nhm_seg'
        if "nhm_seg" not in seg_gdb.columns and "nhm_seg_id" in seg_gdb.columns:
            seg_gdb.rename(columns={"nhm_seg_id": "nhm_seg"}, inplace=True)

        seg_gdb = seg_gdb.set_index("nhm_seg", drop=False).fillna(
            0
        )  # Set an index for segment geodatabase.
        seg_gdb.index.name = "index"  # Index column must be renamed

    # if GIS_format == ".shp":
    #     seg_gdb = gpd.read_file(f"{model_dir}/GIS/model_nsegment.shp").fillna(0)
    #     seg_gdb = seg_gdb.set_index(
    #         "nhm_seg", drop=False
    #     )  # Set an index for segment geodatabase(GIS)
    #     seg_gdb.index.name = "index"  # Index column must be renamed of the hru

    seg_gdb = seg_gdb.to_crs(crs)  # reprojects to the defined crs projection

    print(seg_gdb.columns)
    # Create a dataframe for parameter values
    first = True
    for vv in seg_params:
        if first:
            df = pdb.get_dataframe(vv)
            first = False
        else:
            df = pd.concat([df, pdb.get_dataframe(vv)], axis=1)  # , ignore_index=True)

    df.reset_index(inplace=True)
    # df["model_idx"] = df.index + 1
    df["segment_id"] = df.index + 1
    df.index.name = "index"  # Index column must be renamed
    print(df.columns)
    
    #Pre merge check
    # df_by_segment_id = df.set_index("nhm_seg", drop=False).fillna(
    #         0
    #     )  # Set an index for HRU geodatabase.
    
    # Ensure both contain the same IDs
    ids_df = df["nhm_seg"].tolist()
    print(len(ids_df))
    ids_seg = seg_gdb["nhm_seg"].tolist()
    print(len(ids_seg))
    
    if ids_df != ids_seg:
        raise ValueError("nhm_seg indices in the parameter file and the .gpkg are not the same.")
    else:
        print("nhm_seg indices in the parameter file and the .gpkg match")
    
    # if df_by_segment_id["segment_id"].equals(seg_gdb["segment_id"]):
    #     print("GIS segment_id matches order found in myparam.param")
    #     df.drop(columns=["segment_id"], inplace=True)
    # else:
    #     print("STOP! GIS nhm_id order is not the same as the order found in myparam.param!")
    #     diff = df_by_segment_id.loc[~same, ["segment_id"]].join(
    #         seg_gdb.loc[~same, ["segment_id"]],
    #         lsuffix="_df_by_segment_id",
    #         rsuffix="_seg_gdb"
    #     )
    #     print(diff)

    # Drop segment_id from GIS if present to avoid duplicate after merge
    if "segment_id" in seg_gdb.columns:
        seg_gdb.drop(columns=["segment_id"], inplace=True)

    # Join the segment params values to the segment geodatabase using Merge
    seg_gdb = pd.merge(df, seg_gdb, on="nhm_seg")

    # Create a Goepandas GeoDataFrame for the segment geodatabase
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
    resource_gages_file,
    default_gages_file,
    waterdata_gage_nobs_min,
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
    resource_gages_file : pathlib Path class
        Path to file containing gage information from WaterData for the gages in the parameter file and user modified information.
    default_gages_file : pathlib Path class
        Path to file containing gage information from WaterData for the gages in the parameter file.
    waterdata_gage_nobs_min : int
        Minimum number of days for WaterData gage to be considered as potential poi.

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
    
    """
    Create a dataframe for poi_gages from the parameter file with WaterData gage information data.

    """
    npoigages_info = find_missing_gage_info(root_dir=root_dir,
                                                dest_dir= model_dir / "metadata",
                                                gages_list=poi["poi_gage_id"].to_list(),
                                                resource_file_path= resource_gages_file)

    poi = poi.merge(npoigages_info, left_on="poi_gage_id", right_on="poi_gage_id", how="left")
    poi_df = pd.DataFrame(poi)  # Creates a Pandas DataFrame

    """
    """

    # """
    # Updates the poi_df with user altered metadata in the gages.csv file, if present, or the default_gages.csv file
    # """

    # if gages_file.exists():
    #     gages_df, gages_txt, gages_txt_nb2 = read_gages_file(
    #         model_dir=model_dir,
    #         poi_df=poi_df,
    #         gages_file=gages_file,
    #     )
        
    #     for idx, row in poi_df.iterrows():
    #         """
    #         Checks the gages_df for missing meta data and replace.
    #         """
    #         columns = ["latitude", "longitude", "poi_name", "poi_agency"]
    #         for item in columns:
    #             if pd.isnull(row[item]):
    #                 new_poi_gage_id = row["poi_gage_id"]
    #                 new_item = gages_df.loc[
    #                     gages_df.index == row["poi_gage_id"], item
    #                 ].values[0]
    #                 poi_df.loc[idx, item] = new_item

    # else:
    #     pass
    # if default_gages_file.exists():
    #     gages_df, gages_txt, gages_txt_nb2 = read_gages_file(
    #         model_dir=model_dir,
    #         poi_df=poi_df,
    #         gages_file=gages_file,
    #     )
        
    #     for idx, row in poi_df.iterrows():
    #         """
    #         Checks the poi_df for missing meta data and replace.
    #         """
    #         columns = ["latitude", "longitude", "poi_name", "poi_agency"]
    #         for item in columns:
    #             if pd.isnull(row[item]):
    #                 new_poi_gage_id = row["poi_gage_id"]
    #                 new_item = gages_df.loc[
    #                     gages_df.index == row["poi_gage_id"], item
    #                 ].values[0]
    #                 poi_df.loc[idx, item] = new_item

    # else:
    #     pass

    return poi_df

def create_default_gages_file(
    *,
    root_dir,
    model_dir,
    control_file_name,
    waterdata_gage_nobs_min,
    hru_gdf,
    poi_df,
    seg_gdf,
):

    """
    Create default_gages.csv for your subdomain model.
    NHM-Assist notebooks will display gages using the default gages file (default_gages.csv), if a modified gages file (gages.csv) is lacking.
    By default, this file will be composed of:

        1) the gages listed in the parameter file (poi_gages), and
        2) all streamflow gages from WaterData in the subdomain model that have at least user-specified minimum number of obervations
           through use of the nwis_cache.nc. Metadata for gages will be fetched from NLDI and WaterData databases.
        3) if a resource_gages.csv file exists, these gages will be included as well, and this will be the source of metadata for the file.

    Note: Provided extractions from NHM version 1.1 have only USGS gages in the parameter file but may have no data after 1979.

    Parameters
    ----------
    model_dir : pathlib Path class
        Path object to the subdomain directory.
    control_file_name : pathlib Path class
        Path object to the control file.
    waterdata_gage_nobs_min : int
        Minimum number of days for WaterData gage to be considered as potential poi.
    hru_gdf : geopandas GeoDataFrame
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.
    poi_df : pandas DataFrame
        Dataframe containing gages from the parameter file.

    Returns
    -------
    default_gages_file : pathlib Path class
        Path to file containing gage information from WaterData for the gages in the parameter file.
        
    """
    """ Remove WaterData gages with no daily streamflow data after the st_date in the control file
        *** 6/10/2026 - maybe we don't use the start date in the control file but hardwire to 1/1/1979
    """
    waterdata_cache_file = model_dir / "notebook_output_files" / "nc_files" / "waterdata_cache.nc"
    resource_gages_file = model_dir / "metadata/resource_gages.csv" #(may want to add as funct arg)
    default_gages_file = model_dir / "default_gages.csv"
    
    with xr.open_dataset(waterdata_cache_file) as ds:
        df = ds.to_dataframe()
        obs_list = list(df.index.get_level_values(0).unique())
        # print(waterdata_obs_list)
        del ds
        
    """ But we need to add gages without obs back in to the list, if they are in the param file.
        Read in additional non-WaterData gages from the resource gage file. These are a list of user requested gages 
        that may or may not be in the parameter file or the sf_efc.nc file, and likely include non WaterData gages.
    """
    
    if resource_gages_file.exists():
        col_names = [
            "poi_gage_id",
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
        resource_list = list(set(resource_gages_file_df['poi_gage_id']))
        keep_list = list(set(obs_list + poi_df.poi_gage_id.to_list() + resource_list))

        default_gages_df = find_missing_gage_info(root_dir=root_dir,
                                                  dest_dir= model_dir,
                                                  gages_list=keep_list,
                                                  resource_file_path= model_dir / "metadata/resource_gages.csv")

        """Changed this not to fill if null, but to overwrite the value (allows for corrections/mods)
            May want to build a check in here to see if the values are the same, and if different, give feedback.
        """
                
        for idx, row in default_gages_df.iterrows():
            columns = ["latitude", "longitude", "poi_name", "poi_agency"]
            check_list = resource_gages_file_df["poi_gage_id"].to_list()
            #print(check_list)
            for item in columns:
                #if pd.isnull(row[item]):
                new_poi_gage_id = row["poi_gage_id"]
                if new_poi_gage_id in check_list:
                    new_item = resource_gages_file_df.loc[
                        resource_gages_file_df.poi_gage_id == new_poi_gage_id, item
                    ].values[0]
                    default_gages_df.loc[idx, item] = new_item
                else:
                    #print(f"Gage {new_poi_gage_id} is not in the gages.csv. Add gage and meta data to the gages.csv and rerun this code block.")
                    pass
        print("default_gages.csv metadata transferred from resource_gages.csv.")
        default_gages_df.to_csv(default_gages_file, index=False)

    else:    
        keep_list = list(set(obs_list + poi_df.poi_gage_id.to_list()))
        
        default_gages_df = find_missing_gage_info(root_dir=root_dir,
                                                  dest_dir= model_dir,
                                                  gages_list=keep_list,
                                                  resource_file_path= model_dir / "metadata/resource_gages.csv")

        print("default_gages.csv metadata fetched from NLDI and WaterData databases.",
              "resource_gages_file.csv with all parameter file and domain gages.")
        resource_gages_file_df = default_gages_df.copy()
        resource_gages_file_df.to_csv(resource_gages_file, index=False)
    
        default_gages_df.to_csv(default_gages_file, index=False)
    
    return default_gages_file

def make_hf_map_elements(
    *,
    root_dir,
    model_dir,
    GIS_format,
    param_filename,
    control_file_name,
    waterdata_gages_file,
    gages_file,
    resource_gages_file,
    default_gages_file,
    nhru_params,
    nhru_nmonths_params,
    waterdata_gage_nobs_min,
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
    waterdata_gages_file : pathlib Path class
        Path to WaterData data, e.g., model_dir / "NWISgages.csv"
    gages_file : pathlib Path class
        Path to file containing gage information from WaterData for the gages in the parameter file.
    default_gages_file : pathlib Path class
        Path to file containing gage information from WaterData for the gages in the parameter file.
    nhru_params : list
        Parameters dimensioned by HRU only.   
    nhru_nmonths_params : list
        Parameters dimensioned by HRU and month.
    waterdata_gage_nobs_min : int
        Minimum number of days for WaterData gage to be considered as potential poi.
    
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
    waterdata_gages_aoi : Pandas DataFrame()
        Pandas DataFrame() containing gages from WaterData in the subdomain.
    poi_df : pandas DataFrame
        Dataframe containing gages from the parameter file.
    gages_df : pandas DataFrame
        Represents data pertaining to subdomain gages in parameter file, NWIS, and others.
    gages_txt : str
        Informational feedback printed in notebooks.
    gages_txt_nb2 : str
        Informational feedback printed in notebooks.
    # HW_basins_gdf : geopandas GeoDataFrame
    #     NHM headwaters basins geopandas GeoDataFrame used to display caliration level of HRUs on map.
    # HW_basins : geopandas polyline dataset
    #     Polyline file that was made using HW_basins_gdf.boundary
    
    """
    hru_gdf, hru_txt = create_hru_gdf(
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
        resource_gages_file=resource_gages_file,
        default_gages_file=default_gages_file,
        waterdata_gage_nobs_min=waterdata_gage_nobs_min,
        seg_gdf=seg_gdf,
    )
    waterdata_gages_aoi = fetch_waterdata_gage_info(
        root_dir=root_dir,
        model_dir=model_dir,
        control_file_name=control_file_name,
        waterdata_gage_nobs_min=waterdata_gage_nobs_min,
        hru_gdf=hru_gdf,
        seg_gdf=seg_gdf,
    )

    gages_df, gages_txt, gages_txt_nb2 = read_gages_file(
        model_dir=model_dir,
        poi_df=poi_df,
        gages_file=gages_file,
    )

#    HW_basins_gdf, HW_basins = make_HW_cal_level_files(hru_gdf)

    return (
        hru_gdf,
        hru_txt,
        #hru_cal_level_txt,
        seg_gdf,
        seg_txt,
        waterdata_gages_aoi,
        poi_df,
        gages_df,
        gages_txt,
        gages_txt_nb2,
#        HW_basins_gdf,
#        HW_basins,
    )

def evaluate_and_fix_nhru_geometry(gpkg_path, layer="nhru", fix=True):
    """
    Evaluate and optionally fix geometries in the nhru layer of a GeoPackage.

    Checks for:
    - Invalid geometries (self-intersections, etc.)
    - Non-finite coordinates (NaN, Inf)
    - Null/empty geometries

    Parameters
    ----------
    gpkg_path : str or pathlib.Path
        Path to the model_layers.gpkg file.
    layer : str, optional
        Layer name to evaluate (default "nhru").
    fix : bool, optional
        If True, attempt to fix invalid geometries using shapely.make_valid
        and save the corrected layer back to the GeoPackage (default True).

    Returns
    -------
    report : dict
        Dictionary with keys:
        - "total_features": int
        - "invalid_geom": list of indices with invalid geometries
        - "nonfinite_coords": list of indices with NaN/Inf coordinates
        - "null_or_empty": list of indices with null or empty geometries
        - "fixed": bool, whether fixes were applied and saved
        - "gpkg_path": str, path to the GeoPackage
    """
    import geopandas as gpd
    import numpy as np
    from shapely import get_coordinates, make_valid
    from pathlib import Path

    gpkg_path = Path(gpkg_path)
    gdf = gpd.read_file(gpkg_path, layer=layer)

    report = {
        "total_features": len(gdf),
        "invalid_geom": [],
        "nonfinite_coords": [],
        "null_or_empty": [],
        "fixed": False,
        "gpkg_path": str(gpkg_path),
    }

    # Check for null/empty geometries
    null_mask = gdf.geometry.is_empty | gdf.geometry.isna()
    report["null_or_empty"] = gdf.index[null_mask].tolist()

    # Check for invalid geometries
    valid_mask = gdf.geometry.is_valid
    report["invalid_geom"] = gdf.index[~valid_mask & ~null_mask].tolist()

    # Check for non-finite coordinates
    def has_nonfinite_coords(geom):
        if geom is None or geom.is_empty:
            return False  # already caught above
        coords = get_coordinates(geom, include_z=False)
        return not np.isfinite(coords).all()

    nonfinite_mask = gdf.geometry.apply(has_nonfinite_coords)
    report["nonfinite_coords"] = gdf.index[nonfinite_mask].tolist()

    # Print summary
    print(f"Layer: '{layer}' in {gpkg_path.name}")
    print(f"  Total features: {report['total_features']}")
    print(f"  Null/empty geometries: {len(report['null_or_empty'])}")
    print(f"  Invalid geometries: {len(report['invalid_geom'])}")
    print(f"  Non-finite coordinates: {len(report['nonfinite_coords'])}")

    needs_fix = (
        len(report["invalid_geom"]) > 0 or len(report["nonfinite_coords"]) > 0
    )

    if fix and needs_fix:
        print("  Applying make_valid to fix geometries...")
        gdf["geometry"] = gdf.geometry.apply(
            lambda g: make_valid(g, method="structure", keep_collapsed=True)
            if g is not None and not g.is_empty
            else g
        )

        # Verify fix
        still_invalid = (~gdf.geometry.is_valid & ~null_mask).sum()
        if still_invalid > 0:
            print(f"  WARNING: {still_invalid} geometries still invalid after fix.")
        else:
            print("  All geometries now valid.")

        # Save back to GeoPackage
        gdf.to_file(gpkg_path, layer=layer, driver="GPKG")
        print(f"  Fixed layer saved to {gpkg_path}")
        report["fixed"] = True
    elif not needs_fix:
        print("  All geometries are valid. No fix needed.")

    return report

def _load_byhwobs_cal_gages(root_dir):
    """Load the fixed NHM byHWobs calibration-gages CSV.

    This file is a fixed data dependency shipped with NHM v1.1; its header uses
    the native `poi_id` name. Read it under that name so the ``str`` dtype keeps
    leading zeros (e.g. ``"08049300"``), then canonicalize the column to the
    project-wide `poi_gage_id` at the boundary.
    """
    cal_gages_file = (
        root_dir / "data_dependencies/NHM_v1_1/nhm_v1_1_byhwobs_cal_gages.csv"
    )
    cols = {"poi_id": np.str_, "latitude": float, "longitude": float}
    byHWobs_poi_df = pd.read_csv(cal_gages_file, sep="\t", dtype=cols).fillna(0)
    return byHWobs_poi_df.rename(columns={"poi_id": "poi_gage_id"})