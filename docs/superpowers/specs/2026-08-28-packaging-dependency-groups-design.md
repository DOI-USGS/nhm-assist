# Packaging: dependency groups for default/ci/dev/dev_future environments

**Date:** 2026-08-28
**Status:** Draft, pending review

## Context

`pyproject.toml` currently defines two pixi environments: `default` (the `prod`
feature — the published runtime contract from `[project.dependencies]`, plus
conda-sourced compiled packages in `[tool.pixi.dependencies]`) and `dev` (a
single flat `[tool.pixi.feature.dev.dependencies]` block adding `pytest`,
`pytest-cov`, `ruff`, `pre-commit`, and some aspirational-but-currently-unused
packages — `gdptools`, `ipyleaflet`, `pint-xarray`, `tobler`). CI runs
`pixi run -e dev test`.

This is the next step in the "restructure, pixi, & packaging for v2
foundation" milestone, following !40 (created the `prod`/`dev` split), !42
(declared `[project.dependencies]` as the single authoritative runtime
contract), and !43 (migrated CI to pixi). Work item #44 asks us to adopt
[pywatershed 3.0.0](https://github.com/DOI-USGS/pywatershed/releases/tag/3.0.0),
which has breaking changes and requires Python 3.12 or 3.13 (today's
environment is pinned to `pywatershed>=2.0.1,<3` / Python 3.11). Rather than a
clean cutover on a branch, #44 proposes a separate dev/test environment so
contributors can run either pywatershed version from the same branch.

Separately, work item #41 flags that the
[dataretrieval-python v1.2](https://github.com/DOI-USGS/dataretrieval-python/releases/tag/v1.2.0)
release (and v1.3, since released) shipped breaking changes deferred from
earlier v1.x releases. `dataretrieval` is currently unbounded in both
`[project.dependencies]` and `[tool.pixi.dependencies]` — today's `pixi.lock`
happens to have 1.1.5 resolved, but nothing pins it there, so any future
`pixi install`/lock regeneration (including this one) could silently pull in
1.2+ for every environment with no warning. #41 asks that we test the new
release and pin to `<1.2` if it causes problems; since `dev_future` already
exists as a controlled space for testing pre-release/breaking dependency
versions (per #44), it's the natural place to test dataretrieval 1.2+ too,
alongside pywatershed 3.x.

Separately, this repo's real CI (the GitHub Actions mirror workflow) still
needs migrating to GitLab CI to give merge requests actual signal — tracked
in #47, which is deliberately on the back burner pending GitLab-CI-specific
review of the open questions in
`docs/superpowers/specs/2026-08-25-gitlab-ci-migration-design.md`. This spec
does not do that work; see Non-goals.

We do not plan to publish to PyPI/conda-forge for at least a few months,
which is relevant to one of the decisions below.

Separately, #33 tracks a recurring problem for USGS employees behind a
corporate firewall/VPN: the first reprojection in a session makes `pyproj`
fetch PROJ datum-shift grids from `cdn.proj.org`, and the firewall's SSL
inspection breaks that TLS handshake. The documented fix (conda-forge's
`proj-data` package bundled into the environment, plus `PROJ_NETWORK=OFF`)
adds ~500MB and is unnecessary for a typical end user or CI, so your own
comment on that issue proposed scoping it to the developer environment —
exactly the kind of thing this spec's environment split makes easy to do
correctly.

## Goals

1. Split today's single flat `dev` feature into PEP 735 `[dependency-groups]`
   (`test`: pytest/pytest-cov; `dev`: ruff, pre-commit, jupyter-black, and the
   existing aspirational packages), which pixi auto-converts into matching
   features. This keeps contributor tooling out of published PyPI metadata
   entirely (dependency-groups aren't extras) and lets `ci` and `dev`
   environments compose from a shared `test` feature instead of duplicating
   a dependency list.
2. Add a `ci` environment (`prod` + `test` features) as the pixi-side
   placeholder CI is meant to eventually use — this spec only defines it in
   `pyproject.toml`.
3. Add a `dev_future` environment, in its own solve-group, for testing
   pre-release/breaking dependency versions without disturbing `default`'s
   stable contract or `[project.dependencies]`'s published promise: pywatershed
   3.x (and the Python 3.12/3.13 it requires) per #44, and dataretrieval 1.2+
   per #41.
4. Keep `[project.dependencies]` as the sole authoritative published runtime
   contract — nothing here duplicates it into a second list.
5. Resolve #33 by bundling `proj-data` and disabling PROJ's network fetch in
   the `dev` feature only, so contributors behind a corporate firewall get a
   working `pyproj` automatically, without bloating `default`/`ci`.
6. Resolve #41's short-term ask by pinning `dataretrieval<1.2` on `default`/
   `ci`/`dev` (the known-good line, since nothing has tested 1.2+ yet) while
   `dev_future` tracks `dataretrieval>=1.2` for testing.

## Non-goals

- Any CI workflow changes. `.github/workflows/ci.yaml` and `.gitlab-ci.yml`
  are untouched; wiring `ci` or `dev_future` into an actual pipeline is #47's
  job (currently on the back burner) or a follow-up once it lands.
- Splitting environments per NHM/NHF/PEST workflow — a different, unrelated
  axis, and permanently out of scope: that workflow distinction is being
  unified away separately.
- Migrating `src/assist`/`src/workflow_templates` code to actually support
  pywatershed 3.0's or dataretrieval 1.2's breaking API changes. This spec
  only builds the environments to test against; the code migration is the
  rest of #44's and #41's work, respectively.
- Publishing to PyPI/conda-forge.
- Cleaning up the `dev` group's unused aspirational packages (gdptools,
  ipyleaflet, pint-xarray, tobler) — carried over as-is.

## Design

### 1. Dependency groups replace the flat `dev` feature

```toml
[dependency-groups]
test = ["pytest", "pytest-cov"]
dev = ["ruff", "pre-commit", "gdptools", "ipyleaflet", "pint-xarray", "tobler"]
```

Pixi automatically interprets each group as a same-named feature carrying
the associated `pypi-dependencies`. `jupyter-black` stays in
`[project.dependencies]` (it's already there as a runtime dep for the
generated notebooks, not dev-only tooling).

`proj-data` (issue #33) can't go in `[dependency-groups]` — it's a
conda-forge-only data package, not on PyPI — so it's added directly as a
conda dependency on the same `dev` feature, alongside the group-generated
pypi deps:

```toml
[tool.pixi.feature.dev.dependencies]
proj-data = "*"

[tool.pixi.feature.dev.activation.env]
PROJ_NETWORK = "OFF"
```

This operationalizes the fix from #33 (previously a manual per-machine
recipe) directly into the manifest: any environment composing the `dev`
feature gets the offline grid bundle and network fetches disabled
automatically on activation, with no per-contributor setup. Because `ci`
and `default` never compose `dev`, neither pays the ~500MB cost or picks up
`PROJ_NETWORK=OFF` — matching your comment on #33 that this belongs in the
developer environment only. `dev_future` composes `dev` too, so it inherits
the same fix.

### 2. pywatershed version split

`[project.dependencies]`'s `pywatershed>=2.0.1,<3` becomes `pywatershed>=2.0.1`
(no upper bound). A single shared pin can't express two mutually-exclusive
per-environment ranges — pixi's own documented pattern for testing a future
major version is to keep the package out of any block shared across those
environments and pin it only in per-feature blocks. Concretely:

```toml
[tool.pixi.dependencies]
# python and pywatershed removed from here — now feature-scoped below.
cdsapi = "*"
dask = "*"
# ...(all other shared conda deps, unchanged)

[tool.pixi.feature.prod.dependencies]
python = ">=3.11.9,<3.14"
pywatershed = ">=2.0.1,<3"

[tool.pixi.feature.dev_future.dependencies]
python = ">=3.12,<3.14"
pywatershed = ">=3,<4"
```

Only `prod` and `dev_future` declare these two packages. `ci` and `dev`
compose `prod` (see Section 3) to inherit them rather than redeclaring their
own copy — `dev_future` deliberately does **not** compose `prod`, since
composing a feature that pins `pywatershed>=2.0.1,<3` into the same
environment as `dev_future`'s `>=3,<4` pin would hand pixi two conflicting
conda pins for the same package with no way to reconcile them.

Everything else in the shared `[tool.pixi.dependencies]` block (geopandas,
xarray, scipy, etc.) stays shared across all four environments.

**Risk, accepted deliberately:** loosening `[project.dependencies]`'s bound
means a bare `pip install nhm-assist` (bypassing pixi) could resolve
pywatershed 3.x before `src/assist` supports it. This is acceptable now
because we're not publishing to PyPI/conda-forge for at least a few months —
by then #44's code migration should have resolved which version is actually
current. Re-tighten the published bound as part of whichever change makes
pywatershed 3.x the supported default.

### 3. dataretrieval version split

Same pattern as Section 2, for #41. `dataretrieval` moves out of the shared
`[tool.pixi.dependencies]` block (where it's currently unbounded) and into
per-feature pins. This is on top of Section 2's edit to the same block —
`python`, `pywatershed`, and `dataretrieval` all end up feature-scoped,
nothing else:

```toml
[tool.pixi.dependencies]
# python, pywatershed, and dataretrieval removed from here — now feature-scoped below.
cdsapi = "*"
dask = "*"
# ...(all other shared conda deps, unchanged)

[tool.pixi.feature.prod.dependencies]
dataretrieval = "<1.2"

[tool.pixi.feature.dev_future.dependencies]
dataretrieval = ">=1.2"
```

Unlike the pywatershed split, this doesn't loosen an existing bound — it adds
the first explicit pin `dataretrieval` has ever had, since today it's
unbounded everywhere and only stays on 1.1.5 because that's what's already
resolved in `pixi.lock`. Pinning `default`/`ci`/`dev` to `<1.2` now (rather
than waiting for a problem, per #41's literal wording) closes that gap: this
MR's own lock regeneration could otherwise have silently picked up 1.2 or 1.3
for every environment. `dev_future` tracks `dataretrieval>=1.2` so
contributors can test the async parallel chunker and CQL2 query features #41
calls out, and confirm compatibility before the `<1.2` cap is ever lifted.
`[project.dependencies]`'s unbounded `dataretrieval` entry is unchanged, for
the same reason as pywatershed's: not publishing for a few months yet, and
this list stays the sole authoritative contract (Goal 4).

### 4. Environment/feature composition

| Environment | Features composed | Solve-group | Python | pywatershed | dataretrieval |
|---|---|---|---|---|---|
| `default` | `prod` | `default` | `>=3.11.9,<3.14` | `>=2.0.1,<3` | `<1.2` |
| `ci` | `prod`, `test` | `default` | (same as `default`) | (same as `default`) | (same as `default`) |
| `dev` | `prod`, `test`, `dev` | `default` | (same as `default`) | (same as `default`) | (same as `default`) |
| `dev_future` | `test`, `dev`, `dev_future` | `future` | `>=3.12,<3.14` | `>=3,<4` | `>=1.2` |

```toml
[tool.pixi.environments]
default = { features = ["prod"], solve-group = "default" }
ci = { features = ["prod", "test"], solve-group = "default" }
dev = { features = ["prod", "test", "dev"], solve-group = "default" }
dev_future = { features = ["test", "dev", "dev_future"], solve-group = "future" }
```

`ci` and `dev` staying in the `default` solve-group means their resolved
versions of every shared package always match `default` exactly — no drift
between what end users get and what's tested. `dev_future` needs its own
`future` solve-group because its Python/pywatershed pins are incompatible
with the others'.

`dev_future` composes `test`+`dev` rather than duplicating tooling — same
lint/test tools, just pointed at pywatershed 3.x.

## Testing

- `pixi install` resolves all four environments without conflict — the main
  new-mechanism risk (loosened base pin + per-feature overrides + a second
  solve-group), so a clean install across all of them is the key acceptance
  check.
- `pixi run -e default test`, `-e ci test`, `-e dev test` all still pass —
  regression check that splitting the old monolithic `dev` feature into
  `prod`+`test`+`dev` composition didn't change behavior.
- `pixi run -e dev_future test` is **expected to fail** on real test
  failures today (pywatershed 3.0's breaking changes aren't migrated yet).
  Success here means the environment installs and runs, not that tests
  pass — worth stating explicitly so it isn't later mistaken for a broken
  spec.
- Inspect `pixi.lock` after solving: confirm the `default`/`future`
  solve-groups produced genuinely independent version sets for
  `python`/`pywatershed`/`dataretrieval`, with no cross-contamination —
  specifically, `default`/`ci`/`dev` resolve `dataretrieval<1.2` and
  `dev_future` resolves `dataretrieval>=1.2` (1.2.x or 1.3.x).
- In the `dev` environment, verify PROJ is offline-capable per #33's own
  recipe: `pixi run -e dev python -c "from pyproj import datadir, network;
  print(datadir.get_data_dir()); print(network.is_network_enabled())"`
  should show a data dir inside the pixi env and `network: False`. Confirm
  `default`/`ci` do **not** have `proj-data` installed (env size / package
  list check), since that's the whole point of scoping it to `dev`.
