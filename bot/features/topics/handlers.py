from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes
import logging

from ...core.permissions import require_admin
from ...core.i18n import I18N, t
log = logging.getLogger(__name__)


def _thread_id(update: Update) -> int | None:
    msg = update.effective_message
    return getattr(msg, "message_thread_id", None)


@require_admin
async def topic_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    tid = _thread_id(update)
    if not tid:
        return await update.effective_message.reply_text(t(lang, "topic.not_in_forum"))
    try:
        await context.bot.close_forum_topic(update.effective_chat.id, tid)
        await update.effective_message.reply_text(t(lang, "topic.closed"))
    except Exception as e:
        log.exception("topic_close failed chat=%s tid=%s: %s", update.effective_chat.id, tid, e)


@require_admin
async def topic_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    tid = _thread_id(update)
    if not tid:
        return await update.effective_message.reply_text(t(lang, "topic.not_in_forum"))
    try:
        await context.bot.reopen_forum_topic(update.effective_chat.id, tid)
        await update.effective_message.reply_text(t(lang, "topic.opened"))
    except Exception as e:
        log.exception("topic_open failed chat=%s tid=%s: %s", update.effective_chat.id, tid, e)


@require_admin
async def topic_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    tid = _thread_id(update)
    if not tid:
        return await update.effective_message.reply_text(t(lang, "topic.not_in_forum"))
    name = " ".join(context.args) if context.args else None
    if not name:
        return await update.effective_message.reply_text(t(lang, "topic.rename_usage"))
    try:
        await context.bot.edit_forum_topic(update.effective_chat.id, tid, name=name)
        await update.effective_message.reply_text(t(lang, "topic.renamed"))
    except Exception as e:
        log.exception("topic_rename failed chat=%s tid=%s: %s", update.effective_chat.id, tid, e)


@require_admin
async def topic_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    tid = _thread_id(update)
    msg = update.effective_message
    if not tid:
        return await msg.reply_text(t(lang, "topic.not_in_forum"))
    if not msg.reply_to_message:
        return await msg.reply_text(t(lang, "topic.pin_usage"))
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, msg.reply_to_message.message_id, disable_notification=True)
        await msg.reply_text(t(lang, "topic.pinned"))
    except Exception as e:
        log.exception("topic_pin failed chat=%s tid=%s: %s", update.effective_chat.id, tid, e)
