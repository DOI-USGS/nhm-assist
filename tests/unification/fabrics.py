"""Two-fabric fixtures for the hydrofabric unification.

GFv1.1 and GFv2 geopackages carry different identifier columns, so every
differential test in this concern runs against both.
"""
from __future__ import annotations

import ast
import inspect
import pathlib as pl
import subprocess

import geopandas as gpd

from tests.unification.harness import MODELS, REPO_ROOT

FABRICS: dict[str, pl.Path] = {
    "gfv1_1": MODELS["walla_walla"],
    "gfv2": MODELS["umatilla"],
}


def gpkg_columns(model_dir: pl.Path, layer: str) -> set[str]:
    """Column names (excluding geometry) of one layer of a model's geopackage."""
    gpkg = pl.Path(model_dir) / "GIS" / "model_layers.gpkg"
    frame = gpd.read_file(gpkg, layer=layer, rows=1)
    return {c for c in frame.columns if c != "geometry"}


HYDROFABRIC_BASELINE = "b9ae03d"

NHM_HF = "src/assist/nhm/nhm_hydrofabric.py"
NHF_HF = "src/assist/nhf/nhm_hydrofabric_v2.py"


def baseline_function_source(repo_path: str, name: str, rev: str = HYDROFABRIC_BASELINE) -> str:
    """Source text of one function as recorded at `rev`, without importing it.

    Deliberately parses rather than imports. Importing a historical module runs
    its import block, and this concern deletes
    assist.common.assist_utilities.find_missing_gage_metadata in Task 7 — which
    src/assist/nhm/nhm_hydrofabric.py imports at this baseline. An import-based
    comparison would pass early in the plan and then break permanently.
    """
    source = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{rev}:{repo_path}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    tree = ast.parse(source)
    node = next(
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    segment = ast.get_source_segment(source, node)
    if segment is None:
        raise ValueError(f"could not extract {name} from {repo_path}@{rev}")
    return segment


def baseline_function_ast(repo_path: str, name: str, rev: str = HYDROFABRIC_BASELINE) -> str:
    """Normalized AST dump of a baseline function, name-insensitive."""
    node = ast.parse(baseline_function_source(repo_path, name, rev)).body[0]
    node.name = "_"
    return ast.dump(node)


def current_function_ast(fn) -> str:
    """Normalized AST dump of a live function, comparable to the above."""
    node = ast.parse(inspect.getsource(fn).lstrip()).body[0]
    node.name = "_"
    return ast.dump(node)


# A config carrying every required key. Written in the nhm (NWIS) spelling; the
# loader back-fills the WaterData names, so this satisfies the required set.
COMPLETE_CONFIG = {
    "Folium_maps_dir": "/tmp/m/fm", "model_dir": "/tmp/m",
    "param_filename": "/tmp/m/myparam.param", "param_file": "myparam.param",
    "gages_file": "/tmp/m/gages.csv", "default_gages_file": "/tmp/m/default_gages.csv",
    "output_netcdf_filename": "/tmp/m/out.nc", "NHM_dir": "/tmp/nhm",
    "out_dir": "/tmp/m/output", "notebook_output_dir": "/tmp/m/nof",
    "html_maps_dir": "/tmp/m/hm", "html_plots_dir": "/tmp/m/hp",
    "nc_files_dir": "/tmp/m/nc", "subdomain": "TestBasin", "GIS_format": ".gpkg",
    "control_file_name": "control.default.bandit",
    "nwis_gages_file": "/tmp/m/NWISgages.csv", "nwis_gage_nobs_min": 365,
    "nhru_nmonths_params": ["jh_coef"], "nhru_params": ["carea_max"],
    "selected_output_variables": ["recharge"], "water_years": True,
    "start_date": "1980-01-01T00:00:00", "end_date": "2022-12-31T00:00:00",
    "workspace_txt": "test",
}
