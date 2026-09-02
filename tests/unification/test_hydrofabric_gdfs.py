"""The fabric-tolerance in these two functions is the point of taking nhf's side.

`create_hru_gdf` carries one deliberate, documented exception: the HRU
calibration-level block (reading `nhm_v1_1_HRU_cal_levels.csv` and returning
`hru_cal_level_txt`) is nhm-only functionality that the unification initially
dropped by taking nhf's version verbatim (nhf had it commented out). That was
a real feature loss, not an intentional fabric-tolerance decision, so it was
restored -- see `test_hru_gdf_is_nhf_verbatim_except_the_restored_calibration_block`
below. `create_segment_gdf` has no such exception and stays fully verbatim.
"""
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


@pytest.mark.parametrize("name", ["create_segment_gdf"])
def test_copy_is_ast_identical_to_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert _ast_of(getattr(common, name)) == _ast_of(getattr(nhf_baseline, name))


def _restore_calibration_block(nhf_source: str) -> str:
    """Reconstruct nhf's `create_hru_gdf` source with the nhm calibration-
    level block spliced back in live, exactly as this fix restores it in
    `assist.common.hydrofabric`. Used to prove everything *else* in the
    function is still verbatim nhf.
    """
    replacements = [
        (
            '    # hru_cal_levels_df = pd.read_csv(f"{root_dir}/data_dependencies/NHM_v1_1/nhm_v1_1_HRU_cal_levels.csv").fillna(0)\n'
            '    # hru_cal_levels_df["hw_id"] = hru_cal_levels_df.hw_id.astype("int32")\n'
            "\n"
            '    # hru_gdf = hru_gdf.merge(hru_cal_levels_df, on="nhm_id")\n'
            '    # hru_gdf["hw_id"] = hru_gdf.hw_id.astype("int32")\n',
            '    hru_cal_levels_df = pd.read_csv(f"{root_dir}/data_dependencies/NHM_v1_1/nhm_v1_1_HRU_cal_levels.csv").fillna(0)\n'
            '    hru_cal_levels_df["hw_id"] = hru_cal_levels_df.hw_id.astype("int32")\n'
            "\n"
            '    hru_gdf = hru_gdf.merge(hru_cal_levels_df, on="nhm_id")\n'
            '    hru_gdf["hw_id"] = hru_gdf.hw_id.astype("int32")\n',
        ),
        (
            "    # hru_cal_level_txt = f'{hru_gdf[hru_gdf[\"level\"] > 1][\"level\"].count()} "
            'HRUs are within HWs, and {hru_gdf[hru_gdf["level"] > 2]["level"].count()} are '
            "within HW calibrated with streamflow observations.'\n"
            "\n"
            "    return hru_gdf, hru_text",
            "    hru_cal_level_txt = f'{hru_gdf[hru_gdf[\"level\"] > 1][\"level\"].count()} "
            'HRUs are within HWs, and {hru_gdf[hru_gdf["level"] > 2]["level"].count()} are '
            "within HW calibrated with streamflow observations.'\n"
            "\n"
            "    return hru_gdf, hru_text, hru_cal_level_txt",
        ),
    ]
    result = nhf_source
    for old, new in replacements:
        assert old in result, (
            "nhf baseline's create_hru_gdf no longer has the expected "
            "commented-out calibration block; this test needs updating"
        )
        result = result.replace(old, new)
    return result


def test_hru_gdf_is_nhf_verbatim_except_the_restored_calibration_block(nhf_baseline):
    """The one documented exception to "took nhf's side wholesale": the nhm
    HRU calibration-level block was restored (see module docstring). Splicing
    that same block into nhf's baseline source and comparing ASTs proves
    nothing else about the function drifted from nhf.
    """
    import assist.common.hydrofabric as common

    nhf_source = inspect.getsource(nhf_baseline.create_hru_gdf)
    expected_source = _restore_calibration_block(nhf_source)

    expected_node = ast.parse(expected_source).body[0]
    expected_node.name = "_"
    actual_node = ast.parse(inspect.getsource(common.create_hru_gdf)).body[0]
    actual_node.name = "_"

    assert ast.dump(actual_node) == ast.dump(expected_node)


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
