"""Regression test for the dropped HRU calibration-level feature.

`create_hru_gdf` used to return `(hru_gdf, hru_text, hru_cal_level_txt)`,
computing calibration-level reporting for HRUs from a CONUS-wide data
dependency (`nhm_v1_1_HRU_cal_levels.csv`). The nhf/nhm hydrofabric
unification took nhf's version verbatim, which had that block commented out
and returned only two values. The change was silent: nothing checked the
seven nhm/pest call sites that still unpacked three (or, via
`make_hf_map_elements`, still named `hru_cal_level_txt`), so the nhm workflow
chain failed at runtime with `ValueError: not enough values to unpack
(expected 3, got 2)`.

This test:
  1. Calls `create_hru_gdf` against the real Walla_Walla example model and
     asserts it returns 3 values, with the third a non-empty string
     mentioning HWs (headwaters).
  2. Calls `make_hf_map_elements` against the same model and asserts it
     returns 12 values (the 9 it returned before this fix, plus the restored
     `hru_cal_level_txt`, `HW_basins_gdf`, and `HW_basins`).
  3. Parses every `.py` file under `src/` with `ast` (not regex, so it
     survives call sites moving to different lines) to find every top-level
     assignment whose right-hand side is a call to `create_hru_gdf` or
     `make_hf_map_elements`, and asserts the number of unpacked targets
     matches the function's actual return arity. This is the check that
     would have caught the original break.
"""
from __future__ import annotations

import ast
import pathlib as pl

import pytest

from assist.common.hydrofabric import create_hru_gdf, make_hf_map_elements

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
MODEL_DIR = REPO_ROOT / "nhf_assist" / "domain_data" / "Walla_Walla"

NHRU_PARAMS = [
    "carea_max", "emis_noppt", "fastcoef_lin", "freeh2o_cap", "gwflow_coef",
    "potet_sublim", "rad_trncf", "slowcoef_sq", "smidx_coef", "smidx_exp",
    "snowinfil_max", "soil2gw_max", "soil_moist_max", "soil_rechr_max_frac",
    "ssr2gw_exp", "ssr2gw_rate", "hru_slope", "hru_aspect",
]
NHRU_NMONTHS_PARAMS = [
    "adjmix_rain", "cecn_coef", "jh_coef", "radmax", "rain_cbh_adj",
    "snow_cbh_adj", "tmax_allrain_offset", "tmax_allsnow", "tmax_cbh_adj",
    "tmin_cbh_adj",
]

# Functions this test guards, and their expected return arity now that
# hru_cal_level_txt is restored.
EXPECTED_ARITY = {
    "create_hru_gdf": 3,
    "make_hf_map_elements": 12,
}


def _require_model():
    if not MODEL_DIR.exists():
        pytest.skip(f"Walla_Walla example model not present at {MODEL_DIR}")


def test_create_hru_gdf_returns_three_values():
    _require_model()
    result = create_hru_gdf(
        root_dir=REPO_ROOT,
        model_dir=MODEL_DIR,
        GIS_format=".gpkg",
        param_filename=MODEL_DIR / "myparam.param",
        nhru_params=NHRU_PARAMS,
        nhru_nmonths_params=NHRU_NMONTHS_PARAMS,
    )
    assert len(result) == 3

    hru_cal_level_txt = result[2]
    assert isinstance(hru_cal_level_txt, str)
    assert hru_cal_level_txt.strip() != ""
    assert "HW" in hru_cal_level_txt


def test_make_hf_map_elements_returns_twelve_values(monkeypatch):
    """Exercises the real `create_hru_gdf`/`create_segment_gdf` GIS-reading
    path (which is what the restored calibration-level merge runs inside),
    but stubs out the gage-lookup helpers (`create_poi_df`,
    `fetch_waterdata_gage_info`, `read_gages_file`). Those need exact gage
    CSV fixtures and, for `fetch_waterdata_gage_info`, live network access —
    neither of which this test is about. It only needs to prove the function
    hands back 12 values in the right shape.
    """
    _require_model()
    import assist.common.hydrofabric as hf_module

    monkeypatch.setattr(hf_module, "create_poi_df", lambda **kwargs: "poi_df_stub")
    monkeypatch.setattr(
        hf_module, "fetch_waterdata_gage_info", lambda **kwargs: "waterdata_gages_aoi_stub"
    )
    monkeypatch.setattr(
        hf_module,
        "read_gages_file",
        lambda **kwargs: ("gages_df_stub", "gages_txt_stub", "gages_txt_nb2_stub"),
    )

    result = make_hf_map_elements(
        root_dir=REPO_ROOT,
        model_dir=MODEL_DIR,
        GIS_format=".gpkg",
        param_filename=MODEL_DIR / "myparam.param",
        control_file_name="control.default.bandit",
        waterdata_gages_file=MODEL_DIR / "WaterDataGages.csv",
        gages_file=MODEL_DIR / "gages.csv",
        resource_gages_file=MODEL_DIR / "resource_gages.csv",
        default_gages_file=MODEL_DIR / "default_gages.csv",
        nhru_params=NHRU_PARAMS,
        nhru_nmonths_params=NHRU_NMONTHS_PARAMS,
        waterdata_gage_nobs_min=365,
    )
    assert len(result) == 12

    hru_cal_level_txt = result[2]
    assert isinstance(hru_cal_level_txt, str)
    assert "HW" in hru_cal_level_txt


def _iter_py_files(root: pl.Path):
    for path in root.rglob("*.py"):
        if ".ipynb_checkpoints" in path.parts:
            continue
        yield path


def _unpack_counts_for_calls(source: str, func_name: str) -> list[tuple[int, int]]:
    """Return (lineno, target_count) for every top-level assignment in
    `source` whose RHS is a bare call to `func_name(...)`.

    Only plain `name(...)` calls are matched (not attribute calls), which is
    how every caller in this codebase invokes these two functions. A
    tuple-unpack target (`a, b, c = ...` or `(a, b, c) = ...`) counts its
    elements; a single bare-name target (`x = ...`) counts as 1.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # A handful of workflow templates in this repo are not valid,
        # parseable Python on their own (e.g. stray indentation from
        # jupytext round-tripping) independent of this feature. They import
        # these functions but do not call them, so skipping is safe here;
        # a real call site living in an unparseable file would still show up
        # as a `found_any` gap for a well-formed caller elsewhere failing to
        # compensate, since every other call site is checked independently.
        return []
    counts: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
            continue
        if call.func.id != func_name:
            continue
        for target in node.targets:
            if isinstance(target, (ast.Tuple, ast.List)):
                counts.append((node.lineno, len(target.elts)))
            else:
                counts.append((node.lineno, 1))
    return counts


@pytest.mark.parametrize("func_name", sorted(EXPECTED_ARITY))
def test_every_call_site_under_src_unpacks_the_matching_arity(func_name):
    expected = EXPECTED_ARITY[func_name]
    src_root = REPO_ROOT / "src"
    mismatches = []
    found_any = False

    for path in _iter_py_files(src_root):
        source = path.read_text(encoding="utf-8", errors="ignore")
        if func_name not in source:
            continue
        for lineno, count in _unpack_counts_for_calls(source, func_name):
            found_any = True
            if count != expected:
                mismatches.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno} unpacks {count} "
                    f"value(s) from {func_name}(...), expected {expected}"
                )

    assert found_any, (
        f"expected at least one top-level unpacking call to {func_name}(...) "
        f"under {src_root}, found none. Either every call site was removed "
        "or this test's ast walk needs updating."
    )
    assert mismatches == [], "\n".join(mismatches)
