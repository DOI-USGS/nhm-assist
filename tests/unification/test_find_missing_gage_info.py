"""find_missing_gage_info is nhf's; nhm's survives under a private name."""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHM_PATH = "src/assist/nhm/nhm_assist_utilities.py"
NHF_PATH = "src/assist/nhf/nhm_assist_utilities_v2.py"


@pytest.fixture(scope="module")
def baselines():
    nhm = load_module_from_git(BASELINE_REV, NHM_PATH, "baseline_nhm_for_fmgi")
    nhf = load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_for_fmgi")
    return nhm, nhf


def _body_ast(fn):
    """AST of a function ignoring its name, so a rename does not register."""
    tree = ast.parse(inspect.getsource(fn).lstrip())
    node = tree.body[0]
    node.name = "_"
    return ast.dump(node)


def test_canonical_name_has_nhf_signature(baselines):
    import assist.common.assist_utilities as common

    _, nhf = baselines
    assert inspect.signature(common.find_missing_gage_info) == inspect.signature(
        nhf.find_missing_gage_info
    )


def test_canonical_is_verbatim_nhf(baselines):
    import assist.common.assist_utilities as common

    _, nhf = baselines
    assert _body_ast(common.find_missing_gage_info) == _body_ast(nhf.find_missing_gage_info)


def test_nhm_version_survives_under_a_private_name(baselines):
    import assist.common.assist_utilities as common

    nhm, _ = baselines
    assert inspect.signature(common._find_missing_gage_metadata) == inspect.signature(
        nhm.find_missing_gage_info
    )
    assert _body_ast(common._find_missing_gage_metadata) == _body_ast(
        nhm.find_missing_gage_info
    )


def test_nhm_private_helpers_came_along():
    import assist.common.assist_utilities as common

    assert callable(common._load_nldi_cached)
    assert callable(common._translate_waterdata_columns)


def test_nhm_metadata_lookup_keeps_its_return_contract(tmp_path):
    """Empty input must give an empty frame indexed by poi_gage_id."""
    import assist.common.assist_utilities as common
    import pandas as pd

    out = common._find_missing_gage_metadata(
        gage_ids=[],
        poi_df=pd.DataFrame(),
        resource_file_path=tmp_path / "missing.csv",
        root_dir=tmp_path,
    )
    assert out.empty
    assert out.index.name == "poi_gage_id"
    assert list(out.columns) == ["latitude", "longitude", "poi_name", "poi_agency"]
