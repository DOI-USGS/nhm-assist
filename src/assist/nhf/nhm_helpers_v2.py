from assist.common import helpers as _common_helpers
from assist.common.helpers import hrus_by_poi, subset_stream_network

__all__ = ["subset_stream_network", "hrus_by_poi", "create_poi_group"]


def create_poi_group(hru_gdf, poi_df, param_filename):
    """nhf uses a `poi_gage_id` column; normalize to the canonical `poi_id`."""
    if "poi_gage_id" in poi_df.columns and "poi_id" not in poi_df.columns:
        poi_df = poi_df.rename(columns={"poi_gage_id": "poi_id"})
    return _common_helpers.create_poi_group(hru_gdf, poi_df, param_filename)
