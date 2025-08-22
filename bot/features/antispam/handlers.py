from __future__ import annotations

import time
from collections import deque, defaultdict
from datetime import timedelta
from typing import Deque, Dict, Tuple, Optional
from urllib.parse import urlparse
import logging

from telegram import ChatPermissions, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from ...core.i18n import I18N, t
from ...core.ephemeral import reply_ephemeral
from ...core.permissions import require_group_admin
from ...infra import db
from ...infra.repos import AuditRepo, FiltersRepo
from ...infra.settings_repo import SettingsRepo

log = logging.getLogger(__name__)


DEFAULTS = {
    "window_sec": 5,
    "threshold": 8,
    "mute_seconds": 60,
    "ban_seconds": 600,
}


def _store(context: ContextTypes.DEFAULT_TYPE) -> Dict[Tuple[int, int], Deque[float]]:
    bd = context.bot_data
    if "antispam" not in bd:
        bd["antispam"] = defaultdict(lambda: deque(maxlen=50))
    return bd["antispam"]  # type: ignore[return-value]


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    
    # Only enforce antispam in groups, not in private chats
    if update.effective_chat.type == "private":
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    # Global blacklist, links policy, then content rules
    gb = await enforce_global_blacklist(update, context)
    if gb:
        return
    link_handled = await enforce_link_policy(update, context)
    if link_handled:
        return
    handled = await enforce_content_rules(update, context)
    if handled:
        return
    key = (chat_id, user_id)
    dq = _store(context)[key]
    now = time.monotonic()
    dq.append(now)
    # Load config and cull outside window
    cfg = await get_antispam_config(chat_id)
    WINDOW_SEC = cfg["window_sec"]
    while dq and now - dq[0] > WINDOW_SEC:
        dq.popleft()
    THRESHOLD = cfg["threshold"]
    MUTE_SECONDS = cfg["mute_seconds"]
    BAN_SECONDS = cfg["ban_seconds"]
    if len(dq) >= THRESHOLD:
        lang = I18N.pick_lang(update)
        # Escalate: first time warn, second mute, third temp ban
        strikes_key = (chat_id, user_id, "strikes")
        strikes = context.chat_data.get(strikes_key, 0)
        context.chat_data[strikes_key] = strikes + 1
        try:
            if strikes == 0:
                await update.effective_message.reply_text(t(lang, "antispam.warn"))
                async with db.SessionLocal() as s:  # type: ignore
                    await AuditRepo(s).log(chat_id, update.effective_user.id, "antispam.warn", user_id, {"threshold": len(dq)})
                    await s.commit()
            elif strikes == 1:
                await context.bot.restrict_chat_member(
                    chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=int(time.time()) + MUTE_SECONDS
                )
                await update.effective_message.reply_text(t(lang, "antispam.muted"))
                async with db.SessionLocal() as s:  # type: ignore
                    await AuditRepo(s).log(chat_id, update.effective_user.id, "antispam.mute", user_id, {"seconds": MUTE_SECONDS})
                    await s.commit()
            else:
                await context.bot.ban_chat_member(chat_id, user_id, until_date=int(time.time()) + BAN_SECONDS)
                await update.effective_message.reply_text(t(lang, "antispam.banned"))
                async with db.SessionLocal() as s:  # type: ignore
                    await AuditRepo(s).log(chat_id, update.effective_user.id, "antispam.ban", user_id, {"seconds": BAN_SECONDS})
                    await s.commit()
        finally:
            dq.clear()


def _msg_text(update: Update) -> str:
    """Return message text, falling back to caption when present."""
    if not update.effective_message:
        return ""
    msg = update.effective_message
    txt = getattr(msg, "text", None)
    if txt:
        return txt
    cap = getattr(msg, "caption", None)
    return cap or ""


async def get_global_blacklist() -> dict:
    async with db.SessionLocal() as s:  # type: ignore
        from ...infra.settings_repo import SettingsRepo as SR

        cfg = await SR(s).get(0, "global_blacklist") or {"words": [], "action": None}
    return cfg


async def apply_global_penalty(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    action: str,
    matched_word: str,
    duration: Optional[int] = None
) -> None:
    """Apply penalty to user across ALL groups where bot is admin."""
    # Get all groups from database
    async with db.SessionLocal() as s:  # type: ignore
        from sqlalchemy import select
        from ...infra.models import Group
        
        result = await s.execute(select(Group))
        groups = result.scalars().all()
    
    applied_count = 0
    for group in groups:
        try:
            if action == "mute" and duration:
                until = int(time.time()) + duration
                await context.bot.restrict_chat_member(
                    group.id,
                    user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                applied_count += 1
            elif action == "ban" and duration:
                until = int(time.time()) + duration
                await context.bot.ban_chat_member(
                    group.id,
                    user_id,
                    until_date=until
                )
                applied_count += 1
        except Exception as e:
            # User might not be in this group or bot might not have perms
            log.debug(f"Could not apply {action} to user {user_id} in group {group.id}: {e}")
    
    if applied_count > 0:
        log.info(f"Applied global {action} to user {user_id} in {applied_count} groups for violating: {matched_word}")


async def enforce_global_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_message or not update.effective_user:
        return False
    
    # Only enforce in groups, not in private chats
    if update.effective_chat.type == "private":
        return False
    
    text = _msg_text(update)
    if not text:
        return False
    cfg = await get_global_blacklist()
    words = [w.strip().lower() for w in cfg.get("words", []) if isinstance(w, str)]
    if not words:
        return False
    lowered = text.lower()
    matched = next((w for w in words if w and w in lowered), None)
    if not matched:
        return False
    action = (cfg.get("action") or "warn").lower()
    lang = I18N.pick_lang(update)
    gid = update.effective_chat.id
    uid = update.effective_user.id
    
    # Track this user as a global violator
    async with db.SessionLocal() as s:  # type: ignore
        from ...infra.global_violators_repo import GlobalViolatorsRepo
        cfg2 = await get_antispam_config(gid)
        
        # Determine duration based on action
        duration = None
        if action == "mute":
            duration = int(cfg2["mute_seconds"])
        elif action == "ban":
            duration = int(cfg2["ban_seconds"])
        
        # Record the violation globally
        await GlobalViolatorsRepo(s).add_violation(
            user_id=uid,
            matched_word=matched,
            action=action,
            duration_seconds=duration
        )
        await s.commit()
    
    # Delete offending message first when taking action
    try:
        await context.bot.delete_message(gid, update.effective_message.message_id)
    except Exception:
        pass
    
    # Apply the penalty in current group
    if action == "warn":
        await context.bot.send_message(gid, t(lang, "content.warn"))
        await handle_warn_escalation(gid, uid, update, context)
        
        # Apply warn to ALL groups where user is member
        await apply_global_penalty(context, uid, "warn", matched)
        return True
    
    if action == "mute":
        until = int(time.time()) + int(cfg2["mute_seconds"])
        await context.bot.restrict_chat_member(gid, uid, permissions=ChatPermissions(can_send_messages=False), until_date=until)
        await context.bot.send_message(gid, t(lang, "content.muted"))
        
        # Apply mute to ALL groups where user is member
        await apply_global_penalty(context, uid, "mute", matched, duration)
        return True
    
    if action == "ban":
        until = int(time.time()) + int(cfg2["ban_seconds"])
        await context.bot.ban_chat_member(gid, uid, until_date=until)
        await context.bot.send_message(gid, t(lang, "content.banned"))
        
        # Apply ban to ALL groups where user is member
        await apply_global_penalty(context, uid, "ban", matched, duration)
        return True
    
    return True


def register_handlers(app: Application) -> None:
    app.add_handler(MessageHandler(~filters.COMMAND & ~filters.StatusUpdate.ALL, on_any), group=15)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text), group=20)


async def get_antispam_config(group_id: int) -> dict:
    async with db.SessionLocal() as s:  # type: ignore
        data = await SettingsRepo(s).get(group_id, "antispam")
    if not data:
        return DEFAULTS.copy()
    return {**DEFAULTS, **data}


async def enforce_content_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_message or not update.effective_user:
        return False
    
    # Only enforce in groups, not in private chats
    if update.effective_chat.type == "private":
        return False
    
    gid = update.effective_chat.id
    text = _msg_text(update)
    if not text:
        return False
    async with db.SessionLocal() as s:  # type: ignore
        rules = await FiltersRepo(s).list_rules(gid, limit=100)
    import re

    for r in rules:
        matched = False
        if r.type == "word":
            if r.pattern.lower() in text.lower():
                matched = True
        elif r.type == "regex":
            try:
                if re.search(r.pattern, text, flags=re.IGNORECASE):
                    matched = True
            except re.error:
                continue
        if not matched:
            continue
        lang = I18N.pick_lang(update)
        # Per-rule escalation check
        esc = {}
        if isinstance(r.extra, dict):
            esc = r.extra.get("esc") or {}
        eff_action = r.action
        if esc:
            th = int(esc.get("threshold", 0) or 0)
            cd = int(esc.get("cooldown", 0) or 0)
            ea = esc.get("action") or None
            if th and cd and ea:
                now_ts = time.monotonic()
                key = (gid, update.effective_user.id, r.id)
                hits = context.chat_data.setdefault("rule_hits", {})
                dq = hits.get(key)
                if not dq:
                    from collections import deque

                    dq = deque(maxlen=50)
                    hits[key] = dq
                dq.append(now_ts)
                while dq and now_ts - dq[0] > cd:
                    dq.popleft()
                if len(dq) >= th:
                    eff_action = ea
                    dq.clear()
        # Take action
        try:
            if eff_action == "delete":
                await context.bot.delete_message(gid, update.effective_message.message_id)
            elif eff_action == "warn":
                # Delete first, then warn (send as a normal message, not reply)
                try:
                    await context.bot.delete_message(gid, update.effective_message.message_id)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).exception("antispam delete before warn failed gid=%s: %s", gid, e)
                await context.bot.send_message(gid, t(lang, "content.warn"))
                await handle_warn_escalation(gid, update.effective_user.id, update, context)
            elif eff_action == "mute":
                # Delete first, then restrict
                try:
                    await context.bot.delete_message(gid, update.effective_message.message_id)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).exception("antispam delete before mute failed gid=%s: %s", gid, e)
                cfg = await get_antispam_config(gid)
                until = int(time.time()) + int(cfg["mute_seconds"])
                await context.bot.restrict_chat_member(
                    gid,
                    update.effective_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until,
                )
                await context.bot.send_message(gid, t(lang, "content.muted"))
            elif eff_action == "ban":
                # Delete first, then temp-ban
                try:
                    await context.bot.delete_message(gid, update.effective_message.message_id)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).exception("antispam delete before ban failed gid=%s: %s", gid, e)
                cfg = await get_antispam_config(gid)
                until = int(time.time()) + int(cfg["ban_seconds"])
                await context.bot.ban_chat_member(gid, update.effective_user.id, until_date=until)
                await context.bot.send_message(gid, t(lang, "content.banned"))
            elif eff_action == "reply":
                # Auto-reply should NOT delete the message; just reply
                reply_text = r.extra.get("text") if isinstance(r.extra, dict) else None
                if reply_text:
                    await update.effective_message.reply_text(reply_text)
        finally:
            return True
    return False


def _extract_urls(text: str) -> list[str]:
    import re

    url_re = re.compile(r"https?://\S+", re.IGNORECASE)
    return url_re.findall(text)


def _extract_usernames(text: str) -> list[str]:
    """Extract @username mentions from text"""
    import re
    
    username_re = re.compile(r"@[a-zA-Z][a-zA-Z0-9_]{4,31}", re.IGNORECASE)
    return username_re.findall(text)


async def enforce_link_policy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_message or not update.effective_chat or not update.effective_user:
        return False
    
    # Only enforce in groups, not in private chats
    if update.effective_chat.type == "private":
        return False
    
    text = _msg_text(update)
    urls = _extract_urls(text)
    usernames = _extract_usernames(text)
    
    import logging
    log = logging.getLogger(__name__)
    
    if not urls and not usernames:
        return False

    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(update.effective_chat.id, "links") or {
            "denylist": [],
            "allowlist": [],
            "action": "delete",
            "block_all": False,
            "types": {},
        }
        night = await SettingsRepo(s).get(update.effective_chat.id, "links.night") or {
            "enabled": False,
            "from_h": 0,
            "to_h": 6,
            "tz_offset_min": 0,
            "block_all": True,
        }

    if is_night(night):
        if night.get("block_all", True):
            cfg = {**cfg, "block_all": True}

    denylist = set(d.lower() for d in cfg.get("denylist", []))
    allowlist = set(d.lower() for d in cfg.get("allowlist", []))
    block_all = bool(cfg.get("block_all", False))
    default_action = cfg.get("action", "delete")
    type_actions: dict = cfg.get("types", {})

    def in_list(host: str, doms: set[str]) -> bool:
        parts = host.split(".")
        candidates = [host]
        if len(parts) >= 2:
            candidates.append(".".join(parts[-2:]))
        return any(d in candidates for d in doms)

    # Get group username for auto-allow
    group_username = None
    if update.effective_chat.username:
        group_username = f"@{update.effective_chat.username}".lower()
    
    # For now, don't filter usernames - just process them normally
    # The Telegram API doesn't reliably allow checking membership by username
    filtered_usernames = []
    
    for username in usernames:
        username_lower = username.lower()
        
        # Auto-allow group's own username
        if group_username and username_lower == group_username:
            continue
        
        # Auto-allow sender's own username
        if update.effective_user and update.effective_user.username:
            sender_username = f"@{update.effective_user.username}".lower()
            if username_lower == sender_username:
                continue
        
        # Add to filtered list for policy check
        filtered_usernames.append(username)
    
    # Decide action based on each item (URL or username)
    decided_action: str | None = None
    
    # Process URLs
    for u in urls:
        host = (urlparse(u).hostname or "").lower()
        if not host:
            continue
            
        # Auto-allow group's own links (t.me/groupname or telegram.me/groupname)
        if group_username and host in {"t.me", "telegram.me"}:
            path = urlparse(u).path.lower()
            group_name_without_at = group_username[1:]  # Remove @ from username
            # Check if it's a link to the group or a message in the group
            if path.startswith(f"/{group_name_without_at}/") or path == f"/{group_name_without_at}":
                continue  # Skip this URL, it's the group's own link
        
        # Allowlist overrides everything
        if in_list(host, allowlist):
            continue
        # Per-type action
        cat = classify_link(u)
        act = type_actions.get(cat)
        if act and act != "allow":
            decided_action = act
            break
        if act == "allow":
            continue
        # Block all or denylist
        if block_all or in_list(host, denylist):
            decided_action = default_action
            break
    
    # Process filtered usernames if no action decided yet
    if not decided_action and filtered_usernames:
        for username in filtered_usernames:
            # Check username policy
            username_action = type_actions.get("usernames")
            if username_action and username_action != "allow":
                decided_action = username_action
                break
            elif username_action == "allow":
                continue
            
            # Apply default policy if block_all is enabled
            if block_all:
                decided_action = default_action
                break

    if not decided_action or decided_action == "allow":
        return False

    lang = I18N.pick_lang(update)
    if decided_action == "delete":
        try:
            await context.bot.delete_message(update.effective_chat.id, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("links delete failed gid=%s: %s", update.effective_chat.id, e)
        return True
    if decided_action == "warn":
        # Delete first, then warn (send as a normal message)
        try:
            await context.bot.delete_message(update.effective_chat.id, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("links delete before warn failed gid=%s: %s", update.effective_chat.id, e)
        await context.bot.send_message(update.effective_chat.id, t(lang, "content.warn"))
        await handle_warn_escalation(update.effective_chat.id, update.effective_user.id, update, context)
        return True
    cfg2 = await get_antispam_config(update.effective_chat.id)
    if decided_action == "mute":
        until = int(time.time()) + int(cfg2["mute_seconds"])
        # Delete first, then mute
        try:
            await context.bot.delete_message(update.effective_chat.id, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("links delete before mute failed gid=%s: %s", update.effective_chat.id, e)
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            update.effective_user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await context.bot.send_message(update.effective_chat.id, t(lang, "content.muted"))
        return True
    if decided_action == "ban":
        until = int(time.time()) + int(cfg2["ban_seconds"])
        # Delete first, then ban
        try:
            await context.bot.delete_message(update.effective_chat.id, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("links delete before ban failed gid=%s: %s", update.effective_chat.id, e)
        await context.bot.ban_chat_member(update.effective_chat.id, update.effective_user.id, until_date=until)
        await context.bot.send_message(update.effective_chat.id, t(lang, "content.banned"))
        return True
    return False


def is_night(cfg: dict) -> bool:
    if not cfg or not cfg.get("enabled"):
        return False
    from datetime import datetime, timedelta, timezone

    tz_min = int(cfg.get("tz_offset_min", 0) or 0)
    now = datetime.utcnow() + timedelta(minutes=tz_min)
    from_h = int(cfg.get("from_h", 0)) % 24
    to_h = int(cfg.get("to_h", 6)) % 24
    h = now.hour
    if from_h <= to_h:
        return from_h <= h < to_h
    else:
        return h >= from_h or h < to_h


async def on_any(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Forward/media locks and caption/text enforcement for any message
    if not update.effective_chat or not update.effective_user or not update.effective_message:
        return
    
    # Only enforce locks in groups, not in private chats
    if update.effective_chat.type == "private":
        return
    
    gid = update.effective_chat.id
    msg = update.effective_message
    # If message has a caption (media + text), process blacklist/links/rules first
    if getattr(msg, "caption", None):
        if await enforce_global_blacklist(update, context):
            return
        if await enforce_link_policy(update, context):
            return
        if await enforce_content_rules(update, context):
            return
    # Forwards
    if getattr(msg, "forward_date", None) or getattr(msg, "forward_origin", None):
        action = await get_lock_action(gid, "forwards")
        if action and action != "allow":
            await apply_lock_action(action, gid, update.effective_user.id, update, context)
            return
    # Media types
    mtype = detect_media_type(msg)
    if mtype:
        action = await get_lock_action(gid, mtype)
        if action and action != "allow":
            await apply_lock_action(action, gid, update.effective_user.id, update, context)


def detect_media_type(msg) -> str | None:
    if getattr(msg, "photo", None):
        return "photo"
    if getattr(msg, "video", None):
        return "video"
    if getattr(msg, "animation", None):
        return "animation"
    if getattr(msg, "document", None):
        return "document"
    if getattr(msg, "sticker", None):
        return "sticker"
    if getattr(msg, "voice", None):
        return "voice"
    if getattr(msg, "audio", None):
        return "audio"
    if getattr(msg, "video_note", None):
        return "video_note"
    return None


async def get_lock_action(group_id: int, key: str) -> str | None:
    async with db.SessionLocal() as s:  # type: ignore
        locks = await SettingsRepo(s).get(group_id, "locks") or {}
    if key == "forwards":
        return locks.get("forwards") or None
    media = locks.get("media") or {}
    return media.get(key)


async def apply_lock_action(action: str, gid: int, uid: int, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    if action == "delete":
        try:
            await context.bot.delete_message(gid, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("locks delete failed gid=%s: %s", gid, e)
        return
    if action == "warn":
        # Delete first, then warn (send as a normal message)
        try:
            await context.bot.delete_message(gid, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("locks delete before warn failed gid=%s: %s", gid, e)
        await context.bot.send_message(gid, t(lang, "content.warn"))
        await handle_warn_escalation(gid, uid, update, context)
        return
    cfg2 = await get_antispam_config(gid)
    if action == "mute":
        until = int(time.time()) + int(cfg2["mute_seconds"])
        # Delete first, then mute
        try:
            await context.bot.delete_message(gid, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("locks delete before mute failed gid=%s: %s", gid, e)
        await context.bot.restrict_chat_member(
            gid, uid, permissions=ChatPermissions(can_send_messages=False), until_date=until
        )
        await context.bot.send_message(gid, t(lang, "content.muted"))
        return
    if action == "ban":
        until = int(time.time()) + int(cfg2["ban_seconds"])
        # Delete first, then ban
        try:
            await context.bot.delete_message(gid, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("locks delete before ban failed gid=%s: %s", gid, e)
        await context.bot.ban_chat_member(gid, uid, until_date=until)
        await context.bot.send_message(gid, t(lang, "content.banned"))
        return


def classify_link(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower()
    if not host:
        return "other"
    # Telegram invite links
    if host in {"t.me", "telegram.me"}:
        if path.startswith("/joinchat") or path.startswith("/+"):
            return "invites"
        return "telegram"
    if host.startswith("tg://") or url.lower().startswith("tg://join"):
        return "invites"
    # Shorteners
    shorteners = {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "is.gd",
        "ow.ly",
        "rebrand.ly",
        "buff.ly",
        "bit.do",
    }
    if host in shorteners:
        return "shorteners"
    return "other"


async def maybe_delete_offense(gid: int, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "moderation") or {"delete_offense": True}
    if bool(cfg.get("delete_offense", True)):
        try:
            await context.bot.delete_message(gid, update.effective_message.message_id)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("maybe_delete_offense failed gid=%s: %s", gid, e)


async def handle_warn_escalation(gid: int, uid: int, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    async with db.SessionLocal() as s:  # type: ignore
        from ...infra.repos import WarnsRepo

        await WarnsRepo(s).add(gid, uid, reason="content_rule", created_by=uid)
        count = await WarnsRepo(s).count(gid, uid)
        cfgm = await SettingsRepo(s).get(gid, "moderation") or {"warn_limit": 3}
        limit = int(cfgm.get("warn_limit", 3))
        await s.commit()
    if count >= limit:
        cfg2 = await get_antispam_config(gid)
        until = int(time.time()) + int(cfg2["mute_seconds"])
        try:
            await context.bot.restrict_chat_member(
                gid,
                uid,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("warn escalation mute failed gid=%s uid=%s: %s", gid, uid, e)
        async with db.SessionLocal() as s:  # type: ignore
            from ...infra.repos import WarnsRepo

            await WarnsRepo(s).reset(gid, uid)
            await s.commit()


@require_group_admin
async def add_rule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    msg = update.effective_message
    if not msg:
        return
    if len(context.args) < 3:
        return await msg.reply_text(t(lang, "rules.add.usage"))
    ftype = context.args[0].lower()
    action = context.args[1].lower()
    pattern = " ".join(context.args[2:])
    if ftype not in {"word", "regex"} or action not in {"delete", "warn", "mute", "ban"}:
        return await msg.reply_text(t(lang, "rules.add.usage"))
    async with db.SessionLocal() as s:  # type: ignore
        f = await FiltersRepo(s).add_rule(msg.chat_id, ftype, pattern, action, update.effective_user.id)
        await s.commit()
    await msg.reply_text(t(lang, "rules.add.ok", id=f.id))


@require_group_admin
async def list_rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    msg = update.effective_message
    if not msg:
        return
    async with db.SessionLocal() as s:  # type: ignore
        rules = await FiltersRepo(s).list_rules(msg.chat_id, limit=50)
    if not rules:
        return await msg.reply_text(t(lang, "rules.list.empty"))
    lines = [f"#{r.id} [{r.type}/{r.action}] {r.pattern}" for r in rules]
    text = "\n".join(lines)
    await msg.reply_text(text)


@require_group_admin
async def del_rule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    msg = update.effective_message
    if not msg:
        return
    if not context.args or not context.args[0].isdigit():
        return await msg.reply_text(t(lang, "rules.del.usage"))
    rid = int(context.args[0])
    ok = False
    async with db.SessionLocal() as s:  # type: ignore
        ok = await FiltersRepo(s).delete_rule(msg.chat_id, rid)
        await s.commit()
    await msg.reply_text(t(lang, "rules.del.ok" if ok else "rules.del.missing"))
