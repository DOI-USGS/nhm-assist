"""The two low-divergence hydrofabric functions, taken verbatim from nhf."""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHF_PATH = "src/assist/nhf/nhm_hydrofabric_v2.py"
FROM_NHF = ["read_gages_file"]


@pytest.fixture(scope="module")
def nhf_baseline():
    return load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_hf_basics")


def _ast_of(fn):
    return ast.dump(ast.parse(inspect.getsource(fn)))


@pytest.mark.parametrize("name", FROM_NHF)
def test_copy_is_ast_identical_to_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert _ast_of(getattr(common, name)) == _ast_of(getattr(nhf_baseline, name))


@pytest.mark.parametrize("name", FROM_NHF)
def test_signature_matches_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert inspect.signature(getattr(common, name)) == inspect.signature(
        getattr(nhf_baseline, name)
    )
