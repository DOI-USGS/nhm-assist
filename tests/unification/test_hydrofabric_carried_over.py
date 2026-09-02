"""Functions unique to one side must survive unification."""
import ast
import inspect

from tests.unification.fabrics import (
    NHF_HF,
    NHM_HF,
    baseline_function_ast,
    baseline_function_source,
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
    """`make_hf_map_elements` carries deliberate exceptions from nhf's
    baseline: it now unpacks 3 values from `create_hru_gdf` and returns the
    restored `hru_cal_level_txt` (see tests/unification/test_hydrofabric_gdfs.py
    for why), and it now calls the restored `make_HW_cal_level_files` and
    returns the restored `HW_basins_gdf`/`HW_basins` (see
    tests/unification/test_hru_cal_levels.py for why). Splicing those edits
    into nhf's baseline source and comparing ASTs proves nothing else about
    the function drifted from nhf.
    """
    import assist.common.hydrofabric as common

    nhf_source = baseline_function_source(NHF_HF, "make_hf_map_elements")

    # Each (old, new) pair is one deliberate, independently-verified splice.
    # Asserting `old in expected_source` before applying each one (rather
    # than a single aggregate "did anything change" check at the end) means
    # a no-op `.replace()` — e.g. because the baseline text shifted and a
    # splice target silently stopped matching — fails loudly and names the
    # exact target that went missing, instead of being masked by the other
    # splices still succeeding.
    replacements = [
        (
            '        Path to WaterData data, e.g., model_dir / "NWISgages.csv"',
            '        Path to WaterData data, e.g., model_dir / '
            '"metadata/WaterDataGages.csv"',
        ),
        (
            "    hru_gdf, hru_txt = create_hru_gdf(",
            "    hru_gdf, hru_txt, hru_cal_level_txt = create_hru_gdf(",
        ),
        (
            "        #hru_cal_level_txt,",
            "        hru_cal_level_txt,",
        ),
        (
            "    # HW_basins_gdf : geopandas GeoDataFrame\n"
            "    #     NHM headwaters basins geopandas GeoDataFrame used to "
            "display caliration level of HRUs on map.\n"
            "    # HW_basins : geopandas polyline dataset\n"
            "    #     Polyline file that was made using HW_basins_gdf.boundary\n"
            "    \n"
            '    """',
            "    HW_basins_gdf : geopandas GeoDataFrame\n"
            "        NHM headwaters basins geopandas GeoDataFrame used to "
            "display caliration level of HRUs on map.\n"
            "    HW_basins : geopandas polyline dataset\n"
            "        Polyline file that was made using HW_basins_gdf.boundary\n"
            "\n"
            '    """',
        ),
        (
            "#    HW_basins_gdf, HW_basins = make_HW_cal_level_files(hru_gdf)",
            "    HW_basins_gdf, HW_basins = make_HW_cal_level_files(hru_gdf)",
        ),
        (
            "#        HW_basins_gdf,\n"
            "#        HW_basins,\n"
            "    )",
            "        HW_basins_gdf,\n"
            "        HW_basins,\n"
            "    )",
        ),
    ]

    expected_source = nhf_source
    for old, new in replacements:
        assert old in expected_source, (
            "nhf baseline's make_hf_map_elements no longer contains the "
            f"expected splice target {old!r}; this test needs updating"
        )
        expected_source = expected_source.replace(old, new)

    assert expected_source != nhf_source, (
        "nhf baseline's make_hf_map_elements no longer matches the expected "
        "unpack/return lines; this test needs updating"
    )

    expected_node = ast.parse(expected_source).body[0]
    expected_node.name = "_"

    assert current_function_ast(common.make_hf_map_elements) == ast.dump(expected_node)


def test_map_elements_describes_canonical_waterdata_gages_file():
    import assist.common.hydrofabric as common

    assert 'model_dir / "metadata/WaterDataGages.csv"' in inspect.getdoc(
        common.make_hf_map_elements
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
