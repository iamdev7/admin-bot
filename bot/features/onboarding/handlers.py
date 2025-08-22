from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatPermissions
from telegram.ext import ContextTypes
import logging
import base64
import random
import time

from ...infra import db
from ...infra.settings_repo import SettingsRepo
from ...core.permissions import require_admin
from ...core.i18n import I18N, t
from ...core.utils import group_default_permissions

log = logging.getLogger(__name__)


async def clear_rules_flag(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the rules_sent flag after timeout. Job data contains the key and user_id."""
    if context.job and context.job.data:
        key = context.job.data.get("key")
        user_id = context.job.data.get("user_id")
        if key and user_id:
            # Access user_data for the specific user
            user_context = context.application.user_data.get(user_id, {})
            if key in user_context:
                user_context.pop(key, None)


async def send_captcha_for_join(req, context: ContextTypes.DEFAULT_TYPE, gid: int, captcha_cfg: dict) -> None:
    """Send CAPTCHA verification after join request approval."""
    user = req.from_user
    lang_code = (user.language_code or "en").split("-")[0]
    mode = captcha_cfg.get("mode", "button")
    timeout = int(captcha_cfg.get("timeout", 120))
    
    # NOTE: We do NOT restrict the user immediately because restricted users 
    # cannot interact with inline buttons in groups. We'll restrict them only
    # if they fail or timeout.
    log.info(f"Preparing CAPTCHA for user {user.id} in group {gid} (not restricting yet to allow button interaction)")
    
    # Prepare CAPTCHA
    answer = None
    text = t(lang_code, "captcha.prompt")
    # Add timeout warning
    text += f"\n⏱ {timeout}s"
    buttons = []
    
    if mode == "math":
        a, b = random.randint(1, 9), random.randint(1, 9)
        answer = a + b
        text = t(lang_code, "captcha.math", a=a, b=b) + f"\n⏱ {timeout}s"
        # Generate options including the correct answer
        options = {answer}
        while len(options) < 3:
            options.add(random.randint(2, 18))
        options = list(sorted(options))
        row = [InlineKeyboardButton(str(opt), callback_data=f"captcha:math:{gid}:{user.id}:{opt}") for opt in options]
        buttons.append(row)
    else:
        buttons.append([InlineKeyboardButton(t(lang_code, "captcha.im_human"), callback_data=f"captcha:ok:{gid}:{user.id}")])
    
    kb = InlineKeyboardMarkup(buttons)
    msg = await context.bot.send_message(gid, text, reply_markup=kb)
    
    # Store pending verification data - use the same structure as verification handler
    if "verify" not in context.bot_data:
        context.bot_data["verify"] = {}
    
    # Import the Pending class from verification module
    from ..verification.handlers import Pending
    
    pending_data = Pending(
        message_id=msg.message_id,
        deadline=time.time() + timeout,
        mode=mode,
        answer=answer
    )
    
    context.bot_data["verify"][(gid, user.id)] = pending_data
    log.info(f"Stored CAPTCHA data for key ({gid}, {user.id}): mode={mode}, answer={answer}, message_id={msg.message_id}")
    
    # Schedule timeout cleanup
    from ..verification.handlers import timeout_kick
    context.job_queue.run_once(
        timeout_kick, 
        when=timeout, 
        data={"chat_id": gid, "user_id": user.id}, 
        name=f"verify:{gid}:{user.id}"
    )
    log.info(f"CAPTCHA sent to user {user.id} in group {gid}, mode: {mode}, timeout: {timeout}s")


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle chat join requests."""
    if not update.chat_join_request:
        log.warning("on_join_request called with no chat_join_request in update")
        return
    
    req = update.chat_join_request
    gid = req.chat.id
    uid = req.from_user.id
    
    log.info(f"Processing join request for user {uid} in group {gid} ({req.chat.title})")
    
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
    
    log.info(f"Join settings for {gid}: auto_approve={approve}, require_accept={require_accept}")

    # Check CAPTCHA settings
    captcha_cfg = None
    async with db.SessionLocal() as s:  # type: ignore
        captcha_cfg = await SettingsRepo(s).get(gid, "captcha") or {"enabled": False}
    captcha_enabled = captcha_cfg.get("enabled", False)
    
    # Logical constraints: 
    # - If require_accept is on, auto_approve should be off (they conflict)
    # - CAPTCHA only works with auto_approve (requires user to be in group)
    if require_accept:
        log.info(f"Require accept is enabled for {gid}, sending rules to user {uid}")
        # Disable auto_approve if require_accept is on
        if approve:
            log.warning(f"Both require_accept and auto_approve are on for {gid}, disabling auto_approve")
            approve = False
        # Attempt DM
        lang_code = (req.from_user.language_code or "en").split("-")[0]
        header = t(lang_code, "rules.dm.header", 
                  group_title=req.chat.title or "", 
                  first_name=req.from_user.first_name or "")
        text = header + "\n\n" + (rules_text or t(lang_code, "rules.default"))
        # Generate deep links for accept/decline to ensure bot conversation starts
        bot_username = (await context.bot.get_me()).username or ""
        # Encode the action with group and user IDs in base64 for cleaner URLs
        accept_payload = base64.urlsafe_b64encode(f"join_accept_{gid}_{uid}".encode()).decode().rstrip('=')
        decline_payload = base64.urlsafe_b64encode(f"join_decline_{gid}_{uid}".encode()).decode().rstrip('=')
        
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t(lang_code, "join.accept"), 
                        url=f"https://t.me/{bot_username}?start={accept_payload}"
                    ),
                    InlineKeyboardButton(
                        t(lang_code, "join.decline"), 
                        url=f"https://t.me/{bot_username}?start={decline_payload}"
                    ),
                ]
            ]
        )
        try:
            # Use user_chat_id to contact users who sent join request (requires bot to have can_invite_users permission)
            target_chat_id = req.user_chat_id
            msg = await context.bot.send_message(target_chat_id, text, reply_markup=kb)
            log.info(f"Successfully sent rules to user {uid} for group {gid}")
            # Store message ID so we can edit it later when user clicks the deep link
            context.application.user_data[uid][f"join_rules_msg_{gid}"] = msg.message_id
            # Mark that we sent rules to avoid duplication when user clicks deep-link
            recent_messages_key = f"rules_sent_{gid}_{req.from_user.id}"
            context.user_data[recent_messages_key] = True
            # Clear flag after some time
            context.job_queue.run_once(
                clear_rules_flag,
                when=300,  # Clear after 5 minutes
                data={"key": recent_messages_key, "user_id": req.from_user.id},
                name=f"clear_rules_{gid}_{req.from_user.id}"
            )
        except Exception as e:
            log.exception("Failed to DM rules for pre-approval gid=%s uid=%s: %s", gid, uid, e)
            # Can't DM; leave pending until the user starts the bot
            log.warning(f"User {uid} needs to start the bot first before joining group {gid}")
            return
        # Leave pending for explicit acceptance
        log.info(f"Join request from {uid} left pending for explicit acceptance in group {gid}")
        return

    if approve:
        log.info(f"Auto-approve is enabled for {gid}, approving user {uid}")
        # If CAPTCHA is enabled, we'll send it after approval
        # Check if we require acceptance to unmute after approval (default True unless require_accept pre-approval is used)
        require_unmute = bool((ob or {}).get("require_accept_unmute", True)) and not bool((ob or {}).get("require_accept", False))
        lang_code = (req.from_user.language_code or "en").split("-")[0]
        # Try to DM rules (without button if CAPTCHA is enabled, since they need to solve CAPTCHA first)
        try:
            header = t(lang_code, "rules.dm.header",
                      group_title=req.chat.title or "",
                      first_name=req.from_user.first_name or "")
            text = header + "\n\n" + (rules_text or t(lang_code, "rules.default"))
            
            # Only add Accept button if CAPTCHA is NOT enabled
            # If CAPTCHA is enabled, user must solve it in the group first
            kb_dm = None
            if not captcha_enabled and require_unmute:
                kb_dm = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t(lang_code, "join.accept"), callback_data=f"rules:accept:{gid}:{req.from_user.id}")]]
                )
            
            target_chat_id = req.user_chat_id
            await context.bot.send_message(target_chat_id, text, reply_markup=kb_dm)
            # Mark that we sent rules to avoid duplication when user clicks deep-link
            recent_messages_key = f"rules_sent_{gid}_{req.from_user.id}"
            context.user_data[recent_messages_key] = True
            # Clear flag after some time
            context.job_queue.run_once(
                clear_rules_flag,
                when=300,  # Clear after 5 minutes
                data={"key": recent_messages_key, "user_id": req.from_user.id},
                name=f"clear_rules_{gid}_{req.from_user.id}"
            )
        except Exception as e:
            log.exception("Failed to DM rules after auto-approve gid=%s uid=%s: %s", gid, req.from_user.id, e)
        # Approve the join
        try:
            await context.bot.approve_chat_join_request(gid, req.from_user.id)
            log.info(f"Approved join request for user {req.from_user.id} in group {gid}")
            
            # If CAPTCHA is enabled, trigger it now
            if captcha_enabled:
                log.info(f"CAPTCHA enabled for {gid}, sending verification to user {req.from_user.id}")
                await send_captcha_for_join(req, context, gid, captcha_cfg)
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
    else:
        # Neither require_accept nor approve is set - leave the request pending
        log.info(f"No auto-approve or require_accept for group {gid}, leaving join request from {uid} pending")
        # The admin will need to manually approve/decline this request


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
    
    # Track this interaction in database to mark user as having interacted with bot
    from ...infra import db
    from ...infra.repos import UsersRepo
    from datetime import datetime
    
    try:
        async with db.SessionLocal() as s:  # type: ignore
            await UsersRepo(s).upsert_user(
                uid=uid,
                username=getattr(update.effective_user, 'username', None),
                first_name=getattr(update.effective_user, 'first_name', None),
                last_name=getattr(update.effective_user, 'last_name', None),
                language=getattr(update.effective_user, 'language_code', None),
            )
            await s.commit()
        log.info(f"Tracked user interaction via join callback: user {uid} for group {gid}")
    except Exception as e:
        log.error(f"Failed to track user interaction: {e}")
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
            # Edit the message to show acceptance and add return button
            text = update.effective_message.text or ""
            text += f"\n\n✅ {t(lang, 'rules.accepted')}"
            await update.effective_message.edit_text(text, reply_markup=return_kb)
        except Exception as e:
            log.exception("Failed to edit message after accept gid=%s uid=%s: %s", gid, uid, e)
        # Note: We don't send a separate confirmation since the message was already edited above
    elif action == "decline":
        lang = I18N.pick_lang(update)
        try:
            await context.bot.decline_chat_join_request(gid, uid)
        except Exception as e:
            log.exception("Failed to decline join gid=%s uid=%s: %s", gid, uid, e)
        # Edit the message to show decline
        try:
            text = update.effective_message.text or ""
            text += f"\n\n❌ {t(lang, 'join.declined')}"
            await update.effective_message.edit_text(text, reply_markup=None)
        except Exception as e:
            log.exception("Failed to edit message after decline gid=%s uid=%s: %s", gid, uid, e)
        # Note: We don't send a separate decline message since the message was already edited above


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
    
    # Track this interaction in database to mark user as having interacted with bot
    from ...infra import db
    from ...infra.repos import UsersRepo
    
    try:
        async with db.SessionLocal() as s:  # type: ignore
            await UsersRepo(s).upsert_user(
                uid=uid,
                username=getattr(update.effective_user, 'username', None),
                first_name=getattr(update.effective_user, 'first_name', None),
                last_name=getattr(update.effective_user, 'last_name', None),
                language=getattr(update.effective_user, 'language_code', None),
            )
            await s.commit()
        log.info(f"Tracked user interaction via rules accept callback: user {uid} for group {gid}")
    except Exception as e:
        log.error(f"Failed to track user interaction: {e}")
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
