"""Professional navigation system for bot admin panel.

This module provides state-based navigation with message editing
to minimize message clutter and provide smooth UX.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ...core.i18n import I18N, t

log = logging.getLogger(__name__)


class BotAdminState(Enum):
    """Navigation states for bot admin panel."""
    HOME = "home"
    BROADCAST_MENU = "broadcast_menu"
    BROADCAST_CONFIRM = "broadcast_confirm"
    BROADCAST_WAIT = "broadcast_wait"
    STATS = "stats"
    BLACKLIST = "blacklist"
    BLACKLIST_ADD = "blacklist_add"
    BLACKLIST_IMPORT = "blacklist_import"


class Navigator:
    """Handles navigation with proper message editing."""
    
    @staticmethod
    async def edit_or_send(
        update: Update,
        text: str,
        keyboard: list[list[InlineKeyboardButton]],
        parse_mode: Optional[str] = None
    ) -> None:
        """Edit existing message or send new one if can't edit."""
        markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        try:
            # Try to edit if this is a callback
            if update.callback_query and update.callback_query.message:
                await update.callback_query.message.edit_text(
                    text=text,
                    reply_markup=markup,
                    parse_mode=parse_mode
                )
            else:
                # Send new message
                await update.effective_message.reply_text(
                    text=text,
                    reply_markup=markup,
                    parse_mode=parse_mode
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Message content is same, ignore
                return
            elif "Message can't be edited" in str(e):
                # Message too old, send new one
                await update.effective_message.reply_text(
                    text=text,
                    reply_markup=markup,
                    parse_mode=parse_mode
                )
            else:
                log.error(f"Failed to edit/send message: {e}")
    
    @staticmethod
    def get_home_keyboard(lang: str) -> list[list[InlineKeyboardButton]]:
        """Get home menu keyboard."""
        return [
            [InlineKeyboardButton(t(lang, "botadm.broadcast"), callback_data="botadm:nav:broadcast_menu")],
            [InlineKeyboardButton(t(lang, "botadm.stats"), callback_data="botadm:nav:stats")],
            [InlineKeyboardButton(t(lang, "botadm.global_blacklist"), callback_data="botadm:nav:blacklist")],
            [InlineKeyboardButton(t(lang, "botadm.violators"), callback_data="botadm:nav:violators")],
        ]
    
    @staticmethod
    def get_broadcast_keyboard(lang: str) -> list[list[InlineKeyboardButton]]:
        """Get broadcast menu keyboard."""
        return [
            [InlineKeyboardButton(t(lang, "botadm.to_groups"), callback_data="botadm:bc:target:groups")],
            [InlineKeyboardButton(t(lang, "botadm.to_users"), callback_data="botadm:bc:target:users")],
            [InlineKeyboardButton(t(lang, "botadm.to_chatid"), callback_data="botadm:bc:target:chatid")],
            [InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:home")],
        ]
    
    @staticmethod
    async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Navigate to home screen."""
        lang = I18N.pick_lang(update)
        
        # Clear any pending states
        context.user_data.pop("botadm_wait_chatid", None)
        context.user_data.pop("botadm_wait_content", None)
        context.user_data.pop("botadm_wait_word", None)
        context.user_data.pop("botadm_wait_import", None)
        context.user_data.pop("botadm_broadcast", None)
        
        await Navigator.edit_or_send(
            update,
            t(lang, "botadm.title"),
            Navigator.get_home_keyboard(lang)
        )
    
    @staticmethod
    async def go_broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Navigate to broadcast menu."""
        lang = I18N.pick_lang(update)
        
        # Clear broadcast-specific states
        context.user_data.pop("botadm_wait_chatid", None)
        context.user_data.pop("botadm_wait_content", None)
        context.user_data.pop("botadm_broadcast", None)
        
        await Navigator.edit_or_send(
            update,
            t(lang, "botadm.bc.title"),
            Navigator.get_broadcast_keyboard(lang)
        )
    
    @staticmethod
    async def go_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show stats with back button."""
        from ...infra import db
        from sqlalchemy import select, func
        from ...infra.models import Group, User, Job, AuditLog
        from datetime import datetime, timedelta
        
        lang = I18N.pick_lang(update)
        
        async with db.SessionLocal() as s:  # type: ignore
            groups = int((await s.execute(select(func.count()).select_from(Group))).scalar_one())
            users = int((await s.execute(select(func.count()).select_from(User))).scalar_one())
            autos = int((await s.execute(select(func.count()).select_from(Job))).scalar_one())
            violations = int((await s.execute(select(func.count()).select_from(AuditLog))).scalar_one())
            
            # Enhanced user stats
            yesterday = datetime.utcnow() - timedelta(days=1)
            week_ago = datetime.utcnow() - timedelta(days=7)
            
            active_24h = int((await s.execute(
                select(func.count()).select_from(User).where(User.seen_at >= yesterday)
            )).scalar_one())
            
            active_7d = int((await s.execute(
                select(func.count()).select_from(User).where(User.seen_at >= week_ago)
            )).scalar_one())
        
        text = (
            f"📊 **Bot Statistics**\n\n"
            f"👥 **Users:** {users} total\n"
            f"  • Active (24h): {active_24h}\n"
            f"  • Active (7d): {active_7d}\n\n"
            f"💬 **Groups:** {groups}\n"
            f"🤖 **Automations:** {autos}\n"
            f"⚠️ **Violations:** {violations}"
        )
        
        keyboard = [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:home")]]
        
        await Navigator.edit_or_send(update, text, keyboard, parse_mode="Markdown")
    
    @staticmethod
    async def go_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
        """Navigate to blacklist management with pagination."""
        from ...infra import db
        from ...infra.settings_repo import SettingsRepo
        
        lang = I18N.pick_lang(update)
        
        # Clear blacklist states
        context.user_data.pop("botadm_wait_word", None)
        context.user_data.pop("botadm_wait_import", None)
        
        async with db.SessionLocal() as s:  # type: ignore
            cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
        
        words = list(cfg.get("words", []))
        action = cfg.get("action", "warn")
        
        # Pagination settings
        page_size = 20
        start = page * page_size
        end = start + page_size
        displayed_words = words[start:end]
        total_pages = (len(words) + page_size - 1) // page_size if words else 1
        
        # Build text list of words
        text = f"**{t(lang, 'botadm.blacklist.title')} ({len(words)})**\n"
        if words:
            text += f"_Page {page + 1} of {total_pages}_\n\n"
        
        if displayed_words:
            for i, word in enumerate(displayed_words, start + 1):
                # Truncate very long words for display
                display_word = word[:50] + "..." if len(word) > 50 else word
                text += f"{i}. {display_word}\n"
        elif not words:
            text += t(lang, "botadm.blacklist.empty")
        else:
            text += t(lang, "botadm.blacklist.no_items_page")
        
        text += f"\n**{t(lang, 'action.current')}:** {t(lang, f'action.{action}')}"
        
        rows: list[list[InlineKeyboardButton]] = []
        
        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅", callback_data=f"botadm:bl:page:{page-1}"))
        if words:
            nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="botadm:noop"))
        if end < len(words):
            nav_buttons.append(InlineKeyboardButton("➡", callback_data=f"botadm:bl:page:{page+1}"))
        
        if nav_buttons:
            rows.append(nav_buttons)
        
        # Management buttons
        if words:
            rows.append([
                InlineKeyboardButton(t(lang, "botadm.bl.manage"), callback_data="botadm:bl:manage:0"),
                InlineKeyboardButton(t(lang, "botadm.bl.clear_all"), callback_data="botadm:bl:clear"),
            ])
        
        # Action buttons
        rows.append([
            InlineKeyboardButton(t(lang, "botadm.bl.add"), callback_data="botadm:bl:add"),
            InlineKeyboardButton(t(lang, "botadm.bl.export"), callback_data="botadm:bl:export"),
            InlineKeyboardButton(t(lang, "botadm.bl.import"), callback_data="botadm:bl:import"),
        ])
        
        # Action selection
        rows.append([
            InlineKeyboardButton(
                f"{'✓ ' if action == 'warn' else ''}{t(lang, 'action.warn')}",
                callback_data="botadm:bl:action:warn"
            ),
            InlineKeyboardButton(
                f"{'✓ ' if action == 'mute' else ''}{t(lang, 'action.mute')}",
                callback_data="botadm:bl:action:mute"
            ),
            InlineKeyboardButton(
                f"{'✓ ' if action == 'ban' else ''}{t(lang, 'action.ban')}",
                callback_data="botadm:bl:action:ban"
            ),
        ])
        
        # Back button
        rows.append([InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:home")])
        
        await Navigator.edit_or_send(
            update,
            text,
            rows
        )
    
    @staticmethod
    async def go_blacklist_manage(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
        """Show blacklist words with delete buttons for management."""
        from ...infra import db
        from ...infra.settings_repo import SettingsRepo
        
        lang = I18N.pick_lang(update)
        
        async with db.SessionLocal() as s:  # type: ignore
            cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
        
        words = list(cfg.get("words", []))
        
        # Pagination for management view
        page_size = 10  # Fewer items since we have delete buttons
        start = page * page_size
        end = start + page_size
        displayed_words = words[start:end]
        total_pages = (len(words) + page_size - 1) // page_size if words else 1
        
        text = f"**{t(lang, 'botadm.bl.manage_title')}**\n"
        text += f"_Page {page + 1} of {total_pages}_\n\n"
        text += t(lang, "botadm.bl.manage_help")
        
        rows: list[list[InlineKeyboardButton]] = []
        
        # Show words with delete buttons
        for word in displayed_words:
            # Truncate for button display
            display_word = word[:25] + "..." if len(word) > 25 else word
            rows.append([
                InlineKeyboardButton(display_word, callback_data="botadm:noop"),
                InlineKeyboardButton("🗑", callback_data=f"botadm:bl:del:{word[:50]}")
            ])
        
        # Pagination
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅", callback_data=f"botadm:bl:manage:{page-1}"))
        nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="botadm:noop"))
        if end < len(words):
            nav_buttons.append(InlineKeyboardButton("➡", callback_data=f"botadm:bl:manage:{page+1}"))
        
        if nav_buttons:
            rows.append(nav_buttons)
        
        # Back button
        rows.append([InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:blacklist")])
        
        await Navigator.edit_or_send(update, text, rows, parse_mode="Markdown")
    
    @staticmethod
    async def go_violators(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show global violators list."""
        from ...infra import db
        from ...infra.global_violators_repo import GlobalViolatorsRepo
        from datetime import datetime
        
        lang = I18N.pick_lang(update)
        
        async with db.SessionLocal() as s:  # type: ignore
            violators = await GlobalViolatorsRepo(s).list_violators(limit=20)
        
        if not violators:
            text = t(lang, "botadm.violators") + "\n\n" + t(lang, "botadm.violators.empty")
        else:
            text = t(lang, "botadm.violators.title", count=len(violators)) + "\n\n"
            
            for v in violators[:10]:  # Show first 10
                # Format user info
                text += t(lang, "botadm.violators.user_id", id=f"`{v.user_id}`") + "\n"
                text += t(lang, "botadm.violators.action", action=v.action) + "\n"
                text += t(lang, "botadm.violators.count", count=v.violation_count) + "\n"
                
                # Show matched words
                if v.matched_words:
                    words = ", ".join(v.matched_words[:3])
                    if len(v.matched_words) > 3:
                        words += "..."
                    text += t(lang, "botadm.violators.words", words=words) + "\n"
                
                # Show expiry
                if v.expires_at:
                    remaining = v.expires_at - datetime.utcnow()
                    hours = int(remaining.total_seconds() / 3600)
                    mins = int((remaining.total_seconds() % 3600) / 60)
                    if hours > 0:
                        time_str = f"{hours}h {mins}m"
                    else:
                        time_str = f"{mins}m"
                    text += t(lang, "botadm.violators.expires", time=time_str) + "\n"
                else:
                    text += t(lang, "botadm.violators.expires_never") + "\n"
                
                text += "\n"
            
            if len(violators) > 10:
                text += t(lang, "botadm.violators.more", count=len(violators) - 10) + "\n"
        
        keyboard = [
            [InlineKeyboardButton(t(lang, "botadm.violators.clear_all"), callback_data="botadm:violators:clear_all")],
            [InlineKeyboardButton(t(lang, "botadm.violators.refresh"), callback_data="botadm:nav:violators")],
            [InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:home")]
        ]
        
        await Navigator.edit_or_send(update, text, keyboard, parse_mode="Markdown")