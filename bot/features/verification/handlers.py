from __future__ import annotations

import random
import time
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatPermissions
from telegram.ext import ContextTypes
import logging

from ...core.i18n import I18N, t
from ...core.utils import group_default_permissions
from ...infra import db
from ...infra.settings_repo import SettingsRepo
log = logging.getLogger(__name__)


@dataclass
class Pending:
    message_id: int
    deadline: float
    mode: str
    answer: int | None


def _store(context: ContextTypes.DEFAULT_TYPE):
    bd = context.bot_data
    if "verify" not in bd:
        bd["verify"] = {}
    return bd["verify"]


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.chat_member or not update.effective_chat:
        return
    cm = update.chat_member
    chat = update.effective_chat
    user = cm.new_chat_member.user
    # Only when user just became a member
    if cm.old_chat_member and cm.old_chat_member.status == cm.new_chat_member.status:
        return
    if cm.new_chat_member.status.value != "member":
        return
    # Load settings
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(chat.id, "captcha") or {"enabled": False, "mode": "button", "timeout": 120}
    if not cfg.get("enabled"):
        return
    lang = I18N.pick_lang(update)
    mode = cfg.get("mode", "button")
    timeout = int(cfg.get("timeout", 120))
    # Restrict until verified
    try:
        await context.bot.restrict_chat_member(
            chat.id,
            user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=int(time.time()) + timeout + 60,
        )
    except Exception as e:
        log.exception("verify: restrict failed gid=%s uid=%s: %s", chat.id, user.id, e)
    # Prepare captcha
    answer = None
    text = t(lang, "captcha.prompt")
    buttons = []
    if mode == "math":
        a, b = random.randint(1, 9), random.randint(1, 9)
        answer = a + b
        text = t(lang, "captcha.math", a=a, b=b)
        options = set([answer, random.randint(1, 18), random.randint(1, 18)])
        options = list(sorted(options))
        row = [InlineKeyboardButton(str(opt), callback_data=f"captcha:math:{chat.id}:{user.id}:{opt}") for opt in options]
        buttons.append(row)
    else:
        buttons.append([InlineKeyboardButton(t(lang, "captcha.im_human"), callback_data=f"captcha:ok:{chat.id}:{user.id}")])
    kb = InlineKeyboardMarkup(buttons)
    msg = await context.bot.send_message(chat.id, text, reply_markup=kb)
    # Track pending
    _store(context)[(chat.id, user.id)] = Pending(message_id=msg.message_id, deadline=time.time() + timeout, mode=mode, answer=answer)
    # Schedule timeout cleanup
    context.job_queue.run_once(timeout_kick, when=timeout, data={"chat_id": chat.id, "user_id": user.id}, name=f"verify:{chat.id}:{user.id}")


async def on_captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    data = (update.callback_query.data or "").split(":")
    if len(data) < 4:
        return
    typ = data[1]
    chat_id = int(data[2])
    user_id = int(data[3])
    if update.effective_user and update.effective_user.id != user_id:
        return
    pending = _store(context).get((chat_id, user_id))
    if not pending:
        return
    if typ == "ok" or (typ == "math" and len(data) == 5 and pending.answer == int(data[4])):
        # Verified — restore group default permissions
        try:
            perms = await group_default_permissions(context, chat_id)
            await context.bot.restrict_chat_member(chat_id, user_id, permissions=perms)
        except Exception as e:
            log.exception("verify: unrestrict failed gid=%s uid=%s: %s", chat_id, user_id, e)
        try:
            await context.bot.delete_message(chat_id, pending.message_id)
        except Exception as e:
            log.exception("verify: delete captcha message failed gid=%s mid=%s: %s", chat_id, pending.message_id, e)
        _store(context).pop((chat_id, user_id), None)
        # cancel job
        for jb in context.job_queue.get_jobs_by_name(f"verify:{chat_id}:{user_id}"):
            jb.schedule_removal()


async def timeout_kick(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    user_id = data.get("user_id")
    if chat_id is None or user_id is None:
        return
    # If still pending, kick
    pending = _store(context).get((chat_id, user_id))
    if not pending:
        return
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id)
    except Exception as e:
        log.exception("verify: timeout kick failed gid=%s uid=%s: %s", chat_id, user_id, e)
    _store(context).pop((chat_id, user_id), None)
