# Helper fix — Phase 1 (efc + nhm_helpers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the two lowest-risk duplicated helper modules (`efc`, `nhm_helpers`) into a new `src/assist/common/` package, with back-compat shims so both `nhm` and `nhf` import paths keep working unchanged.

**Architecture:** Move the canonical (nhm) implementation into `src/assist/common/`; replace the `nhm` modules with pure re-export shims; replace the `nhf` modules with re-export shims that add a `poi_gage_id`→`poi_id` boundary rename for the one function that needs it (`create_poi_group`). No behavior change; notebook importers under `src/workflow_templates/` are untouched.

**Tech Stack:** Python 3.11, `unittest` + `pytest`, `pandas`, existing `assist` package.

## Global Constraints

- Branch: `helper-fix` (confirm with `git branch --show-current`).
- Canonical naming: POI id → `poi_id`. `nhm` is already canonical; `nhf` renames `poi_gage_id`→`poi_id` at the boundary.
- Both `assist.nhm.*` and `assist.nhf.*` import paths must keep resolving (shims). No changes in `src/workflow_templates/`.
- `efc.py` is byte-identical across trees and has no `assist` sibling imports → verbatim move. `nhm_helpers.py` has no `assist` sibling imports → verbatim move.
- Tests: `unittest.TestCase`, run with `pytest`. New tests go in `tests/test_common_helpers.py`.
- **Commit after each task, but PROMPT the user before running the commit** (do not commit autonomously) — per user preference (uncommitted work was previously lost to a `git reset --hard`).
- Scope is Phase 1 only: `efc` + `nhm_helpers`. `output_visualization` + `output_plots` are a separate Phase 2 plan.

---

### Task 1: Create `common` package + move `efc` + shims

**Files:**
- Create: `src/assist/common/__init__.py`
- Create: `src/assist/common/efc.py`
- Modify: `src/assist/nhm/efc.py` (→ re-export shim)
- Modify: `src/assist/nhf/efc.py` (→ re-export shim)
- Test: `tests/test_common_helpers.py`

**Interfaces:**
- Produces: `assist.common.efc` exposing `efc`, `get_first_valid`, `compute_efc`, `compute_high_low`, `compute_recurrence_interval`, `plot_efc`, `plot_high_low`. The `nhm`/`nhf` `efc` modules re-export the same objects.

- [ ] **Step 1: Write the failing test**

Create `tests/test_common_helpers.py`:

```python
from __future__ import annotations

import unittest


class CommonEfcTests(unittest.TestCase):
    def test_efc_reexported_from_common_in_nhm(self):
        from assist.common import efc as common_efc
        from assist.nhm import efc as nhm_efc

        self.assertIs(nhm_efc.efc, common_efc.efc)
        self.assertIs(nhm_efc.plot_efc, common_efc.plot_efc)
        self.assertIs(nhm_efc.compute_efc, common_efc.compute_efc)

    def test_efc_reexported_from_common_in_nhf(self):
        from assist.common import efc as common_efc
        from assist.nhf import efc as nhf_efc

        self.assertIs(nhf_efc.efc, common_efc.efc)
        self.assertIs(nhf_efc.plot_efc, common_efc.plot_efc)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run -e default pytest tests/test_common_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assist.common'`

- [ ] **Step 3: Create the common package and move efc verbatim**

Run:
```bash
mkdir -p src/assist/common
printf '"""Shared helpers used by both the nhm and nhf trees."""\n' > src/assist/common/__init__.py
cp src/assist/nhm/efc.py src/assist/common/efc.py
```

- [ ] **Step 4: Replace both efc modules with re-export shims**

Overwrite `src/assist/nhm/efc.py` with:

```python
from assist.common.efc import (
    compute_efc,
    compute_high_low,
    compute_recurrence_interval,
    efc,
    get_first_valid,
    plot_efc,
    plot_high_low,
)

__all__ = [
    "efc",
    "get_first_valid",
    "compute_efc",
    "compute_high_low",
    "compute_recurrence_interval",
    "plot_efc",
    "plot_high_low",
]
```

Overwrite `src/assist/nhf/efc.py` with the identical content (same re-export block).

- [ ] **Step 5: Run test to verify it passes**

Run: `pixi run -e default pytest tests/test_common_helpers.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Smoke-import both shims and a real consumer**

Run:
```bash
pixi run -e default python -c "import assist.nhm.efc, assist.nhf.efc, assist.common.efc; from assist.nhm.efc import efc, plot_efc; from assist.nhf.efc import efc, plot_efc; print('efc shims OK')"
```
Expected: prints `efc shims OK` with no ImportError.

- [ ] **Step 7: Commit (PROMPT USER FIRST)**

Show the user this proposed commit and wait for confirmation before running it:

```bash
git add src/assist/common/__init__.py src/assist/common/efc.py src/assist/nhm/efc.py src/assist/nhf/efc.py tests/test_common_helpers.py
git commit -m "refactor(helpers): move efc into assist.common with re-export shims

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Move `nhm_helpers` → `common/helpers` + shims (nhf poi rename)

**Files:**
- Create: `src/assist/common/helpers.py`
- Modify: `src/assist/nhm/nhm_helpers.py` (→ pure re-export shim)
- Modify: `src/assist/nhf/nhm_helpers_v2.py` (→ re-export + `create_poi_group` rename adapter)
- Test: `tests/test_common_helpers.py`

**Interfaces:**
- Consumes: `assist.common` package (Task 1).
- Produces: `assist.common.helpers` exposing `subset_stream_network(dag_ds, uscutoff_seg, dsmost_seg)`, `hrus_by_poi(pdb, poi)`, `create_poi_group(hru_gdf, poi_df, param_filename)`. `create_poi_group` reads the POI id from the canonical `poi_id` column. The `nhf` shim renames `poi_gage_id`→`poi_id` on `poi_df` before delegating.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_common_helpers.py` (add these imports at top: `from unittest.mock import patch`, `import pandas as pd`):

```python
class CommonHelpersTests(unittest.TestCase):
    def test_helpers_reexported_from_common_in_nhm(self):
        from assist.common import helpers as common_helpers
        from assist.nhm import nhm_helpers

        self.assertIs(
            nhm_helpers.subset_stream_network, common_helpers.subset_stream_network
        )
        self.assertIs(nhm_helpers.hrus_by_poi, common_helpers.hrus_by_poi)
        self.assertIs(nhm_helpers.create_poi_group, common_helpers.create_poi_group)

    def test_nhf_reexports_non_poi_helpers(self):
        from assist.common import helpers as common_helpers
        from assist.nhf import nhm_helpers_v2 as nhf_helpers

        self.assertIs(
            nhf_helpers.subset_stream_network, common_helpers.subset_stream_network
        )
        self.assertIs(nhf_helpers.hrus_by_poi, common_helpers.hrus_by_poi)

    def test_nhf_create_poi_group_renames_poi_gage_id(self):
        import pandas as pd
        from assist.common import helpers as common_helpers
        from assist.nhf import nhm_helpers_v2 as nhf_helpers

        captured = {}

        def fake(hru_gdf, poi_df, param_filename):
            captured["cols"] = list(poi_df.columns)
            return "ok"

        with patch.object(common_helpers, "create_poi_group", side_effect=fake):
            result = nhf_helpers.create_poi_group(
                None, pd.DataFrame({"poi_gage_id": ["g1"]}), "param_file"
            )

        self.assertEqual(result, "ok")
        self.assertIn("poi_id", captured["cols"])
        self.assertNotIn("poi_gage_id", captured["cols"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pixi run -e default pytest tests/test_common_helpers.py::CommonHelpersTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assist.common.helpers'`

- [ ] **Step 3: Move nhm_helpers into common verbatim**

Run:
```bash
cp src/assist/nhm/nhm_helpers.py src/assist/common/helpers.py
```
(`nhm_helpers.py` imports only `warnings`, `collections.abc`, `networkx`, `pyPRMS`, `rich` — no `assist` sibling imports — so no edits needed.)

- [ ] **Step 4: Replace `nhm/nhm_helpers.py` with a pure re-export shim**

Overwrite `src/assist/nhm/nhm_helpers.py` with:

```python
from assist.common.helpers import (
    create_poi_group,
    hrus_by_poi,
    subset_stream_network,
)

__all__ = ["subset_stream_network", "hrus_by_poi", "create_poi_group"]
```

- [ ] **Step 5: Replace `nhf/nhm_helpers_v2.py` with re-export + rename adapter**

Overwrite `src/assist/nhf/nhm_helpers_v2.py` with:

```python
from assist.common import helpers as _common_helpers
from assist.common.helpers import hrus_by_poi, subset_stream_network

__all__ = ["subset_stream_network", "hrus_by_poi", "create_poi_group"]


def create_poi_group(hru_gdf, poi_df, param_filename):
    """nhf uses a `poi_gage_id` column; normalize to the canonical `poi_id`."""
    if "poi_gage_id" in poi_df.columns and "poi_id" not in poi_df.columns:
        poi_df = poi_df.rename(columns={"poi_gage_id": "poi_id"})
    return _common_helpers.create_poi_group(hru_gdf, poi_df, param_filename)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pixi run -e default pytest tests/test_common_helpers.py -v`
Expected: all PASS (Task 1 + Task 2 tests)

- [ ] **Step 7: Smoke-import the shims and the notebook consumers' import lines**

Run:
```bash
pixi run -e default python -c "
from assist.nhm.nhm_helpers import subset_stream_network, hrus_by_poi, create_poi_group
from assist.nhf.nhm_helpers_v2 import subset_stream_network, hrus_by_poi, create_poi_group
from assist.common.helpers import create_poi_group as c
print('helpers shims OK')
"
```
Expected: prints `helpers shims OK`.

- [ ] **Step 8: Commit (PROMPT USER FIRST)**

Show the user this proposed commit and wait for confirmation before running it:

```bash
git add src/assist/common/helpers.py src/assist/nhm/nhm_helpers.py src/assist/nhf/nhm_helpers_v2.py tests/test_common_helpers.py
git commit -m "refactor(helpers): move nhm_helpers into assist.common with poi_id normalization

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Full-suite verification

**Files:** none

- [ ] **Step 1: Run the whole test suite**

Run: `pixi run -e default pytest tests/ -q`
Expected: all PASS (no regressions from the shim swap).

- [ ] **Step 2: Confirm no `src/workflow_templates/` changes were needed**

Run: `git status --short src/workflow_templates`
Expected: no output (untouched).

## Deferred to Phase 2 (separate plan)

`output_visualization` and `output_plots` — these require `poi_gage_id`→`poi_id`
renames that span xarray dims/coords (`obs.sel(poi_gage_id=…)`) across 6 functions
(`create_var_ts_for_poi_basin_df`, `make_plot_var_for_hrus_in_poi_basin`, `oopla`,
`calculate_monthly_kge_in_poi_df`, `create_streamflow_plot`), and safe
universalization needs characterization tests backed by real NHM data fixtures
(none exist in `tests/` today). Phase 2 will first add those fixtures, then extract
these two modules the same way.
