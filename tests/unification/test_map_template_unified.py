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

Marker styling is nhf's. nhf had replaced nhm's CircleMarkers with triangle
icons via make_polygon_icon; those were briefly reverted to circles, then
restored to nhf's triangles once that became the intended default. The
triangles carry a halo -- make_polygon_icon draws the polygon with
`stroke="black" stroke-width="1"`, which is what makes the white non-POI
triangles legible against the map.

create_FMI_poi_markers was never in question: its polygon side count is not
styling at all, it *encodes* the Flow Management Index
(`color, num_sides = fmi_style.get(fmi_val, ("Gray", 4))`).
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
    "retired_path",
    ["assist.nhm.map_template", "assist.nhf.map_template_v2"],
)
def test_the_retired_fabric_paths_are_gone(retired_path):
    """map_template is reachable only at assist.common.map_template."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(retired_path)


def test_the_unified_module_is_importable(common):
    for name in ("make_hf_map", "make_par_map", "make_var_map", "make_streamflow_map"):
        assert callable(getattr(common, name)), name


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


def test_the_nhm_duplicate_is_gone():
    """2,467 lines collapsed to a re-export shim, and the shim is gone too."""
    for retired in ("src/assist/nhm/map_template.py",
                    "src/assist/nhf/map_template_v2.py"):
        assert not (REPO_ROOT / retired).exists(), f"{retired} is back"


# nhf's map_template as it landed in common/ via the bare `git mv`, before any
# adaptation -- the reference for "the nhf way of doing things".
NHF_MARKER_BASELINE = "d977633"
COMMON_MAP_TEMPLATE_PATH = "src/assist/common/map_template.py"

TRIANGLE_MARKER_CLUSTERS = [
    "create_poi_obs_marker_cluster",
    "create_non_poi_obs_marker_cluster",
]

# every marker function that must match nhf byte for byte
NHF_MARKER_FUNCTIONS = [
    "create_poi_marker_cluster",
    "create_non_poi_marker_cluster",
    "create_poi_obs_marker_cluster",
    "create_non_poi_obs_marker_cluster",
    "create_streamflow_poi_markers",
    "make_polygon_icon",
]


def _nhf_baseline_source() -> str:
    import subprocess

    source = subprocess.run(
        ["git", "show", f"{NHF_MARKER_BASELINE}:{COMMON_MAP_TEMPLATE_PATH}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout
    assert "def make_polygon_icon" in source, (
        f"{NHF_MARKER_BASELINE} no longer holds nhf's map_template; this test "
        "needs a new baseline revision"
    )
    return source


def _function_source(source: str, name: str) -> str:
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} not found")


@pytest.mark.parametrize("name", NHF_MARKER_FUNCTIONS)
def test_marker_functions_are_verbatim_nhf(name, common):
    """Compared against nhf's own source rather than hardcoded values, so the
    assertion cannot drift away from what the maps actually looked like."""
    baseline = _nhf_baseline_source()
    actual = pathlib.Path(inspect.getfile(common)).read_text(encoding="utf-8")
    assert _function_source(actual, name) == _function_source(baseline, name), (
        f"{name} has drifted from nhf's version"
    )


@pytest.mark.parametrize("name", TRIANGLE_MARKER_CLUSTERS)
def test_poi_markers_are_triangles_not_circles(name, common):
    """The reverted decision: nhf's triangle icons are the default."""
    live = "\n".join(
        line
        for line in inspect.getsource(getattr(common, name)).splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    assert "make_polygon_icon(" in live, f"{name} no longer draws triangles"
    assert "folium.CircleMarker(" not in live, (
        f"{name} draws circles again; nhf's triangles are the default"
    )
    assert "num_sides=3" in live


def test_triangles_keep_their_halo(common):
    """The halo is the SVG stroke around the fill; without it the white
    non-POI triangles disappear against a light basemap."""
    source = inspect.getsource(common.make_polygon_icon)
    assert 'stroke="black"' in source
    assert 'stroke-width="1"' in source


def test_poi_and_non_poi_triangles_are_distinguishable(common):
    """Black fill for gages in the parameter file, white for potential ones."""
    fills = {}
    for name in TRIANGLE_MARKER_CLUSTERS:
        live = "\n".join(
            line
            for line in inspect.getsource(getattr(common, name)).splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        for node in ast.walk(ast.parse(live)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "make_polygon_icon"
            ):
                kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
                fills[name] = kw.get("color")
    assert fills == {
        "create_poi_obs_marker_cluster": "'black'",
        "create_non_poi_obs_marker_cluster": "'white'",
    }, fills


def test_fmi_markers_keep_their_polygon_encoding(common):
    """The FMI layer's side count carries the index value."""
    live = "\n".join(
        line
        for line in inspect.getsource(common.create_FMI_poi_markers).splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    assert "make_polygon_icon(num_sides=num_sides" in live, (
        "FMI markers lost the data-driven side count"
    )
    assert "fmi_style.get(" in live
