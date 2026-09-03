"""Concern 5: one `display_controls` drives both fabrics.

This is the one module where the *nhm* side won rather than nhf. Both held the
same nine functions, but nhm's had been hardened after the fork (state guards,
output-dir creation, POI None-checks, batch-safe artifact reporting), so taking
nhf's side would have been a straight regression. The single thing nhf's copy
did differently -- omitting the GFv1.1-only `HW_basins` / `HW_basins_gdf` -- is
preserved by asking the injected map backend which keywords it accepts.

The widget callbacks here never fire during a headless notebook run, so these
tests exercise them directly; a notebook passing proves nothing about them.
"""
import ast
import inspect
import pathlib

import pytest

from tests.unification.harness import REPO_ROOT


@pytest.fixture
def dc():
    import assist.common.display_controls as module

    saved = {k: getattr(module, k) for k in vars(module) if not k.startswith("__")}
    yield module
    for k, v in saved.items():
        setattr(module, k, v)


def test_nhf_module_path_is_an_alias_not_a_reexport(dc):
    """`display_controls` holds mutable state that notebooks assign
    (`dc.hru_gdf = ...`). A `from ... import *` shim would copy those names and
    assignments would never reach the implementation, so the shim rebinds
    `sys.modules` instead."""
    import assist.nhf.display_controls_v2 as shim

    assert shim is dc

    shim.subdomain = "AliasProbe"
    assert dc.subdomain == "AliasProbe"


def test_accepted_by_matches_each_fabrics_map_backend(dc):
    import assist.nhf.map_template_v2 as nhf
    import assist.nhm.map_template as nhm

    assert dc._accepted_by(nhm.make_var_map, "HW_basins") == ["HW_basins"]
    assert dc._accepted_by(nhf.make_var_map, "HW_basins") == []

    assert set(
        dc._accepted_by(nhm.make_streamflow_map, "HW_basins", "HW_basins_gdf")
    ) == {"HW_basins", "HW_basins_gdf"}
    assert (
        dc._accepted_by(nhf.make_streamflow_map, "HW_basins", "HW_basins_gdf") == []
    )


def test_accepted_by_passes_everything_to_a_kwargs_backend(dc):
    def anything(**kwargs):
        return None

    assert dc._accepted_by(anything, "HW_basins") == ["HW_basins"]
    assert dc._accepted_by(None, "HW_basins") == []


def _prime(dc, backend, **overrides):
    """Give the module the state generate_map needs, plus a stub backend."""
    class _Val:
        def __init__(self, value):
            self.value = value

    dc.make_var_map = backend
    for name in (
        "root_dir", "out_dir", "plot_start_date", "plot_end_date", "water_years",
        "hru_gdf", "poi_df", "seg_gdf", "html_maps_dir", "year_list",
        "Folium_maps_dir", "subdomain", "HW_basins",
    ):
        setattr(dc, name, overrides.get(name, f"<{name}>"))
    dc.v = _Val("recharge")
    dc.yr = _Val(1980)
    dc._ensure_output_dirs = lambda: None
    dc._get_valid_poi = lambda: "12345678"
    dc._report_external_artifact = lambda kind, artifact: None


def test_generate_map_omits_hw_basins_for_a_gfv2_backend(dc):
    """nhf's make_var_map has no HW_basins parameter; passing it would raise
    TypeError, which is what a plain shim to nhm's version would have done."""
    seen = {}

    def gfv2_backend(
        *, root_dir, out_dir, output_var_sel, plot_start_date, plot_end_date,
        water_years, hru_gdf, poi_df, poi_gage_id_sel, seg_gdf, html_maps_dir,
        year_list, sel_year, Folium_maps_dir, subdomain,
    ):
        seen.update(subdomain=subdomain)
        return "map.html"

    _prime(dc, gfv2_backend)
    dc.generate_map()  # must not raise
    assert seen["subdomain"] == "<subdomain>"


def test_generate_map_passes_hw_basins_to_a_gfv1_1_backend(dc):
    seen = {}

    def gfv1_1_backend(
        *, root_dir, out_dir, output_var_sel, plot_start_date, plot_end_date,
        water_years, hru_gdf, poi_df, poi_gage_id_sel, seg_gdf, html_maps_dir,
        year_list, sel_year, Folium_maps_dir, HW_basins, subdomain,
    ):
        seen.update(HW_basins=HW_basins)
        return "map.html"

    _prime(dc, gfv1_1_backend)
    dc.generate_map()
    assert seen["HW_basins"] == "<HW_basins>"


def test_generate_map_still_bails_when_required_state_is_missing(dc):
    """The hardening must survive the adapter: a GFv1.1 backend with no
    HW_basins set must warn and return, not call the backend."""
    called = []

    def gfv1_1_backend(*, HW_basins, **kwargs):
        called.append(True)
        return "map.html"

    _prime(dc, gfv1_1_backend)
    dc.HW_basins = None
    dc.generate_map()
    assert not called, "generate_map called the backend without HW_basins set"


@pytest.mark.parametrize("workflow", ["nhm", "nhf"])
def test_templates_set_every_literally_required_state(workflow):
    """Each side must assign every `_require_state` name its callbacks use, or
    the callback silently warns and returns."""
    import assist.common.display_controls as module

    tree = ast.parse(inspect.getsource(module))
    required = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_require_state"
        ):
            required.update(
                a.value for a in node.args if isinstance(a, ast.Constant)
            )
    assert required, "no _require_state names found; this test has gone stale"

    assigned = set()
    for name in (
        "5_hru_output_visualization_new",
        "6_streamflow_output_visualization_new",
    ):
        path = REPO_ROOT / f"src/workflow_templates/{workflow}/{name}.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "dc"
                    ):
                        assigned.add(target.attr)

    assert not required - assigned, (
        f"{workflow} templates never set: {sorted(required - assigned)}"
    )


def test_nhf_copy_is_gone():
    """The 213-line duplicate is replaced by the alias shim."""
    path = REPO_ROOT / "src/assist/nhf/display_controls_v2.py"
    source = path.read_text(encoding="utf-8")
    assert "sys.modules[__name__] = _impl" in source
    functions = [
        n.name
        for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef)
    ]
    assert not functions, f"shim still defines {functions}"
