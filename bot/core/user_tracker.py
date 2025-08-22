"""Centralized user tracking middleware.

This module ensures that every user interaction is tracked and stored in the database.
It provides middleware that can be attached to all handlers to automatically track users.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.ext import Application, ContextTypes, BaseHandler

from ..infra import db
from ..infra.repos import UsersRepo

log = logging.getLogger(__name__)


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Track user interaction and update database.
    
    This function extracts user information from any update type and
    ensures it's stored/updated in the database.
    """
    user = None
    
    # Try to get user from various update types
    if update.effective_user:
        user = update.effective_user
    elif update.message and update.message.from_user:
        user = update.message.from_user
    elif update.edited_message and update.edited_message.from_user:
        user = update.edited_message.from_user
    elif update.channel_post and update.channel_post.from_user:
        user = update.channel_post.from_user
    elif update.edited_channel_post and update.edited_channel_post.from_user:
        user = update.edited_channel_post.from_user
    elif update.inline_query and update.inline_query.from_user:
        user = update.inline_query.from_user
    elif update.chosen_inline_result and update.chosen_inline_result.from_user:
        user = update.chosen_inline_result.from_user
    elif update.callback_query and update.callback_query.from_user:
        user = update.callback_query.from_user
    elif update.shipping_query and update.shipping_query.from_user:
        user = update.shipping_query.from_user
    elif update.pre_checkout_query and update.pre_checkout_query.from_user:
        user = update.pre_checkout_query.from_user
    elif update.poll_answer and update.poll_answer.user:
        user = update.poll_answer.user
    elif update.my_chat_member and update.my_chat_member.from_user:
        user = update.my_chat_member.from_user
    elif update.chat_member and update.chat_member.from_user:
        user = update.chat_member.from_user
    elif update.chat_join_request and update.chat_join_request.from_user:
        user = update.chat_join_request.from_user
    
    if not user:
        return
    
    # Skip bots unless explicitly needed
    if getattr(user, 'is_bot', False):
        return
    
    try:
        async with db.SessionLocal() as s:  # type: ignore
            await UsersRepo(s).upsert_user(
                uid=user.id,
                username=getattr(user, 'username', None),
                first_name=getattr(user, 'first_name', None),
                last_name=getattr(user, 'last_name', None),
                language=getattr(user, 'language_code', None),
            )
            await s.commit()
            
        # Log at debug level to avoid spamming logs
        log.debug(f"Updated user {user.id} ({user.username or 'no username'}) - last seen updated")
    except Exception as e:
        log.error(f"Failed to track user {user.id}: {e}")


class UserTrackingMiddleware:
    """Middleware that automatically tracks users on every update."""
    
    def __init__(self, handler: BaseHandler):
        self.handler = handler
        
    async def handle_update(
        self,
        update: Update,
        application: Application,
        check_result: object,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> object:
        """Wrap the handler to track users before processing."""
        # Track user first
        await track_user(update, context)
        
        # Then call the actual handler
        return await self.handler.handle_update(update, application, check_result, context)
    
    def check_update(self, update: Update) -> Optional[object]:
        """Pass through to the wrapped handler's check."""
        return self.handler.check_update(update)


def wrap_handler_with_tracking(handler: BaseHandler) -> BaseHandler:
    """Wrap a handler with user tracking middleware.
    
    This ensures that user data is tracked before the handler runs.
    """
    # Create a wrapper that preserves the handler's properties
    wrapper = UserTrackingMiddleware(handler)
    
    # Copy over important attributes
    wrapper.check_update = handler.check_update
    
    # Return the wrapped handler
    return wrapper


def register_user_tracking(app: Application) -> None:
    """Register global user tracking for all handlers.
    
    This should be called early in the application setup to ensure
    all handlers benefit from automatic user tracking.
    """
    # Add a pre-processor that runs before all handlers
    async def track_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Pre-process all updates to track users."""
        await track_user(update, context)
    
    # Register as a very early handler (group -100) that doesn't block
    from telegram.ext import (
        MessageHandler, CallbackQueryHandler, ChatJoinRequestHandler,
        ChatMemberHandler, InlineQueryHandler, ChosenInlineResultHandler,
        filters
    )
    
    # Track on all message types (includes edits, channel posts, etc.)
    app.add_handler(
        MessageHandler(filters.ALL, track_all_users),
        group=-100
    )
    
    # Track on all callback queries (button clicks)
    app.add_handler(
        CallbackQueryHandler(track_all_users),
        group=-100
    )
    
    # Track on chat join requests
    app.add_handler(
        ChatJoinRequestHandler(track_all_users),
        group=-100
    )
    
    # Track on chat member updates (joins, leaves, etc.)
    app.add_handler(
        ChatMemberHandler(track_all_users, ChatMemberHandler.ANY_CHAT_MEMBER),
        group=-100
    )
    
    # Track on inline queries if used
    app.add_handler(
        InlineQueryHandler(track_all_users),
        group=-100
    )
    
    # Track on chosen inline results if used
    app.add_handler(
        ChosenInlineResultHandler(track_all_users),
        group=-100
    )
    
    log.info("User tracking middleware registered for all update types")


async def get_user_stats() -> dict:
    """Get statistics about tracked users.
    
    Returns a dictionary with user statistics.
    """
    async with db.SessionLocal() as s:  # type: ignore
        from sqlalchemy import select, func
        from ..infra.models import User
        
        total_users = await s.execute(select(func.count()).select_from(User))
        total = total_users.scalar_one()
        
        # Users seen in last 24 hours
        from datetime import datetime, timedelta
        yesterday = datetime.utcnow() - timedelta(days=1)
        active_users = await s.execute(
            select(func.count()).select_from(User).where(User.seen_at >= yesterday)
        )
        active_24h = active_users.scalar_one()
        
        # Users seen in last 7 days
        week_ago = datetime.utcnow() - timedelta(days=7)
        active_week = await s.execute(
            select(func.count()).select_from(User).where(User.seen_at >= week_ago)
        )
        active_7d = active_week.scalar_one()
        
        # Users with usernames
        with_username = await s.execute(
            select(func.count()).select_from(User).where(User.username.isnot(None))
        )
        has_username = with_username.scalar_one()
        
        return {
            'total': total,
            'active_24h': active_24h,
            'active_7d': active_7d,
            'with_username': has_username,
            'without_username': total - has_username,
        }