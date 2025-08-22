from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from telegram import ChatPermissions
import logging

log = logging.getLogger(__name__)


_DUR_RE = re.compile(r"^(?P<num>\d+)(?P<unit>[smhd])$", re.IGNORECASE)


def parse_duration(spec: str | None) -> timedelta | None:
    if not spec:
        return None
    s = spec.strip().lower()
    if s in {"perm", "permanent", "forever"}:
        return None
    m = _DUR_RE.match(s)
    if not m:
        raise ValueError("Invalid duration. Use 30s, 10m, 2h, 3d, or perm")
    num = int(m.group("num"))
    unit = m.group("unit")
    if unit == "s":
        return timedelta(seconds=num)
    if unit == "m":
        return timedelta(minutes=num)
    if unit == "h":
        return timedelta(hours=num)
    if unit == "d":
        return timedelta(days=num)
    raise ValueError("Invalid duration unit")


async def group_default_permissions(context: Any, chat_id: int) -> ChatPermissions:
    """Fetch the chat's default member permissions and use them to unrestrict users.

    Falls back to allowing basic messages if defaults are unavailable.
    """
    try:
        chat = await context.bot.get_chat(chat_id)
        perms = getattr(chat, "permissions", None)
        if isinstance(perms, ChatPermissions):
            return perms
    except Exception as e:
        log.error("Failed to get chat permissions for chat_id=%s: %s", chat_id, e)
    # Minimal safe fallback: allow sending messages; other capabilities follow group defaults.
    try:
        return ChatPermissions(can_send_messages=True)
    except Exception:
        # Last resort (API differences): construct empty then set attribute
        p = ChatPermissions()
        try:
            setattr(p, "can_send_messages", True)
        except Exception as e:
            log.error("Failed to set can_send_messages attribute: %s", e)
        return p
