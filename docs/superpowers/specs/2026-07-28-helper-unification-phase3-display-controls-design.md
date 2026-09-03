# Phase 3 — Unify `display_controls` via dependency injection

Date: 2026-07-28
Branch: `restructure/helper-unification-2`
Status: design approved (mechanism (ii) explicit)

## Goal

Unify the duplicated `display_controls` UI-glue module (nhm `display_controls.py`
vs nhf `display_controls_v2.py`) into `assist.common.display_controls`, following
the same nhm-canonical pattern as Phases 1–2, **without** first unifying its
diverged Phase-4 dependencies (`map_template`, `nhm_hydrofabric`).

## Why it was "blocked", and why DI unblocks it

`display_controls` is a module-as-singleton: the notebook does
`import assist.nhm.display_controls as dc` then assigns ~25 module attributes
(`dc.poi_df = …`, `dc.HW_basins = …`), and the button-handler functions read
those via `globals()`.

Of its 4 internal deps, 2 are already unified (Phase 2: `retrieve_hru_output_info`,
`output_plots`). The remaining 2 diverge:

- `make_var_map` / `make_streamflow_map` (map_template): nhm is a superset
  (extra `HW_basins*` kwargs nhf commented out).
- `make_hf_map_elements` (nhm_hydrofabric): nhf has an extra `resource_gages_file`
  param + `waterdata_*` naming — a real feature/naming divergence.

The block is only that a unified module can't hard-import one backend. Dependency
injection removes it: the backend functions become **injected module attributes**,
exactly like the existing state, so each side supplies its own backend and the
shared UI logic is unified.

Key simplification found during design: **`make_hf_map_elements` is imported but
never called** in `display_controls` (only `make_var_map` @130 and
`make_streamflow_map` @318 are invoked). So the injection surface is **2 functions**,
and the `make_hf_map_elements` import is dead code to remove.

## Design

### Canonical module
Move nhm's `display_controls.py` to `assist/common/display_controls.py` (it is the
evolved superset: `_require_state` guards, `_ensure_output_dirs`,
`_report_external_artifact`). Use `git mv` to preserve history.

### Injected backend
In `common/display_controls.py`, replace the top-of-file backend imports with
module globals defaulting to `None`:

```python
make_var_map = None          # injected by the notebook
make_streamflow_map = None   # injected by the notebook
```

Drop the unused `make_hf_map_elements` import entirely.

Extend `_require_state` guards in `generate_map` / `on_map_clicked` to include the
backend name(s) they call, so a mis-wired notebook fails loudly with a clear
message rather than a `NoneType is not callable`.

### Mechanism (ii): explicit wiring
- The `nhm/display_controls.py` and `nhf/display_controls_v2.py` modules are
  removed (their entire content now lives in common; there is no naming
  normalization needed because the backend is injected).
- The four consuming notebooks change their import to
  `import assist.common.display_controls as dc` and add the backend wiring next to
  the existing `dc.*` assignments:
  - nhm 5, nhm 6: `dc.make_var_map = <nhm make_var_map>`,
    `dc.make_streamflow_map = <nhm make_streamflow_map>`
  - nhf 5, nhf 6: `dc.make_var_map = <nhf make_var_map>`,
    `dc.make_streamflow_map = <nhf make_streamflow_map>`
  Each notebook wires the function(s) its flow uses; wiring both is harmless.

### Consumers (exact list)
- `src/assist/nhm/display_controls.py` → `git mv` to `src/assist/common/display_controls.py`
- `src/assist/nhf/display_controls_v2.py` → removed
- `src/workflow_templates/nhm/5_hru_output_visualization_new.py` (29 `dc.*`)
- `src/workflow_templates/nhm/6_streamflow_output_visualization_new.py` (21 `dc.*`)
- `src/workflow_templates/nhf/5_hru_output_visualization_new.py` (29 `dc.*`)
- `src/workflow_templates/nhf/6_streamflow_output_visualization_new.py` (21 `dc.*`)

## Testing

- `tests/test_display_controls.py` (the existing 5 tests) must pass, retargeted to
  `assist.common.display_controls` and injecting stub backends.
- Add a test that a missing backend triggers the `_require_state` warning path
  (fails loudly, returns without calling `None`).
- Full suite green.

## Out of scope
- Unifying `map_template` / `nhm_hydrofabric` (Phase 4) — the backend stays
  per-side by design.
- The nwis→waterdata terminology (separate branch); backend is nhm's own so no
  conflict either way.

## Risks
- Notebook import change is the main churn; it's mechanical (1 import line + ≤2
  wiring lines per notebook).
- `sys.modules` alias was considered (mechanism (i)) and rejected for its magic and
  cross-import contamination.
