from __future__ import annotations

from telegram.ext import Application, CommandHandler

from .handlers import topic_close, topic_open, topic_rename, topic_pin


def register(app: Application) -> None:
    app.add_handler(CommandHandler("topic_close", topic_close))
    app.add_handler(CommandHandler("topic_open", topic_open))
    app.add_handler(CommandHandler("topic_rename", topic_rename))
    app.add_handler(CommandHandler("topic_pin", topic_pin))

