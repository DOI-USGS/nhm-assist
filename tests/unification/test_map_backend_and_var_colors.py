"""Regressions behind "the maps aren't outputting" in notebook 5.

Three separate defects, all on the widget-callback path. That path is why an
`nbconvert` run reported nb5 PASS while every map was broken: the work happens
in `on_generate_clicked`, and in batch mode nothing clicks the button, so the
notebook exits 0 without ever calling it.

1. `display_controls.make_var_map` was a module-level `None` for the consuming
   notebook to inject. Only the deleted nhf `display_controls_v2` ever assigned
   it, so on the nhm side `generate_map` called `None(...)` ->
   `TypeError: 'NoneType' object is not callable`.
2. `oopla` indexed the fixed 17-key `var_colors_dict`/`leg_only_dict` with
   variables discovered from the model's own output files, so a model writing
   any other qualifying variable raised `KeyError` -- Walla Walla writes
   `pkwater_equiv`.
3. `create_sum_var_annual_gdf` dropped a hardcoded `model_idx`, but
   `create_hru_gdf` keeps whichever of `model_idx`/`model_hru_idx`/
   `model_hru_`/`model_id` the GIS file uses, so it raised
   `KeyError: "['model_idx'] not found in axis"`.

Test 1 deliberately asserts on the *shipped module* rather than injecting a
backend. `test_display_controls_unified.py` sets `dc.make_var_map = backend`
before exercising the callbacks, which is exactly what masked defect 1: the
suite supplied the thing production left as None.
"""
from __future__ import annotations

import ast
import inspect

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon


def test_map_backend_is_bound_without_injection():
    """The shipped module must carry callable map builders, not None."""
    import assist.common.display_controls as dc

    for name in ("make_var_map", "make_streamflow_map"):
        backend = getattr(dc, name)
        assert backend is not None, (
            f"display_controls.{name} is None again. Nothing in src/ assigns it, "
            "so the notebook button raises TypeError: 'NoneType' object is not "
            "callable the moment it is clicked."
        )
        assert callable(backend), f"display_controls.{name} is not callable"


def test_generate_map_does_not_reintroduce_an_injection_placeholder():
    """Guard the import, so a future refactor cannot silently go back to None."""
    import assist.common.display_controls as dc

    source = inspect.getsource(dc)
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in {"make_var_map", "make_streamflow_map"}
                    and isinstance(node.value, ast.Constant)
                    and node.value.value is None
                ):
                    pytest.fail(
                        f"{target.id} is assigned None at module scope again; "
                        "import it from assist.common.map_template instead"
                    )


@pytest.mark.parametrize("var", ["pkwater_equiv", "some_future_prms_variable"])
def test_unlisted_output_variables_have_a_color_and_legend_fallback(var):
    """`output_var_list` is discovered from model output; the dicts are fixed."""
    from assist.common.output_plots import leg_only_dict, var_colors_dict

    assert var_colors_dict.get(var, "grey"), "color fallback missing"
    assert leg_only_dict.get(var, "legendonly"), "legend fallback missing"


def test_oopla_uses_get_not_subscript_for_the_color_dicts():
    """A bare subscript here is what killed the whole flux plot."""
    from assist.common.output_plots import oopla

    source = inspect.getsource(oopla)
    assert "var_colors_dict[var]" not in source, (
        "oopla subscripts var_colors_dict again; any model output variable "
        "outside the fixed 17-key dict raises KeyError"
    )
    assert "leg_only_dict[var]" not in source, (
        "oopla subscripts leg_only_dict again"
    )
    assert "var_colors_dict.get(" in source and "leg_only_dict.get(" in source


HRU_INDEX_SPELLINGS = ["model_idx", "model_hru_idx", "model_hru_", "model_id"]


@pytest.mark.parametrize("spelling", HRU_INDEX_SPELLINGS)
def test_annual_gdf_drop_tolerates_every_hru_index_spelling(spelling):
    """create_hru_gdf keeps whichever spelling the GIS file uses."""
    from assist.common.output_visualization import create_sum_var_annual_gdf

    source = inspect.getsource(create_sum_var_annual_gdf)
    assert 'errors="ignore"' in source or "errors='ignore'" in source, (
        "the bookkeeping-column drop is strict again; a GIS file using "
        f"{spelling!r} instead of 'model_idx' will raise KeyError and take out "
        "the notebook 5 map"
    )


def test_drop_removes_the_hru_index_whichever_spelling_is_present():
    """The drop is cosmetic, so it should strip any spelling that is there."""
    from assist.common.output_visualization import create_sum_var_annual_gdf

    source = inspect.getsource(create_sum_var_annual_gdf)
    for spelling in HRU_INDEX_SPELLINGS:
        assert spelling in source, (
            f"{spelling!r} is not in the drop list; it would survive into the "
            "map popup as a bookkeeping column"
        )


# --- 4. the browser never opened on macOS -------------------------------------
#
# make_webbrowser_map passed `f"{map_file}"` -- a bare filesystem path -- to
# webbrowser.open. WSL was the only branch that built a URL. On macOS
# webbrowser hands the string to AppleScript `open location`, which requires a
# URL: given a POSIX path it opens nothing, exits 0, and MacOSXOSAScript.open
# returns True. So notebooks 2 and 3 saved their html, reported success, and no
# browser ever appeared.


def _call_make_webbrowser_map(monkeypatch, path, *, open_returns=True):
    """Call make_webbrowser_map with webbrowser.open captured, not invoked."""
    import webbrowser

    from assist.common import map_template

    seen = {}

    def fake_open(url, new=0, autoraise=True):
        seen["url"] = url
        seen["new"] = new
        return open_returns

    monkeypatch.setattr(webbrowser, "open", fake_open)
    monkeypatch.delenv("NHM_BATCH_MODE", raising=False)
    monkeypatch.delenv("NEBARI_CONDA_STORE_SERVER_SERVICE_HOST", raising=False)
    monkeypatch.setattr(map_template, "is_wsl", lambda: False)
    map_template.make_webbrowser_map(path)
    return seen


def test_make_webbrowser_map_passes_a_file_url_not_a_bare_path(tmp_path, monkeypatch):
    map_file = tmp_path / "hydrofabric_map.html"
    map_file.write_text("<html></html>")

    seen = _call_make_webbrowser_map(monkeypatch, map_file)

    assert seen["url"].startswith("file://"), (
        f"a bare path reached webbrowser.open ({seen['url']!r}); AppleScript "
        "`open location` silently opens nothing when handed one"
    )
    assert str(map_file) != seen["url"]


def test_make_webbrowser_map_percent_encodes_spaces(tmp_path, monkeypatch):
    """Model directories with spaces must survive the conversion."""
    directory = tmp_path / "Walla Walla"
    directory.mkdir()
    map_file = directory / "hydrofabric_map.html"
    map_file.write_text("<html></html>")

    seen = _call_make_webbrowser_map(monkeypatch, map_file)

    assert "%20" in seen["url"], f"space not encoded in {seen['url']!r}"
    assert " " not in seen["url"]


def test_batch_mode_still_skips_the_browser(tmp_path, monkeypatch):
    """The notebook chain runs under NHM_BATCH_MODE and must open nothing."""
    import webbrowser

    from assist.common import map_template

    called = []
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: called.append(a))
    monkeypatch.setenv("NHM_BATCH_MODE", "1")

    map_template.make_webbrowser_map(tmp_path / "map.html")

    assert not called, "batch mode tried to open a browser"


def test_unopenable_browser_reports_the_saved_path(tmp_path, monkeypatch, capsys):
    """A headless kernel should say where the html is, not fail silently."""
    map_file = tmp_path / "hydrofabric_map.html"
    map_file.write_text("<html></html>")

    _call_make_webbrowser_map(monkeypatch, map_file, open_returns=False)

    assert str(map_file) in capsys.readouterr().out
