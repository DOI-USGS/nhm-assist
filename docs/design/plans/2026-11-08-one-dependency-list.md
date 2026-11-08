# One dependency list for nhm-assist, before publishing to PyPI and conda-forge

**Status:** proposal and probe brief, not yet run (2026-11-08). Nothing in the manifest has changed.

## Why

nhm-assist is to be published to PyPI and conda-forge. Today its runtime dependencies are listed
twice in `pyproject.toml`:

- `[project.dependencies]` (about 28 entries), which is what a wheel, pip, uv and conda-forge's
  grayskull read;
- `[tool.pixi.dependencies]` and the `prod` feature, in conda names, so the pixi environment takes
  the compiled stack from conda-forge.

Nothing checks that the two agree. In standard scientific Python packaging, the package keeps
**one** runtime list, `[project.dependencies]`, with extras for optional runtime features. The
conda-forge feedstock keeps its own recipe in a separate repository, generated from the sdist by
grayskull and kept current by conda-forge's bot. So once nhm-assist is published,
`[project.dependencies]` is exactly what PyPI users get and what the feedstock starts from. It
must be complete and accurate, and it should hold only what the package needs at runtime.

## Proposed rules

1. Declare a package if nhm-assist's code imports it or names it as a plugin (an xarray or pandas
   `engine=`, an accessor such as `.rio`, an fsspec protocol, a file format it reads).
2. Don't declare a package just because a dependency already brings it in.
3. Keep environment-only tools (ruff, pytest, pre-commit, and editor helpers) in pixi features,
   not in `[project.dependencies]`.

## What the current manifest raises

- **Notebook tools in the runtime list.** `jupyterlab`, `jupyter-server`, `jupytext`,
  `jupyter-black`, `ipywidgets` and `ipython` are in `[project.dependencies]`. nhm-assist is used
  through notebooks, so some may be real runtime needs. The maintainers decide which stay; the
  usual pattern is a `notebooks` extra (`pip install nhm-assist[notebooks]`) rather than making
  every install pull JupyterLab.
- **Packages not on conda-forge.** `hydroeval` (pinned `==0.1`, marked unmaintained) and `pyprms`
  have no conda-forge package. A conda-forge recipe cannot depend on them, so before publishing
  there they need conda-forge packages of their own, or must become optional, or (for
  `hydroeval`) be replaced.
- **Exact pins and caps in a published package.** `hydroeval==0.1` and `plotly>=5,<6` constrain
  every downstream environment. Keep a cap only where the code needs it, with a comment naming
  that code.
- **Deliberate exceptions to state, not lose.** `pywatershed` comes from PyPI on purpose
  (AGENTS.md, "Why `pywatershed` comes from PyPI"), `numba` must stay on conda-forge, `prod`
  holds Python at 3.11, and some holds are temporary (AGENTS.md, "Temporary dependency pins").
  Any single-list layout has to keep each of these, written where a reader will find it.

## Two ways to keep one list in pixi

1. **The editable self-install, as now.** pixi installs `[project.dependencies]` through
   `nhm-assist = { path = ".", editable = true }` and satisfies each requirement from conda
   wherever a conda package of that name is already in the environment. Anything not listed on
   the conda side comes from PyPI wheels, so the compiled stack (GDAL, rasterio, netCDF, numba)
   still has to be listed in conda names. This shortens the duplicate list but doesn't remove it.
2. **A pixi-build source package with PyPI mapping.** pixi-build-python has an opt-in setting,
   `ignore-pypi-mapping = false`, which maps `[project.dependencies]` to conda run dependencies
   ([pixi-build-python docs](https://pixi.prefix.dev/latest/build/backends/pixi-build-python/)).
   With nhm-assist consuming itself as a source package, the conda side would list only
   conda-only packages and the exceptions above. pixi-build is a preview feature, so this needs
   `preview = ["pixi-build"]` and a pinned pixi version. A related probe of this setting is
   planned in another project; its findings can be reused here, but nhm-assist's exceptions
   (`pywatershed` from PyPI, `hydroeval` and `pyprms` with no conda package) need their own
   check.

## Probe questions for nhm-assist

1. With option 2, can `pywatershed` stay a PyPI package while the mapping is on, or does the
   mapping pull conda-forge's `pywatershed` (whose 2.x recipe carries the extra requirements
   AGENTS.md describes)?
2. What does the mapping do with `hydroeval` and `pyprms`: lock error, silent skip, or a PyPI
   install? A silent skip must be caught.
3. Do the `prod` feature's holds (Python 3.11, `hdf5`, `pandas<3`, `dataretrieval<1.2`) still
   apply on top of the mapped requirements?
4. Does the converted manifest solve the same conda packages as today's `pixi.lock` on every
   platform the workspace lists? List every difference.
5. Do `pixi run test` and the notebooks' headless runs still pass?

## What replaces a parity check: test what users install

A test that compares two lists can't catch a missing or wrong requirement. A CI job that installs
nhm-assist the way a PyPI user will, and runs the test suite, can:

- a GitLab CI job on code.usgs.gov, in a clean Python image with no conda or pixi;
- `pip install .` (or `uv pip install .`) from `[project.dependencies]` alone;
- `pytest tests/`.

It tests the PyPI wheel world, with GDAL bundled inside the `rasterio` and `pyogrio` wheels, not
the conda environment developers use, so it checks that the requirements resolve and import, not
that the two stacks behave identically. A matching check for conda-forge comes later, from the
feedstock's own recipe tests.

## Suggested order

1. Maintainers decide the notebook tools question and the plan for `hydroeval` and `pyprms`.
2. Prune `[project.dependencies]` by rules 1 to 3.
3. Add the pip-only CI job.
4. Probe option 2. If it works, convert. If not, use option 1 and keep the conda list to the
   compiled stack and the exceptions.
5. Prepare the PyPI release, then the conda-forge recipe (grayskull from the sdist).
