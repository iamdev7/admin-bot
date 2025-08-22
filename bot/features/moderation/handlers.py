from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from telegram import ChatPermissions, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
import logging

from ...core.permissions import require_group_admin
from ...core.utils import parse_duration, group_default_permissions
from ...core.i18n import I18N, t
from ...infra import db
from ...infra.repos import AuditRepo, WarnsRepo
from ...infra.settings_repo import SettingsRepo
from ..antispam.handlers import get_antispam_config
log = logging.getLogger(__name__)


def _target_user_id(update: Update) -> Optional[int]:
    msg = update.effective_message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    return None


@require_group_admin
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    target_id = _target_user_id(update)
    reason = " ".join(context.args) if context.args else None
    if not target_id:
        return await update.effective_message.reply_text(t(lang, "mod.reply_to_target"))
    gid = update.effective_chat.id
    async with db.SessionLocal() as s:  # type: ignore
        await WarnsRepo(s).add(gid, target_id, reason, update.effective_user.id)
        count = await WarnsRepo(s).count(gid, target_id)
        cfg = await SettingsRepo(s).get(gid, "moderation") or {"warn_limit": 3}
        limit = int(cfg.get("warn_limit", 3))
        await AuditRepo(s).log(gid, update.effective_user.id, "warn", target_id, {"reason": reason or "", "count": count})
        await s.commit()
    if count >= limit:
        # Escalate: temporary mute
        cfg2 = await get_antispam_config(gid)
        until_date = datetime.utcnow() + timedelta(seconds=int(cfg2["mute_seconds"]))
        try:
            await context.bot.restrict_chat_member(
                gid,
                target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date,
            )
        except Exception as e:
            log.exception("moderation warn escalate mute failed gid=%s uid=%s: %s", gid, target_id, e)
        async with db.SessionLocal() as s:  # type: ignore
            await WarnsRepo(s).reset(gid, target_id)
            await s.commit()
        await update.effective_message.reply_text(t(lang, "mod.warn_limit_reached"))
    else:
        await update.effective_message.reply_text(t(lang, "mod.warned_count", count=count))


@require_group_admin
async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    target_id = _target_user_id(update)
    if not target_id:
        return await update.effective_message.reply_text(t(lang, "mod.reply_to_target"))
    gid = update.effective_chat.id
    ok = False
    async with db.SessionLocal() as s:  # type: ignore
        ok = await WarnsRepo(s).remove_one(gid, target_id)
        await s.commit()
    await update.effective_message.reply_text(t(lang, "mod.unwarned" if ok else "mod.unwarned_none"))


@require_group_admin
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    target_id = _target_user_id(update)
    if not target_id:
        return await update.effective_message.reply_text(t(lang, "mod.reply_to_target"))
    duration = parse_duration(context.args[0]) if context.args else timedelta(minutes=10)
    until_date = None if duration is None else datetime.utcnow() + duration
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date,
        )
    except Exception as e:
        log.exception("moderation mute failed gid=%s uid=%s: %s", update.effective_chat.id, target_id, e)
    async with db.SessionLocal() as s:  # type: ignore
        await AuditRepo(s).log(
            update.effective_chat.id,
            update.effective_user.id,
            "mute",
            target_id,
            {"until": until_date.isoformat() if until_date else None},
        )
        await s.commit()
    await update.effective_message.reply_text(t(lang, "mod.muted"))


@require_group_admin
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    target_id = _target_user_id(update)
    if not target_id:
        return await update.effective_message.reply_text(t(lang, "mod.reply_to_target"))
    try:
        perms = await group_default_permissions(context, update.effective_chat.id)
        await context.bot.restrict_chat_member(update.effective_chat.id, target_id, permissions=perms)
    except Exception as e:
        log.exception("moderation unmute failed gid=%s uid=%s: %s", update.effective_chat.id, target_id, e)
    async with db.SessionLocal() as s:  # type: ignore
        await AuditRepo(s).log(update.effective_chat.id, update.effective_user.id, "unmute", target_id, {})
        await s.commit()
    await update.effective_message.reply_text(t(lang, "mod.unmuted"))


@require_group_admin
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    target_id = _target_user_id(update)
    if not target_id:
        return await update.effective_message.reply_text(t(lang, "mod.reply_to_target"))
    duration = parse_duration(context.args[0]) if context.args else None
    until_date = None if duration is None else datetime.utcnow() + duration
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target_id, until_date=until_date)
    except Exception as e:
        log.exception("moderation ban failed gid=%s uid=%s: %s", update.effective_chat.id, target_id, e)
    async with db.SessionLocal() as s:  # type: ignore
        await AuditRepo(s).log(
            update.effective_chat.id,
            update.effective_user.id,
            "ban",
            target_id,
            {"until": until_date.isoformat() if until_date else None},
        )
        await s.commit()
    await update.effective_message.reply_text(t(lang, "mod.banned"))


@require_group_admin
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    target_id = _target_user_id(update)
    if not target_id:
        return await update.effective_message.reply_text(t(lang, "mod.reply_to_target"))
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target_id, only_if_banned=True)
    except Exception as e:
        log.exception("moderation unban failed gid=%s uid=%s: %s", update.effective_chat.id, target_id, e)
    async with db.SessionLocal() as s:  # type: ignore
        await AuditRepo(s).log(update.effective_chat.id, update.effective_user.id, "unban", target_id, {})
        await s.commit()
    await update.effective_message.reply_text(t(lang, "mod.unbanned"))


@require_group_admin
async def purge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    count = int(context.args[0]) if context.args else 10
    msg = update.effective_message
    if not msg:
        return
    try:
        for mid in range(msg.message_id - count, msg.message_id):
            try:
                await context.bot.delete_message(msg.chat_id, mid)
            except Exception as e:
                log.exception("moderation purge delete failed gid=%s mid=%s: %s", msg.chat_id, mid, e)
    finally:
        await msg.reply_text(t(lang, "mod.purged", count=count))
