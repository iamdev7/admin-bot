from __future__ import annotations

import asyncio
import logging
from typing import List

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .core.config import settings
from .core.i18n import I18N, t
from .core.logging_config import setup_logging, get_logger
from .core.error_handler import setup_error_handlers
from .core.backup import schedule_backups, manual_backup_command

log = get_logger(__name__)
from .core.user_tracker import register_user_tracking
from .infra.db import init_engine, init_sessionmaker
from .infra.migrate import migrate
from .features.moderation import register as register_moderation
from .features.welcome import register as register_welcome
from .features.antispam import register as register_antispam
from .features.rules import register as register_rules
from .features.automations import register as register_automations
from .features.automations.handlers import load_jobs
from .features.admin_panel import register as register_admin_panel
from .core.admin_sync import register as register_admin_sync
from .features.onboarding import register as register_onboarding
from .features.verification import register as register_verification
from .features.topics import register as register_topics
from .features.bot_admin import register as register_bot_admin
from .features.global_enforcement import register as register_global_enforcement


async def on_startup(app: Application) -> None:
    await migrate()  # ensure DB and pragmas
    await set_bot_commands(app)
    await load_jobs(app)
    schedule_backups(app)  # Schedule database backups


async def set_bot_commands(app: Application) -> None:
    cmds: List[BotCommand] = [
        BotCommand("start", "Start or open control panel"),
        BotCommand("help", "Show help"),
        BotCommand("rules", "Show group rules"),
        BotCommand("settings", "Open settings (admins)"),
        BotCommand("backup", "Create database backup (bot owner only)"),
    ]
    await app.bot.set_my_commands(cmds)


def make_app() -> Application:
    setup_logging()
    I18N.load_locales()

    app = (
        ApplicationBuilder()
        .token(settings.BOT_TOKEN)
        # .rate_limiter(AIORateLimiter())  # Disabled until dependency is installed
        .concurrent_updates(True)
        .post_init(on_startup)
        .build()
    )

    # Register user tracking first (highest priority)
    register_user_tracking(app)
    
    # Register global enforcement early (before other handlers)
    register_global_enforcement(app)
    
    # Basic commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_))
    
    # Admin backup command
    app.add_handler(CommandHandler("backup", manual_backup_command))

    # Feature registrations
    register_moderation(app)
    register_welcome(app)
    register_antispam(app)
    register_rules(app)
    register_automations(app)
    register_admin_panel(app)
    register_bot_admin(app)  # Register bot admin commands for owner
    register_admin_sync(app)
    register_onboarding(app)
    register_verification(app)
    register_topics(app)

    # Events & callbacks - catch unhandled callbacks to prevent errors
    async def _noop(_: Update, __: ContextTypes.DEFAULT_TYPE) -> None:
        return None
    app.add_handler(CallbackQueryHandler(_noop), group=10)

    # Set up error handling
    setup_error_handlers(app)

    return app


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update, fallback=settings.DEFAULT_LANG)
    # Handle deep-link: /start rules_<gid> | rulesu_<username> | rules64_<b64(gid)>
    param: str | None = None
    if context.args:
        param = context.args[0]
    else:
        txt = update.effective_message.text or ""
        parts = txt.split(maxsplit=1)
        if len(parts) == 2:
            param = parts[1]
    gid: int | None = None
    if param:
        if param.startswith("rulesu_"):
            uname = param[7:]
            try:
                chat = await context.bot.get_chat(f"@{uname}")
                gid = chat.id
            except Exception as e:
                log.exception("get_chat by username failed for %s: %s", uname, e)
                gid = None
        elif param.startswith("rules64_"):
            import base64
            data = param[8:]
            # Add padding back for urlsafe b64
            pad = '=' * (-len(data) % 4)
            try:
                decoded = base64.urlsafe_b64decode(data + pad).decode()
                gid = int(decoded)
            except Exception as e:
                log.exception("Failed to decode rules64 payload '%s': %s", data, e)
                gid = None
        elif param.startswith("rules_"):
            gid_s = param[7:]
            try:
                gid = int(gid_s)
            except ValueError:
                gid = None

    if gid is not None:
            # Check if we already sent rules in the last few messages
            # This prevents duplicate messages when user clicks "Read & Accept Rules" button
            recent_messages_key = f"rules_sent_{gid}_{update.effective_user.id if update.effective_user else 0}"
            if context.user_data.get(recent_messages_key):
                # Rules were already sent, don't duplicate - just remind them to click Accept above
                lang = I18N.pick_lang(update)
                reminder_msg = await update.effective_message.reply_text(t(lang, "rules.already_sent"))
                # Store message ID so we can edit it later when user accepts
                context.user_data[f"reminder_msg_{gid}_{update.effective_user.id}"] = reminder_msg.message_id
                return
            
            from .infra import db
            from .infra.settings_repo import SettingsRepo
            rules_text = None
            group_title = str(gid)
            async with db.SessionLocal() as s:  # type: ignore
                rules_text = await SettingsRepo(s).get_text(gid, "rules")
                # DB fallback title (in case get_chat fails)
                try:
                    from .infra.models import Group
                    g = await s.get(Group, gid)
                    if g and g.title:
                        group_title = g.title
                except Exception as e:
                    log.exception("Failed to read group title from DB gid=%s: %s", gid, e)
            # Try live chat info for accurate title
            try:
                chat = await context.bot.get_chat(gid)
                if chat and chat.title:
                    group_title = chat.title
            except Exception as e:
                log.exception("get_chat failed for gid=%s: %s", gid, e)
            header = t(lang, "rules.dm.header")
            txt = header + "\n\n" + t(lang, "join.dm.rules", group_title=group_title, rules=rules_text or t(lang, "rules.default"))
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            uid = update.effective_user.id if update.effective_user else 0
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "join.accept"), callback_data=f"rules:accept:{gid}:{uid}")]])
            await update.effective_message.reply_text(txt, reply_markup=kb)
            
            # Mark that we sent rules to avoid duplication
            context.user_data[recent_messages_key] = True
            # Clear flag after some time
            async def clear_flag(ctx: ContextTypes.DEFAULT_TYPE):
                ctx.user_data.pop(recent_messages_key, None)
            context.job_queue.run_once(clear_flag, when=300)  # Clear after 5 minutes
            
            return
    text = t(lang, "start.welcome", first_name=update.effective_user.first_name or "")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def help_(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update, fallback=settings.DEFAULT_LANG)
    await update.effective_message.reply_text(t(lang, "help.text"))


async def main() -> None:
    # Ensure data directory exists for SQLite path
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    
    # Set up logging (debug mode from env)
    import os
    debug_mode = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")
    setup_logging(log_file=True, debug=debug_mode)
    
    # Log startup info
    log.info(f"Bot starting with {len(settings.OWNER_IDS)} owner(s) configured")

    await init_engine(settings.DATABASE_URL)
    init_sessionmaker()
    app = make_app()

    await app.run_polling(
        allowed_updates=[
            "message",
            "callback_query",
            "chat_member",
            "my_chat_member",
            "chat_join_request",
        ],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    # Ensure data directory exists for SQLite path
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    
    # Set up logging first (debug mode from env)
    import os
    debug_mode = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")
    setup_logging(log_file=True, debug=debug_mode)
    
    # Initialize database synchronously
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_engine(settings.DATABASE_URL))
    init_sessionmaker()
    # Run migrations to create the SQLite file and tables early
    loop.run_until_complete(migrate())
    
    # Create and run the app
    app = make_app()
    app.run_polling(
        allowed_updates=[
            "message",
            "callback_query",
            "chat_member",
            "my_chat_member",
            "chat_join_request",
        ],
        drop_pending_updates=True,
    )
