# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.17.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

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
# Find and set the "nhm-assist" root directory
root_dir = pl.Path(os.getcwd().rsplit("nhm-assist", 1)[0] + "nhm-assist")
sys.path.append(str(root_dir))
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements
from nhm_helpers.map_template import make_hf_map
from nhm_helpers.nhm_assist_utilities import load_subdomain_config

config = load_subdomain_config(root_dir)
# con.print(config)

# %%
import rasterio
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import split, linemerge, snap, nearest_points
from shapely import line_merge
from shapely.geometry import (
    LineString,
    mapping,
    LineString,
    MultiLineString,
    Point,
    Polygon,
    MultiPolygon,
    GeometryCollection,
)
from skimage import measure
from rasterstats import zonal_stats
from rasterio.merge import merge
from rasterio.io import MemoryFile
from rasterio.warp import calculate_default_transform, reproject
from rasterio.mask import mask
import io
from nhm_helpers.nhm_hydrofabric import make_hf_map_elements

# %% [markdown]
# ## Set/Merge DEM for the model subdomain
# #### Define the file path for the DEM.

# %%
dem_folder_path = pl.Path(
    root_dir / "nhgf_v2_fabric_modification/data_dependencies/dem"
)

# %%
dem_folder_path

# %%
dem_files = list(dem_folder_path.glob("*.tif"))
dem_files


# %% [markdown]
# #### Read the DEM for the model subdomain.

# %%
def load_subdomain_DEM(dem_folder_path):
    """ """
    from glob import glob

    dem_files = list(dem_folder_path.glob("*.tif"))
    merged_dem_path = pl.Path(
        root_dir
        / "nhgf_v2_fabric_modification/data_dependencies/dem/NEDSnapshot_merged_fixed_aoi.tif"
    )

    if merged_dem_path in dem_files:
        dem_file_path = merged_dem_path
    else:
        if len(dem_files) == 1:
            dem_file_path = dem_files[0]
        else:
            print(f"{len(dem_files)} DEM files need to be merged for this subdomain.")

            src_files_to_mosaic = [rasterio.open(f) for f in dem_files]

            # Mosaic returns a single array and the transform info
            mosaic, out_trans = merge(
                src_files_to_mosaic, method="max"
            )  # or 'max', 'min', etc.

            # Use metadata of first file as template
            out_meta = src_files_to_mosaic[0].meta.copy()
            out_meta.update(
                {
                    "driver": "GTiff",
                    "height": mosaic.shape[1],
                    "width": mosaic.shape[2],
                    "transform": out_trans,
                }
            )

            with rasterio.open(merged_dem_path, "w", **out_meta) as dest:
                dest.write(mosaic)
            dem_file_path = merged_dem_path
            print("A merged DEM file was created for this model subdomain.")

    return dem_file_path


# share w Andy Bock in future filling gaps function, but can also be used to join lines that are multi-line
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge


def combine_multilines(multilines):
    """
    Combines Shapely LineString polylines in a list that share start or end points.
    Returns a merged Shapely LineString or MultiLineString object.
    """
    merged = []
    multilines = multilines[:]  # copy input

    while multilines:
        polyline = multilines.pop(0)
        changed = True
        while changed:
            changed = False
            for i, other in enumerate(multilines):
                polyline_coords = list(polyline.coords)
                other_coords = list(other.coords)

                if polyline_coords[-1] == other_coords[0]:
                    polyline = LineString(polyline_coords + other_coords[1:])
                    multilines.pop(i)
                    changed = True
                    break
                elif polyline_coords[0] == other_coords[-1]:
                    polyline = LineString(other_coords[:-1] + polyline_coords)
                    multilines.pop(i)
                    changed = True
                    break
                elif polyline_coords[0] == other_coords[0]:
                    polyline = LineString(
                        list(reversed(other_coords)) + polyline_coords[1:]
                    )
                    multilines.pop(i)
                    changed = True
                    break
                elif polyline_coords[-1] == other_coords[-1]:
                    polyline = LineString(
                        polyline_coords + list(reversed(other_coords[:-1]))
                    )
                    multilines.pop(i)
                    changed = True
                    break
        merged.append(polyline)

    # Use linemerge to combine all merged LineStrings into longer lines if possible
    result = linemerge(MultiLineString(merged))

    return result


import geopandas as gpd
from shapely.geometry import LineString, MultiLineString


def flatten_multilines(geoms):
    """
    Flatten list of LineString and MultiLineString geometries into just LineStrings.
    """
    lines = []
    for geom in geoms:
        if isinstance(geom, MultiLineString):
            lines.extend(list(geom.geoms))
        elif isinstance(geom, LineString):
            lines.append(geom)
    return lines


def combine_multilines_geodataframe(gdf):
    """
    Given a GeoDataFrame with line geometries, combine connected line segments.
    Returns a GeoDataFrame similar in structure but with merged geometries.
    """
    # Flatten geometries to a list of LineStrings
    line_list = flatten_multilines(gdf.geometry)

    # Combine lines using the provided function
    merged_geom = combine_multilines(line_list)

    # Construct new GeoDataFrame with merged geometries
    if isinstance(merged_geom, LineString):
        new_gdf = gpd.GeoDataFrame(
            gdf.drop(columns="geometry").iloc[[0]],  # take first row attributes
            geometry=[merged_geom],
            crs=gdf.crs,
        )
    else:  # MultiLineString or GeometryCollection with multiple geometries
        new_gdf = gpd.GeoDataFrame(
            gdf.drop(columns="geometry").iloc[[0] * len(merged_geom.geoms)],
            geometry=list(merged_geom.geoms),
            crs=gdf.crs,
        )

    return new_gdf


# Example usage:
# gdf = gpd.read_file('your_lines.shp')
# combined_gdf = combine_multilines_geodataframe(gdf)
# combined_gdf.to_file('combined_lines.shp')

# %%
dem_file_path = load_subdomain_DEM(dem_folder_path)
print(dem_file_path)

# %% [markdown]
# ## Load the hrus from the National Hydrlogic Geospatial Fabric Version 2 geopackage (.gpkg) [Add ref for source material]

# %%
# Read in the hru_gdf
hru_gdf = gpd.read_file(
    root_dir
    / f"nhgf_v2_fabric_modification/domain_data/NHM_OR_domain/NHM_OR_draft.gpkg",
    layer="nhru",
)
# Convert the index from float to integer
hru_gdf.index = hru_gdf.index.astype(int)
hru_gdf.reset_index(inplace=True, drop=False)
hru_gdf.rename(columns={"index": "hru_index"}, inplace=True)

# %% [markdown]
# ## Create lines to split HRUs near high-elevation peaks.
# This workflow was created to...
# #### Load the peaks(point) shapefile.

# %%
peaks = root_dir / f"nhgf_v2_fabric_modification/domain_data/NHM_OR_domain/OR_peaks.shp"

# %%
# Read the peak points (GeoDataFrame)
peak_points = gpd.read_file(peaks)

# Ensure both GeoDataFrames are in the same CRS
if peak_points.crs != hru_gdf.crs:
    peak_points = peak_points.to_crs(hru_gdf.crs)
# peak_points = peak_points.loc[peak_points.elev_ft != 0]
buffered_polygons = peak_points.apply(
    lambda row: row["geometry"].buffer(row["buff_km"] * 1000), axis=1
)
peak_polygons = gpd.GeoDataFrame(geometry=buffered_polygons, crs=peak_points.crs)

peak_polygons.reset_index(inplace=True)
peak_polygons["elev_m"] = peak_points["elev_ft"] * 0.3048  # peak_points["elev_ft"]
peak_polygons = peak_polygons.loc[peak_polygons.elev_m != 0]

# %%
print(peak_points)

# %%
# Perform a spatial join to find intersecting boundary polygons

intersecting_data = gpd.sjoin(
    hru_gdf, peak_polygons, how="inner", predicate="intersects"
)

# Group by the index of HRU geometries and calculate the maximum max_elev
max_elevations = intersecting_data.groupby("hru_index")["elev_m"].min().reset_index()

# Rename columns for clarity
max_elevations.columns = ["hru_index", "max_boundary_elev"]
max_elevations
# Merge the maximum elevations back into hru_gdf; use left join to keep all HRU data
hru_peaks_gdf = hru_gdf.merge(
    max_elevations, left_on="hru_index", right_on="hru_index", how="inner"
)

# Fill NaN values in max_boundary_elev with None or appropriate value if necessary
hru_peaks_gdf["max_boundary_elev"] = hru_peaks_gdf["max_boundary_elev"].fillna(0)

# %%
hru_peaks_gdf.loc[hru_peaks_gdf["or_hru_id"] == 39110]

# %%
print(len(intersecting_data))
print(len(max_elevations))

# %% jupyter={"source_hidden": true}
# Drop duplicate indexes while keeping the first occurrence

# hru_elev_gdf = hru_gdf[~hru_gdf["hru_index"].duplicated(keep="first")]
hru_peaks_gdf = hru_peaks_gdf.sort_values(
    by=["hru_index", "max_boundary_elev"]
).drop_duplicates(subset="hru_index", keep="first")

# Round elevations to nearest 40
hru_peaks_gdf["rounded_elev"] = (hru_peaks_gdf["max_boundary_elev"] / 30).round() * 30

# %% jupyter={"source_hidden": true}
# Check for multipilygons
has_multipolygons = "MultiPolygon" in hru_peaks_gdf.geometry.geom_type.values
print(has_multipolygons)
print(f"length of hru_peaks_gdf is {len(hru_peaks_gdf)}")

# %% jupyter={"source_hidden": true}
hru_peaks_gdf = hru_peaks_gdf.explode(index_parts=True)
print(f"length of exploded hru_peaks_gdf is {len(hru_peaks_gdf)}")

# %%
lines_list = []
line_count = -1


def _to_coords(contour, transform):
    # Note: contour is a Nx2 array with [row, col] coordinates
    return [rasterio.transform.xy(transform, r, c) for r, c in contour]


for idx, row in hru_peaks_gdf.iterrows():
    hru_index = row["hru_index"]
    print(hru_index)
    row_geometry = row.geometry
    geometries = [mapping(row_geometry)]
    buffered = row.geometry.buffer(1000)  # 300 meter buffer
    buffered_geom = [mapping(buffered)]

    if dem_file_path:
        # print(dem_file_path)
        with rasterio.open(dem_file_path) as src:
            out_image, out_transform = mask(src, buffered_geom, crop=True)
            band_count = src.count
            if out_image.shape[1] > 1 and out_image.shape[2] > 1:
                out_meta = src.meta.copy()
                out_meta.update(
                    {
                        "driver": "GTiff",
                        "height": out_image.shape[1],
                        "width": out_image.shape[2],
                        "transform": out_transform,
                    }
                )
                with MemoryFile() as memfile:
                    with memfile.open(**out_meta) as dataset:
                        dataset.write(out_image)
                        # Read first band
                        data = dataset.read(1)
                        if np.any(data):
                            contours = measure.find_contours(
                                data, level=row["rounded_elev"]
                            )
                            lines = [
                                LineString(_to_coords(contour, out_transform))
                                for contour in contours
                                if len(contour) > 1
                            ]
                            clipped_lines = [
                                line.intersection(row_geometry) for line in lines
                            ]

                            flattened_lines = [
                                line
                                for multi_line in clipped_lines
                                if isinstance(multi_line, MultiLineString)
                                for line in multi_line.geoms  # Extract LineString geometries
                            ] + [
                                line
                                for line in clipped_lines
                                if isinstance(line, LineString)
                            ]  # Add other LineStrings

                            filtered_lines = [
                                line
                                for line in flattened_lines
                                if (
                                    isinstance(line, LineString)
                                    and not line.is_empty
                                    and (
                                        (
                                            len(line.coords) > 500
                                        )  # all lines longer than 50
                                        or (
                                            2 < len(line.coords) < 500
                                            and line.coords[0] != line.coords[-1]
                                        )  # length 10-50 and open
                                    )
                                )
                            ]
                            if filtered_lines:
                                gdf = gpd.GeoDataFrame(
                                    {
                                        "geometry": filtered_lines,
                                        "hru_index": row["hru_index"],
                                        "cont_type": "peak",
                                        "elev": row["rounded_elev"],
                                    },
                                    crs=hru_gdf.crs,
                                )
                                # Final check for multi segments
                                if len(gdf) > 1:
                                    gdf = combine_multilines_geodataframe(gdf)
                                else:
                                    pass

                                lines_list.append(gdf)
                                line_count = line_count + 1
                                # print(
                                #     f"HRU index {hru_index} and line_list_index{line_count}"
                                # )
                        else:
                            print(
                                f"No valid data in DEM for VPU: {vpu_value} at HRU index: {hru_index}"
                            )
            else:
                print(
                    f"Clipped DEM for VPU: {vpu_value} is too small (<2x2) at HRU index: {hru_index}"
                )
    else:
        print(f"No DEM file found for VPU: {vpu_value}")

# %%
# Step 1: Concatenate the list of GeoDataFrames into a single GeoDataFrame
peaks_lines_gdf = pd.concat(lines_list, ignore_index=True)

# Step 2 (optional): Set the CRS if it’s not already set
# Set the CRS to the CRS of one of the original GeoDataFrames if necessary
peaks_lines_gdf.set_crs(hru_gdf.crs, inplace=True)
peaks_lines_gdf.to_file("peaks_lines.shp")

# %%
peak_polygons.set_crs(hru_gdf.crs, inplace=True)
peak_polygons.to_file("peaks_polygons.shp")

# %%
has_multipolygons = "MultiPolygon" in hru_peaks_gdf.geometry.geom_type.values
print(has_multipolygons)

# %%
has_multilinestrings = any(isinstance(geom, MultiLineString) for geom in clipped_lines)
print(has_multilinestrings)

# %%
len(peaks_lines_gdf)

# %% [markdown]
# ## get max elevations for lowland polygons and associate with intersecting HRUs
#
#

# %%
lowlands = (
    root_dir
    / f"nhgf_v2_fabric_modification/domain_data/NHM_OR_domain/lowlands_greater_than_13sqmi.shp"
)

# %%
# Read the lowland boundary polygons (GeoDataFrame)
lowland_polygons = gpd.read_file(lowlands)

# Ensure both GeoDataFrames are in the same CRS
if lowland_polygons.crs != hru_gdf.crs:
    lowland_polygons = lowland_polygons.to_crs(hru_gdf.crs)

lowland_polygons.reset_index(inplace=True)

# %%

# %%
# Prepare results container
max_elev_results = []

for index, row in lowland_polygons.iterrows():
    # row_max = None  # Will hold the max elevation for this row
    with rasterio.open(dem_file_path) as raster:
        polygon_json = [mapping(row.geometry)]
        out_image, _ = mask(raster, polygon_json, crop=True)
        masked_data = out_image[0]

        # print(raster.nodata)

        valid = masked_data[masked_data > 0]
        if valid.size > 0:
            row_max = valid.mean() + ((valid.max() - valid.mean()) * 0.5)

    max_elev_results.append(row_max)

# Assign new column (will align by row index)
lowland_polygons["max_elev"] = max_elev_results
# Exceptions
# TechTeam meeting--faultblock valley adjustments to tghten up selected lowland to valley margin; Grande Ronde, Powder, Steens...eastern 3rd of state
lowland_polygons.loc[lowland_polygons["InPoly_FID"] == 75, "max_elev"] = 1480.00
lowland_polygons.loc[lowland_polygons["InPoly_FID"] == 41, "max_elev"] = 1460.00
lowland_polygons.loc[lowland_polygons["InPoly_FID"] == 93, "max_elev"] = 1500.00
lowland_polygons.loc[lowland_polygons["InPoly_FID"] == 22, "max_elev"] = 1100.00

lowland_polygons.to_file("lowland_polygons.shp")

# %%
lowland_polygons.loc[lowland_polygons["InPoly_FID"] == 93]

# %%
# Perform a spatial join to find intersecting boundary polygons
intersecting_data = gpd.sjoin(
    hru_gdf, lowland_polygons, how="inner", predicate="intersects"
)

# Group by the index of HRU geometries and calculate the maximum max_elev
max_elevations = intersecting_data.groupby("hru_index")["max_elev"].min().reset_index()

# Rename columns for clarity
max_elevations.columns = ["hru_index", "max_boundary_elev"]

# 3. Merge to keep all ties
hru_lowland_gdf = intersecting_data.merge(
    max_elevations,
    left_on=["hru_index", "max_elev"],
    right_on=["hru_index", "max_boundary_elev"],
)

# # Merge the maximum elevations back into hru_gdf; use left join to keep all HRU data
# hru_lowland_gdf = hru_gdf.merge(
#     max_elevations, left_index=True, right_on="index_left", how="left"
# )

# Fill NaN values in max_boundary_elev with None or appropriate value if necessary
hru_lowland_gdf["max_boundary_elev"] = hru_lowland_gdf["max_boundary_elev"].fillna(0)

# %%
# Drop duplicate indexes while keeping the first occurrence

# hru_elev_gdf = hru_gdf[~hru_gdf["hru_index"].duplicated(keep="first")]
hru_lowland_gdf = hru_lowland_gdf.sort_values(
    by=["hru_index", "max_boundary_elev"]
).drop_duplicates(subset="hru_index", keep="first")

hru_lowland_gdf["rounded_elev"] = (
    hru_lowland_gdf["max_boundary_elev"] / 30
).round() * 30

# %%
len(hru_lowland_gdf.rounded_elev)

# %% [markdown]
# ## crs and unit check before buffer

# %%
crs = hru_gdf.crs

# Print CRS details
print("CRS details:")
print(crs)

# Optionally, check if the units are in meters, degrees, etc.
# This can typically be inferred from the EPSG code
if crs is not None:
    print(f"CRS EPSG code: {crs.to_epsg()}")
    if crs.to_epsg() in [4326, 4269]:  # WGS 84
        print("Units: degrees")
    elif crs.to_proj4() is not None and "m" in crs.to_proj4():
        print("Units: meters")
    elif crs.to_proj4() is not None and "ft" in crs.to_proj4():
        print("Units: feet")
    else:
        print("Units: Unknown or derived from CRS definition")
else:
    print("No CRS defined for this GeoDataFrame.")

# %% [markdown]
# ## convert line_list to gdf and write

# %%
# Round elevations to nearest 40
hru_lowland_gdf["rounded_elev"] = (
    hru_lowland_gdf["max_boundary_elev"] / 30
).round() * 30

full_lines_list = []
lines_list = []
clipped_lines_list = []
line_count = -1


def _to_coords(contour, transform):
    # Note: contour is a Nx2 array with [row, col] coordinates
    return [rasterio.transform.xy(transform, r, c) for r, c in contour]


for idx, row in hru_lowland_gdf.iterrows():
    hru_index = row["hru_index"]
    print(hru_index)
    row_geometry = row.geometry
    geometries = [mapping(row_geometry)]
    buffered = row.geometry.buffer(300)  # 300 meter buffer
    buffered_geom = [mapping(buffered)]

    if dem_file_path:
        # print(dem_file_path)
        with rasterio.open(dem_file_path) as src:
            out_image, out_transform = mask(src, buffered_geom, crop=True)
            band_count = src.count
            if out_image.shape[1] > 1 and out_image.shape[2] > 1:
                out_meta = src.meta.copy()
                out_meta.update(
                    {
                        "driver": "GTiff",
                        "height": out_image.shape[1],
                        "width": out_image.shape[2],
                        "transform": out_transform,
                    }
                )
                with MemoryFile() as memfile:
                    with memfile.open(**out_meta) as dataset:
                        dataset.write(out_image)
                        # Read first band
                        data = dataset.read(1)
                        if np.any(data):
                            contours = measure.find_contours(
                                data, level=row["rounded_elev"]
                            )
                            lines = [
                                LineString(_to_coords(contour, out_transform))
                                for contour in contours
                                if len(contour) > 1
                            ]
                            if lines:
                                full_lines_gdf = gpd.GeoDataFrame(
                                    {
                                        "geometry": lines,
                                        "hru_index": row["hru_index"],
                                        "or_hru_id": row["or_hru_id"],
                                        "or_hru_id": row["or_hru_id"],
                                        "cont_type": "lowland",
                                        "elev": row["rounded_elev"],
                                    },
                                    crs=hru_gdf.crs,
                                )
                                # full_lines_list.append(clipped_gdf)
                            clipped_lines = [
                                line.intersection(row_geometry) for line in lines
                            ]
                            if clipped_lines:
                                clipped_gdf = gpd.GeoDataFrame(
                                    {
                                        "geometry": clipped_lines,
                                        "hru_index": row["hru_index"],
                                        "or_hru_id": row["or_hru_id"],
                                        "or_hru_id": row["or_hru_id"],
                                        "cont_type": "lowland",
                                        "elev": row["rounded_elev"],
                                    },
                                    crs=hru_gdf.crs,
                                )
                                clipped_lines_list.append(clipped_gdf)
                            flattened_lines = [
                                line
                                for multi_line in clipped_lines
                                if isinstance(multi_line, MultiLineString)
                                for line in multi_line.geoms  # Extract LineString geometries
                            ] + [
                                line
                                for line in clipped_lines
                                if isinstance(line, LineString)
                            ]  # Add other LineStrings

                            filtered_lines = [
                                line
                                for line in flattened_lines
                                if (
                                    isinstance(line, LineString)
                                    and not line.is_empty
                                    and (
                                        (
                                            len(line.coords) > 500
                                        )  # all lines longer than 50
                                        or (
                                            2 < len(line.coords) < 500
                                            and line.coords[0] != line.coords[-1]
                                        )  # length 10-50 and open
                                    )
                                )
                            ]

                            if filtered_lines:
                                gdf = gpd.GeoDataFrame(
                                    {
                                        "geometry": filtered_lines,
                                        "hru_index": row["hru_index"],
                                        "or_hru_id": row["or_hru_id"],
                                        "cont_type": "lowland",
                                        "elev": row["rounded_elev"],
                                    },
                                    crs=hru_gdf.crs,
                                )

                                # Final check for multi segments
                                if len(gdf) > 1:
                                    gdf = combine_multilines_geodataframe(gdf)
                                else:
                                    pass

                                lines_list.append(gdf)
                                line_count = line_count + 1
                                # print(
                                #     f"HRU index {hru_index} and line_list_index{line_count}"
                                # )
                        else:
                            print(
                                f"No valid data in DEM for VPU: {vpu_value} at HRU index: {hru_index}"
                            )
            else:
                print(
                    f"Clipped DEM for VPU: {vpu_value} is too small (<2x2) at HRU index: {hru_index}"
                )
    else:
        print(f"No DEM file found for VPU: {vpu_value}")

# %%
# Step 1: Concatenate the list of GeoDataFrames into a single GeoDataFrame
lowland_lines_gdf = pd.concat(lines_list, ignore_index=True)

# Step 2 (optional): Set the CRS if it’s not already set
# Set the CRS to the CRS of one of the original GeoDataFrames if necessary
lowland_lines_gdf.set_crs(hru_gdf.crs, inplace=True)
lowland_lines_gdf.to_file("lowland_lines.shp")

# %%
# this cell is a check
# Step 1: Concatenate the list of GeoDataFrames into a single GeoDataFrame
clipped_lines_gdf = pd.concat(clipped_lines_list, ignore_index=True)

# Step 2 (optional): Set the CRS if it’s not already set
# Set the CRS to the CRS of one of the original GeoDataFrames if necessary
clipped_lines_gdf.set_crs(hru_gdf.crs, inplace=True)
# clipped_lines_gdf.to_file("clipped_lowand_lines.shp")

# %%
# # this cell is also a check
# # Step 1: Concatenate the list of GeoDataFrames into a single GeoDataFrame
# full_lines_gdf = pd.concat(full_lines_list, ignore_index=True)

# # Step 2 (optional): Set the CRS if it’s not already set
# # Set the CRS to the CRS of one of the original GeoDataFrames if necessary
# full_lines_gdf.set_crs(hru_gdf.crs, inplace=True)
# # full_lines_gdf.to_file("full_lowand_lines.shp")

# %% jupyter={"source_hidden": true}
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


# def create_hru_map(hru_gdf):

#     hru_map = folium.GeoJson(
#         hru_gdf,
#         style_function=style_function_hru_map,
#         # highlight_function=highlight_function_hru_map,
#         name="NHM HRUs",
#         # tooltip=tooltip_hru,
#         # popup=popup_hru,
#     )
#     return hru_map


# def create_peaks_map(hru_gdf, line_style):

#     hru_map = folium.GeoJson(
#         hru_gdf,
#         style_function=line_style,
#         # highlight_function=highlight_function_hru_map,
#         name="NHM peak HRU breaks",
#         # tooltip=tooltip_hru,
#         # popup=popup_hru,
#     )
#     return hru_map


def create_hru_map(hru_gdf, line_style, layer_name):

    hru_map = folium.GeoJson(
        hru_gdf,
        style_function=line_style,
        # highlight_function=highlight_function_hru_map,
        name=layer_name,
        # tooltip=tooltip_hru,
        # popup=popup_hru,
    )
    return hru_map


# %% jupyter={"source_hidden": true}
def is_wsl():
    """
    Check if the code is running in Windows Subsystem for Linux (WSL).

    Returns
    -------
    bool
        True if running in WSL, False otherwise.
    """

    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
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
                subprocess.check_output(["wslpath", "-w", map_file_str])
                .decode()
                .strip()
            )
            map_file_str = f"file:///{windows_path}"
        webbrowser.open(map_file_str, new=2)


# %% jupyter={"source_hidden": true}
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

from rich import pretty
from rich.console import Console
from nhm_helpers.nhm_output_visualization import (
    create_streamflow_obs_datasets,
    create_sum_seg_var_dataarrays,
    create_sum_var_annual_gdf,
)
from nhm_helpers.output_plots import calculate_monthly_kge_in_poi_df
import subprocess
import os
import webbrowser

pretty.install()
con = Console()
jupyter_black.load()
warnings.filterwarnings("ignore")

# %%
states_gdf = gpd.read_file(
    root_dir / "data_dependencies/US_states/tl_2017_us_state.shp"
).to_crs(hru_gdf.crs)
state = states_gdf.loc[
    states_gdf["STUSPS"] == "OR"
]  # = list((states_gdf.clip(hru_gdf).loc[:]["STUSPS"]).values
state_buff = state.buffer(50000)

hru_clipped = hru_gdf.clip(state_buff)

# %%
print(len(hru_clipped))

# %%
style_function_hru_map_light = lambda x: {
    "opacity": 1,
    "fillColor": "#00000000",  #'goldenrod',
    "color": "white",
    "weight": 1.5,
}
style_function_hru_map_dark = lambda x: {
    "opacity": 1,
    "fillColor": "#00000000",  #'goldenrod',
    "color": "black",
    "weight": 1.5,
}

style_function_peaks_map_dark = lambda x: {
    "opacity": 1,
    "fillColor": "#00000000",  #'goldenrod',
    "color": "black",
    "weight": 1.75,
}
style_function_peaks_map_light = lambda x: {
    "opacity": 1,
    "fillColor": "#00000000",  #'goldenrod',
    "color": "white",
    "weight": 1.75,
}

style_function_lowland_map_light = lambda x: {
    "opacity": 1,
    "fillColor": "#00000000",  #'goldenrod',
    "color": "white",
    "weight": 1.75,
}

style_function_lowland_map_dark = lambda x: {
    "opacity": 1,
    "fillColor": "#00000000",  #'goldenrod',
    "color": "black",
    "weight": 1.75,
}
USGSHydroCached_layer, USGStopo_layer, Esri_WorldImagery, OpenTopoMap = (
    folium_map_tiles()
)
minimap = create_minimap()

################################################

# Make a list of the state abbreviations the subdomain intersects for NWIS queries
states_gdf = gpd.read_file(
    root_dir / "data_dependencies/US_states/tl_2017_us_state.shp"
).to_crs(hru_gdf.crs)
state = states_gdf.loc[
    states_gdf["STUSPS"] == "OR"
]  # = list((states_gdf.clip(hru_gdf).loc[:]["STUSPS"]).values

# create_hru_map(hru_gdf, line_style, layer_name)
hru_map_d = create_hru_map(
    hru_clipped, style_function_hru_map_dark, "NHGFv2 HRUs (dark)"
)
hru_map_l = create_hru_map(
    hru_clipped, style_function_hru_map_light, "NHGFv2 HRUs (light)"
)
# peaks_map = create_peaks_map(peaks_lines_gdf)
peaks_map_d = create_hru_map(
    peaks_lines_gdf, style_function_peaks_map_dark, "Peaks lines (dark)"
)
peaks_map_l = create_hru_map(
    peaks_lines_gdf, style_function_peaks_map_light, "Peaks lines (light)"
)
# lowlands_map = create_lowlands_map(lowland_lines_gdf)
lowlands_map_d = create_hru_map(
    lowland_lines_gdf, style_function_lowland_map_dark, "Lowland lines (dark)"
)
lowlands_map_l = create_hru_map(
    lowland_lines_gdf, style_function_lowland_map_light, "Lowland lines (light)"
)

m2 = folium.Map()
m2 = folium.Map(
    # location=[pfile_lat, pfile_lon],
    tiles=USGSHydroCached_layer,
    # zoom_start=zoom,
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


hru_map_d.add_to(m2)
hru_map_l.add_to(m2)
peaks_map_d.add_to(m2)
peaks_map_l.add_to(m2)
lowlands_map_d.add_to(m2)
lowlands_map_l.add_to(m2)
folium.GeoJson(peak_points).add_to(m2)
folium.GeoJson(lowland_polygons).add_to(m2)

plugins.Fullscreen(position="topleft").add_to(m2)
folium.LayerControl(collapsed=True, position="bottomright").add_to(m2)

##add Non-poi gage markers and labels using row df.interowss loop


# explan_txt = f"HRUs: {pdb.dimensions.get('nhru').meta['size']}, segments: {pdb.dimensions.get('nsegment').meta['size']},<br>gages: {pdb.dimensions.get('npoigages').meta['size']}, Potential gages: {len(additional_gages)}"
# title_html = f"<h1 style='position:absolute;z-index:100000;font-size: 28px;left:26vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '><strong>The NHM {subdomain} model: hydrofabric elements</strong><br><h1 style='position:absolute;z-index:100000;font-size: 20px;left:31vw;right:5vw; top:4vw;text-shadow: 3px  3px  3px white,-3px -3px  3px white,3px -3px  3px white,-3px  3px  3px white; '> {explan_txt}</h1>"

# add custom legend


# m2.get_root().html.add_child(Element(title_html))

map_file = f"hf_v2_map.html"
m2.save(map_file)

make_webbrowser_map(map_file)

# %%
len(peaks_lines_gdf) + len(lowland_lines_gdf)

# %%

# %%
