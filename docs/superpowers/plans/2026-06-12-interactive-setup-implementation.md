# Interactive Setup Command Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-platform `pixi run setup` command that interactively guides users through NHM workspace setup while preserving the existing explicit workspace commands.

**Architecture:** Keep the new prompt/menu behavior in a new `assist.workspace.setup` module so the CLI stays thin and existing business logic remains in `assist.workspace.service`. Persist only `NHM_ASSIST_WORKSPACE_ROOT` in the repo-root ignored `.env`, keep selected project session-local, and continue storing the active model in `project_config/active_model.yaml`. Call notebook generation directly through `workflow_templates.make_notebooks.convert_workflow()` and launch Jupyter with `sys.executable -m jupyter lab <project-root>`.

**Tech Stack:** Python 3.11, argparse, pathlib, subprocess, python-dotenv, unittest, Pixi tasks

---

## File structure

### New files

- Create: `src/assist/workspace/setup.py`
- Create: `tests/test_workspace_setup.py`

### Modified files

- Modify: `src/assist/workspace/cli.py`
- Modify: `src/assist/workspace/__init__.py`
- Modify: `pyproject.toml`

### Existing files referenced but not expected to change

- Reference: `src/assist/workspace/service.py`
- Reference: `src/assist/workspace/bridge.py`
- Reference: `src/workflow_templates/make_notebooks.py`
- Reference: `tests/test_multi_model_workspace.py`

### Responsibility split

- `src/assist/workspace/setup.py`
  Own the interactive loop, `.env` read/write helpers, session-local current-project state, project/model action wrappers, notebook generation wrapper, and Jupyter launch wrapper.

- `src/assist/workspace/cli.py`
  Add a `setup` subcommand and dispatch to `setup.run_setup()`.

- `src/assist/workspace/__init__.py`
  Export the new `run_setup` entrypoint if that is consistent with the existing package surface.

- `pyproject.toml`
  Add the `setup` Pixi task.

- `tests/test_workspace_setup.py`
  Cover `.env` behavior, menu action orchestration, notebook generation dispatch, and Jupyter launch command construction.

---

## Task 1: Add focused failing tests for setup state, dispatch, and launch behavior

**Files:**
- Create: `tests/test_workspace_setup.py`
- Reference: `src/assist/workspace/cli.py`
- Reference: `src/workflow_templates/make_notebooks.py`

- [ ] **Step 1: Write the failing test for reading a missing workspace root from `.env`**

```python
def test_load_workspace_root_returns_none_when_dotenv_missing(self):
    repo_root = self.tmp_path / "repo"
    repo_root.mkdir()

    result = setup.load_workspace_root_from_dotenv(repo_root)

    self.assertIsNone(result)
```

- [ ] **Step 2: Write the failing test for writing `NHM_ASSIST_WORKSPACE_ROOT` to repo-root `.env`**

```python
def test_save_workspace_root_writes_repo_dotenv(self):
    repo_root = self.tmp_path / "repo"
    repo_root.mkdir()
    workspace_root = self.tmp_path / "workspace"

    setup.save_workspace_root_to_dotenv(repo_root, workspace_root)

    dotenv_text = (repo_root / ".env").read_text(encoding="utf-8")
    self.assertIn("NHM_ASSIST_WORKSPACE_ROOT=", dotenv_text)
    self.assertIn(str(workspace_root.resolve()), dotenv_text)
```

- [ ] **Step 3: Write the failing test for creating a project through the setup action wrapper**

```python
def test_action_create_project_sets_current_project(self):
    state = setup.SetupState(repo_root=self.repo_root, workspace_root=self.workspace_root)

    with patch.object(setup, "prompt_required_text", side_effect=["Project_A"]):
        setup.action_create_project(state, print_func=lambda *_: None)

    self.assertEqual(state.current_project, "Project_A")
    self.assertTrue((self.workspace_root / "Project_A" / "models").is_dir())
```

- [ ] **Step 4: Write the failing test for selecting an existing project**

```python
def test_action_open_project_selects_existing_project(self):
    service.create_project(self.workspace_root, "Project_A")
    service.create_project(self.workspace_root, "Project_B")
    state = setup.SetupState(repo_root=self.repo_root, workspace_root=self.workspace_root)

    with patch.object(setup, "prompt_menu_choice", return_value=2):
        setup.action_open_project(state, print_func=lambda *_: None)

    self.assertEqual(state.current_project, "Project_B")
```

- [ ] **Step 5: Write the failing test for refusing project-dependent actions without a current project**

```python
def test_require_current_project_returns_false_without_selection(self):
    state = setup.SetupState(repo_root=self.repo_root, workspace_root=self.workspace_root)
    printed = []

    ok = setup.require_current_project(state, print_func=printed.append)

    self.assertFalse(ok)
    self.assertTrue(any("Select or create a project first." in line for line in printed))
```

- [ ] **Step 6: Write the failing test for notebook generation dispatch**

```python
def test_action_generate_nhm_notebooks_calls_convert_workflow(self):
    state = setup.SetupState(
        repo_root=self.repo_root,
        workspace_root=self.workspace_root,
        current_project="Project_A",
    )

    with patch.object(setup.notebook_builder, "convert_workflow", return_value=[] ) as mock_convert:
        setup.action_generate_nhm_notebooks(state, print_func=lambda *_: None)

    mock_convert.assert_called_once_with(
        "nhm",
        workspace_root=self.workspace_root,
        project_name="Project_A",
        dry_run=False,
    )
```

- [ ] **Step 7: Write the failing test for launching Jupyter from the project root**

```python
def test_action_launch_jupyter_uses_project_root(self):
    state = setup.SetupState(
        repo_root=self.repo_root,
        workspace_root=self.workspace_root,
        current_project="Project_A",
    )

    with patch("assist.workspace.setup.subprocess.Popen") as mock_popen:
        setup.action_launch_jupyter(state, print_func=lambda *_: None)

    command = mock_popen.call_args.args[0]
    self.assertEqual(
        command,
        [sys.executable, "-m", "jupyter", "lab", str(self.workspace_root / "Project_A")],
    )
```

- [ ] **Step 8: Write the failing test for CLI parser support**

```python
def test_build_parser_supports_setup_command(self):
    parser = cli.build_parser()
    args = parser.parse_args(["setup"])
    self.assertEqual(args.command, "setup")
```

- [ ] **Step 9: Run the targeted tests to verify they fail for the expected reasons**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_workspace_setup.py -q
```

Expected:

- import or attribute failures for setup helpers that do not exist yet
- parser failure until `setup` is added to `cli.py`

- [ ] **Step 10: Commit the red test scaffold**

```bash
git add tests/test_workspace_setup.py
git commit -m "test: define interactive setup behavior"
```

---

## Task 2: Add the new setup module with `.env` helpers and session state

**Files:**
- Create: `src/assist/workspace/setup.py`
- Test: `tests/test_workspace_setup.py`

- [ ] **Step 1: Create the setup session state container**

Use a small dataclass:

```python
@dataclass
class SetupState:
    repo_root: Path
    workspace_root: Path | None = None
    current_project: str | None = None
```

- [ ] **Step 2: Add helper to resolve repo-root `.env` path**

```python
def get_repo_dotenv_path(repo_root: Path) -> Path:
    return repo_root / ".env"
```

- [ ] **Step 3: Add helper to load workspace root from `.env`**

Prefer `dotenv_values()`:

```python
def load_workspace_root_from_dotenv(repo_root: Path) -> Path | None:
    dotenv_path = get_repo_dotenv_path(repo_root)
    if not dotenv_path.exists():
        return None
    values = dotenv_values(dotenv_path)
    value = values.get("NHM_ASSIST_WORKSPACE_ROOT")
    return Path(value).expanduser().resolve() if value else None
```

- [ ] **Step 4: Add helper to save workspace root to `.env`**

Use `set_key()` so unrelated `.env` values survive:

```python
def save_workspace_root_to_dotenv(repo_root: Path, workspace_root: str | Path) -> Path:
    dotenv_path = get_repo_dotenv_path(repo_root)
    resolved = Path(workspace_root).expanduser().resolve()
    if not dotenv_path.exists():
        dotenv_path.touch()
    set_key(str(dotenv_path), "NHM_ASSIST_WORKSPACE_ROOT", str(resolved))
    return dotenv_path
```

- [ ] **Step 5: Add a helper for prompting required text values**

Keep prompting centralized:

```python
def prompt_required_text(prompt: str, *, input_func=input) -> str:
    ...
```

- [ ] **Step 6: Add a helper for yes/no confirmation**

```python
def prompt_yes_no(prompt: str, *, default: bool = True, input_func=input) -> bool:
    ...
```

- [ ] **Step 7: Add a helper for numeric menu choices**

```python
def prompt_menu_choice(max_choice: int, *, input_func=input, print_func=print) -> int:
    ...
```

- [ ] **Step 8: Run the targeted tests to verify the new helpers satisfy the first test group**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_workspace_setup.py -q
```

Expected:

- the `.env` tests pass
- action and CLI tests still fail

- [ ] **Step 9: Commit the helper layer**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat: add setup state and dotenv helpers"
```

---

## Task 3: Implement project and model action wrappers on top of the service layer

**Files:**
- Modify: `src/assist/workspace/setup.py`
- Test: `tests/test_workspace_setup.py`
- Reference: `src/assist/workspace/service.py`

- [ ] **Step 1: Add `require_workspace_root()` helper**

This should:

- use the current session state if present
- otherwise load from repo-root `.env`
- otherwise prompt
- create the folder if the user approves
- save back to `.env`

- [ ] **Step 2: Add `require_current_project()` helper**

```python
def require_current_project(state: SetupState, *, print_func=print) -> bool:
    if state.current_project is None:
        print_func("Select or create a project first.")
        return False
    return True
```

- [ ] **Step 3: Implement `action_set_workspace_root()`**

This should prompt, ensure the directory exists, save to `.env`, update state, and print the resolved path.

- [ ] **Step 4: Implement `action_create_project()`**

This should prompt for the project name, call `service.create_project()`, set `state.current_project`, and print the project path.

- [ ] **Step 5: Implement `action_open_project()`**

This should list `service.get_projects()`, prompt by number, set `state.current_project`, and print the new selection.

- [ ] **Step 6: Implement `action_copy_example_model()`**

This should:

- require a current project
- prompt for model name and example name
- call `service.copy_example_model()`
- print the target model path

- [ ] **Step 7: Implement `action_import_model()`**

This should:

- require a current project
- prompt for model name and source path
- call `service.import_model()`
- print the target model path

- [ ] **Step 8: Implement `action_set_active_model()`**

This should list models, prompt by number, call `service.set_active_model()`, and print the config file path.

- [ ] **Step 9: Add tests for the action wrappers if additional gaps remain**

Likely needed:

- import action rejects bad path cleanly
- set-active-model refuses empty model list

- [ ] **Step 10: Run the setup tests to verify action behavior**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_workspace_setup.py -q
```

Expected:

- `.env` and action tests pass
- notebook generation / Jupyter launch / CLI setup tests may still fail

- [ ] **Step 11: Commit the action layer**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat: add interactive setup project actions"
```

---

## Task 4: Implement notebook generation and Jupyter launch actions

**Files:**
- Modify: `src/assist/workspace/setup.py`
- Test: `tests/test_workspace_setup.py`
- Reference: `src/workflow_templates/make_notebooks.py`

- [ ] **Step 1: Import notebook conversion function directly**

Use:

```python
from workflow_templates import make_notebooks as notebook_builder
```

- [ ] **Step 2: Implement `action_generate_nhm_notebooks()`**

This should:

- require a current project
- call:

```python
notebook_builder.convert_workflow(
    "nhm",
    workspace_root=state.workspace_root,
    project_name=state.current_project,
    dry_run=False,
)
```

- [ ] **Step 3: Print the notebook target directory after generation**

Use `bridge.get_project_workflow_notebooks_dir("nhm", ...)` so the status message matches actual path logic.

- [ ] **Step 4: Implement `action_launch_jupyter()`**

Launch the project root, not `notebooks/nhm`:

```python
subprocess.Popen(
    [sys.executable, "-m", "jupyter", "lab", str(project_root)],
    cwd=project_root,
)
```

Why this form:

- uses the current Pixi Python
- avoids depending on shell command resolution
- keeps Jupyter rooted at the project path

- [ ] **Step 5: Print a short status line after the launch command is started**

Example:

```text
Launching Jupyter for C:\Users\alice\nhm-workspace\Columbia_Study
```

- [ ] **Step 6: Run the setup tests to verify generation and launch behavior**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_workspace_setup.py -q
```

Expected:

- notebook generation dispatch test passes
- Jupyter launch command test passes

- [ ] **Step 7: Commit the notebook and launch actions**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat: add setup notebook and launch actions"
```

---

## Task 5: Add the menu loop and CLI/Pixi entrypoints

**Files:**
- Modify: `src/assist/workspace/setup.py`
- Modify: `src/assist/workspace/cli.py`
- Modify: `src/assist/workspace/__init__.py`
- Modify: `pyproject.toml`
- Test: `tests/test_workspace_setup.py`
- Reference: `tests/test_multi_model_workspace.py`

- [ ] **Step 1: Add a `show_current_setup()` helper**

This should print:

- workspace root
- current project
- current project path if selected
- available models if project selected
- active model if present
- notebook directory if project selected

- [ ] **Step 2: Add a `print_menu()` helper**

Keep the menu content in one place so it is easy to update.

- [ ] **Step 3: Add `run_setup()` main loop**

Pseudo-shape:

```python
def run_setup(*, input_func=input, print_func=print) -> int:
    state = SetupState(repo_root=resolve_repo_root())
    state.workspace_root = load_workspace_root_from_dotenv(state.repo_root)
    ensure_workspace_root_for_setup(state, input_func=input_func, print_func=print_func)
    while True:
        print_menu(state, print_func=print_func)
        choice = prompt_menu_choice(9, input_func=input_func, print_func=print_func)
        ...
        if choice == 0:
            return 0
```

- [ ] **Step 4: Add the `setup` subcommand to `cli.py`**

Add:

```python
setup_parser = subparsers.add_parser("setup")
```

and dispatch:

```python
if args.command == "setup":
    return run_setup()
```

- [ ] **Step 5: Import `run_setup` into `cli.py`**

Use a direct import from `assist.workspace.setup`.

- [ ] **Step 6: Export `run_setup` from `src/assist/workspace/__init__.py` if package-level access is useful**

Add the import and `__all__` entry if it fits the existing pattern.

- [ ] **Step 7: Add the Pixi task**

In `pyproject.toml`:

```toml
setup = { cmd = "python -m assist.workspace.cli setup", default-environment = "default" }
```

- [ ] **Step 8: Add parser coverage if needed in an existing CLI-focused test module**

If the new parser assertion fits better in `tests/test_multi_model_workspace.py`, add a small targeted test there instead of duplicating it.

- [ ] **Step 9: Run the full setup test file and the existing workspace tests**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_workspace_setup.py tests/test_multi_model_workspace.py tests/test_model_notebook_generation.py -q
```

Expected:

- all tests pass

- [ ] **Step 10: Commit the menu and entrypoint integration**

```bash
git add src/assist/workspace/setup.py src/assist/workspace/cli.py src/assist/workspace/__init__.py pyproject.toml tests/test_workspace_setup.py tests/test_multi_model_workspace.py
git commit -m "feat: add interactive setup command"
```

---

## Task 6: Smoke-test the interactive setup flow end to end

**Files:**
- No new production files expected
- Reference: `src/assist/workspace/setup.py`

- [ ] **Step 1: Run the focused automated test suite first**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_workspace_setup.py tests/test_multi_model_workspace.py tests/test_model_notebook_generation.py -q
```

Expected:

- PASS

- [ ] **Step 2: Run `pixi task list` and verify `setup` appears**

Run:

```bash
pixi task list
```

Expected:

- includes `setup`

- [ ] **Step 3: Run an interactive smoke flow using a temporary workspace**

Use:

```bash
WORKSPACE=/private/tmp/nhm-assist-setup-smoke
```

Then in `pixi run setup`:

- set workspace root to that path
- create `Columbia_Study`
- copy example model `Walla_Walla`
- set active model to `Walla_Walla`
- generate NHM notebooks
- show current setup

- [ ] **Step 4: Verify resulting filesystem**

Confirm these exist:

```text
/private/tmp/nhm-assist-setup-smoke/Columbia_Study/project_config/active_model.yaml
/private/tmp/nhm-assist-setup-smoke/Columbia_Study/notebooks/nhm/0_workspace_setup.ipynb
/private/tmp/nhm-assist-setup-smoke/Columbia_Study/models/Walla_Walla/inputs/source_data/control.default.bandit
```

- [ ] **Step 5: Verify `.env` contains the configured workspace root**

Run:

```bash
sed -n '1,40p' .env
```

Expected:

- includes `NHM_ASSIST_WORKSPACE_ROOT=/private/tmp/nhm-assist-setup-smoke`

- [ ] **Step 6: Optionally verify Jupyter launch command without leaving a lingering server**

Prefer a mocked or short-lived check over a manual long-running process unless the user specifically wants a live smoke test.

- [ ] **Step 7: Commit only if smoke-test-driven code changes were needed**

If no code changed during smoke testing, skip this commit.

---

## Final verification checklist

- [ ] `tests/test_workspace_setup.py` passes
- [ ] `tests/test_multi_model_workspace.py` still passes
- [ ] `tests/test_model_notebook_generation.py` still passes
- [ ] `pixi task list` shows `setup`
- [ ] interactive setup flow creates projects/models using existing service logic
- [ ] notebook generation writes to `<workspace>/<project>/notebooks/nhm/`
- [ ] Jupyter launch targets `<workspace>/<project>` rather than `notebooks/nhm`
- [ ] `.env` stores only `NHM_ASSIST_WORKSPACE_ROOT`

---

## Notes for implementation

- Do not move active-model state into `.env`.
- Do not shell out to `pixi run notebooks-project` from inside `setup`; call Python conversion directly.
- Do not shell out to `pixi run jupyter lab ...` from inside `setup`; use `sys.executable -m jupyter lab ...`.
- Keep prompt text short and plain so it behaves well in Windows PowerShell.
- Keep the first version NHM-only. If future work adds NHF/PEST setup flows, add them as explicit follow-up tasks rather than prebuilding extra abstractions now.
