"""The two heaviest-divergence functions, taken verbatim from nhf."""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHF_PATH = "src/assist/nhf/nhm_hydrofabric_v2.py"
FROM_NHF = ["create_poi_df", "create_default_gages_file"]


@pytest.fixture(scope="module")
def nhf_baseline():
    return load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_hf_poi")


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


def test_default_gages_uses_the_canonical_gage_lookup():
    """nhf calls find_missing_gage_info; that is what lets Task 7 delete the
    private find_missing_gage_metadata carried over from concern 1."""
    import assist.common.hydrofabric as common

    source = inspect.getsource(common.create_default_gages_file)
    assert "find_missing_gage_info" in source
    assert "find_missing_gage_metadata" not in source


def test_poi_df_uses_the_canonical_gage_id_column():
    import assist.common.hydrofabric as common

    source = inspect.getsource(common.create_poi_df)
    assert "poi_gage_id" in source
