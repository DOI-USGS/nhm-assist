# Simplified Setup Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pixi run setup` a linear guided flow where a new user clicks 1 → 2 → 3 → 4 to reach a fully-configured, launched JupyterLab, with active model auto-set and a clear "loading" state during launch.

**Architecture:** All changes live in the interactive setup CLI layer, `src/assist/workspace/setup.py`. The underlying `service.*` and `bridge.*` functions and the non-interactive `cli.py` subcommands are unchanged. Copy/import actions auto-set the new model active; launch auto-generates notebooks when missing/stale and polls Jupyter for readiness behind a "Loading JupyterLab…" message; the main menu is reordered into a "Guided setup" block (1–4) and a "More options" block (5–10).

**Tech Stack:** Python 3.11, `unittest` + `pytest` runner, `subprocess`/`jupyter_server`, existing `assist.workspace` package.

## Global Constraints

- All edits confined to `src/assist/workspace/setup.py` and its test file `tests/test_workspace_setup.py`. No changes to `service.py`, `bridge.py`, `cli.py`, or `make_notebooks.py`.
- Tests use `unittest.TestCase` in `tests/test_workspace_setup.py`, run with `pytest`. Follow the existing style: inject `print_func`/`input_func`, patch with `unittest.mock.patch`/`patch.object`.
- Preserve all existing public function names and their current keyword arguments; only add new keyword arguments with defaults (backward compatible).
- No real subprocess launches, real sleeps, or real Jupyter servers in tests — inject probes/sleep.
- Commits are local only this session; do not push. (Per user instruction for this session.)
- Run the full setup test module after each task: `pytest tests/test_workspace_setup.py -v`.

---

### Task 1: Auto-set copied example model as active

**Files:**
- Modify: `src/assist/workspace/setup.py` (`action_copy_example_model`, ~274-312)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `service.copy_example_model(workspace_root, project_name, model_name, example_name) -> dict[str, Path]`; `service.set_active_model(workspace_root, *, project_name, model_name) -> Path`; `service.get_active_model_name(workspace_root, project_name) -> str`.
- Produces: `action_copy_example_model` now sets the copied model active before returning `paths["model"]`; on set-active failure it prints a warning and still returns `paths["model"]`.

- [ ] **Step 1: Write the failing test (auto-active on copy)**

Add to `WorkspaceSetupTests` in `tests/test_workspace_setup.py`:

```python
    def test_action_copy_example_model_sets_copied_model_active(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        model_dir = self.workspace_root / "Project_A" / "models" / "Walla_Walla"

        with patch.object(
            setup,
            "list_available_example_names",
            return_value=["Rogue_River", "Walla_Walla"],
        ), patch.object(
            setup, "prompt_menu_choice", return_value=2
        ), patch.object(
            setup.service,
            "copy_example_model",
            return_value={"model": model_dir},
        ), patch.object(
            setup.service, "set_active_model"
        ) as mock_set_active:
            setup.action_copy_example_model(state, print_func=lambda *_: None)

        mock_set_active.assert_called_once_with(
            self.workspace_root,
            project_name="Project_A",
            model_name="Walla_Walla",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_copy_example_model_sets_copied_model_active -v`
Expected: FAIL — `set_active_model` not called (AssertionError: Expected 'set_active_model' to be called once. Called 0 times.)

- [ ] **Step 3: Add the auto-active call**

In `action_copy_example_model`, replace the tail (from the `paths = service.copy_example_model(...)` block through `return paths["model"]`) with:

```python
    workspace_root = require_workspace_root(state)
    paths = service.copy_example_model(
        workspace_root,
        state.current_project,
        model_name,
        example_name,
    )
    print_func(f"Copied example model to {paths['model']}")
    _set_model_active(
        state,
        model_name,
        workspace_root=workspace_root,
        print_func=print_func,
    )
    return paths["model"]
```

And add this helper above `action_copy_example_model`:

```python
def _set_model_active(
    state: SetupState,
    model_name: str,
    *,
    workspace_root: Path,
    print_func=print,
) -> None:
    try:
        service.set_active_model(
            workspace_root,
            project_name=state.current_project,
            model_name=model_name,
        )
        print_func(f"Active model set to {model_name}")
    except (FileNotFoundError, NotADirectoryError, ValueError, OSError) as exc:
        print_func(
            f"Model '{model_name}' is available but could not be set active: {exc}. "
            f"Use 'Set active model' to activate it."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_copy_example_model_sets_copied_model_active -v`
Expected: PASS

- [ ] **Step 5: Write the failing test (copy result preserved when set-active fails)**

```python
    def test_action_copy_example_model_returns_model_even_if_set_active_fails(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        model_dir = self.workspace_root / "Project_A" / "models" / "Walla_Walla"
        printed: list[str] = []

        with patch.object(
            setup,
            "list_available_example_names",
            return_value=["Walla_Walla"],
        ), patch.object(
            setup, "prompt_menu_choice", return_value=1
        ), patch.object(
            setup.service,
            "copy_example_model",
            return_value={"model": model_dir},
        ), patch.object(
            setup.service,
            "set_active_model",
            side_effect=ValueError("boom"),
        ):
            result = setup.action_copy_example_model(state, print_func=printed.append)

        self.assertEqual(result, model_dir)
        self.assertTrue(
            any("could not be set active" in line for line in printed),
            f"expected set-active warning, got: {printed}",
        )
```

- [ ] **Step 6: Run to verify pass (already handled by helper)**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_copy_example_model_returns_model_even_if_set_active_fails -v`
Expected: PASS (the `_set_model_active` helper swallows the error and returns the model)

- [ ] **Step 7: Run the full module and commit**

Run: `pytest tests/test_workspace_setup.py -v`
Expected: all PASS

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): auto-set copied example model as active"
```

---

### Task 2: Auto-set imported model as active

**Files:**
- Modify: `src/assist/workspace/setup.py` (`action_import_model`, ~315-334)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `service.import_model(workspace_root, project_name, model_name, source_dir) -> dict[str, Path]`; `_set_model_active` (from Task 1).
- Produces: `action_import_model` sets the imported model active before returning `paths["model"]`; warning-on-failure via `_set_model_active`.

- [ ] **Step 1: Write the failing test**

```python
    def test_action_import_model_sets_imported_model_active(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        model_dir = self.workspace_root / "Project_A" / "models" / "Imported_M"

        with patch.object(
            setup,
            "prompt_required_text",
            side_effect=["Imported_M", "/some/source"],
        ), patch.object(
            setup.service,
            "import_model",
            return_value={"model": model_dir},
        ), patch.object(
            setup.service, "set_active_model"
        ) as mock_set_active:
            setup.action_import_model(state, print_func=lambda *_: None)

        mock_set_active.assert_called_once_with(
            self.workspace_root,
            project_name="Project_A",
            model_name="Imported_M",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_import_model_sets_imported_model_active -v`
Expected: FAIL — `set_active_model` called 0 times.

- [ ] **Step 3: Add the auto-active call**

In `action_import_model`, replace the tail (from `paths = service.import_model(...)` through `return paths["model"]`) with:

```python
    workspace_root = require_workspace_root(state)
    paths = service.import_model(
        workspace_root,
        state.current_project,
        model_name,
        source_dir,
    )
    print_func(f"Imported model to {paths['model']}")
    _set_model_active(
        state,
        model_name,
        workspace_root=workspace_root,
        print_func=print_func,
    )
    return paths["model"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_import_model_sets_imported_model_active -v`
Expected: PASS

- [ ] **Step 5: Run the full module and commit**

Run: `pytest tests/test_workspace_setup.py -v`
Expected: all PASS

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): auto-set imported model as active"
```

---

### Task 3: Shared notebook generation helper + staleness detection

**Files:**
- Modify: `src/assist/workspace/setup.py` (`action_generate_nhm_notebooks`, ~374-395; add two helpers)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `notebook_builder.convert_workflow("nhm", workspace_root=..., project_name=..., dry_run=False) -> list[Path]`; `notebook_builder.WORKFLOW_INPUT_DIRS["nhm"] -> Path`; `bridge.get_project_workflow_notebooks_dir("nhm", workspace_root, project_name) -> Path`.
- Produces:
  - `generate_nhm_notebooks(state, *, print_func=print) -> list[Path]` — the extracted generation logic.
  - `nhm_notebooks_need_generation(state) -> bool` — True when the project's NHM notebook dir is missing/empty of `.ipynb`, or any template `.py` is newer than its generated `.ipynb`.
  - `action_generate_nhm_notebooks` delegates to `generate_nhm_notebooks`.

- [ ] **Step 1: Write the failing test (extracted helper is called by the action)**

```python
    def test_action_generate_nhm_notebooks_delegates_to_helper(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )

        with patch.object(
            setup, "generate_nhm_notebooks", return_value=[]
        ) as mock_gen:
            setup.action_generate_nhm_notebooks(state, print_func=lambda *_: None)

        mock_gen.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_generate_nhm_notebooks_delegates_to_helper -v`
Expected: FAIL — `AttributeError: <module 'assist.workspace.setup'> does not have the attribute 'generate_nhm_notebooks'`

- [ ] **Step 3: Extract the helper and add staleness detection**

Replace the whole `action_generate_nhm_notebooks` function with:

```python
def generate_nhm_notebooks(
    state: SetupState,
    *,
    print_func=print,
) -> list[Path]:
    workspace_root = require_workspace_root(state)
    created = notebook_builder.convert_workflow(
        "nhm",
        workspace_root=workspace_root,
        project_name=state.current_project,
        dry_run=False,
    )
    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        workspace_root,
        state.current_project,
    )
    print_func(f"Generated NHM notebooks in {notebook_dir}")
    return created


def nhm_notebooks_need_generation(state: SetupState) -> bool:
    if state.workspace_root is None or state.current_project is None:
        return True

    template_dir = notebook_builder.WORKFLOW_INPUT_DIRS["nhm"]
    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        state.workspace_root,
        state.current_project,
    )

    if not notebook_dir.exists() or not any(notebook_dir.rglob("*.ipynb")):
        return True

    for py_file in template_dir.rglob("*.py"):
        relative = py_file.relative_to(template_dir).with_suffix(".ipynb")
        target = notebook_dir / relative
        if not target.exists():
            return True
        if py_file.stat().st_mtime > target.stat().st_mtime:
            return True

    return False


def action_generate_nhm_notebooks(
    state: SetupState,
    *,
    print_func=print,
) -> list[Path] | None:
    if not require_current_project(state, print_func=print_func):
        return None
    return generate_nhm_notebooks(state, print_func=print_func)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_generate_nhm_notebooks_delegates_to_helper -v`
Expected: PASS

- [ ] **Step 5: Confirm the pre-existing convert_workflow test still passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_generate_nhm_notebooks_calls_convert_workflow -v`
Expected: PASS (the action still ultimately calls `convert_workflow` via the helper)

- [ ] **Step 6: Write failing tests for staleness detection**

```python
    def test_nhm_notebooks_need_generation_true_when_none_present(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )

        self.assertTrue(setup.nhm_notebooks_need_generation(state))

    def test_nhm_notebooks_need_generation_false_when_fresh(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        setup.generate_nhm_notebooks(state, print_func=lambda *_: None)

        self.assertFalse(setup.nhm_notebooks_need_generation(state))

    def test_nhm_notebooks_need_generation_true_when_template_newer(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        setup.generate_nhm_notebooks(state, print_func=lambda *_: None)

        notebook_dir = setup.bridge.get_project_workflow_notebooks_dir(
            "nhm", self.workspace_root, "Project_A"
        )
        for nb in notebook_dir.rglob("*.ipynb"):
            import os
            old = nb.stat().st_mtime - 10_000
            os.utime(nb, (old, old))

        self.assertTrue(setup.nhm_notebooks_need_generation(state))
```

- [ ] **Step 7: Run to verify these pass**

Run: `pytest tests/test_workspace_setup.py -k nhm_notebooks_need_generation -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): shared notebook generation helper + staleness check"
```

---

### Task 4: Launch auto-generates, shows loading, polls for readiness

**Files:**
- Modify: `src/assist/workspace/setup.py` (`action_launch_jupyter`, ~398-442; add default readiness probe)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `nhm_notebooks_need_generation(state)`, `generate_nhm_notebooks(state, print_func=...)` (Task 3); `subprocess.Popen`; injected `readiness_probe`/`sleep_func`.
- Produces: `action_launch_jupyter(state, *, print_func=print, startup_probe_seconds=JUPYTER_STARTUP_PROBE_SECONDS, readiness_probe=None, readiness_timeout_seconds=30.0, readiness_poll_seconds=0.5, sleep_func=time.sleep) -> Path | None`. Prints `"Loading JupyterLab…"` before the readiness wait; returns `project_root` on ready or timeout (process alive), `None` on the existing error paths.

- [ ] **Step 1: Write the failing test (auto-generate when notebooks missing)**

```python
    def test_action_launch_jupyter_generates_notebooks_when_needed(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )

        with patch.object(
            setup, "nhm_notebooks_need_generation", return_value=True
        ), patch.object(
            setup, "generate_nhm_notebooks", return_value=[]
        ) as mock_gen, patch(
            "assist.workspace.setup.subprocess.Popen"
        ) as mock_popen:
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.pid = 111
            setup.action_launch_jupyter(
                state,
                print_func=lambda *_: None,
                startup_probe_seconds=0,
                readiness_probe=lambda: True,
                sleep_func=lambda *_: None,
            )

        mock_gen.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_launch_jupyter_generates_notebooks_when_needed -v`
Expected: FAIL — `TypeError: action_launch_jupyter() got an unexpected keyword argument 'readiness_probe'`

- [ ] **Step 3: Rewrite `action_launch_jupyter` and add the default probe**

Replace `action_launch_jupyter` (keep the `JUPYTER_STARTUP_PROBE_SECONDS` constant above it) with:

```python
def _default_jupyter_readiness_probe(project_root: Path) -> bool:
    try:
        from jupyter_server.serverapp import list_running_servers
    except Exception:
        return True
    target = str(Path(project_root).resolve())
    for server in list_running_servers():
        root = server.get("root_dir") or server.get("notebook_dir") or ""
        if root and str(Path(root).resolve()) == target:
            return True
    return False


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
    project_root = bridge.get_project_dir(
        workspace_root,
        state.current_project,
    )

    if nhm_notebooks_need_generation(state):
        print_func("Generating NHM notebooks before launch…")
        generate_nhm_notebooks(state, print_func=print_func)

    command = [sys.executable, "-m", "jupyter", "lab", str(project_root)]
    pretty_command = " ".join(shlex.quote(part) for part in command)

    if importlib.util.find_spec("jupyterlab") is None:
        print_func("Error: JupyterLab is not installed in the current environment.")
        print_func(f"Command attempted: {pretty_command}")
        print_func("Install JupyterLab in this Pixi environment, then try again.")
        return None

    print_func(f"Launching: {pretty_command}")
    try:
        proc = subprocess.Popen(command, cwd=project_root)
    except (OSError, FileNotFoundError) as exc:
        print_func(f"Error: failed to start Jupyter: {exc}")
        print_func(f"Command attempted: {pretty_command}")
        return None

    sleep_func(startup_probe_seconds)
    return_code = proc.poll()
    if return_code is not None:
        print_func(f"Error: Jupyter exited immediately with code {return_code}.")
        print_func(f"Command attempted: {pretty_command}")
        print_func("Check the output above for the underlying error.")
        return None

    if readiness_probe is None:
        readiness_probe = lambda: _default_jupyter_readiness_probe(project_root)

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
            return None
        sleep_func(readiness_poll_seconds)
        elapsed += readiness_poll_seconds

    if ready:
        print_func(f"JupyterLab is ready for {project_root} (PID {proc.pid}).")
        print_func("Open the URL printed above in your browser.")
    else:
        print_func(
            "JupyterLab is still starting — its URL will appear above shortly."
        )
    return project_root
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_launch_jupyter_generates_notebooks_when_needed -v`
Expected: PASS

- [ ] **Step 5: Update the 3 existing launch tests for `sleep_func`**

The existing launch tests pass `startup_probe_seconds=0`; that still works because `sleep_func` defaults to `time.sleep` and `time.sleep(0)` is a no-op. Add `readiness_probe=lambda: True, sleep_func=lambda *_: None` to `test_action_launch_jupyter_uses_project_root` so it does not depend on a real Jupyter server:

```python
    def test_action_launch_jupyter_uses_project_root(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )

        with patch.object(
            setup, "nhm_notebooks_need_generation", return_value=False
        ), patch("assist.workspace.setup.subprocess.Popen") as mock_popen:
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.pid = 12345
            setup.action_launch_jupyter(
                state,
                print_func=lambda *_: None,
                startup_probe_seconds=0,
                readiness_probe=lambda: True,
                sleep_func=lambda *_: None,
            )

        command = mock_popen.call_args.args[0]
        self.assertEqual(
            command,
            [
                sys.executable,
                "-m",
                "jupyter",
                "lab",
                str(self.workspace_root / "Project_A"),
            ],
        )
```

Leave `test_action_launch_jupyter_reports_when_jupyterlab_missing`, `..._process_exits_immediately`, and `..._popen_raises` as-is except adding `sleep_func=lambda *_: None` alongside their existing `startup_probe_seconds=0` argument so they never sleep. Also patch `nhm_notebooks_need_generation` to `return_value=False` in the immediate-exit and popen-raises tests so generation is skipped:

```python
        with patch.object(
            setup, "nhm_notebooks_need_generation", return_value=False
        ), patch("assist.workspace.setup.subprocess.Popen") as mock_popen:
            mock_popen.return_value.poll.return_value = 1
            mock_popen.return_value.returncode = 1
            mock_popen.return_value.pid = 12345
            result = setup.action_launch_jupyter(
                state,
                print_func=printed.append,
                startup_probe_seconds=0,
                sleep_func=lambda *_: None,
            )
```

(The jupyterlab-missing test needs no `nhm_notebooks_need_generation` patch because generation runs before the find_spec check; patch it to `return_value=False` there too to keep that test isolated from the filesystem.)

- [ ] **Step 6: Write the loading/readiness behavior tests**

```python
    def test_action_launch_jupyter_prints_loading_before_ready(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        printed: list[str] = []
        calls = {"n": 0}

        def probe():
            calls["n"] += 1
            return calls["n"] >= 3

        with patch.object(
            setup, "nhm_notebooks_need_generation", return_value=False
        ), patch("assist.workspace.setup.subprocess.Popen") as mock_popen:
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.pid = 222
            result = setup.action_launch_jupyter(
                state,
                print_func=printed.append,
                startup_probe_seconds=0,
                readiness_probe=probe,
                sleep_func=lambda *_: None,
            )

        self.assertEqual(result, self.workspace_root / "Project_A")
        loading_idx = next(i for i, l in enumerate(printed) if "Loading JupyterLab" in l)
        ready_idx = next(i for i, l in enumerate(printed) if "is ready" in l)
        self.assertLess(loading_idx, ready_idx)

    def test_action_launch_jupyter_reports_timeout_when_never_ready(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        printed: list[str] = []

        with patch.object(
            setup, "nhm_notebooks_need_generation", return_value=False
        ), patch("assist.workspace.setup.subprocess.Popen") as mock_popen:
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.pid = 333
            result = setup.action_launch_jupyter(
                state,
                print_func=printed.append,
                startup_probe_seconds=0,
                readiness_probe=lambda: False,
                readiness_timeout_seconds=1.0,
                readiness_poll_seconds=0.5,
                sleep_func=lambda *_: None,
            )

        self.assertEqual(result, self.workspace_root / "Project_A")
        self.assertTrue(
            any("still starting" in line for line in printed),
            f"expected timeout message, got: {printed}",
        )
```

- [ ] **Step 7: Run all launch tests**

Run: `pytest tests/test_workspace_setup.py -k launch_jupyter -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): launch auto-generates notebooks, shows loading, polls readiness"
```

---

### Task 5: Reorder the main menu into guided (1–4) + more (5–10)

**Files:**
- Modify: `src/assist/workspace/setup.py` (`print_main_menu`, ~510-533; dispatch in `run_setup`, ~563-621)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: all `action_*` functions.
- Produces: new menu order and dispatch mapping —
  `1 → action_set_workspace_root`, `2 → action_create_project`, `3 → action_copy_example_model`, `4 → action_launch_jupyter`, `5 → action_open_project`, `6 → action_import_model`, `7 → action_set_active_model`, `8 → action_generate_nhm_notebooks`, `9 → action_show_current_setup`, `10 → action_set_api_key`, `0 → exit`.

- [ ] **Step 1: Write the failing test (menu order + headers)**

```python
    def test_print_main_menu_lists_guided_then_more_options(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )
        printed: list[str] = []

        setup.print_main_menu(state, print_func=printed.append)
        text = "\n".join(printed)

        # Guided block, in order
        self.assertIn("Guided setup", text)
        self.assertIn("1. Set workspace root", text)
        self.assertIn("2. Create project", text)
        self.assertIn("3. Copy example model", text)
        self.assertIn("4. Launch Jupyter", text)
        # More options block
        self.assertIn("More options", text)
        self.assertIn("5. Open existing project", text)
        self.assertIn("6. Import model folder", text)
        self.assertIn("7. Set active model", text)
        self.assertIn("8. Generate NHM notebooks", text)
        self.assertIn("9. Show current setup", text)
        self.assertIn("10. Set USGS WaterData API key", text)
        self.assertIn("0. Exit", text)
        # Guided header appears before the More options header
        self.assertLess(text.index("Guided setup"), text.index("More options"))
        # Launch (4) appears before Open existing project (5)
        self.assertLess(text.index("4. Launch Jupyter"), text.index("5. Open existing project"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_print_main_menu_lists_guided_then_more_options -v`
Expected: FAIL — old menu has "2. Create project" but "3. Open project"/"8. Launch Jupyter", so assertions on the new order fail.

- [ ] **Step 3: Rewrite `print_main_menu`**

Replace the option-printing block (lines printing "1. …" through "0. Exit") with:

```python
    print_func("")
    print_func("  -- Guided setup (do these in order) --")
    print_func("  1. Set workspace root")
    print_func("  2. Create project")
    print_func("  3. Copy example model")
    print_func("  4. Launch Jupyter")
    print_func("")
    print_func("  -- More options --")
    print_func("  5. Open existing project")
    print_func("  6. Import model folder")
    print_func("  7. Set active model")
    print_func("  8. Generate NHM notebooks")
    print_func("  9. Show current setup")
    print_func(" 10. Set USGS WaterData API key")
    print_func("  0. Exit")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_print_main_menu_lists_guided_then_more_options -v`
Expected: PASS

- [ ] **Step 5: Write the failing dispatch test**

```python
    def _run_setup_once(self, choice, action_name):
        # workspace root is configured so run_setup skips first-run prompt
        setup.save_workspace_root_to_dotenv(self.repo_root, self.workspace_root)
        answers = iter([str(choice), "0"])
        with patch.object(setup, action_name) as mock_action, patch.object(
            setup, "prompt_menu_choice", side_effect=[choice, 0]
        ):
            setup.run_setup(
                repo_root=self.repo_root,
                print_func=lambda *_: None,
                input_func=lambda *_: next(answers),
            )
        return mock_action

    def test_run_setup_dispatch_maps_new_numbers(self):
        cases = {
            2: "action_create_project",
            3: "action_copy_example_model",
            4: "action_launch_jupyter",
            5: "action_open_project",
            6: "action_import_model",
            7: "action_set_active_model",
            8: "action_generate_nhm_notebooks",
            9: "action_show_current_setup",
            10: "action_set_api_key",
        }
        for choice, action_name in cases.items():
            with self.subTest(choice=choice):
                mock_action = self._run_setup_once(choice, action_name)
                mock_action.assert_called_once()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_run_setup_dispatch_maps_new_numbers -v`
Expected: FAIL — old dispatch maps e.g. `4 → copy example`, not `action_launch_jupyter`.

- [ ] **Step 7: Remap the dispatch in `run_setup`**

Replace the `if choice == 1:` block and the `try: if choice == 2 … elif choice == 10:` chain with this mapping (keep the surrounding `while True`, `prompt_menu_choice(10, …)`, exit-on-0, and the `except (FileNotFoundError, NotADirectoryError, ValueError, OSError)` wrapper unchanged):

```python
            if choice == 1:
                action_set_workspace_root(
                    state,
                    print_func=print_func,
                    input_func=input_func,
                )
                continue

            try:
                if choice == 2:
                    action_create_project(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 3:
                    action_copy_example_model(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 4:
                    action_launch_jupyter(state, print_func=print_func)
                elif choice == 5:
                    action_open_project(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 6:
                    action_import_model(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 7:
                    action_set_active_model(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 8:
                    action_generate_nhm_notebooks(state, print_func=print_func)
                elif choice == 9:
                    action_show_current_setup(state, print_func=print_func)
                elif choice == 10:
                    action_set_api_key(
                        state, print_func=print_func, input_func=input_func
                    )
            except (FileNotFoundError, NotADirectoryError, ValueError, OSError) as exc:
                print_func(f"Error: {exc}")
```

- [ ] **Step 8: Run the dispatch test and the full module**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_run_setup_dispatch_maps_new_numbers -v`
Expected: PASS

Run: `pytest tests/test_workspace_setup.py -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): reorder menu into guided (1-4) and more-options (5-10) blocks"
```

---

### Task 6: Manual end-to-end verification

**Files:** none (manual)

- [ ] **Step 1: Launch the real menu and walk the guided path**

Run: `pixi run setup`
Do: choose `1` (accept default workspace via Enter), `2` (name a project), `3` (pick an example model), `4` (launch).
Expected:
- After `3`, the printout confirms the model was copied AND "Active model set to …".
- After `4`, "Generating NHM notebooks before launch…" appears (first run), then "Loading JupyterLab…", then "JupyterLab is ready …" once the server is up, and the menu redraws without clobbering Jupyter's URL output.
- The top menu header line shows "Active model: <name>" (not "(not set)").

- [ ] **Step 2: Re-run launch to confirm no regen when fresh**

Do: from the menu choose `4` again.
Expected: no "Generating NHM notebooks…" line (notebooks already fresh); goes straight to launching + loading.

- [ ] **Step 3: Full test suite**

Run: `pytest tests/ -v`
Expected: all PASS
