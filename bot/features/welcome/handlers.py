from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ...core.i18n import I18N, t
from ...infra.settings_repo import SettingsRepo
from ...infra import db


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.chat_member:
        return
    cm = update.chat_member
    if not cm.new_chat_member or not update.effective_chat:
        return
    # Welcome only on join
    if cm.old_chat_member and cm.old_chat_member.status == cm.new_chat_member.status:
        return
    user = cm.new_chat_member.user
    lang = I18N.pick_lang(update)
    template = None
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(update.effective_chat.id, "welcome") or {}
        template = cfg.get("template")
        enabled = cfg.get("enabled", True)
    if enabled:
        text = (
            template.format(first_name=user.first_name or "", group_title=update.effective_chat.title or "")
            if template
            else t(lang, "welcome.message", first_name=user.first_name or "", group_title=update.effective_chat.title or "")
        )
        await context.bot.send_message(update.effective_chat.id, text)
