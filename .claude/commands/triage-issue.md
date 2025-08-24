Analyze and triage a GitHub issue using `gh`.

Issue reference: $ARGUMENTS

Steps:
1) `gh issue view $ARGUMENTS --json number,title,body,labels,author,comments` and summarize.
2) Identify suspected files/functions; propose a plan to investigate/fix.
3) If a fix is small and safe, implement surgical diffs.
4) Otherwise, create a checklist in `docs/TODO.md` with steps and owners (optional).
5) Run `ruff`, `black`, `mypy` and provide manual test steps.

Notes:
- Only use `gh` if installed; otherwise, read linked files manually.

