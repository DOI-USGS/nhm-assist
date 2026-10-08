# "Developer mode" menu option

**Date:** 2026-07-10
**Branch:** `enhance/simple-menu`
**Status:** Approved design — ready for implementation plan

## Problem

Contributors who edit the notebook *templates* (`src/workflow_templates/<workflow>/*.py`)
use `pixi run dev`: it regenerates notebooks from the `.py` templates into the
**repo's** notebook directory and launches JupyterLab against the repo with the
jupytext contents manager, so `.ipynb` edits sync back to the `.py` source. This
is a separate pixi task with no presence in the interactive `pixi run setup` menu.
There should be a menu option for it too.

## Goal & constraints

- Add a **"Developer mode"** menu option that regenerates repo notebooks for a
  chosen workflow and launches JupyterLab against the repo (jupytext pairing),
  mirroring `pixi run dev`.
- **DRY:** the Jupyter launch/readiness ceremony is shared between the existing
  `action_launch_jupyter` and the new dev-mode action via one private helper.
- Guided **1‑4** and existing options **5‑11** unchanged; dev mode is a
  contributor action, visually separated.
- Changes confined to `src/assist/workspace/setup.py` + its test file. No changes
  to `service.py`, `bridge.py`, `cli.py`, or `make_notebooks.py`.

## Design

### 1. Shared launch helper `_launch_jupyter`

Extract the common ceremony from `action_launch_jupyter` into:

```
_launch_jupyter(command, *, cwd, ready_root, print_func=print,
                startup_probe_seconds=JUPYTER_STARTUP_PROBE_SECONDS,
                readiness_probe=None, readiness_timeout_seconds=30.0,
                readiness_poll_seconds=0.5, sleep_func=time.sleep) -> bool
```

Behavior (identical to today's launch): if `jupyterlab` is not importable, print
the install error and return `False`; print `Launching: <cmd>`; start the process
with `subprocess.Popen(command, cwd=cwd)` (called as a module attribute so tests
can patch `assist.workspace.setup.subprocess.Popen`); on `OSError`/`FileNotFoundError`
print the failure and return `False`; `sleep_func(startup_probe_seconds)` then
`proc.poll()` immediate-exit check (return `False` on non-None); default
`readiness_probe` to `lambda: _default_jupyter_readiness_probe(ready_root)`; print
`Loading JupyterLab…`; poll to readiness/timeout with the same messages; return
`True` when the process is running (ready or still starting).

**`subprocess.Popen` is invoked directly inside the helper (not passed as a default
argument)** so the existing tests that patch `assist.workspace.setup.subprocess.Popen`
keep working.

### 2. Refactor `action_launch_jupyter` to use the helper

Signature and behavior unchanged (keeps `startup_probe_seconds`, `readiness_probe`,
`readiness_timeout_seconds`, `readiness_poll_seconds`, `sleep_func`). Body:

```
require current project; workspace_root; project_root = bridge.get_project_dir(...)
if nhm_notebooks_need_generation(state): generate
command = [sys.executable, "-m", "jupyter", "lab", str(project_root)]
ok = _launch_jupyter(command, cwd=project_root, ready_root=project_root,
                     print_func=..., startup_probe_seconds=..., readiness_probe=...,
                     readiness_timeout_seconds=..., readiness_poll_seconds=..., sleep_func=...)
return project_root if ok else None
```

Existing launch tests remain valid: they patch `subprocess.Popen`, pass
`startup_probe_seconds=0` / `readiness_probe` / `sleep_func`, and assert on the
`Popen` command and printed messages — all unchanged observable behavior.

### 3. New action `action_launch_dev_mode`

```
action_launch_dev_mode(state, *, print_func=print, input_func=input,
                       startup_probe_seconds=JUPYTER_STARTUP_PROBE_SECONDS,
                       readiness_probe=None, readiness_timeout_seconds=30.0,
                       readiness_poll_seconds=0.5, sleep_func=time.sleep) -> Path | None
```

1. **Prompt for workflow.** List `bridge.WORKFLOW_NAMES` (`nhm`, `nhf`, `pest`)
   as a numbered menu with `nhm` first and `0` = cancel; read with
   `prompt_menu_choice(len(workflows), ...)`. On `0`, print "Developer mode
   cancelled." and return `None`.
2. **Regenerate repo notebooks** for the chosen workflow:
   `notebook_builder.convert_workflow(workflow)` (no `workspace_root` → writes to
   the repo notebook dir). Always regenerate (dev mode's purpose). Print a
   "Regenerating <workflow> notebooks…" line.
3. **Build the dev launch command** (mirrors `pixi run dev`):
   ```
   repo_root = state.repo_root
   notebook_dir = bridge.get_workflow_notebooks_dir(workflow)
   rel = notebook_dir.relative_to(repo_root).as_posix()
   command = [sys.executable, "-m", "jupyter", "lab",
              "--ServerApp.contents_manager_class=jupytext.TextFileContentsManager",
              f"--ServerApp.root_dir={repo_root}",
              f"--LabApp.default_url=/lab/tree/{rel}"]
   ```
4. **Launch via the shared helper** with `cwd=repo_root`, `ready_root=repo_root`,
   forwarding the probe/sleep args. Return `repo_root` if `ok` else `None`.

Dev mode does **not** require a workspace/project — it operates on the repo.

### 4. Menu placement

Append a contributor subsection to "More options":

```
  -- More options --
  5. Open in VSCode
  6. Open existing project
  7. Import model folder
  8. Set active model
  9. Generate NHM notebooks
 10. Show current setup
 11. Set USGS WaterData API key

  -- Contributor --
 12. Developer mode (edit notebook templates)
  0. Exit
```

`print_main_menu` gains the divider + option 12. `run_setup` dispatch: max choice
becomes 12; `12 → action_launch_dev_mode`.

### 5. Error handling

- Workflow prompt cancel (`0`) → clean return, no launch.
- All launch failure modes handled inside `_launch_jupyter` (jupyterlab missing,
  Popen raises, immediate exit) — same as today.
- `convert_workflow` errors surface via the loop's existing
  `except (FileNotFoundError, NotADirectoryError, ValueError, OSError)` handler.

### 6. Testing

- `_launch_jupyter` is exercised through both actions (no separate direct test
  required, but its behavior is asserted via the action tests).
- `action_launch_jupyter`: existing tests unchanged and still green after refactor.
- `action_launch_dev_mode`:
  - builds the correct command — asserts the `jupytext.TextFileContentsManager`
    flag, `--ServerApp.root_dir=<repo_root>`, and the workflow-specific
    `--LabApp.default_url=/lab/tree/<rel>` (e.g. `nhf` → `nhf_assist/notebooks`).
    Patch `subprocess.Popen`, `notebook_builder.convert_workflow`,
    `prompt_menu_choice`; pass `readiness_probe=lambda: True`, `sleep_func=lambda *_: None`.
  - regenerates the chosen workflow: asserts `convert_workflow(workflow)` called.
  - cancel: `prompt_menu_choice` returns `0` → no `Popen`, returns `None`.
- Menu/dispatch: `print_main_menu` shows the "-- Contributor --" divider and
  "12. Developer mode (edit notebook templates)"; `run_setup` dispatch maps
  `12 → action_launch_dev_mode`; max choice is 12.

## Success criteria

- Selecting "Developer mode" prompts for a workflow, regenerates that workflow's
  repo notebooks, and launches JupyterLab against the repo with the jupytext
  contents manager and the correct default URL.
- The launch/readiness ceremony exists once (`_launch_jupyter`), used by both
  Launch Jupyter and Developer mode.
- Guided 1‑4 and options 5‑11 unchanged; dev mode is option 12 under a Contributor
  divider.
- New and existing setup-CLI tests pass.
