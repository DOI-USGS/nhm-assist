"""find_missing_gage_info is nhf's."""
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


# Deliberate departures from nhf's baseline, as (old_text, new_text) pairs applied
# to the baseline source before comparing. Restores two resilience behaviours that
# nhm's own find_missing_gage_info had and nhf's does not: the NLDI extract in
# data_dependencies/ is untracked and absent on fresh clones and air-gapped
# deployments, and that directory may be read-only on shared filesystems.
INTENDED_EDITS = [
    (
        '''    if not missing_meta_df.empty:
        """
        First, Check the NLDI json''',
        '''    nldi_geojson_path = npoigages_data_dir / "usgs_nldi_gages.geojson"

    if not missing_meta_df.empty and nldi_geojson_path.exists():
        """
        First, Check the NLDI json''',
    ),
    (
        '''        file_path = npoigages_data_dir / "usgs_nldi_gages.geojson"''',
        '''        file_path = nldi_geojson_path''',
    ),
    (
        '''        nldi_gdf.to_file(
            npoigages_data_dir / "usgs_nldi_gages.gpkg",
            driver="GPKG",
        )''',
        '''        try:
            nldi_gdf.to_file(
                npoigages_data_dir / "usgs_nldi_gages.gpkg",
                driver="GPKG",
            )
        except OSError:
            # data_dependencies/ may be read-only on shared filesystems.
            # The cache is an optimization; carry on with the in-memory frame.
            pass''',
    ),
    (
        '        resource_df.to_csv(resource_file_path, index=False)\n',
        '        resource_file_path.parent.mkdir(parents=True, exist_ok=True)\n'
        '        resource_df.to_csv(resource_file_path, index=False)\n',
    ),
    (
        '''            # f"{len(list(set(still_lacking_info_list)))} of {len(gages_df)} are still lacking gage info.",
        )
''',
        '''            # f"{len(list(set(still_lacking_info_list)))} of {len(gages_df)} are still lacking gage info.",
        )
    elif not missing_meta_df.empty:
        # non-fatal: the NLDI extract is an optional local data dependency that is
        # absent on air-gapped deployments and on fresh clones (data_dependencies/
        # is not tracked). The WaterData lookup below covers these gages.
        print(
            f"NLDI database not found at {nldi_geojson_path}; "
            f"seeking {len(missing_meta_df)} gages in USGS WaterData instead."
        )
''',
    ),
]


def test_canonical_is_nhf_plus_only_the_intended_edits(baselines):
    """Verbatim from nhf, except for the substitutions in INTENDED_EDITS."""
    import assist.common.assist_utilities as common

    _, nhf = baselines
    expected_source = inspect.getsource(nhf.find_missing_gage_info)
    for old_text, new_text in INTENDED_EDITS:
        assert old_text in expected_source, (
            f"nhf's baseline no longer contains {old_text!r}, so this "
            "intended-edit entry is stale and the test needs updating"
        )
        expected_source = expected_source.replace(old_text, new_text)

    tree = ast.parse(expected_source.lstrip())
    tree.body[0].name = "_"
    assert _body_ast(common.find_missing_gage_info) == ast.dump(tree.body[0])


def test_nldi_extract_is_optional(tmp_path):
    """The documented reason for the edits above: a missing NLDI extract must not
    raise, because data_dependencies/ is untracked."""
    import assist.common.assist_utilities as common

    root = tmp_path / "root"
    (root / "data_dependencies").mkdir(parents=True)
    assert not (root / "data_dependencies" / "usgs_nldi_gages.geojson").exists()

    source = inspect.getsource(common.find_missing_gage_info)
    assert "nldi_geojson_path.exists()" in source, (
        "the NLDI read is unguarded again; nhm notebook 1 will die with "
        "DataSourceError on any clone without the untracked extract"
    )


def test_nhm_private_helpers_came_along():
    import assist.common.assist_utilities as common

    assert callable(common._load_nldi_cached)
    assert callable(common._translate_waterdata_columns)
