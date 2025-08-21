from __future__ import annotations

from telegram.ext import Application, CommandHandler

from .handlers import rules, set_rules


def register(app: Application) -> None:
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("setrules", set_rules))
