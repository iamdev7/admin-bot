from __future__ import annotations

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatPermissions
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters
import time

from ...core.i18n import I18N, t
from ...core.permissions import require_admin
from ...infra import db
from ...infra.repos import GroupsRepo
from ...infra.settings_repo import SettingsRepo
from ...infra.repos import FiltersRepo


async def start_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_chat:
        return
    if update.effective_chat.type != "private":
        return
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        groups = await GroupsRepo(s).list_admin_groups(update.effective_user.id)
    if not groups:
        await update.effective_message.reply_text(t(lang, "panel.no_groups"))
        return
    buttons = [
        [InlineKeyboardButton(g.title, callback_data=f"panel:group:{g.id}:tab:home")]
        for g in groups[:25]
    ]
    await update.effective_message.reply_text(
        t(lang, "panel.pick_group"), reply_markup=InlineKeyboardMarkup(buttons)
    )


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
        InlineKeyboardButton(t(lang, "panel.tab.audit"), callback_data=f"panel:group:{gid}:tab:audit"),
    ]
    return InlineKeyboardMarkup([tabs, row2, [InlineKeyboardButton(t(lang, "panel.back"), callback_data="panel:back")]])


async def open_group(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
    await update.effective_message.edit_text(t(lang, "panel.tabs"), reply_markup=tabs_keyboard(lang, gid))


async def show_antispam(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
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
    lang = I18N.pick_lang(update)
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
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        rules = await FiltersRepo(s).list_rules(gid, limit=200)
    page_size = 10
    start = page * page_size
    items = rules[start : start + page_size]
    if not items:
        return await update.effective_message.edit_text(
            t(lang, "rules.list.empty"), reply_markup=tabs_keyboard(lang, gid)
        )
    rows = []
    for r in items:
        label = f"#{r.id} [{r.type}/{r.action}]"
        rows.append(
            [
                InlineKeyboardButton(label, callback_data=f"panel:group:{gid}:rules:cfg:{r.id}"),
                InlineKeyboardButton("✖", callback_data=f"panel:group:{gid}:rules:del:{r.id}"),
            ]
        )
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅", callback_data=f"panel:group:{gid}:rules:list:{page-1}"))
    if start + page_size < len(rules):
        nav.append(InlineKeyboardButton("➡", callback_data=f"panel:group:{gid}:rules:list:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")])
    await update.effective_message.edit_text(t(lang, "panel.rules.list_title"), reply_markup=InlineKeyboardMarkup(rows))


async def rules_add_pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
    kb = [
        [
            InlineKeyboardButton("word", callback_data=f"panel:group:{gid}:rules:add:type:word"),
            InlineKeyboardButton("regex", callback_data=f"panel:group:{gid}:rules:add:type:regex"),
        ],
        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")],
    ]
    await update.effective_message.edit_text(t(lang, "panel.rules.add_type"), reply_markup=InlineKeyboardMarkup(kb))


async def rules_add_pick_action(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, ftype: str) -> None:
    lang = I18N.pick_lang(update)
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
        return await start_panel(update, context)
    if len(parts) >= 4 and parts[0] == "panel" and parts[1] == "group":
        gid = int(parts[2])
        user_id = update.effective_user.id if update.effective_user else 0
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
            if tab == "audit":
                return await show_audit(update, context, gid, page=0)
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
                await update.effective_message.reply_text(t(lang, "rules.del.ok" if ok else "rules.del.missing"))
                return await list_rules(update, context, gid, page=0)
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
                    await SettingsRepo(s).set(gid, "onboarding", cfg)
                    await s.commit()
                return await show_onboarding(update, context, gid)
            if parts[4] == "captcha":
                async with db.SessionLocal() as s:  # type: ignore
                    cap = await SettingsRepo(s).get(gid, "captcha") or {"enabled": False, "mode": "button", "timeout": 120}
                    if len(parts) >= 6 and parts[5] == "toggle":
                        cap["enabled"] = not bool(cap.get("enabled", False))
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
            if parts[4] == "type" and len(parts) >= 7 and parts[5] in {"invites", "telegram", "shorteners", "other"}:
                cat = parts[5]
                action = parts[6]
                if action in {"allow", "delete", "warn", "mute", "ban"}:
                    async with db.SessionLocal() as s:  # type: ignore
                        cfg = await SettingsRepo(s).get(gid, "links") or {"types": {}}
                        types = cfg.get("types", {})
                        types[cat] = action
                        cfg["types"] = types
                        await SettingsRepo(s).set(gid, "links", cfg)
                        await s.commit()
                    return await show_links_type_actions(update, context, gid)
            if parts[4] == "add":
                context.user_data[("await_link_domain", gid)] = True
                lang = I18N.pick_lang(update)
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
            if parts[4] == "allow" and len(parts) >= 6:
                if parts[5] == "add":
                    context.user_data[("await_link_allow_domain", gid)] = True
                    lang = I18N.pick_lang(update)
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
        if len(parts) >= 5 and parts[3] == "auto":
            if parts[4] == "add":
                # choose once or repeat and delay/interval
                kb = [
                    [
                        InlineKeyboardButton(t(lang, "panel.auto.once"), callback_data=f"panel:group:{gid}:auto:add:once"),
                        InlineKeyboardButton(t(lang, "panel.auto.repeat"), callback_data=f"panel:group:{gid}:auto:add:repeat"),
                    ],
                    [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                ]
                return await update.effective_message.edit_text(t(lang, "panel.auto.pick_mode"), reply_markup=InlineKeyboardMarkup(kb))
            if parts[4] == "add" and len(parts) >= 6 and parts[5] == "pin":
                kb = [
                    [
                        InlineKeyboardButton("1h", callback_data=f"panel:group:{gid}:auto:add:pin:interval:3600"),
                        InlineKeyboardButton("6h", callback_data=f"panel:group:{gid}:auto:add:pin:interval:21600"),
                        InlineKeyboardButton("1d", callback_data=f"panel:group:{gid}:auto:add:pin:interval:86400"),
                    ],
                    [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                ]
                return await update.effective_message.edit_text(t(lang, "panel.auto.pin_pick_interval"), reply_markup=InlineKeyboardMarkup(kb))
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
                return await update.effective_message.edit_text(t(lang, "panel.auto.pick_delay"), reply_markup=InlineKeyboardMarkup(kb))
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
                    return await update.effective_message.edit_text(t(lang, "panel.auto.pick_delay"), reply_markup=InlineKeyboardMarkup(kb))
                else:
                    kb = [
                        [
                            InlineKeyboardButton("1h", callback_data=f"panel:group:{gid}:auto:add:repeat:interval:3600"),
                            InlineKeyboardButton("6h", callback_data=f"panel:group:{gid}:auto:add:repeat:interval:21600"),
                            InlineKeyboardButton("1d", callback_data=f"panel:group:{gid}:auto:add:repeat:interval:86400"),
                        ],
                        [InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:automations")],
                    ]
                    return await update.effective_message.edit_text(t(lang, "panel.auto.pick_interval"), reply_markup=InlineKeyboardMarkup(kb))
            if parts[4] == "add" and len(parts) >= 8 and parts[5] == "once" and parts[6] == "delay":
                delay = int(parts[7])
                context.user_data[("await_auto_announce", gid)] = {"delay": delay, "interval": None}
                return await update.effective_message.reply_text(t(lang, "panel.auto.prompt_text"))
            if parts[4] == "add" and len(parts) >= 8 and parts[5] == "repeat" and parts[6] == "interval":
                interval = int(parts[7])
                context.user_data[("await_auto_announce", gid)] = {"delay": 5, "interval": interval}
                return await update.effective_message.reply_text(t(lang, "panel.auto.prompt_text"))
            if parts[4] == "add" and len(parts) >= 8 and parts[5] == "pin" and parts[6] == "interval":
                interval = int(parts[7])
                context.user_data[("await_auto_pintext", gid)] = {"interval": interval}
                return await update.effective_message.reply_text(t(lang, "panel.auto.pin_prompt_text"))
            if parts[4] == "add" and len(parts) >= 8 and parts[5] in {"unmute", "unban"} and parts[6] == "delay":
                delay = int(parts[7])
                mode = parts[5]
                context.user_data[(f"await_auto_{mode}_uid", gid)] = {"delay": delay}
                return await update.effective_message.reply_text(t(lang, "panel.auto.prompt_uid"))
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
    for (k, gid), payload in list(context.user_data.items()):
        if k == "await_rules" and payload:
            async with db.SessionLocal() as s:  # type: ignore
                await SettingsRepo(s).set_text(gid, "rules", update.effective_message.text or "")
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
                    lang = I18N.pick_lang(update)
                    await update.effective_message.reply_text(t(lang, "rules.add.ok", id=f.id))
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
                return
        if k == "await_welcome" and payload:
            async with db.SessionLocal() as s:  # type: ignore
                cfg = await SettingsRepo(s).get(gid, "welcome") or {}
                cfg["template"] = update.effective_message.text or ""
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
    lang = I18N.pick_lang(update)
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
    lang = I18N.pick_lang(update)
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
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        auto = await SettingsRepo(s).get(gid, "auto_approve_join") or {"enabled": False}
        ob = await SettingsRepo(s).get(gid, "onboarding") or {"require_accept": False}
        cap = await SettingsRepo(s).get(gid, "captcha") or {"enabled": False, "mode": "button", "timeout": 120}
    label = t(lang, "panel.onboarding.title") + "\n" + t(
        lang, "panel.onboarding.auto", state="ON" if auto.get("enabled") else "OFF"
    ) + "\n" + t(lang, "panel.onboarding.require", state="ON" if ob.get("require_accept") else "OFF") + "\n" + t(lang, "panel.onboarding.captcha", state="ON" if cap.get("enabled") else "OFF") + f"\nMode: {cap.get('mode')} | Timeout: {cap.get('timeout')}s"
    kb = [
        [InlineKeyboardButton(t(lang, "panel.toggle"), callback_data=f"panel:group:{gid}:onboarding:toggle")],
        [InlineKeyboardButton(t(lang, "panel.onboarding.toggle_require"), callback_data=f"panel:group:{gid}:onboarding:require")],
        [InlineKeyboardButton(t(lang, "panel.onboarding.captcha_toggle"), callback_data=f"panel:group:{gid}:onboarding:captcha:toggle")],
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
    await update.effective_message.edit_text(label, reply_markup=InlineKeyboardMarkup(kb))


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
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "links") or {"block_all": False, "denylist": [], "action": "delete"}
        night = await SettingsRepo(s).get(gid, "links.night") or {"enabled": False, "from_h": 0, "to_h": 6, "tz_offset_min": 0, "block_all": True}
    deny = list(cfg.get("denylist", []))
    block_all = bool(cfg.get("block_all", False))
    action = cfg.get("action", "delete")
    rows = [
        [InlineKeyboardButton(t(lang, "panel.links.toggle_block_all"), callback_data=f"panel:group:{gid}:links:toggle_block")],
        [
            InlineKeyboardButton(t(lang, "action.delete"), callback_data=f"panel:group:{gid}:links:action:delete"),
            InlineKeyboardButton(t(lang, "action.warn"), callback_data=f"panel:group:{gid}:links:action:warn"),
            InlineKeyboardButton(t(lang, "action.mute"), callback_data=f"panel:group:{gid}:links:action:mute"),
            InlineKeyboardButton(t(lang, "action.ban"), callback_data=f"panel:group:{gid}:links:action:ban"),
        ],
        [InlineKeyboardButton(t(lang, "panel.links.type_actions"), callback_data=f"panel:group:{gid}:links:type:open")],
        [InlineKeyboardButton(t(lang, "panel.links.night"), callback_data=f"panel:group:{gid}:links:night:open")],
        [InlineKeyboardButton(t(lang, "panel.links.add"), callback_data=f"panel:group:{gid}:links:add")],
        [InlineKeyboardButton(t(lang, "panel.links.allow_add"), callback_data=f"panel:group:{gid}:links:allow:add")],
    ]
    # list deny domains with delete buttons
    for d in deny[:6]:
        rows.append([InlineKeyboardButton(d, callback_data="panel:noop"), InlineKeyboardButton("✖", callback_data=f"panel:group:{gid}:links:del:{d}")])
    # list allow domains with delete buttons
    allow = list(cfg.get("allowlist", []))
    if allow:
        rows.append([InlineKeyboardButton(t(lang, "panel.links.allowlist"), callback_data="panel:noop")])
        for a in allow[:6]:
            rows.append([InlineKeyboardButton(a, callback_data="panel:noop"), InlineKeyboardButton("✖", callback_data=f"panel:group:{gid}:links:allow:del:{a}")])
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")])
    action_label = t(lang, f"action.{action}") if action else ""
    text = t(lang, "panel.links.title") + f"\nBlock all: {'ON' if block_all else 'OFF'}\nDefault: {action_label}"
    await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def show_links_type_actions(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "links") or {"types": {}}
    types = cfg.get("types", {})
    cats = [
        ("invites", t(lang, "panel.links.cat.invites")),
        ("telegram", t(lang, "panel.links.cat.telegram")),
        ("shorteners", t(lang, "panel.links.cat.shorteners")),
        ("other", t(lang, "panel.links.cat.other")),
    ]
    rows = []
    for key, label in cats:
        rows.append([InlineKeyboardButton(label, callback_data="panel:noop")])
        rows.append(
            [
                InlineKeyboardButton(t(lang, "action.allow"), callback_data=f"panel:group:{gid}:links:type:{key}:allow"),
                InlineKeyboardButton(t(lang, "action.delete"), callback_data=f"panel:group:{gid}:links:type:{key}:delete"),
                InlineKeyboardButton(t(lang, "action.warn"), callback_data=f"panel:group:{gid}:links:type:{key}:warn"),
                InlineKeyboardButton(t(lang, "action.mute"), callback_data=f"panel:group:{gid}:links:type:{key}:mute"),
                InlineKeyboardButton(t(lang, "action.ban"), callback_data=f"panel:group:{gid}:links:type:{key}:ban"),
            ]
        )
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:links:open")])
    await update.effective_message.edit_text(t(lang, "panel.links.type_actions"), reply_markup=InlineKeyboardMarkup(rows))


async def show_links_night(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
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
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        locks = await SettingsRepo(s).get(gid, "locks") or {}
    forwards = locks.get("forwards", "allow")
    media = locks.get("media", {})
    media_types = ["photo", "video", "document", "sticker", "voice", "audio", "animation"]
    rows = [
        [InlineKeyboardButton(t(lang, "panel.locks.forwards"), callback_data="panel:noop")],
        [
            InlineKeyboardButton(t(lang, "action.allow"), callback_data=f"panel:group:{gid}:locks:forwards:allow"),
            InlineKeyboardButton(t(lang, "action.delete"), callback_data=f"panel:group:{gid}:locks:forwards:delete"),
            InlineKeyboardButton(t(lang, "action.warn"), callback_data=f"panel:group:{gid}:locks:forwards:warn"),
            InlineKeyboardButton(t(lang, "action.mute"), callback_data=f"panel:group:{gid}:locks:forwards:mute"),
            InlineKeyboardButton(t(lang, "action.ban"), callback_data=f"panel:group:{gid}:locks:forwards:ban"),
        ],
        [InlineKeyboardButton(t(lang, "panel.locks.media"), callback_data="panel:noop")],
    ]
    for mt in media_types:
        rows.append([InlineKeyboardButton(mt, callback_data="panel:noop")])
        rows.append([
            InlineKeyboardButton(t(lang, "action.allow"), callback_data=f"panel:group:{gid}:locks:media:{mt}:allow"),
            InlineKeyboardButton(t(lang, "action.delete"), callback_data=f"panel:group:{gid}:locks:media:{mt}:delete"),
            InlineKeyboardButton(t(lang, "action.warn"), callback_data=f"panel:group:{gid}:locks:media:{mt}:warn"),
            InlineKeyboardButton(t(lang, "action.mute"), callback_data=f"panel:group:{gid}:locks:media:{mt}:mute"),
            InlineKeyboardButton(t(lang, "action.ban"), callback_data=f"panel:group:{gid}:locks:media:{mt}:ban"),
        ])
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:rules")])
    await update.effective_message.edit_text(t(lang, "panel.locks.title"), reply_markup=InlineKeyboardMarkup(rows))


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
        except Exception:
            pass
        await update.effective_message.reply_text(t(lang, "mod.muted"))
        return
    if act == "ban":
        until = int(time.time()) + int(cfg["ban_seconds"])
        try:
            await context.bot.ban_chat_member(gid, uid, until_date=until)
        except Exception:
            pass
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


async def show_automations(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        from ...infra.repos import JobsRepo

        jobs = await JobsRepo(s).list_by_group(gid, limit=50)
    rows = [
        [InlineKeyboardButton(t(lang, "panel.auto.add_announce"), callback_data=f"panel:group:{gid}:auto:add")],
        [InlineKeyboardButton(t(lang, "panel.auto.add_pin"), callback_data=f"panel:group:{gid}:auto:add:pin")],
        [
            InlineKeyboardButton(t(lang, "panel.auto.add_unmute"), callback_data=f"panel:group:{gid}:auto:add:unmute"),
            InlineKeyboardButton(t(lang, "panel.auto.add_unban"), callback_data=f"panel:group:{gid}:auto:add:unban"),
        ],
    ]
    for j in jobs[:10]:
        label = f"#{j.id} {j.kind} next: {j.run_at.isoformat()}"
        rows.append(
            [
                InlineKeyboardButton(label, callback_data="panel:noop"),
                InlineKeyboardButton("✖", callback_data=f"panel:group:{gid}:auto:cancel:{j.id}"),
            ]
        )
    rows.append([InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home")])
    await update.effective_message.edit_text(t(lang, "panel.auto.title"), reply_markup=InlineKeyboardMarkup(rows))


async def show_audit(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int, page: int) -> None:
    lang = I18N.pick_lang(update)
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


async def show_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE, gid: int) -> None:
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(gid, "auto_approve_join") or {"enabled": False}
    enabled = bool(cfg.get("enabled"))
    label = t(lang, "panel.onboarding.title") + "\n" + t(
        lang, "panel.onboarding.auto", state="ON" if enabled else "OFF"
    )
    kb = [
        [
            InlineKeyboardButton(t(lang, "panel.toggle"), callback_data=f"panel:group:{gid}:onboarding:toggle"),
            InlineKeyboardButton(t(lang, "panel.back"), callback_data=f"panel:group:{gid}:tab:home"),
        ]
    ]
    await update.effective_message.edit_text(label, reply_markup=InlineKeyboardMarkup(kb))


def register_callbacks(app):
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^panel:"))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, on_rules_input))
