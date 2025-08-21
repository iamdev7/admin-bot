from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..infra import db
from ..infra.settings_repo import SettingsRepo


async def reply_ephemeral(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    msg = await update.effective_message.reply_text(text)
    gid = update.effective_chat.id if update.effective_chat else None
    if gid is None:
        return
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "ephemeral") or {"seconds": None}
    seconds = cfg.get("seconds")
    if seconds:
        context.job_queue.run_once(delete_message, when=int(seconds), data={"chat_id": msg.chat_id, "message_id": msg.message_id})


async def delete_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    try:
        await context.bot.delete_message(data.get("chat_id"), data.get("message_id"))
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("ephemeral delete failed chat=%s mid=%s: %s", data.get("chat_id"), data.get("message_id"), e)
