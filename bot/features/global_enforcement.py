"""Global enforcement of blacklist violations across all groups."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from telegram import Update, ChatPermissions
from telegram.ext import Application, ContextTypes, MessageHandler, ChatMemberHandler, filters

from ..core.i18n import I18N, t
from ..infra import db
from ..infra.global_violators_repo import GlobalViolatorsRepo

log = logging.getLogger(__name__)


async def check_global_violator_on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if message sender is a global violator and apply penalty."""
    if not update.effective_chat or not update.effective_user:
        return
    
    # Only check in groups
    if update.effective_chat.type == "private":
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Check if user is a global violator
    async with db.SessionLocal() as s:  # type: ignore
        violator = await GlobalViolatorsRepo(s).get_violator(user_id)
        
        if not violator:
            return
        
        # User is a global violator - apply the penalty
        action = violator.action
        lang = I18N.pick_lang(update)
        
        try:
            if action == "mute":
                # Calculate remaining time
                if violator.expires_at:
                    until = int(violator.expires_at.timestamp())
                else:
                    until = int(time.time()) + 3600  # Default 1 hour
                
                await context.bot.restrict_chat_member(
                    chat_id,
                    user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                
                # Delete the message
                try:
                    await context.bot.delete_message(chat_id, update.effective_message.message_id)
                except Exception:
                    pass
                
                # Notify once per group (store in chat_data to avoid spam)
                notify_key = f"notified_violator_{user_id}"
                if not context.chat_data.get(notify_key):
                    context.chat_data[notify_key] = True
                    words_text = ", ".join(violator.matched_words[:3])
                    if len(violator.matched_words) > 3:
                        words_text += "..."
                    await context.bot.send_message(
                        chat_id,
                        t(lang, "global.violator.muted", words=words_text)
                    )
                
            elif action == "ban":
                # Calculate remaining time
                if violator.expires_at:
                    until = int(violator.expires_at.timestamp())
                else:
                    until = int(time.time()) + 86400  # Default 24 hours
                
                await context.bot.ban_chat_member(
                    chat_id,
                    user_id,
                    until_date=until
                )
                
                # Notify
                words_text = ", ".join(violator.matched_words[:3])
                if len(violator.matched_words) > 3:
                    words_text += "..."
                await context.bot.send_message(
                    chat_id,
                    t(lang, "global.violator.banned", words=words_text)
                )
                
        except Exception as e:
            log.error(f"Failed to enforce global penalty on user {user_id} in chat {chat_id}: {e}")


async def check_global_violator_on_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if new member is a global violator and apply penalty."""
    if not update.effective_chat:
        return
    
    # Only check in groups
    if update.effective_chat.type == "private":
        return
    
    chat_id = update.effective_chat.id
    
    # Get new members
    new_members = []
    if update.message and update.message.new_chat_members:
        new_members = update.message.new_chat_members
    elif update.chat_member and update.chat_member.new_chat_member:
        member = update.chat_member.new_chat_member
        if member.status in ["member", "restricted"]:
            new_members = [member.user]
    
    if not new_members:
        return
    
    for user in new_members:
        if user.is_bot:
            continue
        
        # Check if user is a global violator
        async with db.SessionLocal() as s:  # type: ignore
            violator = await GlobalViolatorsRepo(s).get_violator(user.id)
            
            if not violator:
                continue
            
            # User is a global violator - apply the penalty
            action = violator.action
            lang = I18N.pick_lang(update)
            
            try:
                if action == "warn":
                    # Just notify admins
                    words_text = ", ".join(violator.matched_words[:3])
                    if len(violator.matched_words) > 3:
                        words_text += "..."
                    await context.bot.send_message(
                        chat_id,
                        t(lang, "global.violator.join_warn", name=user.first_name, words=words_text)
                    )
                    
                elif action == "mute":
                    # Mute immediately on join
                    if violator.expires_at:
                        until = int(violator.expires_at.timestamp())
                    else:
                        until = int(time.time()) + 3600  # Default 1 hour
                    
                    await context.bot.restrict_chat_member(
                        chat_id,
                        user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=until
                    )
                    
                    words_text = ", ".join(violator.matched_words[:3])
                    if len(violator.matched_words) > 3:
                        words_text += "..."
                    await context.bot.send_message(
                        chat_id,
                        t(lang, "global.violator.join_muted", name=user.first_name, words=words_text)
                    )
                    
                elif action == "ban":
                    # Ban immediately on join
                    if violator.expires_at:
                        until = int(violator.expires_at.timestamp())
                    else:
                        until = int(time.time()) + 86400  # Default 24 hours
                    
                    await context.bot.ban_chat_member(
                        chat_id,
                        user.id,
                        until_date=until
                    )
                    
                    words_text = ", ".join(violator.matched_words[:3])
                    if len(violator.matched_words) > 3:
                        words_text += "..."
                    await context.bot.send_message(
                        chat_id,
                        t(lang, "global.violator.join_banned", name=user.first_name, words=words_text)
                    )
                    
            except Exception as e:
                log.error(f"Failed to enforce global penalty on new member {user.id} in chat {chat_id}: {e}")


async def check_join_request_violator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if join request is from a global violator and handle accordingly."""
    if not update.chat_join_request:
        return
    
    user = update.chat_join_request.from_user
    chat_id = update.chat_join_request.chat.id
    
    # Check if user is a global violator
    async with db.SessionLocal() as s:  # type: ignore
        violator = await GlobalViolatorsRepo(s).get_violator(user.id)
        
        if not violator:
            # Not a violator, let other handlers process this request
            return
        
        # For banned violators: accept then immediately kick
        # This provides better UX - they see they were kicked for violating rules
        if violator.action == "ban":
            try:
                # First approve the request
                await context.bot.approve_chat_join_request(chat_id, user.id)
                log.info(f"Approved join request from global violator {user.id} to kick them")
                
                # Wait a moment for the user to join
                await asyncio.sleep(0.5)
                
                # Then immediately ban them
                await context.bot.ban_chat_member(chat_id, user.id)
                log.info(f"Kicked global violator {user.id} from chat {chat_id}")
                
                # Send notification to the group
                lang = I18N.pick_lang(update)
                words_preview = ", ".join(violator.matched_words[:3])
                if len(violator.matched_words) > 3:
                    words_preview += "..."
                
                msg = t(lang, "global.violator.join_banned", 
                       name=user.first_name or "User",
                       words=words_preview)
                await context.bot.send_message(chat_id, msg)
                
            except Exception as e:
                log.error(f"Failed to handle banned violator {user.id}: {e}")


def register(app: Application) -> None:
    """Register global enforcement handlers."""
    # Check on every message (high priority to run early)
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.StatusUpdate.ALL,
            check_global_violator_on_message
        ),
        group=-50  # Very high priority
    )
    
    # Check when users join
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            check_global_violator_on_join
        ),
        group=-50
    )
    
    # Check join requests - run AFTER normal onboarding (group 1 instead of -50)
    # This way, normal join request handling happens first, and we only decline if they're banned violators
    from telegram.ext import ChatJoinRequestHandler
    app.add_handler(
        ChatJoinRequestHandler(check_join_request_violator),
        group=1  # Lower priority - runs after normal handlers (group 0)
    )
    
    # Also check on chat member updates
    app.add_handler(
        ChatMemberHandler(check_global_violator_on_join),
        group=-50
    )
    
    log.info("Global enforcement handlers registered")