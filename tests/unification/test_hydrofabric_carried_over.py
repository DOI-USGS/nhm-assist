"""Functions unique to one side must survive unification."""
import inspect

from tests.unification.fabrics import (
    NHF_HF,
    NHM_HF,
    baseline_function_ast,
    current_function_ast,
)


def test_nhf_only_geometry_fixer_survived():
    import assist.common.hydrofabric as common

    assert current_function_ast(common.evaluate_and_fix_nhru_geometry) == (
        baseline_function_ast(NHF_HF, "evaluate_and_fix_nhru_geometry")
    )


def test_nhm_only_cal_gages_loader_survived():
    """Parsed, not imported: nhm_hydrofabric at this baseline imports
    find_missing_gage_metadata, which Task 7 deletes."""
    import assist.common.hydrofabric as common

    assert current_function_ast(common._load_byhwobs_cal_gages) == (
        baseline_function_ast(NHM_HF, "_load_byhwobs_cal_gages")
    )


def test_geometry_fixer_defaults_to_the_nhru_layer():
    import assist.common.hydrofabric as common

    params = inspect.signature(common.evaluate_and_fix_nhru_geometry).parameters
    assert params["layer"].default == "nhru"
    assert params["fix"].default is True


def test_map_elements_survived_and_is_verbatim_nhf():
    import assist.common.hydrofabric as common

    assert current_function_ast(common.make_hf_map_elements) == (
        baseline_function_ast(NHF_HF, "make_hf_map_elements")
    )


def test_map_elements_dependencies_all_resolve():
    """It calls three functions added in Tasks 4-5 plus one from assist_utilities.
    This is why it lands here and not in Task 3."""
    import assist.common.hydrofabric as common

    for name in ("create_hru_gdf", "create_poi_df", "create_segment_gdf",
                 "read_gages_file"):
        assert callable(getattr(common, name)), f"{name} missing"
    source = inspect.getsource(common)
    assert "from assist.common.assist_utilities import" in source
    assert "assist.nhf.nhm_assist_utilities_v2" not in source
