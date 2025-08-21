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
    text = None
    async with db.SessionLocal() as s:  # type: ignore
        text = await SettingsRepo(s).get_text(gid, "rules")
    await update.effective_message.reply_text(text or t(lang, "rules.default"))


@require_admin
async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    msg = update.effective_message
    if not msg:
        return
    # Accept text after command or from reply
    text = " ".join(context.args) if context.args else None
    if not text and msg.reply_to_message and msg.reply_to_message.text:
        text = msg.reply_to_message.text
    if not text:
        return await msg.reply_text(t(lang, "rules.set.usage"))
    async with db.SessionLocal() as s:  # type: ignore
        await SettingsRepo(s).set_text(msg.chat_id, "rules", text)
        await s.commit()
    await msg.reply_text(t(lang, "rules.set.ok"))
