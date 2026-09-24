# Dev-Future Unpinned HDF5 and pandas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the `hdf5 <2` and `pandas <3` pins on `default` and `ci`, and let `dev-future` resolve both unpinned.

**Architecture:** Move both pins from pixi's default feature (`[tool.pixi.dependencies]`), which every environment inherits, to the `prod` feature, which `default` and `ci` compose and `dev-future` does not. Loosen `[project.dependencies]` to a `pandas>=2.2` floor so the editable self-install stops re-imposing the cap. This is the pattern !47 used for `pywatershed`. Then re-lock, re-solve `dev-future`, verify per environment that nothing else moved, and document where the pins live.

**Tech Stack:** pixi 0.76.0, `pyproject.toml` manifest, `pixi.lock` v7, pytest.

**Spec:** `docs/design/specs/2026-09-24-dev-future-unpinned-hdf5-pandas-design.md`

## Global Constraints

- Agents stage changes with `git add` but never `git commit`, merge, push, or open a merge request. The commit steps below are for the maintainer. **Stop after each task** for review and commit before starting the next.
- Use pixi only (`pixi run`, `pixi lock`, `pixi update`). No `pip`, `conda`, or `venv`.
- Branch `feature/dev-future-unpin-pins`, based on `develop` at `6bc6baf` (`build(pixi): re-lock to match the manifest; document how to change deps`). That commit's `pixi.lock` is the verification baseline.
- `default` and `ci` must resolve to **identical** package sets on all four platforms (`linux-64`, `osx-64`, `osx-arm64`, `win-64`) before and after.
- The only non-`dev-future` change allowed in `pixi.lock` is the editable `nhm-assist` entry's `requires_dist`, from `pandas>=2.2,<3` to `pandas>=2.2`.
- Pins, exactly: `hdf5 = ">=1.14,<2"` and `pandas = ">=2.2,<3"` on `[tool.pixi.feature.prod.dependencies]`; `pandas = ">=2.2"` in `[tool.pixi.dependencies]`; `"pandas>=2.2"` in `[project.dependencies]`; no `hdf5` entry anywhere else.
- `dev-future` gets no new entries in `[tool.pixi.feature.dev-future.dependencies]`.
- No new test file (spec, Verification).
- Baseline test result in `default`: 5 known failures (see AGENTS.md, CI). The failure set must not grow.

## Review Focus

- **Upstream drift in `default`/`ci`.** conda-forge publishes new builds daily, and pixi only re-solves an environment whose inputs changed. If moving the pins makes pixi treat the `default` solve group as changed, `default`/`ci` could pick up unrelated new builds. Task 1, Step 5 catches this per environment; if it fires, stop and report rather than accept.
- **Plain `pixi update` updates everything.** Always pass `-e dev-future`. Task 1, Step 4 uses the scoped form only.
- **`pixi lock` alone leaves `dev-future` unchanged.** Its old versions still satisfy the loosened constraints. Task 1, Step 6 asserts pandas actually moved to 3.x.
- **A pin left behind in the default table.** A leftover `hdf5` or capped `pandas` in `[tool.pixi.dependencies]` silently re-pins `dev-future`. Task 1, Step 2 checks the manifest text.
- **Lock/manifest mismatch at commit time**, which is the failure the previous commit fixed. Task 1, Step 7 runs `pixi lock --check`.

---

### Task 1: Move the pins to `prod`, re-lock, and verify `default`/`ci` are unchanged

**Files:**
- Modify: `pyproject.toml` (`[project.dependencies]` ~line 72; `[tool.pixi.dependencies]` ~lines 157–166; `[tool.pixi.feature.prod.dependencies]` ~lines 189–193)
- Modify: `pixi.lock` (generated)
- Scratch, not committed: `$TMPDIR/pixi.lock.base`, `$TMPDIR/lockdiff.py`

**Interfaces:**
- Consumes: baseline lock at `6bc6baf`.
- Produces: the manifest and lock that Tasks 2 and 3 describe and test. Task 3 re-runs `$TMPDIR/lockdiff.py` for the MR record.

- [ ] **Step 1: Save the baseline lock and the comparison script**

```bash
git show 6bc6baf:pixi.lock > "$TMPDIR/pixi.lock.base"
```

Write `$TMPDIR/lockdiff.py`:

```python
"""Compare resolved packages per (environment, platform) between two pixi.lock files.

Usage: python lockdiff.py BASE NEW [package ...]
Exit status 1 if any default or ci environment changed.
"""
import re
import sys

import yaml


def load(path):
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    envs = {
        (env, platform): {next(iter(p.values())) for p in pkgs}
        for env, spec in doc["environments"].items()
        for platform, pkgs in spec["packages"].items()
    }
    editable = next(p for p in doc["packages"] if p.get("pypi") == "./")
    return envs, set(editable.get("requires_dist", []))


def name_version(url):
    tail = url.rstrip("/").split("/")[-1]
    m = re.match(r"(.+?)-(\d[^-]*)-[^-]+\.(conda|tar\.bz2)$", tail)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"([A-Za-z0-9_.]+?)-(\d[^-]*?)(-|\.tar\.gz|\.zip)", tail)
    if m:
        return m.group(1).lower().replace("_", "-"), m.group(2)
    return tail, ""


base, base_req = load(sys.argv[1])
new, new_req = load(sys.argv[2])
watch = sys.argv[3:]

changed_protected = False
for key in sorted(set(base) | set(new)):
    b, n = base.get(key, set()), new.get(key, set())
    status = "unchanged" if b == n else f"-{len(b - n)} +{len(n - b)}"
    print(f"{key[0]:>10} {key[1]:<10} {status}")
    if b != n and key[0] in ("default", "ci"):
        changed_protected = True

print("editable requires_dist:", "-", sorted(base_req - new_req), "+", sorted(new_req - base_req))

for key in sorted(k for k in new if k[0] == "dev-future"):
    found = dict(name_version(u) for u in new[key])
    print(key[1], {w: found.get(w, "-") for w in watch})

sys.exit(1 if changed_protected else 0)
```

- [ ] **Step 2: Edit `pyproject.toml`**

In `[project.dependencies]`, replace `"pandas>=2.2,<3",` with:

```toml
  "pandas>=2.2",
```

In `[tool.pixi.dependencies]`, delete these two lines:

```toml
# Temporary hold; see "Temporary dependency pins" in AGENTS.md.
hdf5 = ">=1.14,<2"
```

and replace `pandas = ">=2.2,<3"` with:

```toml
pandas = ">=2.2"
```

In `[tool.pixi.feature.prod.dependencies]`, after `dataretrieval = "<1.2"`, add:

```toml
# Temporary holds; see "Temporary dependency pins" in AGENTS.md.
hdf5 = ">=1.14,<2"
pandas = ">=2.2,<3"
```

Check that no pin was left behind:

Run: `grep -n 'hdf5\|pandas' pyproject.toml`
Expected: exactly four lines. They are `"pandas>=2.2",` in `[project.dependencies]`, `pandas = ">=2.2"` in `[tool.pixi.dependencies]`, and `hdf5 = ">=1.14,<2"` and `pandas = ">=2.2,<3"` under `[tool.pixi.feature.prod.dependencies]`.

- [ ] **Step 3: Re-lock**

Run: `pixi lock`
Expected: exits 0. `default`/`ci` unchanged, `dev-future` changes little or not at all. That's expected, because its locked versions still satisfy the constraints.

- [ ] **Step 4: Re-solve `dev-future` only**

Run: `pixi update -e dev-future`
Expected: exits 0 and lists `pandas 2.3.3 -> 3.x` among the changes. Never run `pixi update` without `-e dev-future` here.

- [ ] **Step 5: Verify `default` and `ci` are unchanged**

Run: `.pixi/envs/default/bin/python "$TMPDIR/lockdiff.py" "$TMPDIR/pixi.lock.base" pixi.lock pandas hdf5 libnetcdf netcdf4 python`
(Windows: `.pixi\envs\default\python.exe`.)

Expected:
- Exit status 0.
- All eight `default` and `ci` rows print `unchanged`. All four `dev-future` rows show changes.
- `editable requires_dist: - ['pandas>=2.2,<3'] + ['pandas>=2.2']`.

If any `default` or ci row changed (exit 1), stop. Don't accept it; report the changed packages to the maintainer. That's the upstream-drift case in Review Focus.

- [ ] **Step 6: Verify what `dev-future` resolved**

From the same output, the four `dev-future` platform lines. Expected on every platform: `pandas` 3.x, `hdf5` 1.14.6, and `python` 3.13.x. The trial on 2026-09-24 gave pandas 3.0.6, hdf5 1.14.6, libnetcdf 4.9.3, netcdf4 1.7.3 and python 3.13.15.

If pandas is still 2.x, or HDF5 differs across platforms, find the constraint responsible. Search `pixi.lock` for packages in `dev-future` whose `depends` pin `pandas` or `hdf5`, report it, and stop. Don't add a workaround.

- [ ] **Step 7: Check the lock matches the manifest**

Run: `pixi lock --check`
Expected: `✔ Lock-file was already up-to-date`

- [ ] **Step 8: Run the `default` test suite**

Run: `pixi run test`
Expected: the same 5 known failures as before (`test_all_template_call_sites` ×2, `test_nothing_in_the_repo_imports_a_retired_path`, `test_the_nhm_package_is_gone`, `test_new_loader_reads_the_repos_live_config`) and no others.

- [ ] **Step 9: Stage, then stop for review**

```bash
git add pyproject.toml pixi.lock
```

Maintainer commits:

```text
build(pixi): move hdf5 and pandas pins to prod so dev-future runs unpinned

The pins sat on the default feature, which every environment composes,
so dev-future could not drop them. Move both to the prod feature, which
default and ci compose, and loosen [project.dependencies] to a
pandas>=2.2 floor, the pattern !47 used for pywatershed.

default and ci resolve to identical packages on all four platforms.
dev-future moves to pandas 3.x; hdf5 stays at 1.14.6 because eccodes
is built only against 1.14.6.
```

---

### Task 2: Document where the pins live and why

**Files:**
- Modify: `AGENTS.md` (the "Temporary dependency pins" section, ~lines 123–133)
- Modify: `README.md` (the `dev-future` bullet under "Environments other than `default`", ~line 276)
- Modify: `CHANGELOG.md` (`[Unreleased]` → `### Changed`)

**Interfaces:**
- Consumes: Task 1's manifest layout and its Step 6 result (pandas 3.x, hdf5 1.14.6).
- Produces: nothing code-facing.

- [ ] **Step 1: Replace the AGENTS.md section**

Replace everything from `## Temporary dependency pins` up to, but not including, `## Known benign warnings` with:

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

- [ ] **Step 2: Update the README `dev-future` bullet**

Replace:

```markdown
- **`dev-future`** — a separate solve group tracking the next major versions of `pywatershed` and `dataretrieval`. Expect real test failures there; it exists to see what is coming.
```

with:

```markdown
- **`dev-future`** — a separate solve group tracking the next major versions of `pywatershed` and `dataretrieval`, with `pandas` and `hdf5` unpinned. Expect real test failures there; it exists to see what is coming.
```

- [ ] **Step 3: Add the CHANGELOG entry**

In `CHANGELOG.md`, under `## [Unreleased]` → `### Changed`, after the `**Environments (!47, !54):**` bullet, add:

```markdown
- **`dev-future` resolves `pandas` and `hdf5` unpinned;** the pins stay on `default` and `ci`.
```

- [ ] **Step 4: Check the edits**

Run: `grep -n 'Temporary dependency pins' -A3 AGENTS.md; grep -n 'unpinned' README.md CHANGELOG.md`
Expected: the new AGENTS.md opening paragraph, one README line and one CHANGELOG line.

Run: `grep -n 'withdrew\|all four platforms' AGENTS.md`
Expected: no match. The out-of-date win-64 rationale is gone.

- [ ] **Step 5: Stage, then stop for review**

```bash
git add AGENTS.md README.md CHANGELOG.md
```

Maintainer commits:

```text
docs: record that the hdf5 and pandas pins live on prod

AGENTS.md: explain why both pins sit on the prod feature, what each
pin is for, and what would let it go. Replace the out-of-date hdf5
rationale: conda-forge ships hdf5 2.x on all platforms, and eccodes
is what holds every environment at 1.14.6. Note that re-solving
dev-future needs pixi update -e dev-future.

README and CHANGELOG: note that dev-future runs pandas and hdf5
unpinned.
```

---

### Task 3: Record the `dev-future` test run for the merge request

**Files:**
- None committed. Output goes into the MR description.

**Interfaces:**
- Consumes: Task 1's lock, and `$TMPDIR/lockdiff.py`.
- Produces: pass/fail counts and the lock-comparison table for the MR.

- [ ] **Step 1: Install and run the suite in `dev-future`**

Run: `pixi run -e dev-future test 2>&1 | tail -40`
Expected: it runs to completion. Failures are expected and informational (spec, Verification check 6). Record the final `N failed, N passed, N skipped` line and the names of failing test modules. If collection itself errors out on import, record the first import error. That's the most useful single finding for the pandas 3 follow-up.

- [ ] **Step 2: Separate new failures from the known five**

Compare the failing test names with the five known ones listed in Task 1, Step 8. List the rest as "new in `dev-future`". Don't try to classify each one as pandas 3, `pywatershed` 3 or `dataretrieval` 1.2. The MR only needs to record them.

- [ ] **Step 3: Re-run the lock comparison for the record**

Run: `.pixi/envs/default/bin/python "$TMPDIR/lockdiff.py" "$TMPDIR/pixi.lock.base" pixi.lock pandas hdf5 libnetcdf netcdf4 python`
Expected: the same output as Task 1, Step 5. Keep it for the MR.

- [ ] **Step 4: Hand the results to the maintainer, then stop**

Give the maintainer:
- the Task 1 lock-comparison output;
- the `default` test result (Task 1, Step 8);
- the `dev-future` counts and new failures (Steps 1–2).

Nothing to stage. Write the MR description in prose, not command lines, per the GitLab WAF note in AGENTS.md.
