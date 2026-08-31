# Dogfooding notebook workflow + jupytext pairing

**Date:** 2026-08-18
**Status:** Approved design, not yet implemented

## Context

`nhm-assist` generates Jupyter notebooks from `.py` templates in
`src/workflow_templates/<workflow>/*.py` (workflows: `nhm`, `nhf`, `pest`) via
`src/workflow_templates/make_notebooks.py`, using [jupytext](https://jupytext.org)
to keep a notebook and its `.py` source in sync.

End users run these notebooks against a **workspace**: an external directory
tree (outside the repo) containing one or more **projects**
(`<workspace>/<project>/`), each of which is the git-tracked unit and can
contain multiple **models** (`<project>/models/<model>/`). A project has one
currently-selected "active model" (`<project>/project_config/active_model.yaml`)
that its shared `<project>/notebooks/<workflow>/` notebooks read at runtime.
Users can also create their own ad hoc/exploratory notebooks anywhere under a
project, e.g. `<project>/notebooks/<sandbox>/`.

Historically, **contributors** (people editing the templates themselves) used
a separate `pixi run dev` task that regenerated notebooks into a repo-root
`notebooks/` directory and launched `jupyter lab` with a custom contents
manager so edits synced back to the `.py` template. That mechanism relied on
a repo-root `jupytext.toml` file. Both the `notebooks/` directory and that
`jupytext.toml` were removed at some point during the pixi restructuring
(confirmed via `git log`: "Added jupytext.toml for tracking .py files" /
later "Deleted old main jupytext file"), and the `README.md` section
describing `pixi run dev` is now stale — it documents a mechanism that no
longer exists. `bridge.py` similarly still maps `nhf`/`pest` to repo-relative
directories (`nhf_assist/notebooks/`, `pestpp_ies_calibration/notebooks/`)
that were never actually created after the restructuring, and a
`notebooks-create` task exists to write into those repo-relative dirs.

Separately, we are moving to a **dogfooding** model: contributors should use
the exact same workflow a real end user uses (their own project/model in an
external workspace), rather than a bespoke in-repo dev-only path.

Finally, no pixi task should launch Jupyter Lab itself anymore (previously
`setup` and `dev` both did). Instead, tasks configure the right files/pairing
and print instructions for the user to open Jupyter themselves (in whatever
tool they use — CLI, VS Code, Kiro).

**Update (2026-08-28):** `pyproject.toml` has changed since this design was
drafted, but nothing below needs revision as a result. `[project.dependencies]`
is now the single authoritative runtime contract in PyPI names (commit
`4cacd6d`, 2026-08-21), with `[tool.pixi.dependencies]` trimmed to just the
conda-sourced compiled packages; `jupytext`, `jupyterlab`, `jupyter-server`,
`ipython`, and `ipywidgets` moved into that PyPI list, reaching both the
`default` and `dev` pixi environments via each feature's editable
`nhm-assist` self-install (the `prod` feature's self-install also became
`editable = true` in `bfa17d9`, matching what `dev` already had). `ipykernel`
is still pulled in transitively via `jupyterlab` in both environments, so
Design section 4's "no new dependency required" still holds. Separately, CI
was migrated off `environment.yaml` onto pixi (`c9d6620`, 2026-08-27; see
`docs/superpowers/specs/2026-08-21-ci-pixi-migration-design.md`), and a
GitLab CI migration is in flight
(`docs/superpowers/specs/2026-08-25-gitlab-ci-migration-design.md`). Neither
touches the notebook/jupytext workflow this design covers. The `[tool.pixi.tasks.*]`
table format this design's `dev-mode` snippet relies on is unchanged.

## Goals

1. Contributors dogfood the real end-user workflow (`setup` /
   `project-create` / `model-create` / `notebooks-create-project`) against
   their own project, instead of a separate in-repo mechanism.
2. A renamed `dev-mode` task additionally (a) points jupytext pairing for
   template notebooks back to the actual `src/workflow_templates/<workflow>/*.py`
   in the repo, and (b) ensures the notebook opens with the `dev` pixi
   environment selected by default.
3. End users (and any ad hoc notebook, dev or prod) get jupytext pairing to a
   same-directory `.py` file, configured per-project so it works without any
   per-notebook setup.
4. No task launches Jupyter Lab. Tasks report what they did and how to open
   the result.
5. Remove the now-fully-stale repo-relative notebook directory concept
   entirely (`nhm`, `nhf`, and `pest` alike).
6. `README.md` accurately describes the above.

## Non-goals

- Splitting `[tool.pixi.feature.*]`/environments per workflow (nhm/nhf/pest)
  — out of scope, unrelated to this change.
- Any change to how models/projects are structured on disk beyond what's
  described here.

## Design

### 1. Remove the repo-relative notebook directory concept

- `src/assist/workspace/bridge.py`: delete `REPO_NOTEBOOK_DIRS` and
  `get_workflow_notebooks_dir()`.
- `src/workflow_templates/make_notebooks.py`: `convert_workflow()` currently
  branches on `workspace_root is None` to choose between a repo-relative
  output dir and a project output dir. Remove that branch — `workspace_root`
  and `project_name` become required parameters. `in_workspace_mode` as a
  boolean is replaced by the `pairing_mode` parameter described below.
- `pyproject.toml`: remove the `notebooks-create` task (the non-project
  variant). Only `notebooks-create-project` and `dev-mode` remain as ways to
  generate notebooks.

None of `notebooks/`, `nhf_assist/notebooks/`, or
`pestpp_ies_calibration/notebooks/` exist in the current repo tree, so this
removal deletes no real content — only stale code paths and docs.

### 2. Per-project jupytext pairing

`project-create` writes a `jupytext.toml` at the project root (only if one
doesn't already exist there, so it never overwrites a user's own
customization):

```toml
# Pair every notebook to a same-directory .py file.
formats = "ipynb,py:percent"
```

This one file, discovered by jupytext walking up from any notebook under the
project, covers:

- Template-generated notebooks under `<project>/notebooks/<workflow>/` for
  end users (`pairing_mode="local"`, see below) — no special-casing needed.
- Any ad hoc/sandbox notebook a user creates themselves anywhere under the
  project, e.g. `<project>/notebooks/<sandbox>/` — jupytext requires no
  per-notebook setup for these; the project-wide default just applies.

We do **not** add any `[tool.jupytext]` configuration to `nhm-assist`'s own
`pyproject.toml`. That file's directory-scoped config can only affect
notebooks that live inside the `nhm-assist` repo tree, but after this change
no notebooks live there — they all live in external projects.

### 3. `pairing_mode` in `make_notebooks.py`

`convert_workflow()` gains a `pairing_mode: Literal["local", "dev"]`
parameter (default `"local"`):

- **`"local"`** (used by `notebooks-create-project` and `setup`): no
  jupytext metadata is embedded in the generated notebook. Pairing is
  whatever the project's `jupytext.toml` says (same-directory `.py`).
- **`"dev"`** (used by `dev-mode` only): embeds jupytext `formats` metadata
  in the generated notebook's front matter, with an explicit path back to
  the real `src/workflow_templates/<workflow>/<name>.py` in the repo. This is
  necessary because jupytext's directory-config mechanism
  (`[tool.jupytext.formats]` prefix-swapping) can only redirect between
  sibling folders reachable from the *same* config file — it cannot reach
  from an external project's directory tree back into the `nhm-assist` repo.
  Per-notebook embedded metadata is the only mechanism that can express an
  arbitrary cross-tree pairing target, and per jupytext's own documented
  precedence rule, individual (embedded) pairing always overrides directory
  config — so this correctly takes priority over the project's
  `jupytext.toml` default for just these files.
  Also stamps `metadata.kernelspec` to the registered dev kernel (see below).

### 4. Kernel registration

A small helper — `ensure_kernel_registered(name, display_name)`, living in
`src/assist/workspace/` alongside `bridge.py` — idempotently (checks
`jupyter kernelspec list` / installs if missing) registers a
distinctly-named `ipykernel` per pixi environment:

- `dev-mode` registers/uses a kernel named e.g. `nhm-assist-dev`, pointing at
  the `dev` environment's Python, and stamps it into every notebook it
  writes or patches.
- `setup` registers/uses an equivalent kernel (e.g. `nhm-assist`) for the
  `default` environment, for the same convenience, and stamps it into
  notebooks generated via `notebooks-create-project`/`setup`.

This works because VS Code's Jupyter extension (and JupyterLab, and
Jupyter-protocol-compliant tools generally) reads a notebook's
`metadata.kernelspec` and pre-selects/suggests that kernel on open — but only
if a kernelspec with that exact name is actually registered on the system.
Registering the kernel and stamping the metadata together is what makes the
"reminder" actually work, rather than a no-op string in the metadata.

`ipykernel` is already present transitively (via `jupyterlab`) in both
environments, so no new dependency is required.

### 5. `dev-mode` task (renamed from `dev`)

`notebooks-create-project`'s task already calls
`python -m workflow_templates.make_notebooks --workflow ... --workspace-root
... --project-name ...` directly (not through `assist.workspace.cli`).
Rather than inventing a separate entry point, `make_notebooks.py`'s CLI
(`parse_args`/`main`) gains a `--pairing-mode {local,dev}` flag (default
`local`), and `dev-mode` is that same command with `--pairing-mode dev`
added — reusing one code path instead of maintaining two:

```toml
[tool.pixi.tasks.dev-mode]
cmd = "python -m workflow_templates.make_notebooks --workflow {{ workflow }} --workspace-root {{ workspace_root }} --project-name {{ project_name }} --pairing-mode dev"
default-environment = "dev"
```

For each template file in the selected workflow:

- If the target `.ipynb` doesn't exist yet: generate it with
  `pairing_mode="dev"`.
- If it already exists: never touch its cell content. Check whether its
  pairing metadata already points at the correct repo path and its
  kernelspec is already the dev kernel; if not, patch just that metadata in
  place. Report one of: created / already dev-configured / metadata updated,
  per file.

No Jupyter Lab launch. The task's final output is a short summary (what was
created/updated/already present) plus the notebooks directory path and the
command to open it (`jupyter lab <path>`, or "open in VS Code/Kiro").

### 6. `setup`'s interactive menu

`src/assist/workspace/setup.py`'s `action_launch_jupyter` (menu step 4,
"Launch Jupyter") is replaced by an action in the same menu position that
prints the notebooks directory path and the command to open it themselves —
it no longer starts a `jupyter lab` subprocess.

### 7. Data flow

**End user:**
`setup` → `project-create` (writes `jupytext.toml`) → `model-create` /
`model-copy-example` → `notebooks-create-project` (`pairing_mode="local"`) →
menu step 4 prints instructions. Opening any notebook in the project — generated
or hand-created — pairs to a same-directory `.py` via the project's
`jupytext.toml`.

**Contributor (dogfooding):** the same `project-create` / `model-create` as
any user against their own test project, then:

```bash
pixi run -e dev dev-mode --workspace-root <ws> --project-name <proj> --workflow nhm
```

Notebooks land in the same `<project>/notebooks/<workflow>/` location a real
user would see, but pair back to `src/workflow_templates/nhm/*.py` in the
repo and open with the `nhm-assist-dev` kernel selected by default. Editing
the notebook in Jupyter and saving writes the change straight into the
repo's template source — exercising the identical end-user code path for
everything except where the paired `.py` file lives.

### 8. README updates

Rewrite the "Developing nhm-assist notebooks" section to describe: the
dogfooding model, `dev-mode`'s new name/arguments, the removal of any
repo-root notebook directory, no auto-launched Jupyter (for both `setup` and
`dev-mode`), the per-project `jupytext.toml`, and kernel auto-selection.

## Testing

- `make_notebooks.py`: unit tests for `pairing_mode="dev"` embedding correct
  `formats` metadata (a repo-relative or absolute path resolving to the real
  template file) and `pairing_mode="local"` embedding none.
- Idempotency: running `dev-mode` twice against the same project produces no
  content changes the second time, only metadata patches where needed (and
  none at all on a third run).
- `project-create`: writing `jupytext.toml` is skipped if one already exists
  at the project root (verify existing content is untouched).
- Kernel registration helper: idempotent — calling it twice does not error
  or duplicate the kernelspec.
- `setup.py`: the replaced menu action prints the expected path/command and
  does not spawn a subprocess.
