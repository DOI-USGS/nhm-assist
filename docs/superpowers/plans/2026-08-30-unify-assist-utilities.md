# Helper Unification, Concern 1: `assist_utilities` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse `src/assist/nhm/nhm_assist_utilities.py` (1100L) and `src/assist/nhf/nhm_assist_utilities_v2.py` (1614L) into a single `src/assist/common/assist_utilities.py`, reducing both originals to re-export shims, with every merge decision justified by a differential test.

**Architecture:** Build a reusable differential-test harness that loads the pre-unification implementations out of git and compares them against the new `common/` implementation on real model data. Merge function-by-function, choosing per function which side is authoritative rather than assuming `_v2` wins. Identifier and config-schema differences are absorbed by small adapters in `common/`.

**Tech Stack:** Python 3.11, pytest, pandas / geopandas, pyPRMS, pywatershed, folium, pixi (`pixi run --frozen`).

**Spec:** `docs/superpowers/specs/2026-08-30-helper-unification-design.md`

## Global Constraints

- Branch: `restructure/helper-unification-2`. Baseline commit for all differential tests: `27f7144` (the `feature/runner` merge).
- Run everything through pixi: `pixi run --frozen python -m pytest ...`. `pixi` lives at `~/.pixi/bin/pixi` and is not on PATH.
- Canonical identifier names inside `common/`: `nhm_id`, `nhm_seg`, `poi_gage_id`. `poi_id` is retired.
- `tests/` and `docs/` are gitignored (`.gitignore:487`); every new file there needs `git add -f`.
- The nhf shim keeps its existing filename `nhm_assist_utilities_v2.py`. 38 workflow templates import it; renaming breaks them.
- Never delete `metadata/fmi_gages_info.csv` (spec decision 5). Nothing can regenerate it.
- Preserve the graceful-skip guard in `fetch_FMI_npoigages_info` added in commit `01fc9b6`.
- Full suite must stay green: 85 passed, 9 subtests.

---

### Task 1: Differential-test harness

**Files:**
- Create: `tests/unification/__init__.py`
- Create: `tests/unification/harness.py`
- Test: `tests/unification/test_harness.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `load_module_from_git(rev: str, repo_path: str, module_name: str) -> ModuleType`
  - `BASELINE_REV: str` (value `"27f7144"`)
  - `normalize_ids(df: pandas.DataFrame) -> pandas.DataFrame`
  - `assert_frames_equivalent(left, right, *, sort_by: str | None = None) -> None`
  - `MODELS: dict[str, pathlib.Path]` mapping `"walla_walla" | "wwgw_basin" | "umatilla"` to model directories

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_harness.py
import pandas as pd
import pytest

from tests.unification.harness import (
    BASELINE_REV,
    assert_frames_equivalent,
    load_module_from_git,
    normalize_ids,
)


def test_loads_a_module_out_of_git():
    mod = load_module_from_git(
        BASELINE_REV, "src/assist/nhm/nhm_assist_utilities.py", "baseline_nhm_utils"
    )
    assert hasattr(mod, "find_missing_gage_info")


def test_normalize_ids_maps_alternate_names_to_canonical():
    df = pd.DataFrame({"hru_id": [1], "hru_segment": [2], "segment_id": [3]})
    out = normalize_ids(df)
    assert list(out.columns) == ["nhm_id", "hru_segment_nhm", "nhm_seg"]


def test_normalize_ids_leaves_canonical_names_alone():
    df = pd.DataFrame({"nhm_id": [1], "poi_gage_id": ["123"]})
    assert list(normalize_ids(df).columns) == ["nhm_id", "poi_gage_id"]


def test_assert_frames_equivalent_ignores_identifier_naming():
    left = pd.DataFrame({"nhm_id": [1, 2], "value": [10, 20]})
    right = pd.DataFrame({"hru_id": [1, 2], "value": [10, 20]})
    assert_frames_equivalent(left, right)


def test_assert_frames_equivalent_still_catches_real_differences():
    left = pd.DataFrame({"nhm_id": [1, 2], "value": [10, 20]})
    right = pd.DataFrame({"nhm_id": [1, 2], "value": [10, 99]})
    with pytest.raises(AssertionError):
        assert_frames_equivalent(left, right)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.unification.harness'`

- [ ] **Step 3: Write minimal implementation**

```python
# tests/unification/__init__.py
```

```python
# tests/unification/harness.py
"""Differential-test harness for the helper unification.

Loads pre-unification implementations straight out of git so the old code can
act as the oracle for the new `common/` implementation.
"""
from __future__ import annotations

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_harness.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add -f tests/unification/__init__.py tests/unification/harness.py tests/unification/test_harness.py
git commit -m "test: add differential-test harness for helper unification

Loads pre-unification modules out of git at 27f7144 so the existing code
can serve as the oracle when functions move to assist/common/."
```

---

### Task 2: Prove the harness can detect the existing divergence

This is the spec's precondition (section 7): a harness that cannot tell the two current implementations apart is worthless as an oracle. This task adds no production code.

**Files:**
- Test: `tests/unification/test_baseline_divergence.py`

**Interfaces:**
- Consumes: `load_module_from_git`, `BASELINE_REV` from Task 1.
- Produces: nothing. Guard test only.

- [ ] **Step 1: Write the test**

```python
# tests/unification/test_baseline_divergence.py
"""Guard: the harness must see the differences we already measured.

If these fail, the harness is not a usable oracle and no unification should
proceed on top of it.
"""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHM_PATH = "src/assist/nhm/nhm_assist_utilities.py"
NHF_PATH = "src/assist/nhf/nhm_assist_utilities_v2.py"

# Measured at 27f7144.
EXPECTED_DIFFERING = {
    "create_append_gages_to_param_file",
    "delete_notebook_output_files",
    "find_missing_gage_info",
    "load_subdomain_config",
    "make_myparam_addl_gages_param_file",
    "make_obs_plot_files",
    "make_plots_par_vals",
}
EXPECTED_NHF_ONLY = {
    "create_append_gages_to_param_file_v2",
    "fetch_FMI_npoigages_info",
    "fetch_non_ref_npoigages_info",
    "fetch_ref_npoigages_info",
    "fetch_waterdata_gage_info",
}
EXPECTED_NHM_ONLY = {
    "_load_nldi_cached",
    "_translate_waterdata_columns",
    "fetch_nwis_gage_info",
    "make_HW_cal_level_files",
}


@pytest.fixture(scope="module")
def baselines():
    nhm = load_module_from_git(BASELINE_REV, NHM_PATH, "baseline_nhm_utils")
    nhf = load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_utils")
    return nhm, nhf


def _public_functions(module):
    return {
        name
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) and obj.__module__ == module.__name__
    }


def test_both_baselines_import(baselines):
    nhm, nhf = baselines
    assert _public_functions(nhm)
    assert _public_functions(nhf)


def test_nhm_only_functions_are_present(baselines):
    nhm, nhf = baselines
    only_nhm = _public_functions(nhm) - _public_functions(nhf)
    assert EXPECTED_NHM_ONLY <= only_nhm


def test_nhf_only_functions_are_present(baselines):
    nhm, nhf = baselines
    only_nhf = _public_functions(nhf) - _public_functions(nhm)
    assert EXPECTED_NHF_ONLY <= only_nhf


def test_shared_functions_really_do_differ(baselines):
    """Source-level check: each expected-differing function differs."""
    nhm, nhf = baselines
    for name in sorted(EXPECTED_DIFFERING):
        a = ast.dump(ast.parse(inspect.getsource(getattr(nhm, name))))
        b = ast.dump(ast.parse(inspect.getsource(getattr(nhf, name))))
        assert a != b, f"{name} was expected to differ but is identical"
```

- [ ] **Step 2: Run the test**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_baseline_divergence.py -v`
Expected: PASS, 4 tests. **If any fail, stop and fix the harness before continuing.**

- [ ] **Step 3: Commit**

```bash
git add -f tests/unification/test_baseline_divergence.py
git commit -m "test: assert the harness detects known nhm/nhf divergence

Precondition from the design doc: the oracle must distinguish the two
existing implementations before it can judge a rewrite."
```

---

### Task 3: Config-schema adapter

`load_subdomain_config` is not drift — the two sides read different yaml schemas. nhm expects `nwis_gages_file` / `nwis_gage_nobs_min`; nhf expects `waterdata_gages_file` / `waterdata_gage_nobs_min` / `resource_gages_file`. The unified reader must accept either, and nhm's `FileNotFoundError` guard must survive.

**Files:**
- Create: `src/assist/common/assist_utilities.py`
- Test: `tests/unification/test_config_schema.py`

**Interfaces:**
- Consumes: harness from Task 1.
- Produces:
  - `load_subdomain_config(root_dir: pathlib.Path) -> dict`
  - `CONFIG_KEY_ALIASES: dict[str, str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_config_schema.py
import pathlib as pl

import pytest
import yaml

from assist.common.assist_utilities import load_subdomain_config

BASE = {
    "Folium_maps_dir": "/tmp/fm",
    "model_dir": "/tmp/m",
    "param_filename": "/tmp/m/myparam.param",
    "gages_file": "/tmp/m/gages.csv",
    "default_gages_file": "/tmp/m/default_gages.csv",
    "output_netcdf_filename": "/tmp/m/out.nc",
    "control_file_name": "control.default.bandit",
    "nhru_nmonths_params": ["jh_coef"],
}


def _write(tmp_path: pl.Path, extra: dict) -> pl.Path:
    (tmp_path / "subdomain_config.yaml").write_text(
        yaml.safe_dump({**BASE, **extra}), encoding="utf-8"
    )
    return tmp_path


def test_reads_the_nhm_nwis_schema(tmp_path):
    root = _write(tmp_path, {"nwis_gages_file": "/tmp/m/NWISgages.csv",
                             "nwis_gage_nobs_min": 365})
    cfg = load_subdomain_config(root)
    assert cfg["waterdata_gages_file"] == pl.Path("/tmp/m/NWISgages.csv")
    assert cfg["waterdata_gage_nobs_min"] == 365


def test_reads_the_nhf_waterdata_schema(tmp_path):
    root = _write(tmp_path, {"waterdata_gages_file": "/tmp/m/WaterDataGages.csv",
                             "waterdata_gage_nobs_min": 400,
                             "resource_gages_file": "/tmp/m/resource_gages.csv"})
    cfg = load_subdomain_config(root)
    assert cfg["waterdata_gages_file"] == pl.Path("/tmp/m/WaterDataGages.csv")
    assert cfg["waterdata_gage_nobs_min"] == 400
    assert cfg["resource_gages_file"] == pl.Path("/tmp/m/resource_gages.csv")


def test_resource_gages_file_is_optional(tmp_path):
    root = _write(tmp_path, {"nwis_gages_file": "/tmp/m/NWISgages.csv",
                             "nwis_gage_nobs_min": 365})
    assert load_subdomain_config(root)["resource_gages_file"] is None


def test_missing_config_raises_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="0_workspace_setup"):
        load_subdomain_config(tmp_path)


# Regression guard: both baselines wrapped 14 keys in pl.Path(). A key left as a
# raw str breaks every consumer that does `config[key] / "something"`.
PATH_KEYS = [
    "Folium_maps_dir", "model_dir", "param_filename", "gages_file",
    "default_gages_file", "output_netcdf_filename", "waterdata_gages_file",
    "NHM_dir", "out_dir", "notebook_output_dir", "html_maps_dir",
    "html_plots_dir", "nc_files_dir",
]


def test_every_path_key_becomes_a_Path(tmp_path):
    extra = {k: f"/tmp/m/{k}" for k in PATH_KEYS if k not in BASE}
    root = _write(tmp_path, {**extra, "nwis_gages_file": "/tmp/m/NWISgages.csv",
                             "nwis_gage_nobs_min": 365})
    cfg = load_subdomain_config(root)
    for key in PATH_KEYS:
        assert isinstance(cfg[key], pl.Path), f"{key} is {type(cfg[key]).__name__}, not Path"


def test_path_keys_absent_from_yaml_become_None(tmp_path):
    root = _write(tmp_path, {"nwis_gages_file": "/tmp/m/NWISgages.csv",
                             "nwis_gage_nobs_min": 365})
    cfg = load_subdomain_config(root)
    assert cfg["out_dir"] is None
    assert cfg["nc_files_dir"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_config_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assist.common.assist_utilities'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/assist/common/assist_utilities.py
"""Shared assist utilities for the nhm and nhf workflows.

Unified from src/assist/nhm/nhm_assist_utilities.py and
src/assist/nhf/nhm_assist_utilities_v2.py. See
docs/superpowers/specs/2026-08-30-helper-unification-design.md.
"""
from __future__ import annotations

import pathlib as pl

import yaml

# nhm used the NWIS spelling; nhf renamed to WaterData. Accept both, canonical
# form is the WaterData spelling.
CONFIG_KEY_ALIASES: dict[str, str] = {
    "nwis_gages_file": "waterdata_gages_file",
    "nwis_gage_nobs_min": "waterdata_gage_nobs_min",
}

# All 14 keys both baselines wrapped in pl.Path(). Omitting any of these leaves a
# raw str in the config, and consumers doing `config["out_dir"] / "x.nc"` raise
# TypeError. Verified against both baselines at 27f7144.
_PATH_KEYS = (
    "Folium_maps_dir",
    "model_dir",
    "param_filename",
    "gages_file",
    "default_gages_file",
    "output_netcdf_filename",
    "waterdata_gages_file",
    "resource_gages_file",
    "NHM_dir",
    "out_dir",
    "notebook_output_dir",
    "html_maps_dir",
    "html_plots_dir",
    "nc_files_dir",
)


def load_subdomain_config(root_dir: pl.Path) -> dict:
    """Load `subdomain_config.yaml`, accepting either the NWIS or WaterData schema."""
    config_path = pl.Path(root_dir) / "subdomain_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            "Missing subdomain config at "
            f"{config_path}. Set the active model for the project, then run "
            "0_workspace_setup.ipynb first from the same project notebook "
            "directory before running later notebooks."
        )

    with open(config_path) as handle:
        raw = yaml.load(handle, Loader=yaml.FullLoader)

    # Fold the retired NWIS key names onto their WaterData equivalents.
    for old_key, new_key in CONFIG_KEY_ALIASES.items():
        if old_key in raw and new_key not in raw:
            raw[new_key] = raw.pop(old_key)

    config: dict = dict(raw)
    for key in _PATH_KEYS:
        value = raw.get(key)
        config[key] = pl.Path(value) if value is not None else None

    config.setdefault("resource_gages_file", None)
    return config
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_config_schema.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add -f src/assist/common/assist_utilities.py tests/unification/test_config_schema.py
git commit -m "feat: unify load_subdomain_config across nhm and nhf schemas

nhm read nwis_gages_file/nwis_gage_nobs_min; nhf read the WaterData
spellings plus resource_gages_file. The unified reader accepts either and
keeps nhm's actionable FileNotFoundError, which nhf lacked."
```

---

### Task 4: `delete_notebook_output_files` — take nhm's version, drop the FMI deletion

The nhm implementation is strictly safer: it guards against a missing folder (nhf's `os.listdir` would raise), counts deletions instead of printing per file, and **never deletes `metadata/fmi_gages_info.csv`**. The destructive behavior is nhf-only, so unifying toward nhm satisfies spec decision 5 directly.

nhm's file list also mentions `NWISgages.csv` and `default_gages_file.csv`; keep both plus nhf's `metadata/WaterDataGages.csv` so either layout is cleaned.

**Files:**
- Modify: `src/assist/common/assist_utilities.py`
- Test: `tests/unification/test_delete_outputs.py`

**Interfaces:**
- Consumes: `src/assist/common/assist_utilities.py` from Task 3.
- Produces: `delete_notebook_output_files(*, notebook_output_dir: pathlib.Path, model_dir: pathlib.Path) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_delete_outputs.py
import pathlib as pl

from assist.common.assist_utilities import delete_notebook_output_files


def _make_model(tmp_path: pl.Path) -> tuple[pl.Path, pl.Path]:
    out = tmp_path / "notebook_output_files"
    for sub in ("Folium_maps", "html_maps", "html_plots", "nc_files"):
        (out / sub).mkdir(parents=True)
        (out / sub / "stale.txt").write_text("x", encoding="utf-8")
    model = tmp_path / "model"
    (model / "metadata").mkdir(parents=True)
    (model / "default_gages.csv").write_text("a", encoding="utf-8")
    (model / "append_gages_to_param_file.csv").write_text("b", encoding="utf-8")
    (model / "metadata" / "WaterDataGages.csv").write_text("c", encoding="utf-8")
    (model / "metadata" / "fmi_gages_info.csv").write_text("PRECIOUS", encoding="utf-8")
    return out, model


def test_fmi_cache_is_never_deleted(tmp_path):
    out, model = _make_model(tmp_path)
    delete_notebook_output_files(notebook_output_dir=out, model_dir=model)
    fmi = model / "metadata" / "fmi_gages_info.csv"
    assert fmi.exists(), "fmi_gages_info.csv cannot be regenerated and must survive"
    assert fmi.read_text(encoding="utf-8") == "PRECIOUS"


def test_regenerable_files_are_deleted(tmp_path):
    out, model = _make_model(tmp_path)
    delete_notebook_output_files(notebook_output_dir=out, model_dir=model)
    assert not (model / "default_gages.csv").exists()
    assert not (model / "append_gages_to_param_file.csv").exists()
    assert not (model / "metadata" / "WaterDataGages.csv").exists()
    for sub in ("Folium_maps", "html_maps", "html_plots", "nc_files"):
        assert list((out / sub).iterdir()) == []


def test_missing_output_subfolder_does_not_raise(tmp_path):
    out, model = _make_model(tmp_path)
    for item in (out / "nc_files").iterdir():
        item.unlink()
    (out / "nc_files").rmdir()
    delete_notebook_output_files(notebook_output_dir=out, model_dir=model)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_delete_outputs.py -v`
Expected: FAIL — `ImportError: cannot import name 'delete_notebook_output_files'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/assist/common/assist_utilities.py`, and add `import os` to the imports at the top:

```python
def delete_notebook_output_files(
    *,
    notebook_output_dir: pl.Path,
    model_dir: pl.Path,
) -> None:
    """Clear prior notebook output so a rerun starts clean."""
    notebook_output_dir = pl.Path(notebook_output_dir)
    model_dir = pl.Path(model_dir)

    subfolders = ["Folium_maps", "html_maps", "html_plots", "nc_files"]
    deleted_by_subfolder: dict[str, int] = {}
    for subfolder in subfolders:
        folder_path = notebook_output_dir / subfolder
        if not folder_path.exists():
            continue
        count = 0
        for file_name in os.listdir(folder_path):
            file_path = folder_path / file_name
            if file_path.is_file():
                os.remove(file_path)
                count += 1
        if count:
            deleted_by_subfolder[subfolder] = count

    deleted_model_files = 0
    files = [
        "default_gages.csv",
        "append_gages_to_param_file.csv",
        "default_gages_file.csv",
        "NWISgages.csv",
    ]
    for file_name in files:
        target = model_dir / file_name
        if target.exists():
            os.remove(target)
            deleted_model_files += 1

    metadata_files = ["WaterDataGages.csv"]
    for file_name in metadata_files:
        target = model_dir / "metadata" / file_name
        if target.exists():
            os.remove(target)
            deleted_model_files += 1

    total = sum(deleted_by_subfolder.values()) + deleted_model_files
    if total == 0:
        print("No prior notebook output files to delete.")
    else:
        print(f"Deleted {total} prior notebook output file(s).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_delete_outputs.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add -f src/assist/common/assist_utilities.py tests/unification/test_delete_outputs.py
git commit -m "fix: stop deleting the unrecoverable FMI cache

Unifies delete_notebook_output_files toward nhm's implementation, which
guards missing folders and never touched metadata/fmi_gages_info.csv. The
nhf version deleted that file on every notebook-1 run; nothing can rebuild
it without TableA2_FlowManagementIndex.csv. Spec decision 5."
```

---

### Task 5: Three verbatim copies from nhm

All three functions are taken from `src/assist/nhm/nhm_assist_utilities.py` **unchanged**.
No edits, no adapter. Rationale, verified against the baselines and the call graph:

- `make_plots_par_vals` — the two sides differ only by a comment (`##%%time` vs
  `# #%%time`); their ASTs are identical, so the copy is provably behaviour-preserving.
- `create_append_gages_to_param_file` and `make_myparam_addl_gages_param_file` — the nhm
  and nhf copies differ by more than naming. nhm selects
  `["nhm_seg", "model_idx", "distance"]` after the `sjoin_nearest`; nhf selects
  `["segment_id", "distance"]` and has no `model_idx` at all. That is a shape difference,
  not a rename. But **only the nhm workflow calls either function** — both are used
  solely by `src/workflow_templates/nhm/add_pois_to_parameters.py`, and nhf's own
  `create_append_gages_to_param_file_v2` has zero callers anywhere. Unifying to nhm's
  version therefore changes nothing any caller can observe.
- No `resolve_segment_column` adapter is added. The spec requires adapters be justified
  by an observed difference in exercised code; here the divergent shape lives only in an
  uncalled copy, so an adapter would be speculative. If an nhf notebook ever calls these,
  it will need one — recorded as a known gap, not built now.

**Files:**
- Modify: `src/assist/common/assist_utilities.py`
- Test: `tests/unification/test_verbatim_copies.py`

**Interfaces:**
- Consumes: `load_module_from_git`, `BASELINE_REV` from Task 1; the module from Task 3.
- Produces, with signatures byte-identical to their nhm originals:
  - `make_plots_par_vals(...)`
  - `create_append_gages_to_param_file(...)`
  - `make_myparam_addl_gages_param_file(...)`

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_verbatim_copies.py
"""Assert the functions this task copies really were copied unchanged.

Compares the AST of each function in assist.common.assist_utilities against the
same function in the pre-unification nhm module, read out of git. This is the
guard against a transcription slip during a "verbatim" copy.
"""
import ast
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


def _ast_of(fn):
    return ast.dump(ast.parse(inspect.getsource(fn)))


@pytest.mark.parametrize("name", COPIED_FROM_NHM)
def test_copy_is_ast_identical_to_the_nhm_baseline(name, nhm_baseline):
    import assist.common.assist_utilities as common

    assert _ast_of(getattr(common, name)) == _ast_of(getattr(nhm_baseline, name)), (
        f"{name} in common/ is not a verbatim copy of the nhm baseline"
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_verbatim_copies.py -v`
Expected: FAIL — `AttributeError`, the three functions do not exist in `common/` yet

- [ ] **Step 3: Write minimal implementation**

Copy the three functions from `src/assist/nhm/nhm_assist_utilities.py` into
`src/assist/common/assist_utilities.py` **exactly as they are** — same body, same
docstrings, same comments, same indentation. Change nothing inside them.

Then add whatever module-level imports they need to the top of the file. Determine
these by reading the nhm module's import block and taking only what these three
functions actually reference. Expect `pandas as pd`, `geopandas as gpd`, and
`numpy as np`; check for `plotly.express as px` and `pyPRMS` usage too. The file
currently imports only `os`, `pathlib as pl`, and `yaml`.

Do NOT rewrite `pdb.get("nhm_seg")` — that string is a pyPRMS parameter name, and the
last test asserts it survives.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_verbatim_copies.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/assist_utilities.py
git add -f tests/unification/test_verbatim_copies.py
```

### Task 6: `make_obs_plot_files` — take nhf's parallel version

This is the one function in this concern where nhf is clearly ahead: it wraps plot generation in a `ThreadPoolExecutor` with a `tqdm` progress bar and a `max_workers=8` parameter. Take nhf's implementation wholesale.

**Files:**
- Modify: `src/assist/common/assist_utilities.py`
- Test: `tests/unification/test_obs_plot_files.py`

**Interfaces:**
- Consumes: Task 3's module.
- Produces: `make_obs_plot_files(*, start_date, end_date, gages_df, xr_streamflow, Folium_maps_dir, max_workers: int = 8) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_obs_plot_files.py
import inspect

import numpy as np
import pandas as pd
import xarray as xr

from assist.common.assist_utilities import make_obs_plot_files


def test_signature_keeps_the_max_workers_knob():
    params = inspect.signature(make_obs_plot_files).parameters
    assert params["max_workers"].default == 8
    for required in ("start_date", "end_date", "gages_df", "xr_streamflow",
                     "Folium_maps_dir"):
        assert required in params


def _tiny_streamflow(gage_ids):
    time = pd.date_range("2020-01-01", periods=10, freq="D")
    data = np.arange(len(time) * len(gage_ids), dtype=float).reshape(
        len(time), len(gage_ids)
    )
    return xr.Dataset(
        {"discharge": (("time", "poi_gage_id"), data)},
        coords={"time": time, "poi_gage_id": list(gage_ids)},
    )


def test_writes_one_plot_file_per_gage(tmp_path):
    gage_ids = ["12345678", "87654321"]
    gages_df = pd.DataFrame(index=pd.Index(gage_ids, name="poi_gage_id"))
    make_obs_plot_files(
        start_date="01/01/2020",
        end_date="01/10/2020",
        gages_df=gages_df,
        xr_streamflow=_tiny_streamflow(gage_ids),
        Folium_maps_dir=tmp_path,
        max_workers=2,
    )
    for gage in gage_ids:
        assert (tmp_path / f"{gage}_streamflow_obs.txt").exists()


def test_existing_plot_files_are_not_regenerated(tmp_path):
    gage_ids = ["12345678"]
    marker = tmp_path / "12345678_streamflow_obs.txt"
    marker.write_text("ORIGINAL", encoding="utf-8")
    gages_df = pd.DataFrame(index=pd.Index(gage_ids, name="poi_gage_id"))
    make_obs_plot_files(
        start_date="01/01/2020",
        end_date="01/10/2020",
        gages_df=gages_df,
        xr_streamflow=_tiny_streamflow(gage_ids),
        Folium_maps_dir=tmp_path,
        max_workers=2,
    )
    assert marker.read_text(encoding="utf-8") == "ORIGINAL"


def test_copy_is_ast_identical_to_the_nhf_baseline():
    """Guard against a transcription slip during the verbatim copy."""
    import ast

    from tests.unification.harness import BASELINE_REV, load_module_from_git

    nhf = load_module_from_git(
        BASELINE_REV,
        "src/assist/nhf/nhm_assist_utilities_v2.py",
        "baseline_nhf_for_obs_plots",
    )
    mine = ast.dump(ast.parse(inspect.getsource(make_obs_plot_files)))
    theirs = ast.dump(ast.parse(inspect.getsource(nhf.make_obs_plot_files)))
    assert mine == theirs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_obs_plot_files.py -v`
Expected: FAIL — `ImportError: cannot import name 'make_obs_plot_files'`

- [ ] **Step 3: Write minimal implementation**

Copy `make_obs_plot_files` verbatim from
`src/assist/nhf/nhm_assist_utilities_v2.py` into
`src/assist/common/assist_utilities.py`. Change nothing inside it.

**Add no imports.** Leave its two function-local imports
(`from concurrent.futures import ThreadPoolExecutor, as_completed` and
`from tqdm.auto import tqdm`) exactly where they are, inside the function body — hoisting
them would make the copy non-verbatim for no benefit. The only module-level names the
function uses are `plotly` and `px`, both already imported by Task 5. `tqdm` 4.68.2 is
present in the pixi environment.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_obs_plot_files.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add -f src/assist/common/assist_utilities.py tests/unification/test_obs_plot_files.py
git commit -m "feat: unify make_obs_plot_files on nhf's parallel implementation

nhf added ThreadPoolExecutor + tqdm with a max_workers knob; nhm looped
serially. Taking nhf's version wholesale."
```

---

### Task 7: `find_missing_gage_info` — nhf takes the name, nhm's becomes private

These are not two implementations of one function. They share a name and nothing else:

| | nhf | nhm |
| --- | --- | --- |
| signature | `(root_dir, dest_dir, gages_list, resource_file_path)` positional | `(*, gage_ids, poi_df, resource_file_path, root_dir, nldi_geojson_path=None)` keyword-only |
| returns | `gages_df` — the caller's frame, augmented in place | a metadata-only frame indexed by `poi_gage_id` |
| length | 348 lines | 92 lines |
| call sites | ~15 (pest `00_Subset`/`01_Prepare` v1.1 and gfv2, `nhf/Fetch_poi_supplimental_information.py`, `gf_params_parse{,_v1_1}.py`, `nhf/nhm_hydrofabric_v2.py` ×3, 2 internal) | 1 (`src/assist/nhm/nhm_hydrofabric.py:565`) |

Per spec decision 8, nhf takes the canonical name. nhm's version is carried as
`_find_missing_gage_metadata` — identical body, new name — because its single caller does
`default_gages_df.set_index("poi_gage_id").combine_first(fetched)`, which depends on the
metadata-only return shape. Handing that caller nhf's whole-frame return would corrupt it
silently rather than raise. The caller is migrated in the hydrofabric concern, where it
lives; this task only stops it breaking.

`_load_nldi_cached` and `_translate_waterdata_columns` come along, since they exist solely
to serve the nhm implementation and stay live under the private name.

**Files:**
- Modify: `src/assist/common/assist_utilities.py`
- Test: `tests/unification/test_find_missing_gage_info.py`

**Interfaces:**
- Consumes: `load_module_from_git`, `BASELINE_REV` from Task 1; the module from Task 3.
- Produces:
  - `find_missing_gage_info(root_dir, dest_dir, gages_list, resource_file_path)` — nhf's, verbatim
  - `_find_missing_gage_metadata(*, gage_ids, poi_df, resource_file_path, root_dir, nldi_geojson_path=None)` — nhm's body, renamed
  - `_load_nldi_cached(...)`, `_translate_waterdata_columns(...)` — nhm's, verbatim

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_find_missing_gage_info.py
"""find_missing_gage_info is nhf's; nhm's survives under a private name."""
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


def test_canonical_is_verbatim_nhf(baselines):
    import assist.common.assist_utilities as common

    _, nhf = baselines
    assert _body_ast(common.find_missing_gage_info) == _body_ast(nhf.find_missing_gage_info)


def test_nhm_version_survives_under_a_private_name(baselines):
    import assist.common.assist_utilities as common

    nhm, _ = baselines
    assert inspect.signature(common._find_missing_gage_metadata) == inspect.signature(
        nhm.find_missing_gage_info
    )
    assert _body_ast(common._find_missing_gage_metadata) == _body_ast(
        nhm.find_missing_gage_info
    )


def test_nhm_private_helpers_came_along():
    import assist.common.assist_utilities as common

    assert callable(common._load_nldi_cached)
    assert callable(common._translate_waterdata_columns)


def test_nhm_metadata_lookup_keeps_its_return_contract(tmp_path):
    """Empty input must give an empty frame indexed by poi_gage_id."""
    import assist.common.assist_utilities as common
    import pandas as pd

    out = common._find_missing_gage_metadata(
        gage_ids=[],
        poi_df=pd.DataFrame(),
        resource_file_path=tmp_path / "missing.csv",
        root_dir=tmp_path,
    )
    assert out.empty
    assert out.index.name == "poi_gage_id"
    assert list(out.columns) == ["latitude", "longitude", "poi_name", "poi_agency"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_find_missing_gage_info.py -v`
Expected: FAIL — `AttributeError: module 'assist.common.assist_utilities' has no attribute 'find_missing_gage_info'`

- [ ] **Step 3: Write minimal implementation**

1. Copy `find_missing_gage_info` verbatim from
   `src/assist/nhf/nhm_assist_utilities_v2.py` into
   `src/assist/common/assist_utilities.py`.
2. Copy `find_missing_gage_info` from `src/assist/nhm/nhm_assist_utilities.py`, rename it
   to `_find_missing_gage_metadata`, and change nothing else inside it.
3. Copy `_load_nldi_cached` and `_translate_waterdata_columns` verbatim from the nhm
   module.
4. Add exactly ONE new module-level import — `from dataretrieval import waterdata` —
   and nothing else. I verified the free names of all four functions against what the
   module already imports: `waterdata` is the only one missing. Both baselines import it
   the same way, and it resolves in the pixi environment. `METADATA_COLS` looks like a
   module constant but is defined inside nhm's function body, so it travels with the copy.
   Do not add `warnings`, `logging`, or anything else speculatively.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_find_missing_gage_info.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/assist_utilities.py
git add -f tests/unification/test_find_missing_gage_info.py
```

### Task 8: Carry over the one-sided functions

Nine functions exist on only one side. Two of them (`_load_nldi_cached` and
`_translate_waterdata_columns`) already arrived in Task 7, so this task carries the
remaining seven.

nhf-only, copy verbatim from `src/assist/nhf/nhm_assist_utilities_v2.py`:
`create_append_gages_to_param_file_v2`, `fetch_FMI_npoigages_info` (**with the
`01fc9b6` graceful-skip guard intact**), `fetch_non_ref_npoigages_info`,
`fetch_ref_npoigages_info`, `fetch_waterdata_gage_info`.

nhm-only, copy verbatim from `src/assist/nhm/nhm_assist_utilities.py`:
`fetch_nwis_gage_info`, `make_HW_cal_level_files`. (`_load_nldi_cached` and
`_translate_waterdata_columns` already arrived in Task 7.)

Note on naming: under spec decision 7, `fetch_waterdata_gage_info` (nhf) is the canonical
name and `fetch_nwis_gage_info` (nhm) is legacy. Both are carried because both have live
callers; do not rename or merge them in this task.

**Files:**
- Modify: `src/assist/common/assist_utilities.py`
- Test: `tests/unification/test_carried_over.py`

**Interfaces:**
- Consumes: Task 7's module.
- Produces: all nine functions above, signatures unchanged from their source side.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_carried_over.py
import inspect
import pathlib as pl

import pandas as pd
import pytest

import assist.common.assist_utilities as cu

NHF_ONLY = [
    "create_append_gages_to_param_file_v2",
    "fetch_FMI_npoigages_info",
    "fetch_non_ref_npoigages_info",
    "fetch_ref_npoigages_info",
    "fetch_waterdata_gage_info",
]
NHM_ONLY = ["fetch_nwis_gage_info", "make_HW_cal_level_files"]


@pytest.mark.parametrize("name", NHF_ONLY + NHM_ONLY)
def test_function_survived_unification(name):
    assert callable(getattr(cu, name)), f"{name} was lost"


def test_fmi_guard_is_preserved(tmp_path):
    """With neither the cache nor TableA2 present, return empty, do not raise."""
    model_dir = tmp_path / "model"
    (model_dir / "metadata").mkdir(parents=True)
    (tmp_path / "data_dependencies").mkdir()

    out = cu.fetch_FMI_npoigages_info(
        tmp_path, model_dir, pd.DataFrame({"poi_gage_id": ["12345678"]})
    )
    assert isinstance(out, pd.DataFrame)
    assert out.empty
    assert "flow_management_index" in out.columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_carried_over.py -v`
Expected: FAIL — `AttributeError` on the first missing function

- [ ] **Step 3: Write minimal implementation**

Copy the seven functions into `src/assist/common/assist_utilities.py`, unchanged.

**Add exactly TWO new module-level imports, and nothing else:**

```python
import glob
import pywatershed as pws
```

I verified the free names of all seven functions against what the module already imports.
`glob` is needed by `fetch_ref_npoigages_info` and `fetch_non_ref_npoigages_info`; `pws` by
`fetch_waterdata_gage_info` and `fetch_nwis_gage_info`. Both resolve in the pixi
environment. Do not add `shapely`'s `Point`/`LineString` — the baselines import them but
none of these seven functions use them. If you see a free-looking name `point`, it is the
parameter of a nested `def nearest_line_distance(point)` inside
`fetch_nwis_gage_info`/`fetch_waterdata_gage_info`, not a module import.

Note: importing `pywatershed` at module level is slow and prints numba JIT and mpsplines
warnings on first import. Both baselines do it this way, so keep it at module level rather
than making it function-local — matching the baselines keeps the copies verbatim.

Verify the FMI guard came across:

```bash
grep -n "skipping FMI gages" src/assist/common/assist_utilities.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_carried_over.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add -f src/assist/common/assist_utilities.py tests/unification/test_carried_over.py
git commit -m "feat: carry the one-sided assist utilities into common/

Five nhf-only functions (FMI/ref/non-ref/WaterData fetchers plus the _v2
append helper) and two nhm-only (fetch_nwis_gage_info,
make_HW_cal_level_files). Asserts the 01fc9b6 FMI guard survived."
```

---

### Task 9: Reduce both sides to shims

This is the pivot: after it, the 38 notebooks that import these modules load `common/` code.
Three things must happen together, or the tree breaks.

**1. Rename `_find_missing_gage_metadata` to `find_missing_gage_metadata`.** Task 7 gave it
a leading underscore, but it has a caller in another module, so it is not private. Rename
the `def` and nothing else.

**2. Fix the one call site that uses nhm's signature.** I classified every
`find_missing_gage_info` call in the repo: twelve use nhf's positional signature, and
exactly one uses nhm's keyword-only one —
`src/assist/nhm/nhm_hydrofabric.py:565`. Since the canonical
`find_missing_gage_info` is now nhf's, that call must switch to
`find_missing_gage_metadata`, which preserves the metadata-only return its
`.set_index("poi_gage_id").combine_first(fetched)` depends on.

**3. Replace both modules with identical shims** exporting the 15 names below. Thirteen of
them are imported by callers somewhere in the repo (`load_subdomain_config` alone in 32
files); `create_append_gages_to_param_file_v2` has no caller but is kept so the nhf
module's public surface is unchanged; `find_missing_gage_metadata` is added for the nhm
hydrofabric caller. The two private helpers (`_load_nldi_cached`,
`_translate_waterdata_columns`) are deliberately NOT exported.

**Files:**
- Modify: `src/assist/common/assist_utilities.py` (the rename only)
- Modify: `src/assist/nhm/nhm_hydrofabric.py` (import + call at ~line 565)
- Replace entirely: `src/assist/nhm/nhm_assist_utilities.py`
- Replace entirely: `src/assist/nhf/nhm_assist_utilities_v2.py`
- Test: `tests/unification/test_shims.py`

**Interfaces:**
- Consumes: the complete `assist.common.assist_utilities` from Task 8.
- Produces: both modules re-export the same 15 objects; `find_missing_gage_metadata`
  replaces `_find_missing_gage_metadata`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_shims.py
"""Both shims must expose the same objects as common/, and contain no logic."""
import inspect

import pytest

import assist.common.assist_utilities as common
import assist.nhf.nhm_assist_utilities_v2 as nhf
import assist.nhm.nhm_assist_utilities as nhm

EXPECTED = [
    "create_append_gages_to_param_file",
    "create_append_gages_to_param_file_v2",
    "delete_notebook_output_files",
    "fetch_FMI_npoigages_info",
    "fetch_non_ref_npoigages_info",
    "fetch_nwis_gage_info",
    "fetch_ref_npoigages_info",
    "fetch_waterdata_gage_info",
    "find_missing_gage_info",
    "find_missing_gage_metadata",
    "load_subdomain_config",
    "make_HW_cal_level_files",
    "make_myparam_addl_gages_param_file",
    "make_obs_plot_files",
    "make_plots_par_vals",
]


@pytest.mark.parametrize("name", EXPECTED)
def test_both_shims_export_the_same_object(name):
    assert getattr(nhm, name) is getattr(common, name), f"nhm/{name}"
    assert getattr(nhf, name) is getattr(common, name), f"nhf/{name}"


@pytest.mark.parametrize("module", [nhm, nhf])
def test_shim_defines_no_logic_of_its_own(module):
    source = open(module.__file__, encoding="utf-8").read()
    assert "def " not in source, f"{module.__name__} still defines functions"
    assert "from assist.common.assist_utilities import" in source


def test_private_helpers_are_not_exported():
    for module in (nhm, nhf):
        assert "_load_nldi_cached" not in (module.__all__ or [])
        assert "_translate_waterdata_columns" not in (module.__all__ or [])


def test_metadata_lookup_is_public_now():
    assert hasattr(common, "find_missing_gage_metadata")
    assert not hasattr(common, "_find_missing_gage_metadata")


def test_canonical_and_metadata_lookup_are_different_functions():
    """Guard against the two APIs being collapsed by mistake."""
    assert common.find_missing_gage_info is not common.find_missing_gage_metadata
    canonical = inspect.signature(common.find_missing_gage_info)
    metadata = inspect.signature(common.find_missing_gage_metadata)
    assert "gages_list" in canonical.parameters
    assert "gage_ids" in metadata.parameters


def test_nhm_hydrofabric_uses_the_metadata_lookup():
    """The one nhm-signature call site must have been migrated."""
    source = open("src/assist/nhm/nhm_hydrofabric.py", encoding="utf-8").read()
    assert "find_missing_gage_metadata" in source
    assert "find_missing_gage_info" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_shims.py -v`
Expected: FAIL — the shims still contain implementations, and
`find_missing_gage_metadata` does not exist yet

- [ ] **Step 3: Write minimal implementation**

First, in `src/assist/common/assist_utilities.py`, rename the function:

```
def _find_missing_gage_metadata(   ->   def find_missing_gage_metadata(
```

Next, in `src/assist/nhm/nhm_hydrofabric.py`, change the import (around line 9) from

```python
from assist.nhm.nhm_assist_utilities import (fetch_nwis_gage_info,
                                              find_missing_gage_info,
                                              make_HW_cal_level_files)
```

to

```python
from assist.nhm.nhm_assist_utilities import (fetch_nwis_gage_info,
                                              find_missing_gage_metadata,
                                              make_HW_cal_level_files)
```

and change the call at around line 565 from `find_missing_gage_info(` to
`find_missing_gage_metadata(`. Leave its keyword arguments exactly as they are.

Then write this exact content to BOTH `src/assist/nhm/nhm_assist_utilities.py` and
`src/assist/nhf/nhm_assist_utilities_v2.py`, replacing them completely:

```python
"""Compatibility shim. Implementation lives in assist.common.assist_utilities."""
from assist.common.assist_utilities import (
    create_append_gages_to_param_file,
    create_append_gages_to_param_file_v2,
    delete_notebook_output_files,
    fetch_FMI_npoigages_info,
    fetch_non_ref_npoigages_info,
    fetch_nwis_gage_info,
    fetch_ref_npoigages_info,
    fetch_waterdata_gage_info,
    find_missing_gage_info,
    find_missing_gage_metadata,
    load_subdomain_config,
    make_HW_cal_level_files,
    make_myparam_addl_gages_param_file,
    make_obs_plot_files,
    make_plots_par_vals,
)

__all__ = [
    "create_append_gages_to_param_file",
    "create_append_gages_to_param_file_v2",
    "delete_notebook_output_files",
    "fetch_FMI_npoigages_info",
    "fetch_non_ref_npoigages_info",
    "fetch_nwis_gage_info",
    "fetch_ref_npoigages_info",
    "fetch_waterdata_gage_info",
    "find_missing_gage_info",
    "find_missing_gage_metadata",
    "load_subdomain_config",
    "make_HW_cal_level_files",
    "make_myparam_addl_gages_param_file",
    "make_obs_plot_files",
    "make_plots_par_vals",
]
```

Keep both filenames unchanged — 38 workflow templates import them by name.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/ -v`
Expected: PASS, all tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/assist_utilities.py src/assist/nhm/nhm_assist_utilities.py \
        src/assist/nhf/nhm_assist_utilities_v2.py src/assist/nhm/nhm_hydrofabric.py
git add -f tests/unification/test_shims.py
```

### Task 10: Full verification

**Files:**
- Test: none new.

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Confirm every importer still imports**

```bash
~/.pixi/bin/pixi run --frozen python -c "
import importlib
for m in ('assist.common.assist_utilities',
          'assist.nhm.nhm_assist_utilities',
          'assist.nhf.nhm_assist_utilities_v2',
          'assist.nhf.map_template_v2',
          'assist.nhf.nhm_hydrofabric_v2',
          'assist.nhf.sf_data_retrieval_v2_1',
          'assist.nhm.map_template',
          'assist.nhm.nhm_hydrofabric',
          'assist.nhm.sf_data_retrieval'):
    importlib.import_module(m)
    print('OK', m)
"
```

Expected: nine `OK` lines. These are the modules that import this concern.

- [ ] **Step 2: Run the whole suite**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/ -q`
Expected: the pre-existing 85 passed / 9 subtests, plus the new unification tests. **Zero failures.**

- [ ] **Step 3: Smoke-check a notebook that uses this concern**

```bash
cd /Users/lludden/Documents/GitHub/nhm-assist-gitlab/nhf_assist/nb_run
export NHM_BATCH_MODE=1
~/.pixi/bin/pixi run --frozen python -m nbconvert --to notebook --execute --inplace \
    --ExecutePreprocessor.timeout=3600 0_workspace_setup.ipynb
```

Expected: exits 0. Notebook 0 calls `load_subdomain_config` and writes
`subdomain_config.yaml`, so it exercises Task 3 directly.

Note: `nhf_assist/nb_run/` is a scratch copy so the tracked notebooks in
`nhf_assist/notebooks/` are not modified by execution. If it is absent, recreate
it and back up the config first, because notebook 0 overwrites it:

```bash
cd /Users/lludden/Documents/GitHub/nhm-assist-gitlab
cp -p nhf_assist/subdomain_config.yaml /tmp/subdomain_config.yaml.bak
mkdir -p nhf_assist/nb_run
cp nhf_assist/notebooks/0_workspace_setup.ipynb nhf_assist/nb_run/
```

`nb_run` must sit inside `nhf_assist/` because notebook 0 derives `root_dir` by
splitting the working directory on the string `"nhf_assist"`.

- [ ] **Step 4: Commit any fixes, then tag the concern done**

```bash
git commit -am "fix: address fallout from assist_utilities unification" || true
```

---

## Remaining concerns

Each gets its own plan, written after this one lands, in dependency order:

1. `hydrofabric` — 6 shared, all 6 differ; `create_hru_gdf` and
   `create_segment_gdf` are the clearest identifier-adapter cases
2. `sf_data_retrieval` — 10 shared, 6 differ; nhm-only `_safe_clip_mask` and
   `_should_retry_waterdata` must survive; delete the dead
   `sf_data_retrieval_v2.py`
3. `map_template` — 21 shared, 17 differ, 8 nhf-only; highest risk
4. `display_controls` — fold nhf's 9 widget functions into the existing
   `common/display_controls.py`, then shim
