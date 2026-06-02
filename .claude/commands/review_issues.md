---
description: Review every open GitHub issue one at a time with checkpoints: assess validity, severity, and disposition, then a prioritized triage summary
---

# /review_issues

Drive a structured review of the repo's open issues with human-in-the-loop checkpoints. This is the issue-side companion to `/review_pr`: it assesses and recommends, it does not fix. Fixing a confirmed issue is the job of `/begin_work` (start work on one issue) or the `triage_issues` skill (reproduce and fix each). Keep that boundary: `/review_issues` produces a triage, not a patch.

Work through every step in order. After each step, stop at the **CHECKPOINT** and wait for the user before continuing.

## Argument

`$ARGUMENTS` is optional:

- empty: review all open issues.
- a label name (e.g. `bug`): review only open issues carrying that label.
- one or more issue numbers (e.g. `102 119 126`): review just those.

If an explicit number is given that is closed or does not exist, note it and skip it rather than aborting the whole run.

## 1. Gather the issue roster

Fetch the open issues in one call:

```
gh issue list --state open --limit 200 --json number,title,labels,author,createdAt,comments,assignees
```

(Apply the label filter with `--label <name>`, or fetch the explicit numbers with `gh issue view` per number.)

Then present a roster the user can confirm before the deep review:

- One row per issue: `#N`, title, labels, comment count, age.
- Propose a **review order**. Default: bugs before enhancements, then oldest first. Within bugs, anything labeled for the active `release/X.Y.Z` scope first. State the ordering rule you used so the user can override it.
- Note the total count and roughly how many checkpoints that means.

Format example:

```
## Open issues (7)

Review order (bugs first, then oldest):
  1. #102 [bug, enhancement]  Cargo missions still missing mission information   (3 comments, 12d)
  2. #98  [bug]               Config tab squishes under display scaling          (1 comment, 9d)
  3. #131 [enhancement]       Add a commodity price overlay                       (0 comments, 2d)
  ...
```

**CHECKPOINT: does this roster and order look right? Ready to start the per-issue review?** Wait for the user.

## 2. Per-issue review

Review one issue at a time, in the agreed order. **Stop at a CHECKPOINT after each issue.** For each:

1. **Gather full context.**
   - `gh issue view <N> --json number,title,body,labels,state,comments,author,createdAt,url`
   - If the body says it is synced from Discord (the `*Synced from Discord: ...*` header), note the source link; the real detail often lives in the thread, so flag when the report is thin.
   - Look for related PRs: `gh pr list --state all --search "<N> in:body"`. Note any open or merged PR that already addresses it.

2. **Locate the code.** Map the symptom to the layer and file using the root `CLAUDE.md` *Common Modification Points* table and the per-directory `CLAUDE.md` guides. Read the relevant code. This is a review: reason from the code and the report. Reproduce by inspection where you can; only run the app or a script when a quick check materially changes the verdict and the user is available to allow it.

3. **Assess** the issue against these dimensions:
   - **Clarity**: is the report actionable, or does it need more information (repro steps, version, screenshot, channel)?
   - **Validity**: is it a real bug, a sensible enhancement, a duplicate, or works-as-intended? For a bug, does the described behavior actually contradict the code's intent?
   - **Reproducibility**: can you reproduce it from the description or by reading the code path? Say what you checked.
   - **Root-cause hypothesis**: best guess at the cause, citing `file:line` where you can. Mark it as a hypothesis when you have not confirmed it.
   - **Scope and affected layer**: which layer and files a fix would touch (use the layer order from `/review_pr`). Small and contained, or cross-cutting?
   - **Severity / priority**: Critical / Major / Minor, calibrated as in `.claude/commands/standards_check.md`. For enhancements, weigh user impact against effort instead.
   - **Branching fit**: would a fix fit the active `release/X.Y.Z` scope? Per root `CLAUDE.md` -> *Version & Release*, a patch branch is bugfix-only; flag an enhancement that would need the next minor or major.

4. **Give the issue a disposition**, exactly one of:
   - **Fix now**: real, in scope, root cause understood well enough to start. Name the file(s) a fix would touch.
   - **Needs info**: cannot proceed without specifics from the reporter. Say exactly what to ask for.
   - **Duplicate of #NN**: point at the canonical issue.
   - **Won't fix / works as intended**: explain why, kindly.
   - **Defer**: real but out of scope for the active branch (backlog or next minor/major).

5. **Present the per-issue review.** Header is the linked issue (`[#N title](url)`). Plain language, no hedging. Lead with the disposition and severity, then the evidence (what you read, the root-cause hypothesis with `file:line`, the affected layer). If a PR already addresses it, say so and recommend closing or linking. Close with a one-line **next action**.

**CHECKPOINT: ready for the next issue?** Wait for the user. If this was the last issue, ask instead: *"Ready for the triage summary?"*

## 3. Triage summary

After every issue is reviewed, present a single prioritized table plus a recommended order of attack:

- **Table**: `#N`, disposition, severity, affected layer, one-line next action.
- **Grouping**: Fix now (by severity), then Needs info, Duplicate, Defer, Won't fix.
- **Suggested fix order** for the "Fix now" set, with a one-line rationale (severity, scope fit, dependency between issues).
- Call out any issue whose fix would not fit the active `release/X.Y.Z` scope.

**CHECKPOINT: pause and ask** what to do with the triage. Offer, and act only on explicit confirmation:

- Post a triage comment on one or more issues.
- Apply or change labels (e.g. `needs-info`, `duplicate`, `wontfix`).
- Close duplicates or works-as-intended issues (with a comment).
- Hand the top "Fix now" issue to `/begin_work` to start the fix.

**Do not post comments, change labels, or close any issue without explicit confirmation.**

## Tone

- Constructive and educational. Assume the reporter meant well, even when the report is thin.
- Explain the *why*, and link the relevant `CLAUDE.md` section when it documents a convention or a path.
- Be specific: cite `file:line`, name the affected layer, point at the canonical duplicate.
- Be honest about uncertainty. A root-cause hypothesis you have not confirmed is a hypothesis, not a verdict.
- Focus on the issue and the code, never the reporter.
