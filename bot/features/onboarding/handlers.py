from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ...infra import db
from ...infra.settings_repo import SettingsRepo
from ...core.permissions import require_admin
from ...core.i18n import I18N, t


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.chat_join_request:
        return
    req = update.chat_join_request
    gid = req.chat.id
    # If onboarding requires accept, send DM with rules and await response
    approve = False
    require_accept = False
    rules_text = None
    async with db.SessionLocal() as s:  # type: ignore
        auto = await SettingsRepo(s).get(gid, "auto_approve_join") or {"enabled": False}
        ob = await SettingsRepo(s).get(gid, "onboarding") or {"require_accept": False}
        approve = bool(auto.get("enabled"))
        require_accept = bool(ob.get("require_accept"))
        rules_text = await SettingsRepo(s).get_text(gid, "rules")

    if require_accept:
        # Attempt DM
        lang_code = (req.from_user.language_code or "en").split("-")[0]
        text = t(lang_code, "join.dm.text", group_title=req.chat.title or "", rules=rules_text or t(lang_code, "rules.default"))
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(t(lang_code, "join.accept"), callback_data=f"join:accept:{gid}:{req.from_user.id}"),
                    InlineKeyboardButton(t(lang_code, "join.decline"), callback_data=f"join:decline:{gid}:{req.from_user.id}"),
                ]
            ]
        )
        try:
            await context.bot.send_message(req.from_user.id, text, reply_markup=kb)
        except Exception:
            # Can't DM; leave pending until the user starts the bot
            return
        # Leave pending for explicit acceptance
        return

    if approve:
        # Send rules to the user first (without requiring acceptance), then approve
        lang_code = (req.from_user.language_code or "en").split("-")[0]
        try:
            text = t(
                lang_code,
                "join.dm.rules",
                group_title=req.chat.title or "",
                rules=rules_text or t(lang_code, "rules.default"),
            )
            await context.bot.send_message(req.from_user.id, text)
        except Exception:
            # If we can't DM (user hasn't started bot), continue to approve
            pass
        try:
            await context.bot.approve_chat_join_request(gid, req.from_user.id)
        except Exception:
            pass


@require_admin
async def toggle_auto_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    msg = update.effective_message
    if not msg:
        return
    if not context.args or context.args[0].lower() not in {"on", "off"}:
        return await msg.reply_text(t(lang, "join.usage"))
    enabled = context.args[0].lower() == "on"
    async with db.SessionLocal() as s:  # type: ignore
        await SettingsRepo(s).set(msg.chat_id, "auto_approve_join", {"enabled": enabled})
        await s.commit()
    await msg.reply_text(t(lang, "join.set", state="ON" if enabled else "OFF"))


async def on_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    data = (update.callback_query.data or "").split(":")
    if len(data) != 4:
        return
    action, gid_s, uid_s = data[1], data[2], data[3]
    gid = int(gid_s)
    uid = int(uid_s)
    if not update.effective_user or update.effective_user.id != uid:
        return
    if action == "accept":
        try:
            await context.bot.approve_chat_join_request(gid, uid)
        except Exception:
            pass
        # Optionally confirm to user
        lang = I18N.pick_lang(update)
        await update.effective_message.reply_text("✅")
    elif action == "decline":
        try:
            await context.bot.decline_chat_join_request(gid, uid)
        except Exception:
            pass
        await update.effective_message.reply_text("❌")
