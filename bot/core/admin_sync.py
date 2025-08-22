from __future__ import annotations

from telegram import ChatMemberUpdated, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import Application, ChatMemberHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
import logging

from .i18n import I18N
from ..infra import db
from ..infra.repos import GroupsRepo, GroupAdminsRepo
log = logging.getLogger(__name__)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.chat_member or not update.effective_chat:
        return
    cm: ChatMemberUpdated = update.chat_member
    user = cm.new_chat_member.user
    status = cm.new_chat_member.status

    async with db.SessionLocal() as s:  # type: ignore
        await GroupsRepo(s).upsert_group(
            gid=update.effective_chat.id,
            title=update.effective_chat.title or str(update.effective_chat.id),
            username=update.effective_chat.username,
            gtype=update.effective_chat.type,
        )
        admins = GroupAdminsRepo(s)
        # Track admin promotions/demotions/leaves
        if status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await admins.upsert_admin(update.effective_chat.id, user.id, status.value, rights={})
        else:
            await admins.delete_admin(update.effective_chat.id, user.id)
        await s.commit()


def register(app: Application) -> None:
    # Track member updates for any user (promotions/demotions)
    app.add_handler(ChatMemberHandler(on_chat_member))
    # Seed/refresh snapshot when the bot itself is added to a chat
    app.add_handler(ChatMemberHandler(on_my_chat_member, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER))
    # On group messages, ensure group exists and seed admins if new
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, on_group_message), group=1)
    # Track users on any message (private or groups) and on callbacks
    app.add_handler(MessageHandler(~filters.StatusUpdate.ALL, on_any_message), group=0)
    app.add_handler(CallbackQueryHandler(on_any_callback), group=0)


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Seed admins snapshot when the bot is added to a chat.

    When the bot is added (or its status changes in a chat), fetch the current
    administrators and upsert them into the snapshot so /panel can list groups
    immediately without waiting for future promotions/demotions.
    """
    if not update.my_chat_member or not update.effective_chat:
        return

    chat = update.effective_chat
    async with db.SessionLocal() as s:  # type: ignore
        # Ensure the group record exists/updated
        await GroupsRepo(s).upsert_group(
            gid=chat.id,
            title=chat.title or str(chat.id),
            username=chat.username,
            gtype=chat.type,
        )

        admins_repo = GroupAdminsRepo(s)
        try:
            admins = await context.bot.get_chat_administrators(chat.id)
        except Exception as e:
            log.exception("admin_sync get_chat_administrators failed gid=%s: %s", chat.id, e)
            admins = []
        for cm in admins:
            try:
                await admins_repo.upsert_admin(chat.id, cm.user.id, str(cm.status), rights={})
            except Exception as e:
                log.exception("admin_sync upsert_admin failed gid=%s uid=%s: %s", chat.id, cm.user.id, e)
        await s.commit()


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ensure a new group is recorded and admins are seeded on first message."""
    if not update.effective_chat:
        return
    chat = update.effective_chat
    async with db.SessionLocal() as s:  # type: ignore
        from ..infra.models import Group

        exists = await s.get(Group, chat.id)
        if exists is not None:
            return
        await GroupsRepo(s).upsert_group(
            gid=chat.id,
            title=chat.title or str(chat.id),
            username=chat.username,
            gtype=chat.type,
        )
        admins_repo = GroupAdminsRepo(s)
        try:
            admins = await context.bot.get_chat_administrators(chat.id)
        except Exception as e:
            log.exception("admin_sync get_chat_administrators (msg) failed gid=%s: %s", chat.id, e)
            admins = []
        for cm in admins:
            try:
                await admins_repo.upsert_admin(chat.id, cm.user.id, str(cm.status), rights={})
            except Exception as e:
                log.exception("admin_sync upsert_admin (msg) failed gid=%s uid=%s: %s", chat.id, cm.user.id, e)
        await s.commit()


async def on_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Upsert users on any incoming message (private or groups)."""
    if not update.effective_user:
        return
    u = update.effective_user
    async with db.SessionLocal() as s:  # type: ignore
        from ..infra.repos import UsersRepo
        await UsersRepo(s).upsert_user(
            uid=u.id,
            username=getattr(u, "username", None),
            first_name=getattr(u, "first_name", None),
            last_name=getattr(u, "last_name", None),
            language=(u.language_code or None),
        )
        await s.commit()


async def on_any_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Upsert users on any callback query interaction."""
    if not update.effective_user:
        return
    u = update.effective_user
    async with db.SessionLocal() as s:  # type: ignore
        from ..infra.repos import UsersRepo
        await UsersRepo(s).upsert_user(
            uid=u.id,
            username=getattr(u, "username", None),
            first_name=getattr(u, "first_name", None),
            last_name=getattr(u, "last_name", None),
            language=(u.language_code or None),
        )
        await s.commit()
