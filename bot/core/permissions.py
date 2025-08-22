from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from .config import settings


class TTLCache:
    def __init__(self, ttl: float = 15.0) -> None:
        self.ttl = ttl
        self._data: dict[tuple[int, int], tuple[float, bool]] = {}
        self._lock = asyncio.Lock()

    async def get(self, chat_id: int, user_id: int) -> Optional[bool]:
        async with self._lock:
            key = (chat_id, user_id)
            if key in self._data:
                ts, val = self._data[key]
                if time.monotonic() - ts < self.ttl:
                    return val
                self._data.pop(key, None)
        return None

    async def set(self, chat_id: int, user_id: int, val: bool) -> None:
        async with self._lock:
            self._data[(chat_id, user_id)] = (time.monotonic(), val)


_admin_cache = TTLCache(ttl=20)


def is_owner(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in settings.OWNER_IDS)


def require_admin(func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return
        if is_owner(user.id):
            return await func(update, context)
        cached = await _admin_cache.get(chat.id, user.id)
        is_admin = False if cached is None else cached
        if cached is None:
            member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = member.status in (
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            )
            await _admin_cache.set(chat.id, user.id, is_admin)
        if is_admin:
            return await func(update, context)
        # silently ignore non-admins
    return wrapper


def require_group_admin(func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]):
    """Decorator that ensures the command is used in a group and by an admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return
        
        # Only work in groups, not in private chats
        if chat.type == "private":
            return
        
        # Check admin status
        if is_owner(user.id):
            return await func(update, context)
        
        cached = await _admin_cache.get(chat.id, user.id)
        is_admin = False if cached is None else cached
        if cached is None:
            member = await context.bot.get_chat_member(chat.id, user.id)
            is_admin = member.status in (
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            )
            await _admin_cache.set(chat.id, user.id, is_admin)
        if is_admin:
            return await func(update, context)
        # silently ignore non-admins
    return wrapper

