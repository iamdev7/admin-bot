"""
Member verification utilities using Telegram Bot API.
No database dependencies - relies solely on get_chat_member.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Tuple

from telegram import Bot, ChatMember
from telegram.error import TelegramError, Forbidden, BadRequest, RetryAfter

log = logging.getLogger(__name__)

# Simple in-memory TTL cache to reduce API calls
_member_cache: dict[Tuple[int, int], Tuple[bool, float]] = {}
CACHE_TTL_SECONDS = 60  # Cache for 1 minute
CACHE_ENABLED = True


async def is_chat_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Check if a user is an active member of a chat.
    
    Args:
        bot: The Bot instance
        chat_id: The chat/group ID
        user_id: The user ID to check
        
    Returns:
        True if user is a member (owner/admin/member/restricted)
        False if user left/banned or on error
        
    Note:
        Uses get_chat_member API call. Cannot resolve username to ID -
        requires numeric user_id. Caches results for 60 seconds.
    """
    # Check cache first
    if CACHE_ENABLED:
        cache_key = (chat_id, user_id)
        if cache_key in _member_cache:
            is_member, timestamp = _member_cache[cache_key]
            if time.time() - timestamp < CACHE_TTL_SECONDS:
                log.debug(f"Cache hit for member check: chat={chat_id}, user={user_id}, member={is_member}")
                return is_member
            else:
                # Expired, remove from cache
                del _member_cache[cache_key]
    
    try:
        # Direct API call to check membership
        member = await bot.get_chat_member(chat_id, user_id)
        
        # Check if user is an active member
        # Status can be: owner, administrator, member, restricted, left, kicked
        is_member = member.status not in [ChatMember.LEFT, ChatMember.KICKED]
        
        # Log the decision
        log.info(
            "Member check",
            extra={
                "event": "member_check",
                "chat_id": chat_id,
                "user_id": user_id,
                "status": member.status,
                "decision": "allow" if is_member else "deny"
            }
        )
        
        # Cache the result
        if CACHE_ENABLED:
            _member_cache[(chat_id, user_id)] = (is_member, time.time())
            # Clean old entries if cache gets too large
            if len(_member_cache) > 1000:
                current_time = time.time()
                _member_cache.clear()  # Simple cleanup - could be optimized
        
        return is_member
        
    except (Forbidden, BadRequest) as e:
        # Bot doesn't have permission or invalid request
        log.warning(f"Cannot check member status: {e}", extra={
            "event": "member_check_error",
            "chat_id": chat_id,
            "user_id": user_id,
            "error": str(e)
        })
        return False
        
    except RetryAfter as e:
        # Rate limited
        log.warning(f"Rate limited, retry after {e.retry_after}s", extra={
            "event": "member_check_rate_limit",
            "chat_id": chat_id,
            "user_id": user_id,
            "retry_after": e.retry_after
        })
        return False
        
    except TelegramError as e:
        # Generic Telegram error
        log.error(f"Telegram error checking member: {e}", extra={
            "event": "member_check_telegram_error",
            "chat_id": chat_id,
            "user_id": user_id,
            "error": str(e)
        })
        return False
        
    except Exception as e:
        # Unexpected error
        log.exception(f"Unexpected error checking member: {e}", extra={
            "event": "member_check_exception",
            "chat_id": chat_id,
            "user_id": user_id,
            "error": str(e)
        })
        return False


async def check_bot_permissions(bot: Bot, chat_id: int) -> bool:
    """
    Check if bot has permission to restrict members in a chat.
    
    Returns:
        True if bot can restrict members, False otherwise
    """
    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        
        # Bot needs to be admin with can_restrict_members permission
        if bot_member.status == ChatMember.ADMINISTRATOR:
            # Check specific permission
            can_restrict = getattr(bot_member, 'can_restrict_members', False)
            if not can_restrict:
                log.warning(f"Bot lacks can_restrict_members permission in chat {chat_id}")
            return can_restrict
        elif bot_member.status == ChatMember.OWNER:
            return True  # Owner can do everything
        else:
            log.warning(f"Bot is not admin in chat {chat_id}, status: {bot_member.status}")
            return False
            
    except TelegramError as e:
        log.error(f"Error checking bot permissions: {e}")
        return False


def clear_member_cache():
    """Clear the member cache."""
    _member_cache.clear()
    log.info("Member cache cleared")


def set_cache_enabled(enabled: bool):
    """Enable or disable caching."""
    global CACHE_ENABLED
    CACHE_ENABLED = enabled
    if not enabled:
        clear_member_cache()
    log.info(f"Member cache {'enabled' if enabled else 'disabled'}")