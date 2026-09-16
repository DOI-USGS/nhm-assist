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
lint tooling, and `proj-data`) and `ci` (identical but without `proj-data`),
plus `dev-future` on a separate solve group for the next-major dependency
track. There is no `dev` environment — `pixi run test` and `pixi run lint`
both run in `default`.

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

The correct workflow is just: edit and save that `.py`, and the paired
notebook updates on its own when you open/run it in Jupyter. No
`jupytext --sync` needed.

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
scopes in repairing the test suite first: `pixi run test` can't collect
today, and 5 of 446 tests fail underneath that. Don't delete or "fix"
the GitHub Actions workflow to work around this gap; the plan is to
replace it with `.gitlab-ci.yml` once that design is implemented, not to
patch around GitLab not reading it.
