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


# Deliberate, reviewed divergences from nhf's baseline, applied per spec
# decision 7 (WaterData is the canonical terminology). Each entry is an exact
# (old, new) source substitution. Keeping the comparison this narrow proves
# nothing ELSE in these functions drifted, which a looser check would not.
INTENDED_EDITS = {
    "create_default_gages_file": [
        ("nwis_cache.nc", "waterdata_cache.nc"),
    ],
    # Two nhm behaviours that taking nhf's create_poi_df verbatim dropped, each
    # restored after the corresponding nhm notebook died on it.
    "create_poi_df": [
        # nhm's map_template renders nhm_seg in the POI marker tooltips
        # (create_poi_obs_marker_cluster) -> notebook 2, KeyError: 'nhm_seg'.
        (
            '    poi = poi.merge(pdb["poi_type"].as_dataframe, left_index=True, right_index=True)\n',
            '    poi = poi.merge(pdb["poi_type"].as_dataframe, left_index=True, right_index=True)\n'
            '    seg_param = next(\n'
            '        (name for name in ("nhm_seg", "nhm_seg_id") if name in pdb.parameters),\n'
            '        None,\n'
            '    )\n'
            '    if seg_param is not None:\n'
            '        seg_ids = pdb[seg_param].as_dataframe\n'
            '        if seg_param != "nhm_seg":\n'
            '            seg_ids = seg_ids.rename(columns={seg_param: "nhm_seg"})\n'
            '        poi = poi.merge(seg_ids, left_on="poi_gage_segment", right_index=True)\n',
        ),
        # nhm's create_streamflow_poi_markers reads nhm_calib -> notebook 6,
        # KeyError: 'nhm_calib'.
        # GFv2 fabrics take their calibration gages from the model's own
        # npoigages_cal_list_<domain>.xlsx instead of the v1.1 byHWobs list, so
        # create_poi_df needs fabric_version.
        (
            "    seg_gdf,\n):",
            '    seg_gdf,\n    fabric_version="1.1",\n):',
        ),
        (
            '    poi_df = pd.DataFrame(poi)  # Creates a Pandas DataFrame\n',
            '    poi_df = pd.DataFrame(poi)  # Creates a Pandas DataFrame\n'
            '    if str(fabric_version).startswith("2"):\n'
            '        cal_gage_ids = _load_ohm_cal_gages(Path(model_dir) / "metadata")\n'
            '    else:\n'
            '        cal_gage_ids = set(_load_byhwobs_cal_gages(root_dir)["poi_gage_id"])\n'
            '    poi_df["nhm_calib"] = "N"\n'
            '    poi_df.loc[\n'
            '        poi_df["poi_gage_id"].astype(str).str.strip().isin(cal_gage_ids), "nhm_calib"\n'
            '    ] = "Y"\n',
        ),
    ],
}


@pytest.mark.parametrize("name", FROM_NHF)
def test_copy_is_ast_identical_to_nhf(name, nhf_baseline):
    """Verbatim from nhf, except for the substitutions in INTENDED_EDITS."""
    import assist.common.hydrofabric as common

    expected_source = inspect.getsource(getattr(nhf_baseline, name))
    for old_text, new_text in INTENDED_EDITS.get(name, []):
        assert old_text in expected_source, (
            f"{name}: nhf's baseline no longer contains {old_text!r}, so this "
            "intended-edit entry is stale and the test needs updating"
        )
        expected_source = expected_source.replace(old_text, new_text)

    assert ast.dump(ast.parse(expected_source)) == _ast_of(getattr(common, name))


@pytest.mark.parametrize("name", FROM_NHF)
def test_signature_matches_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    current = inspect.signature(getattr(common, name))
    baseline = inspect.signature(getattr(nhf_baseline, name))
    if name == "create_poi_df":
        # Deliberate addition, see INTENDED_EDITS: GFv2 calibration gages.
        assert list(current.parameters) == [*baseline.parameters, "fabric_version"]
        assert current.parameters["fabric_version"].default == "1.1"
        current = current.replace(
            parameters=[
                p for p in current.parameters.values() if p.name != "fabric_version"
            ]
        )
    assert current == baseline


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
