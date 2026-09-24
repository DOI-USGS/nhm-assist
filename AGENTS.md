# AGENTS.md

Operating notes for AI coding agents working in this repository. For project
description, environment setup, and contributor/user workflows, see
[README.md](./README.md) — this file doesn't repeat that, only what's
specific to working here as an agent.

## Environment

`pixi` is the only supported dependency/environment manager (README's
"Install pixi" and "Install the environment" sections). Don't introduce
`pip`, `conda`, or `venv` workflows — install and run everything through
`pixi run <task>`. Tasks are defined in `pyproject.toml` under
`[tool.pixi.tasks.*]`; notably:

- `pixi run test` — runs the `tests/` suite (pytest).
- `pixi run lint` — runs `ruff check` + `ruff format --check`. Not currently
  a clean gate: it fails today against pre-existing code with no
  `[tool.ruff]` config yet in place. Don't treat a lint failure as caused by
  your change unless you've confirmed it's new.
- `pixi run dev-mode` / `pixi run setup` — contributor vs. end-user notebook
  workflows; see README's "Developing nhm-assist notebooks" section.

There are two environments for this repo: `default` (analysis stack, tests,
lint tooling, and `proj-data`) and `ci` (the same minus `proj-data` and the
lint tooling), plus `dev-future` on a separate solve group for the next-major
dependency track. There is no `dev` environment — `pixi run test` and
`pixi run lint` both run in `default`.

`ci` is 1.9 GB on disk against `default`'s 2.7 GB. The difference is
`proj-data` plus `ruff`, `pre-commit` and their dependencies — the `dev`
feature, which `ci` does not compose. Until 2026-09 the difference was
`proj-data` alone; see the next section for why.

`ci` also deliberately lacks `PROJ_NETWORK=OFF`, which sits on the `dev`
feature. That variable and `proj-data` together work around USGS VPN SSL
inspection breaking PROJ's datum-grid fetch from `cdn.proj.org` on developer
machines (work item #33). CI runners are not behind that, and the CI job
installs the DOI root CA anyway, so a CI job is expected to fetch grids over
the network if it ever needs them. Don't "fix" this.

## Why `pywatershed` comes from PyPI, not conda-forge

`[tool.pixi.feature.prod.pypi-dependencies]` sources `pywatershed` from PyPI
while everything else compiled comes from conda-forge. That is deliberate and
load-bearing — don't "tidy" it back into `[tool.pixi.feature.prod.dependencies]`.

conda-forge's `pywatershed 2.x` recipe declares its lint, test, doc and
optional extras as *hard run dependencies*: `ruff`, `pre-commit`,
`pytest-{env,order,xdist}`, `sphinx` and its themes, `pandoc`, `git`, `pip`,
`virtualenv`, `jupyter`, `cartopy`, `geoviews`, `holoviews`, `hvplot`,
`datashader`, `panel`. `pywatershed` is in the `prod` feature, so every
environment composing `prod` inherited all of it. The PyPI metadata for the
same version keeps them as real extras.

Measured on the swap (2026-09-22): `ci` went 475 → 412 packages and
2.4 GB → 1.9 GB on disk; `default` 3.2 GB → 2.7 GB. `ruff` and `pre-commit`
left `ci` entirely, so the `ci`/`default` split is now visible rather than
one package wide.

Two constraints this creates:

- **`numba` must stay in `[tool.pixi.dependencies]`.** It is ABI-coupled to
  `numpy` and jit-compiles during `import pywatershed`, so it has to come from
  conda-forge alongside conda `numpy`, not as a PyPI wheel. `llvmlite` follows
  it. Everything else pywatershed needs (`flopy`, `pint`, `contextily`,
  `xmltodict`, `xyzservices`, `epiweeks`) is pure Python and safe from PyPI.
- **`python` is pinned in the `prod` feature.** The 3.11 cap used to come from
  the conda recipe (`python >=3.10,<3.12`). Sourcing from PyPI removed it, so
  `python = ">=3.11.9,<3.12"` now states the policy explicitly. `requires-python`
  in `[project]` stays wider on purpose: what the package supports, not what we
  build.

`flopy` is not used by this repo — it is a hard *import-time* dependency of
`pywatershed`, whose `__init__` imports `MmrToMf6Dfw`, whose module does a
top-level `import flopy`. `import pywatershed` fails without it. Don't remove it.

conda-forge's `pywatershed 3.0.0` recipe is already clean, so when the repo
moves to pywatershed 3 (the `dev-future` track) this can go back to
conda-forge if that is preferred.

### The same problem, one layer down: `pyprms`

`pyprms` declares `sphinx` as a hard runtime dependency in its own PyPI
metadata, which pulls `sphinx`, `pydata-sphinx-theme`, `sphinx-book-theme`,
`sphinx-autodoc-typehints` and the `sphinxcontrib-*` set — 15 packages — into
every environment. `pyprms` is a direct dependency in `[project.dependencies]`
and already comes from PyPI, so re-sourcing cannot fix this one. It needs an
upstream change to `pyprms`. It is small and pure Python; noted so the next
reader doesn't go looking for a local cause.

### What was ruled out, when this was first investigated (#49)

Neither of these is the mechanism, and both are tempting:

- **Solve groups.** `default` and `ci` share `solve-group = "default"` yet
  `proj-data` is in `default` only. Solve groups constrain versions, not
  membership.
- **Dependency-group handling.** `pixi list -e ci --explicit` shows `pytest`,
  from the `test` group that `ci` composes, and does not show `ruff` or
  `pre-commit`, from the `dev` group it does not. Pixi applies the declarations
  correctly.

## User site-packages

A pixi environment is a real prefix, not a virtualenv, so its interpreter still
adds `~/.local/lib/pythonX.Y/site-packages` to `sys.path` — and puts it *ahead*
of the environment's own packages. That directory is keyed by Python minor
version, not by project, so a `pip install --user` run from any other project on
the same machine silently overrides the versions locked here. Neither `pixi
install` nor `pixi list` can see it: both read the lock file, not `sys.path`.

`PYTHONNOUSERSITE` is set in `[tool.pixi.activation.env]` to shut this off for
anything run through pixi. Notebooks are not covered by that, because Jupyter
launches a kernel straight from its `kernel.json` without pixi activation, and
this package deliberately registers no kernel — choosing one is the user's job
in their IDE. The first cell of `0_workspace_setup` checks for the shadowing
instead and names the affected packages.

When a version looks wrong, `python -c "import X; print(X.__file__)"` settles in
one line what `pixi list` structurally cannot answer.

## Temporary dependency pins

`hdf5` and `pandas` are pinned on the `prod` feature, so the pins apply to
`default` and `ci` and deliberately not to `dev-future`, which exists to show
what the next major versions break. Don't move them back to
`[tool.pixi.dependencies]`: that is the default feature, which every
environment composes, and a feature cannot remove a constraint it inherits.
`[project.dependencies]` carries only the `pandas>=2.2` floor for the same
reason, the pattern used for `pywatershed`.

- `hdf5 <2`: holds `default` and `ci` on the 1.14 series until HDF5 2.x has run
  clean in `dev-future`. Today it is redundant in practice: `eccodes`
  (required by `herbie-data` directly and through `cfgrib` →
  `python-eccodes`) is built only against hdf5 1.14.6, so every environment
  resolves 1.14.6.

  The pin was added in !54 to fix a Windows "DLL load failed while importing
  _netCDF4" error. That diagnosis was wrong: the failure came from user
  site-packages shadowing the environment (see "User site-packages" above).
  No import failure is known to depend on this pin.
- `pandas <3`: pandas 3 changes defaults (copy-on-write, a dedicated string
  dtype). On 2026-09-24 the test suite ran on pandas 3.0.6 in `dev-future`
  with no failures beyond the two `default` also has, alongside that
  environment's Python 3.13, `pywatershed` 3 and `dataretrieval` 1.3. The
  notebooks have not been run on pandas 3. Drop the pin once they run clean
  there too.

After changing either pin, re-solve `dev-future` explicitly with
`pixi update -e dev-future`: `pixi lock` keeps locked versions that still
satisfy the constraints.

## Known benign warnings

- Solving the `dev-future` environment warns that `dask` has no extra named
  `dataframe`. `gdptools` and `tobler` pull `dask-geopandas`, which asks for
  dask's `dataframe` extra; dask is satisfied from conda-forge, which carries
  no PyPI extra metadata for the resolver to check against. The extra resolves
  to `dask[array]`, `pandas` and `pyarrow`, all of which conda-forge's `dask`
  already depends on — nothing is missing. Don't pin dask to silence it.

## Editing workflow notebooks

Workflow notebooks are jupytext-paired to `.py` templates under
`src/workflow_templates/`. In dev/contributor mode a project's notebooks are
paired back to those repo templates (the pairing is recorded in each
notebook's `jupytext` metadata, e.g.
`ipynb,../../../../nhm-assist/src/workflow_templates/common//py:percent`), so
the repo `.py` is the source of truth — edit it, not the generated notebook.

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
  carry that setting; a project whose `.vscode/settings.json` is missing, or
  has `onNotebookDocumentOpen` set to false, needs the setup menu's "Repair
  editor settings for this project" action.
- **Never edit both sides between syncs.** The next sync silently keeps
  whichever file is newer and discards the other, with exit code 0 and no
  warning.
- **An agent editing a template and a human with that notebook open are two
  editors of the same content.** The human's next save silently wins and
  discards the agent's edit, exactly like the "never edit both sides" case
  above, with the agent as one of the two sides. Close the notebook before an
  agent edits its template, and reopen it afterward to pull the change in.

Avoid running `jupytext --sync` from the command line to force propagation.
The relative `../` pairing prefix can be mis-resolved by the CLI (relative to
the current directory rather than the notebook), which silently writes a bogus
nested `nhm-assist/...` tree under the notebook folder instead of updating the
repo template.

## Design docs and plans

Specs and implementation plans for substantial changes live under
`docs/design/specs/` and `docs/design/plans/`. Check there for
existing context — rationale, decisions, open questions — before starting
significant work in an area that might already have one.

## Contribution norm

Agents stage changes (`git add` / `git rm`) but do not `git commit`, merge,
push, or open a merge request. Committing and opening the MR is the
maintainer's action.

## Writing GitLab issue and MR descriptions

`code.usgs.gov` sits behind a Cloudflare WAF that inspects request bodies.
A description containing command-line-shaped strings — `python -m pytest`,
a `run -e <env>` invocation, `VAR=VALUE` assignments, registry image
references like `ghcr.io/org/image:tag` — is rejected with a Cloudflare 403
before it ever reaches GitLab. The web UI surfaces no error: the save
silently does nothing, so a long description simply appears not to stick.

This is not a Markdown problem. Headings, task lists, em dashes, and
inline code are all fine, and quick actions only trigger on a line that
*starts* with `/`.

Write commands as prose instead — "the `test` task run in the `ci`
environment" rather than the literal flags — and keep exact invocations in
the spec under `docs/design/specs/`, which arrives by git push and
isn't subject to the WAF. If a save fails, paste the description one
section at a time to find the offending paragraph. Don't try to isolate it
by probing the API with substrings: a burst of requests trips a separate
rate-limit rule that returns the same 403, which makes innocuous text look
guilty.

## CI

CI currently runs on GitHub Actions (`.github/workflows/ci.yaml`): pixi +
the `tests/` suite. This only fires on pushes to the read-only GitHub
mirror (`github.com/DOI-USGS/nhm-assist`) — GitLab, where development
actually happens, does not read `.github/workflows/*` at all, so merge
requests on `code.usgs.gov` currently get no CI signal.

A GitLab CI migration is designed but not yet implemented — see
`docs/design/specs/2026-09-14-gitlab-ci-migration-design.md` for the
current design (it supersedes the 2026-08-25 spec). Note that it also
scopes in repairing the test suite first. That repair is done: the `test`
task passes in both `default` and `ci`, with 447 passed and 10 skipped as of
2026-09-24. The skips are example models absent from a checkout, plus one
baseline-parity test whose skip condition is stale (recorded in the spec's
risks section). Don't delete or "fix"
the GitHub Actions workflow to work around this gap; the plan is to
replace it with `.gitlab-ci.yml` once that design is implemented, not to
patch around GitLab not reading it.
