from __future__ import annotations

from telegram.ext import Application, ChatMemberHandler, CallbackQueryHandler

from .handlers import on_chat_member, on_captcha_callback


def register(app: Application) -> None:
    app.add_handler(ChatMemberHandler(on_chat_member))
    app.add_handler(CallbackQueryHandler(on_captcha_callback, pattern=r"^captcha:"))

