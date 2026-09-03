"""Guard: the harness must see the differences we already measured.

If these fail, the harness is not a usable oracle and no unification should
proceed on top of it.
"""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHM_PATH = "src/assist/nhm/nhm_assist_utilities.py"
NHF_PATH = "src/assist/nhf/nhm_assist_utilities_v2.py"

# Measured at 27f7144. Excludes make_plots_par_vals, which differs in source text
# only by a comment (##%%time vs # #%%time). AST comparison, used by this test,
# omits comments, so it is semantically identical.
EXPECTED_DIFFERING = {
    "create_append_gages_to_param_file",
    "delete_notebook_output_files",
    "find_missing_gage_info",
    "load_subdomain_config",
    "make_myparam_addl_gages_param_file",
    "make_obs_plot_files",
}
EXPECTED_NHF_ONLY = {
    "create_append_gages_to_param_file_v2",
    "fetch_FMI_npoigages_info",
    "fetch_non_ref_npoigages_info",
    "fetch_ref_npoigages_info",
    "fetch_waterdata_gage_info",
}
EXPECTED_NHM_ONLY = {
    "_load_nldi_cached",
    "_translate_waterdata_columns",
    "fetch_nwis_gage_info",
    "make_HW_cal_level_files",
}


@pytest.fixture(scope="module")
def baselines():
    nhm = load_module_from_git(BASELINE_REV, NHM_PATH, "baseline_nhm_utils")
    nhf = load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_utils")
    return nhm, nhf


def _public_functions(module):
    return {
        name
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) and obj.__module__ == module.__name__
    }


def test_both_baselines_import(baselines):
    nhm, nhf = baselines
    assert _public_functions(nhm)
    assert _public_functions(nhf)


def test_nhm_only_functions_are_present(baselines):
    nhm, nhf = baselines
    only_nhm = _public_functions(nhm) - _public_functions(nhf)
    assert EXPECTED_NHM_ONLY <= only_nhm


def test_nhf_only_functions_are_present(baselines):
    nhm, nhf = baselines
    only_nhf = _public_functions(nhf) - _public_functions(nhm)
    assert EXPECTED_NHF_ONLY <= only_nhf


def test_shared_functions_really_do_differ(baselines):
    """Source-level check: each expected-differing function differs."""
    nhm, nhf = baselines
    for name in sorted(EXPECTED_DIFFERING):
        a = ast.dump(ast.parse(inspect.getsource(getattr(nhm, name))))
        b = ast.dump(ast.parse(inspect.getsource(getattr(nhf, name))))
        assert a != b, f"{name} was expected to differ but is identical"
