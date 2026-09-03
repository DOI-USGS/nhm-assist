"""Concern 4: one `map_template` drives both fabrics.

nhf's `map_template_v2` was the dominant side and moved to
`assist.common.map_template` via a bare `git mv` committed alone, so plain
`git blame` still credits the original authors (verified: GS\\ahaj on ~2.7k
lines, 48 commits reachable via --follow). The survey that justified taking
nhf wholesale:

  21 shared functions: 4 identical, 3 differing only by nwis_->waterdata_
  naming (spec decision 7), 4 differing only by HW_basins parameters, 11
  differing in body. **Zero** nhm-only functions, and 8 nhf-only ones. So this
  was an adaptation job, not a merge, and the plan's stop condition (>2
  irreconcilable functions) never triggered.

The one thing nhf had dropped is restored here: headwater basins are GFv1.1-only
(`HW_basins`, `HW_basins_gdf`, and the `hw_id` HRU overlay). nhf had commented
all of it out; the unified module takes them as `None`-defaulted keyword
parameters and guards every render, so nhm keeps its layers and GFv2 callers
that never pass them are unaffected.

Deliberately NOT preserved from nhm, because nhf's versions supersede them:
the tooltip identifiers (nhm_seg/nhm_id -> poi_gage_segment/hru_id) and the
nhm_calib outline ring that distinguished calibration gages.

Marker styling went the other way. nhf had replaced nhm's CircleMarkers with
triangle icons via make_polygon_icon; circles were restored on request. The one
exception is create_FMI_poi_markers, where the polygon's side count is not
styling at all -- it *encodes* the Flow Management Index
(`color, num_sides = fmi_style.get(fmi_val, ("Gray", 4))`), so turning those
into circles would erase the data.
"""
import ast
import inspect
import pathlib

import pytest

from tests.unification.harness import REPO_ROOT

MAP_BUILDERS_WITH_HW = {
    "make_hf_map": ["HW_basins_gdf", "HW_basins"],
    "make_streamflow_map": ["HW_basins_gdf", "HW_basins"],
    "make_par_map": ["HW_basins"],
    "make_var_map": ["HW_basins"],
}


@pytest.fixture(scope="module")
def common():
    import assist.common.map_template as module

    return module


@pytest.mark.parametrize(
    "shim_path",
    ["assist.nhm.map_template", "assist.nhf.map_template_v2"],
)
def test_both_fabric_paths_resolve_to_common(shim_path, common):
    import importlib

    shim = importlib.import_module(shim_path)
    for name in ("make_hf_map", "make_par_map", "make_var_map", "make_streamflow_map"):
        assert getattr(shim, name) is getattr(common, name), name


@pytest.mark.parametrize("name,params", sorted(MAP_BUILDERS_WITH_HW.items()))
def test_hw_basins_params_exist_and_default_to_none(name, params, common):
    """nhm's notebooks pass these; without them notebook 2 dies with TypeError.
    They must default to None so GFv2 callers need not pass them."""
    signature = inspect.signature(getattr(common, name))
    for param in params:
        assert param in signature.parameters, f"{name} lost {param}"
        assert signature.parameters[param].default is None, (
            f"{name}.{param} must default to None for GFv2 callers"
        )


@pytest.mark.parametrize("name,params", sorted(MAP_BUILDERS_WITH_HW.items()))
def test_every_hw_render_is_guarded(name, params, common):
    """Accepting the parameters is not enough -- handing None to folium raises.
    Every *read* of the parameter in the body must sit inside an
    `if <param> is not None:` block. Checked by AST ancestry, not by string
    matching, so it cannot pass vacuously."""
    tree = ast.parse(inspect.getsource(getattr(common, name)).lstrip())
    func = tree.body[0]

    # map every node to its parent so a read can be walked back to its guards
    parents = {}
    for node in ast.walk(func):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def guards_covering(node, param):
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.If) and f"{param} is not None" in ast.unparse(
                node.test
            ):
                return True
        return False

    for param in params:
        reads = [
            n
            for n in ast.walk(func)
            if isinstance(n, ast.Name)
            and n.id == param
            and isinstance(n.ctx, ast.Load)
        ]
        assert reads, (
            f"{name} never reads {param}; the GFv1.1 layer was accepted as a "
            f"parameter but silently never rendered"
        )
        unguarded = [n.lineno for n in reads if not guards_covering(n, param)]
        assert not unguarded, (
            f"{name} reads {param} unguarded at relative line(s) {unguarded}; a "
            f"GFv2 caller passing None would raise inside folium"
        )


def test_hw_basin_style_is_live(common):
    """The style helper every HW render needs; nhf had it commented out."""
    assert callable(common.hw_basin_style)
    assert common.hw_basin_style(None)["color"] == "brown"


def test_hw_id_overlay_is_guarded_on_the_column(common):
    """hw_id comes from the GFv1.1 cal-levels merge in create_hru_gdf. GFv2
    fabrics have no headwaters, so the overlay must be column-conditional."""
    source = inspect.getsource(common.make_streamflow_map)
    assert '"hw_id" in hru_gdf.columns' in source
    assert "hw_id_str" in source


def test_the_eight_nhf_only_functions_survived(common):
    """Taking nhf's side is only worth it if its extra layers came along."""
    for name in (
        "create_FMI_poi_markers",
        "create_geology_map",
        "create_non_ref_gages_markers",
        "create_ref_gages_markers",
        "make_geo_legend",
        "make_geo_map",
        "make_gf_map",
        "make_polygon_icon",
    ):
        assert callable(getattr(common, name)), name


def test_no_nwis_terminology_in_the_public_signatures(common):
    """Spec decision 7: WaterData is canonical."""
    offenders = []
    for name in dir(common):
        if name.startswith("_"):
            continue
        obj = getattr(common, name)
        if not inspect.isfunction(obj):
            continue
        for param in inspect.signature(obj).parameters:
            if "nwis" in param.lower():
                offenders.append(f"{name}({param})")
    assert not offenders, f"retired NWIS naming in signatures: {offenders}"


def test_the_nhm_duplicate_is_a_shim_not_an_implementation():
    """2,467 lines collapsed to a re-export."""
    path = REPO_ROOT / "src/assist/nhm/map_template.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert not defs, f"nhm/map_template.py still defines {defs}"
    assert len(path.read_text(encoding="utf-8").splitlines()) < 120


CIRCLE_MARKER_CLUSTERS = [
    "create_poi_obs_marker_cluster",
    "create_non_poi_obs_marker_cluster",
]


@pytest.mark.parametrize("name", CIRCLE_MARKER_CLUSTERS)
def test_poi_markers_are_circles_not_polygons(name, common):
    """Requested revert of nhf's triangle restyling."""
    source = inspect.getsource(getattr(common, name))
    live = [
        line
        for line in source.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    body = "\n".join(live)
    assert "folium.CircleMarker(" in body, f"{name} no longer draws circles"
    assert "make_polygon_icon(" not in body, (
        f"{name} draws polygon icons again; circles were requested"
    )


def test_fmi_markers_keep_their_polygon_encoding(common):
    """The FMI layer's side count carries the index value, so it must stay a
    polygon even though the POI clusters went back to circles."""
    source = inspect.getsource(common.create_FMI_poi_markers)
    live = "\n".join(
        line for line in source.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    assert "make_polygon_icon(num_sides=num_sides" in live, (
        "FMI markers lost the data-driven side count"
    )
    assert "fmi_style.get(" in live


# nhm's map_template implementation, before the concern-4 shim replaced it.
NHM_MARKER_BASELINE = "d977633"
NHM_MAP_TEMPLATE_PATH = "src/assist/nhm/map_template.py"

# POI gages are black, potential (non-POI) gages are gray, both radius 3.
# nhf had dropped the outline `color` on the plain clusters and bumped the obs
# clusters to radius 4; restored on request.
MARKER_SCHEMA_FUNCTIONS = [
    "create_poi_marker_cluster",
    "create_non_poi_marker_cluster",
    "create_poi_obs_marker_cluster",
    "create_non_poi_obs_marker_cluster",
]


def _circle_marker_schema(source: str, name: str):
    """(color, fill_color, radius) of every CircleMarker in one function."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            found = []
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "CircleMarker"
                ):
                    kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
                    found.append(
                        (kw.get("color"), kw.get("fill_color"), kw.get("radius"))
                    )
            return found
    raise AssertionError(f"{name} not found")


@pytest.mark.parametrize("name", MARKER_SCHEMA_FUNCTIONS)
def test_marker_schema_matches_nhm_exactly(name):
    """Black POI / gray potential-gage circles at radius 3, compared against
    nhm's own pre-unification source rather than hardcoded values, so the
    assertion cannot quietly drift away from what the maps used to look like."""
    import subprocess

    import assist.common.map_template as common

    baseline = subprocess.run(
        ["git", "show", f"{NHM_MARKER_BASELINE}:{NHM_MAP_TEMPLATE_PATH}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout
    assert "def create_poi_marker_cluster" in baseline, (
        f"{NHM_MARKER_BASELINE} no longer holds nhm's map_template "
        "implementation; this test needs a new baseline revision"
    )

    expected = _circle_marker_schema(baseline, name)
    actual = _circle_marker_schema(
        pathlib.Path(inspect.getfile(common)).read_text(encoding="utf-8"), name
    )
    assert actual == expected, (
        f"{name} marker schema drifted from nhm: expected "
        f"(color, fill, radius) {expected}, got {actual}"
    )
