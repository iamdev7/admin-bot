from __future__ import annotations

from telegram.ext import Application, ChatMemberHandler

from .handlers import on_chat_member


def register(app: Application) -> None:
    app.add_handler(ChatMemberHandler(on_chat_member))

