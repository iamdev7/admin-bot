"""Handle private messages to the bot."""

from __future__ import annotations

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters, Application

from .config import settings
from .i18n import t, I18N
from .logging_config import get_logger

log = get_logger(__name__)


async def generate_help_text(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> str:
    """Generate help text based on user permissions."""
    user_id = update.effective_user.id if update.effective_user else 0
    
    # Check if user is bot owner
    is_owner = user_id in settings.OWNER_IDS
    
    # Check if user is admin of any groups
    from ..infra import db
    from ..infra.repos import GroupsRepo
    
    is_group_admin = False
    admin_groups = []
    
    try:
        async with db.SessionLocal() as session:  # type: ignore
            groups = await GroupsRepo(session).list_admin_groups(user_id)
            if groups:
                is_group_admin = True
                admin_groups = groups[:3]  # Show first 3 groups
    except Exception as e:
        log.error(f"Error checking admin groups: {e}")
    
    # Build help text based on permissions
    parts = []
    parts.append(f"📚 <b>{t(lang, 'bot.name')}</b> - {t(lang, 'help.title')}\n")
    
    # Basic commands everyone can use
    parts.append(f"<b>{t(lang, 'help.section.basic')}</b>")
    parts.append(t(lang, "help.cmd.start"))
    parts.append(t(lang, "help.cmd.help"))
    parts.append(t(lang, "help.cmd.panel"))
    parts.append("")
    
    # Group admin commands
    if is_group_admin:
        parts.append(f"<b>{t(lang, 'help.section.admin')}</b>")
        parts.append(t(lang, "help.cmd.warn"))
        parts.append(t(lang, "help.cmd.unwarn"))
        parts.append(t(lang, "help.cmd.mute"))
        parts.append(t(lang, "help.cmd.unmute"))
        parts.append(t(lang, "help.cmd.ban"))
        parts.append(t(lang, "help.cmd.unban"))
        parts.append(t(lang, "help.cmd.purge"))
        parts.append(t(lang, "help.cmd.rules"))
        parts.append(t(lang, "help.cmd.setrules"))
        parts.append(t(lang, "help.cmd.settings"))
        parts.append("")
        
        if admin_groups:
            parts.append(f"<b>{t(lang, 'help.section.groups', count=len(admin_groups))}</b>")
            for group in admin_groups:
                parts.append(f"• {group.title}")
            parts.append("")
    
    # Bot owner commands
    if is_owner:
        parts.append(f"<b>{t(lang, 'help.section.owner')}</b>")
        parts.append(t(lang, "help.cmd.bot"))
        parts.append(t(lang, "help.cmd.backup"))
        parts.append(t(lang, "help.cmd.broadcast"))
        parts.append("")
    
    # Tips section
    parts.append(f"<b>{t(lang, 'help.section.tips')}</b>")
    if not is_group_admin:
        parts.append(t(lang, "help.tip.add_bot"))
        parts.append(t(lang, "help.tip.use_panel"))
    else:
        parts.append(t(lang, "help.tip.panel_private"))
        parts.append(t(lang, "help.tip.antispam"))
        parts.append(t(lang, "help.tip.welcome"))
    
    parts.append("")
    parts.append(t(lang, "help.developer"))
    parts.append(t(lang, "help.channel"))
    
    return "\n".join(parts)


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any private message to the bot."""
    if not update.effective_chat or update.effective_chat.type != "private":
        return
    
    if not update.effective_user:
        return
    
    # Skip if it's a command (commands are handled separately)
    if update.message and update.message.text and update.message.text.startswith('/'):
        return
    
    lang = I18N.pick_lang(update, fallback=settings.DEFAULT_LANG)
    bot_name = t(lang, "bot.name")
    
    # Show welcome message for any non-command message
    text = t(lang, "start.private.welcome", bot_name=bot_name)
    
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show permission-aware help."""
    lang = I18N.pick_lang(update, fallback=settings.DEFAULT_LANG)
    
    # Generate help based on permissions
    if update.effective_chat and update.effective_chat.type == "private":
        text = await generate_help_text(update, context, lang)
        
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
        # Simple help in groups
        await update.effective_message.reply_text(t(lang, "help.text"))


def register_private_handler(app: Application) -> None:
    """Register private message handler."""
    # Handle any non-command private message
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_private_message
        ),
        group=5
    )
    
    log.info("Private message handler registered")