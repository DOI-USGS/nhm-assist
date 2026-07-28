from assist.common import output_plots as _op
from assist.common._adapters import poi_adapt
from assist.common.output_plots import (
    is_wsl,
    leg_only_dict,
    make_webbrowser_map,
    plot_colors,
    stats_table,
    var_colors_dict,
)

__all__ = [
    "plot_colors",
    "var_colors_dict",
    "leg_only_dict",
    "is_wsl",
    "make_webbrowser_map",
    "make_plot_var_for_hrus_in_poi_basin",
    "oopla",
    "stats_table",
    "calculate_monthly_kge_in_poi_df",
    "create_streamflow_plot",
]


# These four reference the POI id (as `poi_gage_id` / `poi_gage_id_sel` in nhf).
# Dispatch to common at call time (not import time) so the target stays patchable.
@poi_adapt
def make_plot_var_for_hrus_in_poi_basin(*args, **kwargs):
    return _op.make_plot_var_for_hrus_in_poi_basin(*args, **kwargs)


@poi_adapt
def oopla(*args, **kwargs):
    return _op.oopla(*args, **kwargs)


@poi_adapt
def calculate_monthly_kge_in_poi_df(*args, **kwargs):
    return _op.calculate_monthly_kge_in_poi_df(*args, **kwargs)


@poi_adapt
def create_streamflow_plot(*args, **kwargs):
    return _op.create_streamflow_plot(*args, **kwargs)
