# CI migration to pixi, and removal of `environment.yaml`

**Date:** 2026-08-21
**Status:** Draft, pending review
**Scope:** `.github/workflows/ci.yaml`, `.github/scripts/`, `environment.yaml`. No changes to
`pyproject.toml`, `src/`, or `tests/`.

## Problem

`environment.yaml` is a second conda dependency manifest that nothing keeps in sync with
`pyproject.toml`. It is now **29 packages behind**: `geopandas`, `netcdf4`, `matplotlib`,
`xarray`, `scipy`, `rasterio`, `scikit-image`, and others are declared for pixi and absent
from it. The README already tells readers the legacy `mamba env create -f environment.yaml`
flow belongs to the `1.1.1` release and that "the `main` branch is pixi-only."

It cannot simply be deleted, because it is the only thing CI builds from:
`.github/workflows/ci.yaml` uses `mamba-org/setup-micromamba@v1` with
`environment-file: environment.yaml` across macOS, Windows, and Ubuntu.

**But that CI job is already broken, silently.** `.github/scripts/test_notebooks.py` globs
`repo_dir / "notebook_scripts"` for `*.py`. That directory does not exist. The glob returns an
empty set, `scripts_to_test` is empty, the loop body never executes, and the job exits 0. The
`test notebooks` job has been passing without testing anything.

The cause is visible in the history: `ci.yaml` was last modified 2025-08-14, a year before the
pixi restructure. It was never updated when the repository moved to `pyproject.toml` and
`src/workflow_templates/`. Notebooks now live in `notebooks/` as `.ipynb`, generated from
`src/workflow_templates/<workflow>/*.py` — a layout that postdates the script entirely.

Two further consequences of the same drift:

- Three scripts in `.github/scripts/` — `mv_cache_files_for_scheduled_tests.py`,
  `restore_cache_files_after_scheduled_tests.py`, `rm_test_output_files_from_cache.py` — are
  referenced by no workflow.
- The `tests/` suite — 70 passing tests — **runs nowhere in CI**.

## Goal

CI that builds from `pyproject.toml` via pixi, runs the test suite that exists, and contains
nothing that pretends to test something it does not. Delete `environment.yaml` once nothing
depends on it.

## Non-goals

- **Executing notebooks in CI.** Retired here rather than repaired; see Decisions.
- **Enabling the lint job.** Deferred; see Decisions.
- Any change to `pyproject.toml`, `src/`, or `tests/`.
- Publishing workflows for PyPI or conda-forge.

## Decisions

### Retire the notebook test rather than repair it

`test_notebooks.py` and the three orphaned cache scripts are deleted, and CI runs
`pixi run test` instead.

Repairing notebook execution means generating notebooks via `pixi run notebooks-create` and
executing all seven against real model data and live network services (USGS, CDS). That is
almost certainly why it rotted, and reviving it is a materially larger job with real flakiness
risk. Replacing a job that tests nothing with one that runs 70 real tests is a strict
improvement available now; notebook execution can be reintroduced deliberately later.

**Consequence to accept:** notebook execution regressions will not be caught by CI. They are
not caught today either — the job has been vacuous — so this loses no real coverage, but it
does make the gap explicit rather than hidden.

### Keep the three-OS matrix

macOS, Windows, and Ubuntu. The geospatial stack is exactly where cross-platform breakage
hides, the pixi manifest targets `osx-64`, `osx-arm64`, `linux-64`, and `win-64`, and pixi
resolves per-platform from one lockfile — so the matrix tests what users actually get.

The `python-version: ["3.11"]` matrix entry is **removed**: pixi pins the interpreter through
`pyproject.toml` (`python = ">=3.11.9,<3.14"`), so the entry is inert and misleading.

### Defer the lint job — reverses an earlier decision

The commented-out `lint` job stays commented out, with a pointer to this section.

The earlier plan was to re-enable it against the existing `pixi run lint` task. Measurement
showed that task does not pass:

| Target | Ruff errors |
| --- | --- |
| `src/assist` | 235 |
| `src/workflow_templates` | 897 |
| `tests` | 3 |
| `notebooks` | clean |

There is no `[tool.ruff]` section in `pyproject.toml`, so ruff runs with default rules over the
entire repository, including the jupytext notebook templates where `E402` (imports not at top),
`F401` (unused imports), and `F841` (unused locals) are normal and not defects.

The blocking finding is in library code: **84 of the 235 errors in `src/assist` are `F821`
undefined names** — `HTML`, `poi_df`, `v2` in `nhf/display_controls_v2.py` and elsewhere. That
is notebook-style code depending on names from the caller's namespace, living inside importable
modules. Some are probably harmless; some are probably real bugs. Triaging them, choosing a rule
set, and adding a `[tool.ruff]` config with the right excludes is a round of its own, and
landing a permanently-red CI job in the meantime helps nobody.

**Prerequisite for a future lint round:** add `[tool.ruff]` with
`extend-exclude = ["src/workflow_templates", "notebooks"]` and `force-exclude = true`, pick an
explicit `select` list, then triage what remains in `src/assist`.

### Retire `environment.yaml`, keep the historical references

The file is deleted. Two references stay:

- `README.md:15` already frames the conda flow as belonging to the `1.1.1` release. It is
  accurate as history and needs no change.
- `CHANGELOG.md` entries describing past additions to `environment.yaml` are historical record
  and must not be rewritten.

## Design

### `.github/workflows/ci.yaml`

Replace the micromamba setup with pixi and the vacuous notebook step with the test suite:

```yaml
      - name: Setup pixi
        uses: prefix-dev/setup-pixi@v0
        with:
          environment: dev
          cache: true

      - name: Run tests
        run: pixi run test
```

- `environment: dev` — the `test` task declares `default-environment = "dev"`, and that
  environment carries pytest.
- The scheduled Linux delay step is **kept**. It exists to stagger nightly runs against ORDWR
  servers, and remains relevant as long as the cron trigger exists.
- The `paths-ignore`, `concurrency`, and `schedule` blocks are unchanged.
- `defaults.run.shell: bash -el {0}` is **kept** — pixi works with it, and changing it is
  unnecessary churn.

### Files deleted

| File | Reason |
| --- | --- |
| `environment.yaml` | Second, 29-package-stale manifest; nothing builds from it after this change. |
| `.github/scripts/test_notebooks.py` | Globs a directory that does not exist; tests nothing. |
| `.github/scripts/mv_cache_files_for_scheduled_tests.py` | Referenced by no workflow. |
| `.github/scripts/restore_cache_files_after_scheduled_tests.py` | Referenced by no workflow. |
| `.github/scripts/rm_test_output_files_from_cache.py` | Referenced by no workflow. |

If `.github/scripts/` is then empty, the directory goes too.

**Orphan status verified repository-wide.** A full-tree grep (excluding `.git`, `.pixi`,
`__pycache__`, and `pixi.lock`) finds references to the three cache scripts only *inside
`.github/scripts/` itself*: `restore_cache_files_after_scheduled_tests.py` imports from
`mv_cache_files_for_scheduled_tests.py`, and `rm_test_output_files_from_cache.py` cites itself
in a docstring example. No workflow invokes any of them. They form a self-contained cluster
with no entry point. `test_notebooks.py` has exactly one caller, `ci.yaml:80`, which this
change removes. There is no GitLab CI configuration in the repository despite the canonical
remote being `code.usgs.gov`.

## Risks

**CI cannot be verified locally.** This is the round's defining constraint. `act` or a similar
runner is not a faithful substitute for three-OS GitHub-hosted runners. The change is
correct-by-inspection only until it runs.

*Mitigation:* land it on a branch and open a PR so CI executes against the change before it
reaches `main`. Do not merge on the strength of local reasoning. Verify all three matrix legs
go green, and confirm the run actually executed 70 tests rather than passing vacuously — the
precise failure this round exists to fix. Read the job log, do not trust the green check.

**`prefix-dev/setup-pixi@v0` behavior on Windows.** The action is well-established, but this
repository has never run it. Windows is the most likely leg to need adjustment.

*Mitigation:* `fail-fast: false` is already set, so one failing leg will not mask the others.

**Loss of notebook coverage is made explicit.** Retiring the notebook test does not reduce
actual coverage — there is none today — but it removes the appearance of it. Anyone reading CI
afterwards should understand notebooks are unverified. The commented-out lint block and this
spec are where that is recorded.

**Shared repository.** `code.usgs.gov/wma/hytest/nhm-assist` has other maintainers. CI changes
affect every contributor. This should go through review rather than being merged directly.

## Verification

1. `grep -rn "environment.ya\?ml"` across the repository returns only the `README.md` and
   `CHANGELOG.md` historical references.
2. `grep -rn` for each deleted script name returns nothing outside the deletions themselves.
3. `pixi run test` passes locally — 70 tests, unchanged by this round.
4. The workflow file is valid YAML and references only tasks that exist in
   `[tool.pixi.tasks]` (`test`).
5. **On the PR:** all three matrix legs green, and the log shows 70 tests collected and run.

Per the repository's contribution norms, the agent stages changes and does not commit, merge,
or push. Opening the PR is the maintainer's action.
