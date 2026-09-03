# Helper Unification — Phase 2 (output_visualization + output_plots) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `nhm_output_visualization` and `output_plots` into `assist.common`, with a shared POI-canonicalization adapter so the nhf shims delegate to one implementation while renaming `poi_gage_id`→`poi_id` (DataFrame columns, xarray dims/coords, and the `poi_gage_id_sel` kwarg) at the boundary.

**Architecture:** Add `assist.common._adapters` with `_canonicalize_poi` + `poi_adapt`. `git mv` the nhm modules into `common/` (canonical — nhm already uses `poi_id` and has the `_normalize_hru_id_column`/`_hru_dim_name` helpers). nhm modules become pure re-export shims; nhf modules re-export the naming-agnostic functions and wrap the poi-bearing ones with `poi_adapt`.

**Tech Stack:** Python 3.11, `unittest` + `pytest`, `pandas`, `xarray`, existing `assist` package.

## Global Constraints

- Repo: `nhm-assist-gitlab`. Branch: `restructure/helper-unification` (confirm `git branch --show-current`).
- Builds on Phase 1 (`assist.common.efc`, `assist.common.helpers` already exist).
- Canonical naming: POI id → `poi_id` (DataFrame column, xarray dim/coord, and the selected-id kwarg `poi_id_sel`). nhm is already canonical.
- Both `assist.nhm.*` and `assist.nhf.*` import paths must keep resolving (shims). No changes in `src/workflow_templates/`.
- Use `git mv` for the module moves so history follows into `common/`.
- `tests/` is gitignored in this repo — new test files must be added with `git add -f`.
- Tests: `unittest.TestCase`, run with `pixi run -e default pytest`. Add to `tests/test_common_helpers.py`.
- Synthetic-input adapter tests (option A): build small fake DataFrames / xarray objects; do NOT depend on real NHM data.
- **Commit after each task, but PROMPT the user before committing** (do not commit autonomously).
- Run the full module after each task: `pixi run -e default pytest tests/test_common_helpers.py -v`.

---

### Task 1: Shared POI adapter (`assist.common._adapters`)

**Files:**
- Create: `src/assist/common/_adapters.py`
- Test: `tests/test_common_helpers.py`

**Interfaces:**
- Produces:
  - `_canonicalize_poi(obj) -> obj` — renames `poi_gage_id`→`poi_id` on a `pandas.DataFrame` column or an `xarray.Dataset`/`DataArray` dim/coord; returns anything else unchanged.
  - `poi_adapt(fn) -> fn` — decorator: remaps a `poi_gage_id_sel` kwarg to `poi_id_sel`, and runs every positional/keyword arg through `_canonicalize_poi`, then calls `fn`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_common_helpers.py`:

```python
class PoiAdapterTests(unittest.TestCase):
    def test_canonicalize_dataframe_column(self):
        import pandas as pd
        from assist.common._adapters import _canonicalize_poi

        df = _canonicalize_poi(pd.DataFrame({"poi_gage_id": ["a"], "x": [1]}))
        self.assertIn("poi_id", df.columns)
        self.assertNotIn("poi_gage_id", df.columns)

    def test_canonicalize_xarray_dim(self):
        import xarray as xr
        from assist.common._adapters import _canonicalize_poi

        ds = xr.Dataset({"q": ("poi_gage_id", [1, 2])}, coords={"poi_gage_id": ["a", "b"]})
        out = _canonicalize_poi(ds)
        self.assertIn("poi_id", out.dims)
        self.assertNotIn("poi_gage_id", out.dims)

    def test_canonicalize_passes_through_other(self):
        from assist.common._adapters import _canonicalize_poi

        self.assertEqual(_canonicalize_poi("gage-123"), "gage-123")
        self.assertEqual(_canonicalize_poi(42), 42)

    def test_poi_adapt_renames_args_and_kwarg(self):
        import pandas as pd
        from assist.common._adapters import poi_adapt

        seen = {}

        @poi_adapt
        def fn(df, *, poi_id_sel=None):
            seen["cols"] = list(df.columns)
            seen["sel"] = poi_id_sel
            return "ok"

        result = fn(pd.DataFrame({"poi_gage_id": ["a"]}), poi_gage_id_sel="gage-1")
        self.assertEqual(result, "ok")
        self.assertIn("poi_id", seen["cols"])
        self.assertEqual(seen["sel"], "gage-1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pixi run -e default pytest tests/test_common_helpers.py::PoiAdapterTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assist.common._adapters'`

- [ ] **Step 3: Implement the adapter**

Create `src/assist/common/_adapters.py`:

```python
"""Boundary adapters to normalize nhf's `poi_gage_id` to the canonical `poi_id`."""
from __future__ import annotations

import functools

import pandas as pd

try:  # xarray is a hard dep in practice, but stay import-safe
    import xarray as xr
except Exception:  # pragma: no cover
    xr = None

_POI_OLD = "poi_gage_id"
_POI_NEW = "poi_id"


def _canonicalize_poi(obj):
    if isinstance(obj, pd.DataFrame):
        if _POI_OLD in obj.columns and _POI_NEW not in obj.columns:
            return obj.rename(columns={_POI_OLD: _POI_NEW})
        return obj
    if xr is not None and isinstance(obj, (xr.Dataset, xr.DataArray)):
        names = set(map(str, getattr(obj, "dims", ()))) | set(
            map(str, getattr(obj, "coords", {}).keys())
        )
        if _POI_OLD in names:
            return obj.rename({_POI_OLD: _POI_NEW})
        return obj
    return obj


def poi_adapt(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if "poi_gage_id_sel" in kwargs and "poi_id_sel" not in kwargs:
            kwargs["poi_id_sel"] = kwargs.pop("poi_gage_id_sel")
        args = tuple(_canonicalize_poi(a) for a in args)
        kwargs = {k: _canonicalize_poi(v) for k, v in kwargs.items()}
        return fn(*args, **kwargs)

    return wrapper
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pixi run -e default pytest tests/test_common_helpers.py::PoiAdapterTests -v`
Expected: 4 PASS

- [ ] **Step 5: Commit (PROMPT USER FIRST)**

Show the user, wait for confirmation:

```bash
git add -f tests/test_common_helpers.py
git add src/assist/common/_adapters.py
git commit -m "feat(common): add POI canonicalization adapter"
```

---

### Task 2: Move `nhm_output_visualization` → `common/output_visualization` + shims

**Files:**
- Create (via git mv): `src/assist/common/output_visualization.py`
- Modify: `src/assist/nhm/nhm_output_visualization.py` (→ pure re-export shim)
- Modify: `src/assist/nhf/nhm_output_visualization_v2.py` (→ re-export + adapt `create_var_ts_for_poi_basin_df`)
- Test: `tests/test_common_helpers.py`

**Interfaces:**
- Consumes: `assist.common._adapters.poi_adapt` (Task 1).
- Produces: `assist.common.output_visualization` exposing the 10 public functions: `retrieve_hru_output_info`, `create_sum_var_dataarrays`, `create_mean_var_dataarrays`, `create_sum_var_annual_gdf`, `create_sum_var_annual_df`, `create_sum_var_monthly_df`, `create_var_daily_df`, `create_var_ts_for_poi_basin_df`, `create_sum_seg_var_dataarrays`, `create_streamflow_obs_datasets` (plus the private `_normalize_hru_id_column`, `_hru_dim_name`).

- [ ] **Step 1: Confirm the nhm module has no `assist` sibling imports**

Run: `grep -nE "^(from|import) .*assist" src/assist/nhm/nhm_output_visualization.py || echo "no sibling imports"`
Expected: `no sibling imports` (so it moves verbatim). If any appear, repoint them to `assist.common.*` in Step 3.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_common_helpers.py`:

```python
class OutputVisualizationShimTests(unittest.TestCase):
    def test_reexport_identity_in_nhm(self):
        from assist.common import output_visualization as common_ov
        from assist.nhm import nhm_output_visualization as nhm_ov

        for name in ("retrieve_hru_output_info", "create_sum_var_annual_df",
                     "create_streamflow_obs_datasets"):
            self.assertIs(getattr(nhm_ov, name), getattr(common_ov, name))

    def test_nhf_reexports_non_poi_functions(self):
        from assist.common import output_visualization as common_ov
        from assist.nhf import nhm_output_visualization_v2 as nhf_ov

        self.assertIs(nhf_ov.create_sum_var_annual_df, common_ov.create_sum_var_annual_df)

    def test_nhf_var_ts_adapter_canonicalizes(self):
        import pandas as pd
        from assist.common import output_visualization as common_ov
        from assist.nhf import nhm_output_visualization_v2 as nhf_ov

        captured = {}

        def fake(poi_df=None, *, poi_id_sel=None, **kw):
            captured["cols"] = list(poi_df.columns)
            captured["sel"] = poi_id_sel
            return "ok"

        with patch.object(common_ov, "create_var_ts_for_poi_basin_df", side_effect=fake):
            result = nhf_ov.create_var_ts_for_poi_basin_df(
                poi_df=pd.DataFrame({"poi_gage_id": ["g1"]}), poi_gage_id_sel="g1"
            )

        self.assertEqual(result, "ok")
        self.assertIn("poi_id", captured["cols"])
        self.assertEqual(captured["sel"], "g1")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pixi run -e default pytest tests/test_common_helpers.py::OutputVisualizationShimTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assist.common.output_visualization'`

- [ ] **Step 4: git mv the module into common**

Run:
```bash
git -C . mv src/assist/nhm/nhm_output_visualization.py src/assist/common/output_visualization.py
```
(If Step 1 found sibling imports, edit them in `common/output_visualization.py` to `assist.common.*` now.)

- [ ] **Step 5: Write the nhm re-export shim**

Create `src/assist/nhm/nhm_output_visualization.py`:

```python
from assist.common.output_visualization import (
    _hru_dim_name,
    _normalize_hru_id_column,
    create_mean_var_dataarrays,
    create_streamflow_obs_datasets,
    create_sum_seg_var_dataarrays,
    create_sum_var_annual_df,
    create_sum_var_annual_gdf,
    create_sum_var_dataarrays,
    create_sum_var_monthly_df,
    create_var_daily_df,
    create_var_ts_for_poi_basin_df,
    retrieve_hru_output_info,
)

__all__ = [
    "retrieve_hru_output_info",
    "create_sum_var_dataarrays",
    "create_mean_var_dataarrays",
    "create_sum_var_annual_gdf",
    "create_sum_var_annual_df",
    "create_sum_var_monthly_df",
    "create_var_daily_df",
    "create_var_ts_for_poi_basin_df",
    "create_sum_seg_var_dataarrays",
    "create_streamflow_obs_datasets",
]
```

- [ ] **Step 6: Write the nhf shim (re-export + one adapter)**

Overwrite `src/assist/nhf/nhm_output_visualization_v2.py`:

```python
from assist.common import output_visualization as _ov
from assist.common._adapters import poi_adapt
from assist.common.output_visualization import (
    create_mean_var_dataarrays,
    create_streamflow_obs_datasets,
    create_sum_seg_var_dataarrays,
    create_sum_var_annual_df,
    create_sum_var_annual_gdf,
    create_sum_var_dataarrays,
    create_sum_var_monthly_df,
    create_var_daily_df,
    retrieve_hru_output_info,
)

__all__ = [
    "retrieve_hru_output_info",
    "create_sum_var_dataarrays",
    "create_mean_var_dataarrays",
    "create_sum_var_annual_gdf",
    "create_sum_var_annual_df",
    "create_sum_var_monthly_df",
    "create_var_daily_df",
    "create_var_ts_for_poi_basin_df",
    "create_sum_seg_var_dataarrays",
    "create_streamflow_obs_datasets",
]

# Only this function references the POI id (as `poi_gage_id` in nhf).
create_var_ts_for_poi_basin_df = poi_adapt(_ov.create_var_ts_for_poi_basin_df)
```

- [ ] **Step 7: Run tests + smoke import**

Run: `pixi run -e default pytest tests/test_common_helpers.py::OutputVisualizationShimTests -v`
Expected: 3 PASS

Run:
```bash
pixi run -e default python -c "
import assist.nhm.nhm_output_visualization, assist.nhf.nhm_output_visualization_v2, assist.common.output_visualization
from assist.nhm.nhm_output_visualization import retrieve_hru_output_info
from assist.nhf.nhm_output_visualization_v2 import create_var_ts_for_poi_basin_df
print('output_visualization shims OK')
"
```
Expected: prints `output_visualization shims OK`.

- [ ] **Step 8: Commit (PROMPT USER FIRST)**

```bash
git add -f tests/test_common_helpers.py
git add src/assist/common/output_visualization.py src/assist/nhm/nhm_output_visualization.py src/assist/nhf/nhm_output_visualization_v2.py
git commit -m "refactor(common): move output_visualization into assist.common with poi adapter"
```

---

### Task 3: Move `output_plots` → `common/output_plots` + shims

**Files:**
- Create (via git mv): `src/assist/common/output_plots.py`
- Modify: `src/assist/nhm/output_plots.py` (→ pure re-export shim)
- Modify: `src/assist/nhf/output_plots_v2.py` (→ re-export 3 + adapt 4)
- Test: `tests/test_common_helpers.py`

**Interfaces:**
- Consumes: `assist.common._adapters.poi_adapt`; `assist.common.helpers`; `assist.common.output_visualization`.
- Produces: `assist.common.output_plots` exposing `is_wsl`, `make_webbrowser_map`, `make_plot_var_for_hrus_in_poi_basin`, `oopla`, `stats_table`, `calculate_monthly_kge_in_poi_df`, `create_streamflow_plot`.

- [ ] **Step 1: Note the nhm module's sibling imports (to repoint)**

Run: `grep -nE "^from assist" src/assist/nhm/output_plots.py`
Expected: two lines importing from `assist.nhm.nhm_helpers` and `assist.nhm.nhm_output_visualization` — these get repointed to `assist.common.*` in Step 4.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_common_helpers.py`:

```python
class OutputPlotsShimTests(unittest.TestCase):
    def test_reexport_identity_nhm(self):
        from assist.common import output_plots as common_op
        from assist.nhm import output_plots as nhm_op

        for name in ("is_wsl", "make_webbrowser_map", "stats_table",
                     "create_streamflow_plot"):
            self.assertIs(getattr(nhm_op, name), getattr(common_op, name))

    def test_nhf_reexports_naming_agnostic(self):
        from assist.common import output_plots as common_op
        from assist.nhf import output_plots_v2 as nhf_op

        for name in ("is_wsl", "make_webbrowser_map", "stats_table"):
            self.assertIs(getattr(nhf_op, name), getattr(common_op, name))

    def test_nhf_create_streamflow_plot_adapter(self):
        import pandas as pd
        import xarray as xr
        from assist.common import output_plots as common_op
        from assist.nhf import output_plots_v2 as nhf_op

        captured = {}

        def fake(*args, poi_id_sel=None, obs=None, **kw):
            captured["sel"] = poi_id_sel
            captured["obs_dims"] = list(obs.dims) if obs is not None else None
            return "ok"

        obs = xr.Dataset({"q": ("poi_gage_id", [1, 2])},
                         coords={"poi_gage_id": ["a", "b"]})
        with patch.object(common_op, "create_streamflow_plot", side_effect=fake):
            result = nhf_op.create_streamflow_plot(poi_gage_id_sel="a", obs=obs)

        self.assertEqual(result, "ok")
        self.assertEqual(captured["sel"], "a")
        self.assertIn("poi_id", captured["obs_dims"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pixi run -e default pytest tests/test_common_helpers.py::OutputPlotsShimTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assist.common.output_plots'`

- [ ] **Step 4: git mv the module and repoint its sibling imports**

Run:
```bash
git -C . mv src/assist/nhm/output_plots.py src/assist/common/output_plots.py
```
Then edit `src/assist/common/output_plots.py` — change the two sibling imports:
- `from assist.nhm.nhm_helpers import create_poi_group` → `from assist.common.helpers import create_poi_group`
- `from assist.nhm.nhm_output_visualization import (` → `from assist.common.output_visualization import (`
(Leave the imported names inside the parentheses unchanged.)

- [ ] **Step 5: Write the nhm re-export shim**

Create `src/assist/nhm/output_plots.py`:

```python
from assist.common.output_plots import (
    calculate_monthly_kge_in_poi_df,
    create_streamflow_plot,
    is_wsl,
    make_plot_var_for_hrus_in_poi_basin,
    make_webbrowser_map,
    oopla,
    stats_table,
)

__all__ = [
    "is_wsl",
    "make_webbrowser_map",
    "make_plot_var_for_hrus_in_poi_basin",
    "oopla",
    "stats_table",
    "calculate_monthly_kge_in_poi_df",
    "create_streamflow_plot",
]
```

- [ ] **Step 6: Write the nhf shim (re-export 3 + adapt 4)**

Overwrite `src/assist/nhf/output_plots_v2.py`:

```python
from assist.common import output_plots as _op
from assist.common._adapters import poi_adapt
from assist.common.output_plots import (
    is_wsl,
    make_webbrowser_map,
    stats_table,
)

__all__ = [
    "is_wsl",
    "make_webbrowser_map",
    "make_plot_var_for_hrus_in_poi_basin",
    "oopla",
    "stats_table",
    "calculate_monthly_kge_in_poi_df",
    "create_streamflow_plot",
]

# These four reference the POI id (as `poi_gage_id` / `poi_gage_id_sel` in nhf).
make_plot_var_for_hrus_in_poi_basin = poi_adapt(_op.make_plot_var_for_hrus_in_poi_basin)
oopla = poi_adapt(_op.oopla)
calculate_monthly_kge_in_poi_df = poi_adapt(_op.calculate_monthly_kge_in_poi_df)
create_streamflow_plot = poi_adapt(_op.create_streamflow_plot)
```

- [ ] **Step 7: Run tests + smoke import**

Run: `pixi run -e default pytest tests/test_common_helpers.py::OutputPlotsShimTests -v`
Expected: 3 PASS

Run:
```bash
pixi run -e default python -c "
import assist.nhm.output_plots, assist.nhf.output_plots_v2, assist.common.output_plots
from assist.nhm.output_plots import create_streamflow_plot, is_wsl
from assist.nhf.output_plots_v2 import create_streamflow_plot, is_wsl
print('output_plots shims OK')
"
```
Expected: prints `output_plots shims OK`.

**Important — module-level names beyond the 7 defs.** Notebooks import `plot_colors` from `output_plots` (a module-level variable, not a `def`). Before writing the shims, list ALL public names the notebooks use:
```bash
grep -rnE "from assist\.(nhm|nhf)\.output_plots" src/workflow_templates
grep -nE "^[a-zA-Z_][a-zA-Z0-9_]* *=" src/assist/common/output_plots.py | grep -iE "plot_colors|color" 
```
Add any such names (e.g. `plot_colors`) to BOTH shims' import lists and `__all__`, or the notebook imports will break.

- [ ] **Step 8: Commit (PROMPT USER FIRST)**

```bash
git add -f tests/test_common_helpers.py
git add src/assist/common/output_plots.py src/assist/nhm/output_plots.py src/assist/nhf/output_plots_v2.py
git commit -m "refactor(common): move output_plots into assist.common with poi adapters"
```

---

### Task 4: Full-suite verification

**Files:** none

- [ ] **Step 1: Confirm any module-level names notebooks import still resolve**

Run:
```bash
grep -rnE "from assist\.(nhm|nhf)\.(output_plots|nhm_output_visualization)" src/workflow_templates | sed 's/#.*//'
```
For each imported name, confirm it appears in the corresponding shim's `__all__` / import list. Add any missing names to both shims.

- [ ] **Step 2: Full common-helpers module**

Run: `pixi run -e default pytest tests/test_common_helpers.py -v`
Expected: all PASS (Phase 1 + adapter + output_visualization + output_plots tests).

- [ ] **Step 3: Full suite**

Run: `pixi run -e default pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 4: Confirm no workflow_templates changes were needed**

Run: `git status --short src/workflow_templates`
Expected: no output.

## Deferred to later phases

- **Phase 3:** `display_controls` (medium; 8 sibling imports).
- **Phase 4:** `nhm_hydrofabric`, `sf_data_retrieval`, `nhm_assist_utilities`, `map_template` — real logic divergence (NWIS↔WaterData, path model, nhf-only functions). Requires a product decision before mechanical unification; triage per module.
