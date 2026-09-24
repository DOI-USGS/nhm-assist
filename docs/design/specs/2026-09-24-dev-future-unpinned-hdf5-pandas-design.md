# Pixi: keep the `hdf5` and `pandas` pins in `default`/`ci`, drop them in `dev-future`

**Date:** 2026-09-24
**Status:** Draft, pending review
**Branch:** off `develop`, after the re-lock commit (see Prerequisite)
**Builds on:** `docs/design/specs/2026-08-28-packaging-dependency-groups-design.md`
(the `pywatershed` and `dataretrieval` version splits, §2–§3)

## Context

Two temporary pins sit in `[tool.pixi.dependencies]`:

```toml
hdf5 = ">=1.14,<2"
pandas = ">=2.2,<3"
```

`pandas` is also capped in `[project.dependencies]` as `"pandas>=2.2,<3"`.

`[tool.pixi.dependencies]` is pixi's default feature, which every environment
composes, including `dev-future`. A feature can add constraints but cannot remove
one it inherits. So `dev-future`, the environment that exists to show what the next
major versions break, is held to the same pins as `default`. It currently resolves
pandas 2.3.3 and hdf5 1.14.6.

The `[project.dependencies]` cap reaches every environment too, through the
editable self-install (`nhm-assist = { path = ".", editable = true }` on the default
feature), so moving only the pixi-table pin would not unpin pandas.

This repo already has a pattern for this. `python`, `dataretrieval` and
`pywatershed` are constrained on the `prod` feature, which `default` and `ci`
compose and `dev-future` does not, and `dev-future` sets its own ranges. For
`pywatershed`, !47 also loosened `[project.dependencies]` to a floor
(`pywatershed>=2.0.1`) so that one per-feature cap could do the work.

## Goals

- `default` and `ci` keep `hdf5 >=1.14,<2` and `pandas >=2.2,<3`, and resolve to
  exactly the packages they resolve to today.
- `dev-future` resolves `hdf5` and `pandas` unpinned.
- The docs record where the pins live, why, and what would let each one go.

## Non-goals

- Making the code pandas 3 compatible. `dev-future` exists to surface that work,
  not to do it.
- Removing either pin from `default`/`ci`.
- Fixing the five known test failures. The GitLab CI migration spec covers them.
- Publishing to PyPI. The loosened `[project.dependencies]` is acceptable only
  because nothing is published yet; see Risks.

## Prerequisite: re-lock `develop` first

`41849b7` added `rioxarray`, `openpyxl` and `gdptools` to `pyproject.toml` without
updating `pixi.lock`. Re-locking the unchanged manifest moves `default` and `ci` by
about 90 packages per platform. That is a separate change, committed on its own
before this work (`build(pixi): re-lock to match the manifest`), so that this
spec's lock diff shows only its own effect.

## Findings from the trial solve

A throwaway solve on 2026-09-24, against the re-locked baseline, with the manifest
changes below:

- **`default` and `ci`: identical resolved packages on all four platforms.**
- **Outside `dev-future`, the lock changes in one place:** the shared editable
  `nhm-assist` entry's `requires_dist`, from `pandas>=2.2,<3` to `pandas>=2.2`.
- **`dev-future`, all four platforms:**

  | package | before | after |
  | --- | --- | --- |
  | pandas | 2.3.3 | 3.0.6 |
  | hdf5 | 1.14.6 | 1.14.6 |
  | libnetcdf / netcdf4 | 4.9.3 / 1.7.3 | 4.9.3 / 1.7.3 |
  | python | 3.13.15 | 3.13.15 |

- **Unpinning `hdf5` has no effect today.** `herbie-data → cfgrib → python-eccodes
  → eccodes` pins it. Even the newest conda-forge `eccodes` (2.48.0) is built
  against `hdf5 >=1.14.6,<1.14.7`. conda-forge does ship hdf5 2.2.0 for all four
  platforms, win-64 included, so the pin's current rationale in AGENTS.md is out of
  date. Unpinning is still worth doing: `dev-future` picks up HDF5 2.x as soon as
  `eccodes` does, with no further manifest change.
- **`pixi lock` alone leaves `dev-future` where it is,** because its locked
  versions still satisfy the loosened constraints. Re-solving it needs
  `pixi update -e dev-future`.

## Design

### 1. `pyproject.toml`

`[project.dependencies]`: floor only, as with `pywatershed`.

```toml
  "pandas>=2.2",
```

`[tool.pixi.dependencies]`: remove the `hdf5` line and its comment. Nothing in this
repo depends on `hdf5` directly; it was only there as a pin. Loosen `pandas` to its
floor, which keeps it sourced from conda-forge:

```toml
pandas = ">=2.2"
```

`[tool.pixi.feature.prod.dependencies]`: add both pins next to the existing ones.

```toml
python = ">=3.11.9,<3.12"
dataretrieval = "<1.2"
# Temporary holds; see "Temporary dependency pins" in AGENTS.md.
hdf5 = ">=1.14,<2"
pandas = ">=2.2,<3"
```

`[tool.pixi.feature.dev-future.dependencies]`: no change. Leaving the pins out is
what unpins them.

### 2. `pixi.lock`

```bash
pixi lock
pixi update -e dev-future
```

### 3. AGENTS.md, "Temporary dependency pins"

Replace the section with:

```markdown
## Temporary dependency pins

`hdf5` and `pandas` are pinned on the `prod` feature, so the pins apply to
`default` and `ci` and deliberately not to `dev-future`, which exists to show
what the next major versions break. Don't move them back to
`[tool.pixi.dependencies]`: that is the default feature, which every
environment composes, and a feature cannot remove a constraint it inherits.
`[project.dependencies]` carries only the `pandas>=2.2` floor for the same
reason, the pattern used for `pywatershed`.

- `hdf5 <2`: holds `default` and `ci` on the 1.14 series until HDF5 2.x has run
  clean in `dev-future`. Today it is redundant in practice: `eccodes` (via
  `herbie-data` → `cfgrib` → `python-eccodes`) is built only against hdf5
  1.14.6, so every environment resolves 1.14.6.

  The pin was added in !54 to fix a Windows "DLL load failed while importing
  _netCDF4" error. That diagnosis was wrong: the failure came from user
  site-packages shadowing the environment (see "User site-packages" above).
  No import failure is known to depend on this pin.
- `pandas <3`: pandas 3 changes defaults (copy-on-write, a dedicated string
  dtype) and this code has not been tested against it. Drop the pin once the
  test suite and notebooks run clean on pandas 3 in `dev-future`.

After changing either pin, re-solve `dev-future` explicitly with
`pixi update -e dev-future`: `pixi lock` keeps locked versions that still
satisfy the constraints.
```

### 4. README and CHANGELOG

- README, "Environments other than `default`": the `dev-future` bullet adds that
  it runs unpinned `pandas` and `hdf5`.
- CHANGELOG `[Unreleased]` → Changed: "`dev-future` now resolves `pandas` and `hdf5`
  unpinned; the pins stay on `default` and `ci`."

## Verification

1. **`default` and `ci` unchanged.** Compare the resolved package set of every
   (environment, platform) pair in `pixi.lock` against the lock at the branch's
   base, the re-lock commit. Every `default` and
   `ci` pair must be identical. A text diff of the lock is not enough: package
   records are shared across environments, so compare per environment.
2. **One shared-entry change.** The editable `nhm-assist` entry differs only in
   `pandas>=2.2,<3` → `pandas>=2.2`.
3. **`dev-future` resolves on all four platforms.** Record its pandas, hdf5,
   libnetcdf, netcdf4 and python versions per platform. Expected: pandas 3.x
   and hdf5 1.14.6 everywhere. If that differs, name the constraint responsible
   rather than working around it.
4. **Lock consistent:** `pixi lock --check` passes.
5. **`default` test suite unchanged:** `pixi run test` gives the same five known
   failures and no new ones.
6. **`dev-future` test run, informational:** `pixi run -e dev-future test`. Record
   the pass/fail counts in the merge request. Failures here are expected and
   do not gate the merge; they are the pandas 3 work this environment surfaces.

No new test file. A test asserting pinned versions would need editing whenever a
pin is dropped, and check 1 is the real guarantee.

## Risks and open questions

- **The published contract no longer caps pandas.** A future
  `pip install nhm-assist` could get pandas 3. That's acceptable while nothing is
  published. Before the first PyPI or conda-forge release, either the code
  supports pandas 3 or the cap goes back into `[project.dependencies]`.
- **`dev-future` drifts further from `default`.** That is its purpose, but its
  failures will now include pandas 3 ones alongside `pywatershed` 3 and
  `dataretrieval` 1.2 ones. The informational test run in check 6 is the record
  that separates them.
- **Contributors who re-lock with plain `pixi lock` won't see `dev-future` move.**
  Documented in AGENTS.md (§3).
