Fix a bug in this repo.

Bug summary: $ARGUMENTS

Do:
1) Think and write a short plan; list suspected files/functions.
2) Identify the root cause quoting relevant code and paths.
3) Propose a minimal fix with reasoning.
4) Edit files with surgical diffs. Keep behavior stable elsewhere.
5) Run: `ruff check .`, `black .`, `mypy bot`
6) Provide manual verification steps.

Constraints:
- Don’t change i18n keys unless necessary. If changed, update EN/AR consistently.
- Avoid unrelated refactors.

Acceptance:
- Root cause explained; fix localized; no regressions observed in adjacent features.

