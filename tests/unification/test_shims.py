# tests/unification/test_shims.py
"""Both shims must expose the same objects as common/, and contain no logic."""
import pytest

import assist.common.assist_utilities as common
import assist.nhf.nhm_assist_utilities_v2 as nhf
import assist.nhm.nhm_assist_utilities as nhm

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
def test_both_shims_export_the_same_object(name):
    assert getattr(nhm, name) is getattr(common, name), f"nhm/{name}"
    assert getattr(nhf, name) is getattr(common, name), f"nhf/{name}"


@pytest.mark.parametrize("module", [nhm, nhf])
def test_shim_defines_no_logic_of_its_own(module):
    source = open(module.__file__, encoding="utf-8").read()
    assert "def " not in source, f"{module.__name__} still defines functions"
    assert "from assist.common.assist_utilities import" in source


def test_private_helpers_are_not_exported():
    for module in (nhm, nhf):
        assert "_load_nldi_cached" not in (module.__all__ or [])
        assert "_translate_waterdata_columns" not in (module.__all__ or [])


def test_metadata_lookup_is_public_now():
    assert not hasattr(common, "find_missing_gage_metadata")
    assert not hasattr(common, "_find_missing_gage_metadata")
