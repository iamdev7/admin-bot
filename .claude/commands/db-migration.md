Introduce a schema change or migration.

Change: $ARGUMENTS

Plan:
1) Specify tables/fields to add/modify and why.
2) Update `bot/infra/models.py` (types, defaults, indices if needed).
3) Update `bot/infra/repos.py` (CRUD, queries) and any call sites.
4) Ensure `bot/infra/migrate.py` remains idempotent and keeps WAL/foreign keys.
5) If needed, backfill/compat logic.
6) Run: `ruff check .`, `black .`, `mypy bot`; boot the app and migrate.
7) Manual test steps.

Constraints:
- Minimal, focused changes; keep existing behavior unchanged unless required.

Acceptance:
- App boots, migration idempotent, new queries behave correctly, types clean.

