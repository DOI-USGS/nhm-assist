# CI Pixi Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CI build from `pyproject.toml` via pixi instead of the stale `environment.yaml`, run the real 70-test pytest suite instead of the vacuous notebook-glob step, and delete everything that only served the old flow.

**Architecture:** Two mechanical changes to `.github/workflows/ci.yaml` (swap `mamba-org/setup-micromamba` for `prefix-dev/setup-pixi`, swap the notebook-test step for `pixi run test`), then deletion of `environment.yaml`, four now-orphaned `.github/scripts/*.py` files, and the resulting empty `.github/scripts/` directory. No changes to `pyproject.toml`, `src/`, `tests/`, `README.md`, or `CHANGELOG.md`.

**Tech Stack:** GitHub Actions YAML, `prefix-dev/setup-pixi@v0`, pixi tasks defined in `pyproject.toml` (`[tool.pixi.tasks.test]`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-ci-pixi-migration-design.md`

## Global Constraints

- Scope is limited to `.github/workflows/ci.yaml`, `.github/scripts/`, and `environment.yaml`. Do not touch `pyproject.toml`, `src/`, or `tests/`.
- `README.md:15` and the `CHANGELOG.md` `environment.yaml` mentions are historical record — leave both files untouched.
- The commented-out `lint` job in `ci.yaml` stays commented out (deferred per spec Decisions — ruff has 235/897/3 errors across `src/assist`/`src/workflow_templates`/`tests` with no `[tool.ruff]` config yet).
- Keep the three-OS matrix (`macos-latest`, `windows-latest`, `ubuntu-latest`) and `fail-fast: false`.
- Keep `paths-ignore`, `concurrency`, `schedule`, the scheduled Linux delay step, and `defaults.run.shell: bash -el {0}` exactly as they are — this round does not touch them.
- **Per the repository's contribution norms: stage changes with `git add`, but do not `git commit`, merge, or push, and do not open a PR.** That is the maintainer's action. Every task below ends with staging, not committing.
- CI cannot be verified locally (three-OS GitHub-hosted runners aren't reproducible with `act`). Local verification is correct-by-inspection; the real check happens once a maintainer opens a PR from this branch.

---

## Task 1: Replace micromamba + notebook-test step with pixi + pytest in `ci.yaml`

**Files:**
- Modify: `.github/workflows/ci.yaml`

**Interfaces:**
- Consumes: `[tool.pixi.tasks.test]` from `pyproject.toml:234-237` (`cmd = "pytest tests/"`, `default-environment = "dev"`) — already exists, unmodified by this plan.
- Produces: n/a (leaf change, nothing downstream depends on this file's structure).

- [ ] **Step 1: Remove the `python-version` matrix entry**

In `.github/workflows/ci.yaml`, in the `test` job's `strategy.matrix` block, delete the `python-version` line. It's currently:

```yaml
    strategy:
      fail-fast: false
      matrix:
        os: ["macos-latest", "windows-latest", "ubuntu-latest"]
        python-version: ["3.11"] #  "3.11"]
```

Change to:

```yaml
    strategy:
      fail-fast: false
      matrix:
        os: ["macos-latest", "windows-latest", "ubuntu-latest"]
```

Reason: pixi pins the interpreter via `pyproject.toml` (`python = ">=3.11.9,<3.14"`), so this matrix entry is inert and misleading (per spec, "Keep the three-OS matrix").

- [ ] **Step 2: Replace the micromamba setup step with pixi setup**

Replace this step:

```yaml
      - name: Setup micromamba
        uses: mamba-org/setup-micromamba@v1
        with:
          environment-file: environment.yaml
          cache-environment: true
          cache-downloads: true
```

with:

```yaml
      - name: Setup pixi
        uses: prefix-dev/setup-pixi@v0
        with:
          environment: dev
          cache: true
```

`environment: dev` is required because `[tool.pixi.tasks.test]` declares `default-environment = "dev"`, and that's the environment carrying pytest.

- [ ] **Step 3: Replace the notebook-test step with `pixi run test`**

Replace this step (the one that globs a directory that doesn't exist and silently passes):

```yaml
      - name: Test notebooks
        working-directory: .github/scripts
        run: |
          python test_notebooks.py
```

with:

```yaml
      - name: Run tests
        run: pixi run test
```

- [ ] **Step 4: Confirm the scheduled-delay step and everything above/below it is untouched**

Read the full file back and confirm it now matches exactly:

```yaml
name: NHM-Assist continuous integration
on:
  # run at 6 AM UTC every day
  # this time is checked below for certain actions: change everywhere if you change
  schedule:
    - cron: "0 6 * * *"
  push:
    paths-ignore:
      - "**.md"
      - ".gitignore"
  pull_request:
    paths-ignore:
      - "**.md"
      - ".gitignore"

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  # lint:
  #   name: Lint
  #   runs-on: ubuntu-latest
  #   defaults:
  #     run:
  #       shell: bash
  #   steps:
  #     - name: Checkout repo
  #       uses: actions/checkout@v4

  #     - name: Setup python
  #       uses: actions/setup-python@v5
  #       with:
  #         python-version: '3.10'

  #     - name: Install ruff
  #       run: pip install ruff

  #     - name: Lint
  #       run: ruff check .

  #     - name: Check format
  #       run: ruff format . --check

  test:
    name: test notebooks
    # needs: lint
    runs-on: ${{ matrix.os }}

    strategy:
      fail-fast: false
      matrix:
        os: ["macos-latest", "windows-latest", "ubuntu-latest"]

    defaults:
      run:
        shell: bash -el {0}

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Setup pixi
        uses: prefix-dev/setup-pixi@v0
        with:
          environment: dev
          cache: true

      # Osx and Linux start with nearly the same speed, Windows is slower.
      - name: Scheduled - delay Linux to not hit ORDWR servers simultaneously
        if: ${{ (github.event.schedule == '0 6 * * *') && (runner.os == 'Linux') }}
        run: |
          python -c "import time; time.sleep(210)"

      - name: Run tests
        run: pixi run test
```

Note: the job's display `name: test notebooks` and the `# needs: lint` comment are left exactly as-is — the spec's Design section only specifies replacing the two steps above, and renaming the job is out of scope for this round.

- [ ] **Step 5: Validate the YAML parses**

Run: `python -c "import yaml, sys; yaml.safe_load(open('.github/workflows/ci.yaml'))" && echo VALID`
Expected: `VALID` printed, no exception.

- [ ] **Step 6: Stage the change (do not commit)**

```bash
git add .github/workflows/ci.yaml
git status
```

Expected: `.github/workflows/ci.yaml` shows as staged (`modified:` under "Changes to be committed"). No commit is made.

---

## Task 2: Delete `environment.yaml` and the orphaned `.github/scripts/*.py` files

**Files:**
- Delete: `environment.yaml`
- Delete: `.github/scripts/test_notebooks.py`
- Delete: `.github/scripts/mv_cache_files_for_scheduled_tests.py`
- Delete: `.github/scripts/restore_cache_files_after_scheduled_tests.py`
- Delete: `.github/scripts/rm_test_output_files_from_cache.py`
- Delete: `.github/scripts/` (directory, once empty)

**Interfaces:**
- Consumes: Task 1's edited `.github/workflows/ci.yaml`, which no longer references `environment.yaml` or `test_notebooks.py`. Deleting these files before Task 1 lands would break CI; deleting after is safe because nothing in the repo still points at them.
- Produces: n/a.

- [ ] **Step 1: Confirm each file is orphaned before deleting**

Run each of these and confirm the only hits are inside `.github/scripts/` itself (self-references) or, for `environment.yaml`, only `README.md` and `CHANGELOG.md`:

```bash
grep -rn "environment\.ya\?ml" --exclude-dir=.git --exclude-dir=.pixi --exclude=pixi.lock .
grep -rln "test_notebooks" --exclude-dir=.git --exclude-dir=.pixi --exclude=pixi.lock .
grep -rln "mv_cache_files_for_scheduled_tests\|restore_cache_files_after_scheduled_tests\|rm_test_output_files_from_cache" --exclude-dir=.git --exclude-dir=.pixi --exclude=pixi.lock .
```

Expected:
- `environment.yaml` grep: `CHANGELOG.md` (2 historical lines), `README.md:15`, and `.github/workflows/ci.yaml:67` (this last one disappears once Task 1's edit is in the working tree — if Task 1 already ran, it won't show).
- `test_notebooks` grep: only `.github/scripts/test_notebooks.py` itself, plus `.github/workflows/ci.yaml` (again, gone if Task 1 already ran).
- Cache-script grep: only the three files under `.github/scripts/` (they reference each other), nothing else.

- [ ] **Step 2: Delete the five files**

```bash
git rm environment.yaml
git rm .github/scripts/test_notebooks.py
git rm .github/scripts/mv_cache_files_for_scheduled_tests.py
git rm .github/scripts/restore_cache_files_after_scheduled_tests.py
git rm .github/scripts/rm_test_output_files_from_cache.py
```

`git rm` deletes the file from the working tree and stages the deletion in one step, satisfying "stage but don't commit."

- [ ] **Step 3: Remove the now-empty `.github/scripts/` directory**

```bash
ls -la .github/scripts/ 2>&1
```

Expected: `No such file or directory` — `git rm` removes a directory automatically once it's empty of tracked files. If anything remains (e.g., an untracked file), investigate before removing it; do not force-delete something unexpected.

- [ ] **Step 4: Confirm the staged state**

```bash
git status
```

Expected: five deletions staged (`deleted:` under "Changes to be committed"), `.github/scripts/` no longer listed as a tracked directory. Still no commit.

---

## Task 3: Local verification pass

**Files:** none modified — this task only runs checks against the state produced by Tasks 1 and 2.

**Interfaces:**
- Consumes: the staged working tree from Tasks 1 and 2.
- Produces: a pass/fail signal for whether this branch is ready to hand to a maintainer to open a PR (per spec Verification items 1-4; item 5 — green matrix legs and 70 tests in the PR's own CI run — can only be checked once a PR exists, which is explicitly the maintainer's action, not this plan's).

- [ ] **Step 1: Re-run the orphan-reference greps against the final tree**

```bash
grep -rn "environment\.ya\?ml" --exclude-dir=.git --exclude-dir=.pixi --exclude=pixi.lock .
```

Expected: exactly two files, `README.md` (1 line) and `CHANGELOG.md` (2 lines). Nothing else — confirms spec Verification item 1.

```bash
grep -rln "test_notebooks\|mv_cache_files_for_scheduled_tests\|restore_cache_files_after_scheduled_tests\|rm_test_output_files_from_cache" --exclude-dir=.git --exclude-dir=.pixi --exclude=pixi.lock .
```

Expected: no output at all — confirms spec Verification item 2.

- [ ] **Step 2: Run the real test suite locally**

```bash
pixi run test
```

Expected: 70 tests pass (same count noted in the spec — this round doesn't change `tests/`, so the count should be unchanged from before this branch). If the count differs, stop and investigate before proceeding — that's a signal something outside this plan's scope has drifted, not something to silently paper over.

- [ ] **Step 3: Validate the workflow YAML and confirm it only references tasks that exist**

```bash
python -c "import yaml; d = yaml.safe_load(open('.github/workflows/ci.yaml')); print('VALID YAML')"
grep -n "pixi run" .github/workflows/ci.yaml
grep -n "^\[tool.pixi.tasks\." pyproject.toml
```

Expected: `VALID YAML`; the only `pixi run` invocation is `pixi run test`; and `test` appears among the `[tool.pixi.tasks.*]` sections in `pyproject.toml` (alongside `setup`, `dev`, `notebooks-create`, `notebooks-create-project`, `workspace-init`, `project-create`, `project-list`, `project-set-active-model`, `model-create`, `model-list`, `model-copy-example`, `model-import`, `lint`). Confirms spec Verification item 4.

- [ ] **Step 4: Review the full staged diff**

```bash
git status
git diff --staged
```

Expected: `.github/workflows/ci.yaml` modified as in Task 1; `environment.yaml` and the four `.github/scripts/*.py` files deleted; no other files touched; nothing committed.

- [ ] **Step 5: Leave the branch for the maintainer**

No further action — do not commit, merge, push, or open a PR. Report to the user that the branch has staged, uncommitted changes ready for their review, and that spec Verification item 5 (three green matrix legs, log confirming 70 tests run) can only be checked once they commit, push, and open a PR themselves.

---

## Self-Review Notes

- **Spec coverage:** Every item in the spec's Design, "Files deleted", and Verification (1-4) sections maps to a task above. Verification item 5 is explicitly out of this plan's reach per the spec's own Risks section ("CI cannot be verified locally") and is called out as the maintainer's follow-up in Task 3 Step 5.
- **No placeholders:** every step shows the literal before/after YAML or the literal shell command; nothing says "add appropriate handling" or defers detail.
- **Consistency check:** the `pixi run test` invocation in Task 1 Step 3 matches `[tool.pixi.tasks.test]` in `pyproject.toml:234-237` verified in Task 3 Step 3; the five deleted paths in Task 2 match the "Files deleted" table in the spec exactly.
