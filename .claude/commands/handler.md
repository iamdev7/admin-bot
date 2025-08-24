Add a PTB v22 handler/command.

Task: $ARGUMENTS

Spec:
- Filters: define `filters.*` expression
- Scope: group/private; admin/owner/public
- Replies: localized via `t()` (add keys to EN/AR)
- Logging: informative, no secrets

Steps:
1) Think and propose a short plan; list exact paths.
2) Implement handler in `bot/features/<area>/handlers.py`.
3) Register via `bot/features/<area>/__init__.py` or `bot/main.py`.
4) Update EN/AR locales for all user text.
5) Run `ruff`, `black`, `mypy`; provide manual test steps.

Acceptance:
- Command appears in scope, permission checks enforced, localized responses.

