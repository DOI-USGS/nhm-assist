# Dev mode and branch switching: questions for the notebook developers

**Date:** 2026-09-22
**Status:** Questions for discussion — no decisions made yet
**Builds on:** `docs/design/specs/2026-09-16-dev-mode-sync-divergence-design.md` (merged as MR !55)

## Purpose

MR !55 fixed three defects in dev-mode syncing. A contributor has since
reported a failure it does not cover: notebooks carrying content across a
`git switch` and overwriting the template on the branch they land on.

This document is for the meeting, not for implementation. It records what we
have verified, states plainly what MR !55 does and does not close, and lists
the questions whose answers change the design. It becomes the real spec once
those questions have answers — at which point the candidate directions at the
end get narrowed to one and a Decisions section replaces this one.

## What was reported

> "My problem was actually more like git switching and switching between
> branches. Then having the old notebook from a previous branch overwrite the
> newer .py on a different branch. When you re-run dev-mode, it checks the
> notebook is pointing at the right template, but it never looks at whether the
> notebook's actual content is still up to date with the branch. Since the
> notebook is outside the repo and the only thing tracked is the .py, when we
> switch, the notebooks carry over."

This is accurate, and it is a different defect from the one MR !55 addressed.

## What we have verified

### Re-running dev-mode does not refresh notebook content

`_patch_existing_notebook` in `src/workflow_templates/make_notebooks.py`
compares exactly three things: the `formats` string, the
`notebook_metadata_filter`, and the absence of a `kernelspec`. When those
match it returns `"already configured"` and writes nothing.

Even on the branch where it does write, it reads the *notebook*, patches that
notebook's metadata, and writes it back. **It never reads the template.**
Notebook cell content is therefore untouched by every dev-mode run after the
first. The reporter's description of this is exactly right.

This is not a bug in isolation — the cell-preservation guarantee is deliberate
and load-bearing, because overwriting would destroy unsynced edits. The gap is
that there is no other mechanism that *does* reconcile content, and the command
name suggests to the user that one ran.

### After a branch switch, file modification time carries no information

jupytext resolves a two-sided sync by modification time: the newer file wins,
silently, exit code 0. That was established in the 2026-09-16 spec (scenarios
2–4).

We tested what `git switch` does to modification times. Given a `t.py` aged to
2020 on the base branch:

| Action | Resulting content | Resulting mtime |
| --- | --- | --- |
| `git switch feature` (newer content) | `new-on-feature` | checkout time |
| `git switch` back to base (**older** content) | `old` | checkout time |

Git stamps the checkout time onto any file whose content differs between the
two branches — whether that content is newer or older in any meaningful sense.
A file that is identical on both branches is not rewritten and keeps its old
mtime.

So after a branch switch, "newer file" and "correct content" are unrelated
facts. The template always *looks* freshest, until the contributor runs or
saves a cell — and then the notebook does.

### The resulting failure window

1. Work in dev mode on branch A. The notebook holds branch A's content.
2. `git switch branch-B`. The `.py` changes on disk. The `.ipynb` lives outside
   the repo, is untracked, and carries over unchanged.
3. `pixi run dev-mode` reports `already configured`. Nothing about the content
   is checked or changed.
4. If the notebook is **opened** now, sync-on-open pulls branch B's template in
   and all is well.
5. If the notebook was **already open** across the switch — no open event fires
   — running a cell and saving pushes branch A's content over branch B's
   template.

Step 5 is the reported failure. Step 4 is why it is intermittent and hard to
describe: the same actions in a different order produce opposite outcomes.

### The root cause underneath all of it

The notebook is untracked, branch-independent state layered on top of
branch-dependent templates. Git's branch model does not reach outside the
repository, and nothing currently records which commit or which template
content a given notebook's cells came from. Without that record, no tool can
tell a stale notebook from an edited one.

## What MR !55 does and does not close

Closes: saving a template silently doing nothing; 47 templates carrying stale
`formats:` headers; a `git pull` being clobbered by a notebook the contributor
then opens.

Does not close:

- A notebook left **open** across a branch switch or pull. No open event fires,
  so sync-on-open never runs.
- Branch switching at all. `onNotebookDocumentOpen: true` reconciles by mtime,
  which we have now shown is meaningless immediately after a checkout.
- `pixi run dev-mode` being a content no-op while reading as a refresh.
- Projects created **before** MR !55. `create_project` never overwrites an
  existing `.vscode/settings.json`, so those still carry
  `onNotebookDocumentOpen: false` until someone runs the setup menu's option 11,
  "Repair editor settings for this project".

## Questions

Grouped by what each group's answers would change. The "why it matters" lines
are there so the meeting can skip questions whose answer is already obvious.

### A. Pinning down what actually happened

1. When a template reverted, was the lost work **committed** or only edited in
   the working tree?
   *Why:* if it was committed, `git reflog` and `git restore` are a real
   backstop and this is a serious annoyance. If uncommitted, it is
   unrecoverable data loss and the fix needs to be a guard, not a report.

2. At the moment it happened, was the notebook **already open** in the editor
   before you switched branches, or did you open it afterwards?
   *Why:* these are two different fixes. Already-open is the gap MR !55 cannot
   reach; opened-afterwards would mean the sync-on-open fix is not working at
   all in your setup, which points at question 16.

3. Did you run `pixi run dev-mode` after switching expecting it to bring the
   notebook up to date?
   *Why:* it does not, and if that expectation is widespread, correcting it —
   in the command's own output, not just the README — is the cheapest available
   fix and worth doing regardless of what else we build.

4. Have you ever seen `[jupytext] Warning: ... is not a paired notebook`, or any
   jupytext output at all, in Kiro?
   *Why:* tells us whether the Jupytext Sync extension is running for you.

5. Does the same thing happen on `git pull`, or only on switching branches?
   *Why:* pull has the same shape and any fix should cover both, but confirming
   it tells us whether the trigger is checkout specifically.

### B. How you actually work

6. One workspace project shared across all your branches, or a separate project
   per branch? How often do you switch branches with notebook work in flight —
   several times a day, or occasionally?
   *Why:* sets how much friction a fix is allowed to add per switch.

7. How expensive are the cell outputs in a notebook you have been working in —
   seconds to re-run, minutes, or a long run you would be unhappy to repeat?
   *Why:* this is the single biggest input. If outputs are cheap, "refresh the
   notebook from the branch's template" is a clean answer. If they are
   expensive, that answer is unacceptable and we need something that preserves
   outputs while replacing code.

8. When you change something, do you edit the **notebook** or the **`.py`
   template**?
   *Why:* saving the template pushes nothing to the notebook, by design and for
   a reason that still holds. If people are editing templates directly, that is
   a separate confusion worth naming.

9. When you switch branches, do you typically have notebook edits that have not
   yet made it into the template?
   *Why:* decides whether a refresh needs an "you have unsynced edits" guard or
   can simply overwrite.

10. Does more than one person ever use the same workspace project?

### C. What you want to happen

11. **The central question.** When you switch branches, what *should* happen to
    the notebook you were working in? Roughly:
    - **Follow the branch.** The notebook tracks the branch like any other
      source file. Outputs and scratch edits are expendable or backed up.
    - **The notebook is mine.** It is a persistent working document; a branch
      switch must never silently change it. Warn at most.
    - **It depends.** Silently refresh when the notebook has nothing the
      template lacks; stop and make me resolve it when it does.
    - **Don't share notebooks across branches at all.** See question 14.

    *Why:* every other decision follows from this one, and it is genuinely
    yours — there is no technically correct answer.

12. Would you accept a command that **refuses to proceed**, or prints a loud
    warning, when a notebook disagrees with the current branch's template? Or do
    you want this to work silently?
    *Why:* a blocking guard is far easier to make correct than an automatic
    merge, and it never loses work. It does interrupt you.

13. If we refresh a notebook from the template, is a timestamped backup copy of
    the old notebook enough safety, or do you want to be asked each time?

14. How much setup cost would you accept to remove the problem structurally —
    a git worktree per branch, or a workspace project per branch, so notebooks
    never cross branches at all?
    *Why:* this is the only direction that eliminates the failure rather than
    mitigating it. It costs disk and a more complex mental model.

15. Should any check be **automatic** (a git hook firing on checkout and pull)
    or an **explicit command** you run when you choose?
    *Why:* a hook lives in the repo but the notebooks live outside it, so an
    automatic check has to discover which workspaces exist. That is real
    complexity, worth paying only if people would not run the command.

### D. Environment — still unresolved from the 2026-09-16 spec

16. Task 0 of that spec was never answered and everything in MR !55 assumes it.
    In Kiro, run **Jupytext Sync: Show Logs** from the command palette. Does it
    name your project's pixi interpreter?
    *Why:* if Kiro does not read the generated `.vscode/settings.json`, MR !55's
    fix never reached you, and the sync-on-open premise is wrong for the people
    who reported the problem. This should be checked **before** the meeting if
    possible — it may reframe several answers above.

17. Does your project's `.vscode/settings.json` contain
    `"onNotebookDocumentOpen": true`? If your project predates MR !55 it will
    not, and you need the setup menu's option 11, "Repair editor settings for
    this project".

## Candidate directions

Listed so the questions have context. **None of these is chosen**, and several
combine.

| | Direction | Roughly what it costs | What it does not fix |
| --- | --- | --- | --- |
| A | Documentation and process only: a "before you switch branches" checklist in the README — close notebooks, save, switch, reopen. | Hours. | Relies on discipline; the failure is silent when discipline slips. |
| B | Record provenance: stamp the template's content hash into the notebook at generation and sync. `dev-mode` then reports which notebooks disagree with the current branch. | Moderate. Needs a place in notebook metadata and a comparison path. | Reports only; does not prevent or repair. |
| C | B, plus an explicit refresh that regenerates diverged notebooks from the branch's templates, backing up what it replaces and refusing when there are unsynced edits. | Moderate to high. The "unsynced edits" test is the hard part. | Contributor must remember to run it — unless combined with D. |
| D | A `post-checkout` / `post-merge` git hook that runs B's check for registered workspaces. | Moderate. Hooks are not distributed by git and the workspaces live outside the repo, so both need solving. | Nothing, if B or C is sound — but it is the piece most likely to break quietly. |
| E | Structural: a git worktree or workspace project per branch, so notebooks never cross branches. | Low to build, higher to live with. | Nothing — it removes the failure mode. Costs disk and a more complex mental model. |
| F | Have `dev-mode` touch the templates so they reliably win the next sync. | An hour. | A blunt mtime trick that would discard genuine pre-switch notebook edits. Listed for completeness; only viable behind C's dirty check. |

Worth noting that A is not merely a fallback. Whatever else we build, the
README and the `dev-mode` command's own output currently imply a content
refresh that does not happen, and that is worth correcting on its own.

## What happens after the meeting

Answers to section C, and especially questions 7 and 11, select from the table
above. This file then gets a Decisions section, drops the Questions section to
an appendix, and becomes the spec that an implementation plan is written
against.

Question 16 should be answered first if at all possible — it can invalidate
premises in the rest.
