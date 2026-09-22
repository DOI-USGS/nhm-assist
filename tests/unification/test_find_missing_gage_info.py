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
    (
        # poi_agency and poi_name are string columns, but nhf's baseline builds
        # every column from [np.nan]*n, which pandas types as float64. The first
        # name written into one forces an upcast that pandas 3 refuses outright.
        # See test_string_metadata_columns_do_not_need_a_dtype_upcast below.
        '''    )  # Initialize empty datafame
''',
        '''    )  # Initialize empty datafame
    gages_df = gages_df.astype({"poi_agency": "object", "poi_name": "object"})
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


def test_string_metadata_columns_do_not_need_a_dtype_upcast(tmp_path):
    """poi_name and poi_agency must not start life as float64.

    gages_df initialises every metadata column from ``[np.nan] * n``, which
    pandas types as float64. The first real gage name written into poi_name
    therefore forces a dtype upcast -- which pandas 2.x performs while emitting
    a FutureWarning, and pandas 3.x refuses outright:

        TypeError: Invalid value 'WALLA WALLA RIVER NEAR TOUCHET, WA'
                   for dtype 'float64'

    Reported from a collaborator running notebook 1 against pandas 3; the
    ``pandas<3`` pin in pyproject.toml is the only reason it does not happen
    here. All three fill branches write through the same columns, so pinning
    the dtypes at construction covers every one of them.
    """
    import warnings

    import pandas as pd

    import assist.common.assist_utilities as common

    root = tmp_path / "root"
    (root / "data_dependencies").mkdir(parents=True)

    # Metadata for every required column, so the frame is complete after the
    # resource-file branch and neither the NLDI nor the WaterData lookup runs.
    resource_file = tmp_path / "metadata" / "resource_gages.csv"
    resource_file.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "poi_gage_id": ["14018500"],
            "poi_agency": ["USGS"],
            "poi_name": ["WALLA WALLA RIVER NEAR TOUCHET, WA"],
            "latitude": [46.0508],
            "longitude": [-118.6753],
            "drainage_area": [1655.0],
            "drainage_area_contrib": [1655.0],
        }
    ).to_csv(resource_file, index=False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gages_df = common.find_missing_gage_info(
            root_dir=root,
            dest_dir=tmp_path / "dest",
            gages_list=["14018500"],
            resource_file_path=resource_file,
        )

    upcasts = [w for w in caught if "incompatible dtype" in str(w.message)]
    assert not upcasts, "metadata fill forced a dtype upcast: " + "; ".join(
        str(w.message) for w in upcasts
    )

    assert gages_df.loc[0, "poi_name"] == "WALLA WALLA RIVER NEAR TOUCHET, WA"
    assert gages_df["poi_name"].dtype == object
    assert gages_df["poi_agency"].dtype == object
    # The numeric columns must stay numeric; a blanket object cast would break
    # the arithmetic and plotting these feed downstream.
    assert gages_df["latitude"].dtype == float
    assert gages_df["longitude"].dtype == float
