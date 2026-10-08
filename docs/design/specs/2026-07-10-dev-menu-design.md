# `pixi run dev` → interactive Developer menu

**Date:** 2026-07-10
**Branch:** `enhance/simple-menu`
**Status:** Approved design — ready for implementation plan

## Problem

`pixi run dev` is a one-shot shell command (regenerate notebooks from templates,
then launch JupyterLab), driven by `{{workflow}}`/`{{notebook_dir}}` args. It has
no interactive menu. Contributors want `pixi run dev` to open a dedicated
Developer menu with the common contributor actions.

## Goal & constraints

- `pixi run dev` opens an interactive **Developer menu** (menu-only; drop the
  positional args).
- The menu offers: launch dev mode (regenerate + JupyterLab), regenerate only,
  open repo in VSCode, regenerate ALL workflows.
- **DRY:** reuse the existing `action_launch_dev_mode`; extract a shared
  `_launch_vscode` helper so project-open and repo-open share code.
- Changes span `src/assist/workspace/setup.py` (menu + actions), `cli.py` (new
  `dev` subcommand), `pyproject.toml` (`dev` task), and the test file. No changes
  to `service.py`, `bridge.py`, or `make_notebooks.py`.

## Design

### 1. `run_dev_menu()` (new, in `setup.py`)

A standalone contributor menu loop, separate from `run_setup`:

```
Developer menu

  1. Launch dev mode (regenerate + JupyterLab)
  2. Regenerate notebooks (no launch)
  3. Open repo in VSCode
  4. Regenerate ALL workflows
  0. Exit
```

- Signature: `run_dev_menu(*, repo_root=None, print_func=print, input_func=input) -> int`.
- Builds `state = SetupState(repo_root=<resolved>, workspace_root=None)` using
  `bridge.resolve_repo_root()` when `repo_root` is None (mirrors `run_setup`).
- Loops: `print_dev_menu(...)` → `prompt_menu_choice(4, ...)` → dispatch. `0`
  prints "Exiting developer menu." and returns 0. Actions are wrapped in the same
  `except (FileNotFoundError, NotADirectoryError, ValueError, OSError)` handler as
  `run_setup`. `KeyboardInterrupt` returns 130.
- `print_dev_menu(state, *, print_func=print)` prints the header + the 5 lines.

### 2. Actions

- **1 → `action_launch_dev_mode`** (already exists): prompts workflow → regenerate
  repo notebooks → launch JupyterLab against the repo. Reused unchanged.
- **2 → `action_regenerate_workflow(state, *, print_func=print, input_func=input)`**
  (new): prompt for a workflow (`bridge.WORKFLOW_NAMES`, `0` = cancel), call
  `notebook_builder.convert_workflow(workflow)`, print the repo notebook dir
  (`bridge.get_workflow_notebooks_dir(workflow)`). Returns the list of created
  paths, or `None` on cancel.
- **3 → `action_open_repo_in_vscode(state, *, print_func=print, input_func=input,
  which=shutil.which, launcher=subprocess.Popen, candidates=None, max_retries=3)`**
  (new): open `code <repo_root>` via `_launch_vscode` (below). No workflow prompt,
  no regeneration — contributors edit the `.py` templates directly.
- **4 → `action_regenerate_all_workflows(state, *, print_func=print)`** (new):
  for each name in `bridge.WORKFLOW_NAMES`, call
  `notebook_builder.convert_workflow(name)`; print a per-workflow line. Returns the
  list of workflow names regenerated.

### 3. DRY: extract `_launch_vscode`

Pull the find-`code` + prompt/retry + launch + fallback out of the current
`action_open_in_vscode` into:

```
_launch_vscode(target_root, *, extra_paths=(), print_func=print, input_func=input,
               which=shutil.which, launcher=subprocess.Popen, candidates=None,
               max_retries=3) -> Path | None
```

Behavior (unchanged from today's `action_open_in_vscode` internals): resolve `code`
via `_find_code_executable`; if missing, print the install guidance and prompt
`Press Enter when done to retry, or type 's' to skip:` up to `max_retries`; on skip
or exhaustion print `Open this folder in VSCode manually: <target_root>` and return
`None`; otherwise launch `launcher([code_path, str(target_root), *extra_paths])`,
handling `OSError`/`FileNotFoundError` with an error + manual-path message; on
success print `Opening <target_root> in VSCode…` and return `target_root`.

Refactor `action_open_in_vscode` to: require project, resolve `project_root`,
generate notebooks if needed, compute `first_nb` and call
`_launch_vscode(project_root, extra_paths=[str(first_nb)] if first_nb.exists() else [], …)`.
Its existing tests remain valid (same messages/args).

`action_open_repo_in_vscode` simply calls
`_launch_vscode(state.repo_root, print_func=…, input_func=…, which=…, launcher=…,
candidates=…, max_retries=…)`.

### 4. Entry point + pixi task

- **`cli.py`**: add a `dev` subparser (no args) and, in `main`, `if args.command
  == "dev": return run_dev_menu()`. Import `run_dev_menu` from
  `assist.workspace.setup`.
- **`pyproject.toml`**: change the `dev` task to
  `dev = { cmd = "python -m assist.workspace.cli dev", default-environment =
  "default", description = "Contributor mode: interactive developer menu to
  regenerate notebook templates and launch JupyterLab/VSCode against the repo." }`
  — remove the `args` array.

The setup menu's option 12 (Developer mode) stays as-is.

### 5. Error handling

- Cancel on any workflow prompt (`0`) → clean return, no side effects.
- VSCode not found → prompt/retry, then manual-path message (via `_launch_vscode`).
- JupyterLab launch failures handled by `_launch_jupyter` (unchanged).
- `convert_workflow` errors caught by the dev-menu loop's try/except.

### 6. Testing

- `run_dev_menu` / `print_dev_menu`: menu shows the 4 options + exit; dispatch maps
  `1→action_launch_dev_mode`, `2→action_regenerate_workflow`,
  `3→action_open_repo_in_vscode`, `4→action_regenerate_all_workflows`; `0` exits.
  (Use a `_run_dev_menu_once` helper mirroring `_run_setup_once`, patching the
  action + `prompt_menu_choice`.)
- `action_regenerate_workflow`: asserts `convert_workflow(<chosen>)` called; cancel
  (`0`) → not called, returns `None`.
- `action_regenerate_all_workflows`: asserts `convert_workflow` called once per
  name in `bridge.WORKFLOW_NAMES`.
- `action_open_repo_in_vscode`: asserts `launcher` called with `[code, repo_root]`
  when `which` resolves; skip path prints manual message and does not launch.
- `_launch_vscode` behavior verified via both `action_open_in_vscode` (existing
  tests, unchanged) and `action_open_repo_in_vscode`.
- `cli.build_parser`: `parse_args(["dev"]).command == "dev"`.

## Success criteria

- `pixi run dev` opens the Developer menu; each option performs its action.
- `_launch_vscode` exists once and is used by both project-open and repo-open.
- `action_launch_dev_mode` is reused (not duplicated).
- `cli.py` accepts `dev`; the pixi `dev` task points at the menu.
- New and existing tests pass.
