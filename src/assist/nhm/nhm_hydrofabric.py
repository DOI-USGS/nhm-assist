"""Compatibility shim. Implementation lives in assist.common.hydrofabric."""
from assist.common.hydrofabric import (
    create_default_gages_file,
    create_hru_gdf,
    create_poi_df,
    create_segment_gdf,
    evaluate_and_fix_nhru_geometry,
    make_hf_map_elements,
    read_gages_file,
)

__all__ = [
    "create_default_gages_file",
    "create_hru_gdf",
    "create_poi_df",
    "create_segment_gdf",
    "evaluate_and_fix_nhru_geometry",
    "make_hf_map_elements",
    "read_gages_file",
]
