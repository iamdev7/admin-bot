Run linters and fix issues iteratively.

Steps:
1) Run `ruff check .` and summarize violations.
2) Fix the highest-value issues first; avoid mass refactors.
3) Run `black .` to format touched files only if needed.
4) Run `mypy bot`; add/adjust type hints minimally.
5) Repeat until clean or only ignorable warnings remain.
6) Summarize remaining warnings and suggested follow-ups.

Notes:
- Keep diffs small. Don’t change behavior.
- Don’t add tools or configs beyond what’s present.

