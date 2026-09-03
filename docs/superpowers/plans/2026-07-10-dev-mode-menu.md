# Developer Mode Menu Option Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Developer mode" option to the setup menu that regenerates a chosen workflow's repo notebooks and launches JupyterLab against the repo (jupytext pairing), mirroring `pixi run dev`.

**Architecture:** Extract the shared Jupyter launch/readiness ceremony from `action_launch_jupyter` into a private `_launch_jupyter` helper in `src/assist/workspace/setup.py`; refactor `action_launch_jupyter` to use it; add `action_launch_dev_mode` that also uses it; wire a new "-- Contributor --" menu option (12) into `print_main_menu` and the `run_setup` dispatch.

**Tech Stack:** Python 3.11, `unittest` + `pytest`, `subprocess`, `jupytext`, existing `assist.workspace` package.

## Global Constraints

- All edits confined to `src/assist/workspace/setup.py` and `tests/test_workspace_setup.py`. No changes to `service.py`, `bridge.py`, `cli.py`, or `make_notebooks.py`.
- Branch: `enhance/simple-menu`. Confirm with `git branch --show-current` before starting.
- Tests use `unittest.TestCase` in `tests/test_workspace_setup.py`, run with `pytest`; inject `print_func`/`input_func`, patch with `unittest.mock`.
- `subprocess.Popen` must be invoked as a module attribute inside `_launch_jupyter` (NOT passed as a default arg) so existing tests patching `assist.workspace.setup.subprocess.Popen` keep working.
- Preserve `action_launch_jupyter`'s existing signature and observable behavior.
- Current menu on `enhance/simple-menu`: guided 1‑4, more-options 5 Open in VSCode, 6 open existing, 7 import, 8 set active, 9 generate, 10 show, 11 API key, 0 exit. This plan adds option 12 (Developer mode).
- Commits local only this session; do not push.
- Run the full module after each task: `pytest tests/test_workspace_setup.py -v`.

---

### Task 1: Extract `_launch_jupyter` and refactor `action_launch_jupyter`

**Files:**
- Modify: `src/assist/workspace/setup.py` (`action_launch_jupyter` and new helper)
- Test: `tests/test_workspace_setup.py` (existing launch tests must stay green)

**Interfaces:**
- Produces: `_launch_jupyter(command, *, cwd, ready_root, print_func=print, startup_probe_seconds=JUPYTER_STARTUP_PROBE_SECONDS, readiness_probe=None, readiness_timeout_seconds=30.0, readiness_poll_seconds=0.5, sleep_func=time.sleep) -> bool` — returns True if the process is running (ready or still starting), False on any failure path.
- `action_launch_jupyter` keeps its current signature and returns `project_root | None`.

- [ ] **Step 1: Run the existing launch tests to establish the green baseline**

Run: `pytest tests/test_workspace_setup.py -k launch_jupyter -v`
Expected: all PASS (these must remain green after the refactor — they are the safety net).

- [ ] **Step 2: Add `_launch_jupyter` and refactor `action_launch_jupyter`**

Replace the current `action_launch_jupyter` body (keep `_default_jupyter_readiness_probe` and `JUPYTER_STARTUP_PROBE_SECONDS` above it) with the helper + a thin action:

```python
def _launch_jupyter(
    command,
    *,
    cwd,
    ready_root,
    print_func=print,
    startup_probe_seconds: float = JUPYTER_STARTUP_PROBE_SECONDS,
    readiness_probe=None,
    readiness_timeout_seconds: float = 30.0,
    readiness_poll_seconds: float = 0.5,
    sleep_func=time.sleep,
) -> bool:
    pretty_command = " ".join(shlex.quote(part) for part in command)

    if importlib.util.find_spec("jupyterlab") is None:
        print_func("Error: JupyterLab is not installed in the current environment.")
        print_func(f"Command attempted: {pretty_command}")
        print_func("Install JupyterLab in this Pixi environment, then try again.")
        return False

    print_func(f"Launching: {pretty_command}")
    try:
        proc = subprocess.Popen(command, cwd=cwd)
    except (OSError, FileNotFoundError) as exc:
        print_func(f"Error: failed to start Jupyter: {exc}")
        print_func(f"Command attempted: {pretty_command}")
        return False

    sleep_func(startup_probe_seconds)
    return_code = proc.poll()
    if return_code is not None:
        print_func(f"Error: Jupyter exited immediately with code {return_code}.")
        print_func(f"Command attempted: {pretty_command}")
        print_func("Check the output above for the underlying error.")
        return False

    if readiness_probe is None:
        readiness_probe = lambda: _default_jupyter_readiness_probe(ready_root)

    print_func("Loading JupyterLab…")
    elapsed = 0.0
    ready = False
    while elapsed < readiness_timeout_seconds:
        if readiness_probe():
            ready = True
            break
        if proc.poll() is not None:
            print_func(
                f"Error: Jupyter exited while starting with code {proc.returncode}."
            )
            print_func("Check the output above for the underlying error.")
            return False
        sleep_func(readiness_poll_seconds)
        elapsed += readiness_poll_seconds

    if ready:
        print_func(f"JupyterLab is ready for {ready_root} (PID {proc.pid}).")
        print_func("Open the URL printed above in your browser.")
    else:
        print_func(
            "JupyterLab is still starting — its URL will appear above shortly."
        )
    return True


def action_launch_jupyter(
    state: SetupState,
    *,
    print_func=print,
    startup_probe_seconds: float = JUPYTER_STARTUP_PROBE_SECONDS,
    readiness_probe=None,
    readiness_timeout_seconds: float = 30.0,
    readiness_poll_seconds: float = 0.5,
    sleep_func=time.sleep,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    workspace_root = require_workspace_root(state)
    project_root = bridge.get_project_dir(workspace_root, state.current_project)

    if nhm_notebooks_need_generation(state):
        print_func("Generating NHM notebooks before launch…")
        generate_nhm_notebooks(state, print_func=print_func)

    command = [sys.executable, "-m", "jupyter", "lab", str(project_root)]
    ok = _launch_jupyter(
        command,
        cwd=project_root,
        ready_root=project_root,
        print_func=print_func,
        startup_probe_seconds=startup_probe_seconds,
        readiness_probe=readiness_probe,
        readiness_timeout_seconds=readiness_timeout_seconds,
        readiness_poll_seconds=readiness_poll_seconds,
        sleep_func=sleep_func,
    )
    return project_root if ok else None
```

- [ ] **Step 3: Run the existing launch tests to confirm the refactor is behavior-preserving**

Run: `pytest tests/test_workspace_setup.py -k launch_jupyter -v`
Expected: all PASS (uses_project_root, jupyterlab_missing, process_exits_immediately, popen_raises, generates_notebooks_when_needed, prints_loading_before_ready, reports_timeout_when_never_ready).

Note on the "ready" message: it now reads `JupyterLab is ready for <project_root>` — the existing test asserts substring `"is ready"`, which still matches.

- [ ] **Step 4: Run the full module and commit**

Run: `pytest tests/test_workspace_setup.py -v`
Expected: all PASS

```bash
git add src/assist/workspace/setup.py
git commit -m "refactor(setup): extract shared _launch_jupyter helper"
```

---

### Task 2: `action_launch_dev_mode`

**Files:**
- Modify: `src/assist/workspace/setup.py` (add `action_launch_dev_mode` after `action_launch_jupyter`)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `bridge.WORKFLOW_NAMES`, `prompt_menu_choice`, `notebook_builder.convert_workflow`, `bridge.get_workflow_notebooks_dir`, `_launch_jupyter` (Task 1).
- Produces: `action_launch_dev_mode(state, *, print_func=print, input_func=input, startup_probe_seconds=JUPYTER_STARTUP_PROBE_SECONDS, readiness_probe=None, readiness_timeout_seconds=30.0, readiness_poll_seconds=0.5, sleep_func=time.sleep) -> Path | None`.

- [ ] **Step 1: Write the failing test (builds the dev command for nhf)**

```python
    def test_action_launch_dev_mode_builds_dev_command(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )
        # bridge.WORKFLOW_NAMES == ("nhm", "nhf", "pest"); choose 2 -> nhf
        with patch.object(setup, "prompt_menu_choice", return_value=2), patch.object(
            setup.notebook_builder, "convert_workflow", return_value=[]
        ) as mock_convert, patch(
            "assist.workspace.setup.subprocess.Popen"
        ) as mock_popen:
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.pid = 999
            result = setup.action_launch_dev_mode(
                state,
                print_func=lambda *_: None,
                readiness_probe=lambda: True,
                sleep_func=lambda *_: None,
                startup_probe_seconds=0,
            )

        self.assertEqual(result, self.repo_root)
        mock_convert.assert_called_once_with("nhf")
        command = mock_popen.call_args.args[0]
        self.assertEqual(command[:4], [sys.executable, "-m", "jupyter", "lab"])
        self.assertIn(
            "--ServerApp.contents_manager_class=jupytext.TextFileContentsManager",
            command,
        )
        self.assertIn(f"--ServerApp.root_dir={self.repo_root}", command)
        self.assertIn(
            "--LabApp.default_url=/lab/tree/nhf_assist/notebooks", command
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_launch_dev_mode_builds_dev_command -v`
Expected: FAIL — `AttributeError: ... has no attribute 'action_launch_dev_mode'`

- [ ] **Step 3: Implement `action_launch_dev_mode`**

Add immediately after `action_launch_jupyter`:

```python
def action_launch_dev_mode(
    state: SetupState,
    *,
    print_func=print,
    input_func=input,
    startup_probe_seconds: float = JUPYTER_STARTUP_PROBE_SECONDS,
    readiness_probe=None,
    readiness_timeout_seconds: float = 30.0,
    readiness_poll_seconds: float = 0.5,
    sleep_func=time.sleep,
) -> Path | None:
    workflows = list(bridge.WORKFLOW_NAMES)
    print_func("")
    print_func("Developer mode regenerates repo notebooks from templates and")
    print_func("launches JupyterLab against the repo (edits sync to .py source).")
    print_func("Choose a workflow:")
    print_func("0. Cancel")
    for idx, name in enumerate(workflows, start=1):
        print_func(f"{idx}. {name}")

    choice = prompt_menu_choice(
        len(workflows),
        input_func=input_func,
        print_func=print_func,
    )
    if choice == 0:
        print_func("Developer mode cancelled.")
        return None

    workflow = workflows[choice - 1]
    repo_root = state.repo_root

    print_func(f"Regenerating {workflow} notebooks from templates…")
    notebook_builder.convert_workflow(workflow)

    notebook_dir = bridge.get_workflow_notebooks_dir(workflow)
    rel = notebook_dir.relative_to(repo_root).as_posix()
    command = [
        sys.executable,
        "-m",
        "jupyter",
        "lab",
        "--ServerApp.contents_manager_class=jupytext.TextFileContentsManager",
        f"--ServerApp.root_dir={repo_root}",
        f"--LabApp.default_url=/lab/tree/{rel}",
    ]

    ok = _launch_jupyter(
        command,
        cwd=repo_root,
        ready_root=repo_root,
        print_func=print_func,
        startup_probe_seconds=startup_probe_seconds,
        readiness_probe=readiness_probe,
        readiness_timeout_seconds=readiness_timeout_seconds,
        readiness_poll_seconds=readiness_poll_seconds,
        sleep_func=sleep_func,
    )
    return repo_root if ok else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_launch_dev_mode_builds_dev_command -v`
Expected: PASS

- [ ] **Step 5: Write the regenerate + cancel tests**

```python
    def test_action_launch_dev_mode_regenerates_selected_workflow(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )
        with patch.object(setup, "prompt_menu_choice", return_value=1), patch.object(
            setup.notebook_builder, "convert_workflow", return_value=[]
        ) as mock_convert, patch(
            "assist.workspace.setup.subprocess.Popen"
        ) as mock_popen:
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.pid = 1
            setup.action_launch_dev_mode(
                state,
                print_func=lambda *_: None,
                readiness_probe=lambda: True,
                sleep_func=lambda *_: None,
                startup_probe_seconds=0,
            )

        mock_convert.assert_called_once_with("nhm")

    def test_action_launch_dev_mode_cancel_returns_none(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )
        with patch.object(setup, "prompt_menu_choice", return_value=0), patch(
            "assist.workspace.setup.subprocess.Popen"
        ) as mock_popen:
            result = setup.action_launch_dev_mode(
                state,
                print_func=lambda *_: None,
            )

        self.assertIsNone(result)
        mock_popen.assert_not_called()
```

- [ ] **Step 6: Run the dev-mode tests**

Run: `pytest tests/test_workspace_setup.py -k launch_dev_mode -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): add action_launch_dev_mode (regenerate + launch against repo)"
```

---

### Task 3: Wire "Developer mode" into the menu (option 12) + dispatch

**Files:**
- Modify: `src/assist/workspace/setup.py` (`print_main_menu`, `run_setup` dispatch)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `action_launch_dev_mode` (Task 2).
- Produces: menu shows a "-- Contributor --" divider and "12. Developer mode (edit notebook templates)"; dispatch `12 → action_launch_dev_mode`; max choice 12.

- [ ] **Step 1: Write the failing menu-layout test**

```python
    def test_print_main_menu_includes_developer_mode_at_12(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )
        printed: list[str] = []
        setup.print_main_menu(state, print_func=printed.append)
        text = "\n".join(printed)

        self.assertIn("Contributor", text)
        self.assertIn("12. Developer mode (edit notebook templates)", text)
        self.assertLess(
            text.index("11. Set USGS WaterData API key"),
            text.index("12. Developer mode (edit notebook templates)"),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_print_main_menu_includes_developer_mode_at_12 -v`
Expected: FAIL — no "12. Developer mode" line.

- [ ] **Step 3: Update `print_main_menu`**

Replace the `print_func(" 11. Set USGS WaterData API key")` / `print_func("  0. Exit")` tail with:

```python
    print_func(" 11. Set USGS WaterData API key")
    print_func("")
    print_func("  -- Contributor --")
    print_func(" 12. Developer mode (edit notebook templates)")
    print_func("  0. Exit")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_print_main_menu_includes_developer_mode_at_12 -v`
Expected: PASS

- [ ] **Step 5: Extend the dispatch test**

Add case 12 to `test_run_setup_dispatch_maps_new_numbers` (append to the `cases` dict):

```python
            11: "action_set_api_key",
            12: "action_launch_dev_mode",
        }
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_run_setup_dispatch_maps_new_numbers -v`
Expected: FAIL — dispatch has no case 12 and max choice is 11.

- [ ] **Step 7: Update the dispatch in `run_setup`**

Change `prompt_menu_choice(11, ...)` to `prompt_menu_choice(12, ...)`, and add after the `choice == 11` branch:

```python
                elif choice == 12:
                    action_launch_dev_mode(
                        state,
                        print_func=print_func,
                        input_func=input_func,
                    )
```

- [ ] **Step 8: Run the dispatch test and full module**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_run_setup_dispatch_maps_new_numbers -v`
Expected: PASS

Run: `pytest tests/test_workspace_setup.py -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): add Developer mode menu option (12)"
```

---

### Task 4: Full verification

**Files:** none

- [ ] **Step 1: Full setup module**

Run: `pytest tests/test_workspace_setup.py -v`
Expected: all PASS.

- [ ] **Step 2: Full suite**

Run: `pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 3: Manual render**

Run:
```bash
pixi run -e default python -c "
from pathlib import Path
from assist.workspace import setup
state = setup.SetupState(repo_root=Path('.').resolve(), workspace_root=Path('~/nhm-workspace').expanduser())
setup.print_main_menu(state, print_func=print)
"
```
Expected: "-- Contributor --" divider with "12. Developer mode (edit notebook templates)" above "0. Exit".
