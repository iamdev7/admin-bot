from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatPermissions
import base64
from telegram.ext import ContextTypes
import logging

from ...infra import db
from ...infra.settings_repo import SettingsRepo
from ...core.permissions import require_admin
from ...core.i18n import I18N, t
from ...core.utils import group_default_permissions

log = logging.getLogger(__name__)


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.chat_join_request:
        return
    req = update.chat_join_request
    gid = req.chat.id
    # If onboarding requires accept, send DM with rules and await response
    approve = False
    require_accept = False
    rules_text = None
    async with db.SessionLocal() as s:  # type: ignore
        auto = await SettingsRepo(s).get(gid, "auto_approve_join") or {"enabled": False}
        ob = await SettingsRepo(s).get(gid, "onboarding") or {"require_accept": False}
        approve = bool(auto.get("enabled"))
        require_accept = bool(ob.get("require_accept"))
        rules_text = await SettingsRepo(s).get_text(gid, "rules")

    if require_accept:
        # Attempt DM
        lang_code = (req.from_user.language_code or "en").split("-")[0]
        header = t(lang_code, "rules.dm.header")
        text = header + "\n\n" + t(
            lang_code,
            "join.dm.text",
            group_title=req.chat.title or "",
            rules=rules_text or t(lang_code, "rules.default"),
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(t(lang_code, "join.accept"), callback_data=f"join:accept:{gid}:{req.from_user.id}"),
                    InlineKeyboardButton(t(lang_code, "join.decline"), callback_data=f"join:decline:{gid}:{req.from_user.id}"),
                ]
            ]
        )
        try:
            await context.bot.send_message(req.from_user.id, text, reply_markup=kb)
            # Mark that we sent rules to avoid duplication when user clicks deep-link
            recent_messages_key = f"rules_sent_{gid}_{req.from_user.id}"
            context.user_data[recent_messages_key] = True
            # Clear flag after some time
            async def clear_flag(ctx: ContextTypes.DEFAULT_TYPE):
                ctx.user_data.pop(recent_messages_key, None)
            context.job_queue.run_once(clear_flag, when=300)  # Clear after 5 minutes
        except Exception as e:
            log.exception("Failed to DM rules for pre-approval gid=%s uid=%s: %s", gid, req.from_user.id, e)
            # Can't DM; leave pending until the user starts the bot
            return
        # Leave pending for explicit acceptance
        return

    if approve:
        # Check if we require acceptance to unmute after approval (default True unless require_accept pre-approval is used)
        require_unmute = bool((ob or {}).get("require_accept_unmute", True)) and not bool((ob or {}).get("require_accept", False))
        lang_code = (req.from_user.language_code or "en").split("-")[0]
        # Try to DM rules with Accept button (even if it fails, proceed)
        try:
            header = t(lang_code, "rules.dm.header")
            text = header + "\n\n" + t(
                lang_code,
                "join.dm.rules",
                group_title=req.chat.title or "",
                rules=rules_text or t(lang_code, "rules.default"),
            )
            kb_dm = InlineKeyboardMarkup(
                [[InlineKeyboardButton(t(lang_code, "join.accept"), callback_data=f"rules:accept:{gid}:{req.from_user.id}")]]
            )
            await context.bot.send_message(req.from_user.id, text, reply_markup=kb_dm)
            # Mark that we sent rules to avoid duplication when user clicks deep-link
            recent_messages_key = f"rules_sent_{gid}_{req.from_user.id}"
            context.user_data[recent_messages_key] = True
            # Clear flag after some time
            async def clear_flag(ctx: ContextTypes.DEFAULT_TYPE):
                ctx.user_data.pop(recent_messages_key, None)
            context.job_queue.run_once(clear_flag, when=300)  # Clear after 5 minutes
        except Exception as e:
            log.exception("Failed to DM rules after auto-approve gid=%s uid=%s: %s", gid, req.from_user.id, e)
        # Approve the join
        try:
            await context.bot.approve_chat_join_request(gid, req.from_user.id)
        except Exception as e:
            log.exception("Failed to approve join request gid=%s uid=%s: %s", gid, req.from_user.id, e)
        # If require_unmute: restrict user and post welcome with deep-link
        if require_unmute:
            try:
                await context.bot.restrict_chat_member(gid, req.from_user.id, permissions=ChatPermissions(can_send_messages=False))
            except Exception as e:
                log.exception("Failed to mute after approve gid=%s uid=%s: %s", gid, req.from_user.id, e)
            try:
                bot_username = (await context.bot.get_me()).username or ""
                # Prefer username-based payload when available to avoid negative ID encoding issues
                payload = (
                    f"rulesu_{req.chat.username}" if getattr(req.chat, "username", None) else f"rules64_{base64.urlsafe_b64encode(str(gid).encode()).decode().rstrip('=')}"
                )
                deep_link = f"https://t.me/{bot_username}?start={payload}"
                lang = lang_code
                text_w = t(
                    lang,
                    "welcome.must_accept",
                    first_name=req.from_user.first_name or "",
                    group_title=req.chat.title or "",
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "welcome.read_accept"), url=deep_link)]])
                m = await context.bot.send_message(gid, text_w, reply_markup=kb)
                # Schedule auto-delete if TTL configured
                async def _delete_job(ctx: ContextTypes.DEFAULT_TYPE):
                    try:
                        await ctx.bot.delete_message(gid, m.message_id)
                    except Exception as e:
                        log.exception("Failed to auto-delete welcome gid=%s mid=%s: %s", gid, m.message_id, e)

                # Read TTL from welcome settings
                try:
                    async with db.SessionLocal() as s:  # type: ignore
                        wcfg = await SettingsRepo(s).get(gid, "welcome") or {}
                        ttl = int(wcfg.get("ttl_sec", 0) or 0)
                except Exception as e:
                    log.exception("Failed reading welcome ttl gid=%s: %s", gid, e)
                    ttl = 0
                if ttl and ttl > 0:
                    context.job_queue.run_once(_delete_job, when=ttl)
            except Exception as e:
                log.exception("Failed to post welcome with deep-link gid=%s: %s", gid, e)


@require_admin
async def toggle_auto_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    msg = update.effective_message
    if not msg:
        return
    if not context.args or context.args[0].lower() not in {"on", "off"}:
        return await msg.reply_text(t(lang, "join.usage"))
    enabled = context.args[0].lower() == "on"
    async with db.SessionLocal() as s:  # type: ignore
        await SettingsRepo(s).set(msg.chat_id, "auto_approve_join", {"enabled": enabled})
        await s.commit()
    await msg.reply_text(t(lang, "join.set", state="ON" if enabled else "OFF"))


async def on_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    data = (update.callback_query.data or "").split(":")
    if len(data) != 4:
        return
    action, gid_s, uid_s = data[1], data[2], data[3]
    gid = int(gid_s)
    uid = int(uid_s)
    if not update.effective_user or update.effective_user.id != uid:
        return
    if action == "accept":
        try:
            await context.bot.approve_chat_join_request(gid, uid)
        except Exception as e:
            log.exception("Failed to approve from pre-approval accept gid=%s uid=%s: %s", gid, uid, e)
        # Edit only the buttons on the original DM to a Return button, keep rules text
        lang = I18N.pick_lang(update)
        return_kb = None
        try:
            chat = await context.bot.get_chat(gid)
            if getattr(chat, "username", None):
                url = f"https://t.me/{chat.username}"
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                return_kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(lang, "rules.return_group"), url=url)]]
                )
        except Exception as e:
            log.exception("Failed building return button via get_chat gid=%s: %s", gid, e)
            return_kb = None
        if return_kb is None:
            # Fallback to DB username
            try:
                from ...infra.models import Group
                async with db.SessionLocal() as s:  # type: ignore
                    g = await s.get(Group, gid)
                    if g and g.username:
                        url = f"https://t.me/{g.username}"
                        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                        return_kb = InlineKeyboardMarkup(
                            [[InlineKeyboardButton(t(lang, "rules.return_group"), url=url)]]
                        )
            except Exception:
                return_kb = None
        try:
            await update.effective_message.edit_reply_markup(return_kb)
        except Exception as e:
            log.exception("Failed to edit reply markup on rules DM gid=%s uid=%s: %s", gid, uid, e)
        # Send a thank-you message below
        try:
            await update.effective_message.reply_text(t(lang, "rules.accepted"))
        except Exception as e:
            log.exception("Failed to send thank-you below rules gid=%s uid=%s: %s", gid, uid, e)
    elif action == "decline":
        try:
            await context.bot.decline_chat_join_request(gid, uid)
        except Exception as e:
            log.exception("Failed to decline join gid=%s uid=%s: %s", gid, uid, e)
        # Remove the buttons from the message
        try:
            await update.effective_message.edit_reply_markup(None)
        except Exception as e:
            log.exception("Failed to remove buttons after decline gid=%s uid=%s: %s", gid, uid, e)
        lang = I18N.pick_lang(update)
        await update.effective_message.reply_text(t(lang, "join.declined"))


async def on_rules_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    data = (update.callback_query.data or "").split(":")
    if len(data) != 4:
        return
    _, _, gid_s, uid_s = data
    gid = int(gid_s)
    uid = int(uid_s)
    if not update.effective_user or update.effective_user.id != uid:
        return
    # Unmute first (restore group default permissions)
    try:
        perms = await group_default_permissions(context, gid)
        await context.bot.restrict_chat_member(gid, uid, permissions=perms)
    except Exception as e:
        log.exception("Failed to unmute on rules accept gid=%s uid=%s: %s", gid, uid, e)
    # Replace only the buttons on the original rules message; keep rules visible
    lang = I18N.pick_lang(update)
    return_kb = None
    try:
        chat = await context.bot.get_chat(gid)
        if getattr(chat, "username", None):
            url = f"https://t.me/{chat.username}"
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            return_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "rules.return_group"), url=url)]])
    except Exception as e:
        log.exception("Failed building return button via get_chat (rules accept) gid=%s: %s", gid, e)
        return_kb = None
    if return_kb is None:
        # Fallback to DB username
        try:
            from ...infra.models import Group
            async with db.SessionLocal() as s:  # type: ignore
                g = await s.get(Group, gid)
                if g and g.username:
                    url = f"https://t.me/{g.username}"
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    return_kb = InlineKeyboardMarkup(
                        [[InlineKeyboardButton(t(lang, "rules.return_group"), url=url)]]
                    )
        except Exception:
            return_kb = None
    # Update only reply markup on the original rules message
    try:
        await update.effective_message.edit_reply_markup(return_kb)
    except Exception as e:
        log.exception("Failed to edit reply markup (rules accept) gid=%s uid=%s: %s", gid, uid, e)
    # Check if there's a reminder message to edit, otherwise send new thank-you
    reminder_msg_key = f"reminder_msg_{gid}_{uid}"
    reminder_msg_id = context.user_data.get(reminder_msg_key)
    
    if reminder_msg_id:
        # Edit the reminder message instead of sending a new one
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=reminder_msg_id,
                text=t(lang, "rules.accepted")
            )
            # Clean up the stored message ID
            context.user_data.pop(reminder_msg_key, None)
        except Exception as e:
            log.exception("Failed to edit reminder message, sending new one: %s", e)
            # Fall back to sending new message if edit fails
            try:
                await update.effective_message.reply_text(t(lang, "rules.accepted"))
            except Exception as e2:
                log.exception("Failed to send thank-you (rules accept) gid=%s uid=%s: %s", gid, uid, e2)
    else:
        # No reminder message, send new thank-you message
        try:
            await update.effective_message.reply_text(t(lang, "rules.accepted"))
        except Exception as e:
            log.exception("Failed to send thank-you (rules accept) gid=%s uid=%s: %s", gid, uid, e)
