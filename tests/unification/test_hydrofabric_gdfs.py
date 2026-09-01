"""The fabric-tolerance in these two functions is the point of taking nhf's side."""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHF_PATH = "src/assist/nhf/nhm_hydrofabric_v2.py"


@pytest.fixture(scope="module")
def nhf_baseline():
    return load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_hf_gdfs")


def _ast_of(fn):
    return ast.dump(ast.parse(inspect.getsource(fn)))


@pytest.mark.parametrize("name", ["create_hru_gdf", "create_segment_gdf"])
def test_copy_is_ast_identical_to_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert _ast_of(getattr(common, name)) == _ast_of(getattr(nhf_baseline, name))


def test_hru_gdf_keeps_the_missing_hru_id_fallback():
    """GFv1.1 geopackages have no hru_id; without this fallback they break."""
    import assist.common.hydrofabric as common

    source = inspect.getsource(common.create_hru_gdf)
    assert '"hru_id" not in hru_gdb.columns' in source
    assert "model_hru_idx" in source


def test_segment_gdf_keeps_the_nhm_seg_id_rename():
    """GFv2 geopackages have nhm_seg_id, not nhm_seg; the rename bridges them."""
    import assist.common.hydrofabric as common

    source = inspect.getsource(common.create_segment_gdf)
    assert "nhm_seg_id" in source
    assert "nhm_seg" in source


def test_neither_function_hardcodes_a_single_fabric_only_column():
    """A bare set_index on nhm_seg with no fallback is the nhm bug we are avoiding."""
    import assist.common.hydrofabric as common

    seg = inspect.getsource(common.create_segment_gdf)
    assert seg.count("nhm_seg_id") >= 1, (
        "the rename that makes GFv2 readable has gone missing"
    )
