# Prompt Playbook — Telegram Admin Bot (PTB v22, SQLite)

This playbook gives high‑signal, low‑ambiguity prompt templates tailored to this repository. Use them to get precise, production‑ready diffs that respect the project’s structure, conventions, and constraints.

## Core Principles (apply in every prompt)

- Context first: restate repo shape and constraints briefly so the assistant stays aligned.
- Minimal diffs: request exact file paths and focused changes via apply_patch.
- Plan before code: ask for a concise step plan; exactly one step “in progress”.
- Strict style: Python 3.11, type hints, small functions, follow naming and module boundaries.
- Separation of concerns: core config/logging/i18n in `bot/core`, DB in `bot/infra`, Telegram handlers in `bot/features/*`.
- i18n: all user‑facing text goes through `t(lang, key, **kwargs)`; update `bot/locales/en.json` and `bot/locales/ar.json`.
- DB changes: update models and repos, wire migrations in `bot/infra/migrate.py`; keep WAL/PRAGMAs.
- Handlers: async PTB v22 style; set correct filters, permissions, and allowed updates.
- Validation: run `ruff`, `black`, `mypy` (don’t add tests by default); provide run instructions.
- Security: no secrets in code; owner‑only/admin checks as needed; sanitize user inputs.

## Quick Context Snippet (paste into new tasks)

Project uses python‑telegram‑bot v22 (async) with SQLite via SQLAlchemy 2.0. Structure:
- `bot/core/` (config via Pydantic, logging, i18n `t()`, permissions, error handling)
- `bot/infra/` (engine, models, repos, migrate, settings)
- `bot/features/*` (moderation, welcome, antispam, rules, automations, admin_panel, topics, onboarding, verification, bot_admin)
- Entry: `python -m bot.main`; locales: `bot/locales/en.json`, `bot/locales/ar.json`.
- Tools: `ruff check .`, `black .`, `mypy bot`.
- Constraints: strict typing, i18n for all user text, minimal diffs, no Docker/CI/tests by default.

## Acceptance Checklist (ask the assistant to confirm)

- Follows repo layout and naming; keeps changes minimal and localized.
- All user‑visible strings localized; EN/AR updated consistently.
- Handlers are async PTB v22, properly registered, and permission‑checked.
- DB schema and repos updated together; migration path covered; WAL/PRAGMAs preserved.
- Code passes `ruff`, `black`, `mypy` and includes run notes or manual test steps.
- Security reviewed: owner/admin checks, sanitized inputs, safe error paths.

---

## Template: Feature Implementation

Use this to add a new capability (command, panel, rule, automation).

```
You are a senior Python engineer working in this repo (PTB v22 async, SQLite).
Task: <clear, one‑paragraph objective>

Context:
- Entry: `bot/main.py`; features live under `bot/features/<area>/`.
- i18n via `t(lang, key, **kwargs)`; update `bot/locales/en.json` and `ar.json`.
- DB via SQLAlchemy 2.0 async; models in `bot/infra/models.py`, repos in `bot/infra/repos.py`, migration in `bot/infra/migrate.py`.
- Style: strict type hints, small cohesive functions, keep side‑effects in `infra`/`features`.

Requirements:
- Handlers: <list commands/callbacks/filters to add>.
- Permissions: <owner/admin/public>; revalidate via `getChatMember` if needed.
- Persistence: <what to store and where>.
- i18n keys: <list of new keys>.
- Logging: use `bot/core/logging_config.py` conventions.

Deliverables:
- Exact file diffs via apply_patch.
- Localized strings (EN + AR) for all user messages.
- Update any registrations in `bot/main.py` or feature `register(...)` as needed.

Plan first, then code. After implementation, run and report:
- `ruff check .`, `black .`, `mypy bot`
- Manual test notes: <how to trigger/verify>

Acceptance criteria:
- <bullet list of verifiable outcomes>
```

## Template: Bugfix Deep Dive

```
Goal: Fix <bug summary>. Provide a short plan, then narrow, patch, and validate.

Given:
- Symptom/logs: <paste or summarize>
- Suspected areas: <files/functions>
- Constraints: minimal diff; keep behavior stable elsewhere; i18n strings unchanged unless needed.

Do:
1) Identify root cause (quote code lines/paths).
2) Propose minimal fix with reasoning.
3) Patch via apply_patch with precise file paths.
4) Run `ruff`, `black`, `mypy` and note any follow‑ups.
5) Provide manual verification steps.

Acceptance:
- Root cause explained; fix localized; no regressions in adjacent features.
```

## Template: Refactor (No Behavior Change)

```
Objective: Improve <module/area> readability/structure without changing behavior.
Scope: <files>; keep public surfaces and i18n keys intact.

Steps:
- Outline small, verifiable refactors (rename internals, extract functions, docstrings, types).
- Patch in small diffs; run linters and type checks.
- Provide before/after snippets for key functions.

Acceptance: identical runtime behavior; cleaner code; `ruff`/`black`/`mypy` pass.
```

## Template: DB Migration/Schema Change

```
Change: <add/modify field/table> to support <feature>.

Update:
- `bot/infra/models.py`: schema and types
- `bot/infra/repos.py`: CRUD and queries
- `bot/infra/migrate.py`: create/ensure changes; keep WAL/foreign keys
- Data backfill/compat if needed

Include:
- Diffs for models, repos, migrate
- Any feature code touching the new data
- Manual migration/testing steps

Acceptance: app boots, migration idempotent, new queries work, `mypy` clean.
```

## Template: Handler/Command (PTB v22)

```
Task: Add `/command` (or callback) for <purpose>.

Handler spec:
- Filter(s): <filters.* expression>
- Permissions: <admin/owner/public>; revalidate admin on action
- Replies: localized via `t()`; ephemeral where appropriate
- Logging: meaningful, no secrets

Deliverables: new/updated handler in `bot/features/<area>/handlers.py`, register in `register(app)`.
Acceptance: command appears in scope (if needed), works in manual test.
```

## Template: Admin Panel (Inline UI)

```
Feature: Add/extend admin panel page/tab for <settings>.

Include:
- Navigation wiring in `bot/features/admin_panel/navigation.py`
- Page handler & callbacks in `bot/features/admin_panel/handlers.py`
- Callback data shape; state persistence if needed
- i18n texts for labels/titles/messages
- Any repos/settings touched

Acceptance: panel opens, controls update settings, confirmations localized.
```

## Template: i18n Update

```
Add texts for <feature>. Update:
- `bot/locales/en.json`
- `bot/locales/ar.json`

Ensure all new user strings use `t(lang, key, **kwargs)` and avoid hard‑coded text in handlers.
```

## Template: Logging & Error Handling

```
Add structured logging in <files>. Use `get_logger(__name__)` or module logger, INFO for normal, WARNING for recoverable issues, ERROR with context. Ensure user‑facing errors use `t(lang, "errors.generic")`. Add/adjust ignored errors in `bot/core/error_handler.py` if appropriate.
```

---

## Example (Filled): Add /softban command

```
Task: Add `/softban` to remove a user’s recent messages (N=50) and kick, allowing immediate rejoin.

Requirements:
- Command in groups; admin‑only; reply‑targeted or `/softban @user [N]`.
- Log to `AuditLog` with actor/target/count.
- i18n: `mod.softban.ok`, `mod.softban.usage`, `mod.softban.no_target`.

Deliverables:
- `bot/features/moderation/handlers.py`: implement handler and register.
- `bot/main.py` or `features/moderation/__init__.py`: ensure registration.
- Locales EN/AR updated.

Acceptance:
- Works via reply and username; defaults N=50 if omitted; localized confirmations; ruff/black/mypy clean.
```

## Example (Filled): Add scheduled announcement preset

```
Task: Admin panel “Automations” gains a preset to post a weekly announcement.

Requirements:
- New callback to create Job(kind="announce", payload={text, chat_id}, run_at=next weekday 10:00, interval=7d).
- i18n keys for titles/buttons/confirmations.
- Show in list and allow cancel.

Deliverables:
- Admin panel handlers/navigation; `JobsRepo.add`, `JobsRepo.list_by_group` usage.
- Locales updated.

Acceptance: visible in panel, job saved, message posts on schedule.
```

---

## Handy Commands

- Lint: `ruff check .`
- Format: `black .`
- Types: `mypy bot`
- Run (polling): `python -m bot.main`

## Do/Don’t

- Do: keep diffs surgical; maintain i18n; use repos; validate permissions.
- Don’t: add Docker/CI; hard‑code secrets; bypass `t()`; introduce tests unless requested.

