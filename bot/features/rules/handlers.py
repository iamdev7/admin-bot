from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ...core.i18n import I18N, t
from ...core.permissions import require_admin
from ...infra import db
from ...infra.settings_repo import SettingsRepo


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    gid = update.effective_chat.id if update.effective_chat else 0
    
    # Get custom rules text
    text = None
    async with db.SessionLocal() as s:  # type: ignore
        text = await SettingsRepo(s).get_text(gid, "rules")
    
    # Create professional rules display
    group_name = update.effective_chat.title if update.effective_chat else "this group"
    
    if text:
        # Custom rules exist - add a professional header
        professional_text = (
            f"📋 <b>Rules for {group_name}</b>\n"
            f"{'─' * 30}\n\n"
            f"{text}"
        )
    else:
        # No custom rules - use professional default
        professional_text = (
            f"📋 <b>Rules for {group_name}</b>\n"
            f"{'─' * 30}\n\n"
            f"📌 <b>General Guidelines:</b>\n\n"
            f"1️⃣ Be respectful to all members\n"
            f"2️⃣ No spam or advertisements\n"
            f"3️⃣ Stay on topic\n"
            f"4️⃣ No harassment or hate speech\n"
            f"5️⃣ Follow Telegram's Terms of Service\n\n"
            f"Please follow these rules to maintain a positive community environment."
        )
    
    await update.effective_message.reply_text(professional_text, parse_mode="HTML")


@require_admin
async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    msg = update.effective_message
    if not msg:
        return
    
    # Get formatted text preserving HTML formatting
    html_text = None
    
    # Check if replying to a message
    if msg.reply_to_message:
        # Get HTML formatted text from the replied message
        if msg.reply_to_message.text:
            html_text = msg.reply_to_message.text_html
        elif msg.reply_to_message.caption:
            html_text = msg.reply_to_message.caption_html
    elif context.args:
        # If text is provided after command, check if message has entities
        if msg.text and msg.entities:
            # Extract HTML from the message, skipping the command entity
            # Find where the command ends
            command_end = len("/setrules")
            if msg.text[command_end:command_end+1] == " ":
                command_end += 1
            # Get the text after the command with HTML formatting
            full_html = msg.text_html
            # Remove the command part from HTML
            # The command will be wrapped in the HTML, so we need to find and remove it
            import re
            # Remove the bot command entity (usually wrapped in a tag)
            html_text = re.sub(r'^.*?/setrules\s*', '', full_html, count=1)
        else:
            # Plain text without formatting
            html_text = " ".join(context.args)
    
    if not html_text:
        return await msg.reply_text(t(lang, "rules.set.usage"))
    
    # Store the HTML formatted text
    async with db.SessionLocal() as s:  # type: ignore
        await SettingsRepo(s).set_text(msg.chat_id, "rules", html_text)
        await s.commit()
    
    await msg.reply_text(t(lang, "rules.set.ok"))
