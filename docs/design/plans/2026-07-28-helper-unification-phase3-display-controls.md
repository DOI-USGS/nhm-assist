# Phase 3 — Unify display_controls (Dependency Injection) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify nhm `display_controls.py` and nhf `display_controls_v2.py` into `assist.common.display_controls`, with the diverged map backend injected per-side.

**Architecture:** nhm's version is the canonical superset. Move it to `assist/common/display_controls.py`; the 2 actually-called map functions (`make_var_map`, `make_streamflow_map`) become `None`-default module globals injected by each consuming notebook, guarded by `_require_state`. The dead `make_hf_map_elements` import is dropped. nhf's module and nhm's module are removed; the 4 notebooks import common and wire their own backend.

**Tech Stack:** Python, ipywidgets, pytest (run via pixi), git.

## Global Constraints

- Run tests with: `pixi run -e default pytest <path> -v`
- `/tests` is gitignored — modified/new test files must be staged with `git add -f`.
- Use `git mv` to preserve file history when moving modules.
- **Per user preference: PROMPT before every commit; never auto-commit.** Commit steps below are gated on explicit user approval.
- Branch: `restructure/helper-unification-2`.
- Only 2 backend functions are injected: `make_var_map`, `make_streamflow_map`. `make_hf_map_elements` is imported-but-never-called → remove it.

---

### Task 1: Move display_controls to common with injected backend

**Files:**
- Move: `src/assist/nhm/display_controls.py` → `src/assist/common/display_controls.py` (via `git mv`)
- Modify: `src/assist/common/display_controls.py` (imports → injected globals; repoint sibling imports)
- Modify: `tests/test_display_controls.py:13` (retarget import)

**Interfaces:**
- Produces: module `assist.common.display_controls` exposing the same public
  functions as before (`generate_map`, `generate_summary`, `generate_flux`,
  `on_generate_clicked`, `on_map_clicked`, `on_plot_clicked`, `warn`, …) plus
  injectable module attributes `make_var_map = None`, `make_streamflow_map = None`.

- [ ] **Step 1: Move the file preserving history**

```bash
git mv src/assist/nhm/display_controls.py src/assist/common/display_controls.py
```

- [ ] **Step 2: Replace backend imports with injected globals**

In `src/assist/common/display_controls.py`, delete these three import lines:

```python
from assist.nhm.map_template import make_var_map
from assist.nhm.nhm_hydrofabric import make_hf_map_elements
from assist.nhm.map_template import make_streamflow_map
```

Repoint the two already-unified sibling imports to common:

```python
# was: from assist.nhm.nhm_output_visualization import retrieve_hru_output_info
from assist.common.output_visualization import retrieve_hru_output_info
# was: from assist.nhm.output_plots import plot_colors
from assist.common.output_plots import plot_colors
# was: from assist.nhm.output_plots import (var_colors_dict, leg_only_dict, make_plot_var_for_hrus_in_poi_basin, oopla)
from assist.common.output_plots import (
    var_colors_dict,
    leg_only_dict,
    make_plot_var_for_hrus_in_poi_basin,
    oopla,
)
# was: from assist.nhm.output_plots import create_streamflow_plot
from assist.common.output_plots import create_streamflow_plot
```

(The duplicate `retrieve_hru_output_info` import at the old line 18 — repoint or drop it; it is redundant.)

In the module-globals block (the `root_dir = None` … section), add:

```python
make_var_map = None          # injected by the consuming notebook
make_streamflow_map = None   # injected by the consuming notebook
```

- [ ] **Step 3: Retarget the test import**

In `tests/test_display_controls.py` change line 13:

```python
from assist.common import display_controls as dc
```

- [ ] **Step 4: Run the existing tests**

Run: `pixi run -e default pytest tests/test_display_controls.py -v`
Expected: PASS (2 tests: `test_generate_summary_reports_external_plot_path`, `test_on_plot_clicked_reports_external_plot_without_inline_preview`). They exercise `generate_summary`/`on_plot_clicked`, which use plot functions (already in common), not the injected backend.

- [ ] **Step 5: Confirm no leftover nhm-internal imports in the moved module**

Run: `grep -nE "assist\.nhm\." src/assist/common/display_controls.py`
Expected: no output.

- [ ] **Step 6: Commit** (prompt user first)

```bash
git add -f src/assist/common/display_controls.py tests/test_display_controls.py
git add src/assist/nhm/display_controls.py
git commit -m "refactor(display_controls): move to assist.common with injected map backend"
```

---

### Task 2: TDD the injected-backend guard

**Files:**
- Modify: `tests/test_display_controls.py` (add one test)
- Modify: `src/assist/common/display_controls.py` (add backend names to `_require_state` in `generate_map` and `on_map_clicked`)

**Interfaces:**
- Consumes: `assist.common.display_controls` from Task 1.
- Produces: `generate_map()` / `on_map_clicked()` return early with a `warn(...)`
  when their backend global is `None`, instead of calling `None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_display_controls.py`:

```python
    def test_generate_map_missing_backend_warns(self):
        dc.make_var_map = None
        dc.poi_df = pd.DataFrame({"poi_gage_id": ["gage-1"]})
        dc.v2 = SimpleNamespace(value="gage-1")

        warnings_seen = []
        with patch.object(dc, "warn", side_effect=warnings_seen.append):
            result = dc.generate_map()

        self.assertIsNone(result)
        self.assertTrue(warnings_seen)
        self.assertIn("make_var_map", warnings_seen[-1])
```

Add `make_var_map` and `make_streamflow_map` to the `setUp` state-snapshot tuple so `tearDown` restores them.

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run -e default pytest tests/test_display_controls.py::DisplayControlsTests::test_generate_map_missing_backend_warns -v`
Expected: FAIL (currently `generate_map` does not guard `make_var_map`; it proceeds past `_require_state` and the test's warn assertion fails or it errors).

- [ ] **Step 3: Add the guard**

In `src/assist/common/display_controls.py`, add `"make_var_map"` to the `_require_state(...)` argument list inside `generate_map`, and `"make_streamflow_map"` to the `_require_state(...)` list inside `on_map_clicked`.

- [ ] **Step 4: Run the full test file**

Run: `pixi run -e default pytest tests/test_display_controls.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit** (prompt user first)

```bash
git add -f tests/test_display_controls.py
git add src/assist/common/display_controls.py
git commit -m "test(display_controls): guard injected backend, fail loudly when unwired"
```

---

### Task 3: Remove old modules and rewire the notebooks

**Files:**
- Delete: `src/assist/nhf/display_controls_v2.py` (via `git rm`)
- Modify: `src/workflow_templates/nhm/5_hru_output_visualization_new.py`
- Modify: `src/workflow_templates/nhm/6_streamflow_output_visualization_new.py`
- Modify: `src/workflow_templates/nhf/5_hru_output_visualization_new.py`
- Modify: `src/workflow_templates/nhf/6_streamflow_output_visualization_new.py`

**Interfaces:**
- Consumes: `assist.common.display_controls` (Task 1/2). Each notebook imports it
  as `dc` and injects the backend it already imports.

- [ ] **Step 1: Delete the nhf module**

```bash
git rm src/assist/nhf/display_controls_v2.py
```

- [ ] **Step 2: Rewire nhm notebook 5 (hru output — uses make_var_map)**

In `src/workflow_templates/nhm/5_hru_output_visualization_new.py`, change the import line
`import assist.nhm.display_controls as dc` → `import assist.common.display_controls as dc`.
Then, in the `dc.*` wiring block, add:

```python
dc.make_var_map = make_var_map
```

(`make_var_map` is already imported at line 59: `from assist.nhm.map_template import make_var_map`.)

- [ ] **Step 3: Rewire nhm notebook 6 (streamflow — uses make_streamflow_map)**

In `src/workflow_templates/nhm/6_streamflow_output_visualization_new.py`, change the
display_controls import to `import assist.common.display_controls as dc`. In the `dc.*`
block add:

```python
dc.make_streamflow_map = make_streamflow_map
```

(`make_streamflow_map` already imported at line 53: `from assist.nhm.map_template import make_streamflow_map`.)

- [ ] **Step 4: Rewire nhf notebook 5 (uses make_var_map)**

In `src/workflow_templates/nhf/5_hru_output_visualization_new.py`, change the
display_controls import to `import assist.common.display_controls as dc`. In the `dc.*`
block add:

```python
dc.make_var_map = make_var_map
```

(`make_var_map` already imported at line 47: `from assist.nhf.map_template_v2 import make_var_map`.)

- [ ] **Step 5: Rewire nhf notebook 6 (uses make_streamflow_map)**

In `src/workflow_templates/nhf/6_streamflow_output_visualization_new.py`, change the
display_controls import to `import assist.common.display_controls as dc`. In the `dc.*`
block add:

```python
dc.make_streamflow_map = make_streamflow_map
```

(`make_streamflow_map` already imported at line 41: `from assist.nhf.map_template_v2 import make_streamflow_map`.)

- [ ] **Step 6: Verify no stale imports of the removed modules remain**

```bash
grep -rnE "assist\.nhm\.display_controls|assist\.nhf\.display_controls_v2" src/
```
Expected: no output.

- [ ] **Step 7: Run the full test suite**

Run: `pixi run -e default pytest tests/ -q`
Expected: PASS (all previously-green tests + the 3 display_controls tests).

- [ ] **Step 8: Commit** (prompt user first)

```bash
git add src/workflow_templates/nhm/5_hru_output_visualization_new.py \
        src/workflow_templates/nhm/6_streamflow_output_visualization_new.py \
        src/workflow_templates/nhf/5_hru_output_visualization_new.py \
        src/workflow_templates/nhf/6_streamflow_output_visualization_new.py \
        src/assist/nhf/display_controls_v2.py
git commit -m "refactor(display_controls): rewire notebooks to common + inject backend; remove nhf module"
```

---

## Notes for the implementer
- Do NOT unify `map_template` / `nhm_hydrofabric` — the backend stays per-side by design (Phase 4).
- The nwis/waterdata naming inside the backend is irrelevant here: each notebook injects its own side's function.
- If a notebook's dc-flow turns out to call `on_map_clicked` (streamflow map) in an nb5, wire `make_streamflow_map` there too — but per current imports, nb5 only needs `make_var_map` and nb6 only needs `make_streamflow_map`.
