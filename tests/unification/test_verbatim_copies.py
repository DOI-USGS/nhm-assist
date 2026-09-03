"""Assert the functions this task copies really were copied unchanged.

Compares the AST of each function in assist.common.assist_utilities against the
same function in the pre-unification nhm module, read out of git. This is the
guard against a transcription slip during a "verbatim" copy.
"""
import ast
import copy
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


def _strip_docstring(fn_node: ast.FunctionDef) -> ast.FunctionDef:
    """Drop a leading bare-string statement (the docstring), if present.

    Final review Fix 5 (2026-08-30) added short documentation notes to
    create_append_gages_to_param_file and make_myparam_addl_gages_param_file
    recording that they require nhm-shaped input. That is a deliberate,
    reviewed divergence from the baseline body, not a transcription slip, so
    it is excluded here rather than weakening the comparison for everything
    else in the function.
    """
    body = fn_node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        fn_node = copy.deepcopy(fn_node)
        fn_node.body = fn_node.body[1:]
    return fn_node


def _ast_of(fn):
    module = ast.parse(inspect.getsource(fn))
    fn_node = module.body[0]
    assert isinstance(fn_node, ast.FunctionDef)
    return ast.dump(_strip_docstring(fn_node))


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
