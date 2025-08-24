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
            
            # Create user mention using ID - proper HTML format
            user_mention = f'<a href="tg://user?id={user.id}">{user.first_name or "Member"}</a>'
            
            # Check if admin has set a custom template
            if template:
                # Process admin's custom template
                custom_text = template.replace("{first_name}", user.first_name or "Member")
                custom_text = custom_text.replace("{user_mention}", user_mention)
                
                # Format other placeholders
                try:
                    custom_text = custom_text.format(
                        group_title=update.effective_chat.title or "",
                        user_id=user.id,
                        username=f"@{user.username}" if user.username else ""
                    )
                except KeyError:
                    # If formatting fails, just use the template with basic replacements
                    pass
                
                # ALWAYS add welcome header with user mention (localized)
                header = t(lang, "welcome.header_greeting", user_mention=user_mention)
                text = f"{header}\n\n{custom_text}"
                
                # Add the rules acceptance note if not already in template (localized)
                if "accept" not in text.lower() and "rules" not in text.lower():
                    reminder = t(lang, "welcome.rules_reminder")
                    text += f"\n\n{reminder}"
            else:
                # Use localized message with HTML user mention
                text = t(lang, "welcome.must_accept_professional", 
                        user_mention=user_mention, 
                        group_title=update.effective_chat.title or "")
                
                # If the key doesn't exist (returns the key itself), use a default
                if text == "welcome.must_accept_professional":
                    # Key not found, use default professional message
                    text = (
                        f"👋 Welcome {user_mention}!\n\n"
                        f"You've joined <b>{update.effective_chat.title}</b>.\n\n"
                        f"⚠️ <b>Important:</b> To participate in this community, you must first read and accept our rules.\n\n"
                        f"Please click the button below to review the rules and unlock messaging."
                    )
            
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "welcome.read_accept"), url=deep)]])
            m = await context.bot.send_message(update.effective_chat.id, text, reply_markup=kb, parse_mode="HTML")
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
    # Regular welcome with professional formatting
    # Create user mention using ID (works even without username)
    user_mention = f'<a href="tg://user?id={user.id}">{user.first_name or "Member"}</a>'
    
    # Professional default welcome template
    default_welcome = (
        f"🎉 Welcome {user_mention}!\n\n"
        f"We're delighted to have you join <b>{update.effective_chat.title}</b>.\n\n"
        f"📋 Please take a moment to familiarize yourself with our community guidelines.\n"
        f"💬 Feel free to introduce yourself and engage with our members.\n\n"
        f"If you have any questions, don't hesitate to ask our moderators."
    )
    
    if template:
        # Process admin's custom template
        custom_text = template.replace("{first_name}", user.first_name or "Member")
        custom_text = custom_text.replace("{user_mention}", user_mention)
        
        # Format other placeholders
        try:
            custom_text = custom_text.format(
                group_title=update.effective_chat.title or "",
                user_id=user.id,
                username=f"@{user.username}" if user.username else ""
            )
        except KeyError:
            # If formatting fails, just use the template with basic replacements
            pass
        
        # ALWAYS add welcome header with user mention (localized)
        header = t(lang, "welcome.header_celebration", user_mention=user_mention)
        text = f"{header}\n\n{custom_text}"
    else:
        text = default_welcome
    
    m = await context.bot.send_message(update.effective_chat.id, text, parse_mode="HTML")
    if ttl and ttl > 0:
        async def _del2(ctx: ContextTypes.DEFAULT_TYPE):
            try:
                await ctx.bot.delete_message(update.effective_chat.id, m.message_id)
            except Exception as e:
                log.exception("Failed to auto-delete welcome (regular) gid=%s mid=%s: %s", update.effective_chat.id, m.message_id, e)
        context.job_queue.run_once(_del2, when=ttl)
