import pathlib as pl
import warnings
from io import StringIO
from urllib import request
from urllib.error import HTTPError
from urllib.request import urlopen
import geopandas as gpd
import netCDF4
import numpy as np
import pandas as pd
import pywatershed as pws
import xarray as xr
from rich.console import Console
import dataretrieval.nwis as nwis
from rich import pretty
from rich.progress import Progress
from nhm_helpers.efc import efc
from nhm_helpers.nhm_assist_utilities import fetch_nwis_gage_info

con = Console()
pretty.install()
warnings.filterwarnings("ignore")


def owrd_scraper(station_nbr, start_date, end_date):
    """
    Acquires daily streamflow data from Oregon Water Resources Department (OWRD).

    Parameters
    ----------
    station_nbr : str
        Gage identification number.        
    start_date : str
        First date of timeseries data ("%m/%d/%Y").       
    end_date : str
        Last date of timeseries data ("%m/%d/%Y").

    Returns
    -------
    df: pandas DataFrame
        Dataframe containing OWRD mean daily streamflow data for the specified gage and date range.
    
    """
    
    # f string the parameters into the url address
    url = f"https://apps.wrd.state.or.us/apps/sw/hydro_near_real_time/hydro_download.aspx?station_nbr={station_nbr}&start_date={start_date}&end_date={end_date}&dataset=MDF&format=html"

    # open and decode the url
    resource = request.urlopen(url)
    content = resource.read().decode(resource.headers.get_content_charset())

    # Ugly parsing between pre tags
    # initializing substrings
    sub1 = "<pre>"
    sub2 = "</pre>"

    # getting index of substrings
    idx1 = content.index(sub1)
    idx2 = content.index(sub2)

    res = ""
    # getting elements in between
    for idx in range(idx1 + len(sub1), idx2):
        res = res + content[idx]

    # make and return the pandas df

    # NOTE:
    # Read in the csv file taking care to set the data types exactly. This is important for stability and functionality.
    # This should be done everytime the databases are read into this and future notebooks!

    col_names = [
        "station_nbr",
        "record_date",
        "mean_daily_flow_cfs",
        #'published_status',
        #'estimated',
        #'revised',
        #'download_date',
    ]
    col_types = [
        np.str_,
        np.str_,
        float,
        # np.str_,
        # np.str_,
        # float,
        # np.str_,
    ]
    cols = dict(
        zip(col_names, col_types)
    )  # Creates a dictionary of column header and datatype called below.

    df = pd.read_csv(StringIO(res), sep="\t", header=0, dtype=cols)

    return df


def create_OR_sf_df(control, model_dir, output_netcdf_filename, hru_gdf, gages_df):
    """
    Determines whether the subdomain intersects OR and proceeds to call owrd_scraper to generate owrd_df. 
    Exports OR streamflow data as cached netCDF file for faster dataframe access.

    Parameters
    ----------
    control : pywatershed Control object
        An instance of Control object, loaded from a control file with pywatershed.        
    model_dir : pathlib Path class
        Path object to the subdomain directory.        
    output_netcdf_filename : pathlib Path class
        output netCDF filename for cachefile, e.g., model_dir / "notebook_output_files/nc_files/sf_efc.nc"        
    hru_gdf : geopandas GeoDataFrame
        HRU geodataframe from GIS data in subdomain.        
    gages_df : pandas DataFrame
        Represents data pertaining to subdomain gages in parameter file, NWIS, and others.
        
    Returns
    -------
    owrd_df : pandas DataFrame
        Dataframe containing OWRD mean daily streamflow data for the specified gage and date range.
    
    """
    

    start_date = pd.to_datetime(str(control.start_time)).strftime("%m/%d/%Y")
    end_date = pd.to_datetime(str(control.end_time)).strftime("%m/%d/%Y")
    owrd_cache_file = (
        model_dir / "notebook_output_files" / "nc_files" / "owrd_cache.nc"
    )  # (eventually comment out)

    owrd_regions = ["16", "17", "18"]

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

    # Make a list if the HUC2 region(s) the subdomain intersects for NWIS queries.
    huc2_gdf = gpd.read_file("./data_dependencies/HUC2/HUC2.shp").to_crs(crs)
    model_domain_regions = list((huc2_gdf.clip(hru_gdf).loc[:]["huc2"]).values)

    if any(item in owrd_regions for item in model_domain_regions):
        owrd_domain_txt = "The model domain intersects the Oregon state boundary. "
        if output_netcdf_filename.exists():
            owrd_domain_txt += "All available streamflow observations for gages in the gages file were previously retrieved from OWRD database and included in the sf_efc.nc file. [bold]To update OWRD data, delete sf_efc.nc and owrd_cache.nc[/bold] and rerun 1_Create_Streamflow_Observations.ipynb."
            owrd_df = pd.DataFrame()
            pass
        else:
            if owrd_cache_file.exists():
                with xr.open_dataset(owrd_cache_file) as owrd_ds:
                    owrd_df = owrd_ds.to_dataframe()
                    print(
                        "Cached copy of OWRD data exists. To re-download the data, remove the cache file."
                    )
                del owrd_ds

            else:
                print(
                    "Retrieving all available streamflow observations from OWRD database for gages in the gages file."
                )
                lst = []

                for ii in gages_df.index:
                    lst.append(owrd_scraper(ii, start_date, end_date))

                if lst:
                    owrd_df = pd.concat(
                        lst
                    )  # Converts the list of df's to a single df  maybe move this to the owrd scraper function

                    # Reformat owrd_df headers and data types
                    # Rename column headers
                    field_map = {
                        "station_nbr": "poi_id",
                        "record_date": "time",
                        "mean_daily_flow_cfs": "discharge",
                        "station_name": "poi_name",
                    }
                    owrd_df.rename(columns=field_map, inplace=True)

                    # Change the datatype for 'poi_id' and 'time'
                    dtype_map = {"poi_id": str, "time": "datetime64[ns]"}
                    owrd_df = owrd_df.astype(dtype_map)

                    # Drop the columns we don't need
                    drop_cols = [
                        "download_date",
                        "estimated",
                        "revised",
                        "published_status",
                    ]
                    owrd_df.drop(columns=drop_cols, inplace=True)

                    # Add new field(s): 'agency_id' and set to 'OWRD'
                    owrd_df["agency_id"] = (
                        "OWRD"  # Creates tags for all OWRD daily streamflow data
                    )

                    # Set multi-index for df
                    owrd_df.set_index(["poi_id", "time"], inplace=True)

                    # Write df as netcdf fine (.nc)
                    owrd_ds = xr.Dataset.from_dataframe(owrd_df)

                    # Set attributes for the variables
                    owrd_ds["discharge"].attrs = {
                        "units": "ft3 s-1",
                        "long_name": "discharge",
                    }
                    owrd_ds["poi_id"].attrs = {
                        "role": "timeseries_id",
                        "long_name": "Point-of-Interest ID",
                        "_Encoding": "ascii",
                    }
                    owrd_ds["agency_id"].attrs = {"_Encoding": "ascii"}

                    # Set encoding (see 'String Encoding' section at https://crusaderky-xarray.readthedocs.io/en/latest/io.html)
                    owrd_ds["poi_id"].encoding.update(
                        {"dtype": "S15", "char_dim_name": "poiid_nchars"}
                    )

                    owrd_ds["time"].encoding.update(
                        {
                            "_FillValue": None,
                            "standard_name": "time",
                            "calendar": "standard",
                            "units": "days since 1940-01-01 00:00:00",
                        }
                    )

                    owrd_ds["agency_id"].encoding.update(
                        {"dtype": "S5", "char_dim_name": "agency_nchars"}
                    )

                    # Add fill values to the data variables
                    var_encoding = dict(_FillValue=netCDF4.default_fillvals.get("f4"))

                    for cvar in owrd_ds.data_vars:
                        if cvar not in ["agency_id"]:
                            owrd_ds[cvar].encoding.update(var_encoding)

                    # add global attribute metadata
                    owrd_ds.attrs = {
                        "Description": "Streamflow data for PRMS",
                        "FeatureType": "timeSeries",
                    }

                    # Write the dataset to a netcdf file
                    print(
                        f"OWRD daily streamflow observations retrieved for {len(owrd_df.index)}, writing data to {owrd_cache_file}."
                    )
                    owrd_ds.to_netcdf(owrd_cache_file)

                    owrd_domain_txt += " All available streamflow observations for gages in the gages file were retrieved from OWRD database."
                else:
                    owrd_domain_txt += " No available streamflow observations for gages in the gages file exist in the OWRD database."
                    owrd_df = pd.DataFrame()
    else:
        owrd_domain_txt = "; the model domain is outside the Oregon state boundary."
        owrd_df = pd.DataFrame()
    con.print(owrd_domain_txt)
    return owrd_df


def ecy_scrape(station, ecy_years, ecy_start_date, ecy_end_date):
    """
    Acquires daily streamflow data from Washington Department of Ecology (ECY).

    Parameters
    ----------
    station : str
        Gage identification for ECY gage.        
    ecy_years : int range
        Range of years to acquire ECY data (comes from control file).        
    ecy_start_date : str
        First date of timeseries data ("%Y-%m-%d")        
    ecy_end_date :
        Last date of timeseries data ("%Y-%m-%d")
        
    Returns
    -------
    None
    
    """
    
    ecy_df_list = []
    for ecy_year in ecy_years:
        url = f"https://apps.ecology.wa.gov/ContinuousFlowAndWQ/StationData/Prod/{station}/{station}_{ecy_year}_DSG_DV.txt"
        try:
            # The string that is to be searched
            key = "DATE"

            # Opening the file and storing its data into the variable lines
            with urlopen(url) as file:
                lines = file.readlines()

            # Going over each line of the file
            dateline = []
            for number, line in enumerate(lines, 1):

                # Condition true if the key exists in the line
                # If true then display the line number
                if key in str(line):
                    dateline.append(number)
                    # print(f'{key} is at line {number}')
            # df = pd.read_csv(url, skiprows=11, sep = '\s{3,}', on_bad_lines='skip', engine = 'python')  # looks for at least three spaces as separator
            df = pd.read_fwf(
                url, skiprows=dateline[0]
            )  # seems to handle formatting for No Data and blanks together, above option is thrown off by blanks
            # df['Day'] = pd.to_numeric(df['Day'], errors='coerce') # day col to numeric
            # df = df[df['Day'].notna()].astype({'Day': int}) #
            # df = df.drop('Day.1', axis=1)
            if len(df.columns) == 3:
                df.columns = ["time", "discharge", "Quality"]
            elif len(df.columns) == 4:
                df.columns = ["time", "utc", "discharge", "Quality"]
                df.drop("utc", axis=1, inplace=True)
            try:
                df.drop(
                    "Quality", axis=1, inplace=True
                )  # drop quality for now, might use to filter later
            except KeyError:
                print(f"no Quality for {station} {ecy_year}")
            df["time"] = pd.to_datetime(df["time"], errors="coerce")
            df = df.dropna(subset=["time"])
            df["poi_id"] = station
            df["discharge"] = pd.to_numeric(df["discharge"], errors="coerce")
            # specify data types
            dtype_map = {"poi_id": str, "time": "datetime64[ns]"}
            df = df.astype(dtype_map)

            df.set_index(["poi_id", "time"], inplace=True)
            # next two lines are new if this breaks...
            idx = pd.IndexSlice
            df = df.loc[
                idx[:, ecy_start_date:ecy_end_date], :
            ]  # filters to the date range
            df["agency_id"] = "ECY"

            ecy_df_list.append(df)
            print(f"good year {ecy_year}")
            print(url)
        except HTTPError:
            pass
        except ValueError as ex:
            print(ex)
            print(ecy_year)
    if len(df) != 0:
        temp_df = pd.concat(ecy_df_list)
        # ecy_df["discharge_cfs"] = pd.to_numeric(ecy_df["discharge_cfs"], errors = 'coerce')
        # maybe inster the rest of the df formatting here:

        return temp_df
    else:
        print(f"No data for station {station} for data range {ecy_years}.")
        return None


def create_ecy_sf_df(control, model_dir, output_netcdf_filename, hru_gdf, gages_df):
    """
    Determines whether the subdomain intersects WA and proceeds to call ecy_scrape to generate ecy_df. 
    Exports WA streamflow data as cached netCDF file for faster dataframe access.

    Parameters
    ----------
    control : pywatershed Control object
        An instance of Control object, loaded from a control file with pywatershed.        
    model_dir : pathlib Path class
        Path object to the subdomain directory.        
    output_netcdf_filename : pathlib Path class
        output netCDF filename for cachefile, e.g., model_dir / "notebook_output_files/nc_files/sf_efc.nc"        
    hru_gdf : geopandas GeoDataFrame
        HRU geodataframe from GIS data in subdomain.        
    gages_df : pandas DataFrame
        Represents data pertaining to subdomain gages in parameter file, NWIS, and others.

    Returns
    -------
    ecy_df : pandas DataFrame
        Dataframe containing ECY mean daily streamflow data for the specified gage and date range.
        
    """
    
    ecy_regions = ["17"]

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

    # Make a list if the HUC2 region(s) the subdomain intersects for NWIS queries.
    huc2_gdf = gpd.read_file("./data_dependencies/HUC2/HUC2.shp").to_crs(crs)
    model_domain_regions = list((huc2_gdf.clip(hru_gdf).loc[:]["huc2"]).values)
    ecy_df = pd.DataFrame()

    if any(item in ecy_regions for item in model_domain_regions):
        ecy_domain_txt = "The model domain intersects the Washington state boundary."
        if output_netcdf_filename.exists():
            ecy_domain_txt += " All available streamflow observations for gages in the gages file were previously retrieved from ECY database and included in the sf_efc.nc file. [bold]To update ECY data, delete sf_efc.nc and ecy_cache.nc [/bold]and rerun 1_Create_Streamflow_Observations.ipynb."
            pass
        else:
            """Check the gages_df for ECY gages."""
            ecy_gages = []
            gage_list = gages_df.index.to_list()
            for i in gage_list:
                # if len(i) == 6 and i.matches("^[A-Z]{1}\\d{3}")
                if (
                    len(i) == 6
                    and i[0:2].isdigit()
                    and i[2].isalpha()
                    and i[4:6].isdigit()
                ):
                    ecy_gages.append(i)
                else:
                    pass

            if ecy_gages:
                con.print(
                    f"{ecy_domain_txt} Retrieving all available streamflow observations from ECY database for ECY gages in the gages file."
                )
                #ecy_df = pd.DataFrame()
                ecy_df_list = []
                ecy_cache_file = (
                    model_dir / "notebook_output_files" / "nc_files" / "ecy_cache.nc"
                )  # This too will go away eventually and so will the if loop below

                if ecy_cache_file.exists():
                    with xr.open_dataset(ecy_cache_file) as ecy_ds:
                        ecy_df = ecy_ds.to_dataframe()
                    print(
                        "Cached copy of ECY data exists. To re-download the data, remove the cache file."
                    )
                    del ecy_ds
                else:
                    # Get start and end dates for ecy_scraper:
                    ecy_start_date = pd.to_datetime(str(control.start_time)).strftime(
                        "%Y-%m-%d"
                    )
                    ecy_end_date = pd.to_datetime(str(control.end_time)).strftime(
                        "%Y-%m-%d"
                    )

                    # Get WY range in years (add 1 year to date range because ecy is water year, add another year because range is not inclusive)
                    ecy_years = range(
                        pd.to_datetime(str(control.start_time)).year,
                        pd.to_datetime(str(control.end_time)).year + 2,
                    )

                    # 2) Go get the data
                    for ecy_gage_id in ecy_gages:
                        try:
                            ecy_df_list.append(
                                ecy_scrape(
                                    ecy_gage_id, ecy_years, ecy_start_date, ecy_end_date
                                )
                            )

                        except UnboundLocalError:
                            print(f"No data for {ecy_gage_id}")
                            pass

                    ecy_df = pd.concat(
                        ecy_df_list
                    )  # Converts the list of ecy gage df's to a single df

                    # set the multiIndex
                    # ecy_df.set_index(['poi_id', 'time'], inplace=True)

                    ecy_df = ecy_df[
                        ~ecy_df.index.duplicated(keep="first")
                    ]  # overlap in ecy records for 10-1, drop duplicates for xarray

                    # Add new fields
                    ecy_df["agency_id"] = (
                        "ECY"  # Creates tags for all ECY daily streamflow data
                    )

                    # Write ecy_df as netcdf (.nc) file
                    ecy_ds = xr.Dataset.from_dataframe(ecy_df)

                    # Set attributes for the variables
                    ecy_ds["discharge"].attrs = {
                        "units": "ft3 s-1",
                        "long_name": "discharge",
                    }
                    ecy_ds["poi_id"].attrs = {
                        "role": "timeseries_id",
                        "long_name": "Point-of-Interest ID",
                        "_Encoding": "ascii",
                    }
                    ecy_ds["agency_id"].attrs = {"_Encoding": "ascii"}

                    # Set encoding
                    # See 'String Encoding' section at https://crusaderky-xarray.readthedocs.io/en/latest/io.html
                    ecy_ds["poi_id"].encoding.update(
                        {"dtype": "S15", "char_dim_name": "poiid_nchars"}
                    )

                    ecy_ds["time"].encoding.update(
                        {
                            "_FillValue": None,
                            "standard_name": "time",
                            "calendar": "standard",
                            "units": "days since 1940-01-01 00:00:00",
                        }
                    )

                    ecy_ds["agency_id"].encoding.update(
                        {"dtype": "S5", "char_dim_name": "agency_nchars"}
                    )

                    # Add fill values to the data variables
                    var_encoding = dict(_FillValue=netCDF4.default_fillvals.get("f4"))

                    for cvar in ecy_ds.data_vars:
                        if cvar not in ["agency_id"]:
                            ecy_ds[cvar].encoding.update(var_encoding)

                    # add global attribute metadata
                    ecy_ds.attrs = {
                        "Description": "Streamflow data for PRMS",
                        "FeatureType": "timeSeries",
                    }

                    # Write the dataset to a netcdf file
                    ecy_ds.to_netcdf(ecy_cache_file)
            else:
                ecy_domain_txt += " No gages in the gages file are ECY managed gages."
                #ecy_df = pd.DataFrame()
    else:
        ecy_domain_txt = "; the model domain is outside the Washinton state boundary."
        #ecy_df = pd.DataFrame()
    #ecy_df = pd.DataFrame()
    con.print(ecy_domain_txt)
    return ecy_df


def create_nwis_sf_df(
    control_file_name,
    model_dir,
    output_netcdf_filename,
    hru_gdf,
    poi_df,
    nwis_gage_nobs_min,
):  # add neis_gage_nobs_min, hru_gdf,
    nwis_cache_file = model_dir / "notebook_output_files" / "nc_files" / "nwis_cache.nc"
    control = pws.Control.load_prms(
        pl.Path(model_dir / control_file_name, warn_unused_options=False)
    )
    nwis_gages_file = model_dir / "NWISgages.csv"

    """
    Create a dataframe for NWIS gages in the model domain

    Parameters
    ----------
    control_file_name: pathlib Path class
        Path object to the control file.        
    model_dir: pathlib Path class
        Path object to the subdomain directory.        
    output_netcdf_filename: pathlib Path class
        output netCDF filename for cachefile, e.g., model_dir / "notebook_output_files/nc_files/sf_efc.nc"        
    hru_gdf: geopandas GeoDataFrame
        HRU geopandas.GeoDataFrame() from GIS data in subdomain.        
    poi_df: pandas DataFrame
        Dataframe containing gages.        
    nwis_gage_nobs_min: int
        Minimum number of days for NWIS gage to be considered as pontential poi.
        
    Returns
    -------
    NWIS_df: pandas DataFrame
        Dataframe of NWIS gages.
        
    """
    
    nwis_gage_info_aoi = fetch_nwis_gage_info(
        model_dir,
        control_file_name,
        nwis_gage_nobs_min,
        hru_gdf,
    )

    if output_netcdf_filename.exists():
        NWIS_df = pd.DataFrame()
        con.print(
            "All available streamflow observations for gages in the gages file were previously retrieved from NWIS database and included in the sf_efc.nc file. [bold]To update NWIS data, delete sf_efc.nc and nwis_cache.nc and rerun 1_Create_Streamflow_Observations.ipynb.[/bold]"
        )
    else:
        if nwis_cache_file.exists():
            with xr.open_dataset(nwis_cache_file) as NWIS_ds:
                NWIS_df = NWIS_ds.to_dataframe()
                print(
                    "Cached copy of NWIS data exists. To re-download the data, remove the cache file."
                )
                del NWIS_ds
        else:
            output_netcdf_filename = (
                model_dir / "notebook_output_files" / "nc_files" / "sf_efc.nc"
            )
            """
            This function returns a dataframe of mean daily streamflow data from NWIS using gages listed in the gages_df,
            for the period of record defined in the NHM model control file control.default.bandit.
            Note: all gages in the gages_df that are not found in NWIS will be ignored.
            """

            nwis_start = pd.to_datetime(str(control.start_time)).strftime("%Y-%m-%d")
            nwis_end = pd.to_datetime(str(control.end_time)).strftime("%Y-%m-%d")
            NWIS_tmp = []

            with Progress() as progress:
                task = progress.add_task(
                    "[red]Downloading...", total=len(nwis_gage_info_aoi)
                )
                err_list = []
                nobs_min_list = []
                for ii in nwis_gage_info_aoi.poi_id:
                    try:
                        NWISgage_data = nwis.get_record(
                            sites=(str(ii)),
                            service="dv",
                            start=nwis_start,
                            end=nwis_end,
                            parameterCd="00060",
                        )
                        if len(NWISgage_data.index) >= nwis_gage_nobs_min:
                            NWIS_tmp.append(NWISgage_data)
                        elif ii in poi_df["poi_id"].unique().tolist():
                            NWIS_tmp.append(NWISgage_data)
                        else:
                            nobs_min_list.append(ii)
                            # con.print(f"Gage id {ii} fewer obs than nwis_gage_nobs_min.")
                    except ValueError:
                        err_list.append(ii)
                        # con.print(f"Gage id {ii} not found in NWIS.")
                        pass
                    progress.update(task, advance=1)

            NWIS_df = pd.concat(NWIS_tmp)
            con.print(
                f"{len(nobs_min_list)} gages had fewer obs than nwis_gage_nobs_min and will be ommited from nwis_gages_cache.nc and NWIS gages.csv unless they appear in the paramter file.\n{nobs_min_list}"
            )
            con.print(f"{len(err_list)} gages: {err_list} were **NOT** found in NWIS.")
            # we only need site_no and discharge (00060_Mean)
            NWIS_df = NWIS_df[["site_no", "00060_Mean"]].copy()
            NWIS_df["agency_id"] = "USGS"

            NWIS_df = NWIS_df.tz_localize(None)
            NWIS_df.reset_index(inplace=True)

            # rename cols to match other df
            NWIS_df.rename(
                columns={
                    "datetime": "time",
                    "00060_Mean": "discharge",
                    "site_no": "poi_id",
                },
                inplace=True,
            )

            NWIS_df.set_index(["poi_id", "time"], inplace=True)

            #### Write the .nc file
            # Reformat data types
            # Change the datatype for 'poi_id' and 'time'
            # dtype_map = {"poi_id": str, "time": "datetime64[ns]"}
            # NWIS_df = NWIS_df.astype(dtype_map)

            # Write df as netcdf fine (.nc)
            NWIS_ds = xr.Dataset.from_dataframe(NWIS_df)

            # Set attributes for the variables
            NWIS_ds["discharge"].attrs = {"units": "ft3 s-1", "long_name": "discharge"}
            NWIS_ds["poi_id"].attrs = {
                "role": "timeseries_id",
                "long_name": "Point-of-Interest ID",
                "_Encoding": "ascii",
            }
            NWIS_ds["agency_id"].attrs = {"_Encoding": "ascii"}

            # Set encoding (see 'String Encoding' section at https://crusaderky-xarray.readthedocs.io/en/latest/io.html)
            NWIS_ds["poi_id"].encoding.update(
                {"dtype": "S15", "char_dim_name": "poiid_nchars"}
            )

            NWIS_ds["time"].encoding.update(
                {
                    "_FillValue": None,
                    "standard_name": "time",
                    "calendar": "standard",
                    "units": "days since 1940-01-01 00:00:00",
                }
            )

            NWIS_ds["agency_id"].encoding.update(
                {"dtype": "S5", "char_dim_name": "agency_nchars"}
            )

            # Add fill values to the data variables
            var_encoding = dict(_FillValue=netCDF4.default_fillvals.get("f4"))

            for cvar in NWIS_ds.data_vars:
                if cvar not in ["agency_id"]:
                    NWIS_ds[cvar].encoding.update(var_encoding)

            # add global attribute metadata
            NWIS_ds.attrs = {
                "Description": "Streamflow data for PRMS",
                "FeatureType": "timeSeries",
            }

            # Write the dataset to a netcdf file
            con.print(
                f"NWIS daily streamflow observations retrieved, writing data to {nwis_cache_file}."
            )
            NWIS_ds.to_netcdf(nwis_cache_file)

            nwis_gage_info_aoi = nwis_gage_info_aoi[
                ~nwis_gage_info_aoi["poi_id"].isin(nobs_min_list)
            ]
            nwis_gage_info_aoi.to_csv(nwis_gages_file, index=False)  # , sep='\t')

    return NWIS_df


def create_sf_efc_df(
    output_netcdf_filename,
    owrd_df,
    ecy_df,
    NWIS_df,
    gages_df,
):
    """
    Combines daily streamflow dataframes from various database retrievals, currently NWIS, OWRD, and ECY into
    one xarray dataset.

    Note: all NWIS data is mirrored the OWRD database without any primary source tag/flag, so
    this section will also determine the original source agency of each daily observation, OWRD vs. NWIS.
    ECY does not republish NWIS data as not USGS gages are in the ECY database.

    The function will will also add to the xarray station information from the gages.csv file.
    The function will also add efc flow classifications to each daily streamflow (Ref from Parker).

    Finally the function will write the xarray to a netcdf file, sf_efc.nc meant to replace the sf.nc file provided
    with the subabsin model.

    Parameters
    ----------        
    output_netcdf_filename : pathlib Path class
        output netCDF filename for cachefile, e.g., model_dir / "notebook_output_files/nc_files/sf_efc.nc"        
    owrd_df : pandas DataFrame
        Dataframe containing OWRD mean daily streamflow data for the specified gage and date range.        
    ecy_df : pandas DataFrame
        Dataframe containing ECY mean daily streamflow data for the specified gage and date range.        
    NWIS_df : pandas DataFrame
        Dataframe of NWIS gages.        
    gages_df : pandas DataFrame
        Represents data pertaining to subdomain gages in parameter file, NWIS, and others.
    
    Returns
    -------
    xr_streamflow: xarray dataset
        Dataset containing streamflow data for all gages, including those from agencies outside USGS if applicable.
        
    """

    if output_netcdf_filename.exists():
        with xr.open_dataset(output_netcdf_filename) as sf:
            xr_streamflow = sf
            del sf
        con.print(
            "All available streamflow observations were previously retrieved and included in the sf_efc.nc file. [bold]To update delete sf_efc.nc[/bold] and rerun 1_Create_Streamflow_Observations.ipynb."
        )
    else:
        streamflow_df = NWIS_df.copy()  # Sets streamflow file to default, NWIS_df

        if (
            not owrd_df.empty
        ):  # If there is an owrd_df, it will be combined with streamflow_df and rewrite the streamflow_df
            # Merge NWIS and OWRD
            streamflow_df = pd.concat([streamflow_df, owrd_df])  # Join the two datasets
            # Drop duplicated indexes, keeping the first occurence (USGS occurs first)
            # try following this thing: https://saturncloud.io/blog/how-to-drop-duplicated-index-in-a-pandas-dataframe-a-complete-guide/#:~:text=Pandas%20provides%20the%20drop_duplicates(),names%20to%20the%20subset%20parameter.
            streamflow_df = streamflow_df[~streamflow_df.index.duplicated(keep="first")]
        else:
            pass

        if (
            not ecy_df.empty
        ):  # If there is an ecy_df, it will be combined with streamflow_df and rewrite the streamflow_df
            streamflow_df = pd.concat([streamflow_df, ecy_df])
            streamflow_df = streamflow_df[~streamflow_df.index.duplicated(keep="last")]
        else:
            pass
            
        xr_station_info = xr.Dataset.from_dataframe(
            gages_df
        )  # gages_df is the new source of gage metadata
        xr_streamflow_only = xr.Dataset.from_dataframe(streamflow_df)
        xr_streamflow = xr.merge(
            [xr_streamflow_only, xr_station_info], combine_attrs="drop_conflicts"
        )
        # test_poi = xr_streamflow.poi_id.values[2]

        # xr_streamflow.agency_id.sel(poi_id=test_poi).to_dataframe().agency_id.unique()
        xr_streamflow = xr_streamflow.sortby(
            "time", ascending=True
        )  # bug fix for xarray

        """
        Set attributes for the variables
        """
        xr_streamflow["discharge"].attrs = {
            "units": "ft3 s-1",
            "long_name": "discharge",
        }
        xr_streamflow["drainage_area"].attrs = {
            "units": "mi2",
            "long_name": "Drainage Area",
        }
        xr_streamflow["drainage_area_contrib"].attrs = {
            "units": "mi2",
            "long_name": "Effective drainage area",
        }
        xr_streamflow["latitude"].attrs = {
            "units": "degrees_north",
            "long_name": "Latitude",
        }
        xr_streamflow["longitude"].attrs = {
            "units": "degrees_east",
            "long_name": "Longitude",
        }
        xr_streamflow["poi_id"].attrs = {
            "role": "timeseries_id",
            "long_name": "Point-of-Interest ID",
            "_Encoding": "ascii",
        }
        xr_streamflow["poi_name"].attrs = {
            "long_name": "Name of POI station",
            "_Encoding": "ascii",
        }
        xr_streamflow["time"].attrs = {"standard_name": "time"}
        xr_streamflow["poi_agency"].attrs = {"_Encoding": "ascii"}
        xr_streamflow["agency_id"].attrs = {"_Encoding": "ascii"}

        # Set encoding
        # See 'String Encoding' section at https://crusaderky-xarray.readthedocs.io/en/latest/io.html
        xr_streamflow["poi_id"].encoding.update(
            {"dtype": "S15", "char_dim_name": "poiid_nchars"}
        )

        xr_streamflow["time"].encoding.update(
            {
                "_FillValue": None,
                "calendar": "standard",
                "units": "days since 1940-01-01 00:00:00",
            }
        )

        xr_streamflow["latitude"].encoding.update({"_FillValue": None})
        xr_streamflow["longitude"].encoding.update({"_FillValue": None})

        xr_streamflow["agency_id"].encoding.update(
            {"dtype": "S5", "char_dim_name": "agency_nchars"}
        )

        xr_streamflow["poi_name"].encoding.update(
            {"dtype": "S50", "char_dim_name": "poiname_nchars"}
        )

        xr_streamflow["poi_agency"].encoding.update(
            {"dtype": "S5", "char_dim_name": "mro_nchars", "_FillValue": ""}
        )
        # Add fill values to the data variables
        var_encoding = dict(_FillValue=netCDF4.default_fillvals.get("f4"))

        for cvar in xr_streamflow.data_vars:
            if xr_streamflow[cvar].dtype != object and cvar not in [
                "latitude",
                "longitude",
            ]:
                xr_streamflow[cvar].encoding.update(var_encoding)

        # add global attribute metadata
        xr_streamflow.attrs = {
            "Description": "Streamflow data for PRMS",
            "FeatureType": "timeSeries",
        }

        """
        Assign EFC values to the Xarray dataset
        """
        """
        Attributes for the EFC-related variables
        """
        attributes = {
            "efc": {
                "dtype": np.int32,
                "attrs": {
                    "long_name": "Extreme flood classification",
                    "_FillValue": -1,
                    "valid_range": [1, 5],
                    "flag_values": [1, 2, 3, 4, 5],
                    "flag_meanings": "large_flood small_flood high_flow_pulse low_flow extreme_low_flow",
                },
            },
            "ri": {
                "dtype": np.float32,
                "attrs": {
                    "long_name": "Recurrence interval",
                    "_FillValue": 9.96921e36,
                    "units": "year",
                },
            },
            "high_low": {
                "dtype": np.int32,
                "attrs": {
                    "long_name": "Discharge classification",
                    "_FillValue": -1,
                    "valid_range": [1, 3],
                    "flag_values": [1, 2, 3],
                    "flag_meanings": "low_flow ascending_limb descending_limb",
                },
            },
        }

        """
        """

        var_enc = {}
        for var, info in attributes.items():
            # Add the variable
            xr_streamflow[var] = xr.zeros_like(
                xr_streamflow["discharge"], dtype=info["dtype"]
            )

            var_enc[var] = {"zlib": True, "complevel": 2}

            # Take care of the attributes
            del xr_streamflow[var].attrs["units"]

            for kk, vv in info["attrs"].items():
                if kk == "_FillValue":
                    var_enc[var][kk] = vv
                else:
                    xr_streamflow[var].attrs[kk] = vv
        """
        Prepare efc variables
        """
        flow_col = "discharge"

        for pp in xr_streamflow.poi_id.data:
            try:
                df = efc(
                    xr_streamflow.discharge.sel(poi_id=pp).to_dataframe(),
                    flow_col=flow_col,
                )

                # Add EFC values to the xarray dataset for the poi
                xr_streamflow["efc"].sel(poi_id=pp).data[:] = df.efc.values
                xr_streamflow["high_low"].sel(poi_id=pp).data[:] = df.high_low.values
                xr_streamflow["ri"].sel(poi_id=pp).data[:] = df.ri.values
            except TypeError:
                pass

        """
        """
        xr_streamflow.to_netcdf(output_netcdf_filename)

    return xr_streamflow
