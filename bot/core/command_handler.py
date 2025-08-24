"""Handle unknown commands and permission checks."""

from __future__ import annotations

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters, Application

from .config import settings
from .i18n import t, I18N
from .logging_config import get_logger

log = get_logger(__name__)

# Known commands and their requirements
COMMANDS = {
    # Public commands (anyone can use)
    "/start": {"private": True, "group": True, "owner": False, "admin": False},
    "/help": {"private": True, "group": True, "owner": False, "admin": False},
    "/privacy": {"private": True, "group": True, "owner": False, "admin": False},
    "/rules": {"private": False, "group": True, "owner": False, "admin": False},
    "/panel": {"private": True, "group": False, "owner": False, "admin": False},
    
    # Admin commands (group admins only)
    "/warn": {"private": False, "group": True, "owner": False, "admin": True},
    "/unwarn": {"private": False, "group": True, "owner": False, "admin": True},
    "/mute": {"private": False, "group": True, "owner": False, "admin": True},
    "/unmute": {"private": False, "group": True, "owner": False, "admin": True},
    "/ban": {"private": False, "group": True, "owner": False, "admin": True},
    "/unban": {"private": False, "group": True, "owner": False, "admin": True},
    "/purge": {"private": False, "group": True, "owner": False, "admin": True},
    "/setrules": {"private": False, "group": True, "owner": False, "admin": True},
    "/settings": {"private": False, "group": True, "owner": False, "admin": True},
    "/joinapprove": {"private": False, "group": True, "owner": False, "admin": True},
    "/addrule": {"private": False, "group": True, "owner": False, "admin": True},
    "/delrule": {"private": False, "group": True, "owner": False, "admin": True},
    
    # Owner commands (bot owners only)
    "/bot": {"private": True, "group": False, "owner": True, "admin": False},
    "/backup": {"private": True, "group": True, "owner": True, "admin": False},
    "/broadcast": {"private": True, "group": False, "owner": True, "admin": False},
    
    # Topic commands (forum groups)
    "/topic_close": {"private": False, "group": True, "owner": False, "admin": True},
    "/topic_open": {"private": False, "group": True, "owner": False, "admin": True},
    "/topic_rename": {"private": False, "group": True, "owner": False, "admin": True},
    "/topic_pin": {"private": False, "group": True, "owner": False, "admin": True},
}


async def handle_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands with appropriate responses."""
    if not update.message or not update.message.text:
        return
    
    if not update.effective_user:
        return
    
    # Extract command
    text = update.message.text
    command = text.split()[0].lower()
    
    # Remove bot username if present (e.g., /command@botname)
    if '@' in command:
        command = command.split('@')[0]
    
    lang = I18N.pick_lang(update, fallback=settings.DEFAULT_LANG)
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type if update.effective_chat else "private"
    is_private = chat_type == "private"
    is_group = chat_type in ["group", "supergroup"]
    
    # Check if command exists
    if command not in COMMANDS:
        # Unknown command
        response = t(lang, "errors.unknown_command", command=command)
        
        # Add help button
        keyboard = [[InlineKeyboardButton("❓ Help", callback_data="help:show")]]
        markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            response,
            parse_mode=ParseMode.HTML,
            reply_markup=markup
        )
        return
    
    # Command exists, check permissions
    cmd_info = COMMANDS[command]
    
    # Check chat type requirements
    if is_private and not cmd_info["private"]:
        # Command only works in groups
        await update.message.reply_text(
            t(lang, "errors.group_only"),
            parse_mode=ParseMode.HTML
        )
        return
    
    if is_group and not cmd_info["group"]:
        # Command only works in private
        bot_username = context.bot.username or "bot"
        await update.message.reply_text(
            t(lang, "errors.private_only", bot_username=bot_username),
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check permission requirements
    if cmd_info["owner"]:
        # Owner-only command
        if user_id not in settings.OWNER_IDS:
            required = t(lang, "errors.owner_only")
            response = t(lang, "errors.no_permission", command=command, required=required)
            await update.message.reply_text(response, parse_mode=ParseMode.HTML)
            return
    
    if cmd_info["admin"] and is_group:
        # Admin-only command in group
        try:
            member = await context.bot.get_chat_member(
                update.effective_chat.id,
                user_id
            )
            if member.status not in ["administrator", "creator"]:
                required = t(lang, "errors.admin_only")
                response = t(lang, "errors.no_permission", command=command, required=required)
                await update.message.reply_text(response, parse_mode=ParseMode.HTML)
                return
        except Exception as e:
            log.error(f"Error checking admin status: {e}")
    
    # If we reach here, the command exists and user has permission,
    # but no handler is registered (shouldn't happen normally)
    log.warning(f"Command {command} exists but no handler registered")


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle help callback button."""
    if not update.callback_query:
        return
    
    await update.callback_query.answer()
    
    # Import the help command from private_handler
    from .private_handler import help_command
    await help_command(update, context)


def register_command_handlers(app: Application) -> None:
    """Register command handlers."""
    # Handle unknown commands (lower priority so it catches unhandled commands)
    app.add_handler(
        MessageHandler(
            filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE,
            handle_unknown_command
        ),
        group=100  # Low priority to catch unhandled commands
    )
    
    # Handle help callback
    from telegram.ext import CallbackQueryHandler
    app.add_handler(
        CallbackQueryHandler(help_callback, pattern="^help:show$"),
        group=5
    )
    
    log.info("Command handlers registered")