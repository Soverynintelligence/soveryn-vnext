# Rules for any model working in this repo

- Never commit to or push `main` without Jon's explicit OK in the current session. Work on a branch and ask before pushing.
- Never sweep unrelated local/uncommitted edits into a commit. Stage only the files for the task at hand (`git add <paths>`, never `git add -A`/`.`), and list what you staged before committing.
- Never force-push, rewrite history, or skip hooks.
- Don't start, stop, or re-seat model servers on the Sparks (:8001, :8888); that's owner-gated.
