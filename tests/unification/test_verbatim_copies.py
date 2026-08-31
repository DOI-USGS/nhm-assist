"""Assert the functions this task copies really were copied unchanged.

Compares the AST of each function in assist.common.assist_utilities against the
same function in the pre-unification nhm module, read out of git. This is the
guard against a transcription slip during a "verbatim" copy.
"""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHM_PATH = "src/assist/nhm/nhm_assist_utilities.py"

COPIED_FROM_NHM = [
    "make_plots_par_vals",
    "create_append_gages_to_param_file",
    "make_myparam_addl_gages_param_file",
]


@pytest.fixture(scope="module")
def nhm_baseline():
    return load_module_from_git(BASELINE_REV, NHM_PATH, "baseline_nhm_for_copies")


def _ast_of(fn):
    return ast.dump(ast.parse(inspect.getsource(fn)))


@pytest.mark.parametrize("name", COPIED_FROM_NHM)
def test_copy_is_ast_identical_to_the_nhm_baseline(name, nhm_baseline):
    import assist.common.assist_utilities as common

    assert _ast_of(getattr(common, name)) == _ast_of(getattr(nhm_baseline, name)), (
        f"{name} in common/ is not a verbatim copy of the nhm baseline"
    )


@pytest.mark.parametrize("name", COPIED_FROM_NHM)
def test_copy_keeps_the_baseline_signature(name, nhm_baseline):
    import assist.common.assist_utilities as common

    assert inspect.signature(getattr(common, name)) == inspect.signature(
        getattr(nhm_baseline, name)
    )


def test_pdb_get_nhm_seg_is_not_rewritten():
    """`pdb.get("nhm_seg")` is a pyPRMS parameter name, not a DataFrame column."""
    import assist.common.assist_utilities as common

    source = inspect.getsource(common.make_myparam_addl_gages_param_file)
    assert 'pdb.get("nhm_seg")' in source
