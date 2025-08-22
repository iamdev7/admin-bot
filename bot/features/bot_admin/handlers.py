from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
import logging

from .navigation import Navigator

from ...core.permissions import is_owner
from ...core.config import settings
from ...core.i18n import I18N, t
from ...infra import db
from ...infra.repos import GroupsRepo, UsersRepo
from ...infra.settings_repo import SettingsRepo

log = logging.getLogger(__name__)


def _ensure_owner(update: Update) -> bool:
    return bool(update.effective_user and is_owner(update.effective_user.id))


async def open_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_owner(update):
        return
    if not update.effective_chat:
        return
    lang = I18N.pick_lang(update)
    # If sent in a group, nudge owner to DM
    if update.effective_chat.type != "private":
        try:
            await update.effective_message.reply_text(t(lang, "botadm.open_dm"))
        except Exception as e:
            log.error(f"Failed to send nudge to open DM: {e}")
        return
    # Use navigator for consistent UI
    await Navigator.go_home(update, context)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_owner(update):
        return
    if not update.callback_query:
        return
    await update.callback_query.answer()
    data = (update.callback_query.data or "").split(":")
    if len(data) < 2:
        return
    lang = I18N.pick_lang(update)
    
    # Handle navigation callbacks
    if data[1] == "nav":
        if len(data) >= 3:
            if data[2] == "home":
                return await Navigator.go_home(update, context)
            elif data[2] == "broadcast_menu":
                return await Navigator.go_broadcast_menu(update, context)
            elif data[2] == "stats":
                return await Navigator.go_stats(update, context)
            elif data[2] == "blacklist":
                return await Navigator.go_blacklist(update, context)
            elif data[2] == "violators":
                return await Navigator.go_violators(update, context)
    
    # Legacy menu handling (for backwards compatibility)
    if data[1] == "menu":
        if len(data) >= 3 and data[2] == "broadcast":
            return await Navigator.go_broadcast_menu(update, context)
        if len(data) >= 3 and data[2] == "stats":
            return await Navigator.go_stats(update, context)
        if len(data) >= 3 and data[2] == "blacklist":
            return await Navigator.go_blacklist(update, context)
        if len(data) >= 3 and data[2] == "root":
            return await Navigator.go_home(update, context)
    # Handle broadcast callbacks with new prefix
    if data[1] == "bc":
        if len(data) >= 3 and data[2] == "target":
            if len(data) >= 4 and data[3] == "groups":
                context.user_data["botadm_broadcast"] = {"target": "groups"}
                targets = await _targets_from_selection(context)
                n = len(targets)
                kb = [
                    [InlineKeyboardButton(t(lang, "botadm.proceed"), callback_data="botadm:bc:confirm")],
                    [InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:broadcast_menu")]
                ]
                return await Navigator.edit_or_send(update, t(lang, "botadm.bc.confirm", n=n), kb)
            elif len(data) >= 4 and data[3] == "users":
                context.user_data["botadm_broadcast"] = {"target": "users"}
                targets = await _targets_from_selection(context)
                n = len(targets)
                kb = [
                    [InlineKeyboardButton(t(lang, "botadm.proceed"), callback_data="botadm:bc:confirm")],
                    [InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:broadcast_menu")]
                ]
                return await Navigator.edit_or_send(update, t(lang, "botadm.bc.confirm", n=n), kb)
            elif len(data) >= 4 and data[3] == "chatid":
                context.user_data["botadm_wait_chatid"] = True
                kb = [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:broadcast_menu")]]
                return await Navigator.edit_or_send(update, t(lang, "botadm.prompt_chat_id"), kb)
        elif len(data) >= 3 and data[2] == "confirm":
            return await prompt_broadcast(update, context)
    
    # Handle blacklist callbacks with new prefix
    if data[1] == "bl":
        if len(data) >= 3 and data[2] == "add":
            context.user_data["botadm_wait_word"] = True
            kb = [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:blacklist")]]
            return await Navigator.edit_or_send(update, t(lang, "botadm.bl.prompt_add"), kb, parse_mode="Markdown")
        elif len(data) >= 3 and data[2] == "export":
            async with db.SessionLocal() as s:  # type: ignore
                cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
            import json
            txt = t(lang, "botadm.bl.export_note") + "\n\n" + json.dumps(cfg, ensure_ascii=False, indent=2)
            kb = [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:blacklist")]]
            return await Navigator.edit_or_send(update, txt, kb)
        elif len(data) >= 3 and data[2] == "import":
            context.user_data["botadm_wait_import"] = True
            kb = [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:blacklist")]]
            return await Navigator.edit_or_send(update, t(lang, "botadm.bl.prompt_import"), kb)
        elif len(data) >= 3 and data[2] == "action" and len(data) >= 4:
            action = data[3]
            if action in {"warn", "mute", "ban"}:
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
                    cfg["action"] = action
                    await SettingsRepo(s).set(0, "global_blacklist", cfg)
                    await s.commit()
            return await Navigator.go_blacklist(update, context)
        elif len(data) >= 3 and data[2] == "del" and len(data) >= 4:
            word = data[3]
            async with db.SessionLocal() as s:  # type: ignore
                cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
                words = [w for w in cfg.get("words", []) if w != word]
                cfg["words"] = words
                await SettingsRepo(s).set(0, "global_blacklist", cfg)
                await s.commit()
            return await Navigator.go_blacklist(update, context)
    
    # Handle violators callbacks
    if data[1] == "violators":
        if len(data) >= 3 and data[2] == "clear_all":
            async with db.SessionLocal() as s:  # type: ignore
                from ...infra.global_violators_repo import GlobalViolatorsRepo
                from sqlalchemy import delete
                from ...infra.models import GlobalViolator
                
                # Clear all violators
                result = await s.execute(delete(GlobalViolator))
                count = result.rowcount
                await s.commit()
            
            # Show confirmation and return to violators list
            lang = I18N.pick_lang(update)
            await update.callback_query.answer(t(lang, "botadm.violators.cleared", count=count), show_alert=True)
            return await Navigator.go_violators(update, context)
    
    # Legacy broadcast handling (keep for compatibility)
    if data[1] == "broadcast":
        if len(data) >= 3 and data[2] == "groups":
            context.user_data["botadm_broadcast"] = {"target": "groups"}
            targets = await _targets_from_selection(context)
            n = len(targets)
            kb = [[InlineKeyboardButton(t(lang, "botadm.proceed"), callback_data="botadm:broadcast:confirm")], [InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:menu:broadcast")]]
            return await _safe_edit(update, context, t(lang, "botadm.bc.confirm", n=n), kb)
        if len(data) >= 3 and data[2] == "users":
            context.user_data["botadm_broadcast"] = {"target": "users"}
            targets = await _targets_from_selection(context)
            n = len(targets)
            kb = [[InlineKeyboardButton(t(lang, "botadm.proceed"), callback_data="botadm:broadcast:confirm")], [InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:menu:broadcast")]]
            return await _safe_edit(update, context, t(lang, "botadm.bc.confirm", n=n), kb)
        if len(data) >= 3 and data[2] == "chatid":
            context.user_data["botadm_wait_chatid"] = True
            return await _safe_edit(update, context, t(lang, "botadm.prompt_chat_id"), [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:menu:broadcast")]])
        if len(data) >= 3 and data[2] == "back":
            return await broadcast_menu(update, context)
        if len(data) >= 3 and data[2] == "confirm":
            return await prompt_broadcast(update, context)
    if data[1] == "blacklist":
        if len(data) >= 3 and data[2] == "add":
            context.user_data["botadm_wait_word"] = True
            return await _safe_edit(update, context, t(lang, "botadm.bl.prompt_add"), [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:menu:blacklist")]])
        if len(data) >= 3 and data[2] == "action":
            # Set global action
            action = data[3] if len(data) >= 4 else None
            if action in {"warn", "mute", "ban"}:
                async with db.SessionLocal() as s:  # type: ignore
                    cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
                    cfg["action"] = action
                    await SettingsRepo(s).set(0, "global_blacklist", cfg)
                    await s.commit()
            return await show_blacklist(update, context)
        if len(data) >= 3 and data[2] == "export":
            # Dump JSON
            async with db.SessionLocal() as s:  # type: ignore
                cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
            import json
            txt = t(lang, "botadm.bl.export_note") + "\n\n" + json.dumps(cfg, ensure_ascii=False, indent=2)
            return await _safe_edit(update, context, txt, [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:menu:blacklist")]])
        if len(data) >= 3 and data[2] == "import":
            context.user_data["botadm_wait_import"] = True
            return await _safe_edit(update, context, t(lang, "botadm.bl.prompt_import"), [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:menu:blacklist")]])
        if len(data) >= 3 and data[2] == "del" and len(data) >= 4:
            word = data[3]
            async with db.SessionLocal() as s:  # type: ignore
                cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
                words = [w for w in cfg.get("words", []) if w != word]
                cfg["words"] = words
                await SettingsRepo(s).set(0, "global_blacklist", cfg)
                await s.commit()
            return await show_blacklist(update, context)


async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    kb = [
        [InlineKeyboardButton(t(lang, "botadm.to_groups"), callback_data="botadm:broadcast:groups")],
        [InlineKeyboardButton(t(lang, "botadm.to_users"), callback_data="botadm:broadcast:users")],
        [InlineKeyboardButton(t(lang, "botadm.to_chatid"), callback_data="botadm:broadcast:chatid")],
        [InlineKeyboardButton(t(lang, "botadm.back_home"), callback_data="botadm:menu:root")],
    ]
    await _safe_edit(update, context, t(lang, "botadm.bc.title"), kb)


async def prompt_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    # Remember current message to edit later
    kb = [[InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:broadcast_menu")]]
    
    # Store message info for later editing
    if update.callback_query and update.callback_query.message:
        context.user_data["botadm_prompt_msg_id"] = update.callback_query.message.message_id
        context.user_data["botadm_prompt_chat_id"] = update.callback_query.message.chat_id
    
    await Navigator.edit_or_send(update, t(lang, "botadm.bc.prompt"), kb)
    context.user_data["botadm_wait_content"] = True
    try:
        targets = await _targets_from_selection(context)
        if targets:
            owner_id = update.effective_user.id if update.effective_user else 0
            context.bot_data[f"botadm_last_sel:{owner_id}"] = {"targets": targets}
            # Also store prompt message info for album broadcasts
            if msg:
                context.bot_data[f"botadm_prompt:{owner_id}"] = {
                    "msg_id": msg.message_id,
                    "chat_id": msg.chat_id
                }
    except Exception as e:
        log.error("Failed to snapshot targets for broadcast: %s", e)


async def _send_copy_to_targets(context: ContextTypes.DEFAULT_TYPE, targets: list[int], src_chat: int, src_mid: int, progress_msg=None) -> tuple[int, int]:
    """Send a message to multiple targets with progress updates.
    Returns (sent_count, failed_count)"""
    import asyncio
    sent = 0
    failed = 0
    total = len(targets)
    
    for i, tid in enumerate(targets):
        try:
            await context.bot.copy_message(chat_id=tid, from_chat_id=src_chat, message_id=src_mid)  # type: ignore[arg-type]
            sent += 1
            log.debug(f"Broadcast sent to {tid} ({sent}/{total})")
            
            # Update progress every 10 messages or at the end
            if progress_msg and (sent % 10 == 0 or sent + failed == total):
                try:
                    lang = I18N.pick_lang(progress_msg)
                    progress_text = t(lang, "botadm.bc.progress", sent=sent, failed=failed, total=total)
                    await context.bot.edit_message_text(
                        chat_id=progress_msg.chat.id,
                        message_id=progress_msg.message_id,
                        text=progress_text
                    )
                except Exception as e:
                    log.debug("Failed to update progress message: %s", e)  # Debug level since progress updates are non-critical
                    
        except Exception as e:
            failed += 1
            log.warning(f"Broadcast failed for chat {tid}: {e}")
            
        # Small delay to avoid rate limits
        if i < len(targets) - 1:
            await asyncio.sleep(0.05)
            
    return sent, failed


async def _send_album_to_targets(context: ContextTypes.DEFAULT_TYPE, targets: list[int], album: list[dict], progress_msg=None) -> tuple[int, int]:
    """Send media album to multiple targets.
    Returns (sent_count, failed_count)"""
    import asyncio
    from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio
    
    sent = 0
    failed = 0
    total = len(targets)

    def build(media: list[dict]):
        items = []
        for i, it in enumerate(media):
            t = it.get("type")
            fid = it.get("file_id")
            cap = it.get("caption") if i == 0 else None
            if t == "photo":
                items.append(InputMediaPhoto(media=fid, caption=cap))
            elif t == "video":
                items.append(InputMediaVideo(media=fid, caption=cap))
            elif t == "document":
                items.append(InputMediaDocument(media=fid, caption=cap))
            elif t == "audio":
                items.append(InputMediaAudio(media=fid, caption=cap))
        return items

    media = build(album)
    
    for i, tid in enumerate(targets):
        try:
            await context.bot.send_media_group(tid, media=media)
            sent += 1
            log.debug(f"Album broadcast sent to {tid} ({sent}/{total})")
            
            # Update progress
            if progress_msg and (sent % 10 == 0 or sent + failed == total):
                try:
                    lang = I18N.pick_lang(progress_msg)
                    progress_text = t(lang, "botadm.bc.progress", sent=sent, failed=failed, total=total)
                    await context.bot.edit_message_text(
                        chat_id=progress_msg.chat.id,
                        message_id=progress_msg.message_id,
                        text=progress_text
                    )
                except Exception as e:
                    log.debug("Failed to update album progress message: %s", e)
                    
        except Exception as e:
            failed += 1
            log.warning(f"Album broadcast failed for chat {tid}: {e}")
            
        # Small delay to avoid rate limits
        if i < len(targets) - 1:
            await asyncio.sleep(0.05)
            
    return sent, failed


async def _targets_from_selection(context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    sel = context.user_data.get("botadm_broadcast") or {}
    target = sel.get("target")
    targets: list[int] = []
    
    log.info(f"Getting broadcast targets for: {target}")
    
    if target == "groups":
        async with db.SessionLocal() as s:  # type: ignore
            from sqlalchemy import select
            from ...infra.models import Group

            groups = (await s.execute(select(Group))).scalars().all()
            targets = [g.id for g in groups]
            log.info(f"Found {len(targets)} groups to broadcast to: {targets[:5]}...")  # Show first 5 IDs
    elif target == "users":
        async with db.SessionLocal() as s:  # type: ignore
            from sqlalchemy import select
            from ...infra.models import User

            users = (await s.execute(select(User))).scalars().all()
            targets = [u.id for u in users]
            log.info(f"Found {len(targets)} users to broadcast to")
    elif target == "chat":
        cid = sel.get("chat_id")
        if isinstance(cid, int):
            targets = [cid]
    return targets


async def on_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Only process if owner AND we're waiting for bot admin input
    if not _ensure_owner(update):
        return
    
    # Check if we're actually waiting for bot admin input
    waiting_for_botadm = any([
        context.user_data.get("botadm_wait_chatid"),
        context.user_data.get("botadm_wait_content"),
        context.user_data.get("botadm_wait_word"),
        context.user_data.get("botadm_wait_import")
    ])
    
    if not waiting_for_botadm:
        # Not waiting for bot admin input, let other handlers process
        return
    
    log.info(f"on_input: Processing bot admin input, user_data keys: {list(context.user_data.keys())}")
    
    # Chat ID entry
    if context.user_data.get("botadm_wait_chatid"):
        context.user_data["botadm_wait_chatid"] = False
        lang = I18N.pick_lang(update)
        txt = (update.effective_message.text or "").strip()
        try:
            cid = int(txt)
        except Exception:
            await update.effective_message.reply_text(t(lang, "botadm.invalid_chat_id"))
            # Delete user's message
            try:
                await update.effective_message.delete()
            except Exception:
                pass
            return
        
        # Delete user's message to keep chat clean
        try:
            await update.effective_message.delete()
        except Exception:
            pass
        
        context.user_data["botadm_broadcast"] = {"target": "chat", "chat_id": cid}
        
        # Create a fake callback update to properly edit the message
        class FakeCallbackQuery:
            def __init__(self, message):
                self.message = message
                self.data = "botadm:bc:confirm"
        
        # Get the stored prompt message
        prompt_msg_id = context.user_data.get("botadm_prompt_msg_id")
        prompt_chat_id = context.user_data.get("botadm_prompt_chat_id")
        
        if prompt_msg_id and prompt_chat_id:
            # Edit the existing message to show confirmation
            n = 1  # Single chat target
            kb = [
                [InlineKeyboardButton(t(lang, "botadm.proceed"), callback_data="botadm:bc:confirm")],
                [InlineKeyboardButton(t(lang, "botadm.back"), callback_data="botadm:nav:broadcast_menu")]
            ]
            try:
                await context.bot.edit_message_text(
                    chat_id=prompt_chat_id,
                    message_id=prompt_msg_id,
                    text=t(lang, "botadm.bc.confirm", n=n),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            except Exception as e:
                log.debug(f"Failed to edit message after chat ID input: {e}")
        else:
            # Fallback: send new message
            return await prompt_broadcast(update, context)

    # Broadcast content capture (supports copy of any message or media albums)
    if context.user_data.get("botadm_wait_content"):
        log.info("on_input: Processing broadcast content")
        lang = I18N.pick_lang(update)
        m = update.effective_message
        mgid = getattr(m, "media_group_id", None)
        if mgid:
            # Accumulate album pieces briefly and finalize
            key = f"botadm_album:{update.effective_user.id}:{mgid}"
            items = context.bot_data.get(key)
            if not isinstance(items, list):
                items = []
                context.bot_data[key] = items
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
                items.append(item)
            jobname = f"botadm_album:{update.effective_user.id}:{mgid}"
            if not context.job_queue.get_jobs_by_name(jobname):
                context.job_queue.run_once(_finalize_broadcast_album, when=1.2, name=jobname, data={"key": key})
            return
        # Single message: copy to selected targets
        sel = context.user_data.get("botadm_broadcast") or {}
        targets = await _targets_from_selection(context)
        if not targets:
            return await update.effective_message.reply_text(t(I18N.pick_lang(update), "botadm.no_targets"))
        
        # Send progress message
        progress_msg = await update.effective_message.reply_text(
            t(lang, "botadm.bc.starting", total=len(targets))
        )
        
        # Send broadcast with progress updates
        sent, failed = await _send_copy_to_targets(
            context, targets, 
            update.effective_chat.id, 
            update.effective_message.message_id,
            progress_msg=progress_msg
        )
        
        context.user_data["botadm_wait_content"] = False
        
        # Edit the original prompt message back to broadcast menu
        prompt_msg_id = context.user_data.pop("botadm_prompt_msg_id", None)
        prompt_chat_id = context.user_data.pop("botadm_prompt_chat_id", None)
        
        if prompt_msg_id and prompt_chat_id:
            try:
                kb = Navigator.get_broadcast_keyboard(lang)
                await context.bot.edit_message_text(
                    chat_id=prompt_chat_id,
                    message_id=prompt_msg_id,
                    text=t(lang, "botadm.bc.title"),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            except Exception as e:
                log.debug(f"Failed to edit prompt message back to menu: {e}")
        
        # Show final status in progress message
        if failed > 0:
            final_text = t(lang, "botadm.bc.sent_with_errors", sent=sent, failed=failed, total=len(targets))
        else:
            final_text = t(lang, "botadm.bc.sent", n=sent)
        
        try:
            await progress_msg.edit_text(final_text)
        except Exception:
            await update.effective_message.reply_text(final_text)

    # Global blacklist: add words (supports multiple lines)
    if context.user_data.get("botadm_wait_word"):
        context.user_data["botadm_wait_word"] = False
        text = (update.effective_message.text or "").strip()
        lang = I18N.pick_lang(update)
        
        if not text:
            await update.effective_message.reply_text(t(lang, "botadm.bl.invalid"))
            # Return to blacklist menu
            return await Navigator.go_blacklist(update, context)
        
        # Split by lines and process each line as a separate word/phrase
        new_words = []
        for line in text.split('\n'):
            line = line.strip().lower()
            if line:  # Skip empty lines
                new_words.append(line)
        
        if not new_words:
            await update.effective_message.reply_text(t(lang, "botadm.bl.invalid"))
            return await Navigator.go_blacklist(update, context)
        
        # Add all new words to blacklist
        async with db.SessionLocal() as s:  # type: ignore
            cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
            words = set(cfg.get("words", []))
            words.update(new_words)  # Add all new words at once
            cfg["words"] = list(sorted(words))
            await SettingsRepo(s).set(0, "global_blacklist", cfg)
            await s.commit()
        
        # Send confirmation message with count
        added_count = len(new_words)
        if added_count == 1:
            confirmation = t(lang, "botadm.bl.added_single")
        else:
            confirmation = t(lang, "botadm.bl.added_multiple", count=added_count)
        
        await update.effective_message.reply_text(confirmation)
        
        # Delete user's message to keep chat clean
        try:
            await update.effective_message.delete()
        except Exception:
            pass
        
        # Update blacklist display
        return await Navigator.go_blacklist(update, context)
    # Global blacklist: import JSON
    if context.user_data.get("botadm_wait_import"):
        context.user_data["botadm_wait_import"] = False
        import json
        lang = I18N.pick_lang(update)
        raw = update.effective_message.text or ""
        success = False
        try:
            cfg = json.loads(raw)
            if not isinstance(cfg, dict):
                raise ValueError("cfg")
            words = cfg.get("words") or []
            action = (cfg.get("action") or "warn").lower()
            if not isinstance(words, list) or action not in {"warn", "mute", "ban"}:
                raise ValueError("shape")
            words = [str(w).strip().lower() for w in words if str(w).strip()]
            async with db.SessionLocal() as s:  # type: ignore
                await SettingsRepo(s).set(0, "global_blacklist", {"words": list(sorted(set(words))), "action": action})
                await s.commit()
            await update.effective_message.reply_text(t(lang, "botadm.bl.import_ok"))
            success = True
        except Exception:
            await update.effective_message.reply_text(t(lang, "common.invalid_json"))
        
        # Delete user's message to keep chat clean
        try:
            await update.effective_message.delete()
        except Exception:
            pass
        
        # Return to blacklist if successful
        if success:
            return await Navigator.go_blacklist(update, context)
        return


async def _finalize_broadcast_album(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    key = data.get("key")
    items = context.bot_data.get(key) or []
    # Find targets from user_data is not available here; broadcast to last selection in bot_data
    # As we are in a job context, we can’t access the owner’s user_data; instead, store last selection globally
    # Fallback: no-op if not available
    try:
        # Infer owner id from key
        owner_id = int(str(key).split(":")[1]) if key else None
    except Exception:
        owner_id = None
    # Look up a stored selection snapshot
    sel = context.bot_data.get(f"botadm_last_sel:{owner_id}") if owner_id is not None else None
    # If not found, try to build from nothing (no-op)
    # Better: capture a copy of selection on prompt
    if not sel:
        return
    # Build targets
    targets = sel.get("targets") or []
    if not targets:
        return
    
    # Try to notify owner about broadcast completion
    sent, failed = await _send_album_to_targets(context, targets, items)
    
    # Try to send status message and edit prompt message back to menu
    try:
        owner_id = int(str(key).split(":")[1]) if key else None
        if owner_id and sent + failed > 0:
            # Get stored prompt message info
            prompt_data = context.bot_data.get(f"botadm_prompt:{owner_id}", {})
            prompt_msg_id = prompt_data.get("msg_id")
            prompt_chat_id = prompt_data.get("chat_id")
            
            # Get language for the owner (default to en)
            from telegram import Message
            # Create a minimal update-like object for language detection
            class FakeUpdate:
                def __init__(self, user_id):
                    self.effective_user = type('obj', (object,), {'id': user_id})()
            
            fake_update = FakeUpdate(owner_id)
            lang = I18N.pick_lang(fake_update, fallback="en")
            
            # Edit prompt message back to broadcast menu
            if prompt_msg_id and prompt_chat_id:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                kb = [
                    [InlineKeyboardButton(t(lang, "botadm.to_groups"), callback_data="botadm:broadcast:groups")],
                    [InlineKeyboardButton(t(lang, "botadm.to_users"), callback_data="botadm:broadcast:users")],
                    [InlineKeyboardButton(t(lang, "botadm.to_chatid"), callback_data="botadm:broadcast:chatid")],
                    [InlineKeyboardButton(t(lang, "botadm.back_home"), callback_data="botadm:menu:root")],
                ]
                try:
                    await context.bot.edit_message_text(
                        chat_id=prompt_chat_id,
                        message_id=prompt_msg_id,
                        text=t(lang, "botadm.bc.title"),
                        reply_markup=InlineKeyboardMarkup(kb)
                    )
                except Exception as e:
                    log.debug(f"Failed to edit prompt message for album: {e}")
                
                # Clean up stored prompt data
                context.bot_data.pop(f"botadm_prompt:{owner_id}", None)
            
            # Send completion status using translations
            if failed > 0:
                status_text = t(lang, "botadm.bc.sent_with_errors", sent=sent, failed=failed, total=sent + failed)
            else:
                status_text = t(lang, "botadm.bc.sent", n=sent)
            
            await context.bot.send_message(owner_id, status_text)
    except Exception as e:
        log.debug(f"Could not send album broadcast status: {e}")
    
    try:
        context.bot_data.pop(key, None)
    except Exception as e:
        log.debug("Failed to clean up album data: %s", e)


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        from sqlalchemy import select, func
        from ...infra.models import Group, User, Job, AuditLog
        from datetime import datetime, timedelta

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
        
    # Enhanced stats text
    text = (
        f"📊 **Bot Statistics**\n\n"
        f"👥 **Users:** {users} total\n"
        f"  • Active (24h): {active_24h}\n"
        f"  • Active (7d): {active_7d}\n\n"
        f"💬 **Groups:** {groups}\n"
        f"🤖 **Automations:** {autos}\n"
        f"⚠️ **Violations:** {violations}"
    )
    
    kb = [[InlineKeyboardButton(t(lang, "botadm.back_home"), callback_data="botadm:menu:root")]]
    await _safe_edit(update, context, text, kb, parse_mode="Markdown")


async def show_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = I18N.pick_lang(update)
    async with db.SessionLocal() as s:  # type: ignore
        cfg = await SettingsRepo(s).get(0, "global_blacklist") or {"words": [], "action": "warn"}
    words = list(cfg.get("words", []))
    action = cfg.get("action", "warn")
    rows: list[list[InlineKeyboardButton]] = []
    for w in words[:25]:
        rows.append([InlineKeyboardButton(w, callback_data="botadm:noop"), InlineKeyboardButton("✖", callback_data=f"botadm:blacklist:del:{w}")])
    rows.append([
        InlineKeyboardButton(t(lang, "botadm.bl.add"), callback_data="botadm:blacklist:add"),
        InlineKeyboardButton(t(lang, "botadm.bl.export"), callback_data="botadm:blacklist:export"),
        InlineKeyboardButton(t(lang, "botadm.bl.import"), callback_data="botadm:blacklist:import"),
    ])
    rows.append([
        InlineKeyboardButton(t(lang, "action.warn"), callback_data="botadm:blacklist:action:warn"),
        InlineKeyboardButton(t(lang, "action.mute"), callback_data="botadm:blacklist:action:mute"),
        InlineKeyboardButton(t(lang, "action.ban"), callback_data="botadm:blacklist:action:ban"),
    ])
    rows.append([InlineKeyboardButton(t(lang, "botadm.back_home"), callback_data="botadm:menu:root")])
    await _safe_edit(update, context, t(lang, "botadm.bl.title", action=action), rows)


async def _safe_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, kb_rows: list[list[InlineKeyboardButton]], parse_mode: str = None) -> None:
    try:
        await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=parse_mode)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        # If cannot edit (first time or old), just reply
        try:
            await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=parse_mode)
        except Exception as e:
            log.debug("Failed to reply with text after edit failed: %s", e)


async def _safe_edit_return_msg(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, kb_rows: list[list[InlineKeyboardButton]]):
    """Like _safe_edit but returns the message object."""
    try:
        return await update.effective_message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return update.effective_message
        # If cannot edit (first time or old), just reply
        try:
            return await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
        except Exception as e:
            log.debug("Failed to reply with text after edit failed: %s", e)
            return None
