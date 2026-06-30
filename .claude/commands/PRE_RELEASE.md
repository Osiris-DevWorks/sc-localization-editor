---
description: Pre-release sanity check before merging release/X.Y.Z to main — runs quality checks, security review, and a contributor + tester acknowledgement audit
---

# /pre_release

Run before merging the active `release/X.Y.Z` integration branch to `main`. This is the final gate before the release ships — it confirms code quality, doc currency, test coverage, that every code contributor is acknowledged in the project's in-app About and the README, and that frequent issue reporters are recognized as testers.

Work through every step in order. After each step, stop at the **CHECKPOINT** and wait for the user before continuing.

## Preflight

- Confirm the current branch is `release/X.Y.Z`. If not, abort and ask the user to switch.
- Confirm working tree is clean (`git status --porcelain`). If dirty, abort.
- Confirm `VERSION.TXT` matches `X.Y.Z`. If mismatched, surface the discrepancy and ask the user before proceeding.

**CHECKPOINT — preflight confirms release branch is ready for audit. Proceed?** Wait for the user.

## 1. Test coverage check

Follow the procedure in `.claude/commands/test_coverage_check.md`. Present findings grouped by severity (Critical / Major / Minor) and end with the verdict line.

**CHECKPOINT — ready for the next check?** Wait for the user.

## 2. UI / docs / tutorial sync check

Follow the procedure in `.claude/commands/docs_sync_check.md`. Present findings grouped by severity and end with the verdict line.

**CHECKPOINT — ready for the next check?** Wait for the user.

## 3. Standards spot-check

Follow the procedure in `.claude/commands/standards_check.md`. Present findings grouped by severity and end with the verdict line.

**CHECKPOINT — ready for the next check?** Wait for the user.

## 4. Security review

Run `/security-review` on the pending changes. Present findings grouped by severity and end with the verdict line.

**CHECKPOINT — ready for the contributor audit?** Wait for the user.

## 5. Contributor & tester acknowledgement audit

Verify every code contributor is acknowledged in `docs/ABOUT.md` and `README.md`, and surface frequent issue reporters who should be recognized as testers.

### 5a. Build the contributor list

Pull every author who has committed code:

```bash
git log --format='%aN|%aE' --no-merges | sort -u
```

Also pull GitHub-known contributors (gives the linkable login):

```bash
gh api "repos/Osiris-DevWorks/smart-citizen/contributors" --paginate --jq '.[] | {login: .login, contributions: .contributions}'
```

**Filter out**:
- The repo owner `Osiris-DevWorks` / `Osiris DevWorks` — already credited as the maintainer.
- AI co-author trailers (`Claude`, `noreply@anthropic.com`, anything tagged `Co-Authored-By: Claude*`) — these are not collaborators.
- Bot accounts (`dependabot[bot]`, `github-actions[bot]`, `*[bot]`, etc.).
- Anonymous commits with no name or only an email and no associated GitHub login.

Normalize: when a person has committed under multiple display-name/email combinations, merge them into one entry. If unsure, surface the duplicates and let the user decide.

### 5b. Pull the current acknowledgement set

Read both:

- `docs/ABOUT.md` — the in-app About panel content. Find the **Contributors** section, the **Acknowledgements** section (the tester list lives here — look for headers containing "Acknowledg", "Credits", "Thanks"), and any **Supporters** subsection.
- `README.md` — the `## Contributors` section, the `## Acknowledgments` section (testers are listed here too), and any `### Supporters` subsection.

Build two normalized sets: **acknowledged contributors** (the Contributors list) and **acknowledged testers** (the names in the Acknowledgements/testers list). Match against the people lists using both display name and GitHub login where known.

### 5c. Categorize each missing contributor

For every contributor not currently acknowledged in **both** files (ABOUT.md and README.md):

- Pull their commit count: `git log --author='<email>' --no-merges --oneline | wc -l`
- Pull a sample of files they touched: `git log --author='<email>' --no-merges --name-only --pretty=format: | sort -u | head -10`
- Categorize:
  - **Substantial code contributor**: ≥3 commits OR touched non-trivial source files (anything under `src/`, `scripts/`, or `tests/`).
  - **Drive-by fixer**: 1–2 commits, only trivial files (README typo, comment fix, whitespace).

### 5d. Tester candidates from issue reporters

Frequent issue reporters who aren't developers are the people testing the app in the wild. Surface them so they can be acknowledged as testers (and invited to the tester group).

Count how many issues each person has reported (issues only — `gh issue list` excludes PRs by default):

```bash
gh issue list --state all --limit 1000 --json number,author --jq '.[].author.login' | sort | uniq -c | sort -rn
```

**Attribution wrinkle — read before trusting the counts.** Many issues are mirrored from Discord under a single bot author (e.g. `discohub-discord-bot` / an `app/*` login). For those, the real reporter is named in the issue body, not the `author` field (e.g. "**Narull** ([Discord](...))"). Where the author is a sync bot, read the bodies and attribute each report to the human named inside, counting by that human. Pull bodies with:

```bash
gh issue list --state all --limit 1000 --json number,author,title,body --jq '.[] | select(.author.login | test("bot|^app/")) | "\(.number)\t\(.body[0:120])"'
```

Flag every person with **3 or more** reported issues as a **candidate tester**, then filter out:
- The repo owner / maintainer (`Osiris-DevWorks`).
- Bot accounts themselves (`*[bot]`, `app/*`) — they are the transport, not a reporter.
- **Anyone who is also a code contributor** (appears in the 5a contributor list, by login or known identity). Developers are credited under **Contributors**, not Testers — never list the same person as both.
- Anyone already in the tester acknowledgement set from 5b.

If a report can't be confidently attributed to a named human, list it as unattributed rather than guessing a count.

### 5e. Report

Group missing **contributors** by significance:

```
**Missing — substantial contributors** (suggest adding):
  Jane Doe (@janedoe) — 12 commits — touched src/gui/, src/utils/
  John Smith (@johnsmith) — 8 commits — touched scripts/

**Missing — drive-by fixers** (consider adding, or skip):
  Anon Contributor — 1 commit — typo fix in README.md

**Acknowledged in ABOUT only** (also needs README): <list if any>
**Acknowledged in README only** (also needs ABOUT): <list if any>

**Already acknowledged in both** (sanity-check): N contributors covered.
```

Then list **tester candidates** (≥3 issues, not developers, not already credited):

```
**Tester candidates** (≥3 reported issues, not code contributors):
  Narull — 5 issues reported (via Discord sync)
  SomeReporter (@somereporter) — 3 issues reported

**Excluded as developers** (reported 3+ but credited under Contributors): <list if any>
```

End with a one-line **verdict** (driven by the contributor side; tester candidates are advisory and never block a release):

- **Clean** — every substantial contributor is acknowledged in both files.
- **Minor issues** — only drive-by fixers missing, or only single-file drift (acknowledged in one but not the other).
- **Needs attention** — substantial contributors missing.

Add a second line if there are tester candidates: *"Tester candidates to consider: N"* (advisory only).

**CHECKPOINT — pause and ask the user whether to draft additions to `docs/ABOUT.md` and `README.md`** (mirrored in both so they stay in sync): contributor names into the **Contributors** section, and any approved tester candidates into the **Acknowledgements** tester list. Do not edit either file without confirmation.

## Final summary

After all five steps complete, give a one-line overall verdict for release readiness — the worst-case verdict across the five checks. List any remaining Critical/Major findings the user needs to address before the `release/X.Y.Z` → `main` merge.

Reminder: this command does not ship the release. Merging `release/X.Y.Z` to `main`, tagging, building the installer, and creating the GitHub release are separate steps documented in root `CLAUDE.md` → *Version & Release → Release checklist*.
