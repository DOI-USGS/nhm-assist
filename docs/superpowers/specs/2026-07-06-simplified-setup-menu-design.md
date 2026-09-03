# Simplified, linear setup menu

**Date:** 2026-07-06
**Branch:** `feature/simple-menu`
**Status:** Approved design — ready for implementation plan

## Problem

The end-user entry point (`pixi run setup` → `assist.workspace.cli setup` →
`run_setup` in `src/assist/workspace/setup.py`) presents a flat 10-item menu.
Two usability problems:

1. **The menu reappears on top of Jupyter startup.** `action_launch_jupyter`
   starts JupyterLab, sleeps 0.75s, and returns into the `while True` loop, which
   immediately re-prints the full menu. The user sees the menu again instead of a
   clear "loading" state while Jupyter comes up.

2. **The happy path is not linear.** Getting fully set up actually requires
   options 1 → 2 → (4 or 5) → 6 → 7 → 8 — six non-consecutive steps, and
   "Set active model" is a separate manual step even in the common single-model
   case. A new user cannot simply click 1, 2, 3, 4.

## Goal & constraints

- A new user can run the guided steps **in order (1 → 2 → 3 → 4)** and end up
  fully configured with sensible defaults and the active model set automatically.
- Launching Jupyter shows a **"Loading JupyterLab…"** state, waits for the server
  to be up, then returns to the menu (menu stays available).
- Both trees/coexistence and back-compat are not a concern here — this only
  touches the interactive setup CLI. Non-interactive `cli.py` subcommands are
  unchanged.
- No behavior change to the underlying `service.*` functions; changes live in the
  setup CLI layer (`setup.py`).

## Design

### 1. Reordered menu — happy path is 1-2-3-4

```
NHM setup

Workspace root: …   Current project: …   Active model: …   USGS API key: …

  ── Guided setup (do these in order) ──
  1. Set workspace root
  2. Create project
  3. Copy example model
  4. Launch Jupyter

  ── More options ──
  5. Open existing project
  6. Import model folder
  7. Set active model
  8. Generate NHM notebooks
  9. Show current setup
 10. Set USGS WaterData API key
  0. Exit
```

- Two section headers ("Guided setup" / "More options") guide the eye down 1→4.
- `print_main_menu` is rewritten to emit the new layout.
- The number dispatch in `run_setup` is remapped to the new order. The underlying
  `action_*` functions are reused as-is except where noted in sections 2 and 3.

### 2. Auto-chaining "actives" so defaults just work

- **Create project (2)** already sets `state.current_project`. Unchanged.
- **Copy example model (3)** — after a successful copy, **auto-set the copied
  model as the active model** for the current project (previously a separate
  manual step). Implemented by calling the existing
  `service.set_active_model(...)` inside `action_copy_example_model` after the
  copy succeeds.
- **Import model folder (6)** — same auto-set-active behavior after a successful
  import, inside `action_import_model`.
- **Set active model (7)** remains for the multi-model case (switching the active
  model among several).

Net effect: 1 → 2 → 3 leaves the user with a workspace, a current project, and an
active model, with no manual "set active" step.

### 3. Launch = generate-if-needed + launch + loading feedback (4)

`action_launch_jupyter` is extended (order matters):

1. Guard: require a current project (existing behavior).
2. **Auto-generate notebooks if missing or stale** for the current project via
   the existing `notebook_builder.convert_workflow("nhm", …)` path used by
   `action_generate_nhm_notebooks`. "Missing/stale" = the project's NHM notebook
   directory has no notebooks, or the `.py` templates are newer than the
   generated `.ipynb` files. Refactor the shared generate logic so both option 8
   and launch call one helper (no duplication).
3. Print **"Loading JupyterLab…"** *before* starting the wait.
4. Start Jupyter with the existing `subprocess.Popen`. Keep the existing
   immediate-exit error check (`proc.poll()` returns non-None → report and
   return).
5. **Poll for readiness** instead of a blind fixed sleep: call an injectable
   `readiness_probe(callable) -> bool` (default probes `jupyter server list` /
   the local server URL) on a short interval up to a timeout (default ~30s).
   - On ready: print the server URL/confirmation and return to the menu.
   - On timeout while the process is still alive: print "JupyterLab is still
     starting — its URL will appear above shortly" and return to the menu.
6. Menu-stays-available behavior: control returns to the `while True` loop as
   today, but only after the loading/readiness feedback, so the menu no longer
   clobbers Jupyter's startup output.

### 4. Error handling

- All existing guarded errors (`FileNotFoundError`, `NotADirectoryError`,
  `ValueError`, `OSError`) continue to be caught by the loop's try/except.
- Auto-set-active (sections 2) failures must not lose the copy/import result:
  wrap the `set_active_model` call so a failure prints a warning ("Model copied
  but could not be set active: …; use option 7") and still returns the created
  model path.
- Auto-generate-notebooks failure during launch aborts the launch with a clear
  message rather than launching against a project with no notebooks.
- JupyterLab-not-installed and start-failure paths are unchanged.

### 5. Testing

Follow the existing pattern in the test suite: `run_setup` and the `action_*`
functions already accept injectable `input_func`/`print_func`; extend with an
injectable readiness probe and clock/sleep for deterministic tests.

- **Menu layout**: assert `print_main_menu` emits the new order and section
  headers; assert the dispatch maps each number to the correct action.
- **Auto-active on copy/import**: after `action_copy_example_model` /
  `action_import_model`, assert `service.get_active_model_name` returns the new
  model; assert the copy result is still returned when set-active fails
  (inject a failing `set_active_model`).
- **Launch generates notebooks**: with no notebooks present, assert launch
  triggers generation; with fresh notebooks, assert it does not regenerate.
- **Loading/readiness**: inject a probe that reports "up" after N calls; assert
  "Loading JupyterLab…" is printed before readiness, the confirmation prints on
  ready, and the timeout message prints when the probe never reports up.

## Success criteria

- Running `pixi run setup` on a fresh machine and choosing 1 → 2 → 3 → 4 yields:
  workspace set, project created and current, example model copied and active,
  notebooks generated, JupyterLab launched.
- Selecting Launch prints "Loading JupyterLab…", waits for readiness, and returns
  to the menu without the menu overwriting Jupyter's startup output.
- All new and existing setup-CLI tests pass.
- No changes to `service.*` behavior or the non-interactive `cli.py` subcommands.
