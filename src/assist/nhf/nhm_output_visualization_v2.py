from assist.common import output_visualization as _ov
from assist.common._adapters import poi_adapt
from assist.common.output_visualization import (
    create_mean_var_dataarrays,
    create_streamflow_obs_datasets,
    create_sum_seg_var_dataarrays,
    create_sum_var_annual_df,
    create_sum_var_annual_gdf,
    create_sum_var_dataarrays,
    create_sum_var_monthly_df,
    create_var_daily_df,
    retrieve_hru_output_info,
)

__all__ = [
    "retrieve_hru_output_info",
    "create_sum_var_dataarrays",
    "create_mean_var_dataarrays",
    "create_sum_var_annual_gdf",
    "create_sum_var_annual_df",
    "create_sum_var_monthly_df",
    "create_var_daily_df",
    "create_var_ts_for_poi_basin_df",
    "create_sum_seg_var_dataarrays",
    "create_streamflow_obs_datasets",
]

# Only this function references the POI id (as `poi_gage_id` in nhf). Dispatch to
# common at call time (not import time) so the canonical target stays patchable.
@poi_adapt
def create_var_ts_for_poi_basin_df(*args, **kwargs):
    return _ov.create_var_ts_for_poi_basin_df(*args, **kwargs)
