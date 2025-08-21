from __future__ import annotations

from telegram.ext import Application, CommandHandler

from .handlers import warn, mute, ban, purge, unmute, unban, unwarn


def register(app: Application) -> None:
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("unwarn", unwarn))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("purge", purge))

