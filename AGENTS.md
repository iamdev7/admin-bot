# Repository Guidelines

## Project Structure & Module Organization
- Code layout (async PTB v22):
  - `bot/core/` (bootstrap, config via Pydantic, logging, i18n `t()` helpers)
  - `bot/infra/` (SQLite models, repositories, migrations, cache, rate limits)
  - `bot/features/` subpackages: `moderation/`, `welcome/`, `antispam/`, `rules/`, `automations/`, `admin_panel/`
- Entry point: `bot/main.py` (run with `python -m bot.main`).
- Locales: `locales/en.json`, `locales/ar.json`.
- Data: SQLite at `./data/bot.db` (WAL mode); seed scripts under `scripts/`.

## Build, Run & Development Commands
- Python 3.11+: `python -m venv .venv && source .venv/bin/activate`
- Install: `pip install -U pip && pip install -e .[dev]`
- Configure: `cp .env.example .env` and set `BOT_TOKEN`, `OWNER_IDS`, `DATABASE_URL=sqlite+aiosqlite:///./data/bot.db`, `DEFAULT_LANG=en`.
- Migrate DB: `python -m bot.infra.migrate` (creates tables, enables WAL/PRAGMAs).
- Run bot (polling): `python -m bot.main` (sets commands and `allowed_updates`).
- Tooling: `ruff check .`, `black .`, `mypy bot` (optional `uvloop` on *nix).

## Coding Style & Naming Conventions
- Strict type hints; small cohesive functions; prefer dataclasses where helpful.
- Indentation 4 spaces; Python 3.11 features allowed (pattern matching, `|` types).
- Naming: modules `snake_case.py`; classes `PascalCase`; functions/vars `snake_case`; constants `UPPER_SNAKE_CASE`.
- Keep `bot/core` side-effect light; push I/O to `bot/infra` and Telegram specifics to `bot/features/*`.

## Commit & Pull Request Guidelines
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `ci:`, `perf:`).
  - Example: `feat(moderation): add /purge with human durations`
- PRs: clear rationale, linked issues (e.g., `Fixes #42`), logs/screenshots when UI/UX changes (inline keyboards).
- Checklist: updated docs, schema/migration notes, `ruff`/`black`/`mypy` pass; keep scope focused (< ~400 LOC).
- Note: per project brief, no Docker, CI/CD, or tests are included by default.

## Security & Configuration Tips
- Do not commit secrets; use `.env` and document keys in `.env.example`.
- Restrict owner powers to `OWNER_IDS`; revalidate admin via `getChatMember` with short TTL cache.
- Maintain group/admin snapshots in DB; never rely on “list groups a user admins”.
- Validate and sanitize user-provided texts; localize all user-facing strings via `t()`.
