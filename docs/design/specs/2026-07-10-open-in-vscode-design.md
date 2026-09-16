# "Open in VSCode" launcher for the setup menu

**Date:** 2026-07-10
**Branch:** `enhance/simple-menu`
**Status:** Approved design — ready for implementation plan

## Problem

The setup menu (`pixi run setup` → `assist.workspace.setup`) can launch JupyterLab
against the active project, but many users prefer to work in **VSCode** (the
native `.ipynb` editor + Python/Jupyter extensions). Today there is no guided way
to open the project in VSCode; a user must find the workspace path and open it
manually.

## Goal & constraints

- Add a menu option that **opens the current project in VSCode**, focused on the
  first notebook, mirroring the existing "Launch Jupyter" experience.
- Work even when the `code` CLI is not on `PATH`: locate it in well-known install
  locations, and if still missing, **prompt the user to install it and retry**,
  so the user can always proceed.
- Keep the guided **1‑2‑3‑4** happy path intact.
- Changes confined to the setup CLI layer (`src/assist/workspace/setup.py`) plus a
  short README note. No changes to `service.*`, `bridge.*`, `cli.py`, or
  `make_notebooks.py`.

## Design

### 1. Locating the `code` executable — `_find_code_executable`

A helper that returns a path to the VSCode CLI or `None`:

1. `shutil.which("code")` — honors `PATH`.
2. If not found, probe well-known locations for the current platform:
   - macOS: `/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code`
   - Linux: `/usr/share/code/bin/code`, `/snap/bin/code`
   - Windows: `%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd`
3. Return the first existing path, else `None`.

The `PATH` lookup and the candidate list are injectable for testing
(`which=shutil.which`, `candidates=<platform list>`).

### 2. Menu action — `action_open_in_vscode`

Mirrors `action_launch_jupyter`:

1. Require a current project (existing `require_current_project` guard).
2. Resolve `project_root = bridge.get_project_dir(workspace_root, current_project)`.
3. **Auto-generate notebooks if missing/stale** via `nhm_notebooks_need_generation`
   + `generate_nhm_notebooks` (same reuse as launch) so the first notebook exists.
4. `code_path = _find_code_executable()`.
5. **If not found → prompt-and-retry loop** (bounded, default 3 attempts):
   - Print install guidance:
     `In VSCode: Cmd/Ctrl+Shift+P → "Shell Command: Install 'code' command in PATH".`
   - Prompt: `Press Enter when done to retry, or type 's' to skip:` (via injected
     `input_func`).
   - On `s`/skip → print the manual path
     (`Open this folder in VSCode manually: <project_root>`) and return `None`.
   - Otherwise re-run `_find_code_executable()`; break when found.
   - Note (documented in the message): a `code` install that only edits a shell
     profile won't be visible to this running process; symlink-based installs into
     an already-on-PATH dir (the common case) are picked up on retry, and the
     well-known-path probe covers the rest.
6. Build the launch args:
   - `args = [code_path, str(project_root)]`
   - `first_nb = project_root / "notebooks" / "nhm" / "0_workspace_setup.ipynb"`
   - if `first_nb.exists()`: `args.append(str(first_nb))`
7. Launch via injected `launcher=subprocess.Popen`. On `OSError`/`FileNotFoundError`,
   print an error + the manual path and return `None`.
8. Print confirmation: `Opening <project_root> in VSCode…` and return `project_root`.

Signature:
`action_open_in_vscode(state, *, print_func=print, input_func=input, which=shutil.which, launcher=subprocess.Popen, candidates=None, max_retries=3) -> Path | None`

### 3. Menu placement

Guided block **1‑4 unchanged**. Insert **"Open in VSCode"** as the first "More
options" entry (new option **5**), shifting the current 5–10 down by one:

```
  -- Guided setup (do these in order) --
  1. Set workspace root
  2. Create project
  3. Copy example model
  4. Launch Jupyter

  -- More options --
  5. Open in VSCode
  6. Open existing project
  7. Import model folder
  8. Set active model
  9. Generate NHM notebooks
 10. Show current setup
 11. Set USGS WaterData API key
  0. Exit
```

`print_main_menu` and the `run_setup` dispatch are updated: max choice becomes 11,
`5 → action_open_in_vscode`, and 6–11 map to the previously-numbered actions
(open project, import model, set active model, generate notebooks, show setup,
API key).

### 4. README note

A short subsection under "Quick start" (README.md): mention the "Open in VSCode"
menu option, that it opens the project + first notebook, and that it needs the
`code` command — with the one-line install hint (Command Palette → "Shell Command:
Install 'code' command in PATH"). One paragraph.

### 5. Error handling

- `code` not found and user skips → manual-path message, return `None` (no crash).
- Launcher raises `OSError`/`FileNotFoundError` → error + manual path, return `None`.
- Notebook generation failure → surfaces via the existing generation path; abort
  the open with a clear message rather than opening an empty project.

### 6. Testing (mirror the launch-jupyter tests)

- `_find_code_executable`: returns the `which` hit; falls back to a candidate path
  that exists; returns `None` when neither is present (inject `which` + candidates).
- `action_open_in_vscode`:
  - launches `code <project_root> <first_nb>` when found and the notebook exists;
    opens just the folder when the notebook is absent.
  - generates notebooks when needed (patch `nhm_notebooks_need_generation`/
    `generate_nhm_notebooks`).
  - prompt-and-retry: `which` returns `None` then a path on the second call →
    asserts the install message printed and the launch happened.
  - skip path: `which` returns `None`, `input_func` returns `"s"` → asserts the
    manual-path message and no launch.
- Menu/dispatch: `print_main_menu` shows "5. Open in VSCode" and the shifted
  numbering; `run_setup` dispatch maps 5 → `action_open_in_vscode` and 6–11 to the
  shifted actions.

## Success criteria

- Selecting "Open in VSCode" opens the current project (and `0_workspace_setup.ipynb`)
  in VSCode when `code` is resolvable, generating notebooks first if needed.
- When `code` is not resolvable, the user is guided to install it and can retry or
  skip; nothing crashes.
- Guided 1‑4 path is unchanged; new option is 5 under "More options".
- New and existing setup-CLI tests pass; README documents the option.
