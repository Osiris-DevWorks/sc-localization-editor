---
description: Ship the active release/X.Y.Z — build the installer, merge to main, tag, push, and publish the GitHub release. Run after /pre_release passes.
---

# /ship_release

Walk the release-ship sequence with checkpoints between each step. Several steps are destructive (merge to `main`, tag, push) or have external side effects (publish GitHub release) — confirm before each.

Run **after** `/pre_release` returns a clean verdict. This command performs the merge-to-`main` handoff, builds the installer, publishes the GitHub release, and offers to open the next integration branch.

Work through every step in order. After each step, stop at the **CHECKPOINT** and wait for the user before continuing.

## Preflight

**This command ships whichever `release/X.Y.Z` branch the user is currently on** — the branch is the input. If multiple release branches exist, the user is responsible for being on the right one before invoking. Don't try to disambiguate.

Stop on the first failure.

- **On a release branch**: `git branch --show-current` must match `release/X\.Y\.Z`. Extract `X.Y.Z` for use below — this is the version we're shipping. Abort otherwise: *"Switch to the release branch you want to ship before running /ship_release."*
- **Surface other open release branches** (advisory): list any other `release/*` branches that exist locally or on origin. If found, print: *"Other release branches exist: <list>. Shipping `release/X.Y.Z` based on current branch — confirm this is the one you mean."* Wait for explicit confirmation before continuing the preflight.
- **Clean working tree**: `git status --porcelain` must be empty. Abort and list offending files otherwise.
- **VERSION.TXT matches branch**: read `VERSION.TXT`, strip whitespace, confirm it equals `X.Y.Z`. Abort with the mismatch otherwise.
- **Up to date with origin** (best-effort): `git fetch origin release/X.Y.Z`; if `git rev-list --count release/X.Y.Z..origin/release/X.Y.Z` > 0, abort: *"Local release branch is behind origin. Pull before shipping."* Skip silently if fetch fails (offline).
- **Pre-release was run recently** (advisory only): grep recent shell history or commit log for `/pre_release`; if no signal, remind the user: *"Heads-up: `/pre_release` doesn't appear to have run on this branch in the recent session. The ship sequence assumes it passed. Continue?"* Don't block.

**CHECKPOINT — preflight passes. Ready to build the installer for `vX.Y.Z`?** Wait for the user.

## 1. Build the installer locally (for smoke-testing only)

**The distributed installer is built by `.github/workflows/release.yml` on tag push, not by this command.** This local build exists only so the user can install and smoke-test the binary *before* triggering the public release. Do not attach the local artifact to a GitHub release — that races with the workflow.

### 1a. PyInstaller onedir build

```bash
.venv/Scripts/python.exe scripts/build/build_exe.py
```

Run from the repo root. Output lands in `dist/SmartCitizen-vX.Y.Z/`. If the build fails, abort and surface the error.

### 1b. Inno Setup installer

Inno Setup is per-user; invoke via PowerShell with the full ISCC path:

```bash
powershell -NoProfile -Command "& 'C:\Users\<USERNAME>\AppData\Local\Programs\Inno Setup 6\ISCC.exe' installer.iss"
```

Output: `dist/SmartCitizen-X.Y.Z-Setup.exe`. If ISCC isn't at that path, ask the user where it's installed.

**CHECKPOINT — installer built at `dist/SmartCitizen-X.Y.Z-Setup.exe` (N MB). Install and smoke-test it before merging to main.** Wait for the user. Do not proceed without explicit go.

## 2. Confirm release notes exist (pre-merge)

The `release.yml` workflow reads `docs/X.Y.Z-RELEASE-NOTES.md` (or root fallback) when publishing — confirm the file exists before merging so the published release isn't auto-generated.

Look in this order:
1. `docs/X.Y.Z-RELEASE-NOTES.md` (post-1.4.1 convention)
2. `X.Y.Z-RELEASE-NOTES.md` at repo root (legacy)

If neither exists, ask the user whether to draft one now or proceed with the workflow's auto-generated notes. Don't fabricate notes.

If notes exist, verify the SAC (Smart App Control) banner is present at the top per project memory. If missing, surface that and ask whether to add it.

**CHECKPOINT — release notes confirmed. Ready to merge `release/X.Y.Z` into `main`?** Wait for the user.

## 3. Merge release branch to main (this triggers the release workflow)

The push to `main` triggers `.github/workflows/release.yml`, which:
- Reads `VERSION.TXT`, derives `vX.Y.Z`, auto-tags the merge commit
- Runs tests, builds installer + portable zip, publishes the GitHub release
- Posts the Discord notification

So **the push IS the ship**. Confirm each git command in this section.

### 3a. Update main locally

```bash
git checkout main
git pull origin main
```

If the pull produces a merge (main diverged unexpectedly), surface that and ask — do not continue automatically.

### 3b. Merge the release branch

```bash
git merge --no-ff release/X.Y.Z -m "Merge release/X.Y.Z into main"
```

`--no-ff` preserves the release branch's history as a discrete merge commit. On merge conflicts, abort and ask the user to resolve manually.

### 3c. Push main

```bash
git push origin main
```

This triggers `release.yml`. The workflow auto-creates and pushes `vX.Y.Z` — no manual `git tag` needed.

**CHECKPOINT — `main` pushed. The release workflow is now running. Watch it at:** `gh run watch` or the Actions tab. Wait for the user to confirm the workflow completed successfully (installer + portable zip attached, Discord notification posted).

## 4. Close Resolved Issues

Review the open issues and close any with a resolution comment if they were fixed in this release. Present a table of issues that were closed and why.

**CHECKPOINT — `issues` closed. Okay to proceed to the next step, or do you want to re-open any of these issues?

## 5. Open the next integration branch

Offer to run `/start_release patch` to open the next bug-fix-scoped branch immediately. Most ships are followed by a patch branch as the new integration target. If the user wants `minor` or `major` instead, defer to them.

Ask: *"Open the next branch now? `patch` is the typical default — gives you `release/X.Y.(Z+1)` for the next round of bug fixes. Reply `patch`, `minor`, `major`, or `skip`."*

On `skip`, just report that the release is shipped and remind the user the next integration target needs to exist before any new work lands.

On any bump arg, defer to `/start_release` with that arg.

## Final report

Print:
- `Shipped vX.Y.Z`
- `Installer: dist/SmartCitizen-X.Y.Z-Setup.exe (<size>)`
- `Release URL: <gh release view url>`
- `Next integration branch: release/X.Y.(Z+1)` (if opened) or `(none yet — open one before starting new work)`
- Reminder: smoke-test the published installer download once GitHub finishes processing.

## Notes

- This command's destructive step is the **push to main**. That push triggers `release.yml`, which builds and publishes the canonical installer + portable zip. There is no `gh release create` invocation in this command — the workflow owns publishing.
- Never combine the merge and push into a single non-interactive run. The user is the gate.
- The local installer build (step 1) is for the user's pre-merge smoke test only. Do NOT attach it to a GitHub release manually; that races with the workflow.
- Tester pre-release installers (`installer-preview.yml`) are a separate flow — they produce throwaway artifacts off PR branches; this command produces the canonical release via `release.yml`.
