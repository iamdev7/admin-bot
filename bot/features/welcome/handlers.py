from __future__ import annotations

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
import base64
from telegram.ext import ContextTypes
import logging

from ...core.i18n import I18N, t
from ...infra.settings_repo import SettingsRepo
from ...infra import db
log = logging.getLogger(__name__)


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
        ttl = int(cfg.get("ttl_sec", 0) or 0)
        ob = await SettingsRepo(s).get(update.effective_chat.id, "onboarding") or {}
        # Default to require unmute unless pre-approval acceptance is enabled
        require_unmute = bool(ob.get("require_accept_unmute", True)) and not bool(ob.get("require_accept", False))
    if not enabled:
        return
    # If require_unmute is enabled: restrict and instruct to accept rules via deep-link
    if require_unmute:
        try:
            await context.bot.restrict_chat_member(update.effective_chat.id, user.id, permissions=ChatPermissions(can_send_messages=False))
        except Exception as e:
            log.exception("Failed to mute on welcome gid=%s uid=%s: %s", update.effective_chat.id, user.id, e)
        try:
            bot_username = (await context.bot.get_me()).username or ""
            payload = (
                f"rulesu_{update.effective_chat.username}"
                if getattr(update.effective_chat, "username", None)
                else f"rules64_{base64.urlsafe_b64encode(str(update.effective_chat.id).encode()).decode().rstrip('=')}"
            )
            deep = f"https://t.me/{bot_username}?start={payload}"
            text = t(
                lang,
                "welcome.must_accept",
                first_name=user.first_name or "",
                group_title=update.effective_chat.title or "",
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "welcome.read_accept"), url=deep)]])
            m = await context.bot.send_message(update.effective_chat.id, text, reply_markup=kb)
            if ttl and ttl > 0:
                async def _del(ctx: ContextTypes.DEFAULT_TYPE):
                    try:
                        await ctx.bot.delete_message(update.effective_chat.id, m.message_id)
                    except Exception as e:
                        log.exception("Failed to auto-delete welcome gid=%s mid=%s: %s", update.effective_chat.id, m.message_id, e)
                context.job_queue.run_once(_del, when=ttl)
        except Exception as e:
            log.exception("Failed sending welcome with deep-link gid=%s: %s", update.effective_chat.id, e)
        return
    # Regular welcome
    text = (
        template.format(first_name=user.first_name or "", group_title=update.effective_chat.title or "")
        if template
        else t(lang, "welcome.message", first_name=user.first_name or "", group_title=update.effective_chat.title or "")
    )
    m = await context.bot.send_message(update.effective_chat.id, text)
    if ttl and ttl > 0:
        async def _del2(ctx: ContextTypes.DEFAULT_TYPE):
            try:
                await ctx.bot.delete_message(update.effective_chat.id, m.message_id)
            except Exception as e:
                log.exception("Failed to auto-delete welcome (regular) gid=%s mid=%s: %s", update.effective_chat.id, m.message_id, e)
        context.job_queue.run_once(_del2, when=ttl)
