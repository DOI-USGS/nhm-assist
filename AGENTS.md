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
- `pixi run dev` / `pixi run setup` — contributor vs. end-user notebook
  workflows; see README's "Developing nhm-assist notebooks" section.

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
`docs/superpowers/specs/` and `docs/superpowers/plans/`. Check there for
existing context — rationale, decisions, open questions — before starting
significant work in an area that might already have one.

## Contribution norm

Agents stage changes (`git add` / `git rm`) but do not `git commit`, merge,
push, or open a merge request. Committing and opening the MR is the
maintainer's action.

## CI

CI currently runs on GitHub Actions (`.github/workflows/ci.yaml`): pixi +
the `tests/` suite. This only fires on pushes to the read-only GitHub
mirror (`github.com/DOI-USGS/nhm-assist`) — GitLab, where development
actually happens, does not read `.github/workflows/*` at all, so merge
requests on `code.usgs.gov` currently get no CI signal.

A GitLab CI migration is designed but not yet implemented — see
`docs/superpowers/specs/2026-08-25-gitlab-ci-migration-design.md` for the
design and its open questions. Don't delete or "fix" the GitHub Actions
workflow to work around this gap; the plan is to replace it with
`.gitlab-ci.yml` once that design is implemented, not to patch around GitLab
not reading it.
