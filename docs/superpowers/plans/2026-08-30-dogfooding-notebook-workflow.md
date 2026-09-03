# Dogfooding Notebook Workflow + Jupytext Pairing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make contributors edit notebook templates through the exact end-user workspace flow — notebooks generated into `<workspace>/<project>/notebooks/<workflow>/` that pair straight back to `src/workflow_templates/<workflow>/*.py` — and stop every pixi task from launching JupyterLab.

**Architecture:** `make_notebooks.convert_workflow()` gains a `pairing_mode` of `"local"` (end users; pairing comes from a per-project `jupytext.toml`) or `"dev"` (contributors; per-notebook jupytext `formats` metadata pointing back into the repo). A new `kernels.py` helper registers one ipykernel spec per pixi environment and stamps it into generated notebooks so Jupyter/VS Code preselect the right interpreter. The repo-relative notebook directory concept (`REPO_NOTEBOOK_DIRS`, `get_workflow_notebooks_dir`, the `notebooks-create` and `dev` tasks) is deleted outright, and `setup`'s "Launch Jupyter" menu action becomes a "here is the path and the command" printer.

**Tech Stack:** Python 3.11+, [jupytext](https://jupytext.org) 1.19.3, `ipykernel` (transitive via `jupyterlab`), pixi tasks in `pyproject.toml`, `unittest` + pytest.

**Spec:** `docs/superpowers/specs/2026-08-18-dogfooding-notebook-workflow-design.md` (including its **Update (2026-08-28)** block)

## Global Constraints

- **Per `AGENTS.md:33-35`: stage changes with `git add` / `git rm`, but do not `git commit`, merge, push, or open a merge request.** That is the maintainer's action. Every task below ends with staging, not committing.
- The three workflow names are exactly `("nhm", "nhf", "pest")` — `bridge.WORKFLOW_NAMES`. Do not add, rename, or split them; per-workflow pixi feature/environment splitting is an explicit spec non-goal.
- The two pairing modes are exactly `"local"` and `"dev"`. `"local"` is the default everywhere.
- Kernel names are exactly `nhm-assist` (default environment) and `nhm-assist-dev` (dev environment).
- The per-project config file is exactly `<project>/jupytext.toml` containing `formats = "ipynb,py:percent"`, and is **never** written if a file already exists at that path.
- Do **not** add any `[tool.jupytext]` section to `nhm-assist`'s own `pyproject.toml` — after this change no notebooks live inside the repo tree, so a directory-scoped config there can affect nothing.
- No task, and no code path, may start a `jupyter lab` subprocess. Tasks print the path and the command instead.
- No new dependency may be added. `jupyterlab` is already in `[project.dependencies]` (`pyproject.toml:57`) and pulls `ipykernel` transitively into both the `default` and `dev` environments (confirmed present in `pixi.lock`), per spec Design §4 and the 2026-08-28 spec update.
- Do not change the on-disk project/model layout beyond adding `<project>/jupytext.toml`.
- The suite is 70 tests today (`pixi run test`). It must stay green at the end of every task.

### Verified jupytext behavior this plan depends on

Two facts were established empirically against jupytext 1.19.3 before writing this plan. Do not re-derive them, and do not "simplify" the code that depends on them.

1. **A `formats` prefix must be RELATIVE, never absolute.** jupytext resolves the prefix against the notebook's own directory by concatenation. Given a notebook at `/ws/proj/notebooks/nhm/0_setup.ipynb`:

   - `"ipynb,/repo/src/workflow_templates/nhm//py:percent"` (absolute) resolves to the nonsense path `/ws/proj/notebooks/nhm//repo/src/workflow_templates/nhm/0_setup.py`.
   - `"ipynb,../../../repo/src/workflow_templates/nhm//py:percent"` (relative) resolves correctly.

   The spec's phrasing "a repo-relative or absolute path" is therefore narrowed by this plan: **relative only**.

2. **The `//` separator between the prefix and the format is required.** `".../nhm/py:percent"` (single slash) concatenates the filename onto the directory name, yielding `.../nhm0_setup.py`.

A full round trip was confirmed: writing an `.ipynb` with a relative `formats` prefix into a workspace, editing a cell, and running `jupytext --sync` updated the source template in the repo. Separately, a project-root `jupytext.toml` containing `formats = "ipynb,py:percent"` was confirmed to pair an unmarked notebook to a same-directory `.py`.

---

## Task 1: Kernel registration helper

Registers one ipykernel spec per pixi environment so that a notebook's stamped `metadata.kernelspec` actually resolves to something on the user's machine. Nothing else in the plan works without this, so it comes first.

**Files:**
- Create: `src/assist/workspace/kernels.py`
- Modify: `src/assist/workspace/__init__.py`
- Test: `tests/test_workspace_kernels.py` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `DEFAULT_KERNEL_NAME: str = "nhm-assist"`, `DEFAULT_KERNEL_DISPLAY_NAME: str = "Python (nhm-assist)"`
  - `DEV_KERNEL_NAME: str = "nhm-assist-dev"`, `DEV_KERNEL_DISPLAY_NAME: str = "Python (nhm-assist dev)"`
  - `PAIRING_MODE_KERNELS: dict[str, tuple[str, str]]` mapping `"local"`/`"dev"` to `(name, display_name)`
  - `list_kernel_names(*, runner=subprocess.run) -> set[str]`
  - `ensure_kernel_registered(name: str, display_name: str, *, runner=subprocess.run) -> bool` — returns `True` if it installed a new spec, `False` if one already existed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workspace_kernels.py`:

```python
from __future__ import annotations

import json
import subprocess
import unittest


from assist.workspace import kernels


class FakeRunner:
    """Stands in for subprocess.run, recording calls and replaying kernel lists."""

    def __init__(self, installed: list[str] | None = None, returncode: int = 0):
        self.installed = list(installed or [])
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if "kernelspec" in command:
            payload = {"kernelspecs": {name: {} for name in self.installed}}
            return subprocess.CompletedProcess(
                command, self.returncode, stdout=json.dumps(payload), stderr=""
            )
        # ipykernel install
        name = command[command.index("--name") + 1]
        self.installed.append(name)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class KernelRegistrationTests(unittest.TestCase):
    def test_registers_kernel_when_missing(self):
        runner = FakeRunner(installed=[])

        created = kernels.ensure_kernel_registered(
            kernels.DEV_KERNEL_NAME,
            kernels.DEV_KERNEL_DISPLAY_NAME,
            runner=runner,
        )

        self.assertTrue(created)
        self.assertIn(kernels.DEV_KERNEL_NAME, runner.installed)
        install_calls = [call for call in runner.calls if "ipykernel" in call]
        self.assertEqual(len(install_calls), 1)
        self.assertIn("--user", install_calls[0])
        self.assertIn(kernels.DEV_KERNEL_DISPLAY_NAME, install_calls[0])

    def test_is_idempotent(self):
        runner = FakeRunner(installed=[])

        first = kernels.ensure_kernel_registered(
            kernels.DEV_KERNEL_NAME, kernels.DEV_KERNEL_DISPLAY_NAME, runner=runner
        )
        second = kernels.ensure_kernel_registered(
            kernels.DEV_KERNEL_NAME, kernels.DEV_KERNEL_DISPLAY_NAME, runner=runner
        )

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(runner.installed.count(kernels.DEV_KERNEL_NAME), 1)
        install_calls = [call for call in runner.calls if "ipykernel" in call]
        self.assertEqual(len(install_calls), 1)

    def test_list_kernel_names_returns_empty_set_on_failure(self):
        runner = FakeRunner(installed=["nhm-assist"], returncode=1)

        self.assertEqual(kernels.list_kernel_names(runner=runner), set())

    def test_list_kernel_names_survives_unparseable_output(self):
        def broken_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="not json", stderr="")

        self.assertEqual(kernels.list_kernel_names(runner=broken_runner), set())

    def test_pairing_mode_kernels_cover_both_modes(self):
        self.assertEqual(
            kernels.PAIRING_MODE_KERNELS,
            {
                "local": (
                    kernels.DEFAULT_KERNEL_NAME,
                    kernels.DEFAULT_KERNEL_DISPLAY_NAME,
                ),
                "dev": (
                    kernels.DEV_KERNEL_NAME,
                    kernels.DEV_KERNEL_DISPLAY_NAME,
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pixi run -e dev pytest tests/test_workspace_kernels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'assist.workspace.kernels'`

- [ ] **Step 3: Write the implementation**

Create `src/assist/workspace/kernels.py`:

```python
"""Registration of per-environment Jupyter kernels for nhm-assist.

A notebook's ``metadata.kernelspec`` only preselects a kernel in JupyterLab or
VS Code if a kernelspec with that exact name is actually registered on the
machine. Stamping the metadata and registering the spec therefore have to
happen together; this module owns the registration half.
"""

from __future__ import annotations

import json
import subprocess
import sys


DEFAULT_KERNEL_NAME = "nhm-assist"
DEFAULT_KERNEL_DISPLAY_NAME = "Python (nhm-assist)"
DEV_KERNEL_NAME = "nhm-assist-dev"
DEV_KERNEL_DISPLAY_NAME = "Python (nhm-assist dev)"

PAIRING_MODE_KERNELS: dict[str, tuple[str, str]] = {
    "local": (DEFAULT_KERNEL_NAME, DEFAULT_KERNEL_DISPLAY_NAME),
    "dev": (DEV_KERNEL_NAME, DEV_KERNEL_DISPLAY_NAME),
}


def list_kernel_names(*, runner=subprocess.run) -> set[str]:
    """Names of every kernelspec Jupyter can currently see.

    Returns an empty set rather than raising if Jupyter is unavailable or
    prints something unparseable — a missing kernel list should degrade into
    "register it again", never into a crashed notebook build.
    """
    result = runner(
        [sys.executable, "-m", "jupyter", "kernelspec", "list", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return set()
    kernelspecs = payload.get("kernelspecs")
    if not isinstance(kernelspecs, dict):
        return set()
    return set(kernelspecs)


def ensure_kernel_registered(
    name: str,
    display_name: str,
    *,
    runner=subprocess.run,
) -> bool:
    """Register an ipykernel spec for the running interpreter if it is missing.

    Returns True if a new spec was installed, False if one already existed.
    """
    if name in list_kernel_names(runner=runner):
        return False

    runner(
        [
            sys.executable,
            "-m",
            "ipykernel",
            "install",
            "--user",
            "--name",
            name,
            "--display-name",
            display_name,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return True
```

- [ ] **Step 4: Export the helper from the package**

In `src/assist/workspace/__init__.py`, add this import block immediately after the `from assist.workspace.examples import resolve_example_source` line:

```python
from assist.workspace.kernels import (
    DEFAULT_KERNEL_DISPLAY_NAME,
    DEFAULT_KERNEL_NAME,
    DEV_KERNEL_DISPLAY_NAME,
    DEV_KERNEL_NAME,
    PAIRING_MODE_KERNELS,
    ensure_kernel_registered,
    list_kernel_names,
)
```

Then add these entries to `__all__`, keeping it alphabetically sorted (so they land near the top, before `"MODEL_SUBDIRS"` for the uppercase ones and in among the lowercase run for the functions):

```python
    "DEFAULT_KERNEL_DISPLAY_NAME",
    "DEFAULT_KERNEL_NAME",
    "DEV_KERNEL_DISPLAY_NAME",
    "DEV_KERNEL_NAME",
    "PAIRING_MODE_KERNELS",
    "ensure_kernel_registered",
    "list_kernel_names",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pixi run -e dev pytest tests/test_workspace_kernels.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Run the full suite**

Run: `pixi run test`
Expected: PASS, 75 tests (70 existing + 5 new).

- [ ] **Step 7: Stage the changes**

```bash
git add src/assist/workspace/kernels.py src/assist/workspace/__init__.py tests/test_workspace_kernels.py
```

Do not commit — see Global Constraints.

---

## Task 2: Remove the repo-relative notebook directory concept

`REPO_NOTEBOOK_DIRS` points at `notebooks/`, `nhf_assist/notebooks/`, and `pestpp_ies_calibration/notebooks/`. **None of those three directories exists in the repo tree** — they were removed during the pixi restructuring. This task deletes the dead code paths and the task that drove them; it deletes no real content.

**Files:**
- Modify: `src/assist/workspace/bridge.py:7-11` (delete `REPO_NOTEBOOK_DIRS`), `src/assist/workspace/bridge.py:53-60` (delete `get_workflow_notebooks_dir`)
- Modify: `src/assist/workspace/__init__.py:5,15,42,60`
- Modify: `src/workflow_templates/make_notebooks.py:6-9,21-38`
- Modify: `pyproject.toml:169-173` (delete the `notebooks-create` task)
- Test: `tests/test_model_notebook_generation.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `convert_workflow(name, *, workspace_root, project_name, dry_run=False)` — `workspace_root` and `project_name` are now **required keyword arguments**; passing neither raises `TypeError`, and passing an empty `project_name` raises `ValueError`. Task 3 extends this same signature with `pairing_mode`.

- [ ] **Step 1: Write the failing tests**

Append these two tests to the `ProjectNotebookGenerationTests` class in `tests/test_model_notebook_generation.py` (after `test_parse_args_supports_project_local_notebook_generation`):

```python
    def test_repo_relative_notebook_helpers_are_gone(self):
        self.assertFalse(hasattr(bridge, "REPO_NOTEBOOK_DIRS"))
        self.assertFalse(hasattr(bridge, "get_workflow_notebooks_dir"))

    def test_convert_workflow_requires_a_project(self):
        with self.assertRaises(TypeError):
            notebook_builder.convert_workflow("nhm")

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                notebook_builder.convert_workflow(
                    "nhm",
                    workspace_root=Path(tmpdir).resolve(),
                    project_name="",
                )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pixi run -e dev pytest tests/test_model_notebook_generation.py -v`
Expected: FAIL — `test_repo_relative_notebook_helpers_are_gone` fails on the first assertion (the attribute still exists); `test_convert_workflow_requires_a_project` fails because `convert_workflow("nhm")` currently succeeds by falling back to the repo-relative directory.

- [ ] **Step 3: Delete the dead helpers from `bridge.py`**

In `src/assist/workspace/bridge.py`, delete the `REPO_NOTEBOOK_DIRS` dict so the module constants read:

```python
WORKFLOW_NAMES = ("nhm", "nhf", "pest")
MODEL_SUBDIRS = ("config", "inputs", "outputs")
PROJECT_MARKER_FILENAME = ".nhm-assist-project"
```

Then delete the whole `get_workflow_notebooks_dir` function (currently lines 53-60):

```python
def get_workflow_notebooks_dir(
    workflow: str,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    if workflow not in WORKFLOW_NAMES:
        raise ValueError(f"unsupported workflow: {workflow}")
    return resolve_repo_root(env=env) / REPO_NOTEBOOK_DIRS[workflow]
```

Leave `resolve_repo_root` alone — `setup.py` and `service.py` still use it.

- [ ] **Step 4: Drop the two names from the package exports**

In `src/assist/workspace/__init__.py`, remove `REPO_NOTEBOOK_DIRS,` and `get_workflow_notebooks_dir,` from the `from assist.workspace.bridge import (...)` block, and remove `"REPO_NOTEBOOK_DIRS",` and `"get_workflow_notebooks_dir",` from `__all__`.

- [ ] **Step 5: Make the project arguments required in `make_notebooks.py`**

In `src/workflow_templates/make_notebooks.py`, change the import to drop the deleted helper:

```python
from assist.workspace.bridge import get_project_workflow_notebooks_dir
```

Then replace the head of `convert_workflow` — the signature through the `in_workspace_mode` branch (currently lines 21-38) — with:

```python
def convert_workflow(
    name: str,
    *,
    workspace_root: str | Path,
    project_name: str,
    dry_run: bool = False,
) -> list[Path]:
    if not project_name:
        raise ValueError("project_name is required")

    input_folder = WORKFLOW_INPUT_DIRS[name]
    output_folder = get_project_workflow_notebooks_dir(
        name, workspace_root, project_name
    )
    created_paths = []
```

Then, in the loop body, drop the now-meaningless `in_workspace_mode` guard — the `formats`-stripping is now unconditional, because every generated notebook is a workspace notebook. Replace:

```python
        notebook = jupytext.read(py_file)
        if in_workspace_mode:
            # Workspace .ipynb files are user-owned copies; they must not pair
            # back to the repo's source templates on save.
            jupytext_meta = notebook.metadata.get("jupytext", {})
            jupytext_meta.pop("formats", None)
        jupytext.write(notebook, output_path)
```

with:

```python
        notebook = jupytext.read(py_file)
        # Pairing is decided by the project, not inherited from the template.
        notebook.metadata.get("jupytext", {}).pop("formats", None)
        jupytext.write(notebook, output_path)
```

(Task 3 replaces this block again with the `pairing_mode` logic — it is written out here so the suite stays green at the end of *this* task.)

- [ ] **Step 6: Delete the `notebooks-create` pixi task**

In `pyproject.toml`, delete this entire block (currently lines 169-173):

```toml
[tool.pixi.tasks.notebooks-create]
cmd = "python -m workflow_templates.make_notebooks --workflow {{ workflow }}"
args = [{ arg = "workflow", default = "all" }]
default-environment = "default"
description = "Generate notebooks from .py templates into the repo's notebook directories (does not launch Jupyter)."
```

Leave `[tool.pixi.tasks.dev]` in place for now — Task 4 replaces it with `dev-mode`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pixi run -e dev pytest tests/test_model_notebook_generation.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 8: Confirm nothing else references the deleted names**

Run: `grep -rn "REPO_NOTEBOOK_DIRS\|get_workflow_notebooks_dir" --include="*.py" src/`
Expected: no output.

Run: `grep -n "^\[tool.pixi.tasks.notebooks-create\]" pyproject.toml`
Expected: no output, while `grep -n "^\[tool.pixi.tasks.notebooks-create-project\]" pyproject.toml` still matches. (Do not try to separate the two with `\b` — in grep, `\b` matches between `e` and `-`, so `notebooks-create\b` also hits `notebooks-create-project`.)

Run: `pixi run test`
Expected: PASS, 77 tests (70 baseline + 5 from Task 1 + 2 here).

- [ ] **Step 9: Stage the changes**

```bash
git add src/assist/workspace/bridge.py src/assist/workspace/__init__.py src/workflow_templates/make_notebooks.py pyproject.toml tests/test_model_notebook_generation.py
```

---

## Task 3: `pairing_mode` in `make_notebooks.py`

The heart of the change. `"local"` notebooks carry no jupytext `formats` and inherit same-directory pairing from the project's `jupytext.toml`; `"dev"` notebooks carry an explicit relative `formats` prefix back into the repo. Both stamp a kernelspec.

**Files:**
- Modify: `src/workflow_templates/make_notebooks.py`
- Test: `tests/test_model_notebook_generation.py`

**Interfaces:**
- Consumes: `PAIRING_MODE_KERNELS`, `ensure_kernel_registered` from Task 1; the required-argument `convert_workflow` signature from Task 2.
- Produces:
  - `PairingMode = Literal["local", "dev"]`
  - `dev_pairing_formats(template_dir: Path, notebook_dir: Path) -> str`
  - `convert_workflow(name, *, workspace_root, project_name, dry_run=False, pairing_mode="local", print_func=print) -> list[Path]`
  - `parse_args` accepts `--pairing-mode {local,dev}`, default `local`
  - Per-file status strings, used verbatim by Task 4's output: `"created"`, `"already dev-configured"`, `"metadata updated"`

- [ ] **Step 1: Write the failing tests**

Add this new test class to `tests/test_model_notebook_generation.py`, after the existing `ProjectNotebookGenerationTests` class. Add `import jupytext` to the file's imports.

```python
class PairingModeTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.workspace_root = Path(self._tmpdir.name).resolve()
        service.create_project(self.workspace_root, "Project_A")
        self.notebook_dir = bridge.get_project_workflow_notebooks_dir(
            "nhm", self.workspace_root, "Project_A"
        )

    def _generate(self, pairing_mode):
        return notebook_builder.convert_workflow(
            "nhm",
            workspace_root=self.workspace_root,
            project_name="Project_A",
            pairing_mode=pairing_mode,
            print_func=lambda *_: None,
        )

    def test_dev_pairing_formats_is_relative_and_resolves_to_the_template(self):
        template_dir = notebook_builder.WORKFLOW_INPUT_DIRS["nhm"]

        formats = notebook_builder.dev_pairing_formats(
            template_dir, self.notebook_dir
        )

        prefix = formats.split(",", 1)[1]
        self.assertFalse(
            prefix.startswith("/"),
            "jupytext concatenates the prefix onto the notebook dir, so an "
            "absolute path resolves to a nonsense location",
        )
        self.assertTrue(prefix.endswith("//py:percent"))
        self.assertNotIn("\\", prefix)

        # The relative prefix must actually land on the real template folder.
        resolved = (self.notebook_dir / prefix.replace("//py:percent", "")).resolve()
        self.assertEqual(resolved, template_dir.resolve())

    def test_local_mode_embeds_no_formats_but_stamps_the_default_kernel(self):
        created = self._generate("local")

        self.assertTrue(created)
        notebook = jupytext.read(created[0])
        self.assertIsNone(notebook.metadata.get("jupytext", {}).get("formats"))
        self.assertEqual(
            notebook.metadata["kernelspec"]["name"], kernels.DEFAULT_KERNEL_NAME
        )

    def test_dev_mode_embeds_formats_pointing_at_the_repo_template(self):
        created = self._generate("dev")

        notebook = jupytext.read(created[0])
        formats = notebook.metadata["jupytext"]["formats"]
        template_dir = notebook_builder.WORKFLOW_INPUT_DIRS["nhm"]
        self.assertEqual(
            formats,
            notebook_builder.dev_pairing_formats(template_dir, self.notebook_dir),
        )
        self.assertEqual(
            notebook.metadata["kernelspec"]["name"], kernels.DEV_KERNEL_NAME
        )

    def test_dev_mode_never_rewrites_existing_cell_content(self):
        created = self._generate("local")
        target = created[0]

        notebook = jupytext.read(target)
        notebook.cells[0].source = "# EDITED BY THE USER"
        jupytext.write(notebook, target)

        self._generate("dev")

        reread = jupytext.read(target)
        self.assertEqual(reread.cells[0].source, "# EDITED BY THE USER")
        self.assertIn("jupytext", reread.metadata)
        self.assertEqual(
            reread.metadata["kernelspec"]["name"], kernels.DEV_KERNEL_NAME
        )

    def test_dev_mode_is_idempotent(self):
        self._generate("dev")
        second = {path: path.read_bytes() for path in self.notebook_dir.rglob("*.ipynb")}

        self._generate("dev")
        third = {path: path.read_bytes() for path in self.notebook_dir.rglob("*.ipynb")}

        self.assertEqual(second.keys(), third.keys())
        for path, payload in second.items():
            self.assertEqual(payload, third[path], f"{path} changed on a repeat run")

    def test_convert_workflow_rejects_an_unknown_pairing_mode(self):
        with self.assertRaises(ValueError):
            self._generate("sideways")

    def test_parse_args_defaults_to_local_pairing(self):
        args = notebook_builder.parse_args(
            ["--workspace-root", "/tmp/ws", "--project-name", "Project_A"]
        )
        self.assertEqual(args.pairing_mode, "local")

        dev_args = notebook_builder.parse_args(
            [
                "--workspace-root",
                "/tmp/ws",
                "--project-name",
                "Project_A",
                "--pairing-mode",
                "dev",
            ]
        )
        self.assertEqual(dev_args.pairing_mode, "dev")
```

Add `kernels` to the module import line at the top of the file:

```python
from assist.workspace import bridge, kernels, service
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pixi run -e dev pytest tests/test_model_notebook_generation.py -v`
Expected: FAIL — `AttributeError: module 'workflow_templates.make_notebooks' has no attribute 'dev_pairing_formats'`, plus `TypeError: convert_workflow() got an unexpected keyword argument 'pairing_mode'`.

- [ ] **Step 3: Write the implementation**

Replace the whole of `src/workflow_templates/make_notebooks.py` with:

```python
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Literal

import jupytext

from assist.workspace.bridge import get_project_workflow_notebooks_dir
from assist.workspace.kernels import PAIRING_MODE_KERNELS, ensure_kernel_registered


TEMPLATES_ROOT = Path(__file__).resolve().parent

WORKFLOW_INPUT_DIRS = {
    "nhm": TEMPLATES_ROOT / "nhm",
    "nhf": TEMPLATES_ROOT / "nhf",
    "pest": TEMPLATES_ROOT / "pest",
}

PairingMode = Literal["local", "dev"]


def dev_pairing_formats(template_dir: Path, notebook_dir: Path) -> str:
    """jupytext ``formats`` pairing a workspace notebook back to a repo template.

    jupytext resolves a ``formats`` prefix by concatenating it onto the
    notebook's own directory, so an absolute path yields a nonsense target
    (``/ws/proj/notebooks/nhm//repo/src/...``). The prefix must be relative,
    and must be posix-separated on every platform. The ``//`` before the
    format name is jupytext's prefix/format separator and is required — with a
    single slash the filename is concatenated onto the directory name.
    """
    try:
        relative = os.path.relpath(template_dir, notebook_dir)
    except ValueError as exc:  # Windows raises across drive letters.
        raise ValueError(
            "dev pairing needs the workspace and the nhm-assist repo on the "
            f"same drive: {notebook_dir} vs {template_dir}"
        ) from exc
    return f"ipynb,{Path(relative).as_posix()}//py:percent"


def _apply_pairing(
    notebook,
    *,
    pairing_mode: PairingMode,
    template_dir: Path,
    notebook_dir: Path,
) -> None:
    kernel_name, kernel_display = PAIRING_MODE_KERNELS[pairing_mode]

    jupytext_meta = notebook.metadata.setdefault("jupytext", {})
    if pairing_mode == "dev":
        jupytext_meta["formats"] = dev_pairing_formats(template_dir, notebook_dir)
    else:
        # Pairing comes from the project's jupytext.toml, not from the file.
        jupytext_meta.pop("formats", None)
    if not jupytext_meta:
        notebook.metadata.pop("jupytext", None)

    notebook.metadata["kernelspec"] = {
        "name": kernel_name,
        "display_name": kernel_display,
        "language": "python",
    }


def _patch_existing_notebook(
    output_path: Path,
    py_file: Path,
    *,
    pairing_mode: PairingMode,
    dry_run: bool,
) -> str:
    """Bring an existing notebook's metadata in line without touching its cells."""
    notebook = jupytext.read(output_path)
    kernel_name, _ = PAIRING_MODE_KERNELS[pairing_mode]
    wanted_formats = dev_pairing_formats(py_file.parent, output_path.parent)

    current_formats = notebook.metadata.get("jupytext", {}).get("formats")
    current_kernel = (notebook.metadata.get("kernelspec") or {}).get("name")
    if current_formats == wanted_formats and current_kernel == kernel_name:
        return "already dev-configured"

    if not dry_run:
        _apply_pairing(
            notebook,
            pairing_mode=pairing_mode,
            template_dir=py_file.parent,
            notebook_dir=output_path.parent,
        )
        jupytext.write(notebook, output_path)
    return "metadata updated"


def convert_workflow(
    name: str,
    *,
    workspace_root: str | Path,
    project_name: str,
    dry_run: bool = False,
    pairing_mode: PairingMode = "local",
    print_func=print,
) -> list[Path]:
    if pairing_mode not in PAIRING_MODE_KERNELS:
        raise ValueError(f"unsupported pairing mode: {pairing_mode}")
    if not project_name:
        raise ValueError("project_name is required")

    input_folder = WORKFLOW_INPUT_DIRS[name]
    if not input_folder.exists():
        raise FileNotFoundError(f"Missing workflow template folder: {input_folder}")

    output_folder = get_project_workflow_notebooks_dir(
        name, workspace_root, project_name
    )
    output_folder.mkdir(parents=True, exist_ok=True)

    created_paths: list[Path] = []

    for py_file in sorted(input_folder.rglob("*.py")):
        relative_path = py_file.relative_to(input_folder)
        output_path = output_folder / relative_path.with_suffix(".ipynb")
        created_paths.append(output_path)

        if pairing_mode == "dev" and output_path.exists():
            status = _patch_existing_notebook(
                output_path,
                py_file,
                pairing_mode=pairing_mode,
                dry_run=dry_run,
            )
        else:
            status = "created"
            if not dry_run:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                notebook = jupytext.read(py_file)
                _apply_pairing(
                    notebook,
                    pairing_mode=pairing_mode,
                    template_dir=py_file.parent,
                    notebook_dir=output_path.parent,
                )
                jupytext.write(notebook, output_path)

        print_func(f"[{name}] {status}: {output_path}")

    return created_paths


def parse_args(argv: list[str] | None = None, *, default_workflow: str = "nhm"):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workflow",
        choices=["nhm", "nhf", "pest", "all"],
        default=default_workflow,
        help="Workflow template set to convert.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned conversions without writing notebooks.",
    )
    parser.add_argument(
        "--workspace-root",
        help="External workspace root for notebook output.",
    )
    parser.add_argument(
        "--project-name",
        help="Project name for project-shared workspace notebook output.",
    )
    parser.add_argument(
        "--pairing-mode",
        choices=["local", "dev"],
        default="local",
        help=(
            "local: pair via the project's jupytext.toml (same-directory .py). "
            "dev: pair back to src/workflow_templates/<workflow>/*.py in the repo."
        ),
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    default_workflow: str = "nhm",
    print_func=print,
) -> int:
    args = parse_args(argv, default_workflow=default_workflow)

    if not args.workspace_root or not args.project_name:
        print_func("Error: --workspace-root and --project-name are both required.")
        return 2

    kernel_name, kernel_display = PAIRING_MODE_KERNELS[args.pairing_mode]
    if not args.dry_run:
        ensure_kernel_registered(kernel_name, kernel_display)

    workflows = list(WORKFLOW_INPUT_DIRS) if args.workflow == "all" else [args.workflow]

    for workflow in workflows:
        created = convert_workflow(
            workflow,
            workspace_root=args.workspace_root,
            project_name=args.project_name,
            dry_run=args.dry_run,
            pairing_mode=args.pairing_mode,
            print_func=print_func,
        )
        notebook_dir = get_project_workflow_notebooks_dir(
            workflow, args.workspace_root, args.project_name
        )
        print_func("")
        print_func(f"[{workflow}] {len(created)} notebook(s) in {notebook_dir}")
        print_func(f"[{workflow}] Open them with: jupyter lab {notebook_dir}")
        print_func(
            f"[{workflow}] Or open that folder in VS Code / Kiro and select the "
            f"'{kernel_display}' kernel."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pixi run -e dev pytest tests/test_model_notebook_generation.py -v`
Expected: PASS, 11 tests.

If `test_dev_mode_is_idempotent` fails, the cause is jupytext normalizing something on the round trip through `_patch_existing_notebook`. Fix it by making `_patch_existing_notebook` return `"already dev-configured"` without writing whenever the metadata already matches — which the implementation above already does — and confirm the *second* and *third* runs are being compared, not the first and second (the first run legitimately creates the files).

- [ ] **Step 5: Confirm the dev round trip actually works end to end**

This is the whole point of the feature, so verify it against real files rather than trusting the metadata assertions alone.

```bash
pixi run -e dev python - <<'PY'
import subprocess, sys, tempfile
from pathlib import Path
import jupytext
from assist.workspace import service, bridge
from workflow_templates import make_notebooks

with tempfile.TemporaryDirectory() as tmp:
    ws = Path(tmp).resolve()
    service.create_project(ws, "Probe")
    make_notebooks.convert_workflow(
        "nhm", workspace_root=ws, project_name="Probe",
        pairing_mode="dev", print_func=lambda *_: None,
    )
    nb_dir = bridge.get_project_workflow_notebooks_dir("nhm", ws, "Probe")
    target = sorted(nb_dir.glob("*.ipynb"))[0]
    template = make_notebooks.WORKFLOW_INPUT_DIRS["nhm"] / (target.stem + ".py")
    original = template.read_text()
    try:
        nb = jupytext.read(target)
        nb.cells[0].source = "# ROUND TRIP PROBE"
        jupytext.write(nb, target)
        subprocess.run([sys.executable, "-m", "jupytext", "--sync", str(target)], check=True)
        assert "# ROUND TRIP PROBE" in template.read_text(), "template was NOT updated"
        print("OK: editing the workspace notebook wrote back into", template)
    finally:
        template.write_text(original)
PY
```

Expected: `OK: editing the workspace notebook wrote back into .../src/workflow_templates/nhm/<name>.py`, and `git status --short src/workflow_templates/` reports the template unchanged afterwards (the `finally` restores it).

- [ ] **Step 6: Run the full suite**

Run: `pixi run test`
Expected: PASS, 84 tests (77 + 7 here).

- [ ] **Step 7: Stage the changes**

```bash
git add src/workflow_templates/make_notebooks.py tests/test_model_notebook_generation.py
```

---

## Task 4: Replace the `dev` pixi task with `dev-mode`

**Files:**
- Modify: `pyproject.toml:163-167` (replace the `dev` task), `pyproject.toml` `[tool.pixi.tasks.setup]` description

**Interfaces:**
- Consumes: the `--pairing-mode` CLI flag and the summary output from Task 3.
- Produces: the `dev-mode` pixi task; no Python interface.

- [ ] **Step 1: Replace the task definition**

In `pyproject.toml`, replace this block:

```toml
[tool.pixi.tasks.dev]
cmd = "python -m workflow_templates.make_notebooks --workflow {{ workflow }} && jupyter lab --ServerApp.contents_manager_class=jupytext.TextFileContentsManager --ServerApp.root_dir=. --LabApp.default_url=/lab/tree/{{ notebook_dir }}"
args = [{ arg = "workflow", default = "nhm" }, { arg = "notebook_dir", default = "notebooks" }]
default-environment = "default"
description = "Contributor mode: regenerate notebooks from .py templates and launch JupyterLab against the repo (not a workspace). Edits sync back to src/workflow_templates/<workflow>/*.py via jupytext."
```

with:

```toml
[tool.pixi.tasks.dev-mode]
cmd = "python -m workflow_templates.make_notebooks --workflow {{ workflow }} --workspace-root {{ workspace_root }} --project-name {{ project_name }} --pairing-mode dev"
args = ["workspace_root", "project_name", { arg = "workflow", default = "nhm" }]
default-environment = "dev"
description = "Contributor mode: generate a project's notebooks paired back to src/workflow_templates/<workflow>/*.py, so editing them in Jupyter edits the templates. Does not launch Jupyter."
```

Note the three deliberate changes beyond the rename: `default-environment` moves from `default` to `dev` (so the stamped `nhm-assist-dev` kernel points at the dev interpreter), the `notebook_dir` argument is gone (notebooks always land in the project), and `workspace_root`/`project_name` are now required positional task arguments matching `notebooks-create-project`.

- [ ] **Step 2: Correct the now-inaccurate `setup` task description**

The `setup` task description still promises it will "launch JupyterLab", which Task 6 removes. In `[tool.pixi.tasks.setup]`, replace the `description` line with:

```toml
description = "End-user entry point: interactive menu to pick a workspace, create projects, copy/import models, set the active model, and generate notebooks. Prints how to open Jupyter; does not launch it."
```

- [ ] **Step 3: Verify the task table parses and lists correctly**

Run: `pixi task list`
Expected: `dev-mode` appears; `dev` and `notebooks-create` do not; `notebooks-create-project`, `setup`, `workspace-init`, `project-create`, `project-list`, `project-set-active-model`, `model-create`, `model-list`, `model-copy-example`, `model-import`, `lint`, and `test` all remain.

Run: `pixi run -e dev python -c "import tomllib,pathlib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); t=d['tool']['pixi']['tasks']; print(sorted(t)); assert 'dev' not in t and 'notebooks-create' not in t and 'dev-mode' in t; print('OK')"`
Expected: the sorted task list followed by `OK`.

- [ ] **Step 4: Smoke-test the task against a throwaway project**

```bash
WS="$(mktemp -d)"
pixi run project-create "$WS" Probe
pixi run dev-mode "$WS" Probe nhm
pixi run dev-mode "$WS" Probe nhm
```

Expected: the first `dev-mode` reports `created:` for every notebook and ends with the count, the directory, and the `jupyter lab <path>` line. The second run reports `already dev-configured:` for every notebook and starts no Jupyter process. Then `rm -rf "$WS"`.

- [ ] **Step 5: Run the full suite and stage**

Run: `pixi run test`
Expected: PASS, 84 tests (this task adds none).

```bash
git add pyproject.toml
```

---

## Task 5: Per-project `jupytext.toml`

Gives end users — and any ad hoc notebook they create anywhere under the project — same-directory `.py` pairing with no per-notebook setup.

**Files:**
- Modify: `src/assist/workspace/service.py:41-60` (`create_project`)
- Test: `tests/test_multi_model_workspace.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `create_project()`'s returned dict gains a `"jupytext_config"` key holding the `Path` to `<project>/jupytext.toml`. Existing keys (`project`, `marker`, `models`, `project_config`, `notebooks`) are unchanged; no existing test asserts on the dict's exact key set, so this is additive.

- [ ] **Step 1: Write the failing tests**

Add these tests to `ProjectSharedNotebookServiceTests` in `tests/test_multi_model_workspace.py`:

```python
    def test_create_project_writes_a_jupytext_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()

            paths = service.create_project(workspace_root, "Project_A")

            config = workspace_root / "Project_A" / "jupytext.toml"
            self.assertEqual(paths["jupytext_config"], config)
            self.assertTrue(config.is_file())
            self.assertIn('formats = "ipynb,py:percent"', config.read_text())

    def test_create_project_never_overwrites_an_existing_jupytext_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            project_dir = workspace_root / "Project_A"
            project_dir.mkdir(parents=True)
            config = project_dir / "jupytext.toml"
            custom = 'formats = "ipynb,scripts//py:light"\n'
            config.write_text(custom, encoding="utf-8")

            service.create_project(workspace_root, "Project_A")

            self.assertEqual(config.read_text(), custom)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pixi run -e dev pytest tests/test_multi_model_workspace.py -k jupytext -v`
Expected: FAIL — `KeyError: 'jupytext_config'`.

- [ ] **Step 3: Write the implementation**

In `src/assist/workspace/service.py`, add this constant immediately after the `_PROJECT_MARKER_CONTENT` block:

```python
JUPYTEXT_CONFIG_FILENAME = "jupytext.toml"

_JUPYTEXT_CONFIG_CONTENT = (
    "# Pair every notebook under this project to a same-directory .py file.\n"
    "# jupytext walks up from each notebook to find this file, so it covers the\n"
    "# generated workflow notebooks and any sandbox notebook you create yourself.\n"
    'formats = "ipynb,py:percent"\n'
)
```

Then, inside `create_project`, immediately before the closing `return paths`, add:

```python
    jupytext_config_path = project_dir / JUPYTEXT_CONFIG_FILENAME
    if not jupytext_config_path.exists():
        jupytext_config_path.write_text(_JUPYTEXT_CONFIG_CONTENT, encoding="utf-8")
    paths["jupytext_config"] = jupytext_config_path
```

The `if not ... .exists()` guard mirrors the marker-file guard directly above it: a user's own pairing customization must survive a re-run of `project-create`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pixi run -e dev pytest tests/test_multi_model_workspace.py -v`
Expected: PASS, 25 tests.

- [ ] **Step 5: Verify same-directory pairing really works**

```bash
WS="$(mktemp -d)"
pixi run project-create "$WS" Probe
mkdir -p "$WS/Probe/notebooks/sandbox"
pixi run -e dev python -c "
import jupytext, sys
nb = jupytext.reads('# %%\nprint(1)\n', fmt='py:percent')
jupytext.write(nb, sys.argv[1])
" "$WS/Probe/notebooks/sandbox/scratch.ipynb"
pixi run -e dev python -m jupytext --sync "$WS/Probe/notebooks/sandbox/scratch.ipynb"
ls "$WS/Probe/notebooks/sandbox/"
```

Expected: the listing shows both `scratch.ipynb` and `scratch.py` — confirming an ad hoc notebook, created by hand in a folder nobody configured, picks up pairing from the project root. Then `rm -rf "$WS"`.

- [ ] **Step 6: Run the full suite and stage**

Run: `pixi run test`
Expected: PASS, 86 tests (84 + 2 here).

```bash
git add src/assist/workspace/service.py tests/test_multi_model_workspace.py
```

---

## Task 6: `setup`'s menu stops launching Jupyter

**Files:**
- Modify: `src/assist/workspace/setup.py:1-16` (imports), `:407-419` (`generate_nhm_notebooks`), `:463-553` (delete the probe and launcher, add the replacement), `:638` (menu label), `:707` (dispatch)
- Test: `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `DEFAULT_KERNEL_DISPLAY_NAME`, `DEFAULT_KERNEL_NAME`, `ensure_kernel_registered` from Task 1.
- Produces: `action_show_notebook_location(state, *, print_func=print) -> Path | None`, replacing `action_launch_jupyter` at menu position 4. `JUPYTER_STARTUP_PROBE_SECONDS`, `_default_jupyter_readiness_probe`, and `action_launch_jupyter` no longer exist.

- [ ] **Step 1: Write the failing tests**

In `tests/test_workspace_setup.py`, **delete** these seven now-obsolete tests, which all exercise subprocess launching:

`test_action_launch_jupyter_uses_project_root`, `test_action_launch_jupyter_reports_when_jupyterlab_missing`, `test_action_launch_jupyter_reports_when_process_exits_immediately`, `test_action_launch_jupyter_reports_when_popen_raises`, `test_action_launch_jupyter_generates_notebooks_when_needed`, `test_action_launch_jupyter_prints_loading_before_ready`, `test_action_launch_jupyter_reports_timeout_when_never_ready`.

Then add this class:

```python
class NotebookLocationActionTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name).resolve()
        self.workspace_root = self.tmp_path / "workspace"
        service.create_project(self.workspace_root, "Project_A")
        self.state = setup.SetupState(
            repo_root=self.tmp_path / "repo",
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        kernel_patcher = patch.object(
            setup, "ensure_kernel_registered", return_value=False
        )
        kernel_patcher.start()
        self.addCleanup(kernel_patcher.stop)

    def test_prints_the_path_and_the_command_without_spawning_anything(self):
        lines = []
        with patch("subprocess.Popen") as mock_popen:
            result = setup.action_show_notebook_location(
                self.state, print_func=lines.append
            )

        mock_popen.assert_not_called()
        output = "\n".join(lines)
        self.assertEqual(result.name, "nhm")
        self.assertIn(str(result), output)
        self.assertIn("jupyter lab", output)
        self.assertIn(setup.DEFAULT_KERNEL_DISPLAY_NAME, output)

    def test_generates_notebooks_first_when_they_are_missing(self):
        with patch.object(setup, "generate_nhm_notebooks") as mock_generate:
            setup.action_show_notebook_location(
                self.state, print_func=lambda *_: None
            )

        mock_generate.assert_called_once()

    def test_returns_none_without_a_current_project(self):
        self.state.current_project = None

        result = setup.action_show_notebook_location(
            self.state, print_func=lambda *_: None
        )

        self.assertIsNone(result)


class LauncherRemovalTests(unittest.TestCase):
    def test_jupyter_launcher_is_gone(self):
        self.assertFalse(hasattr(setup, "action_launch_jupyter"))
        self.assertFalse(hasattr(setup, "_default_jupyter_readiness_probe"))
        self.assertFalse(hasattr(setup, "JUPYTER_STARTUP_PROBE_SECONDS"))
```

Two notes on this class. It patches `subprocess.Popen` globally rather than `setup.subprocess.Popen`, because Step 5 removes `subprocess` from `setup.py`'s imports entirely — the assertion is "nothing anywhere spawned a process", which the global patch expresses correctly.

And its `setUp` patches `ensure_kernel_registered`: `action_show_notebook_location` generates notebooks when they are missing, which would otherwise install a real kernelspec into the developer's home directory as a side effect of running the test suite.

Finally, in `test_run_setup_dispatch_maps_new_numbers`, change the entry for choice `4` from `"action_launch_jupyter"` to `"action_show_notebook_location"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pixi run -e dev pytest tests/test_workspace_setup.py -v`
Expected: FAIL — `AttributeError: module 'assist.workspace.setup' has no attribute 'action_show_notebook_location'`, and `LauncherRemovalTests` fails because `action_launch_jupyter` still exists.

- [ ] **Step 3: Register the default kernel when generating notebooks**

In `src/assist/workspace/setup.py`, replace the body of `generate_nhm_notebooks` (currently lines 407-425) with:

```python
def generate_nhm_notebooks(
    state: SetupState,
    *,
    print_func=print,
) -> list[Path]:
    workspace_root = require_workspace_root(state)
    ensure_kernel_registered(DEFAULT_KERNEL_NAME, DEFAULT_KERNEL_DISPLAY_NAME)
    created = notebook_builder.convert_workflow(
        "nhm",
        workspace_root=workspace_root,
        project_name=state.current_project,
        dry_run=False,
        print_func=lambda *_: None,
    )
    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        workspace_root,
        state.current_project,
    )
    print_func(f"Generated NHM notebooks in {notebook_dir}")
    return created
```

The `print_func=lambda *_: None` keeps `convert_workflow`'s new per-file chatter out of the interactive menu, which prints its own one-line summary.

- [ ] **Step 4: Replace the launcher with a location printer**

Delete lines 463-553 of `src/assist/workspace/setup.py` — that is `JUPYTER_STARTUP_PROBE_SECONDS`, the whole of `_default_jupyter_readiness_probe`, and the whole of `action_launch_jupyter`, up to but not including `def action_show_current_setup(`. In their place, put:

```python
def action_show_notebook_location(
    state: SetupState,
    *,
    print_func=print,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None

    workspace_root = require_workspace_root(state)

    if nhm_notebooks_need_generation(state):
        print_func("Generating NHM notebooks first…")
        generate_nhm_notebooks(state, print_func=print_func)

    notebook_dir = bridge.get_project_workflow_notebooks_dir(
        "nhm",
        workspace_root,
        state.current_project,
    )

    quoted = shlex.quote(str(notebook_dir))
    print_func("")
    print_func(f"Your NHM notebooks are in: {notebook_dir}")
    print_func("Open them yourself with whichever tool you use:")
    print_func(f"  jupyter lab {quoted}")
    print_func(f"  code {quoted}")
    print_func(f"Then select the '{DEFAULT_KERNEL_DISPLAY_NAME}' kernel.")
    print_func("Run 0_workspace_setup.ipynb first.")
    return notebook_dir
```

- [ ] **Step 5: Fix the imports**

Removing the launcher orphans four imports: `importlib.util`, `subprocess`, `sys`, and `time` were each used only by `action_launch_jupyter` or `_default_jupyter_readiness_probe`. Delete all four. Keep `shlex` — `action_show_notebook_location` uses it. The import block becomes:

```python
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

from assist.workspace import bridge, service
from assist.workspace.examples import list_available_example_names
from assist.workspace.kernels import (
    DEFAULT_KERNEL_DISPLAY_NAME,
    DEFAULT_KERNEL_NAME,
    ensure_kernel_registered,
)
from workflow_templates import make_notebooks as notebook_builder
```

Verify the removals were safe: `grep -n "importlib\|subprocess\|sys\.\|time\." src/assist/workspace/setup.py` must return no output.

The test file has the same problem: `tests/test_workspace_setup.py:3` imports `sys`, used only at line 216 inside `test_action_launch_jupyter_uses_project_root`, which Step 1 deletes. Remove `import sys` from that file too, and confirm with `grep -n "sys\." tests/test_workspace_setup.py` returning no output.

- [ ] **Step 6: Update the menu label and the dispatch**

At line 638, change:

```python
    print_func("  4. Launch Jupyter")
```

to:

```python
    print_func("  4. Show notebook folder and how to open it")
```

At line 707, change:

```python
                elif choice == 4:
                    action_launch_jupyter(state, print_func=print_func)
```

to:

```python
                elif choice == 4:
                    action_show_notebook_location(state, print_func=print_func)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pixi run -e dev pytest tests/test_workspace_setup.py -v`
Expected: PASS, 29 tests (32 existing − 7 deleted + 4 new).

- [ ] **Step 8: Confirm no launch path survives anywhere**

Run: `grep -rn "jupyter lab\|Popen\|launch_jupyter" --include="*.py" --include="*.toml" src/ pyproject.toml`
Expected: exactly two hits — `setup.py`'s `f"  jupyter lab {quoted}"` print line and `make_notebooks.py`'s `Open them with: jupyter lab` print line. No `Popen` anywhere, no `launch_jupyter` anywhere, and no `jupyter lab` inside any `cmd = ` in `pyproject.toml`.

Run: `pixi run test`
Expected: PASS, 83 tests (86 − 7 deleted + 4 added).

- [ ] **Step 9: Stage the changes**

```bash
git add src/assist/workspace/setup.py tests/test_workspace_setup.py
```

---

## Task 7: README

**Files:**
- Modify: `README.md:58-62` (guided-setup list), `:68-76` (cheat sheet), `:96-100` (workspace command block), `:129-166` (the whole "Developing nhm-assist notebooks" section)

**Interfaces:**
- Consumes: the final task names and behavior from Tasks 4, 5, and 6.
- Produces: documentation only.

- [ ] **Step 1: Fix the guided-setup list**

Replace item 4 of the numbered list under `pixi run setup`:

```markdown
4. Launch JupyterLab (generates the NHM notebooks first if needed)
```

with:

```markdown
4. Show the notebook folder and the command to open it (generates the NHM notebooks first if needed)
```

- [ ] **Step 2: Replace the pixi task cheat sheet**

The current table points at three repo-relative directories that do not exist. Replace the whole "## Pixi task cheat sheet" section — the table and the parenthetical under it — with:

```markdown
## Pixi task cheat sheet

Notebooks are always generated into a project inside your workspace; there is no
notebook directory inside the repository.

| Goal | Command |
| --- | --- |
| Generate one workflow's notebooks | `pixi run notebooks-create-project <workspace-root> <project-name> nhm` |
| Generate every workflow's notebooks | `pixi run notebooks-create-project <workspace-root> <project-name> all` |
| Generate them paired back to the templates (contributors) | `pixi run dev-mode <workspace-root> <project-name> nhm` |
| Open them | `jupyter lab <workspace-root>/<project-name>/notebooks/nhm` |

No pixi task starts JupyterLab. Each one prints the folder it wrote to and the
command to open it, so you can use JupyterLab, VS Code, Kiro, or anything else.
```

- [ ] **Step 3: Fix the workspace command block**

In the "## Pixi Workspace for NHM" section, the `text` code block ends with a `pixi run jupyter lab ...` line that reads as a task. Replace these two lines:

```text
pixi run notebooks-create-project <workspace-root> <project-name> nhm
pixi run jupyter lab <workspace-root>/<project-name>/notebooks/nhm
```

with:

```text
pixi run notebooks-create-project <workspace-root> <project-name> nhm
```

and add this sentence immediately after the code block, before the existing "Run `0_workspace_setup.ipynb` first" line:

```markdown
The last command prints the notebook folder and the command to open it. Open that
folder however you like, and select the **Python (nhm-assist)** kernel.
```

Also add a bullet to the list above that code block, after "generated NHM notebooks live once per project":

```markdown
- each project gets a `jupytext.toml` pairing every notebook to a same-directory `.py`, so your work is reviewable in git
```

- [ ] **Step 4: Rewrite the contributor section**

Replace the entire "## Developing nhm-assist notebooks" section — from that heading through the end of the "### Why this is separate from `pixi run setup`" paragraph, i.e. everything before "## nhm-assist plots and maps" — with:

```markdown
## Developing nhm-assist notebooks

Contributors use the **same** workspace flow as everyone else. There is no
separate in-repo notebook directory and no contributor-only Jupyter launcher —
you work against your own project, exactly like a user would, so the path you
exercise is the path they get.

Set up a project once:

```bash
pixi run project-create <workspace-root> my-test-project
pixi run model-copy-example <workspace-root> my-test-project Walla_Walla Walla_Walla
pixi run project-set-active-model <workspace-root> my-test-project Walla_Walla
```

Then generate the notebooks in **dev mode**:

```bash
pixi run dev-mode <workspace-root> my-test-project nhm
```

That command:

1. Generates `<workspace-root>/my-test-project/notebooks/nhm/*.ipynb` — the same
   location a real user sees.
2. Pairs each notebook back to its real source template in
   `src/workflow_templates/nhm/*.py` via jupytext metadata, so **saving the
   notebook writes your edit straight into the repo**, where git can see it.
3. Registers and stamps the `Python (nhm-assist dev)` kernel, so the notebook
   opens against the `dev` pixi environment without you picking it each time.
4. Prints the folder and the command to open it. It does **not** start Jupyter.

Re-running `dev-mode` is safe: it never rewrites the content of a notebook that
already exists. It only repairs pairing or kernel metadata that has drifted, and
tells you which of "created", "already dev-configured", or "metadata updated"
applied to each file.

Only the `.py` templates are committed — `*.ipynb` is gitignored.

### Targeting NHF or PEST templates

`dev-mode` defaults to the `nhm` workflow. Pass a different one as the third
argument:

```bash
pixi run dev-mode <workspace-root> my-test-project nhf
pixi run dev-mode <workspace-root> my-test-project pest
```

### How dev mode differs from normal use

Both write notebooks into the same place. The only difference is where the
paired `.py` file lives:

| | `notebooks-create-project` (and `setup`) | `dev-mode` |
| --- | --- | --- |
| Paired `.py` | Same folder as the notebook, via the project's `jupytext.toml` | The real template in `src/workflow_templates/<workflow>/` |
| Kernel | `Python (nhm-assist)` (default env) | `Python (nhm-assist dev)` (dev env) |
| Edits land in | Your project | The nhm-assist repo |

Everything else — how the notebook finds the active model, where outputs go —
is identical, which is the point.
```

- [ ] **Step 5: Verify no stale references survive**

Run: `grep -nE "pixi run dev($| )|notebooks-create($|[^-])|nhf_assist/notebooks|pestpp_ies_calibration/notebooks|Launch JupyterLab" README.md`
Expected: no output. (Anchor on end-of-line or a non-hyphen rather than `\b`, which would also match the `dev-mode` and `notebooks-create-project` references that must stay.)

Run: `grep -n "dev-mode\|jupytext.toml\|nhm-assist dev" README.md`
Expected: several hits across the cheat sheet, the workspace section, and the contributor section.

- [ ] **Step 6: Read the changed sections end to end**

Read `README.md` from the "## Pixi task cheat sheet" heading through the start of "## nhm-assist plots and maps". Confirm every command shown is a task that still exists in `pixi task list` and that no sentence promises a Jupyter launch.

- [ ] **Step 7: Final full verification and stage**

Run: `pixi run test`
Expected: PASS, 83 tests.

Run: `pixi task list`
Expected: `dev-mode` present; `dev` and `notebooks-create` absent.

```bash
git add README.md
git status --short
```

Expected staged set, and nothing else modified:

```text
M  README.md
M  pyproject.toml
M  src/assist/workspace/__init__.py
M  src/assist/workspace/bridge.py
A  src/assist/workspace/kernels.py
M  src/assist/workspace/service.py
M  src/assist/workspace/setup.py
M  src/workflow_templates/make_notebooks.py
M  tests/test_model_notebook_generation.py
M  tests/test_multi_model_workspace.py
A  tests/test_workspace_kernels.py
M  tests/test_workspace_setup.py
```

Do not commit. Hand off to the maintainer.

---

## Spec coverage

| Spec section | Task |
| --- | --- |
| Design §1 — remove repo-relative notebook dirs | Task 2 |
| Design §2 — per-project `jupytext.toml` | Task 5 |
| Design §3 — `pairing_mode` | Task 3 |
| Design §4 — kernel registration | Task 1 (helper), Task 3 (dev stamping), Task 6 (default stamping) |
| Design §5 — `dev-mode` task | Task 3 (CLI flag, statuses), Task 4 (task definition) |
| Design §6 — `setup`'s menu | Task 6 |
| Design §7 — data flow | Verified by Task 3 Step 5 and Task 5 Step 5; documented in Task 7 |
| Design §8 — README | Task 7 |
| Testing — `pairing_mode` metadata | Task 3 Step 1 |
| Testing — idempotency | Task 3 Step 1 (`test_dev_mode_is_idempotent`), Task 4 Step 4 |
| Testing — `jupytext.toml` not overwritten | Task 5 Step 1 |
| Testing — kernel helper idempotent | Task 1 Step 1 |
| Testing — `setup` spawns no subprocess | Task 6 Step 1 |

## Open item for the maintainer

The spec says dev-mode pairing may use "a repo-relative or absolute path". Testing
against jupytext 1.19.3 showed absolute paths do not work — jupytext concatenates
the prefix onto the notebook's own directory. This plan therefore commits to a
relative prefix computed with `os.path.relpath`. The one consequence worth knowing:
on Windows, a workspace on a different drive letter from the repo cannot be
dev-paired at all, and `dev_pairing_formats` raises a clear `ValueError` saying so.
Normal (`local`) use is unaffected. If cross-drive dev-mode on Windows matters,
that needs a follow-up design — symlinking or requiring a same-drive workspace are
the obvious options.

---

## Execution notes (2026-08-30)

The plan was executed end to end. Final state: **84 tests passing**, all seven
tasks staged. Five things differed from the plan as written; each is reflected in
the code that shipped.

**1. dev pairing needed a resolution guard — the biggest change.** The plan
predicted one failure mode (Windows cross-drive) and got the class right but the
scope wrong. jupytext's `full_path` consumes one component of the notebook's
directory per leading `../`; once the directory is spent, the result silently
loses its leading separator and becomes a *relative* path, so jupytext writes the
template into the process's working directory and the contributor's edit is lost.
This happens whenever the workspace and the repo share no ancestor but the
filesystem root. Measured:

| Workspace | Result |
| --- | --- |
| `~/nhm-workspace` (README default) | works |
| `~/Documents/ws` | works |
| `/tmp/ws` (only common ancestor is `/`) | silently wrote a bogus `Users/...` tree into the CWD |

`dev_pairing_formats` now calls `_assert_pairing_resolves`, which asks jupytext's
own `paired_paths` where the pairing lands and raises a `ValueError` naming the
workspace, the template dir, and the path it would have written. The README
documents the constraint. A symlink-based approach would lift the restriction
entirely and is the obvious follow-up if workspaces on separate volumes matter.

**2. The tests had to stop using the platform temp directory.** On macOS
`tempfile.TemporaryDirectory()` returns `/var/folders/...`, which is exactly the
unreachable case above — so `PairingModeTests` anchors its temp workspace beside
the repo (`TEMPLATES_ROOT.parents[1].parent`). Related: the original
`test_dev_pairing_formats_is_relative_and_resolves_to_the_template` resolved the
prefix with `os.path` semantics and passed even while jupytext was getting it
wrong. It now resolves through `paired_paths`. That test gap is why the bug
survived to Step 5.

**3. Task 6 broke two tests the plan did not list.**
`test_action_generate_nhm_notebooks_calls_convert_workflow` asserted the exact
kwargs of `convert_workflow` (the action now passes `print_func` to mute per-file
output), and `test_print_main_menu_lists_guided_then_more_options` asserted the
literal string `"4. Launch Jupyter"`. Both were updated.

**4. Two verification greps in the plan were wrong** and are corrected above:
in grep, `\b` matches between `e` and `-`, so `notebooks-create\b` also matches
`notebooks-create-project`, and `pixi run dev\b` also matches `pixi run dev-mode`.

**5. `tests/` is gitignored (`.gitignore:488`), so `tests/test_workspace_kernels.py`
is untracked** and its 5 tests do not run in CI. The five pre-existing test files
are tracked and staged normally, but adding *any* new test file — or re-staging a
tracked one — requires `git add -f`, because the rule ignores the directory
itself. Left as-is by maintainer decision; removing that one line would fix it.
Local runs see 84 tests; CI will see 79.
