# Helper Unification, Concern 2: `hydrofabric` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse `src/assist/nhm/nhm_hydrofabric.py` (838L) and `src/assist/nhf/nhm_hydrofabric_v2.py` (930L) into a single `src/assist/common/hydrofabric.py`, reduce both originals to re-export shims, close the column-naming question deferred from concern 1, delete `find_missing_gage_metadata`, and fix review finding I2.

**Architecture:** nhf's implementations already carry the GFv1.1-vs-GFv2 tolerance that nhm's lack, so nhf is the source for every shared function rather than a per-function judgement call. Verification is differential against the pre-unification baselines using the harness built in concern 1, exercised against both a GFv1.1 model and a GFv2 model so fabric-specific breakage cannot hide.

**Tech Stack:** Python 3.11, pytest, pandas / geopandas, pyPRMS, pixi (`pixi run --frozen`).

**Spec:** `docs/superpowers/specs/2026-08-30-helper-unification-design.md`

## Global Constraints

- Branch: `restructure/unify-remaining-helpers`. Baseline commit for all differential tests: `b9ae03d` (the tip of `restructure/helper-unification-2`, where concern 1 finished).
- Run everything through pixi: `~/.pixi/bin/pixi run --frozen python -m pytest ...`. `pixi` is NOT on PATH; use the absolute path.
- Canonical identifier names inside `common/`: `nhm_id`, `nhm_seg`, `poi_gage_id`. `poi_id` is retired.
- WaterData is the canonical terminology (spec decision 7). NWIS spellings survive only as back-filled aliases and legacy filenames.
- When the two sides differ, nhf wins (spec decision 8).
- `tests/` and `docs/` are gitignored (`.gitignore:487`); new files there need `git add -f`.
- The nhf shim keeps the filename `nhm_hydrofabric_v2.py` (16 importers); the nhm shim keeps `nhm_hydrofabric.py` (6 importers). Renaming either breaks callers.
- Never delete `metadata/fmi_gages_info.csv` (spec decision 5).
- **Claude never commits.** Every task ends staged-but-uncommitted; the user reviews and commits by hand.
- Full suite must stay green. Baseline at plan time: 152 passed, 9 subtests.

## Why nhf is the source for every shared function

Measured, not assumed. The two fabrics ship different geopackage columns:

| Layer | GFv1.1 (`Walla_Walla`) | GFv2 (`UmatillaRiver`) |
| --- | --- | --- |
| `nhru` | `nhm_id`, `model_hru_idx` | `hru_id`, `hru_segment`, `nhm_hru_seg`, `nhm_id`, `model_hru_idx`, `vpu_agg_id` |
| `nsegment` | `nhm_seg`, `model_seg_idx` | `nhm_seg_id`, `segment_id`, `to_nhm_seg`, `to_segment`, `model_seg_idx`, `vpu_agg_id` |

Consequences:

- nhf's `create_hru_gdf` already falls back when `hru_id` is absent
  (`nhm_hydrofabric_v2.py:97-103`: "v1.1 uses 'model_idx' or 'model_hru_idx' where v2 uses
  'hru_id' — they are the same value"). It works on both fabrics.
- nhf's `create_segment_gdf` renames `nhm_seg_id` to `nhm_seg` before use, so it works on
  both.
- nhm's `create_segment_gdf` does `set_index("nhm_seg")` and `merge(on="nhm_seg")` with no
  fallback. GFv2 geopackages have no `nhm_seg` column, so **nhm's version cannot read a GFv2
  model at all.**

So the column-naming question deferred from concern 1 resolves without a new adapter: the
tolerance already exists in nhf's code. Do not add a `resolve_segment_column` helper. Task 1
proves this empirically before anything is moved.

## File structure

| File | Responsibility |
| --- | --- |
| `src/assist/common/hydrofabric.py` | new; the unified implementation, 8 functions |
| `src/assist/nhm/nhm_hydrofabric.py` | reduced to a re-export shim |
| `src/assist/nhf/nhm_hydrofabric_v2.py` | reduced to a re-export shim |
| `src/assist/common/assist_utilities.py` | modified twice: I2 config fail-fast, and deleting `find_missing_gage_metadata` |
| `tests/unification/fabrics.py` | new; the two-fabric fixture pair used by every task here |
| `tests/unification/test_fabric_matrix.py` | new; the compatibility matrix from Task 1 |
| `tests/unification/test_config_required_keys.py` | new; I2 |
| `tests/unification/test_hydrofabric_*.py` | new; one per unification task |

## Function inventory

Six shared, all six differing. One function unique to each side.

| Function | nhm | nhf | changed lines | nature |
| --- | --- | --- | --- | --- |
| `read_gages_file` | 109 | 109 | 4 | logic only, nearly identical |
| `make_hf_map_elements` | 127 | 129 | 48 | logic only; deferred to Task 6 for its dependencies |
| `create_hru_gdf` | 135 | 178 | 65 | fabric tolerance + ids |
| `create_segment_gdf` | 89 | 134 | 67 | fabric tolerance + ids |
| `create_poi_df` | 162 | 122 | 160 | ids + logic |
| `create_default_gages_file` | 173 | 121 | 178 | ids + logic |
| `_load_byhwobs_cal_gages` | 34 | — | — | nhm only |
| `evaluate_and_fix_nhru_geometry` | — | 93 | — | nhf only |

---

### Task 1: Two-fabric fixtures and the compatibility matrix

Establishes the empirical foundation. No production code changes. This task exists because
concern 1's two Critical bugs both came from a synthesized function with no differential
test; here the differential apparatus lands first.

**Files:**
- Create: `tests/unification/fabrics.py`
- Test: `tests/unification/test_fabric_matrix.py`

**Interfaces:**
- Consumes: `load_module_from_git`, `BASELINE_REV`, `MODELS` from `tests/unification/harness.py`.
- Produces:
  - `FABRICS: dict[str, pathlib.Path]` — `{"gfv1_1": <Walla_Walla>, "gfv2": <UmatillaRiver>}`
  - `gpkg_columns(model_dir: pathlib.Path, layer: str) -> set[str]`
  - `HYDROFABRIC_BASELINE: str` — the string `"b9ae03d"`
  - `baseline_function_source(repo_path: str, name: str, rev: str = HYDROFABRIC_BASELINE) -> str`
  - `baseline_function_ast(repo_path: str, name: str, rev: str = HYDROFABRIC_BASELINE) -> str`
  - `current_function_ast(fn) -> str`

  The three `*_ast` / `*_source` helpers parse baseline source rather than importing it.
  Every AST comparison in this plan uses them, and **no task may use
  `load_module_from_git` on `src/assist/nhm/nhm_hydrofabric.py`**: importing that module at
  this baseline pulls in `find_missing_gage_metadata`, which Task 7 deletes, so an
  import-based test would pass early and then break permanently.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_fabric_matrix.py
"""Which hydrofabric implementation can read which fabric?

This matrix is the evidence for the plan's central claim: nhf's implementations
tolerate both fabrics and nhm's do not. If it ever stops holding, the
unification direction for this concern needs revisiting.
"""
import pytest

from tests.unification.fabrics import FABRICS, gpkg_columns

NHRU_V1_ONLY = {"nhm_id", "model_hru_idx"}
NSEG_V1 = {"nhm_seg", "model_seg_idx"}
NSEG_V2 = {"nhm_seg_id", "segment_id"}


def _skip_if_missing(key):
    if not FABRICS[key].exists():
        pytest.skip(f"{key} model not present at {FABRICS[key]}")


def test_gfv1_1_nsegment_has_nhm_seg_and_not_nhm_seg_id():
    _skip_if_missing("gfv1_1")
    cols = gpkg_columns(FABRICS["gfv1_1"], "nsegment")
    assert "nhm_seg" in cols
    assert "nhm_seg_id" not in cols


def test_gfv2_nsegment_has_nhm_seg_id_and_not_nhm_seg():
    _skip_if_missing("gfv2")
    cols = gpkg_columns(FABRICS["gfv2"], "nsegment")
    assert "nhm_seg_id" in cols
    assert "nhm_seg" not in cols, (
        "if GFv2 gained a plain nhm_seg column, nhf's rename is now a no-op "
        "and this plan's reasoning should be rechecked"
    )


def test_gfv1_1_nhru_lacks_the_v2_id_columns():
    _skip_if_missing("gfv1_1")
    cols = gpkg_columns(FABRICS["gfv1_1"], "nhru")
    assert "nhm_id" in cols
    assert "hru_id" not in cols
    assert "hru_segment" not in cols


def test_gfv2_nhru_has_both_id_families():
    _skip_if_missing("gfv2")
    cols = gpkg_columns(FABRICS["gfv2"], "nhru")
    assert {"nhm_id", "hru_id", "hru_segment"} <= cols


def test_nhf_create_hru_gdf_has_a_fabric_fallback_and_nhm_does_not():
    """Source-level guard on the claim that drives this plan's direction."""
    from tests.unification.fabrics import NHF_HF, NHM_HF, baseline_function_source

    nhf_src = baseline_function_source(NHF_HF, "create_hru_gdf")
    nhm_src = baseline_function_source(NHM_HF, "create_hru_gdf")
    assert '"hru_id" not in hru_gdb.columns' in nhf_src
    assert '"hru_id" not in' not in nhm_src


def test_nhm_create_segment_gdf_assumes_nhm_seg_exists():
    """nhm indexes on nhm_seg with no fallback, so it cannot read a GFv2 model."""
    from tests.unification.fabrics import NHM_HF, baseline_function_source

    src = baseline_function_source(NHM_HF, "create_segment_gdf")
    assert '"nhm_seg"' in src
    assert "nhm_seg_id" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_fabric_matrix.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.unification.fabrics'`

- [ ] **Step 3: Write minimal implementation**

```python
# tests/unification/fabrics.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_fabric_matrix.py -v`
Expected: PASS, 6 tests. Tests skip cleanly if a model directory is absent.

- [ ] **Step 5: Stage (do not commit)**

```bash
git add -f tests/unification/fabrics.py tests/unification/test_fabric_matrix.py
```

---

### Task 2: Review finding I2 — config fail-fast

Folded in from concern 1's final review. `load_subdomain_config` currently turns a missing
key into `None` via `raw.get(key)`, so a bad config surfaces many cells later as
`TypeError: unsupported operand type(s) for /: 'NoneType' and 'str'`. There is a live
exposure at `src/workflow_templates/pest/00_Subset_NHM_baselines_gfv2.py:145`.

The required/optional split is evidence-based, not a guess. I parsed every `config[...]` and
`config.get(...)` read in `src/`: **28 keys are read, and not one is read defensively.**
There is no optional-key category in practice, and both pre-unification baselines
subscripted every key. So the tolerance was a regression.

One genuine exception: `resource_gages_file` is read in 7 places but exists only in
nhf-shaped configs, so an nhm-shaped config legitimately lacks it. It stays tolerated, and
the tolerance becomes explicit rather than incidental.

**Files:**
- Modify: `src/assist/common/assist_utilities.py`
- Modify: `tests/unification/fabrics.py` (add `COMPLETE_CONFIG`)
- Modify: `tests/unification/test_config_schema.py` (delete one test; point `BASE` at `COMPLETE_CONFIG`)
- Test: `tests/unification/test_config_required_keys.py`

**Interfaces:**
- Consumes: `load_subdomain_config` from `assist.common.assist_utilities`.
- Produces:
  - `REQUIRED_CONFIG_KEYS: frozenset[str]`
  - `OPTIONAL_CONFIG_KEYS: frozenset[str]` — currently `{"resource_gages_file"}`
  - `load_subdomain_config` raises `KeyError` naming every missing required key

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_config_required_keys.py
"""A malformed config must fail loudly in the loader, not silently downstream."""
import pathlib as pl

import pytest
import yaml

from assist.common.assist_utilities import (
    OPTIONAL_CONFIG_KEYS,
    REQUIRED_CONFIG_KEYS,
    load_subdomain_config,
)

from tests.unification.fabrics import COMPLETE_CONFIG


def _write(tmp_path: pl.Path, cfg: dict) -> pl.Path:
    (tmp_path / "subdomain_config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return tmp_path


def test_a_complete_config_loads():
    assert REQUIRED_CONFIG_KEYS
    assert "resource_gages_file" in OPTIONAL_CONFIG_KEYS


def test_complete_config_round_trips(tmp_path):
    cfg = load_subdomain_config(_write(tmp_path, COMPLETE_CONFIG))
    assert cfg["subdomain"] == "TestBasin"
    assert isinstance(cfg["out_dir"], pl.Path)


def test_missing_required_key_raises_naming_it(tmp_path):
    broken = {k: v for k, v in COMPLETE_CONFIG.items() if k != "out_dir"}
    with pytest.raises(KeyError, match="out_dir"):
        load_subdomain_config(_write(tmp_path, broken))


def test_error_names_every_missing_key_at_once(tmp_path):
    broken = {k: v for k, v in COMPLETE_CONFIG.items()
              if k not in ("out_dir", "nc_files_dir", "html_maps_dir")}
    with pytest.raises(KeyError) as exc:
        load_subdomain_config(_write(tmp_path, broken))
    message = str(exc.value)
    for key in ("out_dir", "nc_files_dir", "html_maps_dir"):
        assert key in message


def test_optional_key_absent_is_tolerated(tmp_path):
    cfg = load_subdomain_config(_write(tmp_path, COMPLETE_CONFIG))
    assert cfg["resource_gages_file"] is None


def test_waterdata_only_config_also_loads(tmp_path):
    cfg = dict(COMPLETE_CONFIG)
    del cfg["nwis_gages_file"], cfg["nwis_gage_nobs_min"]
    cfg["waterdata_gages_file"] = "/tmp/m/WaterDataGages.csv"
    cfg["waterdata_gage_nobs_min"] = 400
    loaded = load_subdomain_config(_write(tmp_path, cfg))
    assert loaded["nwis_gages_file"] == pl.Path("/tmp/m/WaterDataGages.csv")
    assert loaded["waterdata_gage_nobs_min"] == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_config_required_keys.py -v`
Expected: FAIL — `ImportError: cannot import name 'REQUIRED_CONFIG_KEYS'`

- [ ] **Step 3: Write minimal implementation**

In `src/assist/common/assist_utilities.py`, add the two sets near `CONFIG_KEY_ALIASES`:

```python
# Every key some consumer reads. Derived by parsing all config[...] and
# config.get(...) reads under src/: 28 keys, none read defensively, so a missing
# one is a broken workspace rather than a soft default. Both pre-unification
# baselines subscripted each of these directly.
REQUIRED_CONFIG_KEYS = frozenset({
    "Folium_maps_dir", "GIS_format", "NHM_dir", "control_file_name",
    "default_gages_file", "end_date", "gages_file", "html_maps_dir",
    "html_plots_dir", "model_dir", "nc_files_dir", "nhru_nmonths_params",
    "nhru_params", "notebook_output_dir", "out_dir", "output_netcdf_filename",
    "param_file", "param_filename", "selected_output_variables", "start_date",
    "subdomain", "water_years", "waterdata_gage_nobs_min",
    "waterdata_gages_file", "workspace_txt",
})

# Present only in nhf-shaped configs; nhm-shaped ones legitimately omit it.
OPTIONAL_CONFIG_KEYS = frozenset({"resource_gages_file"})
```

Then, in `load_subdomain_config`, after the alias back-fill and before building the
returned dict, add the check:

```python
    missing = sorted(REQUIRED_CONFIG_KEYS - set(raw))
    if missing:
        raise KeyError(
            f"{config_path} is missing required key(s): {', '.join(missing)}. "
            "Re-run 0_workspace_setup.ipynb for this model to regenerate it."
        )
```

Next, add the shared complete-config fixture to `tests/unification/fabrics.py` so both
test files use one definition:

```python
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
```

Finally, fix `tests/unification/test_config_schema.py`. **Its `BASE` fixture supplies only
8 of the 25 required keys, so adding the fail-fast breaks 6 of its 7 tests, not just the
one being removed.** I verified this by parsing the file. Two changes there:

1. Delete `test_path_keys_absent_from_yaml_become_None` — it pinned the behaviour this task
   removes.
2. Replace the module-level `BASE = {...}` dict with
   `from tests.unification.fabrics import COMPLETE_CONFIG as BASE`, so every remaining test
   builds on a complete config. Do not otherwise change those tests: they still override or
   add keys on top of `BASE`, and must keep passing unmodified.

`test_matches_the_baseline_nhm_loader_on_the_real_config` reads the repository's own
`./subdomain_config.yaml` rather than `BASE`, so it is unaffected.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/ -v`
Expected: PASS. The deleted test is gone; the remaining config tests still pass.

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/assist_utilities.py
git add -f tests/unification/test_config_required_keys.py tests/unification/test_config_schema.py
```

---

### Task 3: `common/hydrofabric.py` with `read_gages_file`

Starts the new module with the single lowest-risk function: `read_gages_file`, which differs
by only 4 lines between the two sides. From nhf per spec decision 8.

`make_hf_map_elements` was originally paired here but has moved to Task 6. Its free names are
`create_hru_gdf`, `create_poi_df`, `create_segment_gdf`, `fetch_waterdata_gage_info` and
`read_gages_file` — three of which Tasks 4 and 5 add. Placing it here would create a module
whose function is uncallable until Task 5 while its AST test passed, so each task would no
longer be a safe stopping point.

**Files:**
- Create: `src/assist/common/hydrofabric.py`
- Test: `tests/unification/test_hydrofabric_basics.py`

**Interfaces:**
- Consumes: harness and fabrics modules from Task 1.
- Produces, with the signature identical to its nhf original: `read_gages_file(...)`.
  Its only free names are `np` and `pd`, so the new module needs exactly
  `import numpy as np` and `import pandas as pd`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_hydrofabric_basics.py
"""The two low-divergence hydrofabric functions, taken verbatim from nhf."""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHF_PATH = "src/assist/nhf/nhm_hydrofabric_v2.py"
FROM_NHF = ["read_gages_file"]


@pytest.fixture(scope="module")
def nhf_baseline():
    return load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_hf_basics")


def _ast_of(fn):
    return ast.dump(ast.parse(inspect.getsource(fn)))


@pytest.mark.parametrize("name", FROM_NHF)
def test_copy_is_ast_identical_to_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert _ast_of(getattr(common, name)) == _ast_of(getattr(nhf_baseline, name))


@pytest.mark.parametrize("name", FROM_NHF)
def test_signature_matches_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert inspect.signature(getattr(common, name)) == inspect.signature(
        getattr(nhf_baseline, name)
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_basics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assist.common.hydrofabric'`

- [ ] **Step 3: Write minimal implementation**

Create `src/assist/common/hydrofabric.py` with this header, then append `read_gages_file`
extracted verbatim from `src/assist/nhf/nhm_hydrofabric_v2.py`:

```python
"""Shared hydrofabric helpers for the nhm and nhf workflows.

Unified from src/assist/nhm/nhm_hydrofabric.py and
src/assist/nhf/nhm_hydrofabric_v2.py. See
docs/superpowers/specs/2026-08-30-helper-unification-design.md.

Implementations come from the nhf side, which already tolerates both the GFv1.1
and GFv2 geopackage column layouts; the nhm versions assume GFv1.1 columns and
cannot read a GFv2 model.
"""
```

Use a script so the copies are exact rather than retyped:

```python
import ast, pathlib as pl

src = pl.Path("src/assist/nhf/nhm_hydrofabric_v2.py").read_text(encoding="utf-8")
tree = ast.parse(src)
chunks = []
for name in ("read_gages_file",):
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    chunks.append(ast.get_source_segment(src, node))

dest = pl.Path("src/assist/common/hydrofabric.py")
dest.write_text(
    dest.read_text(encoding="utf-8").rstrip("\n") + "\n\n\n"
    + "\n\n\n".join(chunks) + "\n",
    encoding="utf-8",
)
```

Then add exactly two module-level imports, `import numpy as np` and `import pandas as pd`.
I verified those are the function's only free names. Do not copy nhf's whole import block —
it contains `geopandas`, `xarray`, `pyPRMS`, `dotenv` and others this function does not use.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_basics.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/hydrofabric.py
git add -f tests/unification/test_hydrofabric_basics.py
```

---

### Task 4: `create_hru_gdf` and `create_segment_gdf` — the fabric-tolerant pair

These two are why nhf is the source. Both are copied verbatim from nhf, and the tests assert
the tolerance survives, because losing it silently would make GFv1.1 models unreadable.

**A pre-existing bug you must copy, not fix.** nhf's `create_hru_gdf` references a name
`same` at two places inside its mismatch branch:

```python
diff = df_by_nhm_id.loc[~same, ["hru_id"]].join(
    hru_gdb.loc[~same, ["hru_id"]],
```

`same` is never assigned anywhere in that function — I checked the full AST. nhm's version
does not reference it at all, so it is nhf-only. The branch is reached only when the GIS
`nhm_id` order disagrees with `myparam.param`, so today a data inconsistency raises
`NameError: name 'same' is not defined` instead of printing the intended comparison.

**Copy it as-is anyway.** This concern is a unification, not a bug hunt, and the AST-identity
test is what makes the move provably behaviour-preserving. Fixing a body while claiming a
verbatim copy would destroy that guarantee for every other function too. The bug is recorded
for a separate follow-up; do not repair it here, and do not add a `same = ...` line.

**Files:**
- Modify: `src/assist/common/hydrofabric.py`
- Test: `tests/unification/test_hydrofabric_gdfs.py`

**Interfaces:**
- Consumes: the module from Task 3; `FABRICS` from Task 1.
- Produces, verbatim from nhf: `create_hru_gdf(...)`, `create_segment_gdf(...)`
- Adds exactly three module-level imports: `import geopandas as gpd`,
  `from pyPRMS import ParameterFile`, `from pyPRMS.metadata.metadata import MetaData`.
  Verified by free-name analysis; `np` and `pd` are already imported by Task 3. Do not add
  anything for the undefined `same` — see the note above.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_hydrofabric_gdfs.py
"""The fabric-tolerance in these two functions is the point of taking nhf's side."""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHF_PATH = "src/assist/nhf/nhm_hydrofabric_v2.py"


@pytest.fixture(scope="module")
def nhf_baseline():
    return load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_hf_gdfs")


def _ast_of(fn):
    return ast.dump(ast.parse(inspect.getsource(fn)))


@pytest.mark.parametrize("name", ["create_hru_gdf", "create_segment_gdf"])
def test_copy_is_ast_identical_to_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert _ast_of(getattr(common, name)) == _ast_of(getattr(nhf_baseline, name))


def test_hru_gdf_keeps_the_missing_hru_id_fallback():
    """GFv1.1 geopackages have no hru_id; without this fallback they break."""
    import assist.common.hydrofabric as common

    source = inspect.getsource(common.create_hru_gdf)
    assert '"hru_id" not in hru_gdb.columns' in source
    assert "model_hru_idx" in source


def test_segment_gdf_keeps_the_nhm_seg_id_rename():
    """GFv2 geopackages have nhm_seg_id, not nhm_seg; the rename bridges them."""
    import assist.common.hydrofabric as common

    source = inspect.getsource(common.create_segment_gdf)
    assert "nhm_seg_id" in source
    assert "nhm_seg" in source


def test_neither_function_hardcodes_a_single_fabric_only_column():
    """A bare set_index on nhm_seg with no fallback is the nhm bug we are avoiding."""
    import assist.common.hydrofabric as common

    seg = inspect.getsource(common.create_segment_gdf)
    assert seg.count("nhm_seg_id") >= 1, (
        "the rename that makes GFv2 readable has gone missing"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_gdfs.py -v`
Expected: FAIL — `AttributeError: module 'assist.common.hydrofabric' has no attribute 'create_hru_gdf'`

- [ ] **Step 3: Write minimal implementation**

Append `create_hru_gdf` and `create_segment_gdf` to `src/assist/common/hydrofabric.py`,
extracted verbatim from `src/assist/nhf/nhm_hydrofabric_v2.py` with the same
`ast.get_source_segment` script shape used in Task 3. Add only the imports these two add,
determined by free-name analysis.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_gdfs.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/hydrofabric.py
git add -f tests/unification/test_hydrofabric_gdfs.py
```

---

### Task 5: `create_poi_df` and `create_default_gages_file`

The two heaviest divergences in this concern (160 and 178 changed lines). Both from nhf.
`create_default_gages_file` is also where the nhm side calls `find_missing_gage_metadata`,
so read Task 7 before starting: the nhf version calls the canonical
`find_missing_gage_info`, which is what allows Task 7 to delete the private one.

**Files:**
- Modify: `src/assist/common/hydrofabric.py`
- Test: `tests/unification/test_hydrofabric_poi.py`

**Interfaces:**
- Consumes: the module from Task 4.
- Produces, verbatim from nhf: `create_poi_df(...)`, `create_default_gages_file(...)`
- Adds exactly two module-level imports, verified by free-name analysis:

```python
import xarray as xr
from assist.common.assist_utilities import find_missing_gage_info
```

  The second one is layering-sensitive. `find_missing_gage_info` is *defined* in
  `assist.common.assist_utilities`; `assist.nhf.nhm_assist_utilities_v2` is only a shim that
  re-exports it. Importing from the shim would make `common/` depend on a workflow package —
  the exact inversion caught in concern 1 — and risks a circular import once Task 7 makes the
  hydrofabric modules shims too.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_hydrofabric_poi.py
"""The two heaviest-divergence functions, taken verbatim from nhf."""
import ast
import inspect

import pytest

from tests.unification.harness import BASELINE_REV, load_module_from_git

NHF_PATH = "src/assist/nhf/nhm_hydrofabric_v2.py"
FROM_NHF = ["create_poi_df", "create_default_gages_file"]


@pytest.fixture(scope="module")
def nhf_baseline():
    return load_module_from_git(BASELINE_REV, NHF_PATH, "baseline_nhf_hf_poi")


def _ast_of(fn):
    return ast.dump(ast.parse(inspect.getsource(fn)))


@pytest.mark.parametrize("name", FROM_NHF)
def test_copy_is_ast_identical_to_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert _ast_of(getattr(common, name)) == _ast_of(getattr(nhf_baseline, name))


@pytest.mark.parametrize("name", FROM_NHF)
def test_signature_matches_nhf(name, nhf_baseline):
    import assist.common.hydrofabric as common

    assert inspect.signature(getattr(common, name)) == inspect.signature(
        getattr(nhf_baseline, name)
    )


def test_default_gages_uses_the_canonical_gage_lookup():
    """nhf calls find_missing_gage_info; that is what lets Task 7 delete the
    private find_missing_gage_metadata carried over from concern 1."""
    import assist.common.hydrofabric as common

    source = inspect.getsource(common.create_default_gages_file)
    assert "find_missing_gage_info" in source
    assert "find_missing_gage_metadata" not in source


def test_poi_df_uses_the_canonical_gage_id_column():
    import assist.common.hydrofabric as common

    source = inspect.getsource(common.create_poi_df)
    assert "poi_gage_id" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_poi.py -v`
Expected: FAIL — `AttributeError` on `create_poi_df`

- [ ] **Step 3: Write minimal implementation**

Append both functions verbatim from nhf using the same extraction script shape. Their
`find_missing_gage_info` and `fetch_waterdata_gage_info` references must resolve to
`assist.common.assist_utilities`, so import them from there — not from
`assist.nhf.nhm_assist_utilities_v2`, which is only a shim over the same objects and would
reintroduce the layering inversion found in concern 1.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_poi.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/hydrofabric.py
git add -f tests/unification/test_hydrofabric_poi.py
```

---

### Task 6: `make_hf_map_elements` and the two one-sided functions

Three functions. `make_hf_map_elements` lands here rather than in Task 3 because it calls
`create_hru_gdf`, `create_poi_df` and `create_segment_gdf`, all of which exist only after
Task 5. It also calls `fetch_waterdata_gage_info`, which lives in
`assist.common.assist_utilities` — import it from there, not from the nhf shim.

`evaluate_and_fix_nhru_geometry` exists only in nhf (93 lines); `_load_byhwobs_cal_gages`
only in nhm (34 lines). Both must survive the shim swap.

**Files:**
- Modify: `src/assist/common/hydrofabric.py`
- Test: `tests/unification/test_hydrofabric_carried_over.py`

**Interfaces:**
- Consumes: the module from Task 5, and `fetch_waterdata_gage_info` from
  `assist.common.assist_utilities`.
- Produces: `make_hf_map_elements(...)` and `evaluate_and_fix_nhru_geometry(...)` from nhf,
  `_load_byhwobs_cal_gages(...)` from nhm
- Adds exactly ONE module-level import, verified by free-name analysis:

```python
from assist.common.assist_utilities import fetch_waterdata_gage_info
```

  Import it from `assist.common.assist_utilities`, where it is defined — never from
  `assist.nhf.nhm_assist_utilities_v2`, which is a shim.

  Two notes on what NOT to add. `evaluate_and_fix_nhru_geometry` carries its own
  function-local imports (`geopandas as gpd`, `numpy as np`,
  `from shapely import get_coordinates, make_valid`, `from pathlib import Path`) — leave them
  inside the body, since hoisting them would break the verbatim copy. And if a free-name scan
  reports an undefined `g`, that is a false positive: `g` is the parameter of a lambda at
  `lambda g: make_valid(g, ...)`. No import is needed for it.
  `_load_byhwobs_cal_gages` needs nothing new.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_hydrofabric_carried_over.py
"""Functions unique to one side must survive unification."""
import inspect

from tests.unification.fabrics import (
    NHF_HF,
    NHM_HF,
    baseline_function_ast,
    current_function_ast,
)


def test_nhf_only_geometry_fixer_survived():
    import assist.common.hydrofabric as common

    assert current_function_ast(common.evaluate_and_fix_nhru_geometry) == (
        baseline_function_ast(NHF_HF, "evaluate_and_fix_nhru_geometry")
    )


def test_nhm_only_cal_gages_loader_survived():
    """Parsed, not imported: nhm_hydrofabric at this baseline imports
    find_missing_gage_metadata, which Task 7 deletes."""
    import assist.common.hydrofabric as common

    assert current_function_ast(common._load_byhwobs_cal_gages) == (
        baseline_function_ast(NHM_HF, "_load_byhwobs_cal_gages")
    )


def test_geometry_fixer_defaults_to_the_nhru_layer():
    import assist.common.hydrofabric as common

    params = inspect.signature(common.evaluate_and_fix_nhru_geometry).parameters
    assert params["layer"].default == "nhru"
    assert params["fix"].default is True


def test_map_elements_survived_and_is_verbatim_nhf():
    import assist.common.hydrofabric as common

    assert current_function_ast(common.make_hf_map_elements) == (
        baseline_function_ast(NHF_HF, "make_hf_map_elements")
    )


def test_map_elements_dependencies_all_resolve():
    """It calls three functions added in Tasks 4-5 plus one from assist_utilities.
    This is why it lands here and not in Task 3."""
    import assist.common.hydrofabric as common

    for name in ("create_hru_gdf", "create_poi_df", "create_segment_gdf",
                 "read_gages_file"):
        assert callable(getattr(common, name)), f"{name} missing"
    source = inspect.getsource(common)
    assert "from assist.common.assist_utilities import" in source
    assert "assist.nhf.nhm_assist_utilities_v2" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_carried_over.py -v`
Expected: FAIL — `AttributeError` on `evaluate_and_fix_nhru_geometry`

- [ ] **Step 3: Write minimal implementation**

Append all three functions verbatim, each from its own source module, using the extraction
script. `make_hf_map_elements` and `evaluate_and_fix_nhru_geometry` come from
`src/assist/nhf/nhm_hydrofabric_v2.py`; `_load_byhwobs_cal_gages` from
`src/assist/nhm/nhm_hydrofabric.py`. Add only the imports they need — and import
`fetch_waterdata_gage_info` from `assist.common.assist_utilities`, never from the nhf shim,
which would recreate the layering inversion found in concern 1.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_carried_over.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/hydrofabric.py
git add -f tests/unification/test_hydrofabric_carried_over.py
```

---

### Task 7: Shims, and delete `find_missing_gage_metadata`

The pivot. Three coupled changes, as in concern 1's Task 9.

**1. Enumerate the export list from real callers.** Before writing the shims, parse every
`.py` under `src/` for names imported from `assist.nhm.nhm_hydrofabric` and
`assist.nhf.nhm_hydrofabric_v2`, and export exactly that union plus the two one-sided
functions. Do not guess the list; concern 1's shim list was wrong twice before it was
derived this way.

**2. Migrate the last `find_missing_gage_metadata` caller and delete the function.**
Concern 1 left `find_missing_gage_metadata` in `common/assist_utilities.py` with a
`REMOVE WHEN` marker, kept alive solely by
`src/assist/nhm/nhm_hydrofabric.py:565`. That file becomes a shim in this task, and the
unified `create_default_gages_file` comes from nhf, which calls the canonical
`find_missing_gage_info`. So the private function has no caller left: delete it from
`common/assist_utilities.py`, drop it from both `assist_utilities` shims' export lists
(18 names down to 17), and update `tests/unification/test_shims.py` accordingly.

**3. Replace both hydrofabric modules with identical shims** over
`assist.common.hydrofabric`, keeping both filenames.

**Files:**
- Modify: `src/assist/common/assist_utilities.py` (delete the function)
- Modify: `src/assist/nhm/nhm_assist_utilities.py`, `src/assist/nhf/nhm_assist_utilities_v2.py` (drop one export)
- Replace entirely: `src/assist/nhm/nhm_hydrofabric.py`, `src/assist/nhf/nhm_hydrofabric_v2.py`
- Modify: `tests/unification/test_shims.py`, `tests/unification/test_find_missing_gage_info.py`,
  `tests/test_multi_model_workspace.py`
- Delete: `tests/test_nhm_find_missing_gage_info.py` (all 8 tests target the removed function)
- Test: `tests/unification/test_hydrofabric_shims.py`

**Interfaces:**
- Consumes: the complete `assist.common.hydrofabric` from Task 6.
- Produces: both hydrofabric modules re-export the same objects; `find_missing_gage_metadata` no longer exists anywhere.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_hydrofabric_shims.py
"""Both hydrofabric shims re-export common/, and the private gage lookup is gone."""
import ast
import pathlib as pl

import pytest

import assist.common.assist_utilities as cu
import assist.common.hydrofabric as common
import assist.nhf.nhm_hydrofabric_v2 as nhf
import assist.nhm.nhm_hydrofabric as nhm

EXPECTED_AT_LEAST = [
    "create_default_gages_file",
    "create_hru_gdf",
    "create_poi_df",
    "create_segment_gdf",
    "evaluate_and_fix_nhru_geometry",
    "make_hf_map_elements",
    "read_gages_file",
]


@pytest.mark.parametrize("name", EXPECTED_AT_LEAST)
def test_both_shims_export_the_same_object(name):
    assert getattr(nhm, name) is getattr(common, name), f"nhm/{name}"
    assert getattr(nhf, name) is getattr(common, name), f"nhf/{name}"


@pytest.mark.parametrize("module", [nhm, nhf])
def test_shim_defines_no_logic(module):
    source = pl.Path(module.__file__).read_text(encoding="utf-8")
    assert "def " not in source
    assert "from assist.common.hydrofabric import" in source


def test_private_gage_lookup_is_gone():
    """Its only caller was nhm_hydrofabric, which is now a shim."""
    assert not hasattr(cu, "find_missing_gage_metadata")
    assert not hasattr(cu, "_find_missing_gage_metadata")


def test_no_source_file_still_references_it():
    hits = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        if "find_missing_gage_metadata" in path.read_text(encoding="utf-8", errors="ignore"):
            hits.append(str(path))
    assert hits == [], f"still referenced in {hits}"


def test_canonical_gage_lookup_still_present():
    assert callable(cu.find_missing_gage_info)


def test_shims_are_byte_identical():
    a = pl.Path(nhm.__file__).read_text(encoding="utf-8")
    b = pl.Path(nhf.__file__).read_text(encoding="utf-8")
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_hydrofabric_shims.py -v`
Expected: FAIL — the modules still contain implementations and `find_missing_gage_metadata` still exists

- [ ] **Step 3: Write minimal implementation**

First derive the export list:

```bash
~/.pixi/bin/pixi run --frozen python - <<'PY'
import ast, pathlib as pl
TARGETS = {"assist.nhm.nhm_hydrofabric", "assist.nhf.nhm_hydrofabric_v2"}
names = set()
for path in pl.Path("src").rglob("*.py"):
    if ".ipynb_checkpoints" in str(path):
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in TARGETS:
            names.update(a.name for a in node.names)
print(sorted(names))
PY
```

Write both shim files with that list (plus `evaluate_and_fix_nhru_geometry` and
`_load_byhwobs_cal_gages` if callers do not already import them), in the same shape concern
1 used:

```python
"""Compatibility shim. Implementation lives in assist.common.hydrofabric."""
from assist.common.hydrofabric import (
    ...,
)

__all__ = [
    ...,
]
```

Then remove `find_missing_gage_metadata` everywhere. I enumerated every reference; it spans
more files than a first read suggests, so work through this list exactly:

Production:
1. `src/assist/common/assist_utilities.py` — delete the function (around line 1150) and its
   `REMOVE WHEN` comment.
2. `src/assist/nhm/nhm_assist_utilities.py` and `src/assist/nhf/nhm_assist_utilities_v2.py` —
   remove it from the import list and from `__all__` in both (18 names down to 17). The two
   files must stay byte-identical.

Tests:
3. `tests/unification/test_shims.py` — remove `"find_missing_gage_metadata"` from `EXPECTED`,
   and delete the two tests that assert the two lookups differ
   (`test_canonical_and_metadata_lookup_are_different_functions`) and that the nhm hydrofabric
   uses the metadata lookup (`test_nhm_hydrofabric_uses_the_metadata_lookup`) — both describe
   a state this task ends. Change
   `test_metadata_lookup_is_public_now` to assert the function is absent instead.
4. `tests/unification/test_find_missing_gage_info.py` — delete
   `test_nhm_version_survives_as_find_missing_gage_metadata` and the metadata-return-contract
   test that calls it. Keep the tests covering the canonical `find_missing_gage_info`.
5. `tests/test_multi_model_workspace.py` — its `patch.object(nhm_hydrofabric,
   "find_missing_gage_metadata", ...)` and the following `callable(...)` assertion now target
   a name the shim no longer exposes. Repoint both to `create_default_gages_file`, which is
   what that test is actually reaching for (it only checks the symbol is imported and
   reachable).
6. **`tests/test_nhm_find_missing_gage_info.py` — delete the whole file.** All 8 of its tests
   call `find_missing_gage_metadata` and cover only that function. They cannot be repointed at
   the canonical `find_missing_gage_info`, which has a different signature and returns the
   caller's frame rather than a metadata-only frame indexed by `poi_gage_id`.

**Record what point 6 costs.** Those 8 tests covered: an empty gage list, skipping gages
already in the resource file, NLDI success, WaterData fallback, NLDI failure falling through
to WaterData, total network failure degrading to empty-with-warnings, and geopackage
regeneration and freshness. nhf's `find_missing_gage_info` handles all the same concerns — I
checked, it has NLDI, resource-file and WaterData paths plus exception handling across 348
lines — but it has no tests of its own for any of them. So the capability survives and the
coverage does not. Do not attempt to rewrite those 8 tests against nhf's API in this task;
that is a follow-up worth doing before this branch merges, and it is recorded as such.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/ -v`
Expected: PASS, all tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/hydrofabric.py src/assist/common/assist_utilities.py \
        src/assist/nhm/nhm_hydrofabric.py src/assist/nhf/nhm_hydrofabric_v2.py \
        src/assist/nhm/nhm_assist_utilities.py src/assist/nhf/nhm_assist_utilities_v2.py
git add -f tests/unification/test_hydrofabric_shims.py tests/unification/test_shims.py
```

---

### Task 8: Full verification

**Files:** none new.

- [ ] **Step 1: Import sweep**

```bash
~/.pixi/bin/pixi run --frozen python -c "
import importlib
for m in ('assist.common.hydrofabric','assist.nhm.nhm_hydrofabric',
          'assist.nhf.nhm_hydrofabric_v2','assist.common.assist_utilities',
          'assist.nhm.nhm_assist_utilities','assist.nhf.nhm_assist_utilities_v2',
          'assist.nhf.map_template_v2','assist.nhm.map_template',
          'assist.nhf.sf_data_retrieval_v2_1','assist.nhm.sf_data_retrieval'):
    importlib.import_module(m); print('OK', m)
"
```

Expected: ten `OK` lines.

- [ ] **Step 2: Every caller name resolves from both shims**

```bash
~/.pixi/bin/pixi run --frozen python - <<'PY'
import ast, pathlib as pl
import assist.common.hydrofabric as common
import assist.nhf.nhm_hydrofabric_v2 as nhf
import assist.nhm.nhm_hydrofabric as nhm
TARGETS = {"assist.nhm.nhm_hydrofabric", "assist.nhf.nhm_hydrofabric_v2"}
names = set()
for path in pl.Path("src").rglob("*.py"):
    if ".ipynb_checkpoints" in str(path):
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in TARGETS:
            names.update(a.name for a in node.names)
bad = [f"{lbl}.{n}" for n in sorted(names) for lbl, mod in (("nhm", nhm), ("nhf", nhf))
       if getattr(mod, n, None) is not getattr(common, n, object())]
print(f"{len(names)} names x 2 shims ->", "ALL RESOLVE" if not bad else f"FAILURES: {bad}")
PY
```

Expected: `ALL RESOLVE`.

- [ ] **Step 3: Full suite**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/ -q`
Expected: at least the 152 tests that passed before this plan, plus the new ones. Zero failures.

- [ ] **Step 4: Notebook smoke check on both fabrics**

```bash
cd /Users/lludden/Documents/GitHub/nhm-assist-gitlab/nhf_assist/nb_run
export NHM_BATCH_MODE=1
~/.pixi/bin/pixi run --frozen python -m nbconvert --to notebook --execute --inplace \
    --ExecutePreprocessor.timeout=3600 0_workspace_setup.ipynb
```

Expected: exit 0. Then repeat with notebook 2 (`2_model_hydrofabric_visualization.ipynb`),
which is the notebook that actually exercises `create_hru_gdf`, `create_segment_gdf`, and
`create_poi_df`. Back up `nhf_assist/subdomain_config.yaml` first; notebook 0 overwrites it.

Note: notebook 2 previously needed two fixes that are already in place on this branch — the
FMI graceful-skip guard, and the rendered `nb_2_v2.png` legend in
`data_dependencies/map_custom_explanations/`. If either is missing, notebook 2 fails for
reasons unrelated to this plan.

- [ ] **Step 5: Confirm the GFv1.1 path still works**

The whole justification for taking nhf's side is that it reads both fabrics. Prove it:

```bash
~/.pixi/bin/pixi run --frozen python - <<'PY'
import warnings; warnings.filterwarnings("ignore")
import pathlib as pl
from tests.unification.fabrics import FABRICS, gpkg_columns
for key, model in FABRICS.items():
    if not model.exists():
        print(f"  {key}: model absent, skipped"); continue
    nhru = gpkg_columns(model, "nhru")
    nseg = gpkg_columns(model, "nsegment")
    print(f"  {key}: nhru has hru_id={'hru_id' in nhru}, "
          f"nsegment has nhm_seg={'nhm_seg' in nseg}, "
          f"nhm_seg_id={'nhm_seg_id' in nseg}")
PY
```

Expected: `gfv1_1` shows `hru_id=False, nhm_seg=True, nhm_seg_id=False`; `gfv2` shows
`hru_id=True, nhm_seg=False, nhm_seg_id=True`. Both must be readable by the unified code.

---

## Remaining concerns after this one

1. `sf_data_retrieval` — 10 shared (6 differ), 2 nhm-only (`_safe_clip_mask`,
   `_should_retry_waterdata`) which must survive; delete the dead
   `sf_data_retrieval_v2.py` (1269L, zero importers). Also the place to address the
   92.5%-identical `fetch_nwis_gage_info` / `fetch_waterdata_gage_info` pair now sitting in
   `common/assist_utilities.py`.
2. `map_template` — 21 shared, 17 differ, 8 nhf-only. The largest and riskiest.
3. `display_controls` — fold nhf's 9 widget functions into the existing
   `common/display_controls.py`, then shim.
