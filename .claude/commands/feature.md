You are working in this repo (PTB v22 async, SQLite). Implement a feature:

Objective: $ARGUMENTS

Follow this workflow:
1) Think and propose a short plan (steps, files to touch). Do not edit yet.
2) Confirm i18n keys to add and where they’ll be used.
3) Implement minimal diffs in:
   - Handlers under `bot/features/<area>/handlers.py` (async PTB v22)
   - Registration via `bot/features/<area>/__init__.py` or `bot/main.py`
   - Persistence in `bot/infra/repos.py` / `bot/infra/models.py` if needed
   - Locales: `bot/locales/en.json` and `bot/locales/ar.json`
4) Run and report: `ruff check .`, `black .`, `mypy bot`
5) Provide manual test instructions.

Constraints:
- Strict typing, small cohesive functions
- Use `t(lang, key, **kwargs)` for all user strings
- Validate admin/owner permissions as appropriate

Acceptance:
- Handlers registered, localized texts added, and feature verifiable by manual steps.

