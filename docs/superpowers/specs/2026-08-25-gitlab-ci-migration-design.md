# Migrate CI to GitLab, retire GitHub Actions, add AGENTS.md

**Date:** 2026-08-25
**Status:** Draft, pending review — several decisions below are open questions for a
GitLab-CI-literate co-developer to weigh in on before this becomes a plan.
**Scope:** add `.gitlab-ci.yml`; delete `.github/` (workflows + scripts); add `AGENTS.md` at
the repo root. No changes to `pyproject.toml`, `src/`, `tests/`, `README.md`, or `CHANGELOG.md`.

## Problem

Primary development (issues, commits, and CI) now happens on `code.usgs.gov/wma/hytest/nhm-assist`
(GitLab). `github.com/DOI-USGS/nhm-assist` is kept as an actively-mirrored, push-only copy for
visibility — not where CI, issues, or merge review happen. Despite that, the repository's only
CI definition is still `.github/workflows/ci.yaml`, a GitHub Actions workflow. GitLab does not
read `.github/workflows/*` at all — it only ever executes `.gitlab-ci.yml` — so **every merge
request opened on GitLab today gets zero CI signal**, including the draft MR that landed the
prior round's pixi migration. That workflow file (recently fixed to build via pixi and run the
real 70-test suite; see `docs/superpowers/specs/2026-08-21-ci-pixi-migration-design.md`) can
only ever fire from a push to the GitHub mirror, and only on `push` events — GitLab merge
requests don't create GitHub pull requests, so `on: pull_request` is dead code from GitLab's
perspective regardless.

Separately, there is no `AGENTS.md` at the repo root. The most recent two rounds of AI-agent
work on this repo (`docs/superpowers/specs/2026-08-21-ci-pixi-migration-design.md` and its
plan) established real, non-obvious operating norms for coding agents working here — the
stage-but-never-commit contribution norm chief among them — that currently live only in a
spec file an agent has to be told to go read.

## Goal

A working `.gitlab-ci.yml` that gives every GitLab merge request real CI signal by building via
pixi and running the test suite, replacing `.github/workflows/ci.yaml` (which is then deleted,
since nothing on GitLab reads it and its only remaining audience — the GitHub mirror — isn't
where development happens). An `AGENTS.md` at the repo root that tells a coding agent, up
front, how CI works now and what this repo's contribution norm expects, without requiring it
to first discover a spec file to learn either.

## Non-goals

- Any change to `pyproject.toml`, `src/`, or `tests/`.
- Removing links to *other* projects' GitHub repos (`pywatershed`, `dataretrieval-python`,
  `folium`, `pre-commit-hooks`, vendored PEST++ utilities, `.gitignore` template attributions).
  These aren't references to *this* repository's GitHub presence and were confirmed, by a
  repo-wide grep, to be the only kind of "github" mention left outside `.github/` itself — there
  is no `CONTRIBUTING.md`, no issue/PR template, no `CODEOWNERS`, and `README.md` already points
  to `code.usgs.gov` for cloning and release links.
- Setting up the actual GitLab Pipeline Schedule (the nightly cron trigger) — `.gitlab-ci.yml`
  can declare that `schedule`-sourced pipelines run the same job, but the cron timing itself is
  project-settings state, not something committed to the repo. That's a manual follow-up for a
  maintainer with project-settings access, same pattern as opening the MR was for the prior round.
- Verifying GitLab-specific runner/project-settings behavior that can't be checked from this
  local checkout (see Open Questions). This round's own CI run on the MR is the actual test, same
  as the prior round.

## Decisions (confirmed)

### Delete `.github/` entirely, don't keep it dormant

Once `.gitlab-ci.yml` is verified working, `.github/workflows/ci.yaml` and the (already-empty
after the last round) `.github/scripts/` directory are deleted outright — not commented out,
not left as a disabled reference. CI's home is GitLab now; keeping a second, unused CI
definition around is exactly the kind of drift that made `environment.yaml` go 29 packages
stale in the first place.

### Assume Linux-only GitLab runners, document the coverage change explicitly

The current GitHub Actions matrix covers `macos-latest`, `windows-latest`, `ubuntu-latest`.
Whether `code.usgs.gov` has non-Linux shared runners couldn't be confirmed — the project's
runner configuration needs an authenticated token to inspect via the GitLab API, and there's no
`glab` CLI or stored GitLab credential on this machine to check with (confirmed: the project's
public API is reachable, but `/runners` returns `401 Unauthorized` unauthenticated). Design
proceeds on the assumption of **Linux-only shared runners**, typical for self-hosted GitLab —
if that assumption is wrong, the whole job/matrix section below needs to expand back out to
multiple platforms. This is a real, acknowledged coverage loss versus the GitHub Actions
version, in the same spirit as the prior round's explicit acknowledgment of losing notebook
coverage: better to state the gap than let CI quietly imply coverage that isn't there.

### Keep a nightly scheduled run; drop the ORDWR delay step

The old delay step existed to stagger three simultaneous OS runners so they didn't all hit
ORDWR servers at once for the (now-retired) notebook job. `tests/` makes zero network calls
(confirmed in the prior round's final review), and a Linux-only pipeline has only one leg to
begin with — the stagger has no remaining purpose. The nightly run itself stays, as a
dependency-drift health check (`pixi run test` against whatever `pixi.lock` currently resolves
to, catching a newly-released package breaking something even with no code changes).

### `AGENTS.md` scope: operating norms + light codebase orientation

Not a full architecture document. Two parts:

1. **Operating norms for coding agents** — sourced from this round's and the prior round's
   specs/plans/ledger: pixi is the only supported environment/task runner (`pixi run test`,
   `pixi run lint` currently fails — 235/897/3 ruff errors with no `[tool.ruff]` config, not
   yet a usable gate); CI is GitLab-only, `.github/` does not exist; the contribution norm is
   that an agent stages changes (`git add`/`git rm`) but never commits, merges, pushes, or opens
   a merge request — that's the maintainer's action.
2. **Light repo orientation** — a short map of `src/assist/`, `src/workflow_templates/`,
   `notebooks/`, `tests/`, `docs/superpowers/` (this repo's spec/plan/agent-process working
   area), so an agent starts oriented instead of exploring cold.

Written and committed as the **last** step of the implementation plan, once the new CI is
actually in place — so it describes something true rather than something aspirational.

### Pixi-on-runner mechanism: official pixi Docker image

`image: ghcr.io/prefix-dev/pixi:<pinned-version>-noble` on the job, rather than installing pixi
via `curl -fsSL https://pixi.sh/install.sh | sh` on a generic Ubuntu image. No install step, no
extra network dependency on `pixi.sh` at job time, and this repo has no need for the extra
base-OS control a plain-Ubuntu-plus-installer approach would buy — `geopandas`/`rasterio`/
`fiona` all ship self-contained builds via conda-forge, no system packages needed beyond what
pixi/conda-forge already resolve.

Confirmed via the GHCR registry API (unauthenticated, public read) that versioned `-noble` tags
exist, e.g. `0.40.3-noble` — a specific version pin is more reproducible than the floating
`latest`/`noble` tags, which also exist. The exact version to pin should be whatever's current
at implementation time; bumping it periodically is a maintainer task, not a one-time decision.

## Open Questions — for GitLab-CI-literate review before this becomes a plan

These are genuine unknowns from this session, not stylistic preferences. Each one changes the
`.gitlab-ci.yml` design below if answered differently:

1. **Runner platforms.** Does `code.usgs.gov` provide macOS and/or Windows shared runners for
   this project, or Linux only? Confirms or overturns the Linux-only assumption above.
2. **`paths-ignore` equivalent.** The old workflow skipped CI for changes that touched only
   `**.md` / `.gitignore`. GitLab's `rules: changes:` matches if *any* listed path changed, not
   "only these" — there's no clean equivalent to "skip only when every changed file is a doc."
   Building one means maintaining an include-list of every source pattern that *should* trigger
   CI (miss a new file type → CI silently doesn't run on it — precisely the failure mode this
   whole migration effort exists to eliminate). Given the test suite now runs in ~8 seconds
   locally, my recommendation is to **drop the doc-skip optimization entirely** and run on every
   push/MR — but this trades a small amount of runner time for removing a correctness-risk
   mechanism, and I'd like a second opinion from someone who's hit this GitLab pattern before.
3. **Duplicate-pipeline prevention.** GitLab fires both a branch pipeline and a merge-request
   pipeline for the same push unless deduplicated. Proposed `workflow: rules:` block below
   follows GitLab's own documented pattern for this (MR pipelines take precedence via
   `$CI_OPEN_MERGE_REQUESTS`). Does this project have any existing convention or gotcha around
   this that differs?
4. **`interruptible: true` / auto-cancel.** This only actually cancels a superseded pipeline if
   the project setting "Auto-cancel redundant pipelines" is on — unverifiable without
   project-settings access. Can someone confirm it's enabled, or should the design not rely on it?
5. **Pinned image version.** Is `0.40.3-noble` (confirmed to exist right now) an acceptable pin,
   or does someone have a more current/preferred version already used elsewhere in this org's
   GitLab pipelines?

## Design

### `.gitlab-ci.yml`

```yaml
stages:
  - test

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_PIPELINE_SOURCE == "push" && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_PIPELINE_SOURCE == "push"
    - if: $CI_PIPELINE_SOURCE == "schedule"

test:
  stage: test
  image: ghcr.io/prefix-dev/pixi:0.40.3-noble
  interruptible: true
  cache:
    key:
      files:
        - pixi.lock
    paths:
      - .pixi
  script:
    - pixi run test
```

- `workflow.rules` — MR-sourced pipelines run; a `push` to a branch with an open MR is
  suppressed (avoids the duplicate-pipeline problem); a plain `push` (no open MR — e.g. a direct
  push to `main`) runs; `schedule`-sourced pipelines (the nightly cron, once a Pipeline Schedule
  exists in project settings) run the same job.
- `cache` — keyed on the hash of `pixi.lock`, so it invalidates exactly when the lock file
  changes; caches `.pixi/` (the installed environment), avoiding a full re-resolve/re-install on
  every run.
- `script: pixi run test` — identical to the local dev workflow and to the GitHub Actions
  version; `pixi run` auto-installs/updates the environment from `pixi.lock` before running, so
  no separate install step is needed.

### Files deleted

| File | Reason |
| --- | --- |
| `.github/workflows/ci.yaml` | GitLab never reads it; CI's home is now `.gitlab-ci.yml`. |
| `.github/scripts/` | Already empty after the prior round; the directory itself goes with the workflow. |

### `AGENTS.md`

New file at the repo root. Content per the "AGENTS.md scope" decision above — drafted in the
implementation plan's final task, once `.gitlab-ci.yml` is confirmed working, so it can state
CI's actual behavior rather than its intended behavior.

## Risks

**Same defining constraint as the prior round: GitLab CI cannot be verified locally.** `pixi
run test` passing locally proves the command works, not that the pipeline syntax, image, cache,
or `workflow.rules` behave as designed on an actual `code.usgs.gov` runner. The Open Questions
above are exactly the parts most likely to need adjustment once this actually runs — this
spec's design is correct-by-inspection only until a real pipeline executes against it.

**Runner platform mismatch.** If `code.usgs.gov` does have Windows/macOS runners and this design
ships Linux-only, real coverage is lost silently unless someone reads this spec. Mitigated by
Open Question #1 and by writing the coverage-loss statement directly into `AGENTS.md`, not just
this spec.

**No Pipeline Schedule = the "nightly run" doesn't actually happen** until a maintainer creates
one in project settings. `.gitlab-ci.yml` alone cannot create it. Same shape of risk as "opening
the PR is the maintainer's action" in the prior round — a step this spec cannot execute for you.

**Shared repository.** Same as the prior round — `code.usgs.gov/wma/hytest/nhm-assist` has other
maintainers, and this changes what every contributor's merge requests are gated on. Should go
through review, and per this round's explicit request, through a GitLab-CI-literate
co-developer's review of the Open Questions above specifically.

## Verification

1. `.gitlab-ci.yml` is valid — checked via GitLab's own CI Lint tool (`code.usgs.gov` exposes
   this per-project; there is no reliable local equivalent for `workflow:` semantics, only for
   YAML syntax).
2. `pixi run test` passes locally — 70 tests, unchanged by this round.
3. `grep -rn "github"` across the repository (excluding vendored third-party code and links to
   other projects) returns nothing pointing at this repository's own GitHub presence, other than
   the two intentional historical mentions already present in `README.md`/`CHANGELOG.md` from
   the prior round.
4. **On the MR:** the pipeline actually runs and the job log shows the real test count — not
   just a green check. This is the direct GitLab equivalent of the prior round's "read the job
   log, do not trust the green check" requirement, and matters even more here since this is the
   very first pipeline this repo has ever run on GitLab.

Per the repository's contribution norms, the agent stages changes and does not commit, merge,
or push. Opening the merge request is the maintainer's action.
