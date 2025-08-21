# Telegram Admin Bot (async, PTB v22, SQLite)

Modular, extensible Telegram group‑management bot using python‑telegram‑bot v22 (async) and SQLite via SQLAlchemy 2.0 (aiosqlite). English and Arabic supported.

## Quick Start
- Python 3.11+
- Create venv and install:
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -U pip && pip install -e .[dev]`
- Configure environment:
  - `cp .env.example .env` and set `BOT_TOKEN`, `OWNER_IDS`, `DATABASE_URL`, `DEFAULT_LANG`
- Initialize DB: `python -m bot.infra.migrate`
- (Optional) Seed owners: `python scripts/seed.py`
- Run (polling): `python -m bot.main`

## Full Setup & Run
1) Create the bot with @BotFather → `/newbot` → copy the token.
2) Disable privacy: @BotFather → `/setprivacy` → choose the bot → `Disable` (needed to moderate non‑command messages).
3) Promote the bot to admin in target groups with permissions: Delete messages, Ban users, Restrict members, Manage chat, Pin messages, Manage topics.
4) Create and activate the virtualenv, install deps, and configure `.env` as shown above.
5) Start the bot: `python -m bot.main`. First run creates `data/bot.db` automatically (WAL enabled).
6) Start a private chat with the bot and send `/panel` to manage settings.

## Structure
- `bot/core/`: config, logging, permissions, i18n, ephemeral replies
- `bot/infra/`: engine, models, migration, repos, settings
- `bot/features/`: moderation, antispam, rules, onboarding, verification, welcome, admin_panel, automations, topics
- `bot/locales/`: packaged translations (EN/AR)

## Commands
- Public: `/start`, `/help`, `/rules`
- Admin (groups): `/settings`, `/setrules <text>`, `/joinapprove on|off`
- Moderation: `/warn`, `/mute <dur>`, `/unmute`, `/ban <dur>`, `/unban`, `/unwarn`, `/purge <N>`
- Forums: `/topic_close`, `/topic_open`, `/topic_rename <name>`, `/topic_pin` (reply)
- Content rules (CLI alternative): `/addrule <word|regex> <delete|warn|mute|ban> <pattern>`, `/listrules`, `/delrule <id>`

## Admin Panel (DM → `/panel`)
- Tabs and key actions:
  - Anti‑Spam: presets (window, threshold, mute/ban durations).
  - Rules: manage content rules (with reply action); Links Policy (allowlist, per‑type actions, Night Mode); Forward & Media Locks.
  - Welcome: toggle + template with `{first_name}`, `{group_title}`.
  - Language: per‑group EN/AR override.
  - Onboarding: auto‑approve toggle; require rules acceptance (DM accept before join); Captcha (button/math, timeout).
  - Automations: announcements (once/repeat), rotate pin, timed unmute/unban.
  - Moderation: warn‑limit, delete‑offense toggle, ephemeral replies (off/10s/30s), Recent Violators with quick actions.
  - Audit: recent moderation events (paged).

## Service (optional)
Run as a systemd service on Linux (edit paths):
```ini
[Unit]
Description=Telegram Admin Bot
After=network.target

[Service]
WorkingDirectory=/path/to/admin-bot
ExecStart=/path/to/admin-bot/.venv/bin/python -m bot.main
Restart=on-failure
User=youruser
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
Then: `systemctl daemon-reload && systemctl enable --now telegram-admin-bot`.

Notes
- No Docker/CI/tests included by design. Use `ruff`, `black`, `mypy` locally.
- Allowed updates: message, callback_query, chat_member, chat_join_request.

## Troubleshooting
- Bot doesn’t react in groups: ensure privacy is disabled and the bot is admin with required rights.
- DM “rules acceptance” not delivered: user must start the bot in private first (Telegram restriction).
- Cannot delete/mute/ban: grant the bot Delete/Restrict/Ban/Manage permissions.
- Install errors on `pip install -e .`: activate the venv and run in project root; packaging includes only `bot/*` and packaged locales.
