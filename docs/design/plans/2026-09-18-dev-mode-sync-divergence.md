# Dev-Mode Sync Divergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a contributor's workspace notebook and its repo template from silently diverging in dev mode, and stop a `git pull` from being clobbered by the next notebook save.

**Architecture:** Three independent defects, three independent fixes. Generated project settings gain one deliberate deviation from the Jupytext Sync extension's defaults (`onNotebookDocumentOpen`), so opening a notebook pulls the template forward before any save can push backward. A new setup-menu action re-stamps that file for projects created before the change, since `create_project` never overwrites. Forty-eight stale template YAML headers are deleted so no jupytext invocation inside the repo resolves a bogus pairing. Documentation is corrected to say that the notebook drives the sync and the template is passive.

**Tech Stack:** Python 3.11, pixi, jupytext 1.19.5, `caenrigen.jupytext-sync` 1.5.0, pytest.

**Spec:** `docs/design/specs/2026-09-16-dev-mode-sync-divergence-design.md`

## Global Constraints

- Agents stage changes with `git add` but never `git commit`, merge, push, or open a merge request. The commit steps below are written for the maintainer to run.
- Run tests with `pixi run test`. Do not introduce `pip`, `conda`, or `venv` workflows.
- **Baseline on macOS arm64 at the time of writing: 5 failed, 432 passed, 10 skipped.** The five failures are pre-existing and documented in AGENTS.md. After every task, re-run and confirm the failure set has not grown. The spec quotes 426 passed / 11 failed — that was measured on Windows, where six additional failures come from the encoding defect Task 1 fixes.
- The dev-mode pairing mechanism does not change. The relative-path `formats` approach and `notebook_metadata_filter = "-all"` stay exactly as they are.
- No `.vscode/` files are committed to this repository. They are generated into user projects only.
- Every file read or written in this plan uses an explicit `encoding="utf-8"`.

## Preconditions

This plan assumes the branch `feature/pixi-envs-and-netcdf-fix` is committed and merged, or at minimum that its staged changes are committed. That branch deletes `src/assist/workspace/kernels.py` and removes kernelspec stamping from `make_notebooks.py`; Task 4 below strips the remaining YAML headers from the same template files. Running Task 4 against an uncommitted tree makes the two changes indistinguishable in review.

## Resolved before planning

Two of the spec's open questions were closed by direct inspection on 2026-09-18 and need no task:

- **Open question 1 — does Kiro read `.vscode/settings.json`?** Yes. `/Applications/Kiro.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js` contains both `".vscode"` and `".vscode/settings.json"`; `product.json` sets `dataFolderName` to `.kiro`, which is the user-data directory, not the folder-settings directory. `caenrigen.jupytext-sync-1.5.0-universal` is installed in `~/.kiro/extensions`. **Spec Task 0 is complete and no `.kiro/` settings equivalent is needed.**
- **Open question 5 — non-`percent` formats among the templates?** No. All 50 template headers declare `format_name: percent`.

One finding sharpens the case for Task 2. The maintainer's Kiro *user* settings already contain `"jupytextSync.syncDocuments": {"onNotebookDocumentOpen": true, ...}`, but all three existing projects under `nhm-workspace/` carry `onNotebookDocumentOpen: false` at folder scope, and VS Code replaces object-typed settings wholesale per scope. The generated file — which today writes the extension's defaults verbatim and therefore deviates in nothing — is actively defeating a user who had already fixed the problem globally.

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `tests/test_multi_model_workspace.py` | Project scaffolding tests, incl. generated editor settings | 1, 2, 3 |
| `tests/test_model_notebook_generation.py` | Notebook generation and pairing tests | 1, 4 |
| `tests/unification/test_add_pois_dimensions.py` | Reads a parameter file | 1 |
| `src/assist/nhf/run_hrrr_download_s3.py` | Reads a progress file | 1 |
| `src/assist/workspace/service.py` | Owns project scaffolding, incl. `_vscode_settings_content` and the new repair function | 2, 3 |
| `src/assist/workspace/setup.py` | Interactive menu; gains one action | 3 |
| `tests/test_workspace_setup.py` | Menu and action tests | 3 |
| `src/workflow_templates/**/*.py` | 48 templates carrying stale YAML headers | 4 |
| `AGENTS.md`, `README.md` | The documented sync rule | 5 |

---

### Task 1: Decode every file read as UTF-8

Templates contain non-ASCII characters (em dashes in comments). `Path.read_text()` with no `encoding` uses the platform default, which is cp1252 on Windows, so these reads raise `UnicodeDecodeError` there and pass on macOS and Linux. This is why the spec's Windows baseline shows six more failures than ours, and it blocks `test_dev_mode_writes_a_header_free_template` — the test that validates Task 4 — from running on the machines that reported the problem.

**Files:**
- Modify: `tests/test_multi_model_workspace.py:139,141,155,165,192,202,216`
- Modify: `tests/test_model_notebook_generation.py:201`
- Modify: `tests/unification/test_add_pois_dimensions.py:40`
- Modify: `src/assist/nhf/run_hrrr_download_s3.py:37`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Behaviour is unchanged on macOS and Linux; this only removes a platform-dependent failure mode.

- [ ] **Step 1: Confirm no unencoded reads are missed**

Run: `grep -rn "\.read_text()" tests/ src/ --include='*.py'`
Expected: exactly 10 hits, at the lines listed above.

- [ ] **Step 2: Add the encoding argument at all 10 call sites**

Each is the same edit. For example, in `tests/test_model_notebook_generation.py:201`:

```python
        template_text = template_path.read_text(encoding="utf-8")
```

and in `src/assist/nhf/run_hrrr_download_s3.py:37`:

```python
    completed_months = set(
        completed_months_file.read_text(encoding="utf-8").strip().split("\n")
    )
```

Apply the identical change to the remaining eight.

- [ ] **Step 3: Verify none remain**

Run: `grep -rn "\.read_text()" tests/ src/ --include='*.py'`
Expected: no output.

- [ ] **Step 4: Run the suite**

Run: `pixi run test`
Expected: 5 failed, 432 passed, 10 skipped — unchanged from baseline on macOS. On Windows the failure count should drop.

- [ ] **Step 5: Stage**

```bash
git add tests/test_multi_model_workspace.py tests/test_model_notebook_generation.py tests/unification/test_add_pois_dimensions.py src/assist/nhf/run_hrrr_download_s3.py
```

Maintainer commits:

```
fix(tests): decode file reads as UTF-8

Path.read_text() with no encoding uses the platform default, which is
cp1252 on Windows. Templates contain em dashes, so these reads raise
UnicodeDecodeError there and pass everywhere else. Six of the Windows-only
test failures come from this, including the dev-mode header test that
validates template changes.
```

---

### Task 2: Turn on sync-on-open in generated project settings

Root cause B. The extension's default is `onNotebookDocumentOpen: false`. With it off, `git pull` brings a newer template, the contributor opens a stale notebook, runs a cell, saves, and jupytext pushes the stale notebook over the freshly pulled template — exit 0, no warning. Scenario 4 in the spec confirms that syncing on open preserves saved outputs, so the fix costs the contributor nothing.

This is the **only** deviation from the extension's declared defaults. Every other key in `syncDocuments` keeps its default value, and is written only because VS Code replaces object-typed settings wholesale per scope.

**Files:**
- Modify: `src/assist/workspace/service.py`, `_vscode_settings_content`
- Test: `tests/test_multi_model_workspace.py:157` (`test_create_project_writes_vscode_jupytext_sync_settings`)

**Interfaces:**
- Consumes: nothing.
- Produces: `_vscode_settings_content() -> str` — signature unchanged; only the value of `syncDocuments.onNotebookDocumentOpen` changes from `False` to `True`.

- [ ] **Step 1: Update the failing test**

In `tests/test_multi_model_workspace.py`, change the asserted dict:

```python
            self.assertEqual(
                settings["jupytextSync.syncDocuments"],
                {
                    "onNotebookDocumentOpen": True,
                    "onNotebookDocumentSave": True,
                    "onNotebookDocumentClose": False,
                    "onTextDocumentOpen": False,
                    "onTextDocumentSave": True,
                    "onTextDocumentClose": False,
                },
            )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `pixi run -e default python -m pytest tests/test_multi_model_workspace.py::MultiModelWorkspaceTests::test_create_project_writes_vscode_jupytext_sync_settings -v`
Expected: FAIL, with `False != True` for `onNotebookDocumentOpen`.

- [ ] **Step 3: Flip the value and record why**

In `src/assist/workspace/service.py`, replace the comment and payload in `_vscode_settings_content` with:

```python
def _vscode_settings_content() -> str:
    # Every key below carries the Jupytext Sync extension's own default value
    # except onNotebookDocumentOpen. The whole object is written because VS Code
    # (and Kiro) replace object-typed settings wholesale per scope rather than
    # merging keys, so a partial override here would silently drop the rest.
    #
    # onNotebookDocumentOpen deliberately departs from the extension's default
    # of False. With it off, a git pull followed by opening the notebook and
    # saving pushes the stale notebook over the freshly pulled template --
    # silently, exit 0. Syncing on open pulls the template forward first, and
    # saved outputs survive it. See
    # docs/design/specs/2026-09-16-dev-mode-sync-divergence-design.md.
    #
    # pythonExecutable is stamped to the interpreter running this call rather
    # than left for the extension's own auto-discovery: jupytext lives only
    # inside nhm-assist's pixi environments, which auto-discovery (the
    # ms-python.python extension's selected interpreter, venv/conda scanning,
    # then `python`/`python3` on PATH) cannot reach.
    payload = {
        "jupytextSync.pythonExecutable": sys.executable,
        "jupytextSync.syncDocuments": {
            "onNotebookDocumentOpen": True,
            "onNotebookDocumentSave": True,
            "onNotebookDocumentClose": False,
            "onTextDocumentOpen": False,
            "onTextDocumentSave": True,
            "onTextDocumentClose": False,
        },
    }
    return json.dumps(payload, indent=2) + "\n"
```

- [ ] **Step 4: Run it and watch it pass**

Run: `pixi run -e default python -m pytest tests/test_multi_model_workspace.py -v`
Expected: PASS, including `test_create_project_never_overwrites_existing_vscode_settings`, which must keep passing untouched.

- [ ] **Step 5: Run the suite**

Run: `pixi run test`
Expected: 5 failed, 432 passed, 10 skipped.

- [ ] **Step 6: Stage**

```bash
git add src/assist/workspace/service.py tests/test_multi_model_workspace.py
```

Maintainer commits:

```
fix(editor): sync notebooks on open in generated project settings

With the extension's default of onNotebookDocumentOpen false, a git pull
followed by opening the notebook and saving pushes the stale notebook over
the freshly pulled template, silently and with exit 0. Opening the notebook
now syncs it first, so the save pushes forward rather than backward. Saved
outputs survive the sync.

This is the only key that departs from the extension's defaults; the rest
of the object is written because VS Code replaces object settings wholesale
per scope.
```

---

### Task 3: Repair action for projects created before Task 2

`create_project` writes `.vscode/settings.json` only when it does not already exist, and a test pins that. Every project created before Task 2 therefore keeps `onNotebookDocumentOpen: false` forever. All three projects under the maintainer's `nhm-workspace/` are in that state today.

**Files:**
- Modify: `src/assist/workspace/service.py` — add `repair_vscode_settings`
- Modify: `src/assist/workspace/__init__.py` — export it
- Modify: `src/assist/workspace/setup.py` — add `action_repair_editor_settings`, menu entry 11, and bump the menu bound
- Test: `tests/test_multi_model_workspace.py`, `tests/test_workspace_setup.py`

**Interfaces:**
- Consumes: `_vscode_settings_content() -> str` from Task 2.
- Produces:
  - `service.repair_vscode_settings(workspace_root: str | Path, project_name: str) -> Path` — overwrites that project's `.vscode/settings.json` with current generated content and returns its path. Raises `FileNotFoundError` if the project does not exist.
  - `setup.action_repair_editor_settings(state: SetupState, *, print_func=print) -> Path`

- [ ] **Step 1: Write the failing service test**

Add to `tests/test_multi_model_workspace.py`:

```python
    def test_repair_vscode_settings_overwrites_stale_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            service.create_project(workspace_root, "Project_A")
            settings_path = workspace_root / "Project_A" / ".vscode" / "settings.json"
            settings_path.write_text(
                '{"jupytextSync.syncDocuments": {"onNotebookDocumentOpen": false}}',
                encoding="utf-8",
            )

            returned = service.repair_vscode_settings(workspace_root, "Project_A")

            self.assertEqual(returned, settings_path)
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertTrue(
                settings["jupytextSync.syncDocuments"]["onNotebookDocumentOpen"]
            )
            self.assertEqual(
                settings["jupytextSync.pythonExecutable"], sys.executable
            )

    def test_repair_vscode_settings_rejects_a_missing_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()

            with self.assertRaises(FileNotFoundError):
                service.repair_vscode_settings(workspace_root, "Nope")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `pixi run -e default python -m pytest tests/test_multi_model_workspace.py -k repair_vscode -v`
Expected: FAIL with `AttributeError: module 'assist.workspace.service' has no attribute 'repair_vscode_settings'`.

- [ ] **Step 3: Implement the repair function**

Add to `src/assist/workspace/service.py`, directly below `create_project`:

```python
def repair_vscode_settings(
    workspace_root: str | Path,
    project_name: str,
) -> Path:
    """Rewrite one project's editor settings with the current generated content.

    create_project deliberately never overwrites an existing settings file, so
    projects created before a change to _vscode_settings_content keep the old
    values indefinitely. This is the explicit opt-in that updates them.
    """
    project_dir = Path(workspace_root).expanduser().resolve() / project_name
    if not project_dir.is_dir():
        raise FileNotFoundError(f"No such project: {project_dir}")

    # VSCODE_SETTINGS_FILENAME is the whole relative path, ".vscode/settings.json",
    # so the parent directory comes from the joined path rather than a separate
    # constant. This mirrors how create_project builds vscode_settings_path.
    settings_path = project_dir / VSCODE_SETTINGS_FILENAME
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(_vscode_settings_content(), encoding="utf-8")
    return settings_path
```

- [ ] **Step 4: Run the service tests**

Run: `pixi run -e default python -m pytest tests/test_multi_model_workspace.py -k repair_vscode -v`
Expected: PASS.

- [ ] **Step 5: Export it**

In `src/assist/workspace/__init__.py`, add `repair_vscode_settings` to the `from assist.workspace.service import (...)` block and to `__all__`, keeping both alphabetical.

- [ ] **Step 6: Write the failing menu-action test**

Add to `tests/test_workspace_setup.py`:

```python
    def test_repair_editor_settings_rewrites_the_file_and_reports_the_path(self):
        lines = []

        result = setup.action_repair_editor_settings(
            self.state, print_func=lines.append
        )

        output = "\n".join(lines)
        self.assertTrue(result.exists())
        self.assertIn(str(result), output)
        settings = json.loads(result.read_text(encoding="utf-8"))
        self.assertTrue(
            settings["jupytextSync.syncDocuments"]["onNotebookDocumentOpen"]
        )
```

Place it in `NotebookLocationActionTests`, whose `setUp` already builds a `SetupState` with `current_project="Project_A"`. That file does **not** currently import `json`, so add `import json` to its import block, before `import shutil`.

- [ ] **Step 7: Run it and watch it fail**

Run: `pixi run -e default python -m pytest tests/test_workspace_setup.py -k repair_editor -v`
Expected: FAIL with `AttributeError: module 'assist.workspace.setup' has no attribute 'action_repair_editor_settings'`.

- [ ] **Step 8: Implement the action**

Add to `src/assist/workspace/setup.py`, directly below `action_show_current_setup`:

```python
def action_repair_editor_settings(
    state: SetupState,
    *,
    print_func=print,
) -> Path | None:
    if not require_current_project(state, print_func=print_func):
        return None
    workspace_root = require_workspace_root(state)
    settings_path = service.repair_vscode_settings(
        workspace_root, state.current_project
    )
    print_func("")
    print_func(f"Rewrote editor settings: {settings_path}")
    print_func(
        "Notebooks now sync from their paired template when you open them, "
        "so a pull cannot be overwritten by the next save."
    )
    print_func("Close and reopen the project folder for it to take effect.")
    return settings_path
```

`require_current_project` is the established guard — `action_generate_nhm_notebooks` uses exactly this shape — and it prints its own message and returns `False` when no project is selected. Hence the `Path | None` return type.

- [ ] **Step 9: Run it and watch it pass**

Run: `pixi run -e default python -m pytest tests/test_workspace_setup.py -k repair_editor -v`
Expected: PASS.

- [ ] **Step 10: Wire it into the menu**

In `print_main_menu`, add after the API-key line:

```python
    print_func(" 11. Repair editor settings for this project")
```

In `run_setup`, change the bound:

```python
            choice = prompt_menu_choice(11, input_func=input_func, print_func=print_func)
```

and add a branch after the `choice == 10` block, inside the same `try`:

```python
                elif choice == 11:
                    action_repair_editor_settings(state, print_func=print_func)
```

- [ ] **Step 11: Run the suite**

Run: `pixi run test`
Expected: 5 failed, 435 passed, 10 skipped — three more passing than baseline, from the two service tests and the one action test. `test_print_main_menu_lists_guided_then_more_options` asserts with `assertIn` per line rather than comparing the whole menu body, so it keeps passing unchanged and needs no edit.

- [ ] **Step 12: Stage**

```bash
git add src/assist/workspace/service.py src/assist/workspace/setup.py src/assist/workspace/__init__.py tests/test_multi_model_workspace.py tests/test_workspace_setup.py
```

Maintainer commits:

```
feat(setup): add an action to repair a project's editor settings

create_project never overwrites an existing .vscode/settings.json, so
projects created before the sync-on-open fix keep the old value forever.
This is the explicit opt-in that re-stamps it, reported through the setup
menu rather than requiring a hand edit.
```

---

### Task 4: Delete the stale template YAML headers

Root cause C. Forty-eight templates carry headers from the pre-workspace layout whose `formats:` lines point at in-repo notebook directories that no longer exist as a concept. Saving one with the sync extension active materializes a notebook inside the repository and leaves a second, divergent copy that a later sync can write back over the template. `make_notebooks.py` overrides `formats` at generation time regardless, so the headers contribute nothing.

All 50 headers declare `format_name: percent`, so none needs the format asserted another way before removal. `0_workspace_setup.py` already has no header and works, which is the proof this is safe.

**Files:**
- Modify: 48 files under `src/workflow_templates/` (`common/`, `nhf/`, `pest/`)
- Test: `tests/test_model_notebook_generation.py` (existing coverage; no new test)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. No Python signature changes.

- [ ] **Step 1: Record the before-state**

```bash
pixi run test 2>&1 | tail -8 > /tmp/before.txt
grep -rln "^#     formats:" src/workflow_templates/ | wc -l
```
Expected: the baseline failure list, and `48`.

- [ ] **Step 2: Capture a pre-change generation for comparison**

```bash
pixi run -e default python -c "
import tempfile, json, jupytext, pathlib
from assist.workspace import service
from workflow_templates import make_notebooks as nb
out = {}
with tempfile.TemporaryDirectory() as d:
    ws = pathlib.Path(d) / 'ws'
    service.create_project(ws, 'Probe')
    service.create_model(ws, 'Probe', 'Walla_Walla')
    for wf in ('nhm', 'nhf', 'pest'):
        for p in nb.convert_workflow(wf, workspace_root=ws, project_name='Probe',
                                     pairing_mode='local', print_func=lambda *a: None):
            n = jupytext.read(p)
            out[f'{wf}/{p.name}'] = [c.source for c in n.cells]
pathlib.Path('/tmp/cells_before.json').write_text(json.dumps(out, sort_keys=True), encoding='utf-8')
print('captured', len(out), 'notebooks')
"
```

- [ ] **Step 3: Strip the headers**

```bash
pixi run -e default python -c "
import pathlib, re
changed = 0
for p in sorted(pathlib.Path('src/workflow_templates').rglob('*.py')):
    text = p.read_text(encoding='utf-8')
    if not text.startswith('# ---'):
        continue
    end = text.find('\n# ---', 5)
    if end == -1:
        print('SKIPPED, unterminated header:', p)
        continue
    body = text[end + len('\n# ---'):].lstrip('\n')
    p.write_text(body, encoding='utf-8')
    changed += 1
print('stripped', changed)
"
```
Expected: `stripped 50`, no `SKIPPED` lines. The count is 50 rather than 48 because two templates carry a header without a `formats:` line; those go too, for the reason the spec gives — a partial header still churns `jupytext_version` across contributors.

- [ ] **Step 4: Verify no headers and no stray notebooks**

```bash
grep -rln "^#     formats:" src/workflow_templates/ | wc -l
grep -rl "^# ---$" src/workflow_templates/ | wc -l
ls notebooks 2>/dev/null && echo "UNEXPECTED notebooks/ dir" || echo "no notebooks/ dir at repo root"
```
Expected: `0`, `0`, and `no notebooks/ dir at repo root`.

- [ ] **Step 5: Verify every template still parses as percent format**

```bash
pixi run -e default python -c "
import jupytext, pathlib
bad = []
for p in sorted(pathlib.Path('src/workflow_templates').rglob('*.py')):
    if p.name == 'make_notebooks.py':
        continue
    try:
        jupytext.read(p, fmt='py:percent')
    except Exception as exc:
        bad.append((p, exc))
print('unreadable:', bad or 'none')
"
```
Expected: `unreadable: none`.

- [ ] **Step 6: Verify generated notebook cells are unchanged**

Re-run the Step 2 snippet writing to `/tmp/cells_after.json`, then:

```bash
pixi run -e default python -c "
import json, pathlib
a = json.loads(pathlib.Path('/tmp/cells_before.json').read_text(encoding='utf-8'))
b = json.loads(pathlib.Path('/tmp/cells_after.json').read_text(encoding='utf-8'))
print('same notebooks:', set(a) == set(b))
diff = [k for k in a if a[k] != b.get(k)]
print('notebooks with changed cells:', diff or 'none')
"
```
Expected: `same notebooks: True` and `notebooks with changed cells: none`. Cell content must be byte-identical; only the templates' headers were removed.

- [ ] **Step 7: Run the suite**

Run: `pixi run test`
Expected: the same failure list as `/tmp/before.txt`. `test_dev_mode_writes_a_header_free_template` must still pass.

- [ ] **Step 8: Stage**

```bash
git add src/workflow_templates
```

Maintainer commits this on its own, per the spec's note that a 50-file mechanical diff will otherwise bury a real change in review:

```
fix(templates): delete stale jupytext YAML headers

48 templates carried formats: lines pointing at in-repo notebook
directories that no longer exist as a concept. Saving one with the sync
extension active materialized a notebook inside the repository and left a
divergent copy a later sync could write back over the template.

make_notebooks.py sets formats at generation time regardless, so the
headers contributed nothing. 0_workspace_setup.py has never had one.
Two further templates with a header but no formats: line go too, since a
partial header still churns jupytext_version across contributors.
```

---

### Task 5: Correct the documented sync rule

Root cause A cannot be fixed without breaking the workspace-specificity constraint that the `-all` filter exists to protect, so it has to be stated rather than implied away. AGENTS.md currently promises the opposite of what happens.

**Files:**
- Modify: `AGENTS.md`, "Editing workflow notebooks"
- Modify: `README.md`, "Developing nhm-assist notebooks"

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Replace the AGENTS.md rule**

Find the paragraph beginning "The correct workflow is just: edit and save that `.py`" and replace it with:

```markdown
The notebook drives the sync; the template is passive. Dev-mode pairing is
recorded only in the notebook's own `jupytext` metadata, because writing it into
the shared template would stamp one contributor's workspace path into a file
everyone else pulls.

What follows from that:

- **Saving the template pushes nothing.** Editing `src/workflow_templates/...`
  and saving does not update anyone's notebook. jupytext reports
  `is not a paired notebook`. Reopen the notebook to pull the change.
- **In JupyterLab, opening the notebook syncs it.** The jupytext contents
  manager does this.
- **In VS Code and Kiro, opening the notebook syncs it only when the Jupytext
  Sync extension has `onNotebookDocumentOpen` set true.** Generated projects
  carry that setting; projects created before 2026-09-18 need the setup menu's
  "Repair editor settings" action.
- **Never edit both sides between syncs.** The next sync silently keeps
  whichever file is newer and discards the other, with exit code 0 and no
  warning.
```

- [ ] **Step 2: Check the surrounding AGENTS.md text still holds**

Run: `grep -n "jupytext --sync\|updates on its own\|paired notebook" AGENTS.md`
Expected: no remaining claim that saving the `.py` updates the notebook. The existing warning about not running `jupytext --sync` from the command line stays — it is still correct and unrelated.

- [ ] **Step 3: Add the contributor-facing version to README.md**

In "Developing nhm-assist notebooks", after the numbered list describing what `dev-mode` does, add:

```markdown
> **Which direction the sync flows.** The notebook is what drives it. Opening
> the notebook pulls the template's latest content into it; saving the notebook
> pushes your edits back out to the template. Saving the **template** does not
> update the notebook — jupytext will tell you it "is not a paired notebook".
>
> So after a `git pull`, reopen the notebook before you work in it. And never
> edit the notebook and the template between syncs: jupytext keeps whichever is
> newer and discards the other without warning.
>
> If you created your project before 2026-09-18, run `pixi run setup` and choose
> **Repair editor settings** once. Older projects were generated without
> sync-on-open, and without it a pull followed by a save silently reverts the
> template.
```

- [ ] **Step 4: Run the suite**

Run: `pixi run test`
Expected: unchanged from baseline. No test reads these files, so this is a guard against an accidental edit elsewhere.

- [ ] **Step 5: Stage**

```bash
git add AGENTS.md README.md
```

Maintainer commits:

```
docs: state that the notebook drives the jupytext sync

AGENTS.md promised that saving a template updates the paired notebook. It
does not: dev-mode pairing lives only in the notebook, deliberately, so the
shared template does not carry one contributor's workspace path. Saving the
template pushes nothing and jupytext reports "is not a paired notebook".

Document the real rule, including that sync-on-open is what makes reopening
the notebook pull a pull forward, and that editing both sides between syncs
loses one of them silently.
```

---

## Verification

After all five tasks:

1. **Failure set has not grown.** `pixi run test` reports the same five pre-existing failures, with the passing count up by the tests added in Task 3.
2. **Root cause B fixed.** Create a project, confirm its `.vscode/settings.json` carries `"onNotebookDocumentOpen": true`. Then, manually in Kiro: generate dev-mode notebooks, edit the repo template, reopen the notebook, and confirm the edit appears without saving.
3. **Root cause B fixed for existing projects.** Run `pixi run setup`, choose Repair editor settings on one of the three projects under `nhm-workspace/`, and confirm the file changes.
4. **Root cause C fixed.** `grep -rln "^#     formats:" src/workflow_templates/` returns nothing. Save a template in an editor with the extension active and confirm no `notebooks/` directory appears at the repository root.
5. **No regression in generation.** Task 4 Step 6 already proves cell content is byte-identical across all three workflows.

## Known limits

- **A notebook left open across a pull is still exposed.** No open event fires, so the root cause B loop can still occur. Sync-on-open narrows the window; it does not close it. Closing it needs a pre-save freshness check, which is extension behaviour this repo does not control.
- **jupytext's last-writer-wins is unchanged.** Editing both sides between syncs still silently discards one. That is upstream, and Task 5 documents it rather than fixing it.
- **Task 2 overrides a user's own `syncDocuments`.** Deliberate: the generated file must protect a contributor who has configured nothing, which is the common case here. A user wanting different sync events must edit the project file rather than their user settings.
