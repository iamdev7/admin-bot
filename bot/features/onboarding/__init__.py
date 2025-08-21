from __future__ import annotations

from telegram.ext import Application, ChatJoinRequestHandler, CommandHandler, CallbackQueryHandler

from .handlers import on_join_request, toggle_auto_approve, on_join_callback


def register(app: Application) -> None:
    app.add_handler(ChatJoinRequestHandler(on_join_request))
    app.add_handler(CommandHandler("joinapprove", toggle_auto_approve))
    app.add_handler(CallbackQueryHandler(on_join_callback, pattern=r"^join:"))
