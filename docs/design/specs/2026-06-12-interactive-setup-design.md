# Interactive Setup Command Design

## Goal

Add a cross-platform interactive `pixi run setup` command that guides a user through common NHM workspace actions without replacing the existing explicit commands.

The command should feel native for macOS, Linux, and Windows PowerShell users, while preserving the current project-shared workspace model:

- one shared NHM notebook set per project
- one active model selected per project
- model-local runtime and output isolation

## Why this exists

The current Pixi command surface is good for scripting and documentation, but it assumes the user already knows:

- which workspace root to use
- whether they need to create or open a project
- when to copy vs import a model
- how to set the active model
- when to generate notebooks
- where to launch Jupyter from

That is fine for contributors and repeat users, but it creates friction for first-run and casual users.

We want a friendly entrypoint that answers:

- "Do you want to create a project or open one?"
- "Do you want to copy an example or import an existing model?"
- "Which model should be active?"
- "Do you want me to generate notebooks and launch Jupyter now?"

## Recommended approach

Implement `setup` as an interactive Python menu layered on top of the existing service functions.

This design is preferred over shell prompts or a heavier stateful shell because it:

- works the same way on macOS, Linux, and Windows
- keeps business logic in the existing service layer
- preserves the explicit low-level commands for tests, docs, and scripting
- avoids nested `pixi run ...` calls from inside another Pixi task

## Scope

### In scope

- add a new `pixi run setup` task
- add a new CLI command named `setup`
- prompt the user for a workspace root when needed
- persist the workspace root in an ignored repo-local `.env`
- offer an interactive loop for the common project/model/notebook actions
- keep the selected project in memory for the current setup session
- read the active model from project config and write it through existing service logic
- launch Jupyter from the project root, not directly from `notebooks/nhm`

### Out of scope

- replacing the existing explicit commands
- storing project selection in `.env`
- storing active model in `.env`
- building a curses UI or rich TUI
- supporting NHF and PEST setup flows in this first version
- moving config persistence to a global user-home config file

## `.env` contract

For the first version, `.env` should stay repo-local and ignored.

That matches the current notebook behavior, where existing code already loads:

- `root_dir / ".env"` in normal local use
- `Path.home() / ".env"` only for Nebari-specific cases

### Stored keys

Only one key should be written by `setup`:

```text
NHM_ASSIST_WORKSPACE_ROOT=<absolute path>
```

Examples:

```text
NHM_ASSIST_WORKSPACE_ROOT=/Users/alice/nhm-workspace
```

```text
NHM_ASSIST_WORKSPACE_ROOT=C:\Users\alice\nhm-workspace
```

### What should not be stored in `.env`

Do not store:

- project name
- model name
- active model
- runtime path
- notebook path

Those are either session-local choices or project-owned state.

### Precedence

When `setup` needs a workspace root, use:

1. workspace root already chosen during the current setup session
2. `NHM_ASSIST_WORKSPACE_ROOT` from repo-root `.env`
3. prompt the user

## User experience

## First run

If `.env` does not exist or does not define `NHM_ASSIST_WORKSPACE_ROOT`, startup should prompt:

```text
No workspace root is configured.
Enter workspace root:
```

If the folder does not exist:

```text
Create this folder? [Y/n]
```

After confirmation:

- create the folder
- write or update `.env`
- enter the setup menu

## Repeat run

If `.env` already defines a workspace root:

```text
Workspace root: C:\Users\alice\nhm-workspace
```

Then enter the menu immediately.

## Main menu

The menu should be simple text, using numeric choices:

```text
NHM setup

Workspace root: C:\Users\alice\nhm-workspace
Current project: Columbia_Study
Active model: Walla_Walla

1. Set workspace root
2. Create project
3. Open project
4. Copy example model
5. Import model folder
6. Set active model
7. Generate NHM notebooks
8. Launch Jupyter
9. Show current setup
0. Exit
```

### Important state split

- workspace root: persisted in `.env`
- current project: in-memory only for the active setup session
- active model: persisted in `<workspace>/<project>/project_config/active_model.yaml`

That keeps user convenience separate from project truth.

## Menu actions

### 1. Set workspace root

Prompt for a path.

Behavior:

- accept absolute or user-home-expanded paths
- create the folder if approved by the user
- save the absolute resolved path to repo-root `.env`
- update current session state

### 2. Create project

Prompt for project name.

Behavior:

- require a workspace root
- call `create_project(...)`
- set this project as the current project in memory
- print the resulting project path

### 3. Open project

Behavior:

- require a workspace root
- list projects under the workspace root
- prompt the user to choose by number
- set the chosen project as the current project in memory

If no projects exist, print a friendly message and return to the menu.

### 4. Copy example model

Behavior:

- require a current project
- ask for model name
- ask for example name
- call `copy_example_model(...)`
- print the target model path

The example source should still resolve through `assist.workspace.examples`.

### 5. Import model folder

Behavior:

- require a current project
- ask for model name
- ask for source folder path
- call `import_model(...)`
- print the normalized model path

### 6. Set active model

Behavior:

- require a current project
- list available models
- prompt by number
- call `set_active_model(...)`
- print the active model config path

### 7. Generate NHM notebooks

Behavior:

- require a current project
- call notebook generation directly in Python, not by shelling out to `pixi`
- target:

```text
<workspace>/<project>/notebooks/nhm/
```

This should call the same conversion logic used by `make_notebooks.py`.

### 8. Launch Jupyter

Behavior:

- require a current project
- launch `jupyter lab <workspace>/<project>`
- do not launch at `<workspace>/<project>/notebooks/nhm`

Launching at the project root avoids the stale path / 404 problem seen when Jupyter is rooted too deep in the tree.

Implementation should invoke `jupyter lab` directly with `subprocess`, using the already-active Pixi environment, instead of calling nested `pixi run ...`.

### 9. Show current setup

Print:

- workspace root
- current project
- current project path
- available models for the current project
- active model from `active_model.yaml` if present
- notebook directory path

### 0. Exit

Return success and leave the environment unchanged.

## Architecture

### Existing files to keep using

#### `src/assist/workspace/service.py`

This remains the owner of:

- project creation
- model creation
- example copy
- external model import
- active model persistence
- runtime preparation

The `setup` flow should call into this file rather than reimplementing filesystem logic.

#### `src/assist/workspace/bridge.py`

This remains the owner of:

- repo root resolution
- workspace root resolution
- project/model path construction
- notebook path construction

The setup flow should use it for path normalization and notebook target paths.

#### `src/workflow_templates/make_notebooks.py`

This remains the owner of notebook conversion behavior.

The setup flow should call its Python conversion function directly instead of shelling out.

### New file

Add a new focused module:

```text
src/assist/workspace/setup.py
```

This file should own:

- interactive prompts
- menu loop
- repo-root `.env` read/write helpers
- current session state for selected project
- orchestration of service calls
- Jupyter launch helper

This keeps `cli.py` thin and avoids mixing prompt-heavy code into the command parser.

### `cli.py` changes

`src/assist/workspace/cli.py` should:

- add a `setup` subcommand
- dispatch to `assist.workspace.setup.run_setup(...)`

It should not own the menu logic itself.

### `pyproject.toml` changes

Add a new task:

```toml
setup = { cmd = "python -m assist.workspace.cli setup", default-environment = "default" }
```

No arguments should be required for the setup task.

## Error handling

### Missing workspace root

If none exists in memory or `.env`, prompt for it instead of failing.

### Invalid menu selection

Print a short error and redisplay the menu.

### Missing current project

For project-dependent actions, print:

```text
Select or create a project first.
```

Then return to the menu.

### No models in project

For model-dependent actions, print:

```text
No models exist for this project yet.
```

Then return to the menu.

### Bad import path

If the import source is not a directory, show the error cleanly and return to the menu.

### Launch failures

If `jupyter lab` fails to start, report the exact command and error text.

## Testing strategy

Add a new test module:

```text
tests/test_workspace_setup.py
```

Cover at least:

1. loading a missing `.env`
2. reading an existing workspace root from `.env`
3. writing `NHM_ASSIST_WORKSPACE_ROOT` to `.env`
4. creating a project through the setup orchestration layer
5. selecting an existing project from a listed set
6. refusing model actions when no current project is selected
7. generating project-shared notebooks through the setup flow
8. launching Jupyter from the project root command, not `notebooks/nhm`

The tests should stub:

- `input()`
- `print()` where needed
- `subprocess` for Jupyter launch

and should call the setup orchestration functions directly rather than trying to test a full interactive terminal session end-to-end.

## Non-goals for this version

Do not add:

- colored terminal UI requirements
- arrow-key navigation
- stored "last project" state
- NHF/Pest setup flows
- automatic notebook execution
- automatic active-model selection after model import unless explicitly chosen by the user

## Success criteria

The feature is successful when:

1. a new user can run `pixi run setup`
2. the command prompts for workspace root if needed
3. the command stores the workspace root in ignored repo-root `.env`
4. the user can create or open a project without remembering low-level commands
5. the user can copy/import a model and set it active
6. the user can generate NHM notebooks
7. the user can launch Jupyter from the correct project root
8. the existing explicit Pixi commands still work unchanged
