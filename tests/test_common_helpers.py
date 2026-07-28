from __future__ import annotations

import unittest


class CommonEfcTests(unittest.TestCase):
    def test_efc_reexported_from_common_in_nhm(self):
        from assist.common import efc as common_efc
        from assist.nhm import efc as nhm_efc

        self.assertIs(nhm_efc.efc, common_efc.efc)
        self.assertIs(nhm_efc.plot_efc, common_efc.plot_efc)
        self.assertIs(nhm_efc.compute_efc, common_efc.compute_efc)

    def test_efc_reexported_from_common_in_nhf(self):
        from assist.common import efc as common_efc
        from assist.nhf import efc as nhf_efc

        self.assertIs(nhf_efc.efc, common_efc.efc)
        self.assertIs(nhf_efc.plot_efc, common_efc.plot_efc)


class CommonHelpersTests(unittest.TestCase):
    def test_helpers_reexported_from_common_in_nhm(self):
        from assist.common import helpers as common_helpers
        from assist.nhm import nhm_helpers

        self.assertIs(
            nhm_helpers.subset_stream_network, common_helpers.subset_stream_network
        )
        self.assertIs(nhm_helpers.hrus_by_poi, common_helpers.hrus_by_poi)
        self.assertIs(nhm_helpers.create_poi_group, common_helpers.create_poi_group)

    def test_helpers_reexported_from_common_in_nhf(self):
        # Both sides now speak `poi_gage_id`, so nhf is a pure re-export of common.
        from assist.common import helpers as common_helpers
        from assist.nhf import nhm_helpers_v2 as nhf_helpers

        self.assertIs(
            nhf_helpers.subset_stream_network, common_helpers.subset_stream_network
        )
        self.assertIs(nhf_helpers.hrus_by_poi, common_helpers.hrus_by_poi)
        self.assertIs(nhf_helpers.create_poi_group, common_helpers.create_poi_group)


class OutputVisualizationShimTests(unittest.TestCase):
    def test_reexport_identity_in_nhm(self):
        from assist.common import output_visualization as common_ov
        from assist.nhm import nhm_output_visualization as nhm_ov

        for name in ("retrieve_hru_output_info", "create_sum_var_annual_df",
                     "create_streamflow_obs_datasets"):
            self.assertIs(getattr(nhm_ov, name), getattr(common_ov, name))

    def test_reexport_identity_in_nhf(self):
        from assist.common import output_visualization as common_ov
        from assist.nhf import nhm_output_visualization_v2 as nhf_ov

        for name in ("create_sum_var_annual_df", "create_var_ts_for_poi_basin_df"):
            self.assertIs(getattr(nhf_ov, name), getattr(common_ov, name))


class OutputPlotsShimTests(unittest.TestCase):
    def test_reexport_identity_nhm(self):
        from assist.common import output_plots as common_op
        from assist.nhm import output_plots as nhm_op

        for name in ("is_wsl", "make_webbrowser_map", "stats_table",
                     "make_plot_var_for_hrus_in_poi_basin", "oopla",
                     "calculate_monthly_kge_in_poi_df", "create_streamflow_plot"):
            self.assertIs(getattr(nhm_op, name), getattr(common_op, name))

    def test_reexport_identity_nhf(self):
        from assist.common import output_plots as common_op
        from assist.nhf import output_plots_v2 as nhf_op

        for name in ("is_wsl", "make_webbrowser_map", "stats_table",
                     "make_plot_var_for_hrus_in_poi_basin", "oopla",
                     "calculate_monthly_kge_in_poi_df", "create_streamflow_plot"):
            self.assertIs(getattr(nhf_op, name), getattr(common_op, name))

    def test_module_constants_reexported(self):
        from assist.common import output_plots as common_op
        from assist.nhm import output_plots as nhm_op
        from assist.nhf import output_plots_v2 as nhf_op

        for name in ("plot_colors", "var_colors_dict", "leg_only_dict"):
            self.assertIs(getattr(nhm_op, name), getattr(common_op, name))
            self.assertIs(getattr(nhf_op, name), getattr(common_op, name))


if __name__ == "__main__":
    unittest.main()
