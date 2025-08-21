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
from .core.logging import setup_logging
from .core.errors import register_error_handler
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


async def on_startup(app: Application) -> None:
    await migrate()  # ensure DB and pragmas
    await set_bot_commands(app)
    await load_jobs(app)


async def set_bot_commands(app: Application) -> None:
    cmds: List[BotCommand] = [
        BotCommand("start", "Start or open control panel"),
        BotCommand("help", "Show help"),
        BotCommand("rules", "Show group rules"),
        BotCommand("settings", "Open settings (admins)"),
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

    # Basic commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_))

    # Feature registrations
    register_moderation(app)
    register_welcome(app)
    register_antispam(app)
    register_rules(app)
    register_automations(app)
    register_admin_panel(app)
    register_admin_sync(app)
    register_onboarding(app)
    register_verification(app)
    register_topics(app)

    # Events & callbacks
    async def _noop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        return None
    app.add_handler(CallbackQueryHandler(_noop), group=10)

    # Errors
    register_error_handler(app)

    return app


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update, fallback=settings.DEFAULT_LANG)
    text = t(lang, "start.welcome", first_name=update.effective_user.first_name or "")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def help_(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update, fallback=settings.DEFAULT_LANG)
    await update.effective_message.reply_text(t(lang, "help.text"))


async def main() -> None:
    # Ensure data directory exists for SQLite path
    from pathlib import Path

    Path("data").mkdir(exist_ok=True)

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
    import sys
    
    # Ensure data directory exists for SQLite path
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    
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
