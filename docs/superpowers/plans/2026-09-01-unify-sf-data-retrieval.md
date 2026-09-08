# Helper Unification, Concern 3: `sf_data_retrieval` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse `src/assist/nhm/sf_data_retrieval.py` (1189L) and `src/assist/nhf/sf_data_retrieval_v2_1.py` (1162L) into a single `src/assist/common/sf_data_retrieval.py`, delete the dead `sf_data_retrieval_v2.py` (1269L, zero importers), strip pasted LLM citation markers from the source, and retire the now-orphaned `fetch_nwis_gage_info`.

**Architecture:** nhm is the `git mv` parent and the behavioural base — the opposite of concerns 1 and 2 — because nhm holds the robustness work (GEOS-safe clip, WaterData retry/backoff/resume, submission staggering) that nhf's copy lacks. nhf's contributions are applied on top: WaterData terminology, the `metadata/` gage path, and a substantially larger `ecy_scrape`. This is the first concern requiring a per-function merge rather than a side choice, so the AST-identity guarantee applies only to the functions that move unchanged.

**Tech Stack:** Python 3.11, pytest, pandas / geopandas / xarray, dataretrieval, pixi (`pixi run --frozen`).

**Spec:** `docs/superpowers/specs/2026-08-30-helper-unification-design.md`

## Global Constraints

- Branch: `restructure/unify-remaining-helpers`. Baseline commit for differential tests: `c47ff07`.
- Run everything through pixi: `~/.pixi/bin/pixi run --frozen python -m pytest ...`. `pixi` is NOT on PATH; use the absolute path.
- WaterData is the canonical terminology (spec decision 7).
- Per spec decision 8, nhf normally wins — **this concern is a documented exception**, justified below.
- Per spec decision 10, the dominant file moves via a bare `git mv` in its own commit.
- `tests/` and `docs/` are gitignored (`.gitignore:487`); new files there need `git add -f`.
- The nhf shim keeps the filename `sf_data_retrieval_v2_1.py` (4 importers); the nhm shim keeps `sf_data_retrieval.py` (1 importer).
- **Claude never commits.** Every task ends staged-but-uncommitted; the user reviews and commits by hand.
- Full suite must stay green. Baseline at plan time: 181 passed, 9 subtests.

## Why nhm is the base here, inverting decision 8

Measured function by function. nhm carries robustness; nhf carries naming and one capability:

| Function | nhm | nhf |
| --- | --- | --- |
| `create_OR_sf_df`, `create_ecy_sf_df` | `clip(_safe_clip_mask(hru_gdf))` — GEOS-safe | `clip(hru_gdf)` — raw; WaterData docstrings |
| `fetch_daily_discharge_batch` | **69L** — retries 429/502/503/504, exponential backoff, resume on `ChunkInterrupted` | **36L** — none of that |
| `create_waterdata_sf_df` | staggered submissions so the WaterData edge sees no burst | `waterdata_cache.nc`, `metadata/WaterDataGages.csv`, `fetch_waterdata_gage_info`, `waterdata_gage_nobs_min` |
| `ecy_scrape` | 92L | **158L** — zip download, per-year DSG_DV parsing, cleanup |
| `create_sf_efc_df` | `NWIS_df` parameter | `waterdata_df` parameter, WaterData docstrings |
| `_safe_clip_mask`, `_should_retry_waterdata` | present | **absent** |

Taking nhf wholesale would delete the "GEOS-safe clip + WaterData retry/stagger" hardening and orphan both helpers. Taking nhm as the base preserves all of it and reduces nhf's contribution to a terminology pass plus one function swap.

Four functions are already identical on both sides and need no attention:
`_as_monitoring_location_ids`, `_chunked`, `_ensure_usgs_pat_stripped`, `owrd_scraper`.

## Two couplings that widen the scope

1. **`create_sf_efc_df`'s parameter rename breaks a caller.** The nhf notebook calls it with
   `waterdata_df=`, the nhm notebook with `NWIS_df=`
   (`src/workflow_templates/nhm/1_create_streamflow_observations.py:230`). One unified
   function cannot satisfy both, so adopting nhf's name requires editing that notebook.
2. **`fetch_nwis_gage_info` becomes orphaned.** Its only callers are the dead
   `sf_data_retrieval_v2.py` (deleted in Task 2) and `nhm/sf_data_retrieval.py:759` (switched
   to `fetch_waterdata_gage_info` in Task 4). Task 6 therefore deletes it, closing concern 1's
   review finding I3 — 388 lines of 92.5%-identical code sitting side by side in
   `common/assist_utilities.py`.

---

### Task 1: `git mv` nhm sf_data_retrieval into `common/`

Per spec decision 10, a bare rename in its own commit so git records it and plain `git blame`
credits the original authors. No other change.

**Files:**
- Rename: `src/assist/nhm/sf_data_retrieval.py` -> `src/assist/common/sf_data_retrieval.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `src/assist/common/sf_data_retrieval.py` with nhm's full content, including
  `_safe_clip_mask` and `_should_retry_waterdata`.

- [ ] **Step 1: Perform the rename**

```bash
git mv src/assist/nhm/sf_data_retrieval.py src/assist/common/sf_data_retrieval.py
```

- [ ] **Step 2: Confirm git records it as a rename**

```bash
git diff --cached --find-renames --name-status
```

Expected: a single line beginning `R100` or `R0xx` pairing the two paths. If it shows `D` plus
`A` instead, stop and report — the rename was not detected and decision 10's benefit is lost.

- [ ] **Step 3: Stage only this (do not commit)**

Nothing further to stage; the `git mv` already staged both sides. Do not create the shim yet —
it must land in a *separate* commit or the rename stops being detectable.

Note for the commit message the user will write: this commit leaves nothing at
`src/assist/nhm/sf_data_retrieval.py`, so its one importer
(`src/workflow_templates/nhm/1_create_streamflow_observations.py`) breaks at this commit and
`git bisect` will fail here for an unrelated reason.

---

### Task 2: Shims on both sides, and delete the dead `_v2`

**Files:**
- Create: `src/assist/nhm/sf_data_retrieval.py` (shim)
- Replace entirely: `src/assist/nhf/sf_data_retrieval_v2_1.py` (shim)
- Delete: `src/assist/nhf/sf_data_retrieval_v2.py`
- Modify: `src/workflow_templates/nhf/make_hydat_gage_resource.py` (drop one unused import name)
- Test: `tests/unification/test_sf_shims.py`

**Interfaces:**
- Consumes: `common/sf_data_retrieval.py` from Task 1.
- Produces: both shims re-export the same objects; the dead file is gone.

**A pre-existing broken import to fix while you are here.**
`src/workflow_templates/nhf/make_hydat_gage_resource.py:50` imports `create_nwis_sf_df` from
`assist.nhf.sf_data_retrieval_v2_1`, which does not define it. That import fails today:

```
ImportError: cannot import name 'create_nwis_sf_df' from 'assist.nhf.sf_data_retrieval_v2_1'
```

The function exists only in `sf_data_retrieval_v2.py`, the dead file this task deletes. Two
facts settle what to do: the template **never calls** the function (line 50 is its only
occurrence, inside the import list), and carrying it would drag in `fetch_single_nwis_gage`
plus force keeping `fetch_nwis_gage_info` alive — the 388-line duplicate Task 6 retires.

So: delete the dead file, and remove `create_nwis_sf_df` from that template's import list.
That repairs the template's ImportError as a side effect. Do not carry the function.

- [ ] **Step 1: Derive the export list from real callers**

Do not guess it. Run:

```bash
~/.pixi/bin/pixi run --frozen python - <<'PY'
import ast, pathlib as pl
TARGETS = {"assist.nhm.sf_data_retrieval", "assist.nhf.sf_data_retrieval_v2_1"}
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

The scan will report `create_nwis_sf_df` because that template imports it. **Exclude it** —
nothing defines it after this task and nothing calls it. The remaining five names are the real
export set: `create_OR_sf_df`, `create_ecy_sf_df`, `create_sf_efc_df`,
`create_waterdata_sf_df`, `fetch_daily_discharge_batch`.

Export exactly that set. Do **not** export `_safe_clip_mask`, `_should_retry_waterdata`,
`_as_monitoring_location_ids`, `_chunked` or `_ensure_usgs_pat_stripped` unless the script
lists them — private helpers stay unexported, matching concerns 1 and 2. If a *test* reaches a
private helper by attribute access, repoint that test at `assist.common.sf_data_retrieval`
rather than widening the shim; that ruling was already made in concern 2.

- [ ] **Step 2: Write the failing test**

```python
# tests/unification/test_sf_shims.py
"""Both sf_data_retrieval shims re-export common/, and the dead _v2 file is gone."""
import pathlib as pl

import pytest

import assist.common.sf_data_retrieval as common
import assist.nhf.sf_data_retrieval_v2_1 as nhf
import assist.nhm.sf_data_retrieval as nhm

EXPECTED_AT_LEAST = [
    "create_ecy_sf_df",
    "create_OR_sf_df",
    "create_sf_efc_df",
    "create_waterdata_sf_df",
    "owrd_scraper",
]


@pytest.mark.parametrize("name", EXPECTED_AT_LEAST)
def test_both_shims_export_the_same_object(name):
    assert getattr(nhm, name) is getattr(common, name), f"nhm/{name}"
    assert getattr(nhf, name) is getattr(common, name), f"nhf/{name}"


@pytest.mark.parametrize("module", [nhm, nhf])
def test_shim_defines_no_logic(module):
    source = pl.Path(module.__file__).read_text(encoding="utf-8")
    assert "def " not in source
    assert "from assist.common.sf_data_retrieval import" in source


def test_shims_are_byte_identical():
    a = pl.Path(nhm.__file__).read_text(encoding="utf-8")
    b = pl.Path(nhf.__file__).read_text(encoding="utf-8")
    assert a == b


def test_dead_v2_file_is_gone():
    assert not pl.Path("src/assist/nhf/sf_data_retrieval_v2.py").exists()


def test_hardening_helpers_survived_in_common():
    """nhm-only robustness work that taking nhf's side would have deleted."""
    assert callable(common._safe_clip_mask)
    assert callable(common._should_retry_waterdata)


def test_private_helpers_are_not_exported():
    for module in (nhm, nhf):
        for private in ("_safe_clip_mask", "_should_retry_waterdata"):
            assert private not in (module.__all__ or [])


def test_the_hydat_template_import_is_repaired():
    """It imported create_nwis_sf_df, which no module defined — a pre-existing ImportError."""
    source = pl.Path(
        "src/workflow_templates/nhf/make_hydat_gage_resource.py"
    ).read_text(encoding="utf-8")
    assert "create_nwis_sf_df" not in source


def test_create_nwis_sf_df_is_gone_everywhere():
    offenders = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        if "create_nwis_sf_df" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path))
    assert offenders == [], f"still referenced in {offenders}"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_sf_shims.py -v`
Expected: FAIL — `src/assist/nhm/sf_data_retrieval.py` does not exist yet (Task 1 moved it)

- [ ] **Step 4: Write the shims and delete the dead file**

Write this content to BOTH `src/assist/nhm/sf_data_retrieval.py` and
`src/assist/nhf/sf_data_retrieval_v2_1.py`, substituting the names from Step 1:

```python
"""Compatibility shim. Implementation lives in assist.common.sf_data_retrieval."""
from assist.common.sf_data_retrieval import (
    ...,
)

__all__ = [
    ...,
]
```

Then remove the dead file and repair the template's import:

```bash
git rm src/assist/nhf/sf_data_retrieval_v2.py
```

In `src/workflow_templates/nhf/make_hydat_gage_resource.py`, delete the single line
`    create_nwis_sf_df,` from the `from assist.nhf.sf_data_retrieval_v2_1 import (...)` block,
leaving the other four names. Change nothing else in that file.

- [ ] **Step 5: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/ -v`
Expected: PASS

- [ ] **Step 6: Stage (do not commit)**

```bash
git add src/assist/nhm/sf_data_retrieval.py src/assist/nhf/sf_data_retrieval_v2_1.py \
        src/workflow_templates/nhf/make_hydat_gage_resource.py
git add -f tests/unification/test_sf_shims.py
```

---

### Task 3: Adopt nhf's `ecy_scrape`

The one function where nhf has materially more capability: 158 lines against nhm's 92,
adding a zip download, per-year `DSG_DV.txt` parsing, and cleanup. Replace nhm's version
wholesale.

**Files:**
- Modify: `src/assist/common/sf_data_retrieval.py`
- Test: `tests/unification/test_sf_ecy_scrape.py`

**Interfaces:**
- Consumes: the module from Task 1.
- Produces: `ecy_scrape(...)` byte-identical to nhf's version at `c47ff07`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_sf_ecy_scrape.py
"""ecy_scrape is the one function taken from nhf in this concern."""
import inspect

from tests.unification.fabrics import baseline_function_ast, current_function_ast

NHF_SF = "src/assist/nhf/sf_data_retrieval_v2_1.py"
BASELINE = "c47ff07"


def test_ecy_scrape_is_verbatim_nhf():
    import assist.common.sf_data_retrieval as common

    assert current_function_ast(common.ecy_scrape) == baseline_function_ast(
        NHF_SF, "ecy_scrape", BASELINE
    )


def test_ecy_scrape_has_the_zip_handling_nhm_lacked():
    import assist.common.sf_data_retrieval as common

    source = inspect.getsource(common.ecy_scrape)
    assert "zipfile" in source
    assert "DSG_DV" in source or "tempfile" in source


def test_ecy_scrape_documents_its_return():
    import assist.common.sf_data_retrieval as common

    doc = inspect.getdoc(common.ecy_scrape) or ""
    assert "temp_df" in doc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_sf_ecy_scrape.py -v`
Expected: FAIL — the current `ecy_scrape` is nhm's 92-line version with no `zipfile`

- [ ] **Step 3: Write minimal implementation**

Replace `ecy_scrape` in `src/assist/common/sf_data_retrieval.py` with nhf's version, extracted
exactly rather than retyped:

**Extract from git, not from disk.** Task 2 replaced
`src/assist/nhf/sf_data_retrieval_v2_1.py` with an 18-line shim, so nhf's `ecy_scrape` no
longer exists in the working tree — it is only in history. Read it from the baseline commit:

```python
import ast, pathlib as pl, subprocess

src = subprocess.run(
    ["git", "show", "c47ff07:src/assist/nhf/sf_data_retrieval_v2_1.py"],
    capture_output=True, text=True, check=True,
).stdout
tree = ast.parse(src)
node = next(n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "ecy_scrape")
replacement = ast.get_source_segment(src, node)

dest = pl.Path("src/assist/common/sf_data_retrieval.py")
text = dest.read_text(encoding="utf-8")
dtree = ast.parse(text)
old = next(n for n in dtree.body
           if isinstance(n, ast.FunctionDef) and n.name == "ecy_scrape")
old_src = ast.get_source_segment(text, old)
dest.write_text(text.replace(old_src, replacement), encoding="utf-8")
```

nhf's version keeps its imports (`zipfile`, `tempfile`, `os`, `from io import StringIO`)
inside the function body. Leave them there — hoisting them would break the AST comparison.

**Add exactly one module-level import:**

```python
from urllib.request import Request
```

Verified by free-name analysis: `ecy_scrape`'s free names are `HTTPError`, `Request`, `pd` and
`urlopen`, and the module already imports all but `Request`. It has `from urllib import request`
(the module) which is not the same name.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_sf_ecy_scrape.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/sf_data_retrieval.py
git add -f tests/unification/test_sf_ecy_scrape.py
```

---

### Task 4: WaterData terminology pass

Applies nhf's naming to the merged module while keeping every piece of nhm's robustness.
This is a rename pass, not a logic change — the `_safe_clip_mask` call, the retry/backoff, the
resume, and the staggering all stay exactly as nhm wrote them.

Includes the one caller edit coupling 1 forces.

**Files:**
- Modify: `src/assist/common/sf_data_retrieval.py`
- Modify: `src/workflow_templates/nhm/1_create_streamflow_observations.py` (line ~230)
- Test: `tests/unification/test_sf_terminology.py`

**Interfaces:**
- Consumes: the module from Task 3.
- Produces: `create_sf_efc_df(..., waterdata_df=..., ...)` — the `NWIS_df` parameter is renamed.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_sf_terminology.py
"""WaterData naming (spec decision 7) with nhm's robustness intact."""
import inspect
import pathlib as pl


def test_create_sf_efc_df_takes_waterdata_df_not_nwis_df():
    import assist.common.sf_data_retrieval as common

    params = inspect.signature(common.create_sf_efc_df).parameters
    assert "waterdata_df" in params
    assert "NWIS_df" not in params


def test_create_waterdata_sf_df_uses_the_waterdata_fetcher_and_metadata_path():
    import assist.common.sf_data_retrieval as common

    source = inspect.getsource(common.create_waterdata_sf_df)
    assert "fetch_waterdata_gage_info" in source
    assert "fetch_nwis_gage_info" not in source
    assert 'metadata/WaterDataGages.csv' in source
    assert "waterdata_cache.nc" in source


def test_geos_safe_clip_survived_the_terminology_pass():
    """nhm-only hardening that adopting nhf's side would have deleted."""
    import assist.common.sf_data_retrieval as common

    for name in ("create_OR_sf_df", "create_ecy_sf_df"):
        source = inspect.getsource(getattr(common, name))
        assert "_safe_clip_mask(hru_gdf)" in source, f"{name} lost the GEOS-safe clip"


def test_retry_and_stagger_survived():
    import assist.common.sf_data_retrieval as common

    batch = inspect.getsource(common.fetch_daily_discharge_batch)
    assert "_should_retry_waterdata" in batch
    assert "max_retries" in batch
    wd = inspect.getsource(common.create_waterdata_sf_df)
    assert "_chunked" in wd


def test_common_has_no_workflow_package_imports():
    """common/ must not import from assist.nhm or assist.nhf."""
    source = pl.Path("src/assist/common/sf_data_retrieval.py").read_text(encoding="utf-8")
    assert "from assist.nhm" not in source
    assert "from assist.nhf" not in source


def test_the_nhm_notebook_caller_was_updated():
    source = open(
        "src/workflow_templates/nhm/1_create_streamflow_observations.py", encoding="utf-8"
    ).read()
    assert "waterdata_df=" in source
    assert "NWIS_df=" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_sf_terminology.py -v`
Expected: FAIL — `create_sf_efc_df` still takes `NWIS_df`

- [ ] **Step 3: Write minimal implementation**

In `src/assist/common/sf_data_retrieval.py`, make exactly these changes:

1. `create_sf_efc_df`: rename the parameter `NWIS_df` to `waterdata_df` and every use of it
   inside the body. Update the docstring wording from NWIS to WaterData, matching nhf's text.
2. `create_OR_sf_df` and `create_ecy_sf_df`: update the two NWIS mentions in each docstring
   and comment to WaterData. **Leave `clip(_safe_clip_mask(hru_gdf))` alone.**
3. `create_waterdata_sf_df`: change the cache filename to `waterdata_cache.nc`, the gage file
   path to `model_dir / "metadata/WaterDataGages.csv"`, the import and call from
   `fetch_nwis_gage_info` to `fetch_waterdata_gage_info`, and the keyword
   `nwis_gage_nobs_min=` to `waterdata_gage_nobs_min=`. **Leave the `_chunked` staggering
   block alone.**
4. **Re-point both `assist.nhm.*` imports.** The `git mv` carried this file over verbatim,
   including two imports that now make `common/` depend on a workflow package:

   ```python
   from assist.nhm.efc import efc                                    # -> assist.common.efc
   from assist.nhm.nhm_assist_utilities import fetch_nwis_gage_info  # -> assist.common.assist_utilities
   ```

   Change them to:

   ```python
   from assist.common.efc import efc
   from assist.common.assist_utilities import fetch_waterdata_gage_info
   ```

   Both `assist.nhm.efc` and `assist.nhm.nhm_assist_utilities` are only shims over `common/`,
   so importing through them is an inversion — the same defect found in concern 1 — and a
   circular-import risk now that the nhm sf_data_retrieval module is itself a shim over this
   file.

Then in `src/workflow_templates/nhm/1_create_streamflow_observations.py` around line 230,
change the `NWIS_df=` keyword in the `create_sf_efc_df(...)` call to `waterdata_df=`. Change
nothing else in that file.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/ -v`
Expected: PASS

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/sf_data_retrieval.py \
        src/workflow_templates/nhm/1_create_streamflow_observations.py
git add -f tests/unification/test_sf_terminology.py
```

---

### Task 5: Strip the pasted LLM citation markers

Both source files carry ChatGPT-style citation artifacts in docstrings and comments —
`:contentReference[oaicite:N]{index=N}`. Six occurrences: `nhm/sf_data_retrieval.py` lines 68
and 576, `nhf/sf_data_retrieval_v2_1.py` lines 40, 614, 650, 651. They are the only such
strings anywhere in `src/`. Harmless at runtime, but they should not ship.

This deliberately breaks the verbatim-copy property for the functions containing them, which
is why it lands in its own task with its own test rather than being smuggled into a copy step.

**Files:**
- Modify: `src/assist/common/sf_data_retrieval.py`
- Test: `tests/unification/test_no_citation_markers.py`

**Interfaces:**
- Consumes: the module from Task 4.
- Produces: no behaviour change.

- [ ] **Step 1: Write the failing test**

```python
# tests/unification/test_no_citation_markers.py
"""Pasted LLM citation markers must not ship in source."""
import pathlib as pl

MARKERS = ("contentReference", "oaicite")


def test_common_sf_data_retrieval_is_clean():
    text = pl.Path("src/assist/common/sf_data_retrieval.py").read_text(encoding="utf-8")
    for marker in MARKERS:
        assert marker not in text, f"{marker} still present"


def test_no_citation_markers_anywhere_under_src():
    offenders = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(m in text for m in MARKERS):
            offenders.append(str(path))
    assert offenders == [], f"citation markers in {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_no_citation_markers.py -v`
Expected: FAIL — markers present in `common/sf_data_retrieval.py`

- [ ] **Step 3: Write minimal implementation**

Remove only the citation markers, leaving the surrounding prose intact and readable. For
example:

```
# dataretrieval uses API_USGS_PAT env var for Water Data APIs auth :contentReference[oaicite:1]{index=1}
```

becomes

```
# dataretrieval uses API_USGS_PAT env var for Water Data APIs auth
```

Strip any trailing whitespace the removal leaves behind. Do not reword or delete the comments
themselves.

- [ ] **Step 4: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/ -v`
Expected: PASS. The second test also covers the shims, which should be clean by construction.

- [ ] **Step 5: Stage (do not commit)**

```bash
git add src/assist/common/sf_data_retrieval.py
git add -f tests/unification/test_no_citation_markers.py
```

---

### Task 6: Retire the orphaned `fetch_nwis_gage_info`

Closes concern 1's review finding I3. `fetch_nwis_gage_info` and `fetch_waterdata_gage_info`
are 92.5% token-identical, 388 lines side by side in `common/assist_utilities.py`. Both had
live callers when concern 1 ran, so neither could go. After Task 2 deleted the dead `_v2` file
and Task 4 switched `create_waterdata_sf_df` to the WaterData fetcher, `fetch_nwis_gage_info`
has no caller left.

**Files:**
- Modify: `src/assist/common/assist_utilities.py`
- Modify: `src/assist/nhm/nhm_assist_utilities.py`, `src/assist/nhf/nhm_assist_utilities_v2.py`
- Modify: `tests/unification/test_shims.py`, `tests/unification/test_carried_over.py`
- Test: `tests/unification/test_nwis_fetcher_retired.py`

**Interfaces:**
- Consumes: the module from Task 4.
- Produces: `fetch_nwis_gage_info` no longer exists anywhere.

- [ ] **Step 1: Confirm it really is orphaned before deleting**

```bash
grep -rn 'fetch_nwis_gage_info' src/ tests/ --include='*.py' | grep -v ipynb_checkpoints
```

Expected: only its own `def`, the two shim export lists, and test references. If any other
call site appears, STOP and report — the premise has changed and the deletion is unsafe.

- [ ] **Step 2: Write the failing test**

```python
# tests/unification/test_nwis_fetcher_retired.py
"""fetch_nwis_gage_info is retired; fetch_waterdata_gage_info is canonical."""
import pathlib as pl

import assist.common.assist_utilities as cu
import assist.nhf.nhm_assist_utilities_v2 as nhf
import assist.nhm.nhm_assist_utilities as nhm


def test_the_nwis_fetcher_is_gone():
    assert not hasattr(cu, "fetch_nwis_gage_info")
    assert not hasattr(nhm, "fetch_nwis_gage_info")
    assert not hasattr(nhf, "fetch_nwis_gage_info")


def test_the_waterdata_fetcher_remains():
    assert callable(cu.fetch_waterdata_gage_info)


def test_no_source_file_still_references_it():
    offenders = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        if "fetch_nwis_gage_info" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path))
    assert offenders == [], f"still referenced in {offenders}"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_nwis_fetcher_retired.py -v`
Expected: FAIL — the function still exists

- [ ] **Step 4: Write minimal implementation**

1. Delete `fetch_nwis_gage_info` from `src/assist/common/assist_utilities.py`.
2. Remove it from the import list and `__all__` of both `assist_utilities` shims (17 names
   down to 16). Keep the two files byte-identical.
3. In `tests/unification/test_shims.py`, remove `"fetch_nwis_gage_info"` from `EXPECTED`.
4. In `tests/unification/test_carried_over.py`, remove it from the carried-over name list and
   from any parametrised case naming it.

- [ ] **Step 5: Run test to verify it passes**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/ -q`
Expected: PASS, zero failures. The count drops slightly as removed parametrised cases go.

- [ ] **Step 6: Stage (do not commit)**

```bash
git add src/assist/common/assist_utilities.py src/assist/nhm/nhm_assist_utilities.py \
        src/assist/nhf/nhm_assist_utilities_v2.py
git add -f tests/unification/test_nwis_fetcher_retired.py tests/unification/test_shims.py \
        tests/unification/test_carried_over.py
```

---

### Task 7: Full verification

**Files:** none new.

- [ ] **Step 1: Import sweep**

```bash
~/.pixi/bin/pixi run --frozen python -c "
import importlib
for m in ('assist.common.sf_data_retrieval','assist.nhm.sf_data_retrieval',
          'assist.nhf.sf_data_retrieval_v2_1','assist.common.assist_utilities',
          'assist.nhm.nhm_assist_utilities','assist.nhf.nhm_assist_utilities_v2',
          'assist.common.hydrofabric','assist.nhm.nhm_hydrofabric',
          'assist.nhf.nhm_hydrofabric_v2','assist.nhf.map_template_v2',
          'assist.nhm.map_template'):
    importlib.import_module(m); print('OK', m)
"
```

Expected: eleven `OK` lines.

- [ ] **Step 2: Every caller name resolves from both shims**

```bash
~/.pixi/bin/pixi run --frozen python - <<'PY'
import ast, pathlib as pl
import assist.common.sf_data_retrieval as common
import assist.nhf.sf_data_retrieval_v2_1 as nhf
import assist.nhm.sf_data_retrieval as nhm
TARGETS = {"assist.nhm.sf_data_retrieval", "assist.nhf.sf_data_retrieval_v2_1"}
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
Expected: zero failures. Note `pytest tests/unification/` alone reports a subset, not the full
suite; always report the `tests/` number.

- [ ] **Step 4: Confirm the rename recorded and blame credits the original authors**

```bash
git log --diff-filter=R --find-renames --name-status --oneline -3 -- src/assist/common/sf_data_retrieval.py
git blame --line-porcelain src/assist/common/sf_data_retrieval.py \
  | grep '^author ' | sed 's/^author //' | sort | uniq -c | sort -rn
```

Expected: an `R` line pairing `src/assist/nhm/sf_data_retrieval.py` with the new path, and
more than one author in the blame output. If blame shows only one author, decision 10's
two-commit rename did not take effect and that is worth reporting.

- [ ] **Step 5: Notebook smoke check**

Both notebook 1 variants import this module, so run the nhf one, which has 4 importers:

```bash
cd /Users/lludden/Documents/GitHub/nhm-assist-gitlab/nhf_assist/nb_run
export NHM_BATCH_MODE=1
~/.pixi/bin/pixi run --frozen python -m nbconvert --to notebook --execute --inplace \
    --ExecutePreprocessor.timeout=3600 1_create_streamflow_observations.ipynb
```

Expected: exit 0. This notebook fetches streamflow observations over the network, so it takes
several minutes and needs connectivity. Back up `nhf_assist/subdomain_config.yaml` first.

---

## Remaining after this concern

1. `map_template` — nhm 2467L + nhf 3317L, 21 shared with 17 differing, 8 nhf-only. The
   largest and riskiest, and the one where decision 10's rename matters most.
2. `display_controls` — fold nhf's 9 widget functions into the existing
   `common/display_controls.py` (389L), then shim. The nhm side is already absent, so this is
   the one concern where a plain rename was already recorded.

Carried-forward debt, unchanged by this plan:
- The 8 deleted gage-lookup tests from concern 2 need rewriting against nhf's
  `find_missing_gage_info` API.
- `same` is undefined in `common/hydrofabric.py`'s `create_hru_gdf` mismatch branch.
- The hardcoded `hydrofabric_domain_data/OHM_2026_02_21/npoigages_data` path in the
  ref-gage fetchers points at a directory absent from this checkout.
