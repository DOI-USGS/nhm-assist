"""Assert the functions this task copies really were copied unchanged.

Compares the AST of each function in assist.common.assist_utilities against the
same function in the pre-unification nhm module, read out of git. This is the
guard against a transcription slip during a "verbatim" copy.
"""
import ast
import copy
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHM_PATH = "src/assist/nhm/nhm_assist_utilities.py"

COPIED_FROM_NHM = [
    "make_plots_par_vals",
    "create_append_gages_to_param_file",
    "make_myparam_addl_gages_param_file",
]


@pytest.fixture(scope="module")
def nhm_baseline():
    return load_module_from_git(BASELINE_REV, NHM_PATH, "baseline_nhm_for_copies")


def _strip_docstring(fn_node: ast.FunctionDef) -> ast.FunctionDef:
    """Drop a leading bare-string statement (the docstring), if present.

    Final review Fix 5 (2026-08-30) added short documentation notes to
    create_append_gages_to_param_file and make_myparam_addl_gages_param_file
    recording that they require nhm-shaped input. That is a deliberate,
    reviewed divergence from the baseline body, not a transcription slip, so
    it is excluded here rather than weakening the comparison for everything
    else in the function.
    """
    body = fn_node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        fn_node = copy.deepcopy(fn_node)
        fn_node.body = fn_node.body[1:]
    return fn_node


def _ast_of(fn):
    module = ast.parse(inspect.getsource(fn))
    fn_node = module.body[0]
    assert isinstance(fn_node, ast.FunctionDef)
    return ast.dump(_strip_docstring(fn_node))


def _ast_of_source(source):
    """Same treatment as `_ast_of`, for source text rather than a function."""
    fn_node = ast.parse(source.lstrip()).body[0]
    assert isinstance(fn_node, ast.FunctionDef)
    return ast.dump(_strip_docstring(fn_node))


# Deliberate departures from the nhm baseline, as (old, new) text applied to the
# baseline source before comparing.
INTENDED_EDITS = {
    # A gage with no latitude/longitude becomes an empty point, and the
    # sjoin_nearest that follows raises a bare GEOSException naming nothing.
    # Unplaceable gages are dropped first -- they cannot be matched to a segment
    # by distance anyway. The v1.1 byHWobs Maine subdomain ships 26 such gages
    # of 136, New England 6 of 407.
    "create_append_gages_to_param_file": [
        (
            "    gages_gdf = gpd.GeoDataFrame(\n",
            '    locatable = gages_df[["latitude", "longitude"]].notna().all(axis=1)\n'
            "    if (~locatable).any():\n"
            "        unplaceable = gages_df.loc[~locatable]\n"
            "        ids = (\n"
            '            unplaceable["poi_gage_id"].tolist()\n'
            '            if "poi_gage_id" in unplaceable.columns\n'
            "            else [str(i) for i in unplaceable.index]\n"
            "        )\n"
            "        print(\n"
            '            f"Skipping {len(ids)} gage(s) without latitude/longitude when matching "\n'
            '            f"gages to segments: {\', \'.join(map(str, ids))}"\n'
            "        )\n"
            "        gages_df = gages_df.loc[locatable]\n"
            "\n"
            "    gages_gdf = gpd.GeoDataFrame(\n",
        ),
    ],
    # pyPRMS's add_poi sets `npoigages` and `nobs` together and looks both up
    # unconditionally. The GFv2-derived pyPRMS subsetter declares no `nobs`, so
    # every v1.2 and v2 subdomain raised `ValueError: Dimension, nobs, does not
    # exist.` here. Seeded from npoigages, matching Bandit-written v1.1 files.
    # Covered by tests/unification/test_add_pois_dimensions.py.
    "make_myparam_addl_gages_param_file": [
        (
            "    pdb.add_poi(addl_gages)\n",
            '    if not pdb.dimensions.exists("nobs"):\n'
            '        pdb.dimensions.add("nobs", size=pdb.dimensions.get("npoigages").size)\n'
            "\n"
            "    pdb.add_poi(addl_gages)\n",
        ),
    ],
}


@pytest.mark.parametrize("name", COPIED_FROM_NHM)
def test_copy_is_ast_identical_to_the_nhm_baseline(name, nhm_baseline):
    """Verbatim from the nhm baseline, except for INTENDED_EDITS above."""
    import assist.common.assist_utilities as common

    expected_source = inspect.getsource(getattr(nhm_baseline, name))
    for old_text, new_text in INTENDED_EDITS.get(name, []):
        assert old_text in expected_source, (
            f"{name}: the nhm baseline no longer contains {old_text[:50]!r}, so "
            "this intended-edit entry is stale and the test needs updating"
        )
        expected_source = expected_source.replace(old_text, new_text, 1)

    assert _ast_of(getattr(common, name)) == _ast_of_source(expected_source), (
        f"{name} in common/ has drifted from the nhm baseline beyond the "
        "intended edit"
    )


@pytest.mark.parametrize("name", COPIED_FROM_NHM)
def test_copy_keeps_the_baseline_signature(name, nhm_baseline):
    import assist.common.assist_utilities as common

    assert inspect.signature(getattr(common, name)) == inspect.signature(
        getattr(nhm_baseline, name)
    )


def test_pdb_get_nhm_seg_is_not_rewritten():
    """`pdb.get("nhm_seg")` is a pyPRMS parameter name, not a DataFrame column."""
    import assist.common.assist_utilities as common

    source = inspect.getsource(common.make_myparam_addl_gages_param_file)
    assert 'pdb.get("nhm_seg")' in source
