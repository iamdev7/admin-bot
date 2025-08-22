from __future__ import annotations

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from .handlers import open_panel, on_callback, on_input


def register(app: Application) -> None:
    app.add_handler(CommandHandler("bot", open_panel))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^botadm:"))
    # Accept any private non-command message for broadcast/blacklist wizards
    # Use group=-1 to process before admin_panel handlers
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_input), group=-1)

