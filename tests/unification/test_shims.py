"""assist_utilities lives only at assist.common; the fabric shims are gone.

This file used to assert that `assist.nhm.nhm_assist_utilities` and
`assist.nhf.nhm_assist_utilities_v2` re-exported the same objects as common/.
Those shims have been removed, so what remains worth asserting is that common/
still exposes the whole surface they used to forward, and that the things
retired during the unification stay retired.
"""
import pytest

import assist.common.assist_utilities as common

EXPECTED = [
    "bynhru_parameter_list",
    "bynmonth_bynhru_parameter_list",
    "bynsegment_parameter_list",
    "create_append_gages_to_param_file",
    "create_append_gages_to_param_file_v2",
    "delete_notebook_output_files",
    "fetch_FMI_npoigages_info",
    "fetch_non_ref_npoigages_info",
    "fetch_ref_npoigages_info",
    "fetch_waterdata_gage_info",
    "find_missing_gage_info",
    "load_subdomain_config",
    "make_HW_cal_level_files",
    "make_myparam_addl_gages_param_file",
    "make_obs_plot_files",
    "make_plots_par_vals",
]


@pytest.mark.parametrize("name", EXPECTED)
def test_common_exposes_the_whole_former_shim_surface(name):
    assert callable(getattr(common, name, None)), f"{name} missing from common"


def test_private_helpers_are_not_exported():
    assert not any(n.startswith("_") for n in getattr(common, "__all__", []))


def test_metadata_lookup_is_public_now():
    assert not hasattr(common, "find_missing_gage_metadata")
    assert not hasattr(common, "_find_missing_gage_metadata")
    assert callable(common.find_missing_gage_info)
