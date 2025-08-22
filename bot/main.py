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
from .core.private_handler import register_private_handler, help_command as new_help_command
from .core.command_handler import register_command_handlers

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
    app.add_handler(CommandHandler("help", new_help_command))
    
    # Admin backup command
    app.add_handler(CommandHandler("backup", manual_backup_command))
    
    # Register private message handler
    register_private_handler(app)
    
    # Register command handlers (for unknown commands and permission checks)
    register_command_handlers(app)

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
    join_action = None  # Track if this is a join request action
    join_gid = None
    join_uid = None
    
    if param:
        # Check for join request deep links first
        import base64
        if len(param) > 0 and not param.startswith("rules"):
            # Try to decode as base64 join request
            try:
                pad = '=' * (-len(param) % 4)
                decoded = base64.urlsafe_b64decode(param + pad).decode()
                if decoded.startswith("join_accept_") or decoded.startswith("join_decline_"):
                    parts = decoded.split("_")
                    if len(parts) == 4:
                        join_action = parts[1]  # "accept" or "decline"
                        join_gid = int(parts[2])
                        join_uid = int(parts[3])
                        # Process join request action
                        if update.effective_user and update.effective_user.id == join_uid:
                            # Delete the /start message immediately
                            try:
                                await update.effective_message.delete()
                            except Exception:
                                pass  # Ignore if deletion fails
                            
                            if join_action == "accept":
                                try:
                                    await context.bot.approve_chat_join_request(join_gid, join_uid)
                                    
                                    # Try to edit the original rules message
                                    original_msg_id = context.application.user_data.get(join_uid, {}).get(f"join_rules_msg_{join_gid}")
                                    
                                    if original_msg_id:
                                        # Get the original message text to keep it
                                        from .infra import db
                                        from .infra.settings_repo import SettingsRepo
                                        rules_text = None
                                        group_title = str(join_gid)
                                        async with db.SessionLocal() as s:  # type: ignore
                                            rules_text = await SettingsRepo(s).get_text(join_gid, "rules")
                                            try:
                                                from .infra.models import Group
                                                g = await s.get(Group, join_gid)
                                                if g and g.title:
                                                    group_title = g.title
                                            except Exception:
                                                pass
                                        try:
                                            chat = await context.bot.get_chat(join_gid)
                                            if chat and chat.title:
                                                group_title = chat.title
                                        except Exception:
                                            pass
                                        
                                        header = t(lang, "rules.dm.header")
                                        txt = header + "\n\n" + t(lang, "join.dm.rules", group_title=group_title, rules=rules_text or t(lang, "rules.default"))
                                        txt += f"\n\n✅ {t(lang, 'rules.accepted')}"
                                        
                                        # Add return button if group has username
                                        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                                        return_kb = None
                                        try:
                                            chat = await context.bot.get_chat(join_gid)
                                            if getattr(chat, "username", None):
                                                url = f"https://t.me/{chat.username}"
                                                return_kb = InlineKeyboardMarkup(
                                                    [[InlineKeyboardButton(t(lang, "rules.return_group"), url=url)]]
                                                )
                                        except Exception:
                                            return_kb = None
                                        
                                        # Edit the original message - remove buttons and add acceptance note
                                        try:
                                            await context.bot.edit_message_text(
                                                chat_id=update.effective_chat.id,
                                                message_id=original_msg_id,
                                                text=txt,
                                                reply_markup=return_kb
                                            )
                                        except Exception as e:
                                            log.warning(f"Could not edit original message: {e}")
                                            # Fallback: send a brief success message that auto-deletes
                                            success_msg = await context.bot.send_message(
                                                chat_id=update.effective_chat.id,
                                                text="✅ " + t(lang, 'rules.accepted')
                                            )
                                            async def delete_success(ctx):
                                                try:
                                                    await ctx.bot.delete_message(update.effective_chat.id, success_msg.message_id)
                                                except Exception:
                                                    pass
                                            context.job_queue.run_once(delete_success, when=3)
                                    else:
                                        # No stored message ID, just send brief confirmation
                                        success_msg = await context.bot.send_message(
                                            chat_id=update.effective_chat.id,
                                            text="✅ " + t(lang, 'rules.accepted')
                                        )
                                        async def delete_success(ctx):
                                            try:
                                                await ctx.bot.delete_message(update.effective_chat.id, success_msg.message_id)
                                            except Exception:
                                                pass
                                        context.job_queue.run_once(delete_success, when=3)
                                    
                                    log.info(f"Approved join request via deep link for user {join_uid} in group {join_gid}")
                                except Exception as e:
                                    log.exception("Failed to approve join request via deep link gid=%s uid=%s: %s", join_gid, join_uid, e)
                                    error_msg = await context.bot.send_message(
                                        chat_id=update.effective_chat.id,
                                        text=t(lang, "join.error")
                                    )
                                    # Delete error message after 5 seconds
                                    async def delete_error(ctx):
                                        try:
                                            await ctx.bot.delete_message(update.effective_chat.id, error_msg.message_id)
                                        except Exception:
                                            pass
                                    context.job_queue.run_once(delete_error, when=5)
                            elif join_action == "decline":
                                try:
                                    await context.bot.decline_chat_join_request(join_gid, join_uid)
                                    
                                    # Try to edit the original rules message
                                    original_msg_id = context.application.user_data.get(join_uid, {}).get(f"join_rules_msg_{join_gid}")
                                    
                                    if original_msg_id:
                                        # Edit the original message to show decline status
                                        try:
                                            # Get group title for the message
                                            group_title = str(join_gid)
                                            try:
                                                chat = await context.bot.get_chat(join_gid)
                                                if chat and chat.title:
                                                    group_title = chat.title
                                            except Exception:
                                                pass
                                            
                                            txt = f"❌ {t(lang, 'join.declined_message')}\n\n"
                                            txt += t(lang, "join.declined_group", group_title=group_title)
                                            
                                            await context.bot.edit_message_text(
                                                chat_id=update.effective_chat.id,
                                                message_id=original_msg_id,
                                                text=txt,
                                                reply_markup=None  # Remove all buttons
                                            )
                                        except Exception as e:
                                            log.warning(f"Could not edit original message for decline: {e}")
                                            # Fallback: send decline message that auto-deletes
                                            decline_msg = await context.bot.send_message(
                                                chat_id=update.effective_chat.id,
                                                text="❌ " + t(lang, "join.declined_message")
                                            )
                                            async def delete_decline(ctx):
                                                try:
                                                    await ctx.bot.delete_message(update.effective_chat.id, decline_msg.message_id)
                                                except Exception:
                                                    pass
                                            context.job_queue.run_once(delete_decline, when=3)
                                    else:
                                        # No stored message ID, send brief decline message
                                        decline_msg = await context.bot.send_message(
                                            chat_id=update.effective_chat.id,
                                            text="❌ " + t(lang, "join.declined_message")
                                        )
                                        async def delete_decline(ctx):
                                            try:
                                                await ctx.bot.delete_message(update.effective_chat.id, decline_msg.message_id)
                                            except Exception:
                                                pass
                                        context.job_queue.run_once(delete_decline, when=3)
                                    
                                    log.info(f"Declined join request via deep link for user {join_uid} in group {join_gid}")
                                except Exception as e:
                                    log.exception("Failed to decline join request via deep link gid=%s uid=%s: %s", join_gid, join_uid, e)
                                    error_msg = await context.bot.send_message(
                                        chat_id=update.effective_chat.id,
                                        text=t(lang, "join.error")
                                    )
                                    # Delete error message after 5 seconds  
                                    async def delete_error(ctx):
                                        try:
                                            await ctx.bot.delete_message(update.effective_chat.id, error_msg.message_id)
                                        except Exception:
                                            pass
                                    context.job_queue.run_once(delete_error, when=5)
                            
                            # Track user interaction
                            from .infra import db
                            from .infra.repos import UsersRepo
                            try:
                                async with db.SessionLocal() as s:  # type: ignore
                                    await UsersRepo(s).upsert_user(
                                        uid=join_uid,
                                        username=getattr(update.effective_user, 'username', None),
                                        first_name=getattr(update.effective_user, 'first_name', None),
                                        last_name=getattr(update.effective_user, 'last_name', None),
                                        language=getattr(update.effective_user, 'language_code', None),
                                    )
                                    await s.commit()
                            except Exception:
                                pass
                            return  # Exit early after processing join request
            except Exception:
                pass  # Not a join request deep link, continue with normal processing
        
        # Normal rules deep links
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
    
    # Check if we're in private chat
    if update.effective_chat and update.effective_chat.type == "private":
        # Show the professional welcome message for private users
        bot_name = t(lang, "bot.name")
        text = t(lang, "start.private.welcome", bot_name=bot_name)
        
        # Add buttons for channel and panel
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [InlineKeyboardButton(t(lang, "bot.button.updates"), url="https://t.me/codei8")],
            [InlineKeyboardButton(t(lang, "bot.button.manage"), callback_data="panel:back")]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        
        await update.effective_message.reply_text(
            text, 
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True
        )
    else:
        # In group, show simple welcome
        text = t(lang, "start.welcome", first_name=update.effective_user.first_name or "")
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def help_(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update, fallback=settings.DEFAULT_LANG)
    
    # Show detailed help in private, simple in groups
    if update.effective_chat and update.effective_chat.type == "private":
        text = t(lang, "help.private")
        
        # Add buttons
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [InlineKeyboardButton(t(lang, "bot.button.updates"), url="https://t.me/codei8")],
            [InlineKeyboardButton(t(lang, "bot.button.manage"), callback_data="panel:back")]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True
        )
    else:
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
