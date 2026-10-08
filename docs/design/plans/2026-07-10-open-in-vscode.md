# Open in VSCode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Open in VSCode" option to the setup menu that opens the current project (and its first notebook) in VSCode, resolving the `code` CLI even when it's not on PATH and guiding the user to install it when it isn't.

**Architecture:** All code changes are in the setup CLI layer, `src/assist/workspace/setup.py`, mirroring the existing `action_launch_jupyter`. A `_find_code_executable` helper resolves the `code` binary (PATH → well-known locations); `action_open_in_vscode` auto-generates notebooks if needed, resolves `code` with a prompt-and-retry fallback, and launches it. The menu gains a new "More options" entry (option 5) and the dispatch shifts 5–10 down to 6–11. A short README note documents it.

**Tech Stack:** Python 3.11, `unittest` + `pytest`, `shutil.which`, `subprocess`, existing `assist.workspace` package.

## Global Constraints

- All code edits confined to `src/assist/workspace/setup.py`, its test file `tests/test_workspace_setup.py`, and a README note in `README.md`. No changes to `service.py`, `bridge.py`, `cli.py`, or `make_notebooks.py`.
- Work happens on branch `enhance/simple-menu` (NOT `learn/readme-quickstart`). Confirm the branch before starting (see Task 0).
- Tests use `unittest.TestCase` in `tests/test_workspace_setup.py`, run with `pytest`. Follow the existing style: inject `print_func`/`input_func`, patch with `unittest.mock.patch`/`patch.object`.
- Preserve existing public function names and their current keyword arguments; only add new keyword arguments with defaults.
- No real subprocess launches, no real VSCode, no real PATH dependence in tests — inject `which`, `launcher`, `input_func`, and `candidates`.
- Commits are local only this session; do not push. (Per user instruction for this session.)
- Existing menu on `enhance/simple-menu` is numbered: 1 workspace, 2 create project, 3 copy example, 4 launch jupyter, 5 open existing, 6 import, 7 set active, 8 generate notebooks, 9 show setup, 10 API key, 0 exit. This plan inserts "Open in VSCode" at 5 and shifts the rest to 6–11.
- Run the full setup module after each task: `pytest tests/test_workspace_setup.py -v`.

---

### Task 0: Confirm branch

**Files:** none (git)

- [ ] **Step 1: Ensure work lands on enhance/simple-menu**

Run: `git branch --show-current`
Expected: `enhance/simple-menu`. If it prints anything else (e.g. `learn/readme-quickstart`), stop and switch: `git switch enhance/simple-menu` (resolve any carried-over uncommitted changes first). Do not implement on `learn/readme-quickstart`.

---

### Task 1: `_find_code_executable` helper

**Files:**
- Modify: `src/assist/workspace/setup.py` (add helper + a module constant, near `action_launch_jupyter`)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Produces:
  - `VSCODE_KNOWN_PATHS: list[str]` — platform-independent superset of well-known `code` locations checked as fallback.
  - `_find_code_executable(*, which=shutil.which, candidates=None) -> str | None` — returns the resolved `code` path (from `which("code")`, else the first existing entry in `candidates` or `VSCODE_KNOWN_PATHS`), else `None`.

- [ ] **Step 1: Write the failing tests**

Add to `WorkspaceSetupTests` in `tests/test_workspace_setup.py`:

```python
    def test_find_code_executable_prefers_path_lookup(self):
        result = setup._find_code_executable(
            which=lambda name: "/usr/local/bin/code" if name == "code" else None,
            candidates=["/nonexistent/code"],
        )
        self.assertEqual(result, "/usr/local/bin/code")

    def test_find_code_executable_falls_back_to_existing_candidate(self):
        existing = self.tmp_path / "code"
        existing.write_text("#!/bin/sh\n", encoding="utf-8")
        result = setup._find_code_executable(
            which=lambda _name: None,
            candidates=[str(self.tmp_path / "missing"), str(existing)],
        )
        self.assertEqual(result, str(existing))

    def test_find_code_executable_returns_none_when_nowhere(self):
        result = setup._find_code_executable(
            which=lambda _name: None,
            candidates=[str(self.tmp_path / "missing")],
        )
        self.assertIsNone(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_workspace_setup.py -k find_code_executable -v`
Expected: FAIL — `AttributeError: module 'assist.workspace.setup' has no attribute '_find_code_executable'`

- [ ] **Step 3: Add the constant and helper**

Ensure `import shutil` is present at the top of `setup.py` (add it beside the existing `import shlex`). Then add above `action_launch_jupyter`:

```python
VSCODE_KNOWN_PATHS = [
    "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
    "/usr/share/code/bin/code",
    "/snap/bin/code",
    str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/bin/code.cmd"),
]


def _find_code_executable(*, which=shutil.which, candidates=None) -> str | None:
    found = which("code")
    if found:
        return found
    for candidate in candidates if candidates is not None else VSCODE_KNOWN_PATHS:
        if Path(candidate).exists():
            return candidate
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_workspace_setup.py -k find_code_executable -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): add _find_code_executable helper"
```

---

### Task 2: `action_open_in_vscode` — launch, generate, prompt-and-retry

**Files:**
- Modify: `src/assist/workspace/setup.py` (add `action_open_in_vscode` after `action_launch_jupyter`)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `require_current_project`, `require_workspace_root`, `bridge.get_project_dir`, `nhm_notebooks_need_generation`, `generate_nhm_notebooks`, `_find_code_executable` (Task 1).
- Produces: `action_open_in_vscode(state, *, print_func=print, input_func=input, which=shutil.which, launcher=subprocess.Popen, candidates=None, max_retries=3) -> Path | None`. Launches `code <project_root> [<first_nb>]`; prints install guidance and retries when `code` is unresolved; returns `project_root` on launch, `None` on skip/error.

- [ ] **Step 1: Write the failing test (happy path launches code with folder + notebook)**

```python
    def test_action_open_in_vscode_launches_with_folder_and_notebook(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        project_root = self.workspace_root / "Project_A"
        first_nb = project_root / "notebooks" / "nhm" / "0_workspace_setup.ipynb"
        first_nb.parent.mkdir(parents=True, exist_ok=True)
        first_nb.write_text("{}", encoding="utf-8")
        launched = {}

        def launcher(args, **kwargs):
            launched["args"] = args
            return None

        with patch.object(setup, "nhm_notebooks_need_generation", return_value=False):
            result = setup.action_open_in_vscode(
                state,
                print_func=lambda *_: None,
                which=lambda _name: "/usr/local/bin/code",
                launcher=launcher,
            )

        self.assertEqual(result, project_root)
        self.assertEqual(
            launched["args"],
            ["/usr/local/bin/code", str(project_root), str(first_nb)],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_open_in_vscode_launches_with_folder_and_notebook -v`
Expected: FAIL — `AttributeError: ... has no attribute 'action_open_in_vscode'`

- [ ] **Step 3: Implement `action_open_in_vscode`**

Add after `action_launch_jupyter`:

```python
def action_open_in_vscode(
    state: SetupState,
    *,
    print_func=print,
    input_func=input,
    which=shutil.which,
    launcher=subprocess.Popen,
    candidates=None,
    max_retries: int = 3,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    workspace_root = require_workspace_root(state)
    project_root = bridge.get_project_dir(workspace_root, state.current_project)

    if nhm_notebooks_need_generation(state):
        print_func("Generating NHM notebooks before opening VSCode…")
        generate_nhm_notebooks(state, print_func=print_func)

    code_path = _find_code_executable(which=which, candidates=candidates)
    attempts = 0
    while code_path is None and attempts < max_retries:
        attempts += 1
        print_func("VSCode 'code' command not found.")
        print_func(
            "In VSCode: press Cmd/Ctrl+Shift+P and run "
            "\"Shell Command: Install 'code' command in PATH\"."
        )
        answer = input_func(
            "Press Enter when done to retry, or type 's' to skip: "
        ).strip().lower()
        if answer in {"s", "skip"}:
            break
        code_path = _find_code_executable(which=which, candidates=candidates)

    if code_path is None:
        print_func(f"Open this folder in VSCode manually: {project_root}")
        return None

    args = [code_path, str(project_root)]
    first_nb = project_root / "notebooks" / "nhm" / "0_workspace_setup.ipynb"
    if first_nb.exists():
        args.append(str(first_nb))

    try:
        launcher(args)
    except (OSError, FileNotFoundError) as exc:
        print_func(f"Error: failed to open VSCode: {exc}")
        print_func(f"Open this folder in VSCode manually: {project_root}")
        return None

    print_func(f"Opening {project_root} in VSCode…")
    return project_root
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_open_in_vscode_launches_with_folder_and_notebook -v`
Expected: PASS

- [ ] **Step 5: Write remaining behavior tests**

```python
    def test_action_open_in_vscode_opens_folder_only_when_no_notebook(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        project_root = self.workspace_root / "Project_A"
        launched = {}

        with patch.object(setup, "nhm_notebooks_need_generation", return_value=False):
            setup.action_open_in_vscode(
                state,
                print_func=lambda *_: None,
                which=lambda _name: "/usr/local/bin/code",
                launcher=lambda args, **kw: launched.setdefault("args", args),
            )

        self.assertEqual(launched["args"], ["/usr/local/bin/code", str(project_root)])

    def test_action_open_in_vscode_generates_notebooks_when_needed(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )

        with patch.object(
            setup, "nhm_notebooks_need_generation", return_value=True
        ), patch.object(
            setup, "generate_nhm_notebooks", return_value=[]
        ) as mock_gen:
            setup.action_open_in_vscode(
                state,
                print_func=lambda *_: None,
                which=lambda _name: "/usr/local/bin/code",
                launcher=lambda args, **kw: None,
            )

        mock_gen.assert_called_once()

    def test_action_open_in_vscode_prompts_then_retries_and_launches(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        printed: list[str] = []
        which_results = iter([None, "/usr/local/bin/code"])
        launched = {}

        with patch.object(setup, "nhm_notebooks_need_generation", return_value=False):
            result = setup.action_open_in_vscode(
                state,
                print_func=printed.append,
                input_func=lambda _prompt: "",
                which=lambda _name: next(which_results),
                launcher=lambda args, **kw: launched.setdefault("args", args),
            )

        self.assertEqual(result, self.workspace_root / "Project_A")
        self.assertIn("args", launched)
        self.assertTrue(
            any("Shell Command: Install" in line for line in printed),
            f"expected install guidance, got: {printed}",
        )

    def test_action_open_in_vscode_skip_prints_manual_path(self):
        service.create_project(self.workspace_root, "Project_A")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        printed: list[str] = []
        launched = {}

        with patch.object(setup, "nhm_notebooks_need_generation", return_value=False):
            result = setup.action_open_in_vscode(
                state,
                print_func=printed.append,
                input_func=lambda _prompt: "s",
                which=lambda _name: None,
                candidates=[str(self.tmp_path / "missing")],
                launcher=lambda args, **kw: launched.setdefault("args", args),
            )

        self.assertIsNone(result)
        self.assertNotIn("args", launched)
        self.assertTrue(
            any("manually" in line for line in printed),
            f"expected manual-path message, got: {printed}",
        )
```

- [ ] **Step 6: Run all vscode-action tests**

Run: `pytest tests/test_workspace_setup.py -k open_in_vscode -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
git commit -m "feat(setup): add action_open_in_vscode with prompt-and-retry"
```

---

### Task 3: Wire "Open in VSCode" into the menu (option 5) + shift dispatch

**Files:**
- Modify: `src/assist/workspace/setup.py` (`print_main_menu`, dispatch in `run_setup`)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `action_open_in_vscode` (Task 2) and all existing `action_*`.
- Produces: new menu order/dispatch — `5 → action_open_in_vscode`, `6 → action_open_project`, `7 → action_import_model`, `8 → action_set_active_model`, `9 → action_generate_nhm_notebooks`, `10 → action_show_current_setup`, `11 → action_set_api_key`; max menu choice 11.

- [ ] **Step 1: Write the failing menu-layout test**

```python
    def test_print_main_menu_includes_open_in_vscode_at_5(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )
        printed: list[str] = []
        setup.print_main_menu(state, print_func=printed.append)
        text = "\n".join(printed)

        self.assertIn("5. Open in VSCode", text)
        self.assertIn("6. Open existing project", text)
        self.assertIn("7. Import model folder", text)
        self.assertIn("8. Set active model", text)
        self.assertIn("9. Generate NHM notebooks", text)
        self.assertIn("10. Show current setup", text)
        self.assertIn("11. Set USGS WaterData API key", text)
        self.assertIn("0. Exit", text)
        self.assertLess(
            text.index("5. Open in VSCode"), text.index("6. Open existing project")
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_print_main_menu_includes_open_in_vscode_at_5 -v`
Expected: FAIL — current menu has no "5. Open in VSCode" and API key is at 10, not 11.

- [ ] **Step 3: Update `print_main_menu`**

Replace the "More options" block with:

```python
    print_func("  -- More options --")
    print_func("  5. Open in VSCode")
    print_func("  6. Open existing project")
    print_func("  7. Import model folder")
    print_func("  8. Set active model")
    print_func("  9. Generate NHM notebooks")
    print_func(" 10. Show current setup")
    print_func(" 11. Set USGS WaterData API key")
    print_func("  0. Exit")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_print_main_menu_includes_open_in_vscode_at_5 -v`
Expected: PASS

- [ ] **Step 5: Write the failing dispatch test**

Replace the existing `test_run_setup_dispatch_maps_new_numbers` cases with the shifted mapping (keep the `_run_setup_once` helper as-is):

```python
    def test_run_setup_dispatch_maps_new_numbers(self):
        cases = {
            2: "action_create_project",
            3: "action_copy_example_model",
            4: "action_launch_jupyter",
            5: "action_open_in_vscode",
            6: "action_open_project",
            7: "action_import_model",
            8: "action_set_active_model",
            9: "action_generate_nhm_notebooks",
            10: "action_show_current_setup",
            11: "action_set_api_key",
        }
        for choice, action_name in cases.items():
            with self.subTest(choice=choice):
                mock_action = self._run_setup_once(choice, action_name)
                mock_action.assert_called_once()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_workspace_setup.py::WorkspaceSetupTests::test_run_setup_dispatch_maps_new_numbers -v`
Expected: FAIL — dispatch still maps 5 → open project and has no case 11.

- [ ] **Step 7: Update the dispatch in `run_setup`**

Change `prompt_menu_choice(10, ...)` to `prompt_menu_choice(11, ...)`, then replace the `try:` action chain (choices 2–10) with:

```python
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
                    action_open_in_vscode(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 6:
                    action_open_project(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 7:
                    action_import_model(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 8:
                    action_set_active_model(
                        state, print_func=print_func, input_func=input_func
                    )
                elif choice == 9:
                    action_generate_nhm_notebooks(state, print_func=print_func)
                elif choice == 10:
                    action_show_current_setup(state, print_func=print_func)
                elif choice == 11:
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
git commit -m "feat(setup): add Open in VSCode menu option (5) and shift dispatch"
```

---

### Task 4: README note

**Files:**
- Modify: `README.md` (under the "Quick start (interactive)" section)

**Interfaces:** none (docs).

- [ ] **Step 1: Add the note**

After the "Quick start (interactive)" numbered list (immediately before the `See the "Pixi Workspace for NHM" section below...` line), insert:

```markdown
Prefer VSCode? Choose **"Open in VSCode"** from the menu to open the project (and
`0_workspace_setup.ipynb`) directly in VSCode. This requires the `code` command on
your PATH — if it's missing, install it from VSCode via
`Cmd/Ctrl+Shift+P → "Shell Command: Install 'code' command in PATH"`, then retry.
```

- [ ] **Step 2: Verify it renders**

Run: `grep -n "Open in VSCode" README.md`
Expected: shows the new line under Quick start.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: note the Open in VSCode menu option"
```

---

### Task 5: Full verification

**Files:** none

- [ ] **Step 1: Full setup module**

Run: `pytest tests/test_workspace_setup.py -v`
Expected: all PASS (includes 3 find-code tests, 5 open-in-vscode tests, menu + dispatch tests).

- [ ] **Step 2: Full suite**

Run: `pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 3: Manual render of the menu**

Run:
```bash
pixi run -e default python -c "
from pathlib import Path
from assist.workspace import setup
state = setup.SetupState(repo_root=Path('.').resolve(), workspace_root=Path('~/nhm-workspace').expanduser())
setup.print_main_menu(state, print_func=print)
"
```
Expected: "5. Open in VSCode" appears as the first "More options" entry, API key is "11".
