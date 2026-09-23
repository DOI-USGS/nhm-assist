# Dev mode: stop the notebook and its template from diverging

**Date:** 2026-09-16
**Status:** Draft, pending review
**Branch:** off `feature/pixi-envs-and-netcdf-fix`
**Builds on:** `docs/design/specs/2026-08-18-dogfooding-notebook-workflow-design.md`

## Context

Contributors working in dev mode report that the workspace `.ipynb` and the repo
`.py` template "get out of sync". Dev mode is the pairing introduced by the
2026-08-18 dogfooding spec: `make_notebooks.py --pairing-mode dev` stamps a
relative `formats` path into the workspace notebook so that editing the notebook
edits the repo template.

This spec identifies three independent defects behind that report, all
reproduced, and proposes fixes. One of them silently destroys committed work.

### Which editor this was verified against

The USGS collaborators developing the notebooks work in **Kiro**, not VS Code.
Everything below was verified on VS Code with `caenrigen.jupytext-sync` 1.5.0 and
jupytext 1.19.5. What carries over, and what does not:

- **Carries over.** Root causes A and C are properties of jupytext and of the
  template files themselves, independent of the editor. The window-scoped settings
  behaviour and the sync-on-open/sync-on-save logic live in the extension's own
  code, which is the same build on Open VSX that Kiro installs.
- **Not verified.** Whether Kiro reads folder settings from `.vscode/settings.json`
  at all, where its user-level settings live, and where it installs extensions.
  Kiro is Code OSS-based, which makes `.vscode/` likely, but it is a fork and this
  was not confirmed — no Kiro install was available.

That gap matters more than a detail. If Kiro does not read the generated
`.vscode/settings.json`, the collaborators never received the interpreter setting,
and Jupytext Sync may have been resolving some other interpreter — or failing
silently — the whole time. That would be a simpler and more urgent explanation for
their reports than root cause B, and it is the first thing to check. See Task 0.

## Problem

### Root cause A — the pairing is recorded only in the notebook

`_apply_pairing` sets `notebook_metadata_filter = "-all"` for dev mode
(`make_notebooks.py`), so the template is written without a YAML header. The repo
has no `jupytext.toml` and no `[tool.jupytext]` in `pyproject.toml`, and jupytext's
config search walking up from `src/workflow_templates/common/` finds nothing.

The result is asymmetric. Asked what each side is paired to, jupytext says:

```
from .py  : [{'extension': '.py', 'format_name': 'percent'}]          <- no pairing
from .ipynb: [{'extension': '.ipynb'},
              {'prefix': '../../../../nhm-assist/src/workflow_templates/common/',
               'format_name': 'percent', 'extension': '.py'}]
```

Only the notebook can drive a sync. The template is passive.

The `-all` filter is not incidental and should not simply be removed: the relative
pairing path is specific to one contributor's workspace layout, so writing it into
the shared template would churn the repo on every contributor's save. That
rationale is recorded in `_apply_pairing` and still holds.

The consequence is that **saving the template does nothing**. A contributor edits
`src/workflow_templates/common/0_workspace_setup.py`, saves, and the Jupytext Sync
extension reports:

```
[jupytext] Warning: '...0_workspace_setup.py' is not a paired notebook
```

The notebook is untouched. On its own this reads as "out of sync", and it
contradicts AGENTS.md, which tells contributors to edit the `.py` and expect the
notebook to follow.

### Root cause B — no sync on notebook open, so a pull gets clobbered

`_vscode_settings_content` in `src/assist/workspace/service.py` writes
`"onNotebookDocumentOpen": false`, copied from the extension's own defaults. Since
that is also the extension's built-in default, the loop below occurs whether or not
the editor reads the generated file — which means it applies to Kiro regardless of
how Task 0 resolves. In dev mode it turns a routine `git pull` into silent data
loss:

1. `git pull` brings new template content; the `.py` is now the newer file.
2. The contributor opens the notebook. No sync fires on open, so the notebook
   still shows the old content.
3. They run a cell and save. The notebook is now newest, so sync pushes the
   **stale** notebook over the **freshly pulled** template.

The pulled changes are gone and the repository looks as though it reverted itself.

AGENTS.md's "the paired notebook updates on its own when you open/run it in
Jupyter" is true of JupyterLab, where the jupytext contents manager syncs on open.
It is not true of VS Code or Kiro with the settings this repo generates — which is
exactly where the promise fails silently, and where the collaborators work.

### Root cause C — 47 templates carry stale `formats:` headers

47 templates under `src/workflow_templates/` still carry YAML headers from the
pre-workspace layout, pointing at in-repo notebook directories that no longer
exist as a concept:

```
common/*.py : formats: notebooks///ipynb,src/workflow_templates/common///py:percent
nhf/*.py    : formats: nhf_assist/notebooks///ipynb,src/workflow_templates/nhf///py:percent
pest/*.py   : formats: pestpp_ies_calibration/notebooks//ipynb,src/workflow_templates/pest//py:percent
```

These give the template a *wrong* pairing, which is worse than none. Saving one
with sync enabled materializes a notebook inside the repository:

```
[jupytext] creating missing directory notebooks\
[jupytext] Updating notebooks/2_model_hydrofabric_visualization.ipynb
```

Those paths are gitignored, so nothing gets committed, but it contradicts the
README's "there is no notebook directory inside the repository" and leaves a
second, divergent copy that a later sync can write back over the template.

This also matters for anyone who adds the repo folder to the same editor window
as their workspace project: `jupytextSync.*` settings are window-scoped, so
sync-on-save applies to the repo templates too.

## Evidence

All reproductions ran against `.pixi/envs/default` (jupytext 1.19.5) in a scratch
sandbox that mirrors the dev-mode layout — a fake repo and a workspace project as
siblings — built by calling `dev_pairing_formats` and `_apply_pairing` directly so
the pairing is identical to what `make_notebooks.py` produces. No real template was
modified.

| # | Scenario | Result |
| --- | --- | --- |
| 1 | Edit template, sync the `.py` | `Warning: ... is not a paired notebook`; notebook unchanged |
| 2 | Template newer, notebook not edited, sync the `.ipynb` | Template change pulled in correctly — self-heals |
| 3 | Both sides edited, notebook saved last, sync the `.ipynb` | Exit **0**, no warning, **template edit silently destroyed** |
| 4 | Template newer, notebook holds saved outputs, sync the `.ipynb` | Template change pulled in **and outputs preserved** |

Scenario 3 is the data-loss case. Scenarios 2 and 4 together are what makes the
proposed fix viable: syncing from the notebook side at open time pulls the
template forward without costing the contributor their outputs.

## Goals

- A contributor in dev mode who pulls, opens the notebook, works, and saves does
  not lose the pulled template changes.
- Templates carry no pairing metadata that resolves anywhere but the contributor's
  own workspace notebook.
- The documented workflow in AGENTS.md and README matches what VS Code and Kiro
  actually do, or says plainly where it does not.

## Non-goals

- Changing the dev-mode pairing mechanism itself. The relative-path `formats`
  approach and the `-all` filter stay.
- Making the repo template an equal partner in the sync. It cannot be, for the
  workspace-specificity reason above; the notebook remains the driver.
- Committing `.vscode/` files to this repository. Settled separately: the
  interpreter path is machine-specific, and recommending the extension to anyone
  who opens the repo would trigger root cause C on every save.
- Fixing jupytext's silent last-writer-wins behaviour. That is upstream.

## Decisions

### Set `onNotebookDocumentOpen: true` in generated project settings

This is the fix for root cause B, and the only one that closes the common loop.
Opening the notebook pulls the latest template first, so the subsequent save
pushes forward rather than backward. Scenario 4 confirms outputs survive.

Alternatives considered:

- *Leave the extension defaults alone and document the hazard.* Rejected: the
  failure is silent and costs committed work. Documentation does not stop it.
- *Also set `onTextDocumentOpen: true`.* Rejected: opening a `.py` should not
  create or touch notebooks, and it does nothing for the failure loop.

### Apply the flag in both pairing modes, not just dev

`create_project` writes `.vscode/settings.json` before a pairing mode is ever
chosen — mode is a `make_notebooks.py` argument, selected later and changeable per
run. Making the file mode-dependent means having dev-mode generation rewrite a
file it does not currently own.

Sync-on-open is harmless in local mode: it reconciles a notebook against its
sibling `.py`, which is the same thing a save already does. Take the simpler
change.

### Strip the stale YAML headers from all 47 templates

Not just the `formats:` line — the whole `# ---` header, matching
`0_workspace_setup.py`, which already has none and works. `make_notebooks.py`
overrides `formats` and `kernelspec` at generation time regardless, so the headers
contribute nothing and actively mislead any jupytext invocation inside the repo.

Leaving `formats:` off but keeping the rest of the header was considered and
rejected: it leaves the same "not a paired notebook" warning with extra noise, and
the remaining `jupytext_version` fields churn across contributors.

### Document that saving a template does not push to the notebook

Root cause A cannot be fixed without breaking the workspace-specificity
constraint, so it must be stated instead of implied away. AGENTS.md currently
promises the opposite.

## Design

### Task 0 — establish what Kiro actually reads (do this first)

Everything else assumes the generated `.vscode/settings.json` reaches the editor.
That is verified for VS Code and unverified for Kiro, so confirm it on a
collaborator's machine before building on it. Nothing here changes any file.

1. Open a generated project in Kiro. From the command palette run **Jupytext Sync:
   Show Logs** and read which interpreter it resolved. The log line is
   `Python '<path>' resolved to: <path>`. If it names the project's pixi
   interpreter, Kiro is reading the folder settings and Task A applies as written.
   If it names something else, or reports a failure to locate an interpreter, it is
   not.
2. If it is not, find where Kiro keeps folder and user settings, and decide whether
   `create_project` should write an additional file (for example a `.kiro/`
   equivalent) alongside `.vscode/`.
3. Record the answer in this spec before starting Task A.

Worth asking the collaborators directly as part of this: whether saving a notebook
has ever appeared to revert a template, and whether they have seen the
`is not a paired notebook` warning. Those distinguish root cause B from a
never-configured extension.

### Task A — generated settings

`src/assist/workspace/service.py`, `_vscode_settings_content`:

- Set `"onNotebookDocumentOpen": True`.
- Extend the existing comment to record why this one value deliberately departs
  from the extension's defaults, referencing this spec.

`tests/test_multi_model_workspace.py`,
`test_create_project_writes_vscode_jupytext_sync_settings` asserts the full
`syncDocuments` dict and must be updated in step.

Note that `create_project` only writes the file when it does not already exist, so
**existing projects will not pick this up**. Decide whether to ship a one-line note
in the README telling contributors to flip it by hand, or to add a repair path.
See open questions.

### Task B — strip stale template headers

Remove the leading `# ---` / `# jupyter:` block from the 47 files listed by:

```
grep -rln "^#     formats:" src/workflow_templates/
```

Verify afterwards that each still round-trips as percent format and that
`make_notebooks.py` produces byte-identical notebooks apart from the intended
metadata. Suggested check, per workflow:

```
pixi run notebooks-create-project <tmp-workspace> Probe all
```

Watch for templates whose header specifies something other than
`format_name: percent`; those need the format asserted another way before the
header goes, or they will be re-read under a different format.

The unification tests touch these files
(`tests/unification/test_all_template_call_sites.py` parses every template), so run
the suite before and after and compare — see Verification.

### Task C — documentation

`AGENTS.md`, "Editing workflow notebooks": replace "edit and save that `.py`, and
the paired notebook updates on its own when you open/run it in Jupyter" with the
accurate rule:

- The notebook drives the sync; the template is passive.
- In JupyterLab, opening the notebook syncs it.
- In VS Code and Kiro, opening the notebook syncs it **only** with
  `onNotebookDocumentOpen: true`.
- Saving the template pushes nothing. Reopen the notebook to pull.
- Never edit both sides between syncs: last writer wins, silently, exit 0.

`README.md`, "Developing nhm-assist notebooks": the same rule, aimed at
contributors rather than agents, plus the manual fix for pre-existing projects if
that is the route chosen in Task A.

## Risks and open questions

1. **Kiro's settings resolution is unverified.** The collaborators use Kiro, and no
   Kiro install was available to test against. If it does not read
   `.vscode/settings.json`, Task A lands with no effect for the people who reported
   the problem, and `create_project` needs to write a Kiro equivalent too. Task 0
   resolves this and gates Task A.
2. **Existing projects keep the old setting.** `create_project` never overwrites
   an existing `.vscode/settings.json` — deliberately, and there is a test pinning
   that. Options: a README note; a `--repair` style flag; or a setup-menu action
   that re-stamps the file. Needs a decision.
3. **Contributor leaves the notebook open across a pull.** No open event fires, so
   the loop in root cause B can still occur. Sync-on-open narrows the window but
   does not close it. A pre-save freshness check would, but that is extension
   behaviour we do not control.
4. **Task B is a 47-file diff.** Mechanical, but large enough to bury a real change
   in review. Land it as its own commit.
5. **`format_name` other than `percent`.** Unverified across all 47; see Task B.
6. **Windows encoding failures in the test suite.** `pixi run test` currently has
   11 pre-existing failures, several from `read_text()` calls with no
   `encoding="utf-8"` decoding templates as cp1252 — including
   `test_dev_mode_writes_a_header_free_template`, which covers exactly the dev-mode
   behaviour this spec touches. That test cannot validate Task B until it is
   repaired. The GitLab CI spec already scopes test-suite repair; this may need to
   go first, or at least that one test.

## Verification

Baseline first, on a clean tree, so pre-existing failures are not attributed to
this work:

```
pixi run test
```

Record the failure list. At the time of writing: 426 passed, 11 failed, 10 skipped.

After each task, re-run and compare failure lists — the set must not grow. Then:

1. **Root cause B fixed.** Create a project, generate dev-mode notebooks, and
   confirm `.vscode/settings.json` carries `"onNotebookDocumentOpen": true`.
   Manually: edit the template, reopen the notebook in the editor, confirm the change
   appears without a save.
2. **Root cause C fixed.** `grep -rln "^#     formats:" src/workflow_templates/`
   returns nothing. Save a template with the extension active and confirm no
   `notebooks/` directory appears at the repository root.
3. **No regression in generation.** Generate all three workflows into a scratch
   workspace, in both pairing modes, and diff against a pre-change run.

## Maintainer actions this spec cannot perform

- Deciding the repair path for existing projects (open question 1).
- Sequencing against the test-suite repair in the GitLab CI spec (open question 5).
- Committing, and opening the merge request.
