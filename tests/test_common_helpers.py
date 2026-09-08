"""The shared helpers are reachable only at assist.common.

This file used to assert that the `assist.nhm.*` / `assist.nhf.*` re-export
shims forwarded the same objects as common/. Those shims are gone, so what is
worth asserting now is the surface itself -- every name the shims used to
forward is still present on the unified module -- and that the retired fabric
paths really are unimportable, so nothing silently depends on them again.
"""
from __future__ import annotations

import importlib
import unittest

# module under assist.common -> names it must expose. These are exactly the
# names the removed shims were checked against.
COMMON_SURFACE = {
    "efc": ("efc", "plot_efc", "compute_efc"),
    "helpers": ("subset_stream_network", "hrus_by_poi", "create_poi_group"),
    "output_visualization": (
        "retrieve_hru_output_info",
        "create_sum_var_annual_df",
        "create_streamflow_obs_datasets",
        "create_var_ts_for_poi_basin_df",
    ),
    "output_plots": (
        "is_wsl",
        "make_webbrowser_map",
        "stats_table",
        "make_plot_var_for_hrus_in_poi_basin",
        "oopla",
        "calculate_monthly_kge_in_poi_df",
        "create_streamflow_plot",
    ),
}

OUTPUT_PLOTS_CONSTANTS = ("plot_colors", "var_colors_dict", "leg_only_dict")

RETIRED_PATHS = (
    "assist.nhm.efc",
    "assist.nhm.nhm_helpers",
    "assist.nhm.nhm_output_visualization",
    "assist.nhm.output_plots",
    "assist.nhf.efc",
    "assist.nhf.nhm_helpers_v2",
    "assist.nhf.nhm_output_visualization_v2",
    "assist.nhf.output_plots_v2",
)


class CommonSurfaceTests(unittest.TestCase):
    def test_every_former_shim_name_is_on_common(self):
        for module_name, names in COMMON_SURFACE.items():
            module = importlib.import_module(f"assist.common.{module_name}")
            for name in names:
                with self.subTest(module=module_name, name=name):
                    self.assertTrue(
                        callable(getattr(module, name, None)),
                        f"assist.common.{module_name}.{name} is missing",
                    )

    def test_output_plots_module_constants_survived(self):
        module = importlib.import_module("assist.common.output_plots")
        for name in OUTPUT_PLOTS_CONSTANTS:
            with self.subTest(name=name):
                self.assertIsNotNone(getattr(module, name, None))


class RetiredFabricPathTests(unittest.TestCase):
    def test_the_fabric_module_paths_are_gone(self):
        for path in RETIRED_PATHS:
            with self.subTest(path=path):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(path)


if __name__ == "__main__":
    unittest.main()
