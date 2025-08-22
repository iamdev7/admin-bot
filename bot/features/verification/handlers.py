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
    
    # NOTE: We do NOT restrict immediately because restricted users cannot click inline buttons
    # We'll only kick them if they timeout without answering
    log.info(f"CAPTCHA enabled for user {user.id} in chat {chat.id}, mode: {mode}, timeout: {timeout}s")
    # Prepare captcha
    answer = None
    text = t(lang, "captcha.prompt") + f"\n⏱ {timeout}s"
    buttons = []
    if mode == "math":
        a, b = random.randint(1, 9), random.randint(1, 9)
        answer = a + b
        text = t(lang, "captcha.math", a=a, b=b) + f"\n⏱ {timeout}s"
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
    try:
        if not update.callback_query:
            log.error("CAPTCHA callback: No callback_query in update")
            return
        
        callback_data = update.callback_query.data or ""
        log.info(f"CAPTCHA callback received: {callback_data}")
        
        data = callback_data.split(":")
        if len(data) < 4:
            log.warning(f"CAPTCHA callback: Invalid data format: {callback_data}")
            await update.callback_query.answer()
            return
        
        typ = data[1]
        chat_id = int(data[2])
        user_id = int(data[3])
        
        log.info(f"CAPTCHA callback: type={typ}, chat_id={chat_id}, user_id={user_id}, effective_user={update.effective_user.id if update.effective_user else 'None'}")
        
        # Check if this is the correct user
        if update.effective_user and update.effective_user.id != user_id:
            lang = I18N.pick_lang(update)
            log.info(f"CAPTCHA: Wrong user {update.effective_user.id} tried to answer for user {user_id}")
            await update.callback_query.answer(
                t(lang, "captcha.wrong_user") or "❌ You are not the one required to solve this.",
                show_alert=True
            )
            return
        
        await update.callback_query.answer()
        
        # Check pending verification
        store = _store(context)
        log.info(f"CAPTCHA store keys: {list(store.keys())}")
        pending = store.get((chat_id, user_id))
        
        if not pending:
            log.warning(f"No pending CAPTCHA for user {user_id} in chat {chat_id}")
            log.warning(f"Available pending CAPTCHAs: {[(k, v.mode) for k, v in store.items()]}")
            return
    except Exception as e:
        log.exception(f"Error in CAPTCHA callback: {e}")
        if update.callback_query:
            try:
                await update.callback_query.answer("Error processing CAPTCHA. Please try again.", show_alert=True)
            except:
                pass
        raise
    
    # Log pending data details
    log.info(f"Found pending CAPTCHA: mode={pending.mode}, answer={pending.answer}, deadline={pending.deadline}")
    
    # Check if answer is correct
    is_correct = False
    if typ == "ok":
        is_correct = True
        log.info(f"User {user_id} clicked 'I am human' button for chat {chat_id}")
    elif typ == "math" and len(data) == 5:
        try:
            user_answer = int(data[4])
            is_correct = (pending.answer == user_answer)
            log.info(f"User {user_id} answered {user_answer} (correct: {pending.answer}, is_correct: {is_correct}) for chat {chat_id}")
        except ValueError as e:
            log.error(f"Failed to parse math answer: {data[4]}, error: {e}")
            is_correct = False
    
    if is_correct:
        # Verified — restore group default permissions
        log.info(f"CAPTCHA verified for user {user_id} in chat {chat_id}")
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
    else:
        # Wrong answer
        log.info(f"Wrong CAPTCHA answer from user {user_id} in chat {chat_id}")
        lang = I18N.pick_lang(update)
        await update.callback_query.answer(
            t(lang, "captcha.wrong_answer") or "❌ Wrong answer. Try again.",
            show_alert=True
        )


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
    
    log.info(f"CAPTCHA timeout for user {user_id} in chat {chat_id}, kicking user")
    
    # Try to delete the CAPTCHA message
    try:
        await context.bot.delete_message(chat_id, pending.message_id)
    except Exception as e:
        log.warning(f"Failed to delete CAPTCHA message on timeout: {e}")
    
    # Kick the user
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id)
    except Exception as e:
        log.exception("verify: timeout kick failed gid=%s uid=%s: %s", chat_id, user_id, e)
    
    _store(context).pop((chat_id, user_id), None)
