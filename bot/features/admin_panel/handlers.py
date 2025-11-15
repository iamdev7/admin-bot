from __future__ import annotations

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatPermissions
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters
import time

from ...core.i18n import I18N, t
import logging
log = logging.getLogger(__name__)


async def safe_edit_message(update: Update, text: str, reply_markup=None, parse_mode=None):
    """Safely edit a message, handling the case where content hasn't changed."""
    try:
        return await update.effective_message.edit_text(
            text, 
            reply_markup=reply_markup, 
            parse_mode=parse_mode
        )
    except Exception as e:
        if "Message is not modified" in str(e):
            if update.callback_query:
                await update.callback_query.answer("✓", show_alert=False)
            return None
        else:
            raise


def _panel_lang(update, gid: int | None) -> str:
    try:
        if gid is not None:
            from ...core.i18n import I18N as _I
            gl = _I.get_group_lang(gid)
            if gl:
                return gl
    except Exception:
        pass
    return I18N.pick_lang(update)


async def _safe_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, text: str, kb_rows: list[list[InlineKeyboardButton]]) -> None:
    """Edit panel message only if view changed; ignore 'Message is not modified'."""
    try:
        last = context.user_data.get("panel_last_view")
        if last == key:
            return
        await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
        context.user_data["panel_last_view"] = key
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise


async def _safe_edit_msg(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, key: str, text: str, kb_rows: list[list[InlineKeyboardButton]]) -> None:
    try:
        # Check if user_data is available (might not be in job context)
        if context.user_data:
            last = context.user_data.get("panel_last_view")
            if last == key:
                return
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=InlineKeyboardMarkup(kb_rows))
        if context.user_data:
            context.user_data["panel_last_view"] = key
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise
from ...core.permissions import require_admin
from ...infra import db
from ...infra.repos import GroupsRepo
from ...infra.settings_repo import SettingsRepo
from ...infra.repos import FiltersRepo


async def start_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False) -> None:
    if not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type != "private":
        return
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        groups = await GroupsRepo(s).list_admin_groups(update.effective_user.id)
    if not groups:
        if edit and update.callback_query:
            await update.effective_message.edit_text(t(lang, "panel.no_groups"))
        else:
            await update.effective_message.reply_text(t(lang, "panel.no_groups"))
        return
    buttons = [
        [InlineKeyboardButton(g.title, callback_data=f"panel:group:{g.id}:tab:home")]
        for g in groups[:25]
    ]
    text = t(lang, "panel.pick_group")
    markup = InlineKeyboardMarkup(buttons)
    
    if edit and update.callback_query:
        await update.effective_message.edit_text(text, reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)


@require_admin
async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    if update.effective_chat and update.effective_chat.type in {"group", "supergroup"}:
        await update.effective_message.reply_text(t(lang, "panel.open_dm"))
    else:
        await start_panel(update, context)


def _ensure_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


async def _is_admin_of(context: ContextTypes.DEFAULT_TYPE, user_id: int, group_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(group_id, user_id)
        return str(member.status) in ("ChatMemberStatus.ADMINISTRATOR", "ChatMemberStatus.OWNER", "administrator", "creator", "owner")
    except Exception:
        return False


def tabs_keyboard(lang: str, gid: int) -> InlineKeyboardMarkup:
    tabs = [
        InlineKeyboardButton(t(lang, "panel.tab.moderation"), callback_data=f"panel:group:{gid}:tab:moderation"),
        InlineKeyboardButton(t(lang, "panel.tab.antispam"), callback_data=f"panel:group:{gid}:tab:antispam"),
        InlineKeyboardButton(t(lang, "panel.tab.rules"), callback_data=f"panel:group:{gid}:tab:rules"),
        InlineKeyboardButton(t(lang, "panel.tab.welcome"), callback_data=f"panel:group:{gid}:tab:welcome"),
    ]
    row2 = [
        InlineKeyboardButton(t(lang, "panel.tab.language"), callback_data=f"panel:group:{gid}:tab:language"),
        InlineKeyboardButton(t(lang, "panel.tab.onboarding"), callback_data=f"panel:group:{gid}:tab:onboarding"),
        InlineKeyboardButton(t(lang, "panel.tab.automations"), callback_data=f"panel:group:{gid}:tab:automations"),
        InlineKeyboardButton(t(lang, "panel.tab.ai"), callback_data=f"panel:group:{gid}:tab:ai"),
    ]
    row3 = [
        InlineKeyboardButton(t(lang, "panel.tab.audit"), callback_data=f"panel:group:{gid}:tab:audit"),
    ]
    return InlineKeyboardMarkup([tabs, row2, row3, [InlineKeyboardButton(t(lang, "panel.back"), callback_data="panel:back")]])


async def open_group(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    await update.effective_message.edit_text(t(lang, "panel.tabs"), reply_markup=tabs_keyboard(lang, gid))


async def show_antispam(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "antispam") or {}
    window = cfg.get("window_sec", 5)
    threshold = cfg.get("threshold", 8)
    mute = cfg.get("mute_seconds", 60)
    ban = cfg.get("ban_seconds", 600)
    text = t(lang, "panel.antispam.title") + "\n" + t(
        lang, "panel.antispam.current", window=window, threshold=threshold, mute=mute, ban=ban
    )
    kb = [
        [
            InlineKeyboardButton(t(lang, "panel.preset.lenient"), callback_data=f"panel:group:{gid}:antispam:preset:lenient"),
            InlineKeyboardButton(t(lang, "panel.preset.normal"), callback_data=f"panel:group:{gid}:antispam:preset:normal"),
            InlineKeyboardButton(t(lang, "panel.preset.strict"), callback_data=f"panel:group:{gid}:antispam:preset:strict"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")],
    ]
    await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        text = await SettingsRepo(s).get_text(gid, "rules")
    n = len(text) if text else 0
    kb = [
        [
            InlineKeyboardButton(t(lang, "panel.rules.add"), callback_data=f"panel:group:{gid}:rules:add"),
            InlineKeyboardButton(t(lang, "panel.rules.list"), callback_data=f"panel:group:{gid}:rules:list:0"),
        ],
        [InlineKeyboardButton(t(lang, "panel.links.policy"), callback_data=f"panel:group:{gid}:links:open")],
        [InlineKeyboardButton(t(lang, "panel.locks.title"), callback_data=f"panel:group:{gid}:locks:open")],
        [InlineKeyboardButton(t(lang, "panel.rules.edittext"), callback_data=f"panel:group:{gid}:rules:edittext")],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")],
    ]
    await update.effective_message.edit_text(
        t(lang, "panel.rules.title") + "\n" + t(lang, "panel.rules.current", n=n),
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def list_rules(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, page: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        rules = await FiltersRepo(s).list_rules(gid, limit=200)
    page_size = 10
    start = page * page_size
    items = rules[start : start + page_size]
    
    # Build text list of rules
    text = f"**{t(lang, 'panel.rules.list_title')}**\n\n"
    
    if not items and page == 0:
        text += t(lang, "rules.list.empty")
        # Show back button to rules menu
        kb = [[InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")]]
        await update.effective_message.edit_text(
            text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
        )
        return
    
    # Display rules as text
    for r in items:
        pattern_preview = r.pattern[:30] + "..." if len(r.pattern) > 30 else r.pattern
        text += f"#{r.id} • {r.type} • {r.action}\n"
        text += f"   Pattern: {pattern_preview}\n\n"
    
    if len(rules) > 10:
        text += f"\n_Showing {start+1}-{min(start+page_size, len(rules))} of {len(rules)} rules_"
    
    # Navigation and action buttons
    rows = []
    
    # Add manage button if there are rules
    if rules:
        rows.append([
            InlineKeyboardButton(t(lang, "panel.rules.manage"), callback_data=f"panel:group:{gid}:rules:manage:0")
        ])
    
    # Navigation buttons
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅", callback_data=f"panel:group:{gid}:rules:list:{page-1}"))
    if len(rules) > page_size:
        nav.append(InlineKeyboardButton(f"{page+1}/{(len(rules)+page_size-1)//page_size}", callback_data="panel:noop"))
    if start + page_size < len(rules):
        nav.append(InlineKeyboardButton("➡", callback_data=f"panel:group:{gid}:rules:list:{page+1}"))
    if nav:
        rows.append(nav)
    
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")])
    await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


async def manage_rules(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, page: int) -> None:
    """Show rules with delete buttons for management."""
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        rules = await FiltersRepo(s).list_rules(gid, limit=200)
    
    page_size = 5  # Fewer items since we have delete buttons
    start = page * page_size
    items = rules[start : start + page_size]
    total_pages = (len(rules) + page_size - 1) // page_size if rules else 1
    
    text = f"**{t(lang, 'panel.rules.manage_title')}**\n"
    text += f"_Page {page + 1} of {total_pages}_\n\n"
    text += t(lang, "panel.rules.manage_help")
    
    rows = []
    
    # Show rules with delete buttons
    for r in items:
        # Truncate pattern for button display
        pattern_display = r.pattern[:20] + "..." if len(r.pattern) > 20 else r.pattern
        label = f"#{r.id} {r.type} • {pattern_display}"
        rows.append([
            InlineKeyboardButton(label[:30], callback_data="panel:noop"),
            InlineKeyboardButton("🗑", callback_data=f"panel:group:{gid}:rules:del:{r.id}")
        ])
    
    # Navigation
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅", callback_data=f"panel:group:{gid}:rules:manage:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="panel:noop"))
    if start + page_size < len(rules):
        nav.append(InlineKeyboardButton("➡", callback_data=f"panel:group:{gid}:rules:manage:{page+1}"))
    
    if nav:
        rows.append(nav)
    
    # Back button
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:rules:list:0")])
    
    await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


async def rules_add_pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    kb = [
        [
            InlineKeyboardButton("word", callback_data=f"panel:group:{gid}:rules:add:type:word"),
            InlineKeyboardButton("regex", callback_data=f"panel:group:{gid}:rules:add:type:regex"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")],
    ]
    await update.effective_message.edit_text(t(lang, "panel.rules.add_type"), reply_markup=InlineKeyboardMarkup(kb))


async def rules_add_pick_action(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, ftype: str) -> None:
    lang = _panel_lang(update, gid)
    kb = [
        [
            InlineKeyboardButton("delete", callback_data=f"panel:group:{gid}:rules:add:action:{ftype}:delete"),
            InlineKeyboardButton("warn", callback_data=f"panel:group:{gid}:rules:add:action:{ftype}:warn"),
        ],
        [
            InlineKeyboardButton("mute", callback_data=f"panel:group:{gid}:rules:add:action:{ftype}:mute"),
            InlineKeyboardButton("ban", callback_data=f"panel:group:{gid}:rules:add:action:{ftype}:ban"),
            InlineKeyboardButton("reply", callback_data=f"panel:group:{gid}:rules:add:action:{ftype}:reply"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")],
    ]
    await update.effective_message.edit_text(t(lang, "panel.rules.add_action"), reply_markup=InlineKeyboardMarkup(kb))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_private(update) or not update.callback_query:
        return
    await update.callback_query.answer()
    data = update.callback_query.data or ""
    parts = data.split(":")
    lang = I18N.pick_lang(update)
    if data == "panel:back":
        return await start_panel(update, context, edit=True)
    if len(parts) >= 4 and parts[0] == "panel" and parts[1] == "group":
        gid = int(parts[2])
        user_id = update.effective_user.id if update.effective_user else 0
        # Ensure group lang is applied even after restart
        try:
            async with db.SessionLocal() as s:  # type: ignore
                from ...infra.settings_repo import SettingsRepo as _SR
                lang_cfg = await _SR(s).get(gid, "language") or {}
                code = lang_cfg.get("code")
                if code:
                    from ...core.i18n import I18N as _I
                    _I.set_group_lang(gid, code)
        except Exception:
            pass
        if not await _is_admin_of(context, user_id, gid):
            return
        if len(parts) >= 5 and parts[3] == "tab":
            tab = parts[4]
            if tab in {"home", ""}:
                return await open_group(update, context, gid)
            if tab == "antispam":
                return await show_antispam(update, context, gid)
            if tab == "rules":
                return await show_rules(update, context, gid)
            if tab == "moderation":
                return await show_moderation(update, context, gid)
            if tab == "language":
                return await show_language(update, context, gid)
            if tab == "welcome":
                return await show_welcome(update, context, gid)
            if tab == "automations":
                return await show_automations(update, context, gid)
            if tab == "onboarding":
                return await show_onboarding(update, context, gid)
            if tab == "ai":
                return await show_ai(update, context, gid)
            if tab == "audit":
                return await show_audit(update, context, gid, 0)

        if len(parts) >= 5 and parts[3] == "auto2":
            step = parts[4]
            if step == "menu":
                import asyncio
                return await auto2_menu(update, context, gid)
            if step == "announce":
                if len(parts) == 5:
                    return await auto2_pick_announce_mode(update, context, gid)
                if len(parts) >= 6 and parts[5] == "once":
                    return await auto2_pick_delay(update, context, gid, key="announce")
                if len(parts) >= 6 and parts[5] == "repeat":
                    return await auto2_pick_interval(update, context, gid)
                if len(parts) >= 7 and parts[5] == "delay" and parts[6].isdigit():
                    context.user_data[("auto2_params", gid)] = {"kind": "announce", "delay": int(parts[6]), "interval": None}
                    return await auto2_prompt_text(update, context, gid, key="announce")
                if len(parts) >= 7 and parts[5] == "interval" and parts[6].isdigit():
                    context.user_data[("auto2_params", gid)] = {"kind": "announce", "delay": 5, "interval": int(parts[6])}
                    return await auto2_prompt_text(update, context, gid, key="announce")
            if step == "pin":
                if len(parts) == 5:
                    return await auto2_pick_interval(update, context, gid)
                if len(parts) >= 7 and parts[5] == "interval" and parts[6].isdigit():
                    context.user_data[("auto2_params", gid)] = {"kind": "rotate_pin", "delay": 5, "interval": int(parts[6])}
                    return await update.effective_message.reply_text(t(_panel_lang(update, gid), "panel.auto.pin_prompt_text"))

        if len(parts) >= 6 and parts[3] == "antispam" and parts[4] == "preset":
            preset = parts[5]
            presets = {
                "lenient": {"window_sec": 5, "threshold": 12, "mute_seconds": 30, "ban_seconds": 300},
                "normal": {"window_sec": 5, "threshold": 8, "mute_seconds": 60, "ban_seconds": 600},
                "strict": {"window_sec": 5, "threshold": 5, "mute_seconds": 180, "ban_seconds": 1800},
            }
            cfg = presets.get(preset)
            if cfg:
                async with db.SessionLocal() as s:  # type: ignore
                    await SettingsRepo(s).set(gid, "antispam", cfg)
                    await s.commit()
                await update.effective_message.reply_text(t(lang, "panel.saved"))
                return await show_antispam(update, context, gid)
        if parts[3] == "rules":
            if len(parts) == 5 and parts[4] == "add":
                return await rules_add_pick_type(update, context, gid)
            if len(parts) == 6 and parts[4] == "list":
                page = int(parts[5])
                return await list_rules(update, context, gid, page)
            if len(parts) == 6 and parts[4] == "manage":
                page = int(parts[5])
                return await manage_rules(update, context, gid, page)
            if len(parts) == 5 and parts[4] == "edittext":
                context.user_data[("await_rules", gid)] = True
                return await update.effective_message.reply_text(t(lang, "panel.rules.prompt"))
            if len(parts) == 7 and parts[4] == "add" and parts[5] == "type":
                ftype = parts[6]
                return await rules_add_pick_action(update, context, gid, ftype)
            if len(parts) == 8 and parts[4] == "add" and parts[5] == "action":
                ftype = parts[6]
                action = parts[7]
                # Wait for text input now
                context.user_data[("await_new_rule", gid)] = {"type": ftype, "action": action}
                return await update.effective_message.reply_text(t(lang, "panel.rules.add_prompt"))
            if len(parts) == 6 and parts[4] == "del":
                rid = int(parts[5])
                async with db.SessionLocal() as s:  # type: ignore
                    ok = await FiltersRepo(s).delete_rule(gid, rid)
                    await s.commit()
                # Don't reply with a separate message, just refresh the list
                return await manage_rules(update, context, gid, page=0)
            if len(parts) == 6 and parts[4] == "cfg":
                rid = int(parts[5])
                return await rule_config(update, context, gid, rid)
            if len(parts) == 8 and parts[4] == "cfg" and parts[6] == "preset":
                rid = int(parts[5])
                preset = parts[7]
                presets = {
                    "off": None,
                    "warn2": {"threshold": 2, "cooldown": 300, "action": "mute"},
                    "ban3": {"threshold": 3, "cooldown": 600, "action": "ban"},
                }
                async with db.SessionLocal() as s:  # type: ignore
                    from ...infra.models import Filter as F
                    f = await s.get(F, rid)
                    if f and f.group_id == gid:
                        extra = f.extra or {}
                        extra["esc"] = presets.get(preset)
                        f.extra = extra
                        await s.commit()
                return await rule_config(update, context, gid, rid)
        if len(parts) >= 5 and parts[3] == "onboarding" and parts[4] == "toggle":
            async with db.SessionLocal() as s:  # type: ignore
                cfg = await SettingsRepo(s).get(gid, "auto_approve_join") or {"enabled": False}
                cfg["enabled"] = not bool(cfg.get("enabled"))
                
                # If enabling auto_approve, disable require_accept (they conflict)
                if cfg["enabled"]:
                    ob_cfg = await SettingsRepo(s).get(gid, "onboarding") or {"require_accept": False}
                    if ob_cfg.get("require_accept"):
                        ob_cfg["require_accept"] = False
                        await SettingsRepo(s).set(gid, "onboarding", ob_cfg)
                        log.info(f"Disabled require_accept for {gid} due to auto_approve being enabled")
                else:
                    # If disabling auto_approve, also disable CAPTCHA (it won't work without auto-approve)
                    captcha_cfg = await SettingsRepo(s).get(gid, "captcha") or {"enabled": False}
                    if captcha_cfg.get("enabled"):
                        captcha_cfg["enabled"] = False
                        await SettingsRepo(s).set(gid, "captcha", captcha_cfg)
                        log.info(f"Disabled CAPTCHA for {gid} due to auto_approve being disabled")
                
                await SettingsRepo(s).set(gid, "auto_approve_join", cfg)
                await s.commit()
            return await show_onboarding(update, context, gid)

        if len(parts) >= 5 and parts[3] == "language" and parts[4] in {"en", "ar"}:
            code = parts[4]
            async with db.SessionLocal() as s:  # type: ignore
                await SettingsRepo(s).set(gid, "language", {"code": code})
                await s.commit()
            from ...core.i18n import I18N as _I

            _I.set_group_lang(gid, code)
            return await show_language(update, context, gid)

        if len(parts) >= 5 and parts[3] == "welcome":
            if parts[4] == "toggle":
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "welcome") or {"enabled": True}
                    cfg["enabled"] = not bool(cfg.get("enabled", True))
                    await SettingsRepo(s).set(gid, "welcome", cfg)
                    await s.commit()
                return await show_welcome(update, context, gid)
            if parts[4] == "edit":
                context.user_data[("await_welcome", gid)] = True
                lang = I18N.pick_lang(update)
                return await update.effective_message.reply_text(t(lang, "panel.welcome.prompt"))
            if parts[4] == "ttl" and len(parts) >= 6:
                try:
                    val = int(parts[5])
                except ValueError:
                    val = 0
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "welcome") or {"enabled": True}
                    cfg["ttl_sec"] = max(0, val)
                    await SettingsRepo(s).set(gid, "welcome", cfg)
                    await s.commit()
                return await show_welcome(update, context, gid)

        if len(parts) >= 5 and parts[3] == "onboarding":
            if parts[4] == "require":
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "onboarding") or {"require_accept": False}
                    cfg["require_accept"] = not bool(cfg.get("require_accept", False))
                    
                    # If enabling require_accept, disable auto_approve (they conflict)
                    if cfg["require_accept"]:
                        auto_cfg = await SettingsRepo(s).get(gid, "auto_approve_join") or {"enabled": False}
                        if auto_cfg.get("enabled"):
                            auto_cfg["enabled"] = False
                            await SettingsRepo(s).set(gid, "auto_approve_join", auto_cfg)
                            log.info(f"Disabled auto_approve for {gid} due to require_accept being enabled")
                    
                    await SettingsRepo(s).set(gid, "onboarding", cfg)
                    await s.commit()
                return await show_onboarding(update, context, gid)
            if parts[4] == "require_unmute":
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "onboarding") or {"require_accept_unmute": False}
                    cfg["require_accept_unmute"] = not bool(cfg.get("require_accept_unmute", False))
                    await SettingsRepo(s).set(gid, "onboarding", cfg)
                    await s.commit()
                return await show_onboarding(update, context, gid)
            if parts[4] == "captcha":
                async with db.SessionLocal() as s:  # type: ignore
                    cap = await SettingsRepo(s).get(gid, "captcha") or {"enabled": False, "mode": "button", "timeout": 120}
                    if len(parts) >= 6 and parts[5] == "toggle":
                        new_enabled = not bool(cap.get("enabled", False))
                        
                        # CAPTCHA only works with auto_approve enabled
                        if new_enabled:
                            auto_cfg = await SettingsRepo(s).get(gid, "auto_approve_join") or {"enabled": False}
                            if not auto_cfg.get("enabled"):
                                # Enable auto_approve if trying to enable CAPTCHA
                                auto_cfg["enabled"] = True
                                await SettingsRepo(s).set(gid, "auto_approve_join", auto_cfg)
                                log.info(f"Enabled auto_approve for {gid} because CAPTCHA was enabled")
                                
                                # Also disable require_accept since auto_approve is now on
                                ob_cfg = await SettingsRepo(s).get(gid, "onboarding") or {"require_accept": False}
                                if ob_cfg.get("require_accept"):
                                    ob_cfg["require_accept"] = False
                                    await SettingsRepo(s).set(gid, "onboarding", ob_cfg)
                                    log.info(f"Disabled require_accept for {gid} due to CAPTCHA/auto_approve being enabled")
                        
                        cap["enabled"] = new_enabled
                    if len(parts) >= 7 and parts[5] == "mode" and parts[6] in {"button", "math"}:
                        cap["mode"] = parts[6]
                    if len(parts) >= 7 and parts[5] == "timeout" and parts[6].isdigit():
                        cap["timeout"] = int(parts[6])
                    await SettingsRepo(s).set(gid, "captcha", cap)
                    await s.commit()
                return await show_onboarding(update, context, gid)

        if len(parts) >= 5 and parts[3] == "links":
            if parts[4] == "open":
                return await show_links(update, context, gid)
            if parts[4] == "night" and len(parts) >= 6 and parts[5] == "open":
                return await show_links_night(update, context, gid)
            # Handle type action changes first (more specific)
            if parts[4] == "type" and len(parts) >= 7 and parts[5] in {"invites", "telegram", "shorteners", "usernames", "other"}:
                cat = parts[5]
                action = parts[6]
                if action in {"default", "allow", "delete", "warn", "mute", "ban"}:
                    async with db.SessionLocal() as s:  # type: ignore
                        cfg = await SettingsRepo(s).get(gid, "links") or {"types": {}}
                        types = cfg.get("types", {})
                        if action == "default":
                            # Remove the specific setting to use default
                            types.pop(cat, None)
                        else:
                            types[cat] = action
                        cfg["types"] = types
                        await SettingsRepo(s).set(gid, "links", cfg)
                        await s.commit()
                    return await show_links_type_actions(update, context, gid)
            # Handle type panel open (less specific)
            if parts[4] == "type" and (len(parts) == 5 or (len(parts) >= 6 and parts[5] == "open")):
                return await show_links_type_actions(update, context, gid)
            if parts[4] == "toggle_block":
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "links") or {"block_all": False, "denylist": [], "action": "delete"}
                    cfg["block_all"] = not bool(cfg.get("block_all", False))
                    await SettingsRepo(s).set(gid, "links", cfg)
                    await s.commit()
                return await show_links(update, context, gid)
            if parts[4] == "action" and len(parts) >= 6:
                action = parts[5]
                if action in {"delete", "warn", "mute", "ban"}:
                    async with db.SessionLocal() as s:  # type: ignore
                        cfg = await SettingsRepo(s).get(gid, "links") or {"block_all": False, "denylist": [], "action": "delete"}
                        cfg["action"] = action
                        await SettingsRepo(s).set(gid, "links", cfg)
                        await s.commit()
                    return await show_links(update, context, gid)
            if parts[4] == "allow" and len(parts) >= 6:
                if parts[5] == "add":
                    context.user_data[("await_link_allow_domain", gid)] = True
                    lang = I18N.pick_lang(update)
                    await update.callback_query.answer()
                    return await update.effective_message.reply_text(t(lang, "panel.links.allow_add_prompt"))
                if parts[5] == "del" and len(parts) >= 7:
                    dom = parts[6]
                    async with db.SessionLocal() as s:  # type: ignore
                        cfg = await SettingsRepo(s).get(gid, "links") or {"allowlist": []}
                        allow = set(cfg.get("allowlist", []))
                        if dom in allow:
                            allow.remove(dom)
                        cfg["allowlist"] = list(allow)
                        await SettingsRepo(s).set(gid, "links", cfg)
                        await s.commit()
                    return await show_links(update, context, gid)
            if parts[4] == "night" and len(parts) >= 6:
                async with db.SessionLocal() as s:  # type: ignore
                    night = await SettingsRepo(s).get(gid, "links.night") or {"enabled": False, "from_h": 0, "to_h": 6, "tz_offset_min": 0, "block_all": True}
                    if parts[5] == "toggle":
                        night["enabled"] = not bool(night.get("enabled", False))
                    elif parts[5] == "block_toggle":
                        night["block_all"] = not bool(night.get("block_all", True))
                    elif parts[5] == "time" and len(parts) >= 8:
                        night["from_h"] = int(parts[6])
                        night["to_h"] = int(parts[7])
                    elif parts[5] == "tz" and len(parts) >= 7:
                        night["tz_offset_min"] = int(parts[6])
                    await SettingsRepo(s).set(gid, "links.night", night)
                    await s.commit()
                return await show_links_night(update, context, gid)
            if parts[4] == "add":
                context.user_data[("await_link_domain", gid)] = True
                lang = I18N.pick_lang(update)
                await update.callback_query.answer()
                return await update.effective_message.reply_text(t(lang, "panel.links.add_prompt"))
            if parts[4] == "del" and len(parts) >= 6:
                dom = parts[5]
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "links") or {"block_all": False, "denylist": [], "action": "delete"}
                    deny = set(cfg.get("denylist", []))
                    if dom in deny:
                        deny.remove(dom)
                    cfg["denylist"] = list(deny)
                    await SettingsRepo(s).set(gid, "links", cfg)
                    await s.commit()
                return await show_links(update, context, gid)
        if len(parts) >= 5 and parts[3] == "locks":
            if parts[4] == "open":
                return await show_locks(update, context, gid)
            if parts[4] == "forwards" and len(parts) >= 6:
                action = parts[5]
                if action in {"allow", "delete", "warn", "mute", "ban"}:
                    async with db.SessionLocal() as s:  # type: ignore
                        locks = await SettingsRepo(s).get(gid, "locks") or {}
                        locks["forwards"] = action
                        await SettingsRepo(s).set(gid, "locks", locks)
                        await s.commit()
                    return await show_locks(update, context, gid)
            if parts[4] == "media" and len(parts) >= 7:
                mtype = parts[5]
                action = parts[6]
                if action in {"allow", "delete", "warn", "mute", "ban"}:
                    async with db.SessionLocal() as s:  # type: ignore
                        locks = await SettingsRepo(s).get(gid, "locks") or {}
                        media = locks.get("media") or {}
                        media[mtype] = action
                        locks["media"] = media
                        await SettingsRepo(s).set(gid, "locks", locks)
                        await s.commit()
                    return await show_locks(update, context, gid)
        if len(parts) >= 5 and parts[3] == "ai":
            if parts[4] == "toggle":
                async with db.SessionLocal() as s:  # type: ignore
                    settings = await SettingsRepo(s).get(gid, "ai_response") or {}
                    settings["enabled"] = not settings.get("enabled", False)
                    await SettingsRepo(s).set(gid, "ai_response", settings)
                    await s.commit()
                return await show_ai(update, context, gid)
            
            if parts[4] == "model" and len(parts) >= 6:
                model = parts[5]
                # Support both specific version and general model names
                if model in ["gemini-2.5-flash", "gpt-5-mini-2025-08-07", "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]:
                    async with db.SessionLocal() as s:  # type: ignore
                        settings = await SettingsRepo(s).get(gid, "ai_response") or {}
                        settings["model"] = model
                        await SettingsRepo(s).set(gid, "ai_response", settings)
                        await s.commit()
                    return await show_ai(update, context, gid)
            
            if parts[4] == "reply_mode":
                async with db.SessionLocal() as s:  # type: ignore
                    settings = await SettingsRepo(s).get(gid, "ai_response") or {}
                    settings["reply_only"] = not settings.get("reply_only", True)
                    await SettingsRepo(s).set(gid, "ai_response", settings)
                    await s.commit()
                return await show_ai(update, context, gid)
            
            if parts[4] == "temp" and len(parts) >= 6:
                try:
                    temp = float(parts[5])
                    if 0.0 <= temp <= 2.0:
                        async with db.SessionLocal() as s:  # type: ignore
                            settings = await SettingsRepo(s).get(gid, "ai_response") or {}
                            settings["temperature"] = temp
                            await SettingsRepo(s).set(gid, "ai_response", settings)
                            await s.commit()
                        return await show_ai(update, context, gid)
                except ValueError:
                    pass
        
        if len(parts) >= 5 and parts[3] == "auto":
            if parts[4] == "toggle" and len(parts) >= 6:
                job_id = int(parts[5])
                async with db.SessionLocal() as s:  # type: ignore
                    from ...infra.repos import JobsRepo
                    j = await JobsRepo(s).get(job_id)
                    if j and j.group_id == gid:
                        payload = j.payload or {}
                        payload["paused"] = not bool(payload.get("paused"))
                        await JobsRepo(s).update_payload(job_id, payload)
                        await s.commit()
                return await show_automations(update, context, gid)
            if parts[4] == "add":
                # choose once or repeat and delay/interval
                kb = [
                    [
                        InlineKeyboardButton(t(lang, "panel.auto.once"), callback_data=f"panel:group:{gid}:auto:add:once"),
                        InlineKeyboardButton(t(lang, "panel.auto.repeat"), callback_data=f"panel:group:{gid}:auto:add:repeat"),
                    ],
                    [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                ]
                await _safe_edit(update, context, key=f"auto:pick_mode:{gid}", text=t(lang, "panel.auto.pick_mode"), kb_rows=kb)
                return

            if parts[4] == "add" and len(parts) >= 6 and parts[5] == "pin":
                kb = [
                    [
                        InlineKeyboardButton("1h", callback_data=f"panel:group:{gid}:auto:add:pin:interval:3600"),
                        InlineKeyboardButton("6h", callback_data=f"panel:group:{gid}:auto:add:pin:interval:21600"),
                        InlineKeyboardButton("1d", callback_data=f"panel:group:{gid}:auto:add:pin:interval:86400"),
                    ],
                    [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                ]
                await _safe_edit(update, context, key=f"auto:pin_interval:{gid}", text=t(lang, "panel.auto.pin_pick_interval"), kb_rows=kb)
                return

            if parts[4] == "add" and len(parts) >= 6 and parts[5] in {"unmute", "unban"}:
                mode = parts[5]
                kb = [
                    [
                        InlineKeyboardButton("10m", callback_data=f"panel:group:{gid}:auto:add:{mode}:delay:600"),
                        InlineKeyboardButton("1h", callback_data=f"panel:group:{gid}:auto:add:{mode}:delay:3600"),
                        InlineKeyboardButton("1d", callback_data=f"panel:group:{gid}:auto:add:{mode}:delay:86400"),
                    ],
                    [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                ]
                await _safe_edit(update, context, key=f"auto:{mode}:pick_delay:{gid}", text=t(lang, "panel.auto.pick_delay"), kb_rows=kb)
                return

            if parts[4] == "add" and len(parts) >= 6 and parts[5] in {"once", "repeat"}:
                mode = parts[5]
                # choose delay or interval presets
                if mode == "once":
                    kb = [
                        [
                            InlineKeyboardButton("10m", callback_data=f"panel:group:{gid}:auto:add:once:delay:600"),
                            InlineKeyboardButton("1h", callback_data=f"panel:group:{gid}:auto:add:once:delay:3600"),
                            InlineKeyboardButton("1d", callback_data=f"panel:group:{gid}:auto:add:once:delay:86400"),
                        ],
                        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                    ]
                    await _safe_edit(update, context, key=f"auto:once:pick_delay:{gid}", text=t(lang, "panel.auto.pick_delay"), kb_rows=kb)
                    return

                else:
                    kb = [
                        [
                            InlineKeyboardButton("1h", callback_data=f"panel:group:{gid}:auto:add:repeat:interval:3600"),
                            InlineKeyboardButton("6h", callback_data=f"panel:group:{gid}:auto:add:repeat:interval:21600"),
                            InlineKeyboardButton("1d", callback_data=f"panel:group:{gid}:auto:add:repeat:interval:86400"),
                        ],
                        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                    ]
                    await _safe_edit(update, context, key=f"auto:pick_interval:{gid}", text=t(lang, "panel.auto.pick_interval"), kb_rows=kb)
                    return

            if parts[4] == "add" and len(parts) >= 8 and parts[5] == "once" and parts[6] == "delay":
                delay = int(parts[7])
                context.user_data[("await_auto_announce", gid)] = {"delay": delay, "interval": None}
                
                try:
                    return await update.effective_message.reply_text(t(lang, "panel.auto.prompt_text"))
                except Exception as e:
                    log.exception("automation panel: prompt text send failed gid=%s: %s", gid, e)
                    return

            if parts[4] == "add" and len(parts) >= 8 and parts[5] == "repeat" and parts[6] == "interval":
                interval = int(parts[7])
                context.user_data[("await_auto_announce", gid)] = {"delay": 5, "interval": interval}
                
                try:
                    return await update.effective_message.reply_text(t(lang, "panel.auto.prompt_text"))
                except Exception as e:
                    log.exception("automation panel: prompt text send failed gid=%s: %s", gid, e)
                    return

            if parts[4] == "add" and len(parts) >= 8 and parts[5] == "pin" and parts[6] == "interval":
                interval = int(parts[7])
                context.user_data[("await_auto_pintext", gid)] = {"interval": interval}
                
                try:
                    return await update.effective_message.reply_text(t(lang, "panel.auto.pin_prompt_text"))
                except Exception as e:
                    log.exception("automation panel: pin prompt send failed gid=%s: %s", gid, e)
                    return

            if parts[4] == "add" and len(parts) >= 8 and parts[5] in {"unmute", "unban"} and parts[6] == "delay":
                delay = int(parts[7])
                mode = parts[5]
                context.user_data[(f"await_auto_{mode}_uid", gid)] = {"delay": delay}
                
                try:
                    return await update.effective_message.reply_text(t(lang, "panel.auto.prompt_uid"))
                except Exception as e:
                    log.exception("automation panel: prompt uid send failed gid=%s: %s", gid, e)
                    return

            if parts[4] == "cancel" and len(parts) >= 6:
                job_id = int(parts[5])
                # remove from DB and job_queue
                async with db.SessionLocal() as s:  # type: ignore
                    from ...infra.repos import JobsRepo

                    ok = await JobsRepo(s).delete(job_id)
                    await s.commit()
                for jb in context.job_queue.get_jobs_by_name(f"job:{job_id}"):
                    jb.schedule_removal()
                return await show_automations(update, context, gid)
        if len(parts) >= 5 and parts[3] == "audit":
            page = 0
            if len(parts) == 5 and parts[4].isdigit():
                page = int(parts[4])
            return await show_audit(update, context, gid, page)

        if len(parts) >= 5 and parts[3] == "moderation":
            if parts[4] == "toggle_delete":
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "moderation") or {"warn_limit": 3, "delete_offense": True}
                    cfg["delete_offense"] = not bool(cfg.get("delete_offense", True))
                    await SettingsRepo(s).set(gid, "moderation", cfg)
                    await s.commit()
                return await show_moderation(update, context, gid)
            if parts[4] == "warn" and len(parts) >= 6 and parts[5].isdigit():
                wl = int(parts[5])
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "moderation") or {"warn_limit": 3}
                    cfg["warn_limit"] = wl
                    await SettingsRepo(s).set(gid, "moderation", cfg)
                    await s.commit()
                return await show_moderation(update, context, gid)
            if parts[4] == "ephemeral" and len(parts) >= 6:
                sec = int(parts[5])
                async with db.SessionLocal() as s:  # type: ignore
                    await SettingsRepo(s).set(gid, "ephemeral", {"seconds": sec or None})
                    await s.commit()
                return await show_moderation(update, context, gid)
            if parts[4] == "recent":
                return await show_recent_violators(update, context, gid)
            if parts[4] == "quick" and len(parts) >= 7:
                uid = int(parts[5])
                act = parts[6]
                await apply_quick_action(update, context, gid, uid, act)
                return


async def on_rules_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_private(update) or not update.effective_user:
        return
    # Find any pending group assignment
    # Save rules text
    for key, payload in list(context.user_data.items()):
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        k, gid = key
        if k == "await_rules" and payload:
            # Get HTML formatted text to preserve formatting
            html_text = ""
            if update.effective_message.text:
                # Use text_html to preserve all formatting (bold, italic, links, etc.)
                html_text = update.effective_message.text_html
            elif update.effective_message.caption:
                # If admin sent a media with caption
                html_text = update.effective_message.caption_html
            
            async with db.SessionLocal() as s:  # type: ignore
                await SettingsRepo(s).set_text(gid, "rules", html_text)
                await s.commit()
            context.user_data[(k, gid)] = False
            lang = I18N.pick_lang(update)
            await update.effective_message.reply_text(t(lang, "panel.rules.saved"))
            return
        if k == "await_new_rule" and isinstance(payload, dict):
            ftype = payload.get("type")
            action = payload.get("action")
            pattern = update.effective_message.text or ""
            if ftype and action and pattern:
                if action == "reply":
                    # Need another message for reply text
                    context.user_data[("await_reply_text", gid)] = {
                        "type": ftype,
                        "action": action,
                        "pattern": pattern,
                    }
                    context.user_data[(k, gid)] = False
                    lang = I18N.pick_lang(update)
                    await update.effective_message.reply_text(t(lang, "panel.rules.reply_prompt"))
                    return
                else:
                    async with db.SessionLocal() as s:  # type: ignore
                        f = await FiltersRepo(s).add_rule(gid, ftype, pattern, action, update.effective_user.id)  # type: ignore
                        await s.commit()
                        rule_id = f.id if f else 0
                    lang = I18N.pick_lang(update)
                    await update.effective_message.reply_text(t(lang, "rules.add.ok", id=rule_id))
                    context.user_data[(k, gid)] = False
                    return
        if k == "await_reply_text" and isinstance(payload, dict):
            ftype = payload.get("type")
            action = payload.get("action")
            pattern = payload.get("pattern")
            reply_text = update.effective_message.text or ""
            if ftype and action == "reply" and pattern:
                async with db.SessionLocal() as s:  # type: ignore
                    f = await FiltersRepo(s).add_rule(
                        gid, ftype, pattern, action, update.effective_user.id, extra={"text": reply_text}  # type: ignore
                    )
                    await s.commit()
                lang = I18N.pick_lang(update)
                await update.effective_message.reply_text(t(lang, "rules.add.ok", id=f.id))
                context.user_data[(k, gid)] = False
                context.user_data.pop(("auto2_params", gid), None)
                return
        if k == "await_welcome" and payload:
            # Get HTML formatted text to preserve formatting
            html_text = ""
            if update.effective_message.text:
                # Use text_html to preserve all formatting (bold, italic, links, etc.)
                html_text = update.effective_message.text_html
            elif update.effective_message.caption:
                # If admin sent a media with caption
                html_text = update.effective_message.caption_html
            
            async with db.SessionLocal() as s:  # type: ignore
                cfg = await SettingsRepo(s).get(gid, "welcome") or {}
                cfg["template"] = html_text
                await SettingsRepo(s).set(gid, "welcome", cfg)
                await s.commit()
            context.user_data[(k, gid)] = False
            lang = I18N.pick_lang(update)
            await update.effective_message.reply_text(t(lang, "panel.saved"))
            return
        if k == "await_link_domain" and payload:
            dom = (update.effective_message.text or "").strip().lower()
            if dom:
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "links") or {"block_all": False, "denylist": [], "action": "delete"}
                    deny = set(cfg.get("denylist", []))
                    deny.add(dom)
                    cfg["denylist"] = list(deny)
                    await SettingsRepo(s).set(gid, "links", cfg)
                    await s.commit()
                lang = I18N.pick_lang(update)
                await update.effective_message.reply_text(t(lang, "panel.saved"))
            context.user_data[(k, gid)] = False
            return
        if k == "await_link_allow_domain" and payload:
            dom = (update.effective_message.text or "").strip().lower()
            if dom:
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(gid, "links") or {"allowlist": []}
                    allow = set(cfg.get("allowlist", []))
                    allow.add(dom)
                    cfg["allowlist"] = list(allow)
                    await SettingsRepo(s).set(gid, "links", cfg)
                    await s.commit()
                lang = I18N.pick_lang(update)
                await update.effective_message.reply_text(t(lang, "panel.saved"))
            context.user_data[(k, gid)] = False
            return
        if k == "await_auto_announce" and isinstance(payload, dict):
            text = update.effective_message.text or ""
            delay = int(payload.get("delay", 5))
            interval = payload.get("interval")
            from datetime import datetime, timedelta
            from ...infra.repos import JobsRepo
            from ...features.automations.handlers import job_name

            run_at = datetime.utcnow() + timedelta(seconds=delay)
            async with db.SessionLocal() as s:  # type: ignore
                j = await JobsRepo(s).add(gid, "announce", {"text": text}, run_at, interval)
                await s.commit()
            # schedule now
            from ...features.automations.handlers import run_job, job_name
            if interval:
                context.job_queue.run_repeating(run_job, interval=interval, first=delay or 1, name=job_name(j.id), data={"job_id": j.id})
            else:
                context.job_queue.run_once(run_job, when=delay or 1, name=job_name(j.id), data={"job_id": j.id})
            lang = I18N.pick_lang(update)
            await update.effective_message.reply_text(t(lang, "panel.saved"))
            context.user_data[(k, gid)] = False
            return
        if k == "await_auto2_text" and isinstance(payload, dict):
            params = context.user_data.get(("auto2_params", gid)) or {}
            kind = params.get("kind")
            # Capture any message type for announcement: use copy_message
            src_chat = update.effective_chat.id
            src_mid = update.effective_message.message_id
            dval = params.get("delay")
            delay = int(dval) if dval is not None else 5
            interval = params.get("interval")
            log.debug(f"Processing auto2_text for gid={gid}, params={params}")
            if kind == "announce":
                # If this is part of a media group (album), accumulate and finalize after short delay
                mgid = getattr(update.effective_message, "media_group_id", None)
                log.debug(f"Media group check for gid={gid}: mgid={mgid}")
                if mgid:
                    # Use bot_data instead of user_data for job access
                    items_key = f"auto2_album:{gid}:{mgid}"
                    if not hasattr(context, 'bot_data'):
                        context.bot_data = {}
                    lst = context.bot_data.get(items_key)
                    if not isinstance(lst, list):
                        lst = []
                        context.bot_data[items_key] = lst
                    m = update.effective_message
                    item = None
                    if getattr(m, "photo", None):
                        item = {"type": "photo", "file_id": m.photo[-1].file_id, "caption": m.caption or None}
                    elif getattr(m, "video", None):
                        item = {"type": "video", "file_id": m.video.file_id, "caption": m.caption or None}
                    elif getattr(m, "document", None):
                        item = {"type": "document", "file_id": m.document.file_id, "caption": m.caption or None}
                    elif getattr(m, "audio", None):
                        item = {"type": "audio", "file_id": m.audio.file_id, "caption": m.caption or None}
                    if item:
                        lst.append(item)
                        log.debug(f"Added media item to album gid={gid} mgid={mgid}: {item['type']}, total items: {len(lst)}")
                    jobname = f"auto2_album:{gid}:{mgid}"
                    jobs = context.job_queue.get_jobs_by_name(jobname)
                    if not jobs:
                        log.info(f"Scheduling album finalization for gid={gid} mgid={mgid} in 1.2s")
                        # Store data references that will be updated as more items arrive
                        job_data = {
                            "gid": gid, 
                            "mgid": mgid,
                            "items_key": items_key,  # Pass the key to retrieve items later
                            "params": params.copy() if params else {},
                            "panel_ref": context.user_data.get(("auto2_panel", gid), {})
                        }
                        context.job_queue.run_once(_auto2_finalize_album, when=1.2, name=jobname, data=job_data)
                    else:
                        log.debug(f"Job already scheduled for album {mgid}, items now: {len(lst)}")
                    # Don't clear params here - they're needed by finalization job
                    return
                from .handlers import _panel_lang
                jid = await _auto2_schedule_announce(context, gid, "", delay, interval, copy={"chat_id": src_chat, "message_id": src_mid}, notify={"chat_id": update.effective_chat.id})
                # Update the panel message back to Automations menu (edit in place)
                panel_ref = context.user_data.get(("auto2_panel", gid)) or {}
                try:
                    if isinstance(panel_ref, dict) and panel_ref.get("chat_id") and panel_ref.get("message_id"):
                        lang2 = _panel_lang(update, gid)
                        kb = [
                            [InlineKeyboardButton(t(lang2, "panel.auto.add_announce"), callback_data=f"panel:group:{gid}:auto2:announce")],
                            [InlineKeyboardButton(t(lang2, "panel.auto.add_pin"), callback_data=f"panel:group:{gid}:auto2:pin")],
                            [
                                InlineKeyboardButton(t(lang2, "panel.auto.add_unmute"), callback_data=f"panel:group:{gid}:auto2:unmute"),
                                InlineKeyboardButton(t(lang2, "panel.auto.add_unban"), callback_data=f"panel:group:{gid}:auto2:unban"),
                            ],
                            [InlineKeyboardButton(t(lang2, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                        ]
                        await _safe_edit_msg(context, panel_ref["chat_id"], panel_ref["message_id"], key=f"auto2:menu:{gid}", text=t(lang2, "panel.auto.title"), kb_rows=kb)
                except BadRequest:
                    pass
                context.user_data[(k, gid)] = False
                context.user_data.pop(("auto2_params", gid), None)
                context.user_data.pop(("auto2_panel", gid), None)
                return
        if k == "await_auto_pintext" and isinstance(payload, dict):
            text = update.effective_message.text or ""
            interval = int(payload.get("interval", 3600))
            delay = 5
            from datetime import datetime, timedelta
            from ...infra.repos import JobsRepo
            from ...features.automations.handlers import run_job, job_name

            run_at = datetime.utcnow() + timedelta(seconds=delay)
            async with db.SessionLocal() as s:  # type: ignore
                j = await JobsRepo(s).add(gid, "rotate_pin", {"text": text, "unpin_previous": True}, run_at, interval)
                await s.commit()
            context.job_queue.run_repeating(run_job, interval=interval, first=delay or 1, name=job_name(j.id), data={"job_id": j.id})
            lang = I18N.pick_lang(update)
            await update.effective_message.reply_text(t(lang, "panel.saved"))
            context.user_data[(k, gid)] = False
            return
        if k == "await_auto_unmute_uid" and isinstance(payload, dict):
            uid_text = update.effective_message.text or ""
            if not uid_text.isdigit():
                continue
            uid = int(uid_text)
            delay = int(payload.get("delay", 600))
            from datetime import datetime, timedelta
            from ...infra.repos import JobsRepo
            from ...features.automations.handlers import run_job, job_name

            run_at = datetime.utcnow() + timedelta(seconds=delay)
            async with db.SessionLocal() as s:  # type: ignore
                j = await JobsRepo(s).add(gid, "timed_unmute", {"user_id": uid}, run_at, None)
                await s.commit()
            context.job_queue.run_once(run_job, when=delay or 1, name=job_name(j.id), data={"job_id": j.id})
            lang = I18N.pick_lang(update)
            await update.effective_message.reply_text(t(lang, "panel.saved"))
            context.user_data[(k, gid)] = False
            return
        if k == "await_auto_unban_uid" and isinstance(payload, dict):
            uid_text = update.effective_message.text or ""
            if not uid_text.isdigit():
                continue
            uid = int(uid_text)
            delay = int(payload.get("delay", 600))
            from datetime import datetime, timedelta
            from ...infra.repos import JobsRepo
            from ...features.automations.handlers import run_job, job_name

            run_at = datetime.utcnow() + timedelta(seconds=delay)
            async with db.SessionLocal() as s:  # type: ignore
                j = await JobsRepo(s).add(gid, "timed_unban", {"user_id": uid}, run_at, None)
                await s.commit()
            context.job_queue.run_once(run_job, when=delay or 1, name=job_name(j.id), data={"job_id": j.id})
            lang = I18N.pick_lang(update)
            await update.effective_message.reply_text(t(lang, "panel.saved"))
            context.user_data[(k, gid)] = False
            return


async def show_language(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    from ...core.i18n import I18N as _I

    current = _I.get_group_lang(gid) or "default"
    kb = [
        [
            InlineKeyboardButton("English", callback_data=f"panel:group:{gid}:language:en"),
            InlineKeyboardButton("العربية", callback_data=f"panel:group:{gid}:language:ar"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")],
    ]
    await update.effective_message.edit_text(t(lang, "panel.language.title") + f"\n{current}", reply_markup=InlineKeyboardMarkup(kb))


async def show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "welcome") or {"enabled": True}
    enabled = bool(cfg.get("enabled", True))
    ttl = int(cfg.get("ttl_sec", 0) or 0)
    kb = [
        [InlineKeyboardButton(t(lang, "panel.toggle"), callback_data=f"panel:group:{gid}:welcome:toggle")],
        [
            InlineKeyboardButton(t(lang, "panel.welcome.edit"), callback_data=f"panel:group:{gid}:welcome:edit"),
            InlineKeyboardButton(t(lang, "panel.rules.edittext"), callback_data=f"panel:group:{gid}:rules:edittext"),
        ],
        [
            InlineKeyboardButton(t(lang, "common.off"), callback_data=f"panel:group:{gid}:welcome:ttl:0"),
            InlineKeyboardButton("60s", callback_data=f"panel:group:{gid}:welcome:ttl:60"),
            InlineKeyboardButton("300s", callback_data=f"panel:group:{gid}:welcome:ttl:300"),
            InlineKeyboardButton("900s", callback_data=f"panel:group:{gid}:welcome:ttl:900"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")],
    ]
    status = "ON" if enabled else "OFF"
    ttl_label = t(lang, "common.off") if ttl <= 0 else f"{ttl}s"
    await update.effective_message.edit_text(
        t(lang, "panel.welcome.title") + f"\n{status}\n" + t(lang, "panel.welcome.ttl", state=ttl_label),
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def show_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        auto = await SettingsRepo(s).get(gid, "auto_approve_join") or {"enabled": False}
        ob = await SettingsRepo(s).get(gid, "onboarding") or {"require_accept": False}
        cap = await SettingsRepo(s).get(gid, "captcha") or {"enabled": False, "mode": "button", "timeout": 120}
    
    # Build status display with compatibility notes
    auto_enabled = auto.get("enabled", False)
    require_accept = ob.get("require_accept", False)
    captcha_enabled = cap.get("enabled", False)
    
    status_lines = [t(lang, "panel.onboarding.title")]
    
    # Auto-approve status
    status_lines.append(t(lang, "panel.onboarding.auto", state="ON" if auto_enabled else "OFF"))
    if auto_enabled and require_accept:
        status_lines.append("⚠️ Conflicts with Require Accept")
    
    # Require accept status  
    status_lines.append(t(lang, "panel.onboarding.require", state="ON" if require_accept else "OFF"))
    if require_accept and auto_enabled:
        status_lines.append("⚠️ Conflicts with Auto-Approve")
    
    # Require unmute status
    status_lines.append(t(lang, "panel.onboarding.require_unmute", state="ON" if ob.get("require_accept_unmute") else "OFF"))
    
    # CAPTCHA status
    status_lines.append(t(lang, "panel.onboarding.captcha", state="ON" if captcha_enabled else "OFF"))
    if captcha_enabled and not auto_enabled:
        status_lines.append("⚠️ Requires Auto-Approve to work")
    status_lines.append(f"CAPTCHA Mode: {cap.get('mode')} | Timeout: {cap.get('timeout')}s")
    
    label = "\n".join(status_lines)
    kb = [
        [InlineKeyboardButton(t(lang, "panel.toggle"), callback_data=f"panel:group:{gid}:onboarding:toggle")],
        [InlineKeyboardButton(t(lang, "panel.onboarding.toggle_require"), callback_data=f"panel:group:{gid}:onboarding:require")],
        [InlineKeyboardButton(t(lang, "panel.onboarding.captcha_toggle"), callback_data=f"panel:group:{gid}:onboarding:captcha:toggle")],
        [InlineKeyboardButton(t(lang, "panel.onboarding.toggle_unmute"), callback_data=f"panel:group:{gid}:onboarding:require_unmute")],
        [InlineKeyboardButton(t(lang, "panel.rules.edittext"), callback_data=f"panel:group:{gid}:rules:edittext")],
        [
            InlineKeyboardButton("button", callback_data=f"panel:group:{gid}:onboarding:captcha:mode:button"),
            InlineKeyboardButton("math", callback_data=f"panel:group:{gid}:onboarding:captcha:mode:math"),
        ],
        [
            InlineKeyboardButton("60s", callback_data=f"panel:group:{gid}:onboarding:captcha:timeout:60"),
            InlineKeyboardButton("120s", callback_data=f"panel:group:{gid}:onboarding:captcha:timeout:120"),
            InlineKeyboardButton("180s", callback_data=f"panel:group:{gid}:onboarding:captcha:timeout:180"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")],
    ]
    await safe_edit_message(update, label, reply_markup=InlineKeyboardMarkup(kb))


async def show_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "moderation") or {"warn_limit": 3, "delete_offense": True}
    warn_limit = int(cfg.get("warn_limit", 3))
    delete_offense = bool(cfg.get("delete_offense", True))
    text = t(lang, "panel.moderation.title") + "\n" + t(
        lang, "panel.moderation.warn_limit", n=warn_limit
    ) + "\n" + t(lang, "panel.moderation.delete_offense", state=("ON" if delete_offense else "OFF"))
    kb = [
        [
            InlineKeyboardButton("3", callback_data=f"panel:group:{gid}:moderation:warn:3"),
            InlineKeyboardButton("5", callback_data=f"panel:group:{gid}:moderation:warn:5"),
            InlineKeyboardButton("7", callback_data=f"panel:group:{gid}:moderation:warn:7"),
        ],
        [InlineKeyboardButton(t(lang, "panel.toggle"), callback_data=f"panel:group:{gid}:moderation:toggle_delete")],
        [
            InlineKeyboardButton("Ephemeral Off", callback_data=f"panel:group:{gid}:moderation:ephemeral:0"),
            InlineKeyboardButton("10s", callback_data=f"panel:group:{gid}:moderation:ephemeral:10"),
            InlineKeyboardButton("30s", callback_data=f"panel:group:{gid}:moderation:ephemeral:30"),
        ],
        [InlineKeyboardButton(t(lang, "panel.moderation.recent"), callback_data=f"panel:group:{gid}:moderation:recent")],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")],
    ]
    await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def show_links(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "links") or {"block_all": False, "denylist": [], "action": "delete"}
        night = await SettingsRepo(s).get(gid, "links.night") or {"enabled": False, "from_h": 0, "to_h": 6, "tz_offset_min": 0, "block_all": True}
    deny = list(cfg.get("denylist", []))
    block_all = bool(cfg.get("block_all", False))
    action = cfg.get("action", "delete")
    allow = list(cfg.get("allowlist", []))
    
    # Build text with current settings
    text = f"**{t(lang, 'panel.links.title')}**\n\n"
    text += f"🔗 **Block All Links:** {'✅ ON' if block_all else '❌ OFF'}\n"
    text += f"⚡ **Default Action:** {action.upper()}\n"
    text += f"🌙 **Night Mode:** {'✅ ON' if night.get('enabled') else '❌ OFF'}\n"
    
    # Show type-specific overrides if any
    types = cfg.get("types", {})
    has_overrides = any(types.get(cat) and types.get(cat) != "default" for cat in ["invites", "telegram", "shorteners", "other"])
    if has_overrides:
        text += f"🎯 **Type Overrides:** Active\n"
    
    if deny:
        text += f"🚫 **Blocked Domains:** {len(deny)}\n"
    if allow:
        text += f"✅ **Allowed Domains:** {len(allow)}\n"
    text += "\n"
    
    rows = [
        [InlineKeyboardButton(
            ("🔴 Disable" if block_all else "🟢 Enable") + " Block All Links", 
            callback_data=f"panel:group:{gid}:links:toggle_block"
        )],
        [InlineKeyboardButton("⚡ Default Action", callback_data="panel:noop")],
        [
            InlineKeyboardButton(("✅ " if action == "delete" else "") + t(lang, "action.delete"), callback_data=f"panel:group:{gid}:links:action:delete"),
            InlineKeyboardButton(("✅ " if action == "warn" else "") + t(lang, "action.warn"), callback_data=f"panel:group:{gid}:links:action:warn"),
            InlineKeyboardButton(("✅ " if action == "mute" else "") + t(lang, "action.mute"), callback_data=f"panel:group:{gid}:links:action:mute"),
            InlineKeyboardButton(("✅ " if action == "ban" else "") + t(lang, "action.ban"), callback_data=f"panel:group:{gid}:links:action:ban"),
        ],
        [InlineKeyboardButton("🎯 " + t(lang, "panel.links.type_actions"), callback_data=f"panel:group:{gid}:links:type:open")],
        [InlineKeyboardButton("🌙 " + t(lang, "panel.links.night"), callback_data=f"panel:group:{gid}:links:night:open")],
        [
            InlineKeyboardButton("➕ " + t(lang, "panel.links.add"), callback_data=f"panel:group:{gid}:links:add"),
            InlineKeyboardButton("✅ " + t(lang, "panel.links.allow_add"), callback_data=f"panel:group:{gid}:links:allow:add"),
        ],
    ]
    
    # List blocked domains with delete buttons
    if deny:
        rows.append([InlineKeyboardButton("🚫 Blocked Domains:", callback_data="panel:noop")])
        for d in deny[:6]:
            rows.append([
                InlineKeyboardButton(f"🔴 {d}", callback_data="panel:noop"), 
                InlineKeyboardButton("🗑", callback_data=f"panel:group:{gid}:links:del:{d}")
            ])
        if len(deny) > 6:
            rows.append([InlineKeyboardButton(f"... and {len(deny) - 6} more", callback_data="panel:noop")])
    
    # List allowed domains with delete buttons
    if allow:
        rows.append([InlineKeyboardButton("✅ Allowed Domains:", callback_data="panel:noop")])
        for a in allow[:6]:
            rows.append([
                InlineKeyboardButton(f"🟢 {a}", callback_data="panel:noop"), 
                InlineKeyboardButton("🗑", callback_data=f"panel:group:{gid}:links:allow:del:{a}")
            ])
        if len(allow) > 6:
            rows.append([InlineKeyboardButton(f"... and {len(allow) - 6} more", callback_data="panel:noop")])
    
    rows.append([InlineKeyboardButton("⬅ " + t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")])
    await safe_edit_message(update, text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


async def show_links_type_actions(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "links") or {"types": {}, "action": "delete"}
    
    types = cfg.get("types", {})
    default_action = cfg.get("action", "delete")  # Get the default action from main links config
    
    cats = [
        ("invites", t(lang, "panel.links.cat.invites"), "💌", "Telegram group/channel invites"),
        ("telegram", t(lang, "panel.links.cat.telegram"), "✈️", "t.me links"),
        ("usernames", t(lang, "panel.links.cat.usernames"), "👤", "@usernames and mentions"),
        ("shorteners", t(lang, "panel.links.cat.shorteners"), "🔗", "URL shorteners (bit.ly, etc)"),
        ("other", t(lang, "panel.links.cat.other"), "🌐", "All other links"),
    ]
    
    # Build text with current settings
    text = f"**{t(lang, 'panel.links.type_actions')}**\n\n"
    text += f"📌 **Default Action:** {default_action.upper()}\n"
    text += "_Configure specific actions for different link types:_\n\n"
    
    for cat_id, cat_label, emoji, description in cats:
        act = types.get(cat_id, "default")  # Show "default" if not specifically set
        if act == "default":
            display_action = f"DEFAULT ({default_action.upper()})"
        else:
            display_action = act.upper()
        text += f"{emoji} **{cat_label}:** {display_action}\n"
    
    text += "\n_Note: 'Default' uses the main action from Links Policy_"
    
    rows = []
    for key, label, emoji, description in cats:
        current_action = types.get(key, "default")
        
        # Display the category with its current setting
        if current_action == "default":
            display_text = f"{emoji} {label}: DEFAULT ({default_action.upper()})"
        else:
            display_text = f"{emoji} {label}: {current_action.upper()}"
        
        rows.append([InlineKeyboardButton(display_text, callback_data="panel:noop")])
        
        # Action buttons with checkmarks
        action_row = []
        
        # Add "Use Default" option
        if current_action == "default":
            action_row.append(InlineKeyboardButton("✅ Default", callback_data=f"panel:group:{gid}:links:type:{key}:default"))
        else:
            action_row.append(InlineKeyboardButton("Default", callback_data=f"panel:group:{gid}:links:type:{key}:default"))
        
        # Add specific action options
        for action in ["allow", "delete", "warn", "mute", "ban"]:
            if current_action == action:
                btn_text = f"✅ {t(lang, f'action.{action}')}"
            else:
                btn_text = t(lang, f"action.{action}")
            
            # Limit buttons per row for better display
            if len(action_row) >= 3:
                rows.append(action_row)
                action_row = []
            
            action_row.append(InlineKeyboardButton(btn_text, callback_data=f"panel:group:{gid}:links:type:{key}:{action}"))
        
        if action_row:
            rows.append(action_row)
    
    rows.append([InlineKeyboardButton("⬅ " + t(lang, "panel.back"), callback_data=f"panel:group:{gid}:links:open")])
    await safe_edit_message(update, text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


async def show_links_night(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        night = await SettingsRepo(s).get(gid, "links.night") or {"enabled": False, "from_h": 0, "to_h": 6, "tz_offset_min": 0, "block_all": True}
    enabled = bool(night.get("enabled"))
    from_h = int(night.get("from_h", 0))
    to_h = int(night.get("to_h", 6))
    tz = int(night.get("tz_offset_min", 0))
    kb = [
        [InlineKeyboardButton(t(lang, "panel.toggle"), callback_data=f"panel:group:{gid}:links:night:toggle")],
        [InlineKeyboardButton("BlockAll", callback_data=f"panel:group:{gid}:links:night:block_toggle")],
        [
            InlineKeyboardButton("00-06", callback_data=f"panel:group:{gid}:links:night:time:0:6"),
            InlineKeyboardButton("22-06", callback_data=f"panel:group:{gid}:links:night:time:22:6"),
            InlineKeyboardButton("23-07", callback_data=f"panel:group:{gid}:links:night:time:23:7"),
        ],
        [InlineKeyboardButton("TZ +0", callback_data=f"panel:group:{gid}:links:night:tz:0"), InlineKeyboardButton("TZ +120", callback_data=f"panel:group:{gid}:links:night:tz:120")],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:links:open")],
    ]
    text = t(lang, "panel.links.night_title") + f"\nEnabled: {'ON' if enabled else 'OFF'} | {from_h:02d}-{to_h:02d} | TZ offset: {tz}min"
    await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def show_locks(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        locks = await SettingsRepo(s).get(gid, "locks") or {}
    forwards = locks.get("forwards", "allow")
    media = locks.get("media", {})
    media_types = ["photo", "video", "document", "sticker", "voice", "audio", "animation"]
    
    # Build text with current settings
    text = f"**{t(lang, 'panel.locks.title')}**\n\n"
    text += f"**Forwards:** {forwards.upper()}\n"
    for mt in media_types:
        action = media.get(mt, "allow")
        text += f"**{mt.capitalize()}:** {action.upper()}\n"
    
    rows = [
        [InlineKeyboardButton(f"📤 {t(lang, 'panel.locks.forwards')}", callback_data="panel:noop")],
        [
            InlineKeyboardButton(("✅ " if forwards == "allow" else "") + t(lang, "action.allow"), callback_data=f"panel:group:{gid}:locks:forwards:allow"),
            InlineKeyboardButton(("✅ " if forwards == "delete" else "") + t(lang, "action.delete"), callback_data=f"panel:group:{gid}:locks:forwards:delete"),
            InlineKeyboardButton(("✅ " if forwards == "warn" else "") + t(lang, "action.warn"), callback_data=f"panel:group:{gid}:locks:forwards:warn"),
            InlineKeyboardButton(("✅ " if forwards == "mute" else "") + t(lang, "action.mute"), callback_data=f"panel:group:{gid}:locks:forwards:mute"),
            InlineKeyboardButton(("✅ " if forwards == "ban" else "") + t(lang, "action.ban"), callback_data=f"panel:group:{gid}:locks:forwards:ban"),
        ],
        [InlineKeyboardButton(f"🎨 {t(lang, 'panel.locks.media')}", callback_data="panel:noop")],
    ]
    
    # Add media type controls with visual indicators
    for mt in media_types:
        current_action = media.get(mt, "allow")
        emoji_map = {
            "photo": "🖼",
            "video": "🎥", 
            "document": "📎",
            "sticker": "🎭",
            "voice": "🎤",
            "audio": "🎵",
            "animation": "🎬"
        }
        emoji = emoji_map.get(mt, "📁")
        rows.append([InlineKeyboardButton(f"{emoji} {mt.capitalize()}: {current_action.upper()}", callback_data="panel:noop")])
        rows.append([
            InlineKeyboardButton(("✅ " if current_action == "allow" else "") + t(lang, "action.allow"), callback_data=f"panel:group:{gid}:locks:media:{mt}:allow"),
            InlineKeyboardButton(("✅ " if current_action == "delete" else "") + t(lang, "action.delete"), callback_data=f"panel:group:{gid}:locks:media:{mt}:delete"),
            InlineKeyboardButton(("✅ " if current_action == "warn" else "") + t(lang, "action.warn"), callback_data=f"panel:group:{gid}:locks:media:{mt}:warn"),
            InlineKeyboardButton(("✅ " if current_action == "mute" else "") + t(lang, "action.mute"), callback_data=f"panel:group:{gid}:locks:media:{mt}:mute"),
            InlineKeyboardButton(("✅ " if current_action == "ban" else "") + t(lang, "action.ban"), callback_data=f"panel:group:{gid}:locks:media:{mt}:ban"),
        ])
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")])
    await safe_edit_message(update, text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


async def show_recent_violators(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        from sqlalchemy import select, desc
        from ...infra.models import AuditLog

        q = (
            select(AuditLog)
            .where(AuditLog.group_id == gid)
            .order_by(desc(AuditLog.id))
            .limit(50)
        )
        rows = (await s.execute(q)).scalars().all()
    seen = set()
    buttons = []
    for r in rows:
        if not r.target_user_id:
            continue
        if r.target_user_id in seen:
            continue
        seen.add(r.target_user_id)
        label = f"{r.target_user_id} • {r.action}"
        buttons.append(
            [
                InlineKeyboardButton(label, callback_data="panel:noop"),
                InlineKeyboardButton(t(lang, "action.warn"), callback_data=f"panel:group:{gid}:moderation:quick:{r.target_user_id}:warn"),
                InlineKeyboardButton(t(lang, "action.mute"), callback_data=f"panel:group:{gid}:moderation:quick:{r.target_user_id}:mute"),
                InlineKeyboardButton(t(lang, "action.ban"), callback_data=f"panel:group:{gid}:moderation:quick:{r.target_user_id}:ban"),
            ]
        )
        if len(buttons) >= 10:
            break
    buttons.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:moderation")])
    await update.effective_message.edit_text(t(lang, "panel.moderation.recent"), reply_markup=InlineKeyboardMarkup(buttons))


async def apply_quick_action(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, uid: int, act: str) -> None:
    lang = I18N.pick_lang(update)
    if act == "warn":
        await update.effective_message.reply_text(t(lang, "mod.warned"))
        return
    from ..antispam.handlers import get_antispam_config
    cfg = await get_antispam_config(gid)
    if act == "mute":
        until = int(time.time()) + int(cfg["mute_seconds"])
        try:
            await context.bot.restrict_chat_member(gid, uid, permissions=ChatPermissions(can_send_messages=False), until_date=until)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("quick mute failed gid=%s uid=%s: %s", gid, uid, e)
        await update.effective_message.reply_text(t(lang, "mod.muted"))
        return
    if act == "ban":
        until = int(time.time()) + int(cfg["ban_seconds"])
        try:
            await context.bot.ban_chat_member(gid, uid, until_date=until)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("quick ban failed gid=%s uid=%s: %s", gid, uid, e)
        await update.effective_message.reply_text(t(lang, "mod.banned"))
        return


async def rule_config(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, rid: int) -> None:
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        from ...infra.models import Filter as F

        f = await s.get(F, rid)
    if not f or f.group_id != gid:
        return
    kb = [
        [
            InlineKeyboardButton("Off", callback_data=f"panel:group:{gid}:rules:cfg:{rid}:preset:off"),
            InlineKeyboardButton("2 in 5m -> mute", callback_data=f"panel:group:{gid}:rules:cfg:{rid}:preset:warn2"),
            InlineKeyboardButton("3 in 10m -> ban", callback_data=f"panel:group:{gid}:rules:cfg:{rid}:preset:ban3"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:rules:list:0")],
    ]
    await update.effective_message.edit_text(f"Rule #{rid} [{f.type}/{f.action}]", reply_markup=InlineKeyboardMarkup(kb))


async def show_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    """Show AI response settings for a group."""
    import os
    lang = _panel_lang(update, gid)
    
    # Check which AI providers are configured
    gemini_configured = bool(os.getenv("GEMINI_API_KEY"))
    openai_configured = bool(os.getenv("OPENAI_API_KEY"))
    api_key_configured = gemini_configured or openai_configured
    
    async with db.SessionLocal() as s:  # type: ignore
        settings = await SettingsRepo(s).get(gid, "ai_response") or {
            "enabled": False,
            "model": "gemini-2.5-flash",
            "max_tokens": 800,
            "temperature": 0.7,
            "reply_only": True,
        }
    
    # Build status text
    text = f"**{t(lang, 'panel.ai.title')}**\n\n"
    
    if not api_key_configured:
        text += f"⚠️ {t(lang, 'panel.ai.no_api_key')}\n\n"
    
    status = "✅ " + t(lang, "panel.ai.status_enabled") if settings["enabled"] else "❌ " + t(lang, "panel.ai.status_disabled")
    text += f"{t(lang, 'panel.ai.status')}: {status}\n"
    model_name = settings.get('model', 'gemini-2.5-flash')
    text += f"{t(lang, 'panel.ai.model')}: {model_name}\n"
    text += f"{t(lang, 'panel.ai.max_tokens')}: {settings.get('max_tokens', 500)}\n"
    
    # GPT-5 models only support temperature=1.0
    if "gpt-5" in model_name:
        text += f"{t(lang, 'panel.ai.temperature')}: 1.0 (Fixed for GPT-5)\n"
    else:
        text += f"{t(lang, 'panel.ai.temperature')}: {settings.get('temperature', 0.7)}\n"
    
    reply_mode = t(lang, "panel.ai.reply_only_yes") if settings.get("reply_only", True) else t(lang, "panel.ai.reply_only_no")
    text += f"{t(lang, 'panel.ai.reply_mode')}: {reply_mode}\n"
    
    # Build keyboard
    rows = []
    
    # Enable/Disable toggle
    if api_key_configured:
        if settings["enabled"]:
            rows.append([InlineKeyboardButton(
                "🔴 " + t(lang, "panel.ai.disable"),
                callback_data=f"panel:group:{gid}:ai:toggle"
            )])
        else:
            rows.append([InlineKeyboardButton(
                "🟢 " + t(lang, "panel.ai.enable"),
                callback_data=f"panel:group:{gid}:ai:toggle"
            )])

        # Model selection
        if gemini_configured:
            rows.append([
                InlineKeyboardButton(
                    "Gemini 2.5 Flash",
                    callback_data=f"panel:group:{gid}:ai:model:gemini-2.5-flash",
                )
            ])
        if openai_configured:
            rows.append([
                InlineKeyboardButton("GPT-5 Mini", callback_data=f"panel:group:{gid}:ai:model:gpt-5-mini-2025-08-07"),
                InlineKeyboardButton("GPT-4o", callback_data=f"panel:group:{gid}:ai:model:gpt-4o"),
                InlineKeyboardButton("GPT-4o Mini", callback_data=f"panel:group:{gid}:ai:model:gpt-4o-mini"),
            ])
        
        # Reply mode toggle
        reply_btn_text = "📨 Reply Only" if not settings.get("reply_only", True) else "💬 All Mentions"
        rows.append([InlineKeyboardButton(
            reply_btn_text,
            callback_data=f"panel:group:{gid}:ai:reply_mode"
        )])
        
        # Temperature adjustment (not available for GPT-5 models)
        current_model = settings.get("model", "gemini-2.5-flash")
        if "gpt-5" not in current_model:
            rows.append([
                InlineKeyboardButton("🧊 Focused", callback_data=f"panel:group:{gid}:ai:temp:0.3"),
                InlineKeyboardButton("⚖️ Balanced", callback_data=f"panel:group:{gid}:ai:temp:0.7"),
                InlineKeyboardButton("🎨 Creative", callback_data=f"panel:group:{gid}:ai:temp:1.0"),
            ])
    
    # Back button
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")])
    
    await update.effective_message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown"
    )


async def show_automations(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    from datetime import timezone
    lang = _panel_lang(update, gid)
    async with db.SessionLocal() as s:  # type: ignore
        from ...infra.repos import JobsRepo
        jobs = await JobsRepo(s).list_by_group(gid, limit=50)
    
    # Build text list of automations
    text = f"**{t(lang, 'panel.automations')}**\n\n"
    
    if jobs:
        for j in jobs[:20]:  # Show first 20 as text
            next_label = j.run_at.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            paused = bool(isinstance(j.payload, dict) and j.payload.get("paused"))
            status = "⏸ Paused" if paused else "✅ Active"
            text += f"#{j.id} • {j.kind} • {status}\n"
            text += f"   Next run: {next_label}\n\n"
        
        if len(jobs) > 20:
            text += f"\n_... and {len(jobs) - 20} more automations_\n"
    else:
        text += t(lang, "panel.auto.empty")
    
    # Keep only action buttons, not job buttons
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(t(lang, "panel.auto.add_announce"), callback_data=f"panel:group:{gid}:auto2:announce")])
    rows.append([InlineKeyboardButton(t(lang, "panel.auto.add_pin"), callback_data=f"panel:group:{gid}:auto2:pin")])
    rows.append([
        InlineKeyboardButton(t(lang, "panel.auto.add_unmute"), callback_data=f"panel:group:{gid}:auto2:unmute"),
        InlineKeyboardButton(t(lang, "panel.auto.add_unban"), callback_data=f"panel:group:{gid}:auto2:unban"),
    ])
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")])
    await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


# ----- Automations v2 (wizard) -----
def _aw(ctx: ContextTypes.DEFAULT_TYPE, gid: int) -> dict:
    key = ("auto2", gid)
    w = ctx.user_data.get(key)
    if not isinstance(w, dict):
        w = {}
        ctx.user_data[key] = w
    return w


async def auto2_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    kb = [
        [InlineKeyboardButton(t(lang, "panel.auto.add_announce"), callback_data=f"panel:group:{gid}:auto2:announce")],
        [InlineKeyboardButton(t(lang, "panel.auto.add_pin"), callback_data=f"panel:group:{gid}:auto2:pin")],
        [
            InlineKeyboardButton(t(lang, "panel.auto.add_unmute"), callback_data=f"panel:group:{gid}:auto2:unmute"),
            InlineKeyboardButton(t(lang, "panel.auto.add_unban"), callback_data=f"panel:group:{gid}:auto2:unban"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
    ]
    await _safe_edit(update, context, key=f"auto2:menu:{gid}", text=t(lang, "panel.auto.title"), kb_rows=kb)


async def auto2_pick_announce_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    w = _aw(context, gid)
    w.clear(); w.update({"kind": "announce"})
    kb = [[
        InlineKeyboardButton(t(lang, "panel.auto.once"), callback_data=f"panel:group:{gid}:auto2:announce:once"),
        InlineKeyboardButton(t(lang, "panel.auto.repeat"), callback_data=f"panel:group:{gid}:auto2:announce:repeat"),
    ], [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:auto2:menu")]]
    await _safe_edit(update, context, key=f"auto2:announce:mode:{gid}", text=t(lang, "panel.auto.pick_mode"), kb_rows=kb)


async def auto2_pick_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, key: str) -> None:
    lang = _panel_lang(update, gid)
    kb = [[
        InlineKeyboardButton("Now", callback_data=f"panel:group:{gid}:auto2:{key}:delay:0"),
        InlineKeyboardButton("10m", callback_data=f"panel:group:{gid}:auto2:{key}:delay:600"),
        InlineKeyboardButton("1h", callback_data=f"panel:group:{gid}:auto2:{key}:delay:3600"),
        InlineKeyboardButton("1d", callback_data=f"panel:group:{gid}:auto2:{key}:delay:86400"),
    ], [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:auto2:menu")]]
    await _safe_edit(update, context, key=f"auto2:{key}:pick_delay:{gid}", text=t(lang, "panel.auto.pick_delay"), kb_rows=kb)


async def auto2_pick_interval(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = _panel_lang(update, gid)
    kb = [[
        InlineKeyboardButton("1h", callback_data=f"panel:group:{gid}:auto2:announce:interval:3600"),
        InlineKeyboardButton("6h", callback_data=f"panel:group:{gid}:auto2:announce:interval:21600"),
        InlineKeyboardButton("1d", callback_data=f"panel:group:{gid}:auto2:announce:interval:86400"),
    ], [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:auto2:menu")]]
    await _safe_edit(update, context, key=f"auto2:announce:pick_interval:{gid}", text=t(lang, "panel.auto.pick_interval"), kb_rows=kb)




async def _auto2_finalize_album(context: ContextTypes.DEFAULT_TYPE) -> None:
    # Initialize variables outside try block
    gid = None
    mgid = None
    items = []
    params = {}
    panel_ref = {}
    delay = 5
    interval = None
    items_key = None
    meta_key = None
    panel_key = None
    
    try:
        if context.job is None:
            log.error("context.job is None in _auto2_finalize_album")
            return
        data = context.job.data if context.job and context.job.data else {}
        gid = data.get("gid") if data else None
        mgid = data.get("mgid") if data else None
        
        log.info(f"Finalizing album for gid={gid} mgid={mgid}, job data keys: {list(data.keys())}")
        if gid is None or mgid is None:
            log.error(f"Missing gid or mgid: gid={gid}, mgid={mgid}")
            return
            
        # Set up keys
        items_key = data.get("items_key") or f"auto2_album:{gid}:{mgid}"
        meta_key = ("auto2_params", gid)
        panel_key = ("auto2_panel", gid)
        
        # Try to get items from bot_data using the key
        items = []
        if hasattr(context, 'bot_data') and context.bot_data and items_key:
            items = context.bot_data.get(items_key, [])
            log.info(f"Retrieved {len(items)} items from bot_data with key {items_key}")
        
        # Fallback to job data if no items found
        if not items:
            items = data.get("items", [])
            log.info(f"Using {len(items)} items from job data (fallback)")
            
        params = data.get("params", {})
        panel_ref = data.get("panel_ref", {})
        if not items:
            log.warning(f"No items found for album gid={gid} mgid={mgid}")
            return
        # Schedule album as announce
        delay = int(params.get("delay") if params else 5) if params else 5
        interval = params.get("interval") if params else None
    except Exception as e:
        log.error(f"Error in _auto2_finalize_album at params processing: {e}")
        # Use defaults if error occurred
        delay = 5
        interval = None
    # Compute lang for panel edit
    try:
        from ...core.i18n import I18N as _I
        lang = _I.get_group_lang(gid) or 'en'
    except Exception:
        lang = 'en'
    # Build album media payload
    album_media = items  # list of dicts with type, file_id, caption
    from .handlers import _panel_lang
    notify = None
    try:
        if panel_ref and isinstance(panel_ref, dict) and panel_ref.get("chat_id"):
            notify = {"chat_id": panel_ref.get("chat_id")}
    except Exception as e:
        log.error(f"Error getting notify from panel_ref: {e}, panel_ref: {panel_ref}")
        notify = None
    log.info(f"Scheduling album announcement for gid={gid} with {len(album_media)} items, delay={delay}, interval={interval}")
    await _auto2_schedule_announce(context, gid, '', delay, interval, copy=None, notify=notify, album_media=album_media)
    # Edit panel back to menu if we have ref
    try:
        log.info(f"Attempting to edit panel back to menu. panel_ref: {panel_ref}")
        if panel_ref and isinstance(panel_ref, dict) and panel_ref.get("chat_id") and panel_ref.get("message_id"):
            kb = [
                [InlineKeyboardButton(t(lang, "panel.auto.add_announce"), callback_data=f"panel:group:{gid}:auto2:announce")],
                [InlineKeyboardButton(t(lang, "panel.auto.add_pin"), callback_data=f"panel:group:{gid}:auto2:pin")],
                [
                    InlineKeyboardButton(t(lang, "panel.auto.add_unmute"), callback_data=f"panel:group:{gid}:auto2:unmute"),
                    InlineKeyboardButton(t(lang, "panel.auto.add_unban"), callback_data=f"panel:group:{gid}:auto2:unban"),
                ],
                [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
            ]
            await _safe_edit_msg(context, panel_ref["chat_id"], panel_ref["message_id"], key=f"auto2:menu:{gid}", text=t(lang, "panel.auto.title"), kb_rows=kb)
            log.info(f"Successfully edited panel back to automations menu for gid={gid}")
        else:
            log.warning(f"Could not edit panel - missing data. chat_id: {panel_ref.get('chat_id') if panel_ref else None}, message_id: {panel_ref.get('message_id') if panel_ref else None}")
    except Exception as e:
        log.error(f"Error editing panel back to menu: {e}")
    # Cleanup
    try:
        # Clean up bot_data
        if hasattr(context, 'bot_data') and context.bot_data and items_key:
            context.bot_data.pop(items_key, None)
            log.info(f"Cleaned up bot_data key: {items_key}")
            
        # Clean up user_data if available
        if context.user_data:
            if gid is not None:
                context.user_data.pop(("await_auto2_text", gid), None)
            if meta_key:
                context.user_data.pop(meta_key, None)
            if panel_key:
                context.user_data.pop(panel_key, None)
    except Exception as e:
        log.error(f"Error during cleanup in _auto2_finalize_album: {e}")
async def auto2_prompt_text(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, key: str) -> None:
    lang = _panel_lang(update, gid)
    context.user_data[("await_auto2_text", gid)] = {"key": key}
    # Remember the panel message to edit later after content is received
    context.user_data[("auto2_panel", gid)] = {"chat_id": update.effective_chat.id, "message_id": update.effective_message.message_id}
    await _safe_edit(update, context, key=f"auto2:{key}:prompt:{gid}", text=t(lang, "panel.auto.prompt_text"), kb_rows=[[InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:auto2:menu")]])


async def _auto2_schedule_announce(context: ContextTypes.DEFAULT_TYPE, gid: int, text: str, delay: int, interval: int | None, copy: dict | None = None, album_media: list | None = None, notify: dict | None = None) -> int:
    from datetime import datetime, timedelta
    from ...infra.repos import JobsRepo
    from ...features.automations.handlers import run_job, job_name
    run_at = datetime.utcnow() + timedelta(seconds=delay)
    payload: dict = {}
    if copy:
        payload["copy"] = copy
    elif text:
        payload["text"] = text
    if notify:
        payload["notify"] = notify
    if album_media:
        payload["album_media"] = album_media
    async with db.SessionLocal() as s:  # type: ignore
        j = await JobsRepo(s).add(gid, "announce", payload, run_at, interval)
        await s.commit()
    if interval:
        # Use a minimal 1s delay to allow payload updates (e.g., copy source)
        first = delay if (delay is not None and delay > 0) else 1
        context.job_queue.run_repeating(run_job, interval=interval, first=first, name=job_name(j.id), data={"job_id": j.id})
    else:
        # Use a minimal 1s delay to allow payload updates before first run
        when = delay if (delay is not None and delay > 0) else 1
        context.job_queue.run_once(run_job, when=when, name=job_name(j.id), data={"job_id": j.id})
    return j.id


async def show_audit(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, page: int) -> None:
    lang = _panel_lang(update, gid)
    page_size = 10
    async with db.SessionLocal() as s:  # type: ignore
        from sqlalchemy import select, desc
        from ...infra.models import AuditLog

        rows = (await s.execute(select(AuditLog).where(AuditLog.group_id == gid).order_by(desc(AuditLog.id)).limit(200))).scalars().all()
    start = page * page_size
    items = rows[start : start + page_size]
    lines = [f"#{a.id} {a.action} actor={a.actor_id} target={a.target_user_id}" for a in items]
    text = t(lang, "panel.audit.title") + "\n" + ("\n".join(lines) if lines else t(lang, "panel.audit.empty"))
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅", callback_data=f"panel:group:{gid}:audit:{page-1}"))
    if start + page_size < len(rows):
        nav.append(InlineKeyboardButton("➡", callback_data=f"panel:group:{gid}:audit:{page+1}"))
    kb = [nav] if nav else []
    kb.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")])
    await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb))



def register_callbacks(app):
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^panel:"))
    # Accept any private message (not commands) for wizards (rules/automations)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_rules_input))
