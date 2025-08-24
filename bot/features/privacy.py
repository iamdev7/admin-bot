"""Privacy policy command handler"""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..core.i18n import I18N, t


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display privacy policy"""
    if not update.effective_message:
        return
    
    lang = I18N.pick_lang(update)
    
    # Get privacy policy text
    privacy_text = t(lang, "privacy.policy")
    
    # Send privacy policy
    await update.effective_message.reply_text(
        privacy_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )