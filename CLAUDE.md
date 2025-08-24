# Claude Code Guide for This Repo

This repository is a Telegram Admin Bot built on python-telegram-bot v22 (async) with SQLite (SQLAlchemy 2.0 async). These notes help Claude Code work effectively here, following Anthropic’s best practices.

## Project Context
- Entry: `python -m bot.main`
- Structure:
  - `bot/core/` — config (Pydantic), logging, i18n `t()`, permissions, error handling
  - `bot/infra/` — DB engine, models, repos, migrations
  - `bot/features/*` — Telegram handlers per feature (moderation, welcome, antispam, rules, automations, admin_panel, topics, onboarding, verification, bot_admin)
  - Locales: `bot/locales/en.json`, `bot/locales/ar.json`
- Tooling: `ruff check .`, `black .`, `mypy bot`
- Run DB migrate: `python -m bot.infra.migrate`

## Working Style (Important)
- Think → Plan → Code → Verify. First, propose a short plan. Don’t edit files until the plan is confirmed.
- Keep diffs surgical and localized. Respect module boundaries and naming conventions.
- All user-facing text must use `t(lang, key, **kwargs)` with EN/AR updates.
- Prefer small, typed functions; Python 3.11 features are OK.
- Separate concerns: core stays side-effect-light; DB in `infra`; Telegram specifics in `features`.
- Validate permissions (owner/admin) and sanitize inputs.

## Useful Commands
- Lint: `ruff check .`
- Format: `black .`
- Types: `mypy bot`
- Migrate: `python -m bot.infra.migrate`
- Run bot (polling): `python -m bot.main`

## Permissions (Claude Code)
Use `/permissions` to streamline approvals for safe operations:
- Always allow: `Edit`
- Consider allowing: `Bash(ruff check:*)`, `Bash(black:*)`, `Bash(mypy:*)`, `Bash(python -m bot.infra.migrate:*)`, `Bash(python -m bot.main:*)`
- Git is optional: `Bash(git commit:*)`, `Bash(git checkout:*)` if you want Claude to manage branches/commits.

## Common Workflows
1) Explore and plan
   - Ask to read specific files (chunked, ≤250 lines each) and summarize.
   - Propose a concise plan with exactly one step in progress.
2) Implement
   - Edit only necessary files. Update EN/AR locales for any new strings.
3) Verify and iterate
   - Run `ruff`, `black`, `mypy` with minimal reruns. Provide manual test steps.
4) Reset context between tasks
   - Use `/clear` when switching topics to keep prompts focused.

## Scratchpads and Checklists
For larger tasks, create a Markdown checklist (e.g., `docs/TODO.md`) and have Claude check off items as it proceeds.

## Optional Tools
- Install `gh` CLI if you want Claude to interact with GitHub (issues/PRs).
- MCP servers can be added via `.mcp.json` if needed.

## i18n Notes
- Add keys to both `bot/locales/en.json` and `bot/locales/ar.json`.
- Never hard-code user-visible strings in handlers.

## Acceptance Checklist (per change)
- Minimal, focused diffs; correct files/paths.
- Async PTB v22 handlers; permissions validated.
- i18n keys added/used; EN/AR in sync.
- DB changes (if any) reflected in models, repos, and migration.
- `ruff`/`black`/`mypy` pass; include run notes.

