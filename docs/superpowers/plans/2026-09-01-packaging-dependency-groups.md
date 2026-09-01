# Packaging Dependency Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single flat `dev` pixi feature with four purpose-built environments (`default`, `ci`, `dev`, `dev_future`) defined entirely in `pyproject.toml`, so contributor tooling lives in PEP 735 dependency groups, `default`/`ci`/`dev` stay pinned to known-good `pywatershed`/`dataretrieval` versions, `dev_future` lets contributors test pywatershed 3.x and dataretrieval 1.2+ from the same branch, and the `dev` feature auto-fixes the corporate-firewall PROJ issue (#33).

**Architecture:** One file, `pyproject.toml`, edited in five sequential passes (dependency-groups conversion, PROJ/proj-data fix, pywatershed version split, dataretrieval version split, environment table), each validated by a cheap TOML-parse check since the manifest is intentionally inconsistent between passes (e.g. `python`'s only pin briefly has no environment composing it). A final task runs the real `pixi install`/`pixi run`/lock-inspection checks once all five passes have landed.

**Tech Stack:** pixi (`pyproject.toml` `[tool.pixi.*]` tables), PEP 735 `[dependency-groups]`, Python's `tomllib` for parse validation, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-packaging-dependency-groups-design.md`

## Global Constraints

- Scope is limited to `pyproject.toml` and the resulting `pixi.lock` regeneration. No changes to `src/`, `tests/`, `.github/workflows/ci.yaml`, or `.gitlab-ci.yml` — wiring `ci`/`dev_future` into an actual pipeline is #47's job (spec Non-goals).
- Do not migrate `src/assist`/`src/workflow_templates` code for pywatershed 3.0 or dataretrieval 1.2 breaking changes — this plan only builds the environments to test against (spec Non-goals).
- Do not touch the `dev` group's unused aspirational packages (`gdptools`, `ipyleaflet`, `pint-xarray`, `tobler`) beyond moving them verbatim into `[dependency-groups]` — carried over as-is (spec Non-goals).
- `[project.dependencies]` stays the sole authoritative published runtime contract (spec Goal 4) — nothing in `[tool.pixi.*]` duplicates a version bound that isn't also reflected there, except the two deliberate exceptions the spec calls out: `pywatershed` and `dataretrieval` get *tighter* per-feature pixi pins than their loosened/unbounded `[project.dependencies]` entries (spec Design §2, §3 "Risk, accepted deliberately").
- **Per the repository's contribution norm: stage changes with `git add`, but do not `git commit`, merge, or push, and do not open a merge request.** That is the maintainer's action. Every task below ends with staging, not committing.
- `pixi run -e dev_future test` is **expected to fail** on real test failures (pywatershed 3.0's breaking changes aren't migrated yet). Success there means the environment installs and runs, not that tests pass.
- `default` never composes the `test` feature (by design, per Goal 1) — there is no test suite to run under `-e default`; only `pixi install -e default` is checked there.

---

## Task 1: Convert the flat `dev` feature into PEP 735 `[dependency-groups]`

**Files:**
- Modify: `pyproject.toml` (insert a `[dependency-groups]` table; replace `[tool.pixi.feature.dev.dependencies]`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: PEP 735 groups `test` (pytest, pytest-cov) and `dev` (ruff, pre-commit, gdptools, ipyleaflet, pint-xarray, tobler), which pixi auto-converts into same-named features `test` and `dev`. Task 5 composes these feature names into `ci`/`dev`/`dev_future`.

- [ ] **Step 1: Insert the `[dependency-groups]` table**

In `pyproject.toml`, right after the `[project.urls]` block:

```toml
[project.urls]
Homepage = "https://code.usgs.gov/wma/hytest/nhm-assist"
```

insert a blank line then:

```toml
[dependency-groups]
test = ["pytest", "pytest-cov"]
dev = ["ruff", "pre-commit", "gdptools", "ipyleaflet", "pint-xarray", "tobler"]
```

so the result reads:

```toml
[project.urls]
Homepage = "https://code.usgs.gov/wma/hytest/nhm-assist"

[dependency-groups]
test = ["pytest", "pytest-cov"]
dev = ["ruff", "pre-commit", "gdptools", "ipyleaflet", "pint-xarray", "tobler"]

[tool.hatch.version]
```

- [ ] **Step 2: Remove the now-redundant flat `dev` feature dependency list**

Replace:

```toml
[tool.pixi.feature.dev.dependencies]
pre-commit = "*"
pytest = "*"
pytest-cov = "*"
ruff = "*"
# unused in code but perhaps aspirational for future work?
gdptools = "*"
ipyleaflet = "*"
pint-xarray = "*"
tobler = "*"

[tool.pixi.feature.dev.pypi-dependencies]
nhm-assist = { path = ".", editable = true }
```

with just:

```toml
[tool.pixi.feature.dev.pypi-dependencies]
nhm-assist = { path = ".", editable = true }
```

(The `[tool.pixi.feature.dev.dependencies]` table is intentionally gone for now — Task 2 reintroduces it with `proj-data` in place of the packages that moved into `[dependency-groups]`.)

- [ ] **Step 3: Validate TOML syntax**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('VALID')"`
Expected: `VALID` printed, no exception.

- [ ] **Step 4: Confirm the moved packages only exist in one place**

Run: `grep -n "gdptools\|ipyleaflet\|pint-xarray\|tobler\|pytest-cov\|^pytest \|pre-commit" pyproject.toml`
Expected: every one of these names appears exactly once, inside the new `[dependency-groups]` table (lines from Step 1) — not also under `[tool.pixi.feature.dev.dependencies]` (which no longer exists after Step 2).

- [ ] **Step 5: Stage the change (do not commit)**

```bash
git add pyproject.toml
git status
```

Expected: `pyproject.toml` shows as staged (`modified:` under "Changes to be committed"). No commit is made.

---

## Task 2: Resolve #33 — add `proj-data` + `PROJ_NETWORK=OFF` to the `dev` feature

**Files:**
- Modify: `pyproject.toml` (reintroduce `[tool.pixi.feature.dev.dependencies]` with `proj-data`; add `[tool.pixi.feature.dev.activation.env]`)

**Interfaces:**
- Consumes: Task 1's `[tool.pixi.feature.dev.pypi-dependencies]` block (this task inserts directly above it).
- Produces: `proj-data` and `PROJ_NETWORK=OFF` on the `dev` feature — inherited by any environment that composes `dev` (only the `dev` and `dev_future` environments, per the composition table Task 5 builds; `default`/`ci` never see it).

- [ ] **Step 1: Add the `proj-data` dependency and activation env var**

Replace:

```toml
[tool.pixi.feature.dev.pypi-dependencies]
nhm-assist = { path = ".", editable = true }
```

with:

```toml
[tool.pixi.feature.dev.dependencies]
proj-data = "*"

[tool.pixi.feature.dev.activation.env]
PROJ_NETWORK = "OFF"

[tool.pixi.feature.dev.pypi-dependencies]
nhm-assist = { path = ".", editable = true }
```

- [ ] **Step 2: Validate TOML syntax**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('VALID')"`
Expected: `VALID` printed, no exception.

- [ ] **Step 3: Confirm the new tables landed once each**

Run: `grep -n "proj-data\|PROJ_NETWORK" pyproject.toml`
Expected: two lines — `proj-data = "*"` under `[tool.pixi.feature.dev.dependencies]`, and `PROJ_NETWORK = "OFF"` under `[tool.pixi.feature.dev.activation.env]`.

- [ ] **Step 4: Stage the change (do not commit)**

```bash
git add pyproject.toml
git status
```

Expected: `pyproject.toml` still shows as staged/modified. No commit is made.

---

## Task 3: pywatershed version split — per-feature pins on `prod` and `dev_future`

**Files:**
- Modify: `pyproject.toml` (loosen `[project.dependencies]`'s `pywatershed` bound; remove `python`/`pywatershed` from the shared `[tool.pixi.dependencies]` block; add `[tool.pixi.feature.prod.dependencies]` and `[tool.pixi.feature.dev_future.dependencies]`)

**Interfaces:**
- Consumes: nothing from other tasks (independent of Tasks 1-2's `dev`-feature edits).
- Produces: `[tool.pixi.feature.prod.dependencies]` and `[tool.pixi.feature.dev_future.dependencies]` tables that Task 4 adds `dataretrieval` lines to, and that Task 5's `[tool.pixi.environments]` composes.

- [ ] **Step 1: Loosen the published `pywatershed` bound**

In `[project.dependencies]`, change:

```toml
  "pywatershed>=2.0.1,<3",
```

to:

```toml
  "pywatershed>=2.0.1",
```

- [ ] **Step 2: Remove `python` and `pywatershed` from the shared conda block**

Replace:

```toml
[tool.pixi.dependencies]
python = ">=3.11.9,<3.14"
cdsapi = "*"
dask = "*"
dataretrieval = "*"
distributed = "*"
fiona = "*"
geopandas = "*"
herbie-data = "*"
matplotlib = "*"
netcdf4 = "*"
numpy = "*"
pandas = ">=2.2,<3"
pyarrow = "*"
rasterio = "*"
rasterstats = "*"
pydot = "*"
pyemu = "*"
pyogrio = "*"
pywatershed = ">=2.0.1,<3"
pyyaml = "*"
scikit-image = "*"
scipy = "*"
shapely = "*"
xarray = "*"
```

with:

```toml
[tool.pixi.dependencies]
cdsapi = "*"
dask = "*"
dataretrieval = "*"
distributed = "*"
fiona = "*"
geopandas = "*"
herbie-data = "*"
matplotlib = "*"
netcdf4 = "*"
numpy = "*"
pandas = ">=2.2,<3"
pyarrow = "*"
rasterio = "*"
rasterstats = "*"
pydot = "*"
pyemu = "*"
pyogrio = "*"
pyyaml = "*"
scikit-image = "*"
scipy = "*"
shapely = "*"
xarray = "*"
```

(`dataretrieval` stays here for now — Task 4 removes it in its own pass.)

- [ ] **Step 3: Add the `prod` feature's `python`/`pywatershed` pins**

Replace:

```toml
[tool.pixi.feature.prod.pypi-dependencies]
nhm-assist = { path = ".", editable = true }
```

with:

```toml
[tool.pixi.feature.prod.dependencies]
python = ">=3.11.9,<3.14"
pywatershed = ">=2.0.1,<3"

[tool.pixi.feature.prod.pypi-dependencies]
nhm-assist = { path = ".", editable = true }
```

- [ ] **Step 4: Add the `dev_future` feature's `python`/`pywatershed` pins**

Directly after the `[tool.pixi.feature.dev.pypi-dependencies]` block (added in Task 1/2), insert:

```toml
[tool.pixi.feature.dev_future.dependencies]
python = ">=3.12,<3.14"
pywatershed = ">=3,<4"
```

so the tail of the feature tables reads:

```toml
[tool.pixi.feature.dev.pypi-dependencies]
nhm-assist = { path = ".", editable = true }

[tool.pixi.feature.dev_future.dependencies]
python = ">=3.12,<3.14"
pywatershed = ">=3,<4"
```

- [ ] **Step 5: Validate TOML syntax**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('VALID')"`
Expected: `VALID` printed, no exception.

- [ ] **Step 6: Confirm `python` and `pywatershed` are feature-scoped, not shared**

Run: `grep -n "^python \|^pywatershed " pyproject.toml`
Expected: no output (neither name appears unindented/top-level in `[tool.pixi.dependencies]` anymore).

Run: `grep -n "pywatershed" pyproject.toml`
Expected: four hits — `[project.dependencies]`'s `"pywatershed>=2.0.1"`, `[tool.pixi.feature.prod.dependencies]`'s `pywatershed = ">=2.0.1,<3"`, `[tool.pixi.feature.dev_future.dependencies]`'s `pywatershed = ">=3,<4"`, and the version cited in the block comment near the top of the file (`"...using pywatershed."` in the `description` field — leave that untouched, it's prose).

- [ ] **Step 7: Stage the change (do not commit)**

```bash
git add pyproject.toml
git status
```

Expected: `pyproject.toml` still shows as staged/modified. No commit is made.

---

## Task 4: dataretrieval version split — per-feature pins on `prod` and `dev_future`

**Files:**
- Modify: `pyproject.toml` (remove `dataretrieval` from the shared `[tool.pixi.dependencies]` block; add pins to `[tool.pixi.feature.prod.dependencies]` and `[tool.pixi.feature.dev_future.dependencies]`)

**Interfaces:**
- Consumes: Task 3's `[tool.pixi.feature.prod.dependencies]` and `[tool.pixi.feature.dev_future.dependencies]` tables (this task adds one line to each).
- Produces: `dataretrieval<1.2` on `prod` (inherited by `default`/`ci`/`dev` once Task 5 composes it), `dataretrieval>=1.2` on `dev_future`.

- [ ] **Step 1: Remove `dataretrieval` from the shared conda block**

Replace:

```toml
[tool.pixi.dependencies]
cdsapi = "*"
dask = "*"
dataretrieval = "*"
distributed = "*"
```

with:

```toml
[tool.pixi.dependencies]
cdsapi = "*"
dask = "*"
distributed = "*"
```

- [ ] **Step 2: Pin `prod` to the known-good line**

Replace:

```toml
[tool.pixi.feature.prod.dependencies]
python = ">=3.11.9,<3.14"
pywatershed = ">=2.0.1,<3"
```

with:

```toml
[tool.pixi.feature.prod.dependencies]
python = ">=3.11.9,<3.14"
pywatershed = ">=2.0.1,<3"
dataretrieval = "<1.2"
```

- [ ] **Step 3: Pin `dev_future` to the testing line**

Replace:

```toml
[tool.pixi.feature.dev_future.dependencies]
python = ">=3.12,<3.14"
pywatershed = ">=3,<4"
```

with:

```toml
[tool.pixi.feature.dev_future.dependencies]
python = ">=3.12,<3.14"
pywatershed = ">=3,<4"
dataretrieval = ">=1.2"
```

- [ ] **Step 4: Validate TOML syntax**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('VALID')"`
Expected: `VALID` printed, no exception.

- [ ] **Step 5: Confirm `dataretrieval` is feature-scoped, not shared, and appears with the right bounds in each spot**

Run: `grep -n "dataretrieval" pyproject.toml`
Expected: three hits — `[project.dependencies]`'s unbounded `"dataretrieval"`, `[tool.pixi.feature.prod.dependencies]`'s `dataretrieval = "<1.2"`, and `[tool.pixi.feature.dev_future.dependencies]`'s `dataretrieval = ">=1.2"`. None under the shared `[tool.pixi.dependencies]` block.

- [ ] **Step 6: Stage the change (do not commit)**

```bash
git add pyproject.toml
git status
```

Expected: `pyproject.toml` still shows as staged/modified. No commit is made.

---

## Task 5: Wire up `ci` and `dev_future` environments; recompose `dev`

**Files:**
- Modify: `pyproject.toml` (rewrite `[tool.pixi.environments]`)

**Interfaces:**
- Consumes: the `test`/`dev` features from Task 1, the `dev`-feature PROJ fix from Task 2, and the `prod`/`dev_future` feature dependency tables from Tasks 3-4.
- Produces: the four environments (`default`, `ci`, `dev`, `dev_future`) that Task 6 installs and tests.

- [ ] **Step 1: Rewrite the environments table**

Replace:

```toml
[tool.pixi.environments]
default = { features = ["prod"], solve-group = "default" }
dev = { features = ["dev"], solve-group = "default" }
```

with:

```toml
[tool.pixi.environments]
default = { features = ["prod"], solve-group = "default" }
ci = { features = ["prod", "test"], solve-group = "default" }
dev = { features = ["prod", "test", "dev"], solve-group = "default" }
dev_future = { features = ["test", "dev", "dev_future"], solve-group = "future" }
```

- [ ] **Step 2: Validate TOML syntax**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('VALID')"`
Expected: `VALID` printed, no exception.

- [ ] **Step 3: Confirm all four environments and their solve-groups are present**

Run: `python -c "
import tomllib
d = tomllib.load(open('pyproject.toml', 'rb'))
envs = d['tool']['pixi']['environments']
for name in ('default', 'ci', 'dev', 'dev_future'):
    print(name, envs[name])
"`

Expected:
```
default {'features': ['prod'], 'solve-group': 'default'}
ci {'features': ['prod', 'test'], 'solve-group': 'default'}
dev {'features': ['prod', 'test', 'dev'], 'solve-group': 'default'}
dev_future {'features': ['test', 'dev', 'dev_future'], 'solve-group': 'future'}
```

- [ ] **Step 4: Stage the change (do not commit)**

```bash
git add pyproject.toml
git status
```

Expected: `pyproject.toml` still shows as staged/modified. No commit is made.

---

## Task 6: Full verification pass

**Files:**
- Modify: `pixi.lock` (regenerated by `pixi install`; not hand-edited)

**Interfaces:**
- Consumes: the fully-edited `pyproject.toml` from Tasks 1-5.
- Produces: a pass/fail signal for whether this branch is ready to hand to a maintainer to open a merge request (per spec Testing section).

- [ ] **Step 1: Resolve all four environments**

```bash
pixi install
```

Expected: exits 0, `pixi.lock` is rewritten, no dependency-conflict errors. This is the main new-mechanism risk (loosened base pin + per-feature overrides + a second solve-group), so a clean install across all four environments is the key acceptance check (spec Testing item 1).

- [ ] **Step 2: Confirm `default` installs but has no test tooling to run**

```bash
pixi install -e default
```

Expected: exits 0. (No `pixi run -e default test` check — `default` never composes `test`, by design.)

- [ ] **Step 3: Run the test suite under `ci` and `dev`**

```bash
pixi run -e ci test
pixi run -e dev test
```

Expected: both pass, same test count as before this branch (no test-suite changes in this plan) — regression check that splitting the old monolithic `dev` feature into `prod`+`test`+`dev` composition didn't change behavior (spec Testing item 2, as corrected).

- [ ] **Step 4: Run the test suite under `dev_future` — expected to fail on real test failures**

```bash
pixi run -e dev_future test
```

Expected: the environment installs and the command runs (pytest executes), but individual tests are expected to fail because pywatershed 3.0's breaking changes aren't migrated in `src/assist`/`src/workflow_templates` yet (spec Non-goals; spec Testing item 3). Success here means "ran", not "passed" — do not treat test failures here as a plan defect.

- [ ] **Step 5: Inspect `pixi.lock` for solve-group independence and version pins**

```bash
python -c "
import yaml
lock = yaml.safe_load(open('pixi.lock'))
envs = lock['environments']
for name in ('default', 'ci', 'dev', 'dev_future'):
    packages = envs[name]['packages']
    print(name, list(packages.keys())[:1] if isinstance(packages, dict) else type(packages))
"
grep -n "dataretrieval-1\." pixi.lock | sort -u
grep -n "pywatershed-" pixi.lock | sort -u
grep -n "python-3\." pixi.lock | sort -u
```

Expected: `default`/`ci`/`dev` (all in the `default` solve-group) resolve the same `python` (3.11.x-3.13.x range per the `prod` pin), the same `pywatershed` (2.x), and the same `dataretrieval` (< 1.2, e.g. 1.1.x); `dev_future` (the `future` solve-group) resolves its own independent `python` (3.12.x or 3.13.x), `pywatershed` (3.x), and `dataretrieval` (>= 1.2, i.e. 1.2.x or 1.3.x). No cross-contamination between the two solve-groups (spec Testing item 4, extended to cover `dataretrieval`).

- [ ] **Step 6: Verify the PROJ offline fix in the `dev` environment**

```bash
pixi run -e dev python -c "from pyproj import datadir, network; print(datadir.get_data_dir()); print(network.is_network_enabled())"
```

Expected: prints a data directory path inside the pixi `dev` environment (not a user cache dir outside it), and `False` for network-enabled (spec Testing item 5).

- [ ] **Step 7: Confirm `default`/`ci` do NOT carry `proj-data`**

```bash
pixi list -e default | grep -i proj-data
pixi list -e ci | grep -i proj-data
```

Expected: no output from either command — `proj-data` (~500MB) is scoped to `dev`/`dev_future` only, never reaching `default`/`ci` (spec Testing item 5, the "whole point of scoping it to `dev`" check).

- [ ] **Step 8: Review the full staged diff**

```bash
git status
git add pixi.lock
git diff --staged -- pyproject.toml
git status
```

Expected: `pyproject.toml` and `pixi.lock` both staged as modified; no other files touched; nothing committed.

- [ ] **Step 9: Leave the branch for the maintainer**

No further action — do not commit, merge, push, or open a merge request. Report to the user that the branch has staged, uncommitted changes (`pyproject.toml`, `pixi.lock`) ready for their review and commit.

---

## Self-Review Notes

- **Spec coverage:** Goal 1 (dependency-groups) → Task 1. Goal 2 (`ci` environment) → Task 5. Goal 3 (`dev_future` for both #44 and #41) → Tasks 3, 4, 5. Goal 4 (`[project.dependencies]` stays authoritative) → enforced as a Global Constraint, checked in Tasks 3/4 Step 5-ish greps confirming no duplicate unbounded lists were introduced. Goal 5 (#33 PROJ fix) → Task 2, verified in Task 6 Steps 6-7. Goal 6 (`dataretrieval<1.2` default/ci/dev vs. `>=1.2` dev_future) → Task 4, verified in Task 6 Step 5. Design §1 (dependency groups + proj-data) → Tasks 1-2. Design §2 (pywatershed split) → Task 3. Design §3 (dataretrieval split) → Task 4. Design §4 (environment/feature composition table) → Task 5. Every Testing bullet (as corrected during planning — see below) → Task 6.
- **Spec defect caught during planning:** the spec's Testing section originally listed `pixi run -e default test` as expected to pass, but `default` only composes `prod` (never `test`), so pytest isn't installed there — that check cannot succeed as written. Fixed inline in the spec (replaced with a `pixi install -e default` check) and reflected in Task 6 Step 2/3 and the Global Constraints note. This was a pre-existing spec bug, not introduced by the #41 revision.
- **No placeholders:** every step shows the literal before/after TOML, the literal shell command, or the literal expected output — nothing says "add appropriate handling" or defers detail.
- **Consistency check:** feature/table names match exactly across tasks — `prod`/`dev`/`test`/`dev_future` feature names in Task 5's environment composition match the `[tool.pixi.feature.*]` table names introduced in Tasks 1-4; the `dataretrieval`/`pywatershed`/`python` version bounds in Task 6's expected lock output match the exact strings written in Tasks 3-4.
