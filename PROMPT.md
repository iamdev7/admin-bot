

**MASTER PROMPT — Build a Production-Grade, Extensible Telegram Group-Management Bot (python-telegram-bot, SQLite)**

You are a **senior Python engineer**. Generate a **modular, scalable Telegram group-management bot** using **python-telegram-bot (latest stable, async, v22.x)**. Target **Python 3.11+**. **Do not include Docker, CI/CD, or tests.** Database is **SQLite** via **SQLAlchemy 2.0 (async, aiosqlite)**.

### Technical Foundations

* Use **`Application` / `ApplicationBuilder`** with full **asyncio** style handlers. Organize by features:

  * `bot/core/` (bootstrap, config, logging, i18n, permissions, errors)
  * `bot/infra/` (db models, repos, migrations, cache, rate limits)
  * `bot/features/moderation/`, `welcome/`, `antispam/`, `rules/`, `automations/`, `admin_panel/`
* Strict type hints; dataclasses where helpful. Keep functions small & cohesive.
* **Dependencies** (in `pyproject.toml`):

  * `python-telegram-bot[callback-data,job-queue,rate-limiter]>=22`
  * `SQLAlchemy>=2`, `aiosqlite`, `python-dotenv`, `pydantic` (for settings), `uvloop` (optional on \*nix)
* **Config via `.env`**:

  * `BOT_TOKEN=...`
  * `OWNER_IDS=123456789,987654321`
  * `DATABASE_URL=sqlite+aiosqlite:///./data/bot.db`
  * `DEFAULT_LANG=en`
* **Internationalization**:

  * `locales/en.json`, `locales/ar.json`; helper `t(lang, key, **kwargs)`.
  * Auto-pick from `update.effective_user.language_code`, allow per-group override.
* **Run**: polling via `python -m bot.main`.

### Telegram & Permissions (must-haves)

* Register handlers for: `message`, `callback_query`, **`chat_member`**, **`chat_join_request`**. Set `allowed_updates` accordingly.
* Use **`filters`** for message routing (e.g., `filters.TEXT & ~filters.COMMAND`).
* All privileged actions require **admin** rights in that group:

  * Decorator `@require_admin` revalidates via `getChatMember` (with short TTL cache).
  * Maintain an **admin snapshot** table kept in sync via **`ChatMemberHandler`** events (promote/demote/left).
* **Owner override**: any user ID in `OWNER_IDS` can manage globally.
* **Important note (design)**: Telegram does **not** expose “list all groups a user admins”. Maintain your own registry of groups where the bot is present and where a user is admin; use it to power the private control panel.

### Data Model (SQLite, SQLAlchemy 2.0 async)

Create tables & indices with migrations and WAL mode:

* `groups(id BIGINT PK, title TEXT, username TEXT, type TEXT, language TEXT, created_at DATETIME)`
* `group_settings(id INTEGER PK, group_id BIGINT FK, key TEXT, value JSON, updated_at DATETIME, UNIQUE(group_id,key))`
* `group_admins(group_id BIGINT, user_id BIGINT, status TEXT, rights JSON, updated_at DATETIME, PRIMARY KEY(group_id,user_id))`
* `users(id BIGINT PK, username TEXT, first_name TEXT, last_name TEXT, language TEXT, seen_at DATETIME)`
* `warns(id INTEGER PK, group_id BIGINT, user_id BIGINT, reason TEXT, expires_at DATETIME, created_by BIGINT)`
* `mutes(id INTEGER PK, group_id BIGINT, user_id BIGINT, reason TEXT, until DATETIME, created_by BIGINT)`
* `bans(id INTEGER PK, group_id BIGINT, user_id BIGINT, reason TEXT, until DATETIME, created_by BIGINT)`
* `filters(id INTEGER PK, group_id BIGINT, type TEXT, pattern TEXT, action TEXT, added_by BIGINT, created_at DATETIME)`
* `audit_log(id INTEGER PK, group_id BIGINT, actor_id BIGINT, action TEXT, target_user_id BIGINT, extra JSON, created_at DATETIME)`
* `jobs(id INTEGER PK, group_id BIGINT, kind TEXT, payload JSON, run_at DATETIME, interval_sec INTEGER NULL)`
* Add indices on `(group_id)`, `(user_id, group_id)`, and time columns. Provide `init_db()`, `migrate()` helpers, and repository classes with atomic upserts & batched reads.

### Private **Control Panel** (DM with the bot)

* `/start` in private: show **InlineKeyboard** listing **groups where the DM user is admin** (paged). Selecting a group opens a **tabbed** inline UI:

  * Tabs: **Moderation**, **Anti-Spam**, **Welcome**, **Rules**, **Automations**, **Language**, **Export/Backup**
* Each tab is a dedicated “page” using **arbitrary callback\_data** (state keys persisted). All changes validate admin again at apply-time. Localize all texts.

### Group Features (professional set)

1. **Moderation**

   * Commands & buttons: `/warn`, `/unwarn`, `/mute`, `/unmute`, `/restrict`, `/ban`, `/unban`, `/del`, `/purge <N>`
   * Parse human durations: `30s`, `10m`, `2h`, `3d`, `perm`
   * Restrictions: send/read/media/links/stickers; support forum **topics** (open/close/rename if permitted)
   * Every action → `audit_log` with actor, target, reason, duration, message link if applicable
2. **Anti-Spam & Content Rules**

   * Flood control (msgs/window per user), duplicate detector, new-account age gate, bad-word/regex lists
   * Link policy (allowlist/denylist), forward lock, media type locks, mention/hashtag limits
   * **Escalation pipeline** per policy: log → warn → temp restrict → ban (thresholds & cooldowns configurable)
3. **Onboarding & Rules**

   * Welcome templates (Markdown/HTML) with variables `{first_name}`, `{group_title}`; optional **button-tap verification** or simple math captcha with timeout
   * Farewell on leave; `/rules` paginated; actions to **pin** or **rotate pin**
   * Handle **join requests** via `ChatJoinRequestHandler` when enabled
4. **Automations (Scheduler)**

   * Use **JobQueue** for: scheduled announcements, rotating pins, timed unmute/unban, daily cleanup of expired warns/mutes
   * Admin UI to create/edit/cancel jobs; accept human intervals and simple cron-like presets
5. **Admin Utilities**

   * `/admins` (list with rights), `/stats` (violations, top offenders, message counts), `/export` (JSON settings & last N audit rows), `/import` (merge with validation)
6. **Localization**

   * Everything user-facing goes through `t()`. Provide EN & AR files; per-group language override.

### Bot Commands & Scopes

* Private scope: `/start`, `/panel`, `/help`
* Group scope (everyone): `/rules`
* Group **admin** scope: `/warn`, `/mute`, `/restrict`, `/ban`, `/purge`, `/settings`
* On startup set commands via `set_my_commands` with appropriate **BotCommandScope** (private, all group chats, chat administrators)

### Resilience, UX & Logging

* Global error handler: structured JSON logs, redacted IDs; friendly localized error to admins
* Auto-delete helper bot messages after N seconds (schedule via JobQueue)
* Rate-limit heavy operations and admin panels using PTB’s built-in **AIORateLimiter**
* Startup sequence:

  * Ensure DB & migrations; enable WAL and foreign keys
  * Warm settings cache per group; rebuild scheduled jobs
  * Set bot commands & `allowed_updates=["message","callback_query","chat_member","chat_join_request"]`

### Deliverables

* Full codebase with the above package layout
* `pyproject.toml`, `README.md`, `.env.example`
* Seed script to register `OWNER_IDS` and default group settings
* Clear run instructions (polling):

  * `python -m bot.main`

**Acceptance Criteria (verify in output)**

* Async PTB app using `ApplicationBuilder`; handlers for messages, callbacks, `ChatMemberHandler`, `ChatJoinRequestHandler`
* Admin DM control panel listing only groups where the user is currently admin (from DB snapshot)
* Working moderation & anti-spam with persistence, human durations, and audit logging
* JobQueue-based automations (timed unmute/unban, announcements, cleanup)
* i18n (EN/AR) with per-group override
* No Docker/CI/tests included

