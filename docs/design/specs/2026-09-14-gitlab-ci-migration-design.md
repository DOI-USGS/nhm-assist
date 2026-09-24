# Migrate CI to GitLab: repair the test suite, then gate merge requests

**Date:** 2026-09-14
**Status:** Draft, pending review
**Work item:** [#47 — Migrate CI from GitHub Actions to GitLab CI](https://code.usgs.gov/wma/hytest/nhm-assist/-/work_items/47)
**Supersedes:** `docs/design/specs/2026-08-25-gitlab-ci-migration-design.md`
**Branch:** off `develop`

## Why this supersedes the 2026-08-25 spec

The prior spec was written before roughly three weeks of merges landed on `develop`
(helper unification, the workspace/packaging restructure, the notebook-template
unification, the `feature/runner` merge). Five of its premises are no longer true, and
two blockers it could not have known about now dominate the work:

| 2026-08-25 spec assumed | Verified on `develop`, 2026-09-14 |
| --- | --- |
| Repo has no `AGENTS.md`; write one as the final task | `AGENTS.md` exists and already describes this exact CI gap |
| `pixi run test` = 70 tests in ~8s | 446 tests, ~90s |
| CI runs the `dev` environment | A dedicated `ci` environment now exists (`prod` + `test`) |
| Pin `ghcr.io/prefix-dev/pixi:0.40.3-noble` | Local pixi is 0.76.0; `0.76.0-noble` confirmed present on GHCR |
| Runner platforms unknowable without a GitLab token | Partly answerable now — see "Evidence from sibling pipelines" |

Its open questions #1–#5 are answered below with evidence rather than assumption. Its
core design — one pixi-based test job, `.github/` deleted afterward — survives intact.

## Problem

Every merge request opened on `code.usgs.gov/wma/hytest/nhm-assist` gets zero CI signal.
GitLab executes only `.gitlab-ci.yml`, which does not exist; the repository's sole CI
definition is `.github/workflows/ci.yaml`, which GitLab never reads. Confirmed via the
API: this project has run **zero pipelines, ever** (`/pipelines` returns `[]`).

Two blockers discovered while scoping this round:

**1. `pixi run test` is broken, and the suite is red.** `pytest tests/` cannot collect —
18 import errors, all `ModuleNotFoundError: No module named 'tests'`. `tests/unification/`
has an `__init__.py` and `tests/` does not, and there is no root `conftest.py` or
`pythonpath` setting, so the repository root never reaches `sys.path`. Running
`python -m pytest tests/` works around it (that inserts the cwd), which is why this has
gone unnoticed — but it means the `pixi run test` task in `pyproject.toml` has been
non-functional for everyone. Underneath the workaround, **five tests genuinely fail**.

**2. No runner is known to be attached.** `shared_runners_enabled` is `false` on this
project. Listing project or group runners requires Maintainer access, which the developer
driving this work does not have. A `.gitlab-ci.yml` with no runner produces a pipeline
that sits pending indefinitely — indistinguishable, to a contributor, from no CI at all.

## Evidence from sibling pipelines

Two WMA projects already run GitLab CI on `code.usgs.gov`. Their working configurations
answer more of the prior spec's open questions than local inspection could.

**`wma/nhgf/toolsteam/gdptools`** — the closer analogue (a Python library running a test
suite, not a deployment):

- **`tags: [wma]`.** A single tag, serving a project under `wma/nhgf/`. This is the
  strongest available evidence that `wma`-scoped runners exist and that `wma/hytest/`
  projects can reach them. Untagged jobs risk never being picked up at all.
- **`image: condaforge/miniforge3:latest`** — pulled directly from Docker Hub, with no
  Artifactory mirror. Public container registries are therefore reachable from these
  runners, which materially raises confidence that GHCR will work too.
- **The DOI root CA is required and is not pre-baked into runners.** `DOIRootCA2.crt` is
  committed at that repository's root — added in a commit titled "also getting gitlab
  runner working again by adding doicert" — copied into `/usr/local/share/ca-certificates/`,
  followed by `update-ca-certificates` and exports of `SSL_CERT_FILE`, `CURL_CA_BUNDLE`,
  `PROJ_CURL_CA_BUNDLE`, `GIT_SSL_CAINFO`, `PIP_CERT`, `REQUESTS_CA_BUNDLE`, plus
  `conda config --set ssl_verify`. The certificate is valid until 2036-04-26.

**`wma/nhgf/pygeoapi`** — a deployment pipeline, less directly applicable, but it
contributes two patterns:

- A fork guard as the first `workflow` rule: `if: $CI_PROJECT_PATH != "<path>" → when: never`.
- Commit-message escapes `[skip pipeline]` / `[run pipeline]`, which are a safer answer to
  the prior spec's open question #2 than any `rules: changes:` construction.

It also uses `artifactory.wma.chs.usgs.gov/docker-official-mirror/` for every image, which
is the documented fallback if GHCR turns out to be unreachable — though `docker-official-mirror`
mirrors Docker Hub *official* images only, and pixi is not one.

## Goal

Every merge request on `code.usgs.gov` runs a pixi-built test suite that is green,
meaningful, and fast enough to gate on — and `.github/` is retired once that is proven.

## Non-goals

- A blocking lint gate. `pixi run lint` fails today against pre-existing code with no
  `[tool.ruff]` config. Adding ruff configuration and fixing its findings is separate work.
- Coverage reporting, dependency auditing, or notebook-execution tests in this round.
- Restructuring the pixi environments (see "Recorded constraints" — this spec records a
  constraint on that work; it does not perform it).
- Windows/macOS coverage. WMA runners are Linux/AWS. This is a real, acknowledged
  reduction from the GitHub Actions three-OS matrix, stated here rather than left implicit.
- Creating the GitLab Pipeline Schedule, enabling runners, or flipping merge-gate settings.
  These are project-settings state a committed file cannot create; see "Maintainer actions".

## Decisions

### Repair the test suite first, in this work item

Work item #47 as written assumes `pixi run test` is a working gate to point CI at. It is
not. Turning on CI against the current `develop` would make every merge request red on day
one, which trains contributors to ignore the signal — the precise failure mode this
migration exists to eliminate. The five failures reduce to three root causes, and one is a
genuine regression that CI would have caught had it existed:

| Failing test(s) | Root cause | Kind |
| --- | --- | --- |
| `test_all_template_call_sites` (×2, on `gf_params_parse.py`), `test_nothing_in_the_repo_imports_a_retired_path` | `src/workflow_templates/nhf/gf_params_parse.py:49` imports `assist.nhf.nhm_assist_utilities_v2`, a module that no longer exists. `find_missing_gage_info` now lives at `src/assist/common/assist_utilities.py:802`. Introduced in `9a9cfa0`. | Real breakage on `develop` |
| `test_the_nhm_package_is_gone` | `src/assist/nhm/` contains only `__pycache__`; its sources were deleted in `8e21b32`, but stale `.pyc` files keep the directory present. | Local artifact; passes on a clean checkout |
| `test_new_loader_reads_the_repos_live_config` | Expects `subdomain_config.yaml` at the repository root. The workspace restructure eliminated repo-root configs; they live under a project's `project_config/` now. | Stale test |

All three are resolved as of 2026-09-24; see Task A for the record of each fix.

### One test job, nothing else, in the first pipeline

`pixi run -e ci test` and nothing more. This is the first pipeline this repository has ever
run, against a runner situation that is inferred rather than confirmed; every additional job
is another way for the first attempt to fail ambiguously. Non-blocking lint, coverage
reporting, and a nightly scheduled run are all reasonable follow-ups once a green pipeline
exists — and `workflow.rules` below already admits `schedule`-sourced pipelines, so the
nightly needs only a maintainer to create the schedule, not a file change.

### Run the `ci` environment, not `dev`

The `ci` environment (`prod` + `test`) postdates the prior spec. It excludes `proj-data` —
2.4 GB versus `default`'s 3.2 GB — while sharing the `default` solve group, so it resolves
to the same package versions users get.

> **Correction (2026-09-22, work item #49):** this paragraph originally claimed `ci` also
> excludes ruff and pre-commit. It does not. Both are present, as transitive conda
> dependencies of `pywatershed` 2.x rather than from the `dev` feature — see the rewritten
> "leaner CI dependency set" note below. `proj-data` is the entire difference between the
> two environments, and the 2.4 GB / 3.2 GB figures were measured correctly.

### No `cache:` block in the first pipeline

The prior spec proposed caching `.pixi/` keyed on `pixi.lock`. That environment is 2.4 GB;
compressing, uploading, and restoring it is plausibly slower than a fresh `pixi install`
from the lock file, and it is one more failure mode on a pipeline whose basic viability is
unproven. Ship without it, read the actual install time from the first job log, then add
caching as a measured follow-up if the number justifies it.

### Commit `DOIRootCA2.crt` at the repository root

`pixi install` fetches from conda-forge and PyPI over exactly the HTTPS path that USGS
TLS inspection intercepts. gdptools solves this by committing the certificate and
installing it in `before_script`; nhm-assist does the same. The certificate is a public
DOI root CA, not a secret.

### Commit-message escape instead of a `paths-ignore` equivalent

The old GitHub workflow skipped CI when only `**.md` or `.gitignore` changed. GitLab's
`rules: changes:` matches when *any* listed path changed, so expressing "skip only when
every changed file is a doc" requires maintaining an include-list of every source pattern
that should trigger CI — and missing a new file type means CI silently stops running on it.
`[skip pipeline]` in the commit message, per the pygeoapi convention, puts that decision in
the author's hands explicitly and fails safe.

### Delete `.github/` only after a green GitLab pipeline

Per work item #47's acceptance criteria. Until GitLab CI is proven, the GitHub Actions
workflow remains the only working CI definition in the repository, even if it only ever
fires on mirror pushes.

## Design

### Task A — repair the test suite

1. **Superseded by `07ea89f`.** This step proposed a `[tool.pytest.ini_options]`
   `pythonpath = ["."]` table. Instead, the `test` task now runs `python -m pytest tests/`,
   and the `-m` form puts the repository root on `sys.path` so `tests.unification.harness`
   resolves. No pytest configuration table was added. Bare `pytest` still collects only
   part of the suite, which the comment on the task records.

2. **Done in `41849b7`.** `src/workflow_templates/nhf/gf_params_parse.py` now imports
   `find_missing_gage_info` from `assist.common.assist_utilities`, which resolved three of
   the five failures.

3. **Done.** `test_the_nhm_package_is_gone` now asserts that `src/assist/nhm/` holds no
   `*.py` source, rather than that the directory is absent. Git leaves an untracked
   `__pycache__` behind when it deletes a package, and a sourceless `.pyc` there is not
   importable, so the leftover is not the package returning.
   `test_retired_module_is_unimportable` still guards every retired module by name. The
   fix was verified with the stale `__pycache__` still present, so no local
   `git clean` is needed.

4. **Done, re-pointed rather than retired.** The test's one unique claim is that both
   spellings resolve to the same value, `waterdata_*` and `nwis_*`, whichever one the
   YAML was written in. The two `tmp_path` schema tests assert only the `waterdata_*`
   side. It is now
   `test_both_gage_key_spellings_resolve_whichever_is_written`, parametrized over an
   `nwis` and a `waterdata` config. Each is written to `tmp_path` from
   `tests/unification/fabrics.py`'s `COMPLETE_CONFIG`, with that fixture's own `nwis_*`
   keys dropped so each case holds exactly one spelling.

Exit criterion: `pixi run test` exits 0. The baseline before steps 3 and 4 (2026-09-24)
was 456 collected: 444 passed, 2 failed, 10 skipped. After them it is 457 collected:
447 passed, 10 skipped. That count is +1 from step 3 and +2 from step 4, whose one test
became two cases. It was confirmed on 2026-09-24 in both the `default` and `ci`
environments.

### Task B — `.gitlab-ci.yml`

```yaml
---
stages:
  - test

workflow:
  rules:
    # Never run in forks or in the GitHub mirror's namespace.
    - if: $CI_PROJECT_PATH != "wma/hytest/nhm-assist"
      when: never
    - if: $CI_COMMIT_MESSAGE =~ /\[skip pipeline\]/
      when: never
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    # A push to a branch with an open MR would otherwise double-fire.
    - if: $CI_PIPELINE_SOURCE == "push" && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_PIPELINE_SOURCE == "push"
    - if: $CI_PIPELINE_SOURCE == "schedule"

test:
  stage: test
  tags:
    - wma
  image: ghcr.io/prefix-dev/pixi:0.76.0-noble
  interruptible: true
  before_script:
    # USGS TLS inspection: conda-forge and PyPI fetches fail without the DOI root CA.
    - cp DOIRootCA2.crt /usr/local/share/ca-certificates/
    - update-ca-certificates
    - export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
    - export CURL_CA_BUNDLE="${SSL_CERT_FILE}"
    - export REQUESTS_CA_BUNDLE="${SSL_CERT_FILE}"
    - export PIP_CERT="${SSL_CERT_FILE}"
    - export GIT_SSL_CAINFO="${SSL_CERT_FILE}"
    # PROJ uses its own libcurl handle and reads this, not CURL_CA_BUNDLE alone.
    # `ci` ships without proj-data and without PROJ_NETWORK=OFF, so a datum-shift
    # grid fetch from cdn.proj.org is permitted here and needs the DOI CA too.
    - export PROJ_CURL_CA_BUNDLE="${SSL_CERT_FILE}"
  script:
    - pixi run -e ci test
```

Plus `DOIRootCA2.crt` committed at the repository root, copied from the gdptools checkout.

### Task C — retire GitHub Actions, gated on a green pipeline

1. Delete `.github/workflows/ci.yaml` and the `.github/` directory.
2. Rewrite `AGENTS.md`'s CI section: GitLab CI is the real, current gate; describe the
   `wma` tag, the `ci` environment, the DOI certificate step, and `[skip pipeline]`.
   Remove the pointer to the superseded spec.
3. Note the Linux-only coverage change in `AGENTS.md`, not only in this spec.

## Recorded constraints on the pixi environment restructuring

> **Update (2026-09-22, work item #49): the merge has happened. One half of this
> constraint holds; the other half is withdrawn as wrong.**
>
> `default` now composes `prod` + `test` + `dev`; the `dev` *environment* is gone while the
> `dev` *feature* remains, since `dev-future` composes it. `ci` is unchanged at `prod` +
> `test`.
>
> - **"`ci` must not inherit `proj-data`" — still binding, and satisfied.** `proj-data`
>   sits in the `dev` feature, which `ci` does not compose. It is the *only* package
>   `default` has that `ci` lacks: 817 MB of `share/proj`, and the whole value of keeping
>   a separate `ci` environment at all.
> - **"`ci` must set `PROJ_NETWORK=OFF`" — WITHDRAWN.** An interim note dated 2026-09-18
>   recorded this as an unfixed defect. That was a misreading of why the setting exists.
>   `proj-data` and `PROJ_NETWORK=OFF` were introduced together (work item #33) to work
>   around USGS VPN SSL inspection breaking PROJ's grid fetch from `cdn.proj.org` *on
>   developer machines*. A WMA runner is not behind that inspection, and the CI job
>   installs the DOI root CA regardless — which is the same remedy, applied at the job
>   rather than by avoiding the network. A CI job reaching `cdn.proj.org` is therefore the
>   intended behaviour, not a hermeticity failure, and the dedicated `ci` activation block
>   sketched below should **not** be applied.
>
>   The one thing this does require is `PROJ_CURL_CA_BUNDLE` in the job's `before_script`,
>   since PROJ uses its own libcurl handle and does not read `CURL_CA_BUNDLE` alone. That
>   export has been added to the `.gitlab-ci.yml` above.
>
>   In practice this may never fire: the test suite only *constructs* `crs=4326`, and the
>   reprojections in `src/` are NAD83-family (`4326`↔`5070`, `ESRI:102039`), which do not
>   normally pull datum-shift grids. See "Risks and open questions" for the fallback if
>   the first pipeline proves otherwise.
>
> The `README.md` quotation below is also superseded: that file no longer describes
> `proj-data` as scoped to `dev`/`dev-future`, because `default` now carries it.

The lead developers intended to merge the `dev` environment into `default`, on the grounds
that most end users need `proj-data` too. This spec did not perform that change, but CI
depends on a property it could silently break, so the constraint is recorded here:

**`ci` must not inherit `proj-data`, and must set `PROJ_NETWORK=OFF`.**
*(The second clause is withdrawn — see the 2026-09-22 update above. The rest of this
section is the original text, kept for the record.)*

`proj-data` is ~800 MB of datum-shift grids. `README.md` already documents it as scoped to
`dev`/`dev-future` specifically "so `default`/`ci` don't pay the extra ~500MB". If
`proj-data` is moved into `prod` to give `default` the grids, `ci` inherits it too, since
`ci = prod + test`. The suggested shape that satisfies both goals:

```toml
[tool.pixi.feature.proj.dependencies]
proj-data = "*"
[tool.pixi.feature.proj.activation.env]
PROJ_NETWORK = "OFF"

# WITHDRAWN 2026-09-22 (#49) — do not apply this block; see the update above.
[tool.pixi.feature.ci.activation.env]
PROJ_NETWORK = "OFF"          # hermetic: never reach cdn.proj.org

[tool.pixi.environments]
default = { features = ["prod", "proj"], solve-group = "default" }
ci      = { features = ["prod", "test"], solve-group = "default" }
dev     = { features = ["prod", "proj", "test", "dev"], solve-group = "default" }
```

Same solve group throughout, so all three still resolve to identical versions.

~~`PROJ_NETWORK=OFF` on `ci` matters independently of that merge.~~ **Superseded
2026-09-22 (#49).** The original argument ran: `README.md`'s firewall warning describes
`pyproj` hanging or failing with `CERTIFICATE_VERIFY_FAILED` while fetching datum grids
from `cdn.proj.org` under SSL inspection, so a CI job with neither the grids on disk nor
network fetches disabled is exposed to exactly that. The error in it is treating "the same
interception the DOI certificate exists to handle" as a reason to avoid the network, when
it is a reason to trust the certificate — which the job already does. Exporting
`PROJ_CURL_CA_BUNDLE` extends that same remedy to PROJ's own libcurl handle, and is the
change actually adopted. Disabling the fetch instead would trade a working grid lookup for
silently lower-accuracy transforms.

**A leaner CI dependency set was considered and rejected.** The conclusion stands; the
original reasoning, kept below in strikethrough, measured the wrong thing.

~~Of the 41 direct dependencies, 32 are imported somewhere in `src/` or `tests/`. The nine
that are not — `distributed`, `ipython`, `jupyter-server`, `jupyterlab`, `pyarrow`,
`pyogrio`, `rasterio`, `rasterstats`, `scikit-image` — are mostly indirect I/O backends for
geopandas/pandas or the Jupyter runtime. Removing them would save roughly 300 MB of
2,400 MB.~~

Work item #49 measured where the weight actually is. **89 of `ci`'s 475 packages — 0.18 GB
of a 0.48 GB download — are reachable only through `pywatershed`**, whose conda-forge 2.x
recipe declares its lint, test, doc and optional extras as hard run dependencies: `ruff`,
`pre-commit`, `pytest-{cov,env,order,xdist}`, `sphinx`, `pandoc`, `git`, `virtualenv`, and
the `panel`/`holoviews`/`datashader`/`geoviews` stack. Pruning the direct dependency list
cannot reach any of that, which is why the ~300 MB estimate above overstated what the
exercise would buy.

The hazard that motivated the rejection is unchanged and still decisive: if CI's
environment omits a package some template imports, CI goes red for a problem no user has.
The tests import most of the stack precisely because they exercise what users run.

**Update (2026-09-22): the real lever was pulled.** `pywatershed` now comes from PyPI,
where those are genuine extras, with `numba` held on conda-forge for its numpy ABI coupling
and `python = ">=3.11.9,<3.12"` stating the 3.11 policy the conda recipe used to impose
implicitly. Measured: `ci` 475 → 412 packages and 2.4 GB → 1.9 GB on disk; `default`
3.2 GB → 2.7 GB. `ruff` and `pre-commit` left `ci` entirely.

Two consequences for this spec:

- **`ci` is now meaningfully distinct from `default`**, not one package wide — the split is
  `proj-data` plus the `dev` feature's lint tooling. The "Run the `ci` environment" decision
  above is stronger than when it was written.
- **A 0.5 GB smaller install changes the caching arithmetic.** The "No `cache:` block"
  decision was taken against a 2.4 GB environment; it is now 1.9 GB. Still ship without
  caching and read the real install time from the first job log, but the follow-up
  measurement is the one that settles it.

See "Why `pywatershed` comes from PyPI, not conda-forge" in `AGENTS.md`. The residual
`sphinx` stack in `ci` comes from `pyprms`, which makes the same packaging mistake in its
own PyPI metadata and needs an upstream fix.

## Risks and open questions

**`tags: [wma]` is inferred, not confirmed.** It is taken from a working pipeline in
`wma/nhgf/toolsteam/`, one namespace over. If those runners are not scoped to
`wma/hytest/`, the job sits pending rather than failing loudly. Mitigation: if the first
pipeline does not pick up within a few minutes, ask the toolsteam for the correct tag
rather than assuming the file is wrong.

**No runner may be attached at all.** `shared_runners_enabled` is `false`, and confirming
otherwise needs Maintainer access. This is the single most likely reason for the first
pipeline not to run, and it is not fixable from the repository.

**GHCR reachability is unproven.** gdptools proves Docker Hub is reachable; GHCR is a
different host. If the image pull fails, the documented fallback is
`condaforge/miniforge3:latest` with pixi installed in `before_script`, or the Artifactory
mirror.

**pixi may not honor `SSL_CERT_FILE`.** This is the sharpest technical unknown. pixi's
downloader is Rust-based, and depending on its TLS backend it may use bundled webpki roots
rather than the system trust store that `update-ca-certificates` and `SSL_CERT_FILE`
affect. gdptools sidesteps this with `conda config --set ssl_verify`, which has no pixi
equivalent. If `pixi install` fails with a certificate error despite the `before_script`,
the ordered fallbacks are: (1) `SSL_CERT_DIR` alongside `SSL_CERT_FILE`; (2) the
miniforge base image, where conda's `ssl_verify` setting is available; (3) `pixi config
set tls-no-verify true`, which is insecure and a last resort only.

**PROJ datum-grid fetches from a WMA runner are unproven.** `ci` ships without `proj-data`
and without `PROJ_NETWORK=OFF`, by the decision recorded above, so if a transform needs a
datum-shift grid the job will reach `cdn.proj.org` through the same inspected TLS path the
DOI certificate exists to handle. `PROJ_CURL_CA_BUNDLE` in `before_script` is the intended
remedy, but it has not been exercised on a runner. This is a low-probability risk: the
suite only constructs `crs=4326`, and `src/` reprojects within the NAD83 family
(`4326`↔`5070`, `ESRI:102039`), which does not normally trigger a grid download. If the
first pipeline does show a `CERTIFICATE_VERIFY_FAILED` or a hang inside `pyproj`, the
ordered fallbacks are: (1) confirm `PROJ_CURL_CA_BUNDLE` is exported before the failing
step; (2) set `PROJ_NETWORK=OFF` as a job variable, accepting ballpark transforms in CI;
(3) add `proj-data` to `ci`, at 817 MB, only if a test genuinely needs grid accuracy.

**Is `osx-64` still needed? (Recorded 2026-09-24; not decided.)** The workspace locks four
platforms, and `osx-64` (Intel Macs) is about a quarter of `pixi.lock`: 503 to 513 package
entries in each of `ci`, `default` and `dev-future`. Every re-lock solves and records it,
and no CI job here tests it. Dropping it from `[tool.pixi.workspace] platforms` would
shrink the lock and speed up solving. The cost is that anyone still on an Intel Mac could
no longer install, and `osx-arm64` builds do not run on Intel hardware. Before removing it,
ask the team whether anyone develops or runs notebooks on an Intel Mac. If the answer is
no, remove it in its own commit with a fresh re-lock, so the lock diff shows only the
dropped platform.

**A baseline-parity test is skipped for a stale reason. (Recorded 2026-09-24; follow-up.)**
`test_matches_the_baseline_nhm_loader_on_a_legacy_config` in
`tests/unification/test_config_schema.py` skips unless a repo-root `subdomain_config.yaml`
exists. The workspace restructure removed that file permanently. The test does not read it:
it writes its own legacy config to `tmp_path`. So the skip condition is meaningless and the
test never runs. It is one of the 10 skips. What it does need is the baseline revision
`27f7144`, which it loads with `git show`. GitLab clones only 20 commits deep by default,
so unskipping it as-is would fail in CI. It was left untouched in Task A. The follow-up is
either to change the skip condition to "baseline revision reachable" (it then runs locally
and skips in CI), or to set `GIT_DEPTH: 0` on the job so it runs in both, at the cost of
a full clone.

**GitLab CI cannot be verified locally.** Syntax can be checked with GitLab's CI Lint tool;
`workflow:` semantics, runner pickup, image pull, and TLS behavior cannot. The first
merge request is the actual test.

## Verification

1. `pixi run test` passes locally after Task A — 447 passed, 10 skipped. Not
   `python -m pytest`: the task itself, since that is what CI runs. Confirm
   `pixi run -e ci test` too, which is the exact command the job issues.
2. `.gitlab-ci.yml` passes GitLab's CI Lint tool (project → Build → Pipeline editor →
   Validate). The API endpoint requires a token scope the developer's token lacks, so this
   is done in the web UI.
3. **On the merge request: read the job log, not the badge.** The log must show the real
   test count — 447 passed, 10 skipped — and a successful `pixi install`. A green check on a job that
   silently collected zero tests is exactly the failure this migration is meant to end.
4. Confirm the pipeline fired *once*, not twice, for a push to a branch with an open MR.
5. Only after 3 and 4: delete `.github/`, update `AGENTS.md`.

## Maintainer actions this spec cannot perform

- Confirm or attach a runner; verify the correct tag.
- Create the Pipeline Schedule for the nightly dependency-drift run (`.gitlab-ci.yml`
  already admits `schedule`-sourced pipelines).
- Enable "Auto-cancel redundant pipelines" so `interruptible: true` has effect.
- Flip `only_allow_merge_if_pipeline_succeeds` (currently `false`) once the pipeline is
  trusted — without it, CI reports but does not gate.
- Commit, push, and open the merge request. Per `AGENTS.md`, agents stage only.
