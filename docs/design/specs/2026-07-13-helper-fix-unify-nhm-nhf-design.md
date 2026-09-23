# Helper fix: reorganize and universalize nhm/nhf helpers (DRY)

**Date:** 2026-07-13
**Branch:** `helper-fix`
**Status:** Draft — pending review

## Problem

`src/assist/nhm/` and `src/assist/nhf/` are near-parallel trees. `nhf` began as a
`_v2` fork of `nhm` and the two have drifted, but for the low-drift pairs the
"difference" is almost entirely **one naming convention**, not real logic:

- POI id column/dim: `poi_id` (nhm) vs `poi_gage_id` (nhf)
- HRU id column/dim: `nhm_id` vs `nhru`
- import paths (`assist.nhm.*` vs `assist.nhf.*`)

Measured divergence (differing / total lines per pair):

| Pair | Differing / total | Verdict |
|---|---|---|
| `efc.py` | **0 / 726** | byte-identical duplicate |
| `nhm_helpers` | 4 / 386 | ~identical |
| `nhm_output_visualization` | 60 / 1376 | ~4% drift |
| `output_plots` | 102 / 3148 | ~3% drift |
| `sf_data_retrieval` | 482 / 2458 | ~20% drift |
| `map_template` | 1578 / 5747 | ~27% drift |
| `nhm_hydrofabric` | 604 / 1756 | ~34% drift |
| `nhm_assist_utilities` | 1150 / 2695 | ~43% drift |
| `display_controls` | 251 / 601 | ~42% drift |

DRY sharing has already started organically: `nhf/sf_data_retrieval_v2_1.py`
already does `from assist.nhm.efc import efc`, and `nhm/nhm_output_visualization.py`
grew `_normalize_hru_id_column` / `_hru_dim_name` helpers that already tolerate both
`nhm_id` and `nhru`.

## Goal & constraints

- **Both trees coexist** long-term. Extract shared logic into one common module
  both import, and **universalize** functions that differ only by naming so there
  is a single implementation.
- **This spec covers the four lowest-drift pairs only** (low-hanging fruit); the
  heavily diverged pairs are explicitly deferred.
- **No behavior change** to either tree — notebook outputs must be unchanged.
- **No changes required** in `src/workflow_templates/` (the ~6 notebook importers).

## Scope

In scope:

| Source pair | Extract to |
|---|---|
| `nhm/efc.py` + `nhf/efc.py` | `src/assist/common/efc.py` (verbatim move) |
| `nhm/nhm_helpers.py` + `nhf/nhm_helpers_v2.py` | `src/assist/common/helpers.py` |
| `nhm/nhm_output_visualization.py` + `nhf/nhm_output_visualization_v2.py` | `src/assist/common/output_visualization.py` |
| `nhm/output_plots.py` + `nhf/output_plots_v2.py` | `src/assist/common/output_plots.py` |

Out of scope (future work): `map_template`, `nhm_assist_utilities`,
`nhm_hydrofabric`, `sf_data_retrieval`, `display_controls`.

## Design

### 1. Canonical naming contract (boundary normalization)

Shared code speaks one vocabulary:

- POI identifier → **`poi_id`** (DataFrame column and xarray dim/coord)
- HRU identifier → **`nhm_id`**, tolerating `nhru` via the existing
  `_normalize_hru_id_column` / `_hru_dim_name` helpers (promoted into `common`).

`nhm` data is already canonical. `nhf` data uses `poi_gage_id`, so the `nhf` side
**normalizes at the boundary**: rename `poi_gage_id` → `poi_id` on inputs and back
to `poi_gage_id` on outputs where `nhf` downstream code depends on the original
name. This mirrors a pattern already present in the repo, so it is proven here and
keeps shared function signatures clean.

Rejected alternatives: parameterizing the column name on every function (threads an
argument through every call site) and a config/constants module (adds per-tree
coupling and hidden global-ish state) — both heavier than this scope warrants.

### 2. New `src/assist/common/` package

```
src/assist/common/
  __init__.py
  efc.py                  # moved verbatim from nhm/efc.py (== nhf/efc.py)
  helpers.py              # canonical shared helpers (create_poi_group, etc.)
  output_visualization.py # canonical; includes the normalize helpers
  output_plots.py         # canonical shared plotting
```

`output_plots` depends on `helpers` and `output_visualization`, so it is extracted
last.

### 3. Back-compat shims (no notebook changes)

The consumers are jupytext `.py` sources under `src/workflow_templates/{nhm,nhf}/`;
their import lines stay untouched.

- **nhm modules** (`assist/nhm/efc.py`, `nhm_helpers.py`,
  `nhm_output_visualization.py`, `output_plots.py`) → **pure re-exports** from
  `common` (nhm is already canonical).
- **nhf modules** (`assist/nhf/efc.py`, `nhm_helpers_v2.py`,
  `nhm_output_visualization_v2.py`, `output_plots_v2.py`) → **thin adapters**:
  rename `poi_gage_id` → `poi_id` on inputs (and back on outputs where nhf
  downstream needs it), then delegate to `common`.

`efc` has no naming difference, so both nhm and nhf shims for it are pure
re-exports.

### 4. Safety net — characterization tests (TDD refactor)

Before extracting anything, add characterization tests that pin current behavior of
each in-scope function for **both** the nhm and nhf paths:

- Data-returning functions (e.g. `retrieve_hru_output_info`,
  `calculate_monthly_kge_in_poi_df`): assert DataFrame / array equality against
  captured fixtures.
- Plot functions (e.g. `create_streamflow_plot`): assert on the returned figure
  structure / trace data and that the expected HTML file is written.

The refactor is complete only when both the nhm and nhf paths reproduce the pinned
outputs. Tests are written against the current public import paths so they keep
passing through the shim swap.

## Sequencing (small, reviewable commits)

1. **`efc`** — move to `common/efc.py`, replace both trees' files with re-export
   shims. Trivial; proves the shim pattern.
2. **`helpers`** — extract to `common/helpers.py`; nhm shim re-exports, nhf shim
   adapts `poi_id`/`poi_gage_id`.
3. **`output_visualization`** — extract to `common/output_visualization.py`,
   bringing the `_normalize_hru_id_column` / `_hru_dim_name` helpers along.
4. **`output_plots`** — extract last (depends on the previous two).

Each step: characterization tests green before and after.

## Success criteria

- `efc`, `helpers`, `output_visualization`, `output_plots` logic lives once in
  `src/assist/common/`.
- All existing `assist.nhm.*` and `assist.nhf.*` import paths still resolve.
- Characterization tests pass for both trees before and after the refactor.
- No changes required in `src/workflow_templates/`.
