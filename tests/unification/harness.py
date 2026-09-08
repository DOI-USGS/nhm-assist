"""Differential-test harness for the helper unification.

Loads pre-unification implementations straight out of git so the old code can
act as the oracle for the new `common/` implementation.
"""
from __future__ import annotations

import contextlib
import importlib.util
import pathlib as pl
import subprocess
import sys
import tempfile
from types import ModuleType

import pandas as pd
from pandas.testing import assert_frame_equal

REPO_ROOT = pl.Path(__file__).resolve().parents[2]

# The feature/runner merge: last commit before any unification of this concern.
BASELINE_REV = "27f7144"

MODELS: dict[str, pl.Path] = {
    "walla_walla": REPO_ROOT / "nhf_assist" / "domain_data" / "Walla_Walla",
    "wwgw_basin": REPO_ROOT / "nhf_assist" / "domain_data" / "WWGW_Basin",
    "umatilla": REPO_ROOT / "nhf_assist" / "domain_data" / "UmatillaRiver",
}

# Alternate spelling -> canonical name. Order matters only for readability.
ID_ALIASES: dict[str, str] = {
    "hru_id": "nhm_id",
    "hruid": "nhm_id",
    "nhru": "nhm_id",
    "hru_segment": "hru_segment_nhm",
    "segment_id": "nhm_seg",
    "seg_id": "nhm_seg",
    "tosegment": "tosegment_nhm",
    "poi_id": "poi_gage_id",
}

_module_cache: dict[tuple[str, str], ModuleType] = {}

# Historical fabric module path -> the unified module that replaced it.
#
# The shipped package no longer carries `assist.nhm.*` / `assist.nhf.*`
# re-export shims. Pre-unification sources still import through those paths
# (`from assist.nhm.nhm_helpers import hrus_by_poi`), so loading one as an
# oracle needs the old names resolvable for the duration of the load. These
# aliases exist only inside the test harness: they are installed around
# `exec_module` and removed again, so nothing here makes a deleted path
# importable for application code.
_BASELINE_MODULE_ALIASES: dict[str, str] = {
    "assist.nhm.efc": "assist.common.efc",
    "assist.nhm.nhm_helpers": "assist.common.helpers",
    "assist.nhm.nhm_assist_utilities": "assist.common.assist_utilities",
    "assist.nhm.nhm_hydrofabric": "assist.common.hydrofabric",
    "assist.nhm.nhm_output_visualization": "assist.common.output_visualization",
    "assist.nhm.output_plots": "assist.common.output_plots",
    "assist.nhm.sf_data_retrieval": "assist.common.sf_data_retrieval",
    "assist.nhm.map_template": "assist.common.map_template",
    "assist.nhm.streamflow_postprocess": "assist.common.streamflow_postprocess",
    "assist.nhf.efc": "assist.common.efc",
    "assist.nhf.nhm_helpers_v2": "assist.common.helpers",
    "assist.nhf.nhm_assist_utilities_v2": "assist.common.assist_utilities",
    "assist.nhf.nhm_hydrofabric_v2": "assist.common.hydrofabric",
    "assist.nhf.nhm_output_visualization_v2": "assist.common.output_visualization",
    "assist.nhf.output_plots_v2": "assist.common.output_plots",
    "assist.nhf.sf_data_retrieval_v2_1": "assist.common.sf_data_retrieval",
    "assist.nhf.map_template_v2": "assist.common.map_template",
    "assist.nhf.display_controls_v2": "assist.common.display_controls",
}


@contextlib.contextmanager
def _baseline_import_aliases():
    """Make the retired fabric module paths resolvable, then take them away."""
    import importlib

    installed = []
    try:
        for old_path, new_path in _BASELINE_MODULE_ALIASES.items():
            if old_path in sys.modules:
                continue
            try:
                sys.modules[old_path] = importlib.import_module(new_path)
            except ModuleNotFoundError:
                # A baseline that predates this module simply will not ask.
                continue
            installed.append(old_path)
        yield
    finally:
        for old_path in installed:
            sys.modules.pop(old_path, None)


def load_module_from_git(rev: str, repo_path: str, module_name: str) -> ModuleType:
    """Import the version of `repo_path` recorded at `rev` as `module_name`."""
    key = (rev, repo_path)
    if key in _module_cache:
        return _module_cache[key]

    source = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{rev}:{repo_path}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    tmp_dir = pl.Path(tempfile.mkdtemp(prefix="unification_baseline_"))
    tmp_file = tmp_dir / f"{module_name}.py"
    tmp_file.write_text(source, encoding="utf-8")

    spec = importlib.util.spec_from_file_location(module_name, tmp_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build a spec for {repo_path} at {rev}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    with _baseline_import_aliases():
        spec.loader.exec_module(module)

    _module_cache[key] = module
    return module


def normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Rename identifier columns to their canonical `common/` spelling."""
    rename = {c: ID_ALIASES[c] for c in df.columns if c in ID_ALIASES}
    return df.rename(columns=rename) if rename else df


def assert_frames_equivalent(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    sort_by: str | None = None,
) -> None:
    """Compare two frames, ignoring identifier naming and column order."""
    left_n = normalize_ids(left.reset_index(drop=True))
    right_n = normalize_ids(right.reset_index(drop=True))

    if sort_by is not None:
        left_n = left_n.sort_values(sort_by).reset_index(drop=True)
        right_n = right_n.sort_values(sort_by).reset_index(drop=True)

    shared = [c for c in left_n.columns if c in right_n.columns]
    assert shared, (
        f"no shared columns: left={sorted(left_n.columns)} "
        f"right={sorted(right_n.columns)}"
    )

    assert_frame_equal(
        left_n[shared],
        right_n[shared],
        check_dtype=False,
        check_like=True,
    )
