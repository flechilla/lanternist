---
name: pr
description: Open a pull request for the current work. Checks the branch, runs every gate and a self-review, commits in the project's style, pushes, fills the PR template with what was actually run, and watches CI until it is green.
argument-hint: "[PR title]"
disable-model-invocation: true
---

# Open a pull request

The user invoked this, which authorizes pushing this branch and opening one PR. It doesn't authorize
merging, force-pushing or touching other branches.

1. **Branch.** Run `git status` and `git branch --show-current`. If you're on `main`, create
   `feat/…`, `fix/…` or `chore/…` named after the change. If the working tree holds unrelated
   changes, stop and ask which belong in this PR.
2. **Gates.** Run `scripts/check`. Everything must pass before you go on; use `/check` to fix
   failures.
3. **Review.** Run `/self-review`. Fix every **must fix**. Fix each **should fix** or say in the PR
   why not. Re-run `scripts/check` if anything changed.
4. **Commits.** Match `git log --oneline -10`: a subject that says what changed, such as `M2 Phase B:
   writer on OpenRouter`, and a body that says why. Put a mechanical change (reformat, rename, moved
   file) in its own commit. Never commit `lanternist.toml`, secrets, `web/dist` or
   `src/lanternist/api/static`.
5. **Push.** `git push -u origin HEAD`.
6. **Body.** Fill `.github/pull_request_template.md`:
   - *What and why*: one paragraph, plus the plan section it implements.
   - *How it was checked*: the commands you actually ran and what they showed. Include
     `pytest -m live` or `-m gpu` only if they ran, with what the live run cost.
   - *Checklist*: tick only what's true. For an item that doesn't apply, leave it unticked and write
     "n/a: reason" after it.
   Write it to a temp file.
7. **Open.** `gh pr create --base main --title "<title>" --body-file <file>`. Use `$ARGUMENTS` as the
   title if one was given; otherwise use the main commit's subject.
8. **CI.** `gh pr checks --watch`. If a check fails, read its log (`gh run view --log-failed`), fix,
   commit, push and watch again.
9. **Report** the PR URL, the CI result, and anything left for the reviewer.
